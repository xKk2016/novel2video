# -*- coding: utf-8 -*-
"""场1 距离感修正：去掉「逼近 / 探身出圈 / 跨步向前」等位移措辞。

依据原文（重生前山巅血战）：
    「群敌环伺，早已经没有了生路。」
    「围攻他的正道群雄……牢牢包围着方源……」
    「他们没有动手，都忌惮着方源的临死反扑。」
    「一直静如雕塑的方源，慢慢转身。群雄顿时一阵骚动，齐齐后退一大步。」

→ 是「包围」，不是「逼近」：无人敢上前，更无肢体接触。方源一动，群雄反而后退。

原分镜里「leans forward out of the encircling crowd / one arm flung out /
past the shoulder / striding one step forward / lunging half a step forward」
这类**人物实际位移**会让模型拍成贴身叫骂，与设定冲突。

本脚本只改有位移的 4 镜（2 / 3 / 19 / 20）；镜 5、9、15 经复核只有
「at the front of the ring」「ring of enemies」「nearly spent」这类
位置/镜头推近措辞，不构成逼近，保持原样。

用法：
    python tools/patch_distance_shots.py --dry-run
    python tools/patch_distance_shots.py --apply
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

PATCHES = {
    2: {
        "video_prompt": (
            "Chinese donghua 2D cel-shaded anime style. [Shot 1] The camera sits behind "
            "the blood-soaked man in the torn black robe, looking past his back toward the "
            "front: only his back is in frame, his long loose hair and the torn black robe "
            "filling the left third of the picture in shadow. Facing the camera beyond him, "
            "across a wide stretch of bare rock, a burly middle-aged cultivator in white "
            "robes with a thick grey-streaked beard plants his feet and keeps his ground, "
            "one arm flung out in accusation, jaw tight, eyes blazing, not daring to step "
            "any closer. Golden hour warm side light catches the crowd's shoulders from "
            "behind the ridge. The camera pushes in slowly on the shouting man's face "
            "across the empty ground left between them."
        ),
        "video_prompt_zh": (
            "[镜2] 镜头位于那位浴血、黑袍残破的男子身后，越过他的背影朝前看：画面里只有他的"
            "背面，披散长发与破烂黑袍占据左侧三分之一并保持在暗部。他之外，隔着大片裸露岩"
            "石、远远站着一名留着花白浓须的白袍魁梧中年修士，双脚钉在原地不敢靠近，只一臂"
            "挥出怒指，牙关紧咬，双目怒睁。黄昏暖侧光从山脊后方勾出人群肩线。镜头越过两人之"
            "间空出的地面，缓慢推向喊话者的脸。"
        ),
    },
    3: {
        "video_prompt": (
            "Chinese donghua 2D cel-shaded anime style. [Shot 1] Medium shot of a young "
            "cultivator in blue robes with his hair tied in a high topknot standing his "
            "ground at the edge of the ring, his longsword held low with the tip pointed at "
            "the ground, chin lifted, mouth curled in cold contempt, his feet planted and "
            "refusing to come any closer. Crowd silhouettes mass far behind him, out of "
            "focus. Low golden side light rims his cheekbone and the blade edge. The camera "
            "holds him from across the wide empty ground of the ring, the rest of the "
            "encirclement stretching away behind."
        ),
        "video_prompt_zh": (
            "[镜3] 中景。一名将长发束成高髻的蓝袍青年修士立在包围圈边缘，长剑低垂、剑尖指"
            "地，抬着下巴，嘴角挂着冷酷的轻蔑，双脚钉在原地不肯再上前一步。身后远处人群剪影"
            "密集，焦点虚化。低角度暖金侧光勾出他的颧骨与剑刃亮边。镜头隔着包围圈中大片空地"
            "对着他，整个包围阵型在他身后铺开。"
        ),
    },
    19: {
        "video_prompt": (
            "Chinese donghua 2D cel-shaded anime style. [Shot 1] Close-up of the elderly "
            "cultivator in grey robes with the long white beard standing rooted where he is "
            "and shaking his staff at him from a distance, spittle flying, veins standing "
            "out on his forehead, too wary to move in. Cold side light with deep shadow. "
            "The camera pushes in hard on his face."
        ),
        "video_prompt_zh": (
            "[镜19] 特写。留着长白须的灰袍老修士双脚钉在原地，只远远地朝他挥杖怒喝，唾沫横"
            "飞，额上青筋暴起，忌惮得不敢上前。冷侧光带深影。镜头用力推近他的脸。"
        ),
    },
    20: {
        "video_prompt": (
            "Chinese donghua 2D cel-shaded anime style. [Shot 1] Wide shot: he stands alone "
            "at the centre as the ring of cultivators at last edges a single wary step inward "
            "from every side, weapons lifted but still held back, no one daring to be the "
            "first. He does not move. Then a blinding white core ignites at his chest and "
            "blows outward in one expanding shockwave, throwing a wall of dust and debris "
            "down the ridge and flinging the nearest attackers backwards. The camera pushes "
            "in hard through the blast and the frame goes white."
        ),
        "video_prompt_zh": (
            "[镜20] 大远景。他独自立于中央，包围圈终于从四面试探性地收拢一步，兵器举起却仍"
            "不敢落下，无人敢做第一个。他没有动。随后，一点炽白核心在他胸口亮起，向外炸开成"
            "一道猛烈扩张的冲击波，沿山脊推出一堵尘浪碎石墙，最靠前的攻击者被掀飞。镜头迎着"
            "爆风猛烈推近，画面转成一片炽白。"
        ),
    },
}


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    with open(SB, encoding="utf-8") as f:
        shots = json.load(f)

    by_idx = {int(s["index"]): s for s in shots}
    changed = 0

    for idx, patch in sorted(PATCHES.items()):
        s = by_idx.get(idx)
        if s is None:
            print(f"[SKIP] 镜{idx} 不存在")
            continue
        touched = []
        for field, new in patch.items():
            old = str(s.get(field) or "")
            if old == new:
                continue
            if args.dry_run:
                print(f"\n{'=' * 70}\n镜{idx} · {field}  (旧 {len(old)} 字符 → 新 {len(new)} 字符)")
                print(f"--- 旧 ---\n{old}\n--- 新 ---\n{new}")
            s[field] = new
            touched.append(field)
        if touched:
            changed += 1
            if args.apply:
                print(f"[OK] 镜{idx} 已更新 {touched}")

    if args.dry_run:
        print(f"\n[dry-run] 将修改 {changed} 镜，未落盘。")
        return

    bak = os.path.join(
        ROOT, "output",
        f"storyboard_ch1_v3.bak_before_distance_{datetime.datetime.now():%Y%m%d_%H%M%S}.json",
    )
    shutil.copy2(SB, bak)
    # 原文件即 indent=1、无末尾换行；保持一致，避免整文件 diff 噪声。
    with open(SB, "w", encoding="utf-8") as f:
        json.dump(shots, f, ensure_ascii=False, indent=1)
    print(f"\n[apply] 已修改 {changed} 镜；备份 → {os.path.basename(bak)}")


if __name__ == "__main__":
    main()
