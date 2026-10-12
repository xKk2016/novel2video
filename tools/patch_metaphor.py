# -*- coding: utf-8 -*-
"""修「修辞/成语被字面化」与「重复人物」两类 prompt 缺陷（幂等 + 备份）。

背景（2026-10-06，老板实跑镜1/2 后反馈）：

1) 【修辞曲解】镜1 把「残阳如血」当成了字面意义的血泊。
   源头在 rewrite_ch1_v2.py:124 ——「青茅山山巅，残阳如血，乌云压顶。荒芜的
   灰白岩石山脊空无一人，石缝间积着一滩暗红的血水」。这句本身自相矛盾：
   「空无一人」却「积着一滩血水」，血没有来源。v3 直接继承了这个意象。
   原文实际是「落日的余晖将山边的晚霞点燃，一时间绚烂如火」——「如血」形容的是
   天边晚霞的颜色，不是地上的血。
   ⇒ 镜1 删掉地上血泊（画面无人则血无来源），把「如血」正确落到天空/晚霞。
   ⚠️ 血泊本身不是错的：原文「方源脚下已经积了一大滩的血水」，所以**方源在场**的
      镜头（镜 9/20/21）保留血泊是对的，只清「无人却有血」的镜 1。

2) 【比喻实体化】英文 prompt 里 `like ...` 句型会把喻体画成实体：
   镜9 `like a war banner`（怕画出一面旗）、镜10 `like an old well`（怕画出一口井）。
   ⇒ 改成不引入新物件的写法。

3) 【重复人物】镜2 出现两个绿袍背影：锚图 peak_dusk_siege 自带方源背影 +
   参考图 back.png + prompt 又描述背影，三重叠加。
   ⇒ prompt 明写「整幅画面只有这一道背影」。

4) 【音频噪声】镜1 纯环境音却全是高频摩擦噪声词（keening / hissing / scraping），
   实测 Peak -0.57dB、RMS -19dB，等于把风声当主体在放，听感就是「很大的噪音」。
   ⇒ 改为柔和克制的氛围音，明确「几乎无音效、压低在混音底层」。

用法：
    python tools/patch_metaphor.py --dry-run
    python tools/patch_metaphor.py --apply
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


# (镜号, 字段, 旧串, 新串)  —— 旧串必须唯一命中，否则报错不写
RULES = [
    # ---------------- 镜1：残阳如血 不是 地上的血泊 ----------------
    (1, "video_prompt",
     "golden hour warm side light raking low across the rock as the sun sinks into burning clouds. "
     "A bare grey mountain summit, cracked stone underfoot, a wide dark pool of spilled blood spreading "
     "between the boulders, dry grass flattened and shivering. No one in frame. The camera drifts slowly "
     "to the right along the silent ridge, the last red light sliding across the wet stone.",
     "golden hour warm side light raking low across the rock as the sun sinks low. The whole western sky "
     "is ablaze, the sunset cloud lit up in fiery crimson and deep red. A bare grey mountain summit, "
     "cracked stone underfoot, dry gravel and dry grass flattened and shivering. No one in frame - the "
     "whole summit is deserted and bare. The camera drifts slowly to the right along the silent ridge, "
     "the last red light sliding across the dry stone."),
    (1, "video_prompt_zh",
     "黄昏暖金侧光低角度扫过岩面，落日正沉入燃烧般的云海。光秃的灰白山巅，脚下岩面龟裂，"
     "巨石之间摊着一大片暗红血泊，枯草被风压伏、簌簌发抖。画面无人。"
     "镜头沿寂静山脊缓慢右移，最后一抹红光在湿石上缓缓滑过。",
     "黄昏暖金侧光低角度扫过岩面，落日西沉，半边天烧成绚烂的火红晚霞。"
     "光秃的灰白山巅，脚下岩面龟裂，干燥的碎石与枯草被风压伏、簌簌发抖；"
     "整座山巅空无一人、寸物皆无。"
     "镜头沿寂静山脊缓慢右移，最后一抹红光在干燥的岩面上缓缓滑过。"),
    (1, "audio_prompt",
     "Ambient sound: a thin high mountain wind keening across bare rock, dry grass hissing, a hollow echo "
     "rolling off the empty valley. SFX: one long low gust scraping loose gravel across stone.",
     "Ambient sound: soft steady wind moving across open high ground, quiet and unhurried, with a wide "
     "empty stillness underneath it. SFX: almost none - only one low continuous breath of air, kept "
     "distant and low in the mix."),
    (1, "audio_prompt_zh",
     "环境音：尖细的高山风掠过裸露岩面呜咽作响，枯草簌簌，空旷山谷传来空洞回声。"
     "音效：一阵低沉的长风推动碎石在岩石上摩擦滚过。",
     "环境音：柔和稳定的风掠过开阔高地，安静舒缓，底下是一片宽广的空寂。"
     "音效：几乎没有——只有一缕低沉绵长的气流，远远地压在混音最底层。"),

    # ---------------- 镜2：只许有一道背影 ----------------
    (2, "video_prompt",
     "only his back is in frame, his long loose hair",
     "only his back is in frame - this is the ONLY figure anywhere in the picture seen from behind, "
     "there is no second back-turned person anywhere in frame - his long loose hair"),
    (2, "video_prompt_zh",
     "画面里只有他的背面，披散长发",
     "画面里只有他这一道背面——整幅画面再无第二个背身人影——披散长发"),

    # ---------------- 镜5：风声噪声词 ----------------
    (5, "audio_prompt",
     "Ambient sound: wind keening, the massed low murmur of a hostile crowd.",
     "Ambient sound: soft wind over the ridge, the massed low murmur of a hostile crowd."),
    (5, "audio_prompt_zh",
     "环境音：风声呜咽，敌意人群稠密的低语。",
     "环境音：柔和的风掠过山脊，敌意人群稠密的低语。"),

    # ---------------- 镜9：如战旗 → 怕画出旗子 ----------------
    (9, "video_prompt",
     "the hem lifts and cracks in the wind like a war banner",
     "the hem snaps and cracks sharply in the wind"),
    (9, "video_prompt_zh",
     "衣摆被风掀起、啪啪作响如战旗",
     "衣摆被风掀起、猎猎作响"),

    # ---------------- 镜10：如古井 → 怕画出一口井 ----------------
    (10, "video_prompt",
     "unhurried and depthless like an old well, blinking once",
     "unhurried, depthless and utterly still, blinking once"),
    (10, "video_prompt_zh",
     "从容而深不见底，如古井一般，只眨了一下",
     "从容、深不见底、静得没有一丝波动，只眨了一下"),
    (10, "audio_prompt",
     "Ambient sound: wind thinning into a steady hiss.",
     "Ambient sound: wind thinning into a low steady wash."),
    (10, "audio_prompt_zh",
     "环境音：风声退成一条平稳的嘶响。",
     "环境音：风声退成一片平稳的低鸣。"),

    # ---------------- 镜15：比喻收紧 ----------------
    (15, "video_prompt",
     "with something like relief in them",
     "with a faint hint of relief in them"),
    (15, "video_prompt_zh",
     "眼中竟像有一丝释然",
     "眼中竟透出一丝释然"),
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
            failed.append((idx, field, "镜号不存在"))
            continue
        cur = s.get(field) or ""
        if old in cur:
            plan.append((idx, field, old, new))
        elif new in cur:
            skipped.append((idx, field, "已是新版"))
        else:
            failed.append((idx, field, "旧串未命中"))

    print("=" * 74)
    for idx, field, _, _ in plan:
        print("  [改] 镜%-3d %s" % (idx, field))
    for idx, field, why in skipped:
        print("  [跳] 镜%-3d %s (%s)" % (idx, field, why))
    for idx, field, why in failed:
        print("  [!!] 镜%-3d %s (%s)" % (idx, field, why))
    print("=" * 74)
    print("待改 %d 处，已是最新 %d 处，失败 %d 处" % (len(plan), len(skipped), len(failed)))
    if failed:
        print("存在未命中项，未写入任何内容。请核对旧串。")
        return 1
    if not plan:
        print("无事可做。")
        return 0
    if a.dry_run:
        print("（dry-run，未写入）")
        return 0

    bak = os.path.join(ROOT, "assets", "01_script", "storyboard",
                       "storyboard_ch1_v3.bak_before_metaphor_%s.json"
                       % datetime.now().strftime("%Y%m%d_%H%M%S"))
    shutil.copy2(SB, bak)

    touched = set()
    for idx, field, old, new in plan:
        s = by_idx[idx]
        s[field] = (s.get(field) or "").replace(old, new)
        touched.add(idx)

    # scene 字段是 video_prompt_zh 的人工截断副本 —— 内容变了就要跟着重建
    for idx in sorted(touched):
        s = by_idx[idx]
        s["scene"] = (s.get("video_prompt_zh") or "")[:60]

    with open(SB, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print("已写入。备份 → %s" % os.path.basename(bak))
    print("同步重建 scene 字段的镜：%s" % ", ".join(str(i) for i in sorted(touched)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
