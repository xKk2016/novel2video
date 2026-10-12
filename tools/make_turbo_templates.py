# -*- coding: utf-8 -*-
"""生成 turbo LoRA 版工作流模板（第 23 轮）。

**为什么需要这个**：官方 H3 模板给了两档 ——
  · 非 turbo 档：不挂 LoRA + **20 步**（我们一直在用，也即官方默认）
  · turbo 档  ：挂 turbo LoRA + **4 或 8 步**
turbo LoRA 是**提速**蒸馏（20 步 → 4/8 步，约 3~5 倍），**不是提质**。

⚠️ **LoRA 必须与底模配对，不能混挂** —— 名字里的 `fl2v` / `ref2v` 分别对应两个底模：
  · i2v / t2v / fl2va → `minimax_h3_fl2v_turbo_*`（配 FL2VA 底模）
  · r2v               → `minimax_h3_ref2v_turbo_*`（配 Ref2VA 底模）
⚠️ 两个底模的张量层名 **100% 相同**（实测 932 个键全重合）⇒ 挂错了**不会报错**，
   会静默加载并按错误条件推理。**只能靠文件名前缀区分。**
⚠️ ref2v 的 4 步 LoRA **只有 `v0.1` 版**（544p 训练），而 fl2v 那边已迭代到 `v1.1 768p`（已提升为生产版）
   ⇒ r2v 在 4 步下的画质预期低于 i2v/t2v/fl2va。
   ⚠️ **r2v 目前用 8 步版**（`ref2v_turbo_8step_v1.0_768p`）：ref2v 没有 v1.1，8 步版的分辨率与版本都更好。

**不改现有模板**：新文件另存为 `h3_<mode>_turbo<N>_api.json`，
用 config 的 `workflow_api_i2v` / `workflow_api` / `workflow_api_fl2va` /
`workflow_api_r2v` 切换（见 `tools/switch_workflow.py`），随时可回退。

接线改动（3 处）：
  ① 新增节点 "90": LoraLoaderModelOnly { model:["1",0], lora_name, strength_model:1.0 }
  ② 节点 2（MiniMaxH3SigmaShift）的 model: ["1",0] → ["90",0]
     —— LoRA 先打权重，SigmaShift 后设采样设置（顺序不能反）
  ③ 节点 7（KSampler）的 steps: 20 → N

用法：
    ./.venv/Scripts/python.exe tools/make_turbo_templates.py --dry-run
    ./.venv/Scripts/python.exe tools/make_turbo_templates.py
"""
import argparse
import json
import os
import shutil
import sys

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TDIR = os.path.join(ROOT, "templates")

# FL2VA 底模的三个模式（r2v 走 Ref2VA，在 main 里单独处理）
MODES = {
    "i2v": "h3_i2v_api.json",
    "t2v": "h3_t2v_api.json",
    "fl2va": "h3_fl2va_api.json",
}

# ⭐ 4 步 LoRA 生产版 = **v1.1**（2026-10-09 15:00 实测后升级）
#   v1.0 在复杂画面镜（镜3）会出「暗紫色块 = 黑雾」：暗部 17.7% / 亮度 100.4 / 帧间差 4.22
#   v1.1 同一个镜：暗部 **10.8%** / 亮度 **120.5**（=20 步基线）/ 帧间差 **2.43**，黑雾消失
#   结构完全一致（624 张量 / 208 组 lora_A / alpha 128 与 384 并存 / scale 全 1.0）⇒ 纯权重替换
#   v1.0 文件仍留在 models/loras/ 里，需要对比时手工改回即可。
LORA_4 = "minimax_h3_fl2v_turbo_4step_v1.1_768p_comfyui_bf16.safetensors"
LORA_4_V10 = "minimax_h3_fl2v_turbo_4step_v1.0_768p_comfyui_bf16.safetensors"   # 旧版（有黑雾缺陷，留作对照）
LORA_8 = "minimax_h3_fl2v_turbo_8step_v1.0_768p_comfyui_bf16.safetensors"   # 768p 版（匹配推理分辨率）
# R2V 专用（Ref2VA 底模）—— 与上面两个 fl2v 的不通用
LORA_REF2V_4 = "minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors"      # 544p 训练（唯一 4 步版）
LORA_REF2V_8 = "minimax_h3_ref2v_turbo_8step_v1.0_768p_comfyui_bf16.safetensors"  # 768p

LORA_NODE_ID = "90"          # 各模板都空闲（i2v 最大 20 / t2v 12 / fl2va 21）


def build(src_path, lora_name, steps, scheduler="normal", shift_audio=None,
          sampler_name=None, shift_video=None):
    d = json.load(open(src_path, encoding="utf-8"))

    # 定位关键节点
    unet = next(k for k, v in d.items()
                if isinstance(v, dict) and v.get("class_type") == "UNETLoader")
    shift = next(k for k, v in d.items()
                 if isinstance(v, dict) and v.get("class_type") == "MiniMaxH3SigmaShift")
    sampler = next(k for k, v in d.items()
                   if isinstance(v, dict) and "steps" in (v.get("inputs") or {}))

    if LORA_NODE_ID in d:
        raise SystemExit("节点 %s 已被占用，请改 LORA_NODE_ID" % LORA_NODE_ID)

    # ① 新增 LoRA 节点
    d[LORA_NODE_ID] = {
        "class_type": "LoraLoaderModelOnly",
        "inputs": {
            "model": [unet, 0],
            "lora_name": lora_name,
            "strength_model": 1.0,
        },
    }
    # ② SigmaShift 改吃 LoRA 输出 + 对齐该 LoRA 的训练 shift
    #    ⚠️ shift 必须与 LoRA 的训练配置一致，否则 sigma 序列偏离训练分布
    d[shift]["inputs"]["model"] = [LORA_NODE_ID, 0]
    if shift_video is not None:
        d[shift]["inputs"]["shift_video"] = float(shift_video)
    if shift_audio is not None:
        d[shift]["inputs"]["shift_audio"] = float(shift_audio)
    # ③ 改步数与调度器
    d[sampler]["inputs"]["steps"] = int(steps)
    d[sampler]["inputs"]["scheduler"] = scheduler
    # ④ 可选：改采样器（sampler_name 挂在另一个节点，如 KSamplerSelect / KSampler）
    if sampler_name:
        snode = next(k for k, v in d.items()
                     if isinstance(v, dict) and "sampler_name" in (v.get("inputs") or {}))
        d[snode]["inputs"]["sampler_name"] = sampler_name

    # 注释（JSON 里带下划线键，不影响 ComfyUI 解析）
    d["_comment_turbo"] = (
        "turbo LoRA 版：%s @ strength 1.0，steps=%d，scheduler=%s，"
        "shift_video=%s，shift_audio=%s。"
        "由 tools/make_turbo_templates.py 生成，勿手改 —— 要调参改脚本重跑。"
        "⚠️ shift 必须对齐该 LoRA 的训练配置（官方 README model specs 表）："
        "FL2VA 4step v1.1 768p → 6/3；FL2VA 8step v1.0 (544p) → 12/3；"
        "Ref2VA 4step v0.1 → 12/3；Ref2VA 8step v1.0 768p → 6/3。"
        "⚠️ scheduler 用 simple：4 步下 normal 会让画面崩（满屏交叉网纹）。"
        % (lora_name, int(steps), scheduler,
           d[shift]["inputs"].get("shift_video"),
           d[shift]["inputs"].get("shift_audio")))
    return d, unet, shift, sampler


def build_r2v(src_path, lora_name, steps, scheduler="simple",
              shift_video=None, shift_audio=None, sampler_name=None):
    """R2V 专用：结构与 i2v 不同。

    底模是 ref2va（不是 fl2va）；走 SamplerCustomAdvanced + BasicGuider；
    模型（节点 1）同时喂给 BasicScheduler(8) 和 BasicGuider(9)；
    **模板里原本没有 SigmaShift 节点** ⇒ 要改 shift 必须新插一个。
    """
    d = json.load(open(src_path, encoding="utf-8"))
    unet = "1"
    sched = "8"
    guider = "9"

    lora_id = "90"
    for k in (lora_id, "91"):
        if k in d:
            raise SystemExit("节点 %s 已被占用，请改 LORA_NODE_ID" % k)

    d[lora_id] = {
        "class_type": "LoraLoaderModelOnly",
        "inputs": {"model": [unet, 0], "lora_name": lora_name, "strength_model": 1.0},
    }
    last_model = lora_id

    if shift_video is not None or shift_audio is not None:
        d["91"] = {
            "class_type": "MiniMaxH3SigmaShift",
            "inputs": {
                "model": [lora_id, 0],
                "shift_video": float(shift_video if shift_video is not None else 12.0),
                "shift_audio": float(shift_audio if shift_audio is not None else 3.0),
            },
        }
        last_model = "91"

    d[sched]["inputs"]["model"] = [last_model, 0]
    d[sched]["inputs"]["steps"] = int(steps)
    d[sched]["inputs"]["scheduler"] = scheduler
    d[guider]["inputs"]["model"] = [last_model, 0]
    # 采样器在独立的 KSamplerSelect（节点 7）
    if sampler_name:
        d["7"]["inputs"]["sampler_name"] = sampler_name

    d["_comment_turbo"] = (
        "R2V(Ref2VA) turbo LoRA 版：%s @ strength 1.0，steps=%d，scheduler=%s，"
        "shift_video=%s，shift_audio=%s。由 tools/make_turbo_templates.py 生成，勿手改。"
        "⚠️ 底模是 ref2va，必须用 ref2v 专用 turbo LoRA，不能挂 fl2v 那套。"
        "⚠️ shift 必须对齐训练配置：Ref2VA 4step v0.1 → 12/3；Ref2VA 8step v1.0 768p → 6/3"
        "（原生 r2v 模板无 SigmaShift 节点，用默认 12 ⇒ 8 步那条必须插）。"
        % (lora_name, int(steps), scheduler,
           d.get("91", {}).get("inputs", {}).get("shift_video", "未插(沿用默认12)"),
           d.get("91", {}).get("inputs", {}).get("shift_audio", "未插(沿用默认3)"), ))
    return d, unet, last_model, sched


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--scheduler", default="simple",
                    help="采样调度器（默认 simple；4 步下 normal 会让画面崩）")
    ap.add_argument("--shift-audio", type=float, default=None,
                    help="覆盖 shift_audio（默认沿用源模板的 3.0；调大按推导方向是错的，仅供实测对照）")
    ap.add_argument("--shift-video", type=float, default=None,
                    help="R2V 专用：覆盖 shift_video（默认 6.0，对齐 Ref2VA turbo 的训练 shift）")
    ap.add_argument("--sampler", default=None,
                    help="采样器 sampler_name（默认沿用源模板 res_multistep；"
                         "社区给 turbo 的配对是 euler）")
    a = ap.parse_args()

    # 每个变体的 shift 必须对齐该 LoRA 的训练配置（官方 README「model specs」表）
    variants = [
        ("turbo4", LORA_4, 4, 6.0, 3.0),     # FL2VA 4step v1.0 768p  → 训练 6/3
        ("turbo8", LORA_8, 8, 6.0, 3.0),     # FL2VA 8step v1.0 768p → 训练 6/3
    ]
    made = []

    for tag, lora, steps, sv_def, sa_def in variants:
        sv = a.shift_video if a.shift_video is not None else sv_def
        sa = a.shift_audio if a.shift_audio is not None else sa_def
        print("=" * 76)
        print("变体 %s  ←  %s   steps=%d  sampler=%s  scheduler=%s  shift=%s/%s"
              % (tag, lora, steps, a.sampler or "沿用源模板", a.scheduler, sv, sa))
        for mode, src in MODES.items():
            src_path = os.path.join(TDIR, src)
            if not os.path.isfile(src_path):
                print("  ✗ 缺源模板 %s" % src)
                continue
            d, unet, shift, sampler = build(src_path, lora, steps, a.scheduler,
                                            sa, a.sampler, sv)
            out = os.path.join(TDIR, "h3_%s_%s_api.json" % (mode, tag))
            print("  %-6s UNET(%s) → LoRA(%s) → SigmaShift(%s) steps=%d sched=%s shift=%s/%s"
                  % (mode, unet, LORA_NODE_ID, shift, steps, a.scheduler,
                     d[shift]["inputs"]["shift_video"], d[shift]["inputs"]["shift_audio"]))
            if not a.dry_run:
                with open(out, "w", encoding="utf-8") as f:
                    json.dump(d, f, ensure_ascii=False, indent=2)
                made.append(os.path.basename(out))

    # ---- R2V（Ref2VA 底模，必须用 ref2v 专用 LoRA）----
    # Ref2VA 4step v0.1 → 训练 12/3 ；Ref2VA 8step v1.0 768p → 训练 6/3
    for tag, lora, steps, sv_def, sa_def in [("turbo4", LORA_REF2V_4, 4, 12.0, 3.0),
                                             ("turbo8", LORA_REF2V_8, 8, 6.0, 3.0)]:
        sv = a.shift_video if a.shift_video is not None else sv_def
        sa = a.shift_audio if a.shift_audio is not None else sa_def
        print("=" * 76)
        print("变体 r2v-%s  ←  %s" % (tag, lora))
        print("         steps=%d  sampler=%s  scheduler=%s  shift=%s/%s"
              % (steps, a.sampler or "沿用源模板", a.scheduler, sv, sa))
        src_r2v = os.path.join(TDIR, "h3_r2v_api.json")
        if not os.path.isfile(src_r2v):
            print("  ✗ 缺源模板 h3_r2v_api.json")
            continue
        d, unet, last_model, sched = build_r2v(
            src_r2v, lora, steps, a.scheduler,
            shift_video=sv, shift_audio=sa, sampler_name=a.sampler)
        out = os.path.join(TDIR, "h3_r2v_%s_api.json" % tag)
        print("  r2v    UNET(%s) → LoRA(%s) → SigmaShift(%s) → Scheduler(%s)/Guider  steps=%d"
              % (unet, LORA_NODE_ID, last_model, sched, steps))
        print("         sampler=%s  shift_video=%s shift_audio=%s"
              % (d["7"]["inputs"]["sampler_name"],
                 d.get("91", {}).get("inputs", {}).get("shift_video"),
                 d.get("91", {}).get("inputs", {}).get("shift_audio")))
        if not a.dry_run:
            with open(out, "w", encoding="utf-8") as f:
                json.dump(d, f, ensure_ascii=False, indent=2)
            made.append(os.path.basename(out))

    print("=" * 76)
    if a.dry_run:
        print("[dry-run] 未写文件。")
    else:
        print("已生成 %d 个：" % len(made))
        for m in made:
            print("   templates/%s" % m)
        print()
        print("下一步：切 config")
        print("   ./.venv/Scripts/python.exe tools/switch_workflow.py --turbo 4")
        print("   ./.venv/Scripts/python.exe tools/switch_workflow.py --off      # 回退")
    return 0


if __name__ == "__main__":
    sys.exit(main())
