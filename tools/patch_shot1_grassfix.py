# -*- coding: utf-8 -*-
"""镜1 提示词 ↔ 新锚图对齐 + 镜20 血泊处置（第 21 轮）。

背景：老板发现「镜1 的参考帧里没有草」。深挖后确认三件事：
  1. 真因不是「状态词诱发过程」，而是**锚图 peak_dusk.png 是纯裸岩**（一小撮草都没有），
     提示词却写了草 → I2V 首帧是硬约束，H3 只能凭空补 → 表现成「草自己长出来」。
  2. 锚图天空饱和度仅 0.084（旧版 0.460），提示词写「ablaze / fiery crimson」完全不成立。
  3. 镜1 提示词**自己跟自己矛盾**：既写 `low tufts of dry grass` 又写 `deserted and bare`。

处置：
  · 已用 ImageGen 图生图重出锚图（保构图，只改天空为火红晚霞 + 石缝加零星枯草）。
  · 本脚本把镜1 提示词改成与新锚图一致 —— 删掉与「有草」冲突的 bare 表述。
  · 镜20 的地面血泊：原文是「方源脚下的灰白山石，早已经被鲜血染成了暗红」，
    **原文没有任何尸体**。故把 `the dark pool of blood` 改为忠于原文的
    「脚下的岩石被血染成暗红」，避免出现「一片血泊却无尸体」的逻辑硬伤。

用法：
    python tools/patch_shot1_grassfix.py            # dry-run
    python tools/patch_shot1_grassfix.py --apply
"""
import argparse
import datetime
import json
import os
import shutil
import sys

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SB = os.path.join(ROOT, "assets", "01_script", "storyboard", "storyboard_ch1_v3.json")

# ---------------- 镜1 ----------------
S1_OLD = "A bare grey mountain summit, cracked stone underfoot"
S1_NEW = "A grey mountain summit, cracked stone underfoot"
# 去掉与「有草」冲突的 deserted and bare
S1_OLD2 = "No one in frame - the whole summit is deserted and bare."
S1_NEW2 = "No one in frame - the whole summit stands empty and silent."
S1_ZH_OLD = "整座山巅空无一人、寸物皆无。"
S1_ZH_NEW = "整座山巅空无一人、寂静无声。"
# 中文「光秃」与新锚图（有草）冲突
S1_ZH_OLD2 = "光秃的灰白山巅，脚下岩面龟裂"
S1_ZH_NEW2 = "灰白的山巅，脚下岩面龟裂"

# ---------------- 镜20 ----------------
S20_OLD = "the nearest few pressing right up to the edge of the dark pool of blood"
S20_NEW = ("the nearest few pressing right up to the edge of the dark red stain "
           "spreading across the cracked stone at his feet")
S20_ZH_OLD = "最靠前的几人已经逼到血泊边缘"
S20_ZH_NEW = "最靠前的几人已经逼到他脚下那片染暗红了的岩面边缘"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    shots = json.load(open(SB, encoding="utf-8"))
    by = {int(s["index"]): s for s in shots}

    print("=" * 74)
    ok = True
    # --- 镜1 ---
    s1 = by[1]
    for old, name in [(S1_OLD, "镜1 EN bare grey"), (S1_OLD2, "镜1 EN deserted and bare"),
                      (S1_ZH_OLD, "镜1 ZH 寸物皆无"), (S1_ZH_OLD2, "镜1 ZH 光秃")]:
        txt = s1["video_prompt"] if "EN" in name else s1["video_prompt_zh"]
        hit = old in txt
        print(("  ✓ " if hit else "  ✗ ") + name)
        ok = ok and hit
    # --- 镜20 ---
    s20 = by[20]
    for old, name in [(S20_OLD, "镜20 EN dark pool of blood"),
                      (S20_ZH_OLD, "镜20 ZH 血泊边缘")]:
        txt = s20["video_prompt"] if "EN" in name else s20["video_prompt_zh"]
        hit = old in txt
        print(("  ✓ " if hit else "  ✗ ") + name)
        ok = ok and hit

    if not ok:
        print("\n⛔ 有锚点未命中，中止。")
        return 1

    e1 = s1["video_prompt"].replace(S1_OLD, S1_NEW).replace(S1_OLD2, S1_NEW2)
    z1 = (s1["video_prompt_zh"].replace(S1_ZH_OLD, S1_ZH_NEW)
                                 .replace(S1_ZH_OLD2, S1_ZH_NEW2))
    e20 = s20["video_prompt"].replace(S20_OLD, S20_NEW)
    z20 = s20["video_prompt_zh"].replace(S20_ZH_OLD, S20_ZH_NEW)

    print()
    print("-" * 74)
    print("【镜1 新版 EN】\n" + e1)
    print("\n【镜1 新版 ZH】\n" + z1)
    print("-" * 74)
    print("【镜20 新版 EN】\n" + e20)
    print("\n【镜20 新版 ZH】\n" + z20)
    print("-" * 74)

    if not a.apply:
        print("[dry-run] 未落盘。加 --apply 生效。")
        return 0

    bak = os.path.join(ROOT, "output",
                       "storyboard_ch1_v3.bak_before_grass_anchor_%s.json"
                       % datetime.datetime.now().strftime("%Y%m%d_%H%M%S"))
    shutil.copy2(SB, bak)

    s1["video_prompt"] = e1
    s1["video_prompt_zh"] = z1
    s20["video_prompt"] = e20
    s20["video_prompt_zh"] = z20

    json.dump(shots, open(SB, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("[apply] 镜1 / 镜20 已更新；备份 → %s" % os.path.basename(bak))
    return 0


if __name__ == "__main__":
    sys.exit(main())
