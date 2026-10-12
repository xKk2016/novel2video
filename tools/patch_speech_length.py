# -*- coding: utf-8 -*-
"""加长「语音顶到片尾、说不完」的台词镜。

背景（2026-10-09 诊断）：
    分镜时长原按「字数 ÷ 4.0 字/秒」估算，但 H3 实际念白只有 3.5~3.75 字/秒，
    且短句会被显著拖长（实测镜20：7 字占 5.15s）。
    ⇒ 长台词镜语音贴死在最后一帧，没有收尾气口，听感"赶 / 没说完"。

**帧数由 tools/audit_duration.py 的同一套逻辑自动算出，不硬编码** ——
    ① 片段已生成 → 实测语音跨度（谱平坦度分离人声）
    ② 片段未生成 → max(字数/3.5, 4.8) + 0.8s 收尾
    建议帧数 = 向上吸附到 17k+5 网格

纳入条件：gap = 建议时长 − 现时长 > 0.4s

用法：
    ./.venv/Scripts/python.exe tools/patch_speech_length.py            # dry-run
    ./.venv/Scripts/python.exe tools/patch_speech_length.py --apply    # 落盘
"""
import argparse
import datetime
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from audit_duration import (TAIL_PAD, CLIPS, GRID, snap, measure_span)  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SB = os.path.join(ROOT, "assets", "01_script", "storyboard",
                  "storyboard_ch1_v3.json")
GAP_MIN = 0.4          # gap 超过这个才纳入
CPS_FALLBACK = 3.5     # 估算语速
MIN_SPAN = 4.8         # 跨度下限（短句拖长兜底）


def plan(d):
    """算出改动计划 [(idx, scene, old, new, span, src, gap)]。"""
    out = []
    for s in d:
        line = (s.get("line") or "").strip()
        if not line:
            continue
        i = s["index"]
        n = len(line)
        cur = s["length"]
        clip = os.path.join(CLIPS, "shot_%03d.mp4" % i)

        if os.path.isfile(clip):
            f0, f1 = measure_span(clip)
            span = round(f1 - f0, 2) if f1 else 0.0
            src = "实测"
        else:
            span = round(max(n / CPS_FALLBACK, MIN_SPAN), 2)
            src = "估算"

        nf = snap((span + TAIL_PAD) * 24)
        gap = round(nf / 24 - cur / 24, 2)
        if gap > GAP_MIN:
            out.append((i, s.get("scene_no"), cur, nf, span, src, gap))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="落盘（默认只 dry-run）")
    ap.add_argument("--file", default=SB)
    a = ap.parse_args()

    if not os.path.isfile(a.file):
        print("⛔ 分镜不存在：%s" % a.file)
        return 1

    d = json.load(open(a.file, encoding="utf-8"))
    rows = plan(d)

    print("分镜：%s" % os.path.relpath(a.file, ROOT))
    print("=" * 84)
    print("%-4s %-4s %-8s %-8s %-9s %-7s %-8s %-8s %s"
          % ("镜", "场", "旧帧", "新帧", "语音跨度", "依据", "旧时长", "新时长", "变化"))
    print("-" * 84)
    for i, sc, old, new, span, src, gap in rows:
        print("%-4d %-4d %-8d %-8d %-9.2f %-7s %-8.2f %-8.2f %+.2fs"
              % (i, sc, old, new, span, src, old / 24, new / 24, gap))
    print("-" * 84)

    s1 = [r for r in rows if r[1] == 1]
    s234 = [r for r in rows if r[1] != 1]
    print("共 %d 镜需加长（场1 %d 镜 / 场2/3/4 %d 镜），净增 %.2f 秒"
          % (len(rows), len(s1), len(s234),
             sum(r[6] for r in rows)))
    print("  旧总时长 %.2fs → 新总时长 %.2fs"
          % (sum(r[2] for r in rows) / 24, sum(r[3] for r in rows) / 24))

    if not rows:
        print("无需改动。")
        return 0
    if not a.apply:
        print("\n[DRY-RUN] 未落盘。加 --apply 执行。")
        return 0

    # ---- 备份 ----
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = os.path.join(ROOT, "output",
                       "storyboard_ch1_v3.bak_before_speechlen_%s.json" % ts)
    shutil.copy2(a.file, bak)

    # ---- 落盘前重新校验锚点（防并发/误改）----
    cur_map = {x["index"]: x.get("length") for x in d}
    bad = [(r[0], r[2], cur_map.get(r[0])) for r in rows
           if cur_map.get(r[0]) != r[2]]
    if bad:
        print("\n⛔ 锚点复核失败，中止：")
        for i, exp, got in bad:
            print("   镜%d 期望旧帧 %s，实际 %s" % (i, exp, got))
        return 1

    # ---- 写入 ----
    by_idx = {x["index"]: x for x in d}
    for i, sc, old, new, span, src, gap in rows:
        by_idx[i]["length"] = new
        by_idx[i]["duration"] = round(new / 24.0, 2)

    with open(a.file, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)

    # ---- 复验 ----
    chk = {x["index"]: x for x in json.load(open(a.file, encoding="utf-8"))}
    ok = all(chk[i]["length"] == new and
             abs(chk[i]["duration"] - round(new / 24.0, 2)) < 1e-6
             for i, sc, old, new, span, src, gap in rows)
    print("\n%s" % ("✓ 已落盘，复验通过" if ok else "⚠ 已落盘，但复验失败"))
    print("  备份 → %s" % os.path.relpath(bak, ROOT))
    print("  改动镜号：%s"
          % "、".join(str(r[0]) for r in rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
