# -*- coding: utf-8 -*-
"""关键帧 ↔ 提示词 一致性体检（第 20 轮 · 补充）。

上一版 `check_ref_prompt_consistency.py` 只查了**锚图**（i2v 用锚图当首帧），
但场1 里镜 9/12/13/15/16/20 是**有人工关键帧覆盖**的（`assets/03_keyframes/shot_NNN.png`）——
这时首帧是那张关键帧，不是锚图。必须用关键帧的真实内容去比对提示词。

输出 output/_diag/keyframe_prompt_check.md

用法：
    ./.venv/Scripts/python.exe tools/check_keyframe_prompt.py
"""
import json
import os
import re
import sys

import cv2
import numpy as np

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SB = os.path.join(ROOT, "assets", "01_script", "storyboard", "storyboard_ch1_v3.json")
KF = os.path.join(ROOT, "assets", "03_keyframes")
OUT = os.path.join(ROOT, "output", "_diag", "keyframe_prompt_check.md")

# 针对关键帧的「画面可验证断言」：提示词说 X → 图里必须能看到 X
# 这里只放**能靠肉眼/像素判断**的环境级断言，人物表情类不自动判。
VISUAL_ASSERTS = {
    "火红晚霞/天空炽烈": [r"\bablaze\b", r"fiery crimson", r"burning sunset"],
    "绿色山脊": [r"green ridgeline"],
    "血泊（地面）": [r"\bpool of blood\b", r"dark pool", r"blood on the ground"],
    "草": [r"\bgrass\b", r"\btuft"],
    "雨": [r"\brain\b"],
    "灯笼": [r"\blantern"],
    "蜡烛/油灯": [r"\bcandle", r"\boil lamp"],
    "雪": [r"\bsnow"],
    "武器出鞘/刀剑": [r"\bblade", r"\bsword", r"\bspear"],
    "尘土飞扬": [r"\bdust"],
    "群雄(远处人群)": [r"\bcrowd\b", r"\bhost\b", r"the rank"],
}


def imread_unicode(path):
    """cv2.imread 在中文路径下会失败 —— 用 imdecode 绕过。"""
    try:
        buf = np.fromfile(path, dtype=np.uint8)
        return cv2.imdecode(buf, cv2.IMREAD_COLOR)
    except Exception:
        return None


def main():
    shots = {int(s["index"]): s for s in json.load(open(SB, encoding="utf-8"))}
    kfs = sorted(f for f in os.listdir(KF)
                 if re.fullmatch(r"shot_\d{3}\.png", f))

    L = []
    W = L.append
    W("# 关键帧 ↔ 提示词 一致性体检")
    W("")
    W("> 场1 的镜 9/12/13/15/16/20 有人工关键帧覆盖 → 首帧 = 该关键帧（**硬约束**）。")
    W("> 提示词若点名该关键帧里不存在的元素，H3 只可能凭空生成。")
    W("")

    rows = []
    for fn in kfs:
        idx = int(fn[5:8])
        s = shots.get(idx)
        if not s:
            continue
        p = os.path.join(KF, fn)
        im = imread_unicode(p)
        if im is None:
            W("- ⚠ %s 读取失败" % fn)
            continue
        a = cv2.cvtColor(im, cv2.COLOR_BGR2RGB).astype(float)
        h, w, _ = a.shape
        mx, mn = a.max(2), a.min(2)
        sat = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1), 0)

        # 天空带（上 30%）
        sky = a[:int(h * 0.30)]
        sky_sat = sat[:int(h * 0.30)]
        sky_rg = (sky[:, :, 0] - sky[:, :, 1]).max()

        txt = (s.get("video_prompt", "") or "")
        hits = []
        for label, pats in VISUAL_ASSERTS.items():
            if any(re.search(pp, txt, re.I) for pp in pats):
                hits.append(label)

        rows.append(dict(idx=idx, sc=s["scene_no"], fn=fn, size="%dx%d" % (w, h),
                         bright=round(float(a.mean()), 1),
                         sky_sat=round(float(sky_sat.mean()), 3),
                         sky_rg=int(sky_rg), hits=hits, txt=txt))

    W("## 关键帧实测指标")
    W("")
    W("| 镜 | 场 | 文件 | 尺寸 | 全图亮度 | 天空饱和度 | 天空 R−G 最大 |")
    W("|---|---|---|---|---|---|---|")
    for r in sorted(rows, key=lambda x: x["idx"]):
        W("| %d | %d | %s | %s | %s | %s | %s |" % (
            r["idx"], r["sc"], r["fn"], r["size"], r["bright"],
            r["sky_sat"], r["sky_rg"]))
    W("")

    W("## 提示词里的画面断言（需人工对着关键帧核）")
    W("")
    for r in sorted(rows, key=lambda x: x["idx"]):
        W("### 镜 %d（场%d · %s）" % (r["idx"], r["sc"], r["fn"]))
        W("")
        W("- 亮度 %s ／ 天空饱和度 %s ／ 天空 R−G 最大 %s" % (
            r["bright"], r["sky_sat"], r["sky_rg"]))
        if r["sky_sat"] < 0.12 and r["sky_rg"] < 50:
            W("- ⚠ **天空饱和度极低**（%s）+ 无明显红橙偏移 → 若提示词要求"
              "「火红晚霞 / ablaze / fiery crimson」，首帧里并不存在" % r["sky_sat"])
        W("- 提示词画面断言：" + ("、".join(r["hits"]) if r["hits"] else "（无）"))
        W("")

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    open(OUT, "w", encoding="utf-8").write("\n".join(L))
    print("=" * 74)
    print("关键帧数：%d" % len(rows))
    for r in sorted(rows, key=lambda x: x["idx"]):
        flag = "⚠低饱和" if (r["sky_sat"] < 0.12 and r["sky_rg"] < 50) else " " * 6
        print("  镜%-3d %-14s 亮度%-6s 天空饱和%-6s R-G最大%-4s %s"
              % (r["idx"], r["fn"], r["bright"], r["sky_sat"], r["sky_rg"], flag))
    print("=" * 74)
    print("报表 → %s" % os.path.relpath(OUT, ROOT))


if __name__ == "__main__":
    main()
