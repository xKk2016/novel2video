# -*- coding: utf-8 -*-
"""抽帧网格对比工具（临时诊断用）。

用法:
    python tools/_diag_frame_grid.py --out output/_diag/_grid.png \
        --item "20step|path/to/a.mp4" --item "8step|path/to/b.mp4" ...
"""
import argparse
import os
import sys

import cv2
import numpy as np


def read_frames(path, n=7):
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        raise SystemExit("无法打开: " + path)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    idxs = ([total // 2] if n == 1
            else [int(round(i * (total - 1) / (n - 1))) for i in range(n)])
    frames = []
    for i in idxs:
        cap.set(cv2.CAP_PROP_POS_FRAMES, i)
        ok, fr = cap.read()
        if not ok:
            fr = np.zeros((h, w, 3), np.uint8)
        frames.append((i, fr))
    cap.release()
    return dict(total=total, w=w, h=h, fps=fps, frames=frames)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--item", action="append", required=True,
                    help='标签|视频路径')
    ap.add_argument("--cols", type=int, default=7)
    ap.add_argument("--cellw", type=int, default=360)
    ap.add_argument("--pad", type=int, default=6)
    args = ap.parse_args()

    rows = []
    for it in args.item:
        label, path = it.split("|", 1)
        info = read_frames(path, args.cols)
        print("%-12s %s  %dx%d  %d帧 %.2ffps" % (
            label, os.path.basename(path), info["w"], info["h"],
            info["total"], info["fps"]))
        cellh = int(args.cellw * info["h"] / info["w"])
        cells = []
        for i, fr in info["frames"]:
            fr = cv2.resize(fr, (args.cellw, cellh), interpolation=cv2.INTER_AREA)
            # 顶部标签条
            bar = np.zeros((22, args.cellw, 3), np.uint8)
            cv2.putText(bar, "f%d" % i, (6, 16), cv2.FONT_HERSHEY_SIMPLEX,
                        0.5, (0, 255, 255), 1, cv2.LINE_AA)
            cells.append(np.vstack([bar, fr]))
        row = np.hstack([np.hstack([c, np.full((c.shape[0], args.pad, 3), 40, np.uint8)])
                         for c in cells])
        # 左侧标签列
        lab = np.zeros((row.shape[0], 130, 3), np.uint8)
        cv2.putText(lab, label, (8, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.55,
                    (0, 255, 0), 1, cv2.LINE_AA)
        rows.append(np.hstack([lab, row]))

    W = max(r.shape[1] for r in rows)
    rows = [np.hstack([r, np.full((r.shape[0], W - r.shape[1], 3), 40, np.uint8)])
            for r in rows]
    grid = np.vstack([np.vstack([r, np.full((args.pad, W, 3), 40, np.uint8)])
                      for r in rows])
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    cv2.imwrite(args.out, grid)
    print("已写出:", args.out, grid.shape)


if __name__ == "__main__":
    main()
