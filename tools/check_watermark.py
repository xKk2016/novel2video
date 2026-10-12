#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把关键帧右下角（水印区）裁出来放大 N 倍、拼成一张检查图。

为什么需要：水印残影缩到 1/3 几乎看不见，必须放大目视（2026-10-06 踩过坑）。

用法：
    ./.venv/Scripts/python.exe tools/check_watermark.py --shots 3,4,5,6,8,17,18,19 --zoom 4
"""
import argparse
import os
import sys

import cv2
import numpy as np

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KF_DIR = os.path.join(ROOT, "assets", "03_keyframes")
OUT = os.path.join(ROOT, "output", "_kf_raw3", "watermark_check.png")


def read(path):
    data = np.fromfile(path, dtype=np.uint8)
    return cv2.imdecode(data, cv2.IMREAD_COLOR)


def write(path, img):
    ok, buf = cv2.imencode(".png", img)
    if not ok:
        raise RuntimeError("imencode 失败")
    buf.tofile(path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shots", required=True)
    ap.add_argument("--zoom", type=int, default=4)
    ap.add_argument("--cw", type=int, default=210, help="裁剪宽")
    ap.add_argument("--ch", type=int, default=150, help="裁剪高")
    ap.add_argument("--cols", type=int, default=4)
    a = ap.parse_args()

    shots = [int(x) for x in a.shots.split(",") if x.strip()]
    tiles = []
    for n in shots:
        p = os.path.join(KF_DIR, "shot_%03d.png" % n)
        if not os.path.isfile(p):
            print("!! 缺图 镜%d" % n)
            return 1
        img = read(p)
        h, w = img.shape[:2]
        crop = img[h - a.ch:, w - a.cw:]
        big = cv2.resize(crop, None, fx=a.zoom, fy=a.zoom, interpolation=cv2.INTER_NEAREST)
        cv2.putText(big, "shot %03d" % n, (14, 46), cv2.FONT_HERSHEY_SIMPLEX, 1.4,
                    (0, 0, 255), 3, cv2.LINE_AA)
        tiles.append(big)

    cols = a.cols
    rows = (len(tiles) + cols - 1) // cols
    th, tw = tiles[0].shape[:2]
    grid = np.full((rows * th, cols * tw, 3), 255, np.uint8)
    for i, t in enumerate(tiles):
        r, c = divmod(i, cols)
        grid[r * th:(r + 1) * th, c * tw:(c + 1) * tw] = t

    write(OUT, grid)
    print("已生成检查图（%dx 放大）：%s" % (a.zoom, OUT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
