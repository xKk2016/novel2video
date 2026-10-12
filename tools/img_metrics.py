#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""场景锚/关键帧体检指标：亮度 / 死黑 / 过曝 / 锐度 / 饱和度。

用项目 venv 跑（需要 numpy + cv2）：
  ./.venv/Scripts/python.exe tools/img_metrics.py <图或目录> [<图或目录> ...]

⚠️ 项目 `.venv` 里只有 cv2、**没有 PIL** —— 别写成 `from PIL import Image`。
⚠️ 路径含中文（「蛊真人视频生成」），cv2.imread 会静默返回 None，
   必须走 np.fromfile + cv2.imdecode。

判据（skill §5.3）：
  - 死黑占比 (g<25)  > 60%  → 要考虑提亮
  - 锐度 Laplacian 方差   → 新代次应比旧代次明显更高（+30%~+143% 为历史区间）
  - 饱和度偏高 + 亮度低  → 典型「电影调色」症状
"""
import os
import sys

import cv2
import numpy as np

EXTS = {".png", ".jpg", ".jpeg", ".webp"}


def imread_u(path):
    """读图，兼容中文路径。cv2.imread 遇中文路径会静默返回 None。"""
    buf = np.fromfile(path, dtype=np.uint8)
    if buf.size == 0:
        raise IOError("读不到文件：%s" % path)
    im = cv2.imdecode(buf, cv2.IMREAD_COLOR)
    if im is None:
        raise IOError("解码失败：%s" % path)
    return im


def metrics(path):
    bgr = imread_u(path)
    a = bgr[:, :, ::-1].astype(np.float32)  # BGR -> RGB
    h, w = a.shape[:2]
    g = a[:, :, 0] * 0.299 + a[:, :, 1] * 0.587 + a[:, :, 2] * 0.114
    lap = np.zeros_like(g)
    lap[1:-1, 1:-1] = (
        g[:-2, 1:-1] + g[2:, 1:-1] + g[1:-1, :-2] + g[1:-1, 2:] - 4.0 * g[1:-1, 1:-1]
    )
    mx = a.max(axis=2)
    mn = a.min(axis=2)
    sat = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1e-6), 0.0)
    return {
        "size": "%dx%d" % (w, h),
        "mean": float(g.mean()),
        "dark": float((g < 25).mean() * 100.0),
        "blow": float((g > 250).mean() * 100.0),
        "sharp": float(lap.var()),
        "sat": float(sat.mean() * 100.0),
    }


def collect(args):
    out = []
    for p in args:
        p = os.path.abspath(p)
        if os.path.isdir(p):
            for n in sorted(os.listdir(p)):
                if os.path.splitext(n)[1].lower() in EXTS:
                    out.append(os.path.join(p, n))
        elif os.path.isfile(p):
            out.append(p)
        else:
            print("!! 不存在：%s" % p, file=sys.stderr)
    return out


def main():
    files = collect(sys.argv[1:])
    if not files:
        print(__doc__)
        return 1
    hdr = "%-46s %-11s %7s %7s %7s %9s %7s" % (
        "file", "size", "mean", "dark%", "blow%", "sharp", "sat%"
    )
    print(hdr)
    print("-" * len(hdr))
    for f in files:
        name = os.path.basename(f)
        if len(name) > 46:
            name = name[:22] + "..." + name[-21:]
        try:
            m = metrics(f)
        except Exception as e:  # noqa: BLE001
            print("%-46s  ERROR %s" % (name, e))
            continue
        print("%-46s %-11s %7.1f %7.1f %7.1f %9.1f %7.1f" % (
            name, m["size"], m["mean"], m["dark"], m["blow"], m["sharp"], m["sat"]
        ))
    return 0


if __name__ == "__main__":
    sys.exit(main())
