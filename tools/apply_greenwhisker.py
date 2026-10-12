# -*- coding: utf-8 -*-
"""把「方源 = 花白头发 + 残破碧绿大袍」的设定落地到 config 与场1 分镜。

背景：原著开篇（重生前）方源是花白长发、残破碧绿大袍的老魔头，
      而此前资产/提示词一律写成 black robe / black hair —— 与设定不符。

改动范围：
  1) config.json
     - video.costume.by_scene["1"]  = 残破碧绿大袍（场1 专用；场2/4 少年方源仍是黑袍 default）
     - video.character.by_scene["1"]= 成年（中年）+ 花白 salt-and-pepper 长发
  2) storyboard_ch1_v3.json 的场1（镜1-20）文本
     - torn black robe / the black robe / black belt  → 碧绿
     - long straight black hair / long black hair      → 花白
     - 「黑色剪影」这类**不是服装**的 black 一律保留

幂等：全部用 str.replace，二次运行 no-op。
用法：
    python tools/apply_greenwhisker.py            # 干跑，只打印将发生的变化
    python tools/apply_greenwhisker.py --apply    # 落盘
"""
import argparse
import json
import os
import shutil
import sys

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(HERE)

COSTUME_SCENE1 = (
    "wearing a tattered dark jade-green long cross-collar robe, the silk dulled and "
    "frayed with its hem torn into hanging strips, over a plain off-white inner lining, "
    "a dark green cloth belt knotted at the waist"
)

CHARACTER_SCENE1 = (
    "the character is a lean middle-aged man with a long narrow face and high cheekbones, "
    "a hard angular jawline, deep-set sharp narrow half-lidded eyes with faint crow's feet "
    "at the corners, straight thin grey-streaked eyebrows, a cold composed resting face "
    "with naturally flat-set lips, a calm indifferent gaze, long straight loose hair in a "
    "grizzled salt-and-pepper mix of silver-white strands shot through with the remaining "
    "black, worn completely loose with no topknot no bun no hair band and no hairpin, "
    "pale weathered skin"
)

# 顺序敏感：长的先替，避免短规则吃掉长规则的匹配
EN_RULES = [
    ("torn black robe", "torn dark jade-green robe"),
    ("long straight black hair", "long straight grizzled silver-white hair"),
    ("long black hair", "long grizzled silver-white hair"),
    ("plain black cloth belt", "plain dark green cloth belt"),
    ("plain black belt", "plain dark green belt"),
    ("the black robe", "the dark jade-green robe"),
]
ZH_RULES = [
    ("破烂黑袍", "破烂的碧绿大袍"),
    ("黑袍残破", "碧绿大袍残破"),
    ("顺黑袍背部垂落的乌长直发", "顺碧绿袍背部落下的花白长直发"),
    ("长长的黑发", "长长的花白头发"),
    ("黑袍", "碧绿大袍"),
]
# 明确排除：这些 black 不是服装，禁止替换
KEEP_PATTERNS = ["black silhouette", "黑色剪影"]

SB_PATH = "assets/01_script/storyboard/storyboard_ch1_v3.json"
CFG_PATH = "config.json"
SB_FIELDS = ["video_prompt", "video_prompt_zh", "appearance", "video_prompt_zh", "scene"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="真正落盘（默认只干跑）")
    args = ap.parse_args()

    # ---------------- 1. 分镜 ----------------
    with open(SB_PATH, encoding="utf-8") as f:
        sb = json.load(f)

    changes = []
    for s in sb:
        if s.get("scene_no") != 1:
            continue
        for fld in SB_FIELDS:
            v = s.get(fld)
            if not v or not isinstance(v, str):
                continue
            old = v
            for a, b in EN_RULES + ZH_RULES:
                v = v.replace(a, b)
            if v != old:
                s[fld] = v
                changes.append((s["index"], fld))

    print(f"[1] 分镜场1 命中字段 {len(changes)} 处：")
    for idx, fld in changes:
        print(f"      镜{idx:>2} [{fld}]")

    # 守卫：确认没有把不该改的改掉
    for s in sb:
        if s.get("scene_no") != 1:
            continue
        for fld in SB_FIELDS:
            v = s.get(fld)
            if not isinstance(v, str):
                continue
            for pat in KEEP_PATTERNS:
                if pat in v:
                    print(f"    [OK] 镜{s['index']} [{fld}] 保留了 '{pat}'（非服装，未替换）")

    # ---------------- 2. config ----------------
    with open(CFG_PATH, encoding="utf-8") as f:
        cfg = json.load(f)
    v = cfg["video"]
    old_cost = (v.get("costume", {}).get("by_scene") or {}).get("1")
    old_char = (v.get("character", {}).get("by_scene") or {}).get("1")
    v.setdefault("costume", {}).setdefault("by_scene", {})["1"] = COSTUME_SCENE1
    v.setdefault("character", {}).setdefault("by_scene", {})["1"] = CHARACTER_SCENE1

    print("\n[2] config.video.costume.by_scene['1']")
    print("    旧:", (old_cost or "(空 → 用 default 黑袍)")[:110])
    print("    新:", COSTUME_SCENE1[:110])
    print("[2] config.video.character.by_scene['1']")
    print("    旧:", (old_char or "(空)")[:110])
    print("    新:", CHARACTER_SCENE1[:110])

    if not args.apply:
        print("\n（干跑）未写盘。加 --apply 落盘。")
        return

    shutil.copy(SB_PATH, SB_PATH + ".bak_greenwhisker")
    shutil.copy(CFG_PATH, CFG_PATH + ".bak_greenwhisker")
    with open(SB_PATH, "w", encoding="utf-8") as f:
        json.dump(sb, f, ensure_ascii=False, indent=1)
    with open(CFG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    print("\n[OK] 已落盘（原文件备份为 *.bak_greenwhisker）")


if __name__ == "__main__":
    main()
