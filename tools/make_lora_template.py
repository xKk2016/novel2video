# -*- coding: utf-8 -*-
"""在任意 H3 模板上挂 LoRA（风格 / 加速均可，支持多个串联）。

与 `make_turbo_templates.py` 的区别：那个是 turbo 专用（写死 fl2v/ref2v 的加速 LoRA 组合）；
本脚本**通用**——任意 LoRA、任意个数、可选覆盖 steps/sampler/scheduler/shift。

**核心逻辑（通用，不写死节点号）**：
  ① 找 `UNETLoader`
  ② 找**所有**把 `["<unet_id>", 0]` 当 model 输入的节点（r2v 有 2 处：BasicScheduler + BasicGuider；
     i2v/t2v 有 1~2 处：SigmaShift / KSampler）
  ③ 在这条链中间插入 N 个 `LoraLoaderModelOnly`（按给定顺序串联）
  ④ 把步骤②找到的节点全部改指向链尾
  ⇒ 顺序：UNETLoader → LoRA1 → LoRA2 → … → (SigmaShift) → Sampler/Guider

**为什么必须"找所有引用"**：只改一处会让另一处静默地用上**没挂 LoRA 的模型**
（r2v 踩过：模型同时喂 BasicScheduler 和 BasicGuider）。

用法：
    # 单个风格 LoRA（保持原模板的步数与采样参数）
    ./.venv/Scripts/python.exe tools/make_lora_template.py \
        --src templates/h3_r2v_api.json \
        --out templates/h3_r2v_lumi_api.json \
        --lora Anime2Realsim__H3.safetensors --strength 1.0

    # 风格 + 加速 串联（作者已验证兼容）
    ./.venv/Scripts/python.exe tools/make_lora_template.py \
        --src templates/h3_r2v_api.json --out templates/h3_r2v_lumi_t8_api.json \
        --lora Anime2Realsim__H3.safetensors --strength 1.0 \
        --lora minimax_h3_ref2v_turbo_8step_v1.0_768p_comfyui_bf16.safetensors --strength 1.0 \
        --steps 8

    # 只预览不写文件
    ./.venv/Scripts/python.exe tools/make_lora_template.py --src ... --out ... --lora ... --dry-run
"""
import argparse
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

BASE_ID = 900          # LoRA 节点 ID 起始（模板里 1~21 与 90/91 都可能被占）


def free_ids(d, n):
    used = {int(k) for k, v in d.items() if isinstance(v, dict) and str(k).isdigit()}
    out, i = [], BASE_ID
    while len(out) < n:
        if i not in used:
            out.append(str(i))
        i += 1
    return out


def apply_lora(src_path, out_path, loras, strengths, steps=None,
               sampler_name=None, scheduler=None,
               shift_video=None, shift_audio=None, dry=False):
    d = json.load(open(src_path, encoding="utf-8"))

    unet = next(k for k, v in d.items()
                if isinstance(v, dict) and v.get("class_type") == "UNETLoader")
    # 所有把 unet 当 model 输入的节点
    sinks = [k for k, v in d.items()
             if isinstance(v, dict) and (v.get("inputs") or {}).get("model") == [unet, 0]]
    if not sinks:
        raise SystemExit("没找到引用 UNETLoader 输出的节点，模板结构不认识")

    ids = free_ids(d, len(loras))
    prev = unet
    for nid, name, st in zip(ids, loras, strengths):
        d[nid] = {
            "class_type": "LoraLoaderModelOnly",
            "inputs": {"model": [prev, 0], "lora_name": name,
                       "strength_model": float(st)},
        }
        prev = nid
    for s in sinks:
        d[s]["inputs"]["model"] = [prev, 0]

    # 可选覆盖
    changed = []
    if steps is not None:
        for k, v in d.items():
            if isinstance(v, dict) and "steps" in (v.get("inputs") or {}):
                v["inputs"]["steps"] = int(steps)
                changed.append("steps=%d @%s" % (int(steps), k))
    if scheduler is not None:
        for k, v in d.items():
            if isinstance(v, dict) and "scheduler" in (v.get("inputs") or {}):
                v["inputs"]["scheduler"] = scheduler
                changed.append("scheduler=%s @%s" % (scheduler, k))
    if sampler_name is not None:
        for k, v in d.items():
            if isinstance(v, dict) and "sampler_name" in (v.get("inputs") or {}):
                v["inputs"]["sampler_name"] = sampler_name
                changed.append("sampler=%s @%s" % (sampler_name, k))
    if shift_video is not None or shift_audio is not None:
        hit = False
        for v in d.values():
            if isinstance(v, dict) and v.get("class_type") == "MiniMaxH3SigmaShift":
                if shift_video is not None:
                    v["inputs"]["shift_video"] = float(shift_video)
                if shift_audio is not None:
                    v["inputs"]["shift_audio"] = float(shift_audio)
                hit = True
                changed.append("shift=%s/%s" % (v["inputs"]["shift_video"],
                                                v["inputs"]["shift_audio"]))
        if not hit:
            print("  ⚠️ 该模板没有 MiniMaxH3SigmaShift 节点，shift 未改动")

    d["_comment_lora"] = (
        "由 tools/make_lora_template.py 生成，勿手改 —— 要调参改脚本重跑。"
        "LoRA 链：%s（%s）；源模板 %s。"
        % (" → ".join(loras), "/".join("%.2f" % s for s in strengths),
           os.path.basename(src_path)))

    print("源模板 : %s" % os.path.basename(src_path))
    print("链路   : UNETLoader(%s) → %s → %s"
          % (unet, " → ".join("LoRA(%s@%.2f)" % (n, s) for n, s in zip(loras, strengths)),
             "+".join(sinks)))
    for c in changed:
        print("         覆盖 %s" % c)
    print("输出   : %s" % os.path.basename(out_path))

    if dry:
        print("[dry-run] 未写文件")
        return 0
    json.dump(d, open(out_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("✓ 已写入")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--lora", action="append", required=True, help="LoRA 文件名（可重复）")
    ap.add_argument("--strength", action="append", type=float, default=None,
                    help="与 --lora 一一对应；只给一个则应用到全部")
    ap.add_argument("--steps", type=int, default=None)
    ap.add_argument("--sampler", default=None)
    ap.add_argument("--scheduler", default=None)
    ap.add_argument("--shift-video", type=float, default=None)
    ap.add_argument("--shift-audio", type=float, default=None)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    src = a.src if os.path.isabs(a.src) else os.path.join(ROOT, a.src)
    out = a.out if os.path.isabs(a.out) else os.path.join(ROOT, a.out)
    if not os.path.isfile(src):
        raise SystemExit("源模板不存在：%s" % src)

    if a.strength is None:
        st = [1.0] * len(a.lora)
    elif len(a.strength) == 1:
        st = a.strength * len(a.lora)
    elif len(a.strength) == len(a.lora):
        st = a.strength
    else:
        raise SystemExit("--strength 个数必须为 1 或与 --lora 相同")

    return apply_lora(src, out, a.lora, st, a.steps, a.sampler, a.scheduler,
                      a.shift_video, a.shift_audio, a.dry_run)


if __name__ == "__main__":
    sys.exit(main())
