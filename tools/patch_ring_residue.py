# -*- coding: utf-8 -*-
"""清剿「围成圈」旧口径的**最后一层残留**（场1 镜3/5/12/17/19 + 镜21 距离锁）。

为什么还有残留
--------------
`patch_crowd_layout.py` 改的是「群雄从哪来、穿什么」，但镜头自身的**构图描述**里
仍写着「包围圈」（ring / encirclement）：
  · 镜3  `standing his ground at the edge of the ring` / `the wide empty ground of the ring`
  · 镜5  `at the front of the ring`
  · 镜19 audio `the ring closing in` —— 音频层也带旧口径，dump 提示词才看得到
另一类是**量词残留**（不算错但读着仍像围圈）：
  · 镜12 `那一圈正道群雄` → 应为「那一群」
  · 镜17 `The men around him go still` → 应为「身旁的人」

还有一类是**数据脱节**：镜3/5/18/19 的 `scene` 字段停在更早版本，
与 `video_prompt_zh` 说的已经不是一回事（如镜19 scene 写「猛地上前半步，木杖前戳」，
而 prompt 早已改成「双脚钉在原地…忌惮得不敢上前」—— 正好相反）。
`scene` 不参与最终提示词，但参与 `_uses_protagonist` 判定，脱节是隐患，一并重建。

最后，镜21（自爆）也挂着场1 距离锁「no one closes in」，而该镜正是气浪掀飞最近修士的爆点，
同样关掉（`distance_lock: false`）。

幂等 + 备份；`--dry-run` 只打印。
"""
import argparse
import json
import os
import re
import shutil
import sys
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SB = os.path.join(ROOT, "assets", "01_script", "storyboard", "storyboard_ch1_v3.json")

# (镜号, 字段, 旧串, 新串) —— 全部为定点替换，命中不到就跳过（幂等）
EDITS = [
    # ---- 镜3：构图描述去 ring ------------------------------------------
    (3, "video_prompt",
     "standing his ground at the edge of the ring",
     "standing his ground at the front of the scattered rank"),
    (3, "video_prompt",
     "The camera holds him from across the wide empty ground of the ring, "
     "the encirclement stretching away behind.",
     "The camera holds him from across the wide empty ground, "
     "the loose rank stretching away behind."),
    (3, "video_prompt_zh", "立在包围圈边缘", "立在散兵线最前"),
    (3, "video_prompt_zh",
     "镜头隔着包围圈中大片空地对着他，整个包围阵型在他身后铺开。",
     "镜头隔着大片空地对准他，松散的阵线在他身后铺开。"),
    # ---- 镜5 --------------------------------------------------------------
    (5, "video_prompt",
     "at the front of the ring", "at the front of the scattered rank"),
    (5, "video_prompt_zh", "包围圈前方", "阵线最前"),
    # ---- 镜12：量词 -------------------------------------------------------
    (12, "video_prompt_zh", "那一圈正道群雄", "那一群正道群雄"),
    # ---- 镜17：around him -------------------------------------------------
    (17, "video_prompt",
     "The men around him go still.", "The men nearest him go still."),
    (17, "video_prompt_zh", "周围的人静了下来。", "他身旁的人静了下来。"),
    # ---- 镜19：音频层 -----------------------------------------------------
    (19, "audio_prompt",
     "Ambient sound: wind, the ring closing in.",
     "Ambient sound: wind, a crowd shuffling uneasily on stone."),
    (19, "audio_prompt_zh", "风声，包围圈收拢。", "风声，人群在石面上不安地挪动。"),
]

# `scene` 重建规则：与 video_prompt_zh 保持一致（含 [镜N] 前缀，前 100 字符）
SCENE_REBUILD = [3, 5, 18, 19]
SCENE_LEN = 100

# 关闭距离锁的镜头（该镜语义与「无人敢靠近」相反）
DIST_OFF = [21]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    dry = not a.apply

    sb = json.load(open(SB, encoding="utf-8"))
    by_idx = {int(s["index"]): s for s in sb}
    todos = []

    for idx, field, old, new in EDITS:
        s = by_idx.get(idx)
        if s is None:
            print("[警告] 找不到镜%d" % idx)
            continue
        cur = str(s.get(field) or "")
        if old not in cur:
            print("[跳过] 镜%-3d %-16s 已是新口径" % (idx, field))
            continue
        s[field] = cur.replace(old, new)
        todos.append(("镜%d" % idx, field, old, new))

    for idx in SCENE_REBUILD:
        s = by_idx.get(idx)
        if s is None:
            continue
        zh = str(s.get("video_prompt_zh") or "")
        want = zh[:SCENE_LEN]
        if s.get("scene") == want:
            print("[跳过] 镜%-3d scene 已同步" % idx)
            continue
        todos.append(("镜%d" % idx, "scene（重建）", str(s.get("scene") or "")[:70], want[:70]))
        s["scene"] = want

    for idx in DIST_OFF:
        s = by_idx.get(idx)
        if s is None:
            continue
        if s.get("distance_lock") is False:
            print("[跳过] 镜%-3d 距离锁已关闭" % idx)
            continue
        todos.append(("镜%d" % idx, "distance_lock", repr(s.get("distance_lock")), "False"))
        s["distance_lock"] = False

    for where, field, o, n in todos:
        print("-" * 74)
        print("[%s] %s" % (where, field))
        print("  旧:", o)
        print("  新:", n)
    print("-" * 74)
    print("共 %d 处改动" % len(todos))

    if dry:
        print("\n（试运行，未写入。加 --apply 生效）")
        return 0
    if not todos:
        print("无需改动。")
        return 0

    bak = "%s.bak_before_ringresidue_%s.json" % (
        os.path.splitext(SB)[0], datetime.now().strftime("%Y%m%d_%H%M%S"))
    shutil.copy2(SB, bak)
    with open(SB, "w", encoding="utf-8") as f:
        json.dump(sb, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print("\n已写入。备份：%s" % os.path.basename(bak))

    # 自检：场1 是否还有真正的围圈词（排除 shivering / tearing 之类子串误报）
    pat = re.compile(r"\b(ring|rings|encircl\w*)\b|包围圈|围成一圈", re.I)
    left = []
    for s in sb:
        i = int(s["index"])
        if s.get("scene_no") != 1:
            continue
        for k in ("video_prompt", "video_prompt_zh", "audio_prompt",
                  "audio_prompt_zh", "scene"):
            for m in pat.finditer(str(s.get(k) or "")):
                t = str(s.get(k))
                left.append("镜%d %s: …%s…" % (i, k, t[max(0, m.start()-25):m.end()+25]))
    print("场1 复查：" + ("干净 ✓" if not left else ""))
    for x in left:
        print("   ", x)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
