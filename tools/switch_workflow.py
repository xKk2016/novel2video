# -*- coding: utf-8 -*-
"""一键切换「非 turbo / turbo LoRA」工作流（第 23 轮建立）。

改的是 config.json 里这 4 个键：
    workflow_api_i2v   → i2v        ┐
    workflow_api       → t2v        ├ 跟随 --turbo 的档位（4 或 8）
    workflow_api_fl2va → fl2va      ┘
    workflow_api_r2v   → r2v        ← **固定 4 步**（官方 ref2v_turbo_4step_v0.1）
                                      ⚠️ 必须用 ref2v 专用 LoRA，不能挂 fl2v 版

⚠️ 采样器/调度器由 make_turbo_templates.py 决定，当前生产档为
   **`euler` + `simple`**（2026-10-09 验证：4 步下音频 L/R 0.812 vs res_multistep 的 0.023）。

⭐ i2v/t2v/fl2va 的 4 步模板已使用 **FL2V Turbo LoRA v1.1**（2026-10-09 15:00 升级）。
   v1.0 在复杂画面镜会出「暗紫色块＝黑雾」；v1.1 同一镜暗部 17.7%→10.8%、亮度回到 20 步水平、黑雾消失。

用法：
    ./.venv/Scripts/python.exe tools/switch_workflow.py --turbo 4
    ./.venv/Scripts/python.exe tools/switch_workflow.py --turbo 8
    ./.venv/Scripts/python.exe tools/switch_workflow.py --off
    ./.venv/Scripts/python.exe tools/switch_workflow.py --status
"""
import argparse
import datetime
import json
import os
import shutil
import sys

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CFG = os.path.join(ROOT, "config.json")

BASE = {
    "workflow_api_i2v": "templates/h3_i2v_api.json",
    "workflow_api": "templates/h3_t2v_api.json",
    "workflow_api_fl2va": "templates/h3_fl2va_api.json",
    "workflow_api_r2v": "templates/h3_r2v_api.json",
}
TURBO = {
    "workflow_api_i2v": "templates/h3_i2v_turbo%d_api.json",
    "workflow_api": "templates/h3_t2v_turbo%d_api.json",
    "workflow_api_fl2va": "templates/h3_fl2va_turbo%d_api.json",
}
# ── R2V 固定 4 步（2026-10-09 15:10 正式化，不随 --turbo 档位变化）──
# 历史：最初钉 8 步（lightx2v ref2v_turbo_8step_v1.0_768p），理由是"4 步版只有 544p v0.1"。
# 2026-10-09 实测推翻该判断 —— 同镜同参考图对比（镜2）：
#   · 4 步 ref2v_turbo_4step_v0.1（官方 Comfy-Org）→ **2m51s**，Lap 239.3、音频相关正常
#   · 8 步 ref2v_turbo_8step_v1.0_768p（lightx2v）→ 5m20s，Lap 只有 170.9
#   原因：8step LoRA 的 alpha=8 / rank=128 ⇒ ComfyUI 实算 scale=0.0625，**有效强度只有 4step 的 8%**，
#   等于裸底模在跑。4step 的 scale=1.0 满强度 ⇒ 4 步反而清晰、快 1.87 倍。
# ⇒ r2v 固定在 **4 步官方版**（shift 12/3，因该 LoRA 是 544p 训练）。
# ⚠️ 必须用 ref2v 专用 LoRA，不能挂 fl2v 版（两者层名 100% 相同，挂错不报错）。
R2V_FIXED = "templates/h3_r2v_turbo4_api.json"
CORE = ("workflow_api_i2v", "workflow_api", "workflow_api_fl2va")   # 必须有
LABEL = {"workflow_api_i2v": "i2v", "workflow_api": "t2v",
         "workflow_api_fl2va": "fl2va", "workflow_api_r2v": "r2v"}


def show(cfg):
    v = cfg["video"]
    for k in ("workflow_api_i2v", "workflow_api", "workflow_api_fl2va",
              "workflow_api_r2v"):
        cur = v.get(k, "")
        if cur == BASE.get(k, ""):
            kind = "非 turbo(20步)"
        elif "turbo4" in cur:
            kind = "turbo4(4步)"
        elif "turbo8" in cur:
            kind = "turbo8(8步)"
        else:
            kind = "其他"
        print("   %-20s %-40s %s" % (k, cur, kind))


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--turbo", choices=["4", "8"])
    g.add_argument("--off", action="store_true")
    g.add_argument("--status", action="store_true")
    a = ap.parse_args()

    cfg = json.load(open(CFG, encoding="utf-8"))

    if a.status:
        print("当前工作流配置：")
        show(cfg)
        return 0

    if a.off:
        target = dict(BASE)
    else:
        target = {k: (t % int(a.turbo)) for k, t in TURBO.items()}
        target["workflow_api_r2v"] = R2V_FIXED      # r2v 固定 8 步

    # 校验：核心三项必须有；r2v 缺文件时跳过（保留原工作流）
    skipped = []
    missing = []
    for k in list(target):
        if os.path.isfile(os.path.join(ROOT, target[k])):
            continue
        if k in CORE:
            missing.append(target[k])
        else:
            skipped.append((k, target[k]))
            target[k] = BASE[k]
    if missing:
        print("✗ 缺核心模板文件：")
        for m in missing:
            print("   ", m)
        print("\n先跑： ./.venv/Scripts/python.exe tools/make_turbo_templates.py")
        return 1
    for k, v in skipped:
        print("⚠️  %s 的 turbo 模板不存在（%s）⇒ 该路保持非 turbo" % (LABEL[k], v))
    if skipped:
        print()

    print("旧配置：")
    show(cfg)
    print()
    print("新配置：")
    for k, v in target.items():
        print("   %-20s %-38s %s" % (k, v, LABEL[k]))

    bak = os.path.join(ROOT, "output",
                       "config.bak_before_turbo_%s.json"
                       % datetime.datetime.now().strftime("%Y%m%d_%H%M%S"))
    shutil.copy2(CFG, bak)

    for k, v in target.items():
        cfg["video"][k] = v
    cfg["video"]["comment_turbo_switch"] = (
        "[2026-10-09] turbo LoRA 开关。--turbo 4/8 = 挂 distil LoRA 跑 4/8 步"
        "（采样器/调度器 = euler + simple，提速约 3.8 倍）；"
        "--off = 回到官方非 turbo 档（20 步，质量最好，适合最终出片）。"
        "r2v 固定 8 步：ref2v 的 4 步 LoRA 只有 v0.1（544p 训练），"
        "而 8 步版是 v1.0 768p —— 更新 + 分辨率更高 ⇒ 效果更好，不随档位切换。"
        "备份：%s" % os.path.basename(bak))

    with open(CFG, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)

    print()
    print("✓ 已切换为「%s」；备份 → output/%s"
          % ("非 turbo（20 步）" if a.off else "turbo%s（%s 步）" % (a.turbo, a.turbo),
             os.path.basename(bak)))
    print("  ⚠️ 改的是工作流模板 ⇒ 分镜 hash 未变，但生成结果会不同；")
    print("     若要重跑已完成的镜，需先 restage_rerun.py 归档旧片段。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
