# -*- coding: utf-8 -*-
"""清掉 `audio_prompt` 里的「元描述 / 否定 / 混音指令」——它们对 H3 不是声音内容（幂等 + 备份）。

背景（2026-10-07，老板看 dump 后反馈：**第 1 镜没有对白，但环境音生成也很奇怪**）。

镜1 当时的 `overall_soundscape` 是：
    soft steady wind moving across open high ground, quiet and unhurried, with a wide empty
    stillness underneath it. almost none - only one low continuous breath of air,
    kept distant and low in the mix.

**整段几乎没有一句在描述「声音」** —— `quiet and unhurried`（情绪/节奏）、
`wide empty stillness`（抽象）、`almost none`（否定）、`kept distant and low in the mix`
（混音指令）。H3 拿到这段，不知道要生成什么声音，只能乱生成。

**根因是上一轮我为了「降噪」把混音意图写进了 prompt** —— 这是把两个层次搞混了：

| 层次 | 该写什么 | 该由谁管 |
|---|---|---|
| **内容层**（`audio_prompt`） | 具体的、能听见的声音：风、雨、脚步、呼吸 | 提示词 |
| **混音层** | 响度、峰值、降噪、各轨比例 | `config.video.audio_filter`（ffmpeg 滤镜） |

⚠️ H3 走 `BasicGuider`，**只有一个条件输入、没有负面分支**——否定词与"压低"这类
元描述**不会被减去，反而会被当成描述内容登记进去**。官方口径：
**把禁止写成正面描述，直接写「应该有什么」。**

官方还规定 `overall_soundscape` 只放 **1-4 句**「环境音 / 动作音效 / 非语言人声」。
本项目 10/58 镜中招（其余多为"静下来"这类**声音事件**，属合理，不动）。

用法：
    python tools/patch_audio_meta.py --dry-run
    python tools/patch_audio_meta.py --apply
"""

import argparse
import json
import os
import shutil
import sys
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SB = os.path.join(ROOT, "assets", "01_script", "storyboard", "storyboard_ch1_v3.json")

# (镜号, 字段, 旧串, 新串) —— 新值一律「正面 + 具体 + 可听见」，不带 Ambient sound/SFX 前缀
RULES = [
    # 镜1：整段重写（原值几乎没有声音内容）
    (1, "audio_prompt",
     "Ambient sound: soft steady wind moving across open high ground, quiet and unhurried, "
     "with a wide empty stillness underneath it. SFX: almost none - only one low continuous "
     "breath of air, kept distant and low in the mix.",
     "a steady low wind moving across open rock at dusk, rising and falling in slow long gusts, "
     "dry grit skittering lightly over bare stone"),
    (1, "audio_prompt_zh",
     "环境音：柔和稳定的风掠过开阔高地，安静舒缓，底下是一片宽广的空寂。"
     "音效：几乎没有——只有一缕低沉绵长的气流，远远地压在混音最底层。",
     "黄昏时分，一阵低沉稳定的风掠过开阔岩面，在漫长的阵风里起伏，干燥的砂砾轻轻刮过裸露的石头"),

    # 镜2：去掉混音指令
    (2, "audio_prompt",
     "Ambient sound: soft wind over the ridge, the low murmur of a crowd, kept well back in the "
     "mix. SFX: one short indrawn breath before the shout, quiet footsteps on gravel. "
     "The spoken line sits clear and forward; everything else stays low and calm.",
     "soft wind over the ridge, the low murmur of a crowd, one short indrawn breath before the "
     "shout, quiet footsteps on gravel"),
    (2, "audio_prompt_zh",
     "环境音：柔和的风掠过山脊，人群低语，远远地压在混音底层。"
     "音效：喊话前一次短促的吸气，碎石上轻轻的脚步声。对白清晰靠前，其余一概压低、保持平稳。",
     "柔和的风掠过山脊，人群低语，喊话前一次短促的吸气，碎石上轻轻的脚步声"),

    # 镜13：去纯否定短语
    (13, "audio_prompt",
     "Ambient sound: the wind settling to a low steady tone, silence off the ridgeline. "
     "SFX: a soft exhale that turns into a quiet laugh.",
     "the wind settling into a low steady tone, a soft exhale that turns into a quiet laugh"),
    (13, "audio_prompt_zh",
     "环境音：风声落成低而稳定的长音，山脊之外一片寂静。音效：一声轻缓的呼气，转成极轻的笑。",
     "风声落成低而稳定的长音，一声轻缓的呼气，转成极轻的笑"),

    # 镜14：去 almost none / nearly silent
    (14, "audio_prompt",
     "Ambient sound: a soft hollow room tone with a faint city hum far away. "
     "SFX: almost none, the memory is nearly silent.",
     "a soft hollow room tone, a faint city hum far away, a low muffled rumble of distant traffic"),
    (14, "audio_prompt_zh",
     "环境音：柔软空荡的室内底噪，远处有极淡的城市嗡鸣。音效：几乎没有音效，这段记忆近乎无声。",
     "柔软空荡的室内底噪，远处极淡的城市嗡鸣，一阵低沉模糊的远处车流声"),

    # 镜17：去 nearly nothing
    (17, "audio_prompt",
     "Ambient sound: wind dropping away to nearly nothing, an uneasy crowd silence. "
     "SFX: a half-spoken breath catching in the throat.",
     "the wind falling away to a faint drift, the crowd gone quiet, a half-spoken breath "
     "catching in the throat"),
    (17, "audio_prompt_zh",
     "环境音：风声几乎落尽，人群陷入不安的死寂。音效：半句未出的话卡在喉咙里的一顿。",
     "风声落成若有若无的飘动，人群安静下来，半句未出的话卡在喉咙里的一顿"),

    # 镜43/48/58：「几乎无声 / 死寂」这类否定式，改成「声音怎么变化」的正面描述
    (43, "audio_prompt",
     "Ambient sound: rain, and the corridor going completely still. "
     "SFX: fabric falling silent, one hand stopping mid-gesture.",
     "rain steady on the eaves, the corridor falling quiet, fabric settling still, "
     "one hand stopping mid-gesture"),
    (43, "audio_prompt_zh",
     "环境音：雨声，走廊彻底静下来。音效：布料静住，一只手停在半途。",
     "雨声持续，走廊静下来，布料归于静止，一只手停在半途"),
    (48, "audio_prompt",
     "Ambient sound: rain falling steadily, water dripping from the eaves, the corridor now "
     "nearly silent. SFX: the last soft footsteps fading out, one lantern wick ticking.",
     "rain falling steadily, water dripping from the eaves, the corridor gone quiet, "
     "the last soft footsteps fading out, one lantern wick ticking"),
    (48, "audio_prompt_zh",
     "环境音：雨持续落下，水从檐口滴落，走廊已近乎无声。音效：最后几声轻步远去，一盏灯笼的灯芯轻响。",
     "雨持续落下，水从檐口滴落，走廊安静下来，最后几声轻步远去，一盏灯笼的灯芯轻响"),
    (58, "audio_prompt",
     "Ambient sound: rain steady outside, the room very quiet. "
     "SFX: one slow breath, then silence.",
     "rain steady outside, the room hushed, one slow breath, then the room settling quiet"),
    (58, "audio_prompt_zh",
     "环境音：屋外雨声持续，屋内极静。音效：一次缓慢的呼吸，随后归于沉默。",
     "屋外雨声持续，屋内安静下来，一次缓慢的呼吸，随后归于平静"),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    if not (a.dry_run or a.apply):
        ap.error("请指定 --dry-run 或 --apply")

    d = json.load(open(SB, encoding="utf-8"))
    by_idx = {int(s["index"]): s for s in d}

    plan, skipped, failed = [], [], []
    for idx, field, old, new in RULES:
        s = by_idx.get(idx)
        if s is None:
            failed.append("镜%d 不存在" % idx)
            continue
        cur = s.get(field) or ""
        if old in cur:
            plan.append("镜%-3d %s" % (idx, field))
        elif new in cur:
            skipped.append("镜%d %s 已是新版" % (idx, field))
        else:
            failed.append("镜%d %s 旧串未命中" % (idx, field))

    print("=" * 74)
    for p in plan:
        print("  [改]", p)
    for p in skipped:
        print("  [跳]", p)
    for p in failed:
        print("  [!!]", p)
    print("=" * 74)
    print("待改 %d 处，已是最新 %d 处，失败 %d 处" % (len(plan), len(skipped), len(failed)))
    if failed:
        print("存在未命中项，未写入任何内容。")
        return 1
    if not plan:
        print("无事可做。")
        return 0
    if a.dry_run:
        print("（dry-run，未写入）")
        return 0

    bak = os.path.join(ROOT, "assets", "01_script", "storyboard",
                       "storyboard_ch1_v3.bak_before_audiometa_%s.json"
                       % datetime.now().strftime("%Y%m%d_%H%M%S"))
    shutil.copy2(SB, bak)

    for idx, field, old, new in RULES:
        s = by_idx[idx]
        s[field] = (s.get(field) or "").replace(old, new)

    with open(SB, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print("已写入。备份 → %s" % os.path.basename(bak))
    return 0


if __name__ == "__main__":
    sys.exit(main())
