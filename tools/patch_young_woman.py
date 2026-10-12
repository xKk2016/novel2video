#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把「正道群雄丁」（镜 7 / 镜 8 那位说方源侮辱她的女修士）改年轻好看。

原文设定是「暗红袍中年女修士」，出图出来是 40+ 的沧桑妇人。
这里整体改写成「约二十岁的年轻女子，容貌清丽」，
保留三样不能动的身份标记：**暗红袍 / 素木簪束发 / 满面泪痕**，
以及「悲恸转为怨恨」的情绪线与台词（台词一字不改）。

顺带把镜 7 的群雄口径从 `standing at the far edge of the ring`（包围圈）
统一成散兵线同向 —— 和 2026-10-06 那轮 `patch_crowd_layout.py` 的口径对齐
（镜 7 当时漏在外面没改）。

幂等：重复跑只在旧文本还在时才动手。
用法：
  python tools/patch_young_woman.py --dry-run
  python tools/patch_young_woman.py --apply
"""
import argparse
import json
import os
import shutil
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SB = os.path.join(ROOT, "assets", "01_script", "storyboard", "storyboard_ch1_v3.json")

NEW_EN_7 = (
    "[Shot 1] Medium shot of a young female cultivator in dark red robes, "
    "a plain wooden pin binding her hair, only in her early twenties and notably "
    "pretty - clear fair skin, delicate even features, dark almond eyes, soft brows, "
    "lips pale and slightly parted - standing at the far edge of the loosely "
    "scattered host, one hand pressed hard over her own mouth, the other gripping "
    "her sleeve, tears cutting pale tracks through the thin dust on her face. "
    "Cold blue-grey side light, with the last warm rim still burning behind her. "
    "The camera pushes in slowly as grief turns into hatred."
)
NEW_ZH_7 = (
    "[镜7] 中景。一名束素木簪、身着暗红袍的年轻女修士立在散阵远端，"
    "约莫二十出头，容貌清丽——皮肤白净、五官秀致、眉目分明、唇色微白，"
    "一只手死死压住自己的嘴，另一只手攥紧袖口，泪水在她沾了薄尘的脸上冲出浅痕。"
    "冷蓝灰侧光，她身后还燃着最后一点暖色轮廓光。镜头缓慢推近，捕捉悲恸转为怨恨的过程。"
)
NEW_SPK_7 = (
    "the young female cultivator in dark red robes, a clear bitter voice "
    "rising into a shriek, speaking Mandarin Chinese"
)

NEW_EN_8 = (
    "[Shot 1] Close-up of the young woman's face, a plain wooden pin binding her "
    "hair, only in her early twenties and notably pretty - clear fair skin, delicate "
    "even features, dark almond eyes - as she tears her hand away from her mouth and "
    "shrieks, mouth wide, eyes wide and wet, tendons standing in her neck, loose hair "
    "stuck across her cheek. Cold side light; behind her the allied host dissolves "
    "into shadow, a loose mixed crowd of many differently coloured and cut robes, all "
    "turned the same way toward the man off frame, no weapon of theirs raised at her "
    "or at each other. The camera pushes in a little harder on the scream."
)
NEW_ZH_8 = (
    "[镜8] 特写。束木簪的年轻女修士把手从嘴边猛地扯开、尖声嘶吼，"
    "约莫二十出头，容貌清丽、皮肤白净、眉目秀致，"
    "双目圆睁、眼中带泪，脖颈青筋暴起，散发黏在颊侧。"
    "冷侧光；她身后正道各派联军溶入暗部，袍服颜色款式驳杂、无两人相同，"
    "所有人朝向同一方向、面朝画外那个人，无人对她或对彼此举起兵器。"
    "镜头在嘶吼中略加快推近。"
)
NEW_SPK_8 = NEW_SPK_7

# 镜号 -> (video_prompt, video_prompt_zh, speaker)
TARGETS = {
    7: (NEW_EN_7, NEW_ZH_7, NEW_SPK_7),
    8: (NEW_EN_8, NEW_ZH_8, NEW_SPK_8),
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    if not os.path.isfile(SB):
        sys.exit("找不到分镜文件 %s" % SB)

    with open(SB, encoding="utf-8") as f:
        data = json.load(f)

    changed = 0
    for s in data:
        try:
            idx = int(s.get("index"))
        except (TypeError, ValueError):
            continue
        if idx not in TARGETS:
            continue
        en, zh, spk = TARGETS[idx]
        before = (s.get("video_prompt"), s.get("video_prompt_zh"), s.get("speaker"))
        after = (en, zh, spk)
        if before == after:
            print("  镜 %d 已是目标状态，跳过" % idx)
            continue
        s["video_prompt"] = en
        s["video_prompt_zh"] = zh
        s["speaker"] = spk
        # scene 是 video_prompt_zh 的截断，同步替换
        s["scene"] = zh[:80]
        changed += 1
        print("  镜 %d：已改写（中年 -> 年轻清丽）" % idx)

    if changed == 0:
        print("无需改动。")
        return

    if a.dry_run or not a.apply:
        print("\n[dry-run] 将改动 %d 镜。加 --apply 生效。" % changed)
        return

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = os.path.join(os.path.dirname(SB), "storyboard_ch1_v3.bak_before_youngwoman_%s.json" % stamp)
    shutil.copy2(SB, bak)
    with open(SB, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print("\n已写入 %s\n备份 %s" % (SB, bak))


if __name__ == "__main__":
    main()
