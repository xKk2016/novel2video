#!/usr/bin/env python3
"""novel_to_video —— 小说章节 -> 剧本 -> 分镜 -> H3 生成 + 截帧接力 -> 成片。

流水线可分段执行、可断点续跑：
  [1] 章节 -> 剧本        (--script-only)
  [2] 剧本 -> 分镜        (--storyboard-only, --shots-limit N)
  [3] 素材检查 / 关键帧   (fl2va 校验关键帧；chain 只校验三视图参考)
  [4] 逐镜生成视频        (已完成镜头自动跳过)
  [5] 配音 + 拼接成片

生成模式 (config.video.mode / --mode)，核心区别是「首尾帧怎么来」：
  chain  —— 主线。只靠「角色设定 + 三视图 + 场景锚」锁人物与环境，首尾帧不预画，逐镜按
            continuity 字段决定接法：
            · continue  = 同场同机位 -> I2V，首帧 = 上一镜视频截取的尾帧（零错位接力）
            · new_angle = 同场换机位 -> 不带首帧重新构图：有主角 -> R2V(三视图锁人)，否则 T2V
            · new_scene = 换场/换景   -> 同上，参考图按新场次取
            （未标注 continuity 时兜底：场首=new_scene，其余=continue）
            场景锚（config.video.scene_anchor）解决「同空间背景各画各的」：同一空间
            （祠堂/走廊/山寨夜景…）的镜头共用一套环境基准。两级生效 —— 文字锚注入所有
            镜头的提示词；mode=i2v 时无主角镜改走「首帧=锚图」的 I2V，有主角镜把锚图并进
            R2V 参考图列表。锚按空间划分（一场可含多空间），写在分镜 anchor 字段里。
  fl2va  —— 兼容旧法：预生成首/尾关键帧 -> H3 首尾帧夹逼
  r2v    —— 全程参考图生视频
  t2v    —— 全程纯文生视频

用法:
  python novel_to_video.py --chapter 章节.txt --script-only
  python novel_to_video.py --chapter 章节.txt --storyboard-only --shots-limit 12
  python novel_to_video.py --storyboard-file output/storyboard_anime.json --mode chain
  python novel_to_video.py --storyboard-file output/storyboard_anime.json --max-shots 2

依赖: .venv (imageio-ffmpeg, python-docx)
"""
import argparse
import json
import os
import re
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import comfyui_client as cc
import llm_client as lc
import assemble as ac
import tts_client as tc
import runner_support as rs


def load_config(path):
    cfg = json.load(open(path, encoding="utf-8"))
    cfg["_base"] = HERE
    v = cfg.get("video", {})
    for key in ("workflow_api", "workflow_api_r2v", "workflow_api_i2v",
                "workflow_api_fl2va"):
        p = v.get(key)
        if p and not os.path.isabs(p):
            v[key] = os.path.join(HERE, p)
    return cfg


def read_chapter(path):
    if path.lower().endswith(".docx"):
        import docx
        d = docx.Document(path)
        return "\n".join(p.text for p in d.paragraphs)
    return open(path, encoding="utf-8").read()


def _abs(p):
    return p if os.path.isabs(p) else os.path.join(HERE, p)


def parse_shot_range(txt):
    """解析镜头区间字符串，返回 (from, to)。

    支持：'5-10'、'20'（20→末）、'8-'（8→末）、'5 10'、'5,10'、'5、10'。
    未指定的一侧为 0（表示不设边界）。无法识别时返回 None。
    放在 python 侧解析，避免 bat 里 findstr/for 在 chcp 65001 下的正则与注入坑。
    """
    import re
    t = str(txt or "").strip()
    if not t:
        return 0, 0
    t = re.sub(r"[,，、\s]+", "-", t)
    if re.fullmatch(r"\d+", t):          # 单个数字：N 表示「第 N 镜到末尾」
        return int(t), 0
    m = re.fullmatch(r"(\d*)-(\d*)", t)
    if not m:
        return None
    a, b = m.group(1), m.group(2)
    if not a and not b:
        return None
    return (int(a) if a else 0), (int(b) if b else 0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--chapter", default="", help="小说章节文件 .txt/.md/.docx")
    ap.add_argument("--script-file", default="", help="复用已有剧本 JSON（跳过章节改写）")
    ap.add_argument("--storyboard-file", default="", help="复用已有分镜 JSON（跳过 LLM）")
    ap.add_argument("--out", default="",
                    help="成片输出路径（默认 <paths.release>/final.mp4）")
    ap.add_argument("--config", default="config.json")
    ap.add_argument("--minutes", type=int, default=5, help="目标成片时长（分钟，用于剧本改写）")
    ap.add_argument("--shots-limit", type=int, default=0,
                    help="生成分镜时最多输出 N 个镜头（0=不限制）")
    ap.add_argument("--script-only", action="store_true", help="只生成剧本后停止")
    ap.add_argument("--storyboard-only", action="store_true", help="生成剧本+分镜后停止")
    ap.add_argument("--max-shots", type=int, default=0,
                    help="本次最多生成前 N 个镜头的视频（0=全部）")
    ap.add_argument("--from-shot", type=int, default=0,
                    help="只跑第 N 镜起（含 N）。与 --to-shot 组合成区间，如 5 10 = 第5~10镜")
    ap.add_argument("--to-shot", type=int, default=0,
                    help="只跑到第 N 镜止（含 N）。0=到最后一镜")
    ap.add_argument("--range", default="",
                    help='区间字符串，如 "5-10" / "20" / "8-"；优先于 --from-shot/--to-shot')
    ap.add_argument("--mode", default="",
                    help="生成模式 chain/fl2va/r2v/t2v（默认取 config.video.mode）")
    ap.add_argument("--keyframes-dir", default="", help="关键帧图目录（默认 <paths.keyframes>）")
    ap.add_argument("--clips-dir", default="", help="片段目录（默认 <paths.clips>）")
    ap.add_argument("--no-tts", action="store_true", help="跳过配音")
    ap.add_argument("--plan-only", action="store_true",
                    help="只打印逐镜生成计划（走哪种模式/首帧来源），不连 ComfyUI、不生成")
    ap.add_argument("--dump-prompts", action="store_true",
                    help="打印每镜最终注入的完整提示词（含风格/服装/外貌/对白）后退出，不连 ComfyUI")
    ap.add_argument("--time-budget", type=float, default=0,
                    help="本次最长运行分钟数；到点后在镜头边界优雅退出（0=不限）")
    ap.add_argument("--retries", type=int, default=2, help="单镜失败重试次数（默认 2）")
    ap.add_argument("--redo-from", type=int, default=0,
                    help="从第 N 镜起强制重跑（含 N），忽略已有产物")
    ap.add_argument("--skip-failed", action="store_true",
                    help="某镜失败后继续跑后面的（默认失败即停，避免链式接力断裂）")
    ap.add_argument("--no-concat", action="store_true",
                    help="即使全部完成也不做配音与拼接")
    ap.add_argument("--dry-run", action="store_true",
                    help="离线演练：不连 ComfyUI、不真生成，用模拟产物走完跳过/留痕/续跑逻辑")
    ap.add_argument("--log-file", default="",
                    help="日志文件（默认 output/logs/run_<时间戳>.log）")
    ap.add_argument("--state-file", default="",
                    help="进度状态文件（默认 output/run_state.json）")
    ap.add_argument("--lock-file", default="",
                    help="单实例锁文件（默认 output/.runner.lock）")
    ap.add_argument("--fresh-state", action="store_true",
                    help="状态表与当前分镜不匹配时，归档旧状态表并从零开始（不覆盖原文件）")
    ap.add_argument("--accept-state", action="store_true",
                    help="状态表与当前分镜不匹配时，无视差异沿用旧完成记录（风险自负）")
    args = ap.parse_args()

    if not (args.chapter or args.script_file or args.storyboard_file):
        ap.error("需要 --chapter / --script-file / --storyboard-file 之一")

    cfg = load_config(os.path.join(HERE, args.config))

    # ---------- 路径分层（2026-10-06 起）----------
    # 资产层（config.paths.*）= 可长期复用的产物，按六环节流水线分目录：
    #     01_script 剧本分镜 / 02_design 定妆资产 / 03_keyframes 关键帧 /
    #     04_clips 片段 / 05_audio 音频 / 06_release 成片
    # 运行时层（config.output_dir，默认 output/）= 只服务于「这一次运行」的东西：
    #     run_state.json / logs / _raw / 锁文件。删掉不影响资产。
    # 未配置 paths 时逐项回退到旧默认值，老配置可直接跑。
    tiers = cfg.get("paths") or {}

    def _tier(key, fallback):
        return _abs(str(tiers.get(key) or fallback))

    out_dir = _abs(cfg.get("output_dir", "output"))
    os.makedirs(out_dir, exist_ok=True)
    release_dir = _tier("release", os.path.join(os.path.dirname(out_dir) or ".", "output"))

    # --dry-run 的全部产物隔离到 output/_dryrun/，绝不写进正式 keyframes/clips/state，
    # 否则假 mp4（带合法 ftyp 头）会被 clip_is_valid 判为有效产物 → 真跑时被误跳过。
    if args.dry_run:
        work_dir = os.path.join(out_dir, "_dryrun")
        kf_dir = os.path.join(work_dir, "keyframes")
        clip_dir = os.path.join(work_dir, "clips")
    else:
        work_dir = out_dir
        kf_dir = _abs(args.keyframes_dir) if args.keyframes_dir \
            else _tier("keyframes", os.path.join(out_dir, "keyframes"))
        clip_dir = _abs(args.clips_dir) if args.clips_dir \
            else _tier("clips", os.path.join(out_dir, "clips"))
    os.makedirs(kf_dir, exist_ok=True)
    os.makedirs(clip_dir, exist_ok=True)
    if args.dry_run:
        print(f"[0/5] 演练模式：产物隔离到 {os.path.relpath(work_dir, HERE)}")
    else:
        print(f"[0/5] 资产分层：关键帧 {os.path.relpath(kf_dir, HERE)}"
              f" | 片段 {os.path.relpath(clip_dir, HERE)}")

    # 环节①的自动产物落点：剧本 JSON 与分镜 JSON 都归到 01_script/
    script_dir = _tier("script", out_dir)
    sb_dir = os.path.join(script_dir, "storyboard")

    # ---------- 运行支撑：日志（控制台+文件双写）/ 进度状态 / 单实例锁 ----------
    log_path = _abs(args.log_file) if args.log_file else \
        os.path.join(out_dir, "logs", f"run_{rs.now_stamp()}.log")
    state_path = _abs(args.state_file) if args.state_file else \
        os.path.join(work_dir, "run_state.json")
    if args.state_file:
        journal_path = os.path.join(os.path.dirname(os.path.abspath(state_path)),
                                    "shots.jsonl")
    elif args.dry_run:
        journal_path = os.path.join(work_dir, "shots.jsonl")
    else:
        journal_path = os.path.join(out_dir, "logs", "shots.jsonl")
    lock_path = _abs(args.lock_file) if args.lock_file else \
        os.path.join(out_dir, ".runner.lock")
    log = rs.RunLogger(log_path)

    # ---------- [1] 章节 -> 剧本 ----------
    script = None
    if args.script_file:
        p = _abs(args.script_file)
        script = json.load(open(p, encoding="utf-8"))
        print(f"[1/5] 复用已有剧本：{p}")
    elif args.storyboard_file:
        print("[1/5] 复用已有分镜，跳过剧本")
    else:
        text = read_chapter(_abs(args.chapter))
        print(f"[1/5] 已读取章节 {len(text)} 字，正在改编为剧本（目标 {args.minutes} 分钟）...")
        script = lc.make_script(text, cfg, minutes=args.minutes)
        os.makedirs(script_dir, exist_ok=True)
        p = os.path.join(script_dir, "script.json")
        json.dump(script, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print(f"      剧本已存：{p} —— 《{script.get('title','')}》"
              f"，{len(script.get('scenes', []))} 场")
    if args.script_only:
        print("（--script-only）已停止。")
        return

    # ---------- [2] 剧本 -> 分镜 ----------
    if args.storyboard_file:
        p = _abs(args.storyboard_file)
        data = json.load(open(p, encoding="utf-8"))
        shots = data.get("shots", []) if isinstance(data, dict) else data
        print(f"[2/5] 复用已有分镜：{p}（{len(shots)} 个镜头）")
    else:
        if script is None:
            script = json.load(open(os.path.join(script_dir, "script.json"), encoding="utf-8"))
        print("[2/5] 正在拆分镜...")
        sb = lc.make_storyboard(script, cfg, max_shots=args.shots_limit)
        shots = sb.get("shots", [])
        if not shots:
            print("ERROR: LLM 未返回有效分镜"); sys.exit(1)
        os.makedirs(sb_dir, exist_ok=True)
        p = os.path.join(sb_dir, "storyboard.json")
        json.dump(shots, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print(f"      分镜已存：{p}（{len(shots)} 个镜头，"
              f"总时长 {sum(s.get('duration', 5) for s in shots)}s）")
    if args.storyboard_only:
        print("（--storyboard-only）已停止。")
        return
    # 全量分镜留一份：拼接时按镜号补齐，避免「分段跑」拼出残缺成片
    all_shots = list(shots)
    if args.max_shots > 0:
        shots = shots[:args.max_shots]
        print(f"      （--max-shots={args.max_shots}，本次只跑前 {len(shots)} 个镜头）")

    # 区间选择：--range 字符串优先，其次 --from-shot / --to-shot，按镜号（index）筛选，含两端
    # 非法区间统一用退出码 4（2 是「已有实例在跑」的锁占用，别混）
    frm, to = int(args.from_shot or 0), int(args.to_shot or 0)
    if str(args.range or "").strip():
        parsed = parse_shot_range(args.range)
        if parsed is None:
            print(f'ERROR: --range 无法识别："{args.range}"（示例 5-10 / 20 / 8-）')
            sys.exit(4)
        frm, to = parsed
    if frm or to:
        if frm and to and frm > to:
            print(f"ERROR: 区间非法：起始镜 {frm} 大于结束镜 {to}。")
            sys.exit(4)
        _idx = lambda i, s: int(s.get("index", i + 1))
        shots = [s for i, s in enumerate(shots)
                 if (not frm or _idx(i, s) >= frm) and (not to or _idx(i, s) <= to)]
        if not shots:
            print(f"ERROR: 区间 {frm or 1}~{to or '末'} 内没有镜头，请核对镜号。")
            sys.exit(4)
        print(f"      （区间 {frm or 1}~{to or '末'}：本次只跑 {len(shots)} 镜，"
              f"镜号 {shots[0].get('index')}~{shots[-1].get('index')}）")

    # ---------- [3] 素材检查 ----------
    vcfg = cfg["video"]
    mode = (args.mode or vcfg.get("mode", "chain")).lower()
    ref_imgs = [_abs(p) for p in vcfg.get("ref_images", [])]
    # 按场次覆盖参考图：键=scene_no 字符串（如 {"1":[成年版...], "2":[少年版...]}）
    ref_map = {str(k): [_abs(p) for p in v]
               for k, v in (vcfg.get("ref_images_by_scene") or {}).items()}
    # 道具图（铁律三「场景图 → 道具图 → 人物定妆图」的中间层）：
    # assets/02_design/props/<道具>.png。默认空，配置后自动插到人物图之前。
    props_default = [_abs(p) for p in vcfg.get("props", [])]
    props_map = {str(k): [_abs(p) for p in v]
                 for k, v in (vcfg.get("props_by_scene") or {}).items()}

    prot_kw = [str(k).lower() for k in
               vcfg.get("protagonist_keywords", ["long straight black hair"])]

    def _refs_for(s):
        """取该镜所属场次的三视图；未配置则回退默认 ref_images。

        分镜可用 ref 字段收窄参考图（**这是背影镜不出正脸的机制前提**）：
          · `back` —— 只给背面全身图。背影/过肩镜若连同正面图一起喂，模型会照着
            正面图在画面正中另画一张正脸（2026-10-06 抽帧实测：过肩镜三人同框）。
          · `face` —— 只给面部特写图（极端特写镜）。
          · 其余   —— 全部三视图。
        收窄后若一张都匹配不到，回退全量，避免因命名不符把参考图喂空。
        """
        base = list(ref_map.get(str(s.get("scene_no")), ref_imgs))
        want = str(s.get("ref") or "").strip().lower()
        if want in ("back", "face"):
            hit = [p for p in base if f"_{want}." in p]
            return hit or base
        return base

    def _props_for(s):
        """该镜要挂的道具定妆图（铁律三的中间层）。

        收窄语义与 `_refs_for` 一致：分镜 `props` 字段 > `props_by_scene[场次]`
        > 顶层 `props`。分镜可给单个名字或名字列表；一张都匹配不到时回退全量，
        避免因命名不符把道具图喂空。
        """
        base = list(props_map.get(str(s.get("scene_no")), props_default))
        want = s.get("props")
        if want:
            names = [want] if isinstance(want, str) else list(want)
            keys = [str(w).strip().lower() for w in names if str(w).strip()]
            hits = [p for p in base
                    if any(k in os.path.basename(p).lower() for k in keys)]
            return hits or base
        return base

    def _uses_protagonist(s):
        # 显式标注优先：关键词匹配太脆（如镜1 的 video_prompt 只写 "his long hair"，
        # 不含 "long straight black hair"，会漏判导致服装/外貌串不注入）。分镜若有
        # protagonist 字段，以它为准；否则回退关键词。
        if "protagonist" in s:
            return bool(s.get("protagonist"))
        blob = " ".join(str(s.get(k, "")) for k in
                        ("first_frame_prompt", "last_frame_prompt",
                         "video_prompt", "scene")).lower()
        return any(k in blob for k in prot_kw)

    # 风格兜底：T2V（无图可依）必须靠文字钉住画风，否则整段场戏跟着跑偏。
    style_prefix = vcfg.get("style_prefix", "").strip()
    style_markers = [str(k).lower() for k in vcfg.get("style_markers", [])]
    # 反 3D 短语：H3 走 BasicGuider + cfg=1，没有 uncond 分支 = 没有 negative prompt
    # 通道，"不要 3D"只能写成正向描述。可一键关闭（见 config.comment_style_negatives）。
    style_neg = str(vcfg.get("style_negatives") or "").strip()
    if not bool(vcfg.get("style_negatives_enabled", True)):
        style_neg = ""
    style_full = f"{style_prefix}, {style_neg}" if (style_prefix and style_neg) else style_prefix

    def _strip_legacy_style(text):
        """剥掉分镜提示词开头自带的短风格句。

        ⚠️ 这是 2026-10-06 画风分叉的根因之一：分镜的 video_prompt 大都会以
        一句短风格串开头（如 "Chinese donghua 2D cel-shaded anime style."），
        它含 style_markers → 老的 _with_style 幂等判定误命中 → **config 里的完整
        风格串（40+ 词）从不注入**，全片画风锁只剩 9 个单词。
        实测：镜1（I2V，首帧图锁风格）出 2D，镜2（R2V，风格全看文字）直接掉进
        模型默认先验出 3D CG。

        策略：开头第一句若「短（≤90 字符）+ 不含句号外的镜头描述 + 命中风格标记」
        则视为遗留风格句剥掉，风格统一由 style_prefix 承担。幂等：不匹配就原样返回。
        """
        t = str(text or "").strip()
        if not t or not style_markers:
            return t
        m = re.match(r"^([^.\n]{1,90}\.)\s*", t)
        if not m:
            return t
        if any(k in m.group(1).lower() for k in style_markers):
            return t[m.end():].strip()
        return t

    # 视角 → 职责。三条铁律之二「有图不写外观」的落地：挂了参考图就不再在
    # prompt 里复述外貌，改为在这里逐张声明「这张图管什么」，让模型按图取值。
    _VIEW_DUTY = {
        "back": ("the character reference seen from behind, locking the "
                 "protagonist's hairstyle, costume and body proportions "
                 "only, not his pose or his framing"),
        "face": ("the character reference for the protagonist's face, "
                 "locking facial identity and features only"),
        "front": ("the character reference for the protagonist, locking his "
                  "identity, hairstyle, costume and body proportions only"),
        "side": ("the character reference for the protagonist, locking his "
                 "identity, hairstyle, costume and body proportions only"),
    }
    _DUTY_LOCATION = ("the location reference, locking the spatial layout, "
                      "architecture, materials and lighting only")
    _DUTY_PROP = ("the prop reference, locking the object's shape, material "
                  "and scale only")
    _DUTY_UNKNOWN = "a supporting reference"

    def _ref_binding_sentence(refs):
        """按 H3 规范生成参考图绑定句（逐张声明职责）。

        ⚠️ 官方说明：`<Picture i> / <Video k> / <Audio j> reference conditioning
        for MiniMax H3. **Use the same tags when prompting.**` —— 不在 prompt 里
        点名，参考图只是隐式对齐，模型分不清哪张是角色、哪张是场景。

        职责识别**优先按资产分层目录**（2026-10-06 分层后）：
            assets/02_design/characters/<角色>/<视角>.png → 角色参考
            assets/02_design/scenes/<空间>.png            → 场景参考
            assets/02_design/props/<道具>.png             → 道具参考
        再回退旧命名（`*_back.png` / `*_front.png` / `*anchor_*.png`），
        保证老资产目录也能识别。

        ⚠️ **改名即失效**：若输出里出现 `_DUTY_UNKNOWN`（"a supporting
        reference"），说明有参考图的路径既不在分层目录、也不符合旧命名 ——
        绑定句会退化成无效声明。`--dump-prompts` 后 grep 这个词即可自查。
        """
        if not refs:
            return ""
        parts = []
        for k, p in enumerate(refs, 1):
            raw = str(p).replace("\\", "/").lower()
            name = os.path.basename(raw)
            stem = os.path.splitext(name)[0]
            if "/characters/" in raw:
                duty = _VIEW_DUTY.get(stem, _VIEW_DUTY["front"])
            elif "/scenes/" in raw:
                duty = _DUTY_LOCATION
            elif "/props/" in raw:
                duty = _DUTY_PROP
            elif name.startswith("back.") or "_back." in name:
                duty = _VIEW_DUTY["back"]
            elif name.startswith("face.") or "_face." in name:
                duty = _VIEW_DUTY["face"]
            elif "_front." in name or "_side." in name:
                duty = _VIEW_DUTY["front"]
            elif "anchor" in name:
                duty = _DUTY_LOCATION
            else:
                duty = _DUTY_UNKNOWN
            parts.append(f"<Picture {k}> is {duty}.")
        return " ".join(parts)

    def _with_style(text, refs=None):
        """确保提示词带**完整**风格串（含反 3D 短语）；R2V 镜另插参考图绑定句。

        2026-10-06 修复：老实现「检测到风格标记就跳过前置」过于宽松 —— 分镜自带的
        短风格句也会命中，导致完整风格串永不生效。现改为：先剥除遗留短风格句，
        再判断文本是否已以完整串开头（真幂等）。
        """
        t = str(text or "").strip()
        if not style_full or not t:
            return t
        # 幂等判定放在剥除之前：文本已以完整风格串开头就直接返回。
        # （顺序很重要 —— 若先剥再判，含 style_markers 的完整串本身可能被 _strip_legacy_style 误剥。）
        if t.lower().startswith(style_prefix.lower()):
            return t
        t = _strip_legacy_style(t)
        bind = _ref_binding_sentence(refs)
        mid = f"{bind} " if bind else ""
        return f"{style_full}, {mid}{t}"

    # 场景锚（空间锚）：同一空间的镜头必须共用一套环境基准，否则无主角的空镜各画各的，
    # 同场空间感漂移（祠堂/走廊这类纯空镜场次尤其明显）。
    # 锚按「空间」而不是按场次划分 —— 一场戏可能横跨多个空间（场2 = 山寨夜景 + 祠堂 + 走廊）。
    # 两级生效：
    #   ①文字锚 —— 锚的 prompt 注入该镜最终提示词（所有模式都生效，零成本）
    #   ②图锚   —— mode=i2v 时：无主角镜改走「首帧 = 锚图」的 I2V（背景铁定同源，机位/主体
    #                仍由 prompt 驱动而变）；有主角镜把锚图追加进 R2V 参考图列表
    #                （人物锁三视图 + 环境锁锚图）
    # 优先级：分镜单镜 anchor 字段 > by_scene[场次] > 无锚（保持原行为）。
    anc_cfg = vcfg.get("scene_anchor") or {}
    anc_on = bool(anc_cfg.get("enabled", False))
    anc_mode = str(anc_cfg.get("mode", "i2v")).lower()
    anc_defs = {str(k): v for k, v in (anc_cfg.get("anchors") or {}).items()}
    anc_by_scene = {str(k): str(v).strip()
                    for k, v in (anc_cfg.get("by_scene") or {}).items()}

    def _anchor_id_for(s):
        """该镜的锚 ID（空串=无锚）。"""
        if not anc_on:
            return ""
        return (str(s.get("anchor") or "").strip()
                or anc_by_scene.get(str(s.get("scene_no")), ""))

    def _anchor_for(s):
        """该镜的锚定义 dict（无锚返回 None）。"""
        aid = _anchor_id_for(s)
        if not aid:
            return None
        return anc_defs.get(aid)

    def _anchor_img_for(s):
        """该镜可用的锚图绝对路径；未启用图锚 / 未配图 / 文件不存在 → ""（退回原模式）。"""
        if anc_mode != "i2v":
            return ""
        a = _anchor_for(s)
        if not a:
            return ""
        img = str(a.get("image") or "").strip()
        if not img:
            return ""
        p = _abs(img)
        return p if os.path.exists(p) else ""

    def _anchor_img_ok(aid):
        """锚图是否就位：未配图（纯文字锚）也算就位，只有配了图却找不到文件才算不就位。"""
        a = anc_defs.get(str(aid)) or {}
        img = str(a.get("image") or "").strip()
        return (not img) or os.path.exists(_abs(img))

    def _append_clause(t, add):
        """把 add 拼到 t 尾部，按 t 的结尾标点选分隔符。

        ⚠️ 2026-10-06：旧的死板拼接会产生 `...pushes in slowly toward him., on the flat
        rocky summit...`（句号后又来逗号）与 `...drift in the air the encircling crowd
        keeps...`（两个分句直接粘死）。文字锚一恢复生效，这些瑕疵就全部暴露在提示词里，
        会让模型读串语境（分句边界丢失 = 环境描述被当成动作描述）。
        """
        t = str(t or "").strip()
        add = str(add or "").strip()
        if not t:
            return add
        if not add:
            return t
        if t.endswith((".", "!", "?", "。", "！", "？", ",", "，", "、", ";", "；")):
            return f"{t} {add}"
        return f"{t}, {add}"

    def _with_anchor(text, s):
        """把场景锚的环境串追加到提示词尾部（幂等）。对白最后由 _with_dialogue 追加。

        分镜可显式声明 `anchor_text: false`（该镜提示词自带完整环境与光线），
        此时跳过文字锚、只保留图锚 —— 避免同一环境在一句里被描述两遍。

        ⚠️ 2026-10-06 场景漂移修复：`anchor_mode == "prompt"` 的镜走 T2V，**没有首帧
        图**，文字锚是它**唯一**的场景约束。实测场1 有 7 个这样的镜，video_prompt
        里一个环境词都没有（summit/rock/dusk/sky 全为 0），而 anchor_text=false 又把
        文字锚一并关掉 —— 模型凭空发挥，直接把同一座山巅画成了室内。
        故：T2V 镜强制注入文字锚，忽略 anchor_text 开关；有首帧图的镜照旧跳过。
        """
        t = str(text or "").strip()
        amode = str(s.get("anchor_mode") or "").strip().lower()
        cont = str(s.get("continuity") or "").strip().lower()
        # 「首帧就是这张锚图」的镜 = 无主角 + 非 prompt 模式 + 非接力。
        # **只有这种镜才允许跳过文字锚**（图已经把环境钉死了），其余一律注入：
        #   · T2V（anchor_mode=prompt）—— 根本没有首帧图，文字锚是唯一场景约束
        #   · R2V 换位 —— 锚图只是 5 张参考图里的 1 张，H3 走 cfg=1 服从度弱，
        #     实测镜9/镜11 照样把山巅漂成城池宫殿 + 广场人群
        #   · I2V 接力 —— 首帧是上一镜尾帧，漂移会被整条链继承下来
        anchor_is_first_frame = ((amode != "prompt")
                                 and (not _uses_protagonist(s))
                                 and (cont != "continue"))
        # ⚠️ 2026-10-06 逻辑修正：原写 `and not anchor_is_first_frame`，**条件写反了** ——
        # 结果是「除首帧锚镜外全部跳过文字锚」，与上方注释和 skill 声明完全相反。
        # 实测代价：场4 fangyuan_room 8 镜 / 场3 window_view 2 镜（均有主角，走 R2V）
        # 文字锚命中 **0 次**；corridor 23 镜里只命中 1 次（唯一那个首帧锚镜）。
        # 现改为「只有首帧就是锚图的镜才跳过」。
        if s.get("anchor_text") is False and anchor_is_first_frame:
            return t
        a = _anchor_for(s)
        if not a or not t:
            return t
        ap = str(a.get("prompt") or "").strip()
        if not ap or ap.lower() in t.lower():
            return t
        return _append_clause(t, ap)

    # 群雄距离锁：重生前（场1）正道群雄「环伺」但**无人敢靠近** —— 原文
    # 「他们没有动手，都忌惮着方源的临死反扑」「群雄顿时一阵骚动，齐齐后退一大步」。
    # 分镜里却写了「探身出圈 / 跨步向前 / 长杖刺出」这类位移，模型照做，画面就变成
    # 贴身叫骂甚至肢体接触。H3 无 negative 通道，只能按场次补一条**正向**距离约束。
    dist_cfg = vcfg.get("distance_lock") or {}
    dist_on = bool(dist_cfg.get("enabled", False))
    dist_by_scene = {str(k): str(v).strip()
                     for k, v in (dist_cfg.get("by_scene") or {}).items()}

    def _with_distance(text, s):
        """把该场的「保持距离」约束追加到提示词尾部（幂等）。

        单镜可显式关闭：分镜写 `distance_lock: false` 时跳过本场距离锁。
        ⚠️ 2026-10-06 新增：镜20「群雄逼迫而来」的语义就是**压上来**（原文「群雄逼迫
        而来，恰在这时…自爆」），而场1 距离锁写的是「无人敢靠近」。两者直接冲突 ——
        不关掉的话镜20 的最终 prompt 会同时出现「逼到血泊边缘」与「no one closes in」，
        模型必按权重高的那份演。距离锁本来只服务镜1–19 的「环伺但忌惮」段。
        """
        t = str(text or "").strip()
        if not dist_on or not t:
            return t
        if s.get("distance_lock") is False:
            return t
        d = dist_by_scene.get(str(s.get("scene_no")), "")
        if not d or d.lower() in t.lower():
            return t
        return _append_clause(t, d)

    def _refs_with_anchor(s):
        """R2V 参考图 = 本场的场景图 + 道具图 + 人物定妆图（合计 ≤9 张）。

        **挂载顺序是三条铁律之三：场景图 → 道具图 → 人物定妆图。**
        顺序直接决定 prompt 里 `<Picture N>` 的编号，所以不是审美问题 ——
        改顺序会让已生成的片段与新编号对不上，必须重跑。

        由 `video.ref_order` 控制（默认 `scene_first` = 铁律顺序）：
          · `scene_first`      —— 场景锚 → 道具 → 三视图（推荐，与行业惯例一致）
          · `character_first`  —— 三视图 → 场景锚（2026-10-06 之前的旧顺序，留作回退）
        道具图暂未启用（`props/` 为空），一旦配置即自动插到人物图之前。
        """
        chars = list(_refs_for(s))
        scene_img = _anchor_img_for(s)
        prop_imgs = [p for p in _props_for(s) if p not in chars]

        scene_block = ([scene_img] if scene_img else []) + prop_imgs
        if str(vcfg.get("ref_order", "scene_first")).lower() == "character_first":
            ordered = chars + scene_block
        else:
            ordered = scene_block + chars

        # 去重（保序）并压到 H3 的 9 张上限内
        out, seen = [], set()
        for p in ordered:
            if p and p not in seen:
                seen.add(p)
                out.append(p)
        return out[:9]

    # 服装锁：实测 R2V 参考图锁不住服装颜色/款式（首跑出白衣事故），
    # 场首镜必须靠文字把服装钉死；同场后续镜是 I2V 接力，会继承场首颜色。
    # 可配置 —— 优先级：镜头级 s["costume"] > by_scene[场次] > by_episode[集] > default。
    costume_cfg = vcfg.get("costume") or {}
    costume_on = bool(costume_cfg.get("enabled", False))
    costume_default = str(costume_cfg.get("default") or "").strip()
    costume_by_scene = {str(k): str(v).strip()
                        for k, v in (costume_cfg.get("by_scene") or {}).items()}
    costume_by_ep = {str(k): str(v).strip()
                     for k, v in (costume_cfg.get("by_episode") or {}).items()}
    cur_ep = str(vcfg.get("episode", "") or "")
    costume_apply = str(costume_cfg.get("apply_to", "protagonist")).lower()

    def _costume_for(s):
        """取该镜适用的服装串（空串=不注入）。"""
        if not costume_on:
            return ""
        return (str(s.get("costume") or "").strip()
                or costume_by_scene.get(str(s.get("scene_no")), "")
                or costume_by_ep.get(cur_ep, "")
                or costume_default)

    def _with_costume(text, s):
        """把服装串追加到提示词尾部；已含则不重复（幂等）。
        apply_to=protagonist（默认）时仅对含主角关键词的镜头生效。"""
        c = _costume_for(s)
        t = str(text or "").strip()
        if not c or not t:
            return t
        if costume_apply == "protagonist" and not _uses_protagonist(s):
            return t
        if c.lower() in t.lower():
            return t
        return _append_clause(t, c)

    # 外貌锁：实测仅三视图参考，人物脸型/眼型/神情/发型细节易跑偏，运行期用文字钉死。
    # 可配置 —— 优先级：镜头级 s["appearance"] > by_scene[场次] > by_episode[集] > default。
    char_cfg = vcfg.get("character") or {}
    char_on = bool(char_cfg.get("enabled", False))
    char_default = str(char_cfg.get("default") or "").strip()
    char_by_scene = {str(k): str(v).strip()
                     for k, v in (char_cfg.get("by_scene") or {}).items()}
    char_by_ep = {str(k): str(v).strip()
                  for k, v in (char_cfg.get("by_episode") or {}).items()}
    char_apply = str(char_cfg.get("apply_to", "protagonist")).lower()

    def _character_for(s):
        """取该镜适用的外貌串（空串=不注入）。"""
        if not char_on:
            return ""
        return (str(s.get("appearance") or "").strip()
                or char_by_scene.get(str(s.get("scene_no")), "")
                or char_by_ep.get(cur_ep, "")
                or char_default)

    def _with_character(text, s):
        """把外貌串追加到提示词尾部；已含则不重复（幂等）。
        apply_to=protagonist（默认）时仅对主角镜生效。"""
        c = _character_for(s)
        t = str(text or "").strip()
        if not c or not t:
            return t
        if char_apply == "protagonist" and not _uses_protagonist(s):
            return t
        if c.lower() in t.lower():
            return t
        return _append_clause(t, c)

    # H3 原生对白：把 line 转成 H3 的 <d>[语言] 台词</d> 语法连同说话人一起注入 prompt，
    # 由 H3 在生成视频时一并产出人声（替代 edge-tts 后期混音）。启用后应关闭 tts。
    dlg_cfg = vcfg.get("dialogue") or {}
    dlg_on = bool(dlg_cfg.get("enabled", False))
    dlg_lang = str(dlg_cfg.get("language") or "Chinese")
    dlg_spk = str(dlg_cfg.get("default_speaker") or "A character with a clear voice")
    dlg_mode = str(dlg_cfg.get("default_speech_mode") or "on-screen")
    dlg_verb = str(dlg_cfg.get("default_speech_verb") or "shouts")
    # 说话人 → 稳定 ID：修「所有台词都被标成同一个 S1」导致的多角色串音/串脸。
    # 同一个人物全片共用一个 ID（方源=S1、旁白=S2…）；编号按首次出现顺序自动生成，
    # 也可用 dialogue.speaker_ids 显式钉死（如 {"方源":"S1"}）。
    dlg_ids_cfg = {str(k): str(v) for k, v in (dlg_cfg.get("speaker_ids") or {}).items()}
    spk_registry = {}                       # speaker_key -> "S1"/"S2"…
    _spk_used = set(dlg_ids_cfg.values())

    def _speaker_key(s):
        """该镜说话人标识：优先分镜显式 speaker_key，否则退回 speaker 描述文本
        （同一段描述视为同一人）。自动编号就是按它去重的。"""
        return (str(s.get("speaker_key") or "").strip()
                or str(s.get("speaker") or "").strip())

    def _build_speaker_registry():
        """按镜头顺序给每个说话人分配稳定 ID（先到先得，跳过已占用的编号）。"""
        n = 1
        for s in shots:
            if not str(s.get("line") or "").strip():
                continue
            key = _speaker_key(s)
            if not key or key in spk_registry:
                continue
            if key in dlg_ids_cfg:
                spk_registry[key] = dlg_ids_cfg[key]
                continue
            while f"S{n}" in _spk_used:
                n += 1
            spk_registry[key] = f"S{n}"
            _spk_used.add(f"S{n}")
            n += 1

    def _speaker_tag_for(s):
        return spk_registry.get(_speaker_key(s), "S1")

    def _with_dialogue(text, s):
        """有台词则追加 H3 对白描述；无台词原样返回（幂等）。

        两种句式严格分开（对齐 H3 官方 spec）：
          · 画内对白：`{说话人} (S1) shouts: <d>[Chinese] 台词</d>`
          · 画外旁白：`{说话人} (S2) says in an off-screen voiceover: <d>[Chinese] 台词</d>
                       while all on-screen characters' lips remain completely closed.`
        旁白不写明「嘴唇闭合」时，模型会自己给画内角色配上口型甚至换语言。
        """
        t = str(text or "").strip()
        if not dlg_on or not t:
            return t
        line = str(s.get("line") or "").strip()
        if not line:
            # ⚠️ 2026-10-06 修复：无台词镜必须**显式声明无人声**。
            # 语言本来只靠 `<d>[Chinese] …</d>` 钉住；镜12 是动作镜、line 为空，
            # 一条语言指令都没有，H3 原生音轨自由发挥，生成了非中文人声。
            # 前 20 镜里镜1/9/11/12 都属此类。
            guard = ("This shot has no spoken dialogue and no human voices: "
                     "ambient sound and sound effects only.")
            return t if guard in t else _append_clause(t, guard)
        if f"<d>[{dlg_lang}]" in t and line in t:
            return t  # 已注入
        spk = str(s.get("speaker") or dlg_spk).strip()
        mode = str(s.get("speech_mode") or dlg_mode).strip()
        verb = str(s.get("speech_verb") or dlg_verb).strip()
        tag = _speaker_tag_for(s)
        head = t if t.endswith((".", "!", "?", "。", "！", "？")) else t + "."
        if mode.lower().startswith("off"):
            return (f"{head} {spk} ({tag}) says in an off-screen voiceover: "
                    f"<d>[{dlg_lang}] {line}</d> "
                    f"while all on-screen characters' lips remain completely closed.")
        return f"{head} {spk} ({tag}) {verb}: <d>[{dlg_lang}] {line}</d>"

    if dlg_on:
        _build_speaker_registry()

    if mode == "fl2va":
        print(f"[3/5] 检查关键帧图：{kf_dir}")
        missing = []
        for i, s in enumerate(shots):
            n = s.get("index", i + 1)
            prev = shots[i - 1] if i > 0 else None
            cross = (prev is None) or (s.get("scene_no") != prev.get("scene_no"))
            if cross and not os.path.exists(os.path.join(kf_dir, f"shot_{n:03d}_first.png")):
                missing.append(f"shot_{n:03d}_first.png  ← 跨场镜头的起始帧")
            if not os.path.exists(os.path.join(kf_dir, f"shot_{n:03d}_last.png")):
                missing.append(f"shot_{n:03d}_last.png  ← 该镜头尾帧")
        if missing:
            print("ERROR: 缺少关键帧图，请先出图后重跑：")
            for m in missing:
                print("   -", m)
            sys.exit(1)
        print(f"      关键帧齐全（{len(shots)} 镜）。")
    else:
        # chain / r2v / t2v：不再预生成关键帧，只校验三视图参考图
        all_sets = {"默认": ref_imgs}
        all_sets.update({f"场{k}": v for k, v in ref_map.items()})
        for label, paths in all_sets.items():
            gone = [p for p in paths if not os.path.exists(p)]
            if gone:
                print(f"WARN: {label}参考图缺失，将在运行期跳过：")
                for m in gone:
                    print("   -", m)
        ref_imgs = [p for p in ref_imgs if os.path.exists(p)]
        ref_map = {k: [p for p in v if os.path.exists(p)] for k, v in ref_map.items()}
        scene_brief = "、".join(f"场{k}→{len(v)}图" for k, v in ref_map.items()) or "无"
        print(f"[3/5] 模式={mode}：无需预生成关键帧；三视图 默认 {len(ref_imgs)} 张；"
              f"按场覆盖：{scene_brief}")
        # 场景锚：核对锚定义是否齐全、锚图是否就位（缺图不致命，只是该镜退回 T2V，文字锚照常生效）
        if anc_on:
            used_ids = []
            for s in shots:
                aid = _anchor_id_for(s)
                if aid and aid not in used_ids:
                    used_ids.append(aid)
            bad = []
            for aid in used_ids:
                a = anc_defs.get(aid)
                if not a:
                    bad.append(f"{aid}（锚未在 config 中定义）")
                    continue
                img = str(a.get("image") or "").strip()
                if anc_mode == "i2v" and img and not os.path.exists(_abs(img)):
                    bad.append(f"{aid} → {img}")
            ok_img = [i for i in used_ids if _anchor_img_ok(i)]
            if anc_mode == "i2v":
                print(f"      场景锚：mode=i2v，本片用到 {len(used_ids)} 个空间锚"
                      f"（{', '.join(used_ids) if used_ids else '无'}）；"
                      f"锚图就位 {len(ok_img)}/{len(used_ids)}")
            else:
                print(f"      场景锚：mode={anc_mode}（仅文字锚，不改生成模式）；"
                      f"本片用到 {len(used_ids)} 个空间锚")
            if bad:
                print("      WARN: 以下锚缺图/未定义，对应镜头退回 T2V（文字锚仍生效）：")
                for m in bad:
                    print("         -", m)

    # ---------- 工作流注入点 ----------
    wf_i2v = vcfg.get("workflow_api_i2v") or vcfg.get("workflow_api_fl2va")
    wf_fl2va = vcfg.get("workflow_api_fl2va") or wf_i2v
    wf_r2v = vcfg.get("workflow_api_r2v")
    wf_t2v = vcfg.get("workflow_api")
    i_p = vcfg.get("i2v_prompt_input", ["6", "prompt"])
    i_f = vcfg.get("i2v_first_frame_input", ["20", "image"])
    fp_p = vcfg.get("fl2va_prompt_input", ["6", "prompt"])
    fp_f = vcfg.get("first_frame_input", ["20", "image"])
    fp_l = vcfg.get("last_frame_input", ["21", "image"])
    r_p = vcfg.get("r2v_prompt_input", ["5", "prompt"])
    r_r = vcfg.get("ref_images_input", ["5", "ref_images"])
    t_p = vcfg.get("prompt_input", ["6", "prompt"])
    raw_dir = os.path.join(work_dir, "_raw")

    # ---------- 逐镜计划表（日志 / --plan-only / 实际执行 三者同规则）----------
    def _plan_for(i, s):
        """返回 (模式标签, 首帧来源说明, 参考图列表, continuity, 锚图路径)。"""
        prev = shots[i - 1] if i > 0 else None
        scene_start = (prev is None) or (s.get("scene_no") != prev.get("scene_no"))
        # 镜头衔接：分镜 continuity 显式标注优先 ——
        #   continue  = 同场同机位，接上一镜尾帧（I2V 零错位）
        #   new_angle = 同场换机位，重新构图（不带首帧）
        #   new_scene = 换场/换景，重锚
        # 缺省兜底：场首=new_scene，其余=continue（兼容未标注 continuity 的旧分镜）。
        cont = str(s.get("continuity") or "").strip().lower()
        if cont not in ("continue", "new_angle", "new_scene"):
            cont = "new_scene" if scene_start else "continue"
        # 人工关键帧覆盖（方案 B）：output/keyframes/shot_NNN.png 存在时，本镜强制走 I2V 首帧，
        # 优先级最高（压过接力 / 换位 / 锚定）。脸的相似度与画风由关键帧 100% 决定，不再指望
        # R2V 的参考图条件 —— 镜13 实测：5 张参考图挂满、外貌串写全，出图仍是模型的通用脸。
        # 关键帧由 ImageGen 出图（1 分钟 / 5-10 credits），可以反复重出到脸满意，再交给 H3 动起来。
        kf_now = os.path.join(kf_dir, f"shot_{s.get('index', i+1):03d}.png")
        if mode != "fl2va" and os.path.exists(kf_now):
            return ("I2V 关键帧",
                    f"人工关键帧 shot_{s.get('index', i+1):03d}.png",
                    [], "keyframe", kf_now)
        if mode == "fl2va":
            if scene_start:
                return ("FL2VA 首尾帧",
                        f"关键帧 shot_{s.get('index', i+1):03d}_first.png", [], cont, "")
            return ("FL2VA 接力",
                    f"shot_{prev.get('index', i):03d}.mp4 尾帧", [], cont, "")
        # 只有「真衔接」才接上一镜尾帧；换机位/换景一律重新构图，
        # 否则会把独立机位的镜头硬接成一条几乎不变的长镜头（老问题根因）。
        if cont == "continue" and prev is not None and not scene_start:
            return ("I2V 接力", f"shot_{prev.get('index', i):03d}.mp4 尾帧", [], cont, "")
        refs = _refs_with_anchor(s)
        if refs and _uses_protagonist(s):
            tag = "R2V 重锚" if cont == "new_scene" else "R2V 换位"
            return (tag, "-", refs, cont, "")
        # 无主角：若该空间有锚图 → 以锚图为首帧重新构图（背景铁定同源，机位/主体仍按 prompt 变）。
        # 例外 —— 人物镜（分镜标 anchor_mode="prompt"）：空景锚图当首帧，模型只能在空场景上
        # 凭空长出一张脸，人脸/神态必然崩。这类镜改用文字锚 + T2V 重新构图。
        amode = str(s.get("anchor_mode") or "").strip().lower()
        aimg = _anchor_img_for(s)
        if aimg and amode != "prompt":
            return ("I2V 锚定", f"锚图 {os.path.basename(aimg)}", [], cont, aimg)
        if amode == "prompt":
            tag = "T2V 人物镜" if cont == "new_scene" else "T2V 换位"
        else:
            tag = "T2V 空镜" if cont == "new_scene" else "T2V 换位"
        return (tag, "-", [], cont, "")

    def _audio_track(s):
        """生成 H3 的 `overall_soundscape` 字段内容（环境音 + 动作音效 + 非语言人声）。

        ⚠️ **官方结构是硬要求**（ComfyUI/MiniMax H3 提示词指南）：提示词必须写成三个
        固定字段，模型靠字段名区分「画面」与「音频」：

            integrated_multimodal_description: [Shot 1] …（画面/动作/对白）
            overall_soundscape: …（1-4 句：环境音、动作音效、非语言人声）
            non_diegetic_music: …（1-3 句：只有观众能听到的配乐；没有就 N/A）

        2026-10-06 实测代价：项目此前用自创的 `Ambient sound: … SFX: …` 平铺在末尾，
        **三个字段名一个都没有** → 模型分不清哪段文本该当音频处理，表现为
        「安静镜头里冒出没有要求的人声/噪声」。官方原话就是这条症状的解法：
        *安静的镜头返回了你没有要求的人声时，就把这两个字段都明确写出来并重新生成。*
        """
        aud = str(s.get("audio_prompt") or "").strip()
        if not aud:
            return str(vcfg.get("soundscape_default") or "N/A")
        # 字段名已承担「这是音频」的语义，剥掉自创前缀
        aud = re.sub(r"^\s*Ambient sound\s*[:：]\s*", "", aud, flags=re.I)
        aud = re.sub(r"\s*SFX\s*[:：]\s*", " ", aud, flags=re.I)
        return aud.strip()

    def _build_prompt(s, refs=None):
        """该镜最终提示词 —— **按 H3 官方三段式结构**输出：

            integrated_multimodal_description: 风格(+参考图绑定) → 场景锚 → 距离锁
                                                → 服装 → 外貌 → 对白(<d> 标签)
            overall_soundscape:                环境音 / 动作音效 / 非语言人声
            non_diegetic_music:                观众专属配乐（无则 N/A）

        refs：该镜实际挂载的参考图列表（plan 已算好）。非空时会在风格串后插入
        `<Picture N>` 绑定句 —— 本地 H3 节点要求 prompt 用同款标签点名参考图。
        """
        base = (s.get("video_prompt") or s.get("first_frame_prompt")
                or s.get("scene", ""))
        t = _with_style(base, refs)
        t = _with_anchor(t, s)
        t = _with_distance(t, s)

        # ── 铁律二「有图不写外观」────────────────────────────────────
        # 本镜挂了**人物**参考图时，外貌/服装应由图承担，文字不再复述 ——
        # 「文字和图一打架，人就会变样」。
        # 但本项目有历史教训：参考图绑定句曾退化成 "a supporting reference"
        # （路径改名导致），图等于没点名，模型直接忽略 → 出过「黑袍写成白袍」
        # 「通用脸」。绑定句修复后参考图才真正开始起作用。
        # 故此项默认 `text`（保留文字锁，即 2026-10-06 之前的行为），
        # 待 A/B 验证参考图确实锁得住之后，再切 `skip` 执行铁律二。
        #   text  = 图文并用（当前默认，安全）
        #   skip  = 挂了人物图就跳过服装/外貌串（铁律二目标态）
        appearance_mode = str(vcfg.get("appearance_with_refs", "text")).lower()
        has_char_ref = any(("/characters/" in str(p).replace("\\", "/").lower()
                            or "_front." in os.path.basename(str(p)).lower()
                            or "_side." in os.path.basename(str(p)).lower()
                            or "_face." in os.path.basename(str(p)).lower()
                            or "_back." in os.path.basename(str(p)).lower())
                           for p in (refs or []))
        if not (appearance_mode == "skip" and has_char_ref):
            t = _with_costume(t, s)
            t = _with_character(t, s)

        # 对白留在画面段内 —— 官方要求「每句台词都写在它所在的镜头里，与该镜头的动作
        # 写在同一个段落中」
        t = _with_dialogue(t, s)

        sound = _audio_track(s)
        music = str(vcfg.get("non_diegetic_music") or "N/A").strip() or "N/A"
        return (f"integrated_multimodal_description: {t}\n\n"
                f"overall_soundscape: {sound}\n\n"
                f"non_diegetic_music: {music}")

    plan = [_plan_for(i, s) for i, s in enumerate(shots)]
    n_total = len(shots)
    # 日志展示用：区间跑时显示「全量总镜数」，避免出现「镜 5/4」这种误导
    n_show = len(all_shots) if len(all_shots) != n_total else n_total

    scene_counts = {}
    for s in shots:
        key = s.get("scene_no")
        scene_counts[key] = scene_counts.get(key, 0) + 1
    scene_brief = "、".join(f"场{k} {v} 镜" for k, v in
                            sorted(scene_counts.items(), key=lambda kv: str(kv[0])))

    log.banner("novel2video runner —— 分镜 → H3 逐镜生成", dry=args.plan_only)
    log.kv("项目", HERE)
    log.kv("分镜", _abs(args.storyboard_file) if args.storyboard_file else "(本次生成)")
    log.kv("模式", mode)
    log.kv("镜头", f"{n_total} 个（{scene_brief}）"
               + (f"｜本次区间，全片共 {n_show} 镜" if n_show != n_total else ""))
    log.kv("参考图", "；".join([f"默认 {len(ref_imgs)} 张"] +
                              [f"场{k} {len(v)} 张" for k, v in ref_map.items()]))
    log.kv("工作流", f"R2V={os.path.basename(wf_r2v or '-')}  "
                     f"I2V={os.path.basename(wf_i2v or '-')}  "
                     f"T2V={os.path.basename(wf_t2v or '-')}")
    log.kv("单镜超时", f"{int(vcfg.get('shot_timeout_sec', 2400) / 60)} 分钟")
    if args.time_budget:
        log.kv("时间预算", f"{args.time_budget:g} 分钟（到点在镜头边界退出，不打断进行中的镜头）")
    log.kv("失败重试", f"每镜最多 {args.retries} 次")
    log.kv("功能开关", "场景锚={}  服装={}  外貌={}  原生对白={}  tts={}".format(
        (f"on({anc_mode})" if anc_on else "off"),
        "on" if costume_on else "off",
        "on" if char_on else "off",
        "on" if dlg_on else "off",
        "on" if cfg.get("tts", {}).get("enabled") else "off"))
    if dlg_on and spk_registry:
        log.kv("说话人ID", "；".join(f"{k}→{v}" for k, v in spk_registry.items()))
    log.kv("日志文件", log_path)
    log.kv("进度状态", state_path)
    log.rule()
    log.info("逐镜计划：")
    for i, s in enumerate(shots):
        n = s.get("index", i + 1)
        label, first_src, refs, cont, _aimg = plan[i]
        tail = f"  参考 {len(refs)} 张" if refs else ""
        say = ""
        if dlg_on and str(s.get("line") or "").strip():
            say = f"  [对白 {_speaker_tag_for(s)}]"
        anc = _anchor_id_for(s)
        ainfo = f"  锚:{anc}" if anc else ""
        _d = s.get("duration") or ((s.get("length") or 0) / 24.0)
        dstr = f"  {_d:.2f}s/{s.get('length')}帧" if _d else ""
        log.info(f"  镜 {n:>3}/{n_show} | 场{s.get('scene_no')} | "
                 f"{label:<10} | {cont:<9}{dstr} | 首帧←{first_src}{tail}{say}{ainfo}")
    log.rule()

    # ---------- 分镜 vs 状态表：错配拦截 ----------
    # 换分镜（如 v2→v3）却沿用旧 run_state.json 时，新分镜的镜头会按旧记录被判为
    # 「已完成」而整段跳过，且不报任何错。这里显式拦下来。
    state = rs.RunState(state_path, n_total)
    sb_fp = (rs.storyboard_fingerprint(_abs(args.storyboard_file))
             if args.storyboard_file else None)
    prev_fp = state.storyboard_info() if sb_fp else {}
    if sb_fp and sb_fp.get("hash") and prev_fp.get("hash") \
            and prev_fp["hash"] != sb_fp["hash"]:
        done_n = sum(1 for r in state.data["shots"].values() if r.get("status") == "done")
        clip_n = 0
        for _k, _r in state.data["shots"].items():
            if _r.get("status") != "done":
                continue
            try:
                _n = int(_k)
            except (TypeError, ValueError):
                continue
            if rs.clip_is_valid(os.path.join(clip_dir, f"shot_{_n:03d}.mp4")):
                clip_n += 1
        _crel = os.path.relpath(clip_dir, HERE).replace("\\", "/")
        log.rule("!")
        log.warn("状态表绑定的分镜与当前分镜不一致 —— 直接沿用会把新分镜的镜头误跳过。")
        log.info(f"  状态表绑定 : {prev_fp.get('file', '?')}  hash={prev_fp.get('hash', '?')}"
                 f"  {prev_fp.get('shots', '?')} 镜  于 {prev_fp.get('at', '?')}")
        log.info(f"  当前分镜   : {sb_fp['file']}  hash={sb_fp['hash']}"
                 f"  {sb_fp['shots']} 镜  改动于 {sb_fp.get('mtime', '?')}")
        log.info(f"  旧状态内有 {done_n} 镜标记完成，其中 {clip_n} 个片段文件仍存在（{_crel}）")
        if args.plan_only:
            log.warn("  仅计划模式，此处不中止；正式跑前请用 --fresh-state 或 --accept-state 表态。")
        elif args.fresh_state:
            _bak = f"{state_path}.bak_{rs.now_stamp()}"
            try:
                shutil.move(state_path, _bak)
            except OSError:
                pass
            log.warn(f"  已按 --fresh-state 归档旧状态表 → {os.path.basename(_bak)}，从零开始。")
            state = rs.RunState(state_path, n_total)
        elif args.accept_state:
            log.warn("  已按 --accept-state 继续：沿用旧完成记录（仅当你确认旧片段仍适用时使用）。")
        else:
            log.info("  处理方式（二选一）：")
            log.info("    1) 舍弃旧状态、从零开始：加 --fresh-state（旧状态自动归档，不删除）")
            log.info("    2) 确认旧完成记录仍适用于新分镜：加 --accept-state")
            log.info("    另请核对 clips/ 内是否残留旧分镜的同名片段（存在即被判为已完成）。")
            log.rule("!")
            log.close()
            sys.exit(5)
        log.rule("!")

    if args.plan_only:
        log.info("（--plan-only）仅打印计划，未连接 ComfyUI、未生成任何内容。")
        log.close()
        return

    if args.dump_prompts:
        for i, s in enumerate(shots):
            n = s.get("index", i + 1)
            print(f"\n### 镜 {n} | 场{s.get('scene_no')} | "
                  f"protagonist={_uses_protagonist(s)} | 锚={_anchor_id_for(s) or '-'} | "
                  f"{plan[i][0]}")
            print(_build_prompt(s, plan[i][2]))
        log.info("（--dump-prompts）仅打印最终提示词，未连接 ComfyUI、未生成。")
        log.close()
        return

    # ---------- 单实例锁（防止两个 runner 同时跑，互相覆盖产物）----------
    lock = rs.SingleInstanceLock(lock_path)
    if not lock.acquire():
        log.fail(f"检测到另一个 runner 正在运行（锁文件：{lock_path}）。")
        log.info("  确认没有其它实例在跑后，删除该锁文件再重试。")
        log.close()
        sys.exit(2)
    log.info(f"已取得运行锁：{lock_path}")

    # ---------- [4] 确保 ComfyUI ----------
    if args.dry_run:
        log.info("（--dry-run）离线演练：跳过 ComfyUI 连接检查。")
    else:
        log.info("检查 ComfyUI 服务...")
        if not cc.ensure_running(cfg["comfyui_url"], cfg.get("comfyui_launch_bat"),
                                 cfg.get("comfyui_auto_start", True)):
            log.fail("ComfyUI 未启动，请先双击「启动ComfyUI服务.bat」，再重跑本脚本。")
            lock.release(); log.close()
            sys.exit(1)
        log.ok(f"ComfyUI 就绪：{cfg['comfyui_url']}")

    # 分镜指纹绑定：拿到运行锁后再落盘（避免两个 runner 同时写状态表）。
    # 触发时机 = 首次运行，或刚按 --fresh-state / --accept-state 越过上面的错配检查。
    if sb_fp and sb_fp.get("hash") \
            and state.storyboard_info().get("hash") != sb_fp["hash"]:
        state.bind_storyboard(sb_fp)
        log.info(f"  状态表已绑定分镜：{sb_fp['file']}（{sb_fp['shots']} 镜 "
                 f"hash={sb_fp['hash']}）")

    # 只统计「本次选定区间」的镜——state 文件跨区间累积，直接 counts() 会把区间外的
    # 历史 done 也算进来，导致范围跑被误判成「已全部完成」而提前拼接。
    scope_idx = [int(s.get("index", i + 1)) for i, s in enumerate(shots)]

    def scope_counts():
        d = sum(1 for n in scope_idx if state.get(n).get("status") == "done")
        f = sum(1 for n in scope_idx if state.get(n).get("status") == "failed")
        return d, f

    done_before, _fail_before = scope_counts()
    log.info(f"逐镜生成开始（共 {n_total} 镜，已完成 {done_before}）")

    def _rel(p):
        return os.path.relpath(p, HERE).replace("\\", "/")

    # 1x1 占位 PNG（dry-run 用，避免假 mp4 被 ffmpeg 抽帧时炸掉）
    _FAKE_PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
                 b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
                 b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82")

    def _grab(video, png):
        """截取上一镜尾帧作本镜首帧；dry-run 时写占位图代替。"""
        if args.dry_run:
            os.makedirs(os.path.dirname(png), exist_ok=True)
            with open(png, "wb") as f:
                f.write(_FAKE_PNG)
            return png
        return ac.extract_last_frame(video, png)

    # 当前镜的帧数（24fps）—— H3 模板里 length 写死 124（≈5.17s），提交前必须
    # 按分镜的 length 改写；否则不管分镜标 3 秒还是 15 秒，成片每镜都是 5.17s。
    _cur = {"length": None}

    def _gen(url, workflow, prompt, **kw):
        """统一生成入口：dry-run 时返回模拟 MP4，其余交给真实 ComfyUI。"""
        kw.setdefault("length", _cur["length"])
        if args.dry_run:
            time.sleep(0.2)
            os.makedirs(raw_dir, exist_ok=True)
            fake = os.path.join(raw_dir, f"dry_{rs.now_stamp()}.mp4")
            with open(fake, "wb") as f:
                f.write(b"\x00\x00\x00\x20ftypisom" + b"\x00" * 24000)
            m = kw.get("meta")
            if m is not None:
                m.update(prompt_id="dry-run",
                         workflow=os.path.basename(workflow or ""),
                         raw_files=[os.path.basename(fake)],
                         length_frames=cc.snap_length(_cur["length"]))
            return [fake]
        return cc.generate(url, workflow, prompt, **kw)

    shot_timeout = float(vcfg.get("shot_timeout_sec", 2400))
    started = time.time()
    budget_s = (args.time_budget or 0) * 60.0
    redo_from = args.redo_from or 0
    if redo_from:
        log.warn(f"--redo-from {redo_from}：第 {redo_from} 镜及之后强制重跑")
    aborted_at = None
    budget_hit = False
    ran = 0

    for i, s in enumerate(shots):
        n = s.get("index", i + 1)
        out_clip = os.path.join(clip_dir, f"shot_{n:03d}.mp4")
        label, first_src, refs, cont, anchor_img = plan[i]
        force = bool(redo_from and n >= redo_from)
        _cur["length"] = s.get("length")          # 本镜帧数 → 提交前改写 H3 的 length

        # 断点续跑：产物有效且未要求重跑 → 跳过
        if not force and rs.clip_is_valid(out_clip):
            if state.get(n).get("status") != "done":
                state.mark(n, status="done", clip=_rel(out_clip),
                           note="历史产物，自动确认")
            log.skip(f"镜 {n}/{n_show} | {label} | 已完成，跳过"
                     f"（{rs.fmt_size(out_clip)}）")
            continue

        # 时间预算：仅在新镜开始前判断 —— 已开始的镜头一定让它跑完
        if budget_s and (time.time() - started) >= budget_s:
            budget_hit = True
            log.warn(f"时间预算 {args.time_budget:g} 分钟到，停在镜 {n} 之前"
                     f"（本次新完成 {ran} 镜）")
            break

        prev = shots[i - 1] if i > 0 else None
        scene_start = (prev is None) or (s.get("scene_no") != prev.get("scene_no"))
        do_continue = (cont == "continue" and prev is not None and not scene_start)
        prompt = _build_prompt(s, refs)
        meta = {}
        state.mark(n, status="running", mode=label, scene_no=s.get("scene_no"),
                   started_at=rs.full_stamp(), clip=_rel(out_clip))
        log.step(f"镜 {n}/{n_show} | 场{s.get('scene_no')} | {label}"
                 f" | 首帧←{first_src}")

        attempt = 0
        while True:
            attempt += 1
            t0 = time.time()
            try:
                if mode == "fl2va":
                    if scene_start:
                        first_img = os.path.join(kf_dir, f"shot_{n:03d}_first.png")
                        log.info(f"      起始帧 ← {_rel(first_img)}")
                    else:
                        pn = prev.get("index", i)
                        first_img = os.path.join(kf_dir, f"shot_{n:03d}_prev_last.png")
                        _grab(
                            os.path.join(clip_dir, f"shot_{pn:03d}.mp4"), first_img)
                        log.info(f"      起始帧 ← shot_{pn:03d}.mp4 尾帧")
                    outs = _gen(
                        cfg["comfyui_url"], wf_fl2va, prompt,
                        first_frame_path=first_img,
                        last_frame_path=os.path.join(kf_dir, f"shot_{n:03d}_last.png"),
                        prompt_pair=fp_p, first_pair=fp_f, last_pair=fp_l,
                        out_dir=raw_dir, timeout=shot_timeout, meta=meta)
                elif do_continue:
                    pn = prev.get("index", i)
                    prev_clip = os.path.join(clip_dir, f"shot_{pn:03d}.mp4")
                    if not rs.clip_is_valid(prev_clip):
                        log.warn(f"      上一镜 {pn} 产物不可用 → 本镜降级为重新构图")
                        fallback_refs = _refs_with_anchor(s)
                        fa_img = _anchor_img_for(s)
                        if fallback_refs and _uses_protagonist(s):
                            outs = _gen(
                                cfg["comfyui_url"], wf_r2v, prompt,
                                ref_image_paths=fallback_refs, prompt_pair=r_p,
                                ref_pair=r_r, out_dir=raw_dir,
                                timeout=shot_timeout, meta=meta)
                        elif fa_img:
                            log.info(f"      降级为场景锚 I2V｜锚图 "
                                     f"{os.path.basename(fa_img)}")
                            outs = _gen(
                                cfg["comfyui_url"], wf_i2v, prompt,
                                first_frame_path=fa_img, prompt_pair=i_p,
                                first_pair=i_f, out_dir=raw_dir,
                                timeout=shot_timeout, meta=meta)
                        else:
                            outs = _gen(
                                cfg["comfyui_url"], wf_t2v, prompt,
                                prompt_pair=t_p, out_dir=raw_dir,
                                timeout=shot_timeout, meta=meta)
                    else:
                        first_img = os.path.join(kf_dir, f"shot_{n:03d}_prev_last.png")
                        _grab(prev_clip, first_img)
                        log.info(f"      首帧 ← shot_{pn:03d}.mp4 尾帧（{_rel(first_img)}）")
                        outs = _gen(
                            cfg["comfyui_url"], wf_i2v, prompt,
                            first_frame_path=first_img,
                            prompt_pair=i_p, first_pair=i_f,
                            out_dir=raw_dir, timeout=shot_timeout, meta=meta)
                elif anchor_img:
                    # 场景锚定：本镜无主角，用该空间锚图作首帧 —— 背景与同空间其它镜同源，
                    # 机位/主体差异仍由 prompt 驱动（不会被上一镜尾帧锁死成"画面僵住"）。
                    # 人工关键帧（方案 B）也走这里 —— 本质同为「以某张图作首帧」。
                    log.info(f"      {'人工关键帧' if cont == 'keyframe' else '场景锚'}"
                             f"首帧 ← {_rel(anchor_img)}")
                    outs = _gen(
                        cfg["comfyui_url"], wf_i2v, prompt,
                        first_frame_path=anchor_img,
                        prompt_pair=i_p, first_pair=i_f,
                        out_dir=raw_dir, timeout=shot_timeout, meta=meta)
                else:
                    # 换机位/换景：不接上一镜尾帧，用参考图（主角）或纯文字重新构图
                    if refs and _uses_protagonist(s):
                        log.info(f"      重新构图 R2V｜参考图 {len(refs)} 张："
                                 f"{', '.join(os.path.basename(p) for p in refs)}")
                        outs = _gen(
                            cfg["comfyui_url"], wf_r2v, prompt,
                            ref_image_paths=refs, prompt_pair=r_p, ref_pair=r_r,
                            out_dir=raw_dir, timeout=shot_timeout, meta=meta)
                    else:
                        log.info("      重新构图 T2V｜纯文字")
                        outs = _gen(
                            cfg["comfyui_url"], wf_t2v, prompt,
                            prompt_pair=t_p, out_dir=raw_dir,
                            timeout=shot_timeout, meta=meta)

                shutil.copy(outs[0], out_clip)
                took = time.time() - t0
                ran += 1
                state.mark(n, status="done", clip=_rel(out_clip),
                           seconds=round(took, 1), finished_at=rs.full_stamp(),
                           first_frame_src=first_src,
                           refs=[_rel(p) for p in refs],
                           prompt_head=prompt[:300],
                           prompt_id=meta.get("prompt_id"),
                           workflow=meta.get("workflow"),
                           raw_files=meta.get("raw_files"))
                rs.RunState.journal(journal_path, {
                    "shot": n, "scene_no": s.get("scene_no"), "mode": label,
                    "status": "done", "clip": _rel(out_clip),
                    "seconds": round(took, 1), "size": os.path.getsize(out_clip),
                    "attempt": attempt, "first_frame_src": first_src,
                    "prompt_id": meta.get("prompt_id"),
                    "workflow": meta.get("workflow"),
                    "raw_files": meta.get("raw_files"), "at": rs.full_stamp(),
                })
                log.ok(f"镜 {n}/{n_show} | 完成 {rs.fmt_dur(took)} → "
                       f"{_rel(out_clip)}（{rs.fmt_size(out_clip)}）")
                break
            except Exception as e:
                took = time.time() - t0
                if attempt <= args.retries:
                    log.warn(f"镜 {n}/{n_show} | 第 {attempt} 次失败"
                             f"（{rs.fmt_dur(took)}）：{type(e).__name__}: {e}"
                             f" —— 15s 后重试")
                    state.mark(n, status="running", attempts=attempt,
                               last_error=str(e))
                    time.sleep(15)
                    continue
                log.fail(f"镜 {n}/{n_show} | 失败（已重试 {args.retries} 次）："
                         f"{type(e).__name__}: {e}")
                state.mark(n, status="failed", attempts=attempt,
                           error=str(e), failed_at=rs.full_stamp())
                rs.RunState.journal(journal_path, {
                    "shot": n, "scene_no": s.get("scene_no"), "mode": label,
                    "status": "failed", "attempts": attempt, "error": str(e),
                    "at": rs.full_stamp(),
                })
                if args.skip_failed:
                    log.warn(f"      （--skip-failed）不中断，继续后续镜头；"
                             f"稍后可用 --redo-from {n} 单独补跑镜 {n}")
                    break
                aborted_at = n
                break
        lock.heartbeat()
        if aborted_at:
            break

    done, _failed = scope_counts()
    log.rule()
    if aborted_at:
        log.fail(f"中断：镜 {aborted_at} 失败，本次完成 {done}/{n_total} 镜。")
        log.info(f"修复后重跑本脚本，将从镜 {aborted_at} 续（之前的自动跳过）。")
        log.info(f"状态表 {state_path}｜流水 {journal_path}")
        lock.release(); log.close()
        sys.exit(1)

    if done < n_total:
        log.warn(f"未全部完成：{done}/{n_total}"
                 + ("（时间预算到）" if budget_hit else "（部分镜缺失）"))
        log.info(f"再次运行本脚本会自动续跑剩余 {n_total - done} 镜。")
        lock.release(); log.close()
        sys.exit(10 if budget_hit else 1)

    log.ok(f"本次区间 {n_total} 镜全部就绪（本次新生成 {ran} 镜）。")

    # 拼接取 clips 目录里「所有」有效片段（按镜号排序），而不是只取本次区间——
    # 分段跑（如先 1~20 再 21~40）时，最后一段也能拼出完整成片。
    import glob as _glob
    import re as _re
    _by_idx = {}
    for i, s in enumerate(all_shots):
        _by_idx[int(s.get("index", i + 1))] = s
    clips = []
    for p in sorted(_glob.glob(os.path.join(clip_dir, "shot_*.mp4"))):
        m = _re.match(r"^shot_(\d+)\.mp4$", os.path.basename(p))
        if not m or not rs.clip_is_valid(p):
            continue
        n = int(m.group(1))
        s = _by_idx.get(n) or {}
        clips.append((p, s.get("line", ""), s.get("duration", 5)))
    if not clips:
        log.fail("没有任何可用片段，无法拼接。")
        lock.release(); log.close()
        sys.exit(1)

    if args.no_concat:
        log.info("（--no-concat）跳过配音与拼接。")
        lock.release(); log.close()
        return

    out_path = _abs(args.out) if args.out else os.path.join(release_dir, "final.mp4")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    try:
        # ---------- [4.5] 配音 ----------
        tts_cfg = cfg.get("tts", {})
        if tts_cfg.get("enabled") and not args.no_tts:
            log.info(f"[4.5] 生成配音并混入片段（音色 {tts_cfg.get('voice')}）...")
            voice = tts_cfg.get("voice", "zh-CN-YunxiNeural")
            tts_dir = os.path.join(out_dir, "tts")
            os.makedirs(tts_dir, exist_ok=True)
            new_clips = []
            for i, (vpath, line, dur) in enumerate(clips):
                if not line or not line.strip():
                    new_clips.append((vpath, line, dur))
                    continue
                raw = os.path.join(tts_dir, f"line_{i:02d}.mp3")
                fit = os.path.join(tts_dir, f"line_{i:02d}_fit.m4a")
                mixed = os.path.join(tts_dir, f"clip_{i:02d}_voiced.mp4")
                tc.synth_line(line, voice, raw, rate=tts_cfg.get("rate", "+0%"))
                tc.fit_audio_to_duration(raw, fit, float(dur))
                tc.mux_voice_into_video(
                    vpath, fit, mixed,
                    keep_ambient=tts_cfg.get("keep_ambient", True),
                    voice_gain=tts_cfg.get("voice_gain", 1.0),
                    ambient_gain=tts_cfg.get("ambient_gain", 0.3))
                new_clips.append((mixed, line, dur))
            clips = new_clips

        # ---------- [5] 拼接 ----------
        log.info("[5] 烧字幕 + 拼接成片...")
        ac.concat_clips(clips, out_path, font=cfg.get("subtitle_font"),
                        audio_filter=(cfg.get("video") or {}).get("audio_filter"))
    except Exception as e:
        log.fail(f"配音/拼接失败：{type(e).__name__}: {e}")
        log.info(f"  各镜头片段仍在 {os.path.relpath(clip_dir, HERE).replace(os.sep, '/')}/"
                 f"，修好后重跑本脚本即可直接续到拼接。")
        lock.release(); log.close()
        sys.exit(1)

    state.data["final"] = {"path": os.path.relpath(out_path, HERE),
                           "finished_at": rs.full_stamp()}
    state.save()
    log.ok(f"成片 → {out_path}（{rs.fmt_size(out_path)}，"
           f"总耗时 {rs.fmt_dur(time.time() - started)}）")
    log.rule()
    lock.release()
    log.close()


if __name__ == "__main__":
    main()
