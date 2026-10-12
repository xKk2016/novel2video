#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把场1 的镜 2/11 的 anchor 从 peak_dusk 改成构图锚 peak_dusk_siege（幂等）。

背景（方案 C）：这 2 镜都是「方源背影居中 + 群雄在对面」的构图，贯穿多镜、纯文字压不住
（H3 走 cfg=1，文字只是弱约束）→ 专门出了一张**含人物**的构图锚图 `peak_dusk_siege`，
给它们当 R2V 参考图，一次解决场景漂移。

但分镜里这 2 镜的 `anchor` 字段一直写着 `peak_dusk`（空景锚），等于那张构图锚图
从未挂上去 —— 本脚本补上这一步。

⚠️ **2026-10-06 变更：镜 20 已从本脚本迁出。** 拆镜后镜20 =「群雄压上」，改走人工关键帧
（首帧 `03_keyframes/shot_020.png`），anchor 切回纯环境锚 `peak_dusk` —— 因为锚不再是它的
首帧，只剩「文字锚」作用，而 siege 锚的 prompt 里那句 `a large loose ring … around him`
会顺手灌进 prompt（见 tools/patch_shot20_siege.py）。
⇒ **别把 20 加回 TARGETS**，否则重跑会把镜20 拉回 siege 锚，与关键帧打架。

⚠️ `peak_dusk_siege` 含人物（方源背影），**不能**给无主角空镜当环境底（那是 peak_dusk 的活）。

用法：python tools/patch_siege_anchor.py [--dry-run]
"""
import argparse
import json
import shutil
import sys
from datetime import datetime

SB = "assets/01_script/storyboard/storyboard_ch1_v3.json"
TARGETS = [2, 11]  # ⚠️ 20 已迁出，见 docstring，勿加回
OLD, NEW = "peak_dusk", "peak_dusk_siege"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    shots = json.loads(open(SB, encoding="utf-8").read())
    changed = []
    for s in shots:
        if s.get("index") in TARGETS:
            cur = s.get("anchor")
            if cur == OLD:
                s["anchor"] = NEW
                changed.append(s["index"])
            elif cur != NEW:
                print("!! 镜 %s 的 anchor 是 %r，既不是 %s 也不是 %s，跳过"
                      % (s["index"], cur, OLD, NEW))
    if not changed:
        print("无需改动（已是 %s，或 index 不匹配）" % NEW)
        return 0
    if a.dry_run:
        print("[dry-run] 将改这 %d 镜：%s -> %s" % (len(changed), changed, NEW))
        return 0
    bak = SB + ".bak_before_siege_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    shutil.copy2(SB, bak)
    with open(SB, "w", encoding="utf-8") as f:
        f.write(json.dumps(shots, ensure_ascii=False, indent=2) + "\n")
    print("已改 %d 镜 %s -> %s：%s" % (len(changed), OLD, NEW, changed))
    print("备份：%s" % bak)
    return 0


if __name__ == "__main__":
    sys.exit(main())
