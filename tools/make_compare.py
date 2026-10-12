#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""拼图工具：把多张图（或同一区域裁切）拼成一张对比图，用于目视验收。

⚠️ 2026-10-06 由 PIL 改为 **cv2**：项目 `.venv` 里只有 `cv2` + `numpy`，**没有 PIL**
   （系统 python / 托管 python 则连 cv2 都没有）。本文件因此统一走
   `np.fromfile + cv2.imdecode` / `cv2.imencode + tofile`，兼容中文路径。

用法（用 ./.venv/Scripts/python.exe 跑）：
  # 横向拼接整图，自动缩放到统一高度
  tools/make_compare.py -o out.png img1.png img2.png img3.png

  # 只裁右下角区域再看（查水印残留）
  tools/make_compare.py --crop 1036,764,500,260 -o out.png img1.png img2.png

  # 分两行、每行 4 张
  tools/make_compare.py --cols 4 --height 400 -o out.png a.png b.png c.png d.png
"""
import argparse
import os
import sys

import cv2
import numpy as np


def read(path):
    data = np.fromfile(path, dtype=np.uint8)
    return cv2.imdecode(data, cv2.IMREAD_COLOR)


def write(path, img):
    ok, buf = cv2.imencode(".png", img)
    if not ok:
        raise RuntimeError("imencode 失败")
    buf.tofile(path)


def fit(img, h):
    ih, iw = img.shape[:2]
    w = max(1, round(iw * h / ih))
    return cv2.resize(img, (w, h), interpolation=cv2.INTER_AREA)


def ascii_only(s):
    return "".join(ch if 32 <= ord(ch) < 127 else "?" for ch in s)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("images", nargs="+")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--crop", default=None, help="x,y,w,h 统一裁切区域")
    ap.add_argument("--cols", type=int, default=0, help="每行张数；0=全部一行")
    ap.add_argument("--height", type=int, default=420, help="单张缩放后高度")
    ap.add_argument("--pad", type=int, default=8, help="格间距")
    ap.add_argument("--label", action="store_true", help="左上角标文件名（非 ASCII 会变 ?）")
    a = ap.parse_args()

    box = None
    if a.crop:
        box = tuple(int(v) for v in a.crop.split(","))
        assert len(box) == 4, "--crop 要 x,y,w,h 四个数"

    tiles = []
    for p in a.images:
        if not os.path.isfile(p):
            print("!! 跳过不存在：%s" % p, file=sys.stderr)
            continue
        im = read(p)
        if im is None:
            print("!! 读不出：%s" % p, file=sys.stderr)
            continue
        if box:
            x, y, w, h = box
            ih, iw = im.shape[:2]
            im = im[max(0, y):min(ih, y + h), max(0, x):min(iw, x + w)]
        tiles.append((os.path.basename(p), fit(im, a.height)))
    if not tiles:
        print("没有可拼接的图", file=sys.stderr)
        return 1

    cols = a.cols if a.cols > 0 else len(tiles)
    rows = (len(tiles) + cols - 1) // cols
    cw = max(t.shape[1] for _, t in tiles) + a.pad
    ch = max(t.shape[0] for _, t in tiles) + a.pad
    canvas = np.full((ch * rows + a.pad, cw * cols + a.pad, 3), 26, np.uint8)
    for i, (name, t) in enumerate(tiles):
        r, c = divmod(i, cols)
        x = a.pad + c * cw
        y = a.pad + r * ch
        canvas[y:y + t.shape[0], x:x + t.shape[1]] = t
        if a.label:
            tag = ascii_only(name if len(name) <= 34 else name[:16] + ".." + name[-16:])
            (tw, th), _ = cv2.getTextSize(tag, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
            cv2.rectangle(canvas, (x, y), (x + tw + 8, y + th + 10), (0, 0, 0), -1)
            cv2.putText(canvas, tag, (x + 4, y + th + 4), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                        (255, 255, 255), 1, cv2.LINE_AA)
    write(a.out, canvas)
    print("已写出 %s  (%dx%d, %d 张)" % (a.out, canvas.shape[1], canvas.shape[0], len(tiles)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
