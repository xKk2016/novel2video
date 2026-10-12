# -*- coding: utf-8 -*-
"""镜1「草凭空生长」+ 镜2「方源一直在动」修复（第 18/19 轮）。

两条 bug 是**同一机理**：H3 必须有运动；主体只给「静态外观/状态」而没给动作时，
模型会自己发明一个运动让它「活起来」。

- 镜1：`dry grass flattened and shivering` —— `flattened` 是状态词、`shivering` 太弱
        → 模型自编了「草生长出来又退回去」（实测地面金黄色像素 0% → 10.3% → 0.94% 山峰曲线）。
- 镜2：方源描述全是静态外观、零动作动词；且推镜目标 `the shouting man's face` 指代不明，
        实测**推反了**，推在前景方源背影上 → 视觉上等价于「他朝镜头走来」。

修法三件套（全正面措辞；H3 走 BasicGuider、无 negative 分支，禁用 does not move 类）：
  1. 状态写成「已达成 + 保持」（flattened → sits low and holds still）
  2. 给元素指派**受限动作**（草 → stay rooted and keep their height, only tips trembling faintly）
  3. 加**排他性运动声明**（the only movement in the shot being ...）

用法：
    python tools/patch_shot12_motionfix.py            # dry-run
    python tools/patch_shot12_motionfix.py --apply
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

STYLE_2D = "Chinese donghua 2D cel-shaded anime style. "

# ---------------- 镜1 ----------------
S1_OLD = "dry gravel and dry grass flattened and shivering"
S1_NEW = (
    "dry gravel and low tufts of dry grass that sit low and hold still, staying rooted "
    "and keeping their height, only their tips trembling faintly in the steady wind"
)
S1_TAIL_OLD = (
    "The camera drifts slowly to the right along the silent ridge, the last red light "
    "sliding across the dry stone."
)
S1_TAIL_NEW = (
    "The camera drifts slowly to the right along the silent ridge, the last red light "
    "sliding across the dry stone; the only movement in the shot is the slow rightward "
    "drift of the camera and the steady wind through the grass."
)

S1_ZH_OLD_KW = "干燥的碎石与枯草被风压伏、簌簌发抖"
S1_ZH_NEW = (
    "干燥的碎石与低矮的枯草丛静静伏在原地、保持着原来的高度，草根牢牢扎住不动，"
    "只有草尖在稳定的风里轻轻发颤"
)
S1_ZH_TAIL_OLD = "镜头沿寂静山脊缓慢右移，最后一抹红光在干燥的岩面上缓缓滑过。"
S1_ZH_TAIL_NEW = (
    "镜头沿寂静山脊缓慢右移，最后一抹红光在干燥的岩面上缓缓滑过；"
    "整个画面里唯一的运动，只有镜头缓慢的右移，以及穿过草丛的稳定的风。"
)

# ---------------- 镜2 ----------------
S2_BODY_OLD = (
    "both of his hands are empty and hang loose at his sides, he holds no weapon and "
    "nothing at all in his hands"
)
S2_BODY_NEW = (
    "he stands rooted and perfectly motionless with his back square to the camera, his "
    "feet planted on the cracked stone and his shoulders level, his body holding the same "
    "place in frame throughout, only the loose ends of his long hair and the torn hem of "
    "his robe stirring faintly in the cold wind; both of his hands are empty and hang "
    "loose at his sides, he holds no weapon and nothing at all in his hands"
)
S2_PUSH_OLD = (
    "The camera pushes in slowly on the shouting man's face across the empty ground left "
    "between them."
)
S2_PUSH_NEW = (
    "The camera pushes in slowly, tightening on the distant white-robed cultivator's face "
    "across the empty ground between them, moving along its own axis only with no sideways "
    "drift, while the foreground figure stays rooted in the same place in frame, perfectly "
    "still and unmoving."
)

S2_ZH_BODY_OLD = (
    "他双手空着、自然垂在身侧，不持任何兵器、手中空无一物——"
    "披散长发与破烂的碧绿大袍占据左侧三分之一并保持在暗部。"
)
S2_ZH_BODY_NEW = (
    "他背对镜头、稳稳钉在原地、纹丝不动，双脚踩在龟裂的岩石上，双肩平齐，"
    "始终占据画面中同一个位置；只有披散的长发发梢与破烂衣摆被冷风轻轻掀动。"
    "他双手空着、自然垂在身侧，不持任何兵器、手中空无一物——"
    "披散长发与破烂的碧绿大袍占据左侧三分之一并保持在暗部。"
)
S2_ZH_PUSH_OLD = "镜头越过两人之间空出的地面，缓慢推向喊话者的脸。"
S2_ZH_PUSH_NEW = (
    "镜头缓慢推近，越过两人之间空出的地面，逐渐收紧到远处那位白袍修士的脸上；"
    "镜头只沿自身轴线推进、不做任何横向移动，而前景的身影始终停在画面中同一位置，"
    "纹丝不动。"
)


def strip_style(txt):
    if txt.startswith(STYLE_2D):
        return txt[len(STYLE_2D):], True
    return txt, False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    with open(SB, encoding="utf-8") as f:
        shots = json.load(f)

    by_idx = {int(s["index"]): s for s in shots}

    print("=" * 74)
    print("镜1 keyframes/anchor_mode:", by_idx[1]["anchor_mode"], "| ref:", by_idx[1]["ref"])
    print("镜2 keyframes/anchor_mode:", by_idx[2]["anchor_mode"], "| ref:", by_idx[2]["ref"])
    print("=" * 74)

    # ---- 镜1 ----
    s1 = by_idx[1]
    en1 = s1["video_prompt"]
    zh1 = s1["video_prompt_zh"]
    checks = [
        (S1_OLD in en1, "镜1 英文：草的那句"),
        (S1_TAIL_OLD in en1, "镜1 英文：结尾排他声明锚点"),
        (S1_ZH_OLD_KW in zh1, "镜1 中文：草的那句"),
        (S1_ZH_TAIL_OLD in zh1, "镜1 中文：结尾"),
    ]
    for ok, name in checks:
        print(("  ✓ 命中 " if ok else "  ✗ 未命中 ") + name)
    if not all(ok for ok, _ in checks):
        print("\n⛔ 镜1 锚点未全部命中，中止（避免误改）。")
        return 1

    en1 = en1.replace(S1_OLD, S1_NEW).replace(S1_TAIL_OLD, S1_TAIL_NEW)
    zh1 = zh1.replace(S1_ZH_OLD_KW, S1_ZH_NEW).replace(S1_ZH_TAIL_OLD, S1_ZH_TAIL_NEW)
    en1, stripped1 = strip_style(en1)

    # ---- 镜2 ----
    s2 = by_idx[2]
    en2 = s2["video_prompt"]
    zh2 = s2["video_prompt_zh"]
    checks2 = [
        (S2_BODY_OLD in en2, "镜2 英文：方源双手句"),
        (S2_PUSH_OLD in en2, "镜2 英文：推镜句"),
        (S2_ZH_BODY_OLD in zh2, "镜2 中文：方源双手句"),
        (S2_ZH_PUSH_OLD in zh2, "镜2 中文：推镜句"),
    ]
    for ok, name in checks2:
        print(("  ✓ 命中 " if ok else "  ✗ 未命中 ") + name)
    if not all(ok for ok, _ in checks2):
        print("\n⛔ 镜2 锚点未全部命中，中止（避免误改）。")
        return 1

    en2 = en2.replace(S2_BODY_OLD, S2_BODY_NEW).replace(S2_PUSH_OLD, S2_PUSH_NEW)
    zh2 = zh2.replace(S2_ZH_BODY_OLD, S2_ZH_BODY_NEW).replace(S2_ZH_PUSH_OLD, S2_ZH_PUSH_NEW)
    en2, stripped2 = strip_style(en2)

    print()
    print("-" * 74)
    print("【镜1 新版 EN】\n" + en1)
    print("\n【镜1 新版 ZH】\n" + zh1)
    print("-" * 74)
    print("【镜2 新版 EN】\n" + en2)
    print("\n【镜2 新版 ZH】\n" + zh2)
    print("-" * 74)
    print("旧 2D 风格串剥除：镜1=%s 镜2=%s" % (stripped1, stripped2))

    if not a.apply:
        print("\n[dry-run] 未落盘。加 --apply 生效。")
        return 0

    bak = os.path.join(
        ROOT, "output",
        "storyboard_ch1_v3.bak_before_shot12_motionfix_%s.json"
        % datetime.datetime.now().strftime("%Y%m%d_%H%M%S"),
    )
    shutil.copy2(SB, bak)

    s1["video_prompt"] = en1
    s1["video_prompt_zh"] = zh1
    s2["video_prompt"] = en2
    s2["video_prompt_zh"] = zh2

    with open(SB, "w", encoding="utf-8") as f:
        json.dump(shots, f, ensure_ascii=False, indent=1)

    print("\n[apply] 镜1 / 镜2 已更新；备份 → %s" % os.path.basename(bak))
    return 0


if __name__ == "__main__":
    sys.exit(main())
