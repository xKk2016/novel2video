# -*- coding: utf-8 -*-
"""镜12 提示词与关键帧对齐。

背景：镜12 原先走 I2V 接力，首帧取自镜11 尾帧 —— 而镜11 的 R2V 把场景重构到了
城池广场（远处楼阁 + 密密麻麻的人群方阵），与场1 的山巅完全不符。镜12 继承这张
错图，于是「转身露脸」的动作是在一个错误的地点、错误的光线下发生的，脸也崩了。

现改为 I2V 关键帧（同镜13 的处理方式）：首帧 = 人工关键帧 shot_012.png
（写实 3D CG，山巅黄昏，方源转身侧脸已入画，远处群雄保持距离）。

首帧既然已经是「转身完成」，提示词里的「from behind him / he begins to turn」
就与画面矛盾了，必须改写为「完成转身并定住」。

用法：
    python tools/patch_shot12_prompt.py --apply
"""
import argparse
import datetime
import json
import os
import shutil
import sys

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SB = os.path.join(ROOT, "output", "storyboard_ch1_v3.json")

NEW_EN = (
    "Chinese donghua 2D cel-shaded anime style. [Shot 1] He completes the turn and "
    "holds still: his long black hair settles and swings on past his shoulder, the torn "
    "hem lifting in the cold wind. Behind him and far below, the ring of distant "
    "cultivators recoils as one, tiny figures stepping back and pressing away from him. "
    "Warm low side light catches half of his face. The camera holds steady on him with "
    "only a slight slow push-in."
)
NEW_ZH = (
    "[镜12] 他完成转身后定住：长长的黑发顺过肩头继续轻摆，破烂衣摆被冷风掀起。身后远处"
    "那一圈正道群雄齐齐骚动后退，细小的人影纷纷向外退避。暖调低侧光打亮他半张脸。镜头稳"
    "住，只极缓地推近。"
)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    with open(SB, encoding="utf-8") as f:
        shots = json.load(f)

    s = next(x for x in shots if int(x["index"]) == 12)
    print(f"旧 EN: {s['video_prompt'][:110]}...")
    print(f"新 EN: {NEW_EN[:110]}...")
    if not args.apply:
        print("\n[dry-run] 未落盘。")
        return

    s["video_prompt"] = NEW_EN
    s["video_prompt_zh"] = NEW_ZH
    bak = os.path.join(
        ROOT, "output",
        f"storyboard_ch1_v3.bak_before_shot12_{datetime.datetime.now():%Y%m%d_%H%M%S}.json",
    )
    shutil.copy2(SB, bak)
    with open(SB, "w", encoding="utf-8") as f:
        json.dump(shots, f, ensure_ascii=False, indent=1)
    print(f"\n[apply] 镜12 已更新；备份 → {os.path.basename(bak)}")


if __name__ == "__main__":
    main()
