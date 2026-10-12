#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把场1 镜20「群雄逼迫 + 方源自爆」拆成两镜，并修掉四处文字问题。

**为什么拆**（诊断见 `assets/01_script/reports/场1自爆段_逻辑审查_20261006.md`）：
镜20 原本在 7.29 秒里塞了 9 个递进动作（收拢→举兵→不动→胸口白核→冲击波→
尘浪碎石墙→掀飞→镜头猛推→转白），原文「群雄逼迫而来」与「轰的一声自爆」
本是两个独立节拍。H3 在这个时长里演不清，爆炸会糊成一片白光。

**拆法**：
  镜20  = 群雄压上（124 帧 / 5.17s）—— 去掉「仍不敢落下，无人敢做第一个」，
          让联军真的压上来（原文：「群雄逼迫而来」）
  镜21  = 自爆爆点（141 帧 / 5.88s）—— 新增，正面低角度，爆心可见

**顺延**：原 index >= 21 的全部 +1（场2/3/4 共 37 镜），
并同步中文 prompt 的 `[镜N]` 前缀。全片 57 -> 58 镜。

**同时修掉的文字问题**：
  镜 9  ——「扫视围成一圈的敌人」是 `patch_crowd_layout.py` 的漏网镜，
            改为与全片一致的「同向逼视」口径
  镜 13 —— 光位自相矛盾（「落日在他身后」+「暖侧光」）。改为自洽的逆光口径，
            与现有关键帧 shot_013.png 的实际画面（肩后落日 + 面部由天光提亮）一致
  镜 16 ——「若是刚炼成的春秋蝉有效…」原文是「这般想着」，属心声；
            `speech_mode` 由 on-screen 改为 off-screen / voiceover

⚠️ 镜号是「该镜走哪条路」的开关（关键帧 shot_NNN.png、片段 shot_NNN.mp4），
   顺延后必须同步归档 04_clips 里的旧片段，否则会被 `clip_is_valid`
   误判为「已完成」而跳过 —— 见 `tools/archive_misaligned_assets.py`。

幂等：检测到场1 已有 index=21 则整脚本跳过。
用法：
  python tools/patch_selfdestruct_split.py --dry-run
  python tools/patch_selfdestruct_split.py --apply
"""
import argparse
import json
import os
import re
import shutil
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SB = os.path.join(ROOT, "assets", "01_script", "storyboard", "storyboard_ch1_v3.json")

# ---------------------------------------------------------------- 镜 9
S9_EN_OLD = "as he turns his head slowly and scans the ring of enemies"
S9_EN_NEW = ("as he turns his head slowly and scans the massed front of enemies "
             "standing squared against him")
S9_ZH_OLD = "他缓慢转头，扫视围成一圈的敌人。"
S9_ZH_NEW = "他缓慢转头，扫视对面那一大片同向逼视他的各派修士。"

# ---------------------------------------------------------------- 镜 13
S13_EN_OLD = ("with his back to the ring, the burning sunset and green ridgelines behind his "
              "shoulder. His pale face takes on a faint flush in the red light.")
S13_EN_NEW = ("with his back to the massed host, the burning sunset and green ridgelines low on "
              "the horizon beyond his shoulder, rimming his outline from behind. The open dusk "
              "light and a warm side bounce lift his pale face into a faint flush of blood.")
S13_EN_OLD2 = "Golden hour warm side light, the sun a low disc behind him."
S13_EN_NEW2 = ("Golden hour backlight from the low sun behind him, his face still clearly "
               "readable against the open dusk sky.")
S13_ZH_OLD = ("此刻他面向镜头、背对包围圈，肩后是燃烧般的落日与层层青翠山脊。他苍白的脸在红光里泛起一层淡薄"
              "血色。")
S13_ZH_NEW = ("此刻他面向镜头、背对满地群敌，落日正低悬在他肩后的山脊线上，从背后给他镶出一圈暖边；黄昏"
              "天光与侧向暖反射提亮他苍白的脸，泛起一层淡薄血色。")
S13_ZH_OLD2 = "黄昏暖侧光，落日低悬在他身后。"
S13_ZH_NEW2 = "黄昏逆光，落日低悬在他身后，面部在开阔天光下依然清晰可读。"

# ---------------------------------------------------------------- 镜 20（改为只拍「压上」）
S20_ZH = (
    "[镜20] 大远景。他独自立在龟裂岩面中央，正道各派联军终于压上——散开的那一整条阵线同时向前踏进，"
    "兵器齐齐落下指向他，最靠前的几人已经逼到血泊边缘。他依旧没有动。镜头迎着压上来的阵线缓慢推进。"
)
S20_EN = (
    "[Shot 1] Wide shot: he stands alone in the middle of the cracked stone plateau as the allied "
    "host finally surges in — the whole scattered rank steps forward as one, every blade coming "
    "down and levelling at him, the nearest few pressing right up to the edge of the dark pool of "
    "blood. He still does not move. The camera pushes in slowly against the closing line."
)
S20_LINE = "群雄逼迫而来。"
S20_AMB = "wind rising hard, boots stamping forward across cracked stone"
S20_AMB_ZH = "风力拔高，靴底成片踏上龟裂岩面"
S20_SFX = "hundreds of blade edges coming down together, a host surging in as one"
S20_SFX_ZH = "成百兵器齐齐落下，人群同时向前压上的闷响"

# ---------------------------------------------------------------- 新镜 21（自爆）
S21_ZH = (
    "[镜21] 大远景，低机位仰拍。他立于画面正中，胸口一点炽白核心骤然亮起，随即向外炸开成一道猛烈扩张的"
    "冲击波；白光在同一瞬间吞没他的身形，沿山脊推出一堵尘浪与碎石墙，最靠前的修士被气浪掀得双脚离地倒飞。"
    "镜头迎着爆风猛烈推近，整个画面转成一片炽白。"
)
S21_EN = (
    "[Shot 1] Extreme wide shot from a low upward angle: he stands dead centre as a blinding white "
    "core ignites at his chest and blows outward in one expanding shockwave. The white light "
    "swallows his silhouette in that same instant, throwing a wall of dust and debris down the "
    "ridge and blasting the nearest cultivators off their feet backwards. The camera pushes in "
    "hard through the blast and the whole frame goes white."
)
S21_AMB = "wind roaring to a peak, then a sudden total pressure drop into dead silence"
S21_AMB_ZH = "狂风啸到顶点，随后气压骤降，陷入彻底的静默"
S21_SFX = "a deep concussive boom, rock shattering, debris tearing through the air"
S21_SFX_ZH = "沉闷巨大的爆响，岩石迸裂，碎块撕裂空气"

FRAME_MIN = 124  # H3 合法帧数下限（5.17s），实测集合步长 17


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    if not os.path.isfile(SB):
        sys.exit("找不到分镜文件 %s" % SB)

    with open(SB, encoding="utf-8") as f:
        data = json.load(f)

    if any(int(s.get("index", 0)) == 21 and s.get("scene_no") == 1 for s in data):
        print("场1 已有第 21 镜 —— 已拆过分，跳过。")
        return

    idx_set = {int(s["index"]) for s in data}
    for need in (9, 13, 16, 20):
        if need not in idx_set:
            sys.exit("分镜里找不到镜 %d，结构不符，中止。" % need)

    log = []
    orig20 = next(s for s in data if int(s["index"]) == 20)
    total_before = len(data)
    len20_old = orig20.get("length")
    n_shift = sum(1 for s in data if int(s["index"]) >= 21)

    # ---- 1. 镜 9
    s9 = next(s for s in data if int(s["index"]) == 9)
    if S9_EN_OLD in s9["video_prompt"]:
        s9["video_prompt"] = s9["video_prompt"].replace(S9_EN_OLD, S9_EN_NEW)
    if S9_ZH_OLD in s9["video_prompt_zh"]:
        s9["video_prompt_zh"] = s9["video_prompt_zh"].replace(S9_ZH_OLD, S9_ZH_NEW)
        s9["scene"] = s9["video_prompt_zh"][:80]
    log.append("镜 9  去「围成一圈」口径")

    # ---- 2. 镜 13
    s13 = next(s for s in data if int(s["index"]) == 13)
    for old, new in ((S13_EN_OLD, S13_EN_NEW), (S13_EN_OLD2, S13_EN_NEW2)):
        if old in s13["video_prompt"]:
            s13["video_prompt"] = s13["video_prompt"].replace(old, new)
    for old, new in ((S13_ZH_OLD, S13_ZH_NEW), (S13_ZH_OLD2, S13_ZH_NEW2)):
        if old in s13["video_prompt_zh"]:
            s13["video_prompt_zh"] = s13["video_prompt_zh"].replace(old, new)
    s13["scene"] = s13["video_prompt_zh"][:80]
    log.append("镜 13 光位改为自洽的逆光口径")

    # ---- 3. 镜 16
    s16 = next(s for s in data if int(s["index"]) == 16)
    # ⚠️ 现有旁白镜的写法是 speech_mode="off-screen voiceover" + speech_verb="says"
    #    （复合字符串，不是拆成两半）—— 见镜 10/15/20。别再写成 "off-screen"。
    s16["speech_mode"] = "off-screen voiceover"
    s16["speech_verb"] = "says"
    log.append("镜 16 心声改为 off-screen / voiceover")

    # ---- 4. 镜 20 改为「群雄压上」
    orig20["length"] = FRAME_MIN
    orig20["duration"] = round(FRAME_MIN / 24, 2)
    orig20["video_prompt"] = S20_EN
    orig20["video_prompt_zh"] = S20_ZH
    orig20["scene"] = S20_ZH[:80]
    orig20["line"] = S20_LINE
    orig20["audio_prompt"] = "Ambient sound: %s. SFX: %s." % (S20_AMB, S20_SFX)
    orig20["audio_prompt_zh"] = "环境音：%s。音效：%s。" % (S20_AMB_ZH, S20_SFX_ZH)
    log.append("镜 20 改为只拍「群雄压上」（%d 帧 / %.2fs）" % (FRAME_MIN, FRAME_MIN / 24))

    # ---- 5. 顺延 index >= 21（含中文 prompt 的 [镜N] 前缀）
    for s in data:
        i = int(s["index"])
        if i >= 21:
            s["index"] = i + 1
            s["video_prompt_zh"] = re.sub(
                r"^\[镜%d\]" % i, "[镜%d]" % (i + 1), s["video_prompt_zh"]
            )
    log.append("原 index>=21 的 %d 镜顺延 +1（含 [镜N] 前缀）" % n_shift)

    # ---- 6. 插入新镜 21
    shot21 = {
        "index": 21,
        "scene_no": 1,
        "shot_type": "action",
        "protagonist": True,
        "anchor": "peak_dusk",
        "continuity": "new_angle",
        "ref": "full",
        "anchor_mode": "prompt",
        "length": 141,
        "duration": round(141 / 24, 2),
        "video_prompt": S21_EN,
        "video_prompt_zh": S21_ZH,
        "audio_prompt": "Ambient sound: %s. SFX: %s." % (S21_AMB, S21_SFX),
        "audio_prompt_zh": "环境音：%s。音效：%s。" % (S21_AMB_ZH, S21_SFX_ZH),
        "scene": S21_ZH[:80],
        "line": "",
        "speaker_key": "",
        "speaker": "",
        "speech_mode": "on-screen",
        "speech_verb": "says",
        "appearance": "",
        "anchor_text": False,
    }
    pos = max(k for k, s in enumerate(data) if int(s["index"]) == 20)
    data.insert(pos + 1, shot21)
    log.append("插入新镜 21「自爆」（141 帧 / %.2fs）" % (141 / 24))

    # ---- 校验
    idx = [int(s["index"]) for s in data]
    ok_cont = idx == list(range(1, len(data) + 1))
    if not ok_cont:
        sys.exit("!! 顺延后 index 不连续：%s" % idx[:5] + " ...")

    print("将执行：")
    for line in log:
        print("  ·", line)
    print()
    print("镜数 %d -> %d ；场1 镜数 20 -> 21" % (total_before, len(data)))
    tot = sum(s.get("length", 0) for s in data) / 24
    print("全片总时长 %.1f 秒（%.2f 分钟）" % (tot, tot / 60))
    print("场1 时长变化：镜20 %.2fs -> 镜20 %.2fs + 镜21 %.2fs" % (
        len20_old / 24, FRAME_MIN / 24, 141 / 24))

    if a.dry_run or not a.apply:
        print("\n[dry-run] 加 --apply 生效。")
        return

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = os.path.join(os.path.dirname(SB),
                       "storyboard_ch1_v3.bak_before_split20_%s.json" % stamp)
    shutil.copy2(SB, bak)
    with open(SB, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print("\n已写入 %s\n备份 %s" % (SB, bak))


if __name__ == "__main__":
    main()
