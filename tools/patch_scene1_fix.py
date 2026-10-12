# -*- coding: utf-8 -*-
"""场1 前段的两个结构性修正（幂等 + 备份）。

背景（2026-10-06，dump 最终 prompt 时发现）：

1) 【镜1 被注入距离锁】镜1 是「画面无人」的空景建立镜头，却被场1 的距离锁
   追加了 `the scattered host stands ... facing him ... the nearest enemy` ——
   画面里根本没有人，却命令模型「让他面对他」。这会诱导模型**凭空生成人物**。
   距离锁本来只服务「环伺但忌惮」的有人镜头。
   ⇒ 镜1 置 `distance_lock: false`（沿用镜20/21 已有的单镜开关）。

2) 【镜2/11 的双背影】这两镜都走 R2V，`<Picture 1>` 是构图锚
   `peak_dusk_siege.png`，而**该锚图自身含一个方源背影**；同时 prompt 又用文字
   描述「方源背影占左侧三分之一」、参考图里还有 `<Picture 5>` back.png 专门锁定
   背影 —— 三重来源叠加，实测镜2 生成了**两个**绿袍背影（老板反馈「还是有一个
   奇怪的人背对着方源」）。
   ⇒ 把这两镜的 `anchor` 换回纯空景锚 `peak_dusk.png`（同一场景、无人无背影），
      场景锁定作用等价，但不再往画面里塞第二个人。方源背影由 back.png +
      prompt 描述承担。

用法：
    python tools/patch_scene1_fix.py --dry-run
    python tools/patch_scene1_fix.py --apply
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

DIST_OFF = [1]             # 空景镜头：关掉距离锁
ANCHOR_TO_EMPTY = [2, 11]  # 从含背影的 peak_dusk_siege 换回纯空景 peak_dusk


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    if not (a.dry_run or a.apply):
        ap.error("请指定 --dry-run 或 --apply")

    d = json.load(open(SB, encoding="utf-8"))
    by_idx = {int(s["index"]): s for s in d}

    plan, skipped = [], []
    for i in DIST_OFF:
        s = by_idx.get(i)
        if s is None:
            continue
        if s.get("distance_lock") is False:
            skipped.append("镜%d 距离锁已是关" % i)
        else:
            plan.append("镜%-3d distance_lock: %r → False" % (i, s.get("distance_lock")))
    for i in ANCHOR_TO_EMPTY:
        s = by_idx.get(i)
        if s is None:
            continue
        cur = s.get("anchor")
        if cur == "peak_dusk":
            skipped.append("镜%d 锚已是 peak_dusk" % i)
        else:
            plan.append("镜%-3d anchor: %s → peak_dusk" % (i, cur))

    print("=" * 72)
    for p in plan:
        print("  [改]", p)
    for p in skipped:
        print("  [跳]", p)
    print("=" * 72)
    print("待改 %d 处，已是最新 %d 处" % (len(plan), len(skipped)))
    if not plan:
        print("无事可做。")
        return 0
    if a.dry_run:
        print("（dry-run，未写入）")
        return 0

    bak = os.path.join(ROOT, "assets", "01_script", "storyboard",
                       "storyboard_ch1_v3.bak_before_scene1fix_%s.json"
                       % datetime.now().strftime("%Y%m%d_%H%M%S"))
    shutil.copy2(SB, bak)

    for i in DIST_OFF:
        by_idx[i]["distance_lock"] = False
    for i in ANCHOR_TO_EMPTY:
        by_idx[i]["anchor"] = "peak_dusk"

    with open(SB, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print("已写入。备份 → %s" % os.path.basename(bak))
    return 0


if __name__ == "__main__":
    sys.exit(main())
