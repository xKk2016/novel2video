# -*- coding: utf-8 -*-
"""修「凭空武器」+「音频响度顶满」两类问题（幂等 + 备份）。

背景（2026-10-06 晚，老板实跑镜1/2 后反馈）：
「声音方面还是没有改善，而且方源手里多了一把武器，实际上没有」
并问「会不会是之前 sample 改 normal 的问题」。

────────────────────────────────────────────────────────────
【一】凭空武器 —— 根因是距离锁在召唤武器，不是 scheduler

dump 镜2 最终 prompt 后，全篇**唯一的武器词**来自距离锁：
    `... the nearest enemy, every weapon levelled the same way toward him and not one
     turned on a companion, no one closes in ...`
模型把这句里「武器」的概念泛化到了前景人物（方源）身上，给他配了一把刀。

而且这句本来就违背原文 —— 原文写的是「**他们没有动手**，都忌惮着方源的临死反扑」，
群雄根本没举兵器。「举着兵器朝他」是改口径时加戏加出来的。
⇒ 距离锁去掉武器描述，改为贴原文的「无人有所动作」。
⇒ 镜2 再补一句「他双手空着」，双保险（他是过肩镜的前景主体，最容易被配武器）。

关于 scheduler：`normal` **不是原因**。它只改变低噪段的细化程度
（`simple` 末步 σ=0.387 硬着陆；`normal` 覆盖到 σ=0.126 再归零）——
**不会凭空引入一个语义物件**。语义物件由 prompt/参考图决定。已核对：
`front.png` / `back.png` 定妆图方源双手空空，`peak_dusk` 锚串无人物无武器。
`normal` 顶多让 prompt 里已有的暗示更容易被画实，属于**放大器不是起因**。

────────────────────────────────────────────────────────────
【二】音频响度顶满 —— 是 H3 的系统性行为，只能在混音环节治理

实测（astats）：新片 镜1 Peak −6.19 / 镜2 −1.09；归档旧片段
镜3 −0.75、镜5 −0.66、镜16 −2.97 —— **几乎每一镜都顶到接近满刻度**，
RMS 普遍在 −17~−22 dB（纯环境音镜该在 −30~−40）。
频谱上 镜2 是 0–15kHz **全频段均匀发亮**（宽带噪声），不是干净的语音。

⇒ 这是 H3 原生音频生成的行为，**改单镜 prompt 只能微调**（镜1 改后 Peak 从
  −0.57 降到 −6.19，是有效的，但全片其他镜照旧）。
⇒ 唯一能**统一治理**的位置是拼接环节（逐片段重编码时加滤镜；concat 是 `-c copy`）。
  已给 `assemble.py` 的 `concat_clips()` 加 `audio_norm` 参数，并在 `config.json`
  加 `video.loudnorm`。

本脚本另外两处：
- 镜2/17 的 `speaker` 去掉 `loud sharp`（尖锐音色是"刺耳"的直接来源；全片仅这两镜用它）。
- 镜2 的 `audio_prompt` 收敛环境音强度并明确混音层次。

用法：
    python tools/patch_audio_weapon.py --dry-run
    python tools/patch_audio_weapon.py --apply
"""

import argparse
import json
import os
import shutil
import sys
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CFG = os.path.join(ROOT, "config.json")
SB = os.path.join(ROOT, "assets", "01_script", "storyboard", "storyboard_ch1_v3.json")

AF = "highpass=f=80,afftdn=nr=10:nf=-35,alimiter=limit=0.7:level=false"
DIST_OLD = ("keeping a wide, wary distance, standing well back with clear open ground "
            "between him and the nearest enemy, every weapon levelled the same way toward "
            "him and not one turned on a companion, no one closes in")
DIST_NEW = ("keeping a wide, wary distance, standing well back with clear open ground "
            "between him and the nearest enemy, no one closes in")

SPK_OLD = "a loud sharp furious voice"
SPK_NEW = "a clear resonant adult male voice, forceful but controlled"

SB_RULES = [
    # 镜2：他双手空着（过肩镜前景主体，最容易被配武器）
    (2, "video_prompt",
     "there is no second back-turned person anywhere in frame - his long loose hair",
     "there is no second back-turned person anywhere in frame - both of his hands are empty "
     "and hang loose at his sides, he holds no weapon and nothing at all in his hands - "
     "his long loose hair"),
    (2, "video_prompt_zh",
     "整幅画面再无第二个背身人影——披散长发",
     "整幅画面再无第二个背身人影；他双手空着、自然垂在身侧，不持任何兵器、手中空无一物——披散长发"),
    # 镜2：环境音收敛 + 明确混音层次
    (2, "audio_prompt",
     "Ambient sound: mountain wind pressing through the crowd, sleeves and robes snapping. "
     "SFX: a sharp indrawn breath right before the shout, boots grinding on gravel.",
     "Ambient sound: soft wind over the ridge, the low murmur of a crowd, kept well back in the "
     "mix. SFX: one short indrawn breath before the shout, quiet footsteps on gravel. "
     "The spoken line sits clear and forward; everything else stays low and calm."),
    (2, "audio_prompt_zh",
     "环境音：高山风穿过人群，衣袖与袍角啪啪作响。音效：喊话前猛地吸气，靴底在碎石上碾磨。",
     "环境音：柔和的风掠过山脊，人群低语，远远地压在混音底层。"
     "音效：喊话前一次短促的吸气，碎石上轻轻的脚步声。对白清晰靠前，其余一概压低、保持平稳。"),
    # 镜2 / 镜17：去掉尖锐音色词
    (2, "speaker", SPK_OLD, SPK_NEW),
    (17, "speaker", SPK_OLD, SPK_NEW),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    if not (a.dry_run or a.apply):
        ap.error("请指定 --dry-run 或 --apply")

    cfg = json.load(open(CFG, encoding="utf-8"))
    sb = json.load(open(SB, encoding="utf-8"))
    by_idx = {int(s["index"]): s for s in sb}

    plan, skipped, failed = [], [], []

    # ---- config: 距离锁 ----
    dl = ((cfg.get("video") or {}).get("distance_lock") or {}).get("by_scene") or {}
    cur1 = dl.get("1", "")
    if DIST_NEW in cur1 and DIST_OLD not in cur1:
        skipped.append("config 距离锁已是无武器版")
    elif DIST_OLD in cur1:
        plan.append("config video.distance_lock.by_scene.1 —— 去掉武器句")
    else:
        failed.append("config 距离锁：旧串未命中")

    # ---- config: 拼配音滤镜 ----
    cur_af = (cfg.get("video") or {}).get("audio_filter")
    if cur_af == AF:
        skipped.append("config audio_filter 已就位")
    else:
        plan.append("config video.audio_filter = %r → %r" % (cur_af, AF))

    # ---- storyboard ----
    for idx, field, old, new in SB_RULES:
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

    print("=" * 76)
    for p in plan:
        print("  [改]", p)
    for p in skipped:
        print("  [跳]", p)
    for p in failed:
        print("  [!!]", p)
    print("=" * 76)
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

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    shutil.copy2(CFG, CFG + ".bak_before_audioweapon_%s" % stamp)
    shutil.copy2(SB, SB + ".bak_before_audioweapon_%s" % stamp)

    # config 写入
    if DIST_OLD in cur1:
        dl["1"] = cur1.replace(DIST_OLD, DIST_NEW)
    cfg.setdefault("video", {})["audio_filter"] = AF
    with open(CFG, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
        f.write("\n")

    # storyboard 写入
    touched = set()
    for idx, field, old, new in SB_RULES:
        s = by_idx[idx]
        s[field] = (s.get(field) or "").replace(old, new)
        touched.add(idx)
    for idx in sorted(touched):
        by_idx[idx]["scene"] = (by_idx[idx].get("video_prompt_zh") or "")[:60]
    with open(SB, "w", encoding="utf-8") as f:
        json.dump(sb, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print("已写入。备份后缀 .bak_before_audioweapon_%s" % stamp)
    print("重建 scene 的镜：%s" % ", ".join(str(i) for i in sorted(touched)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
