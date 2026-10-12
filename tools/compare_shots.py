# -*- coding: utf-8 -*-
"""多版同镜横向对比（时间线拼图 + 音频指标）。

用途：同一个镜号的不同生成参数版本放在一起比值。
  · 时间线拼图：每版抽 6 帧（0/24/48/72/96/120）横向排一行，上下堆叠
  · 音频指标：L/R 相关系数、Side/Mid 能量比(dB)、Peak
    —— L/R² ≥0.98 健康；0.6~0.98 亚健康；<0.6 损坏

用法：
  ./.venv/Scripts/python.exe tools/compare_shots.py \
      --item "20步|assets/04_clips/_archive/xxx/shot_002.mp4" \
      --item "A euler|assets/04_clips/shot_002.mp4" \
      --out output/_diag/cmp.png
"""
import argparse
import os
import subprocess
import sys

import cv2
import imageio_ffmpeg
import numpy as np

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FF = imageio_ffmpeg.get_ffmpeg_exe()

FRAMES = [0, 24, 48, 72, 96, 120]


def read_png(p):
    return cv2.imdecode(np.fromfile(p, np.uint8), cv2.IMREAD_COLOR)


def timeline(src, cols_w=380, tag=""):
    """抽 6 帧横排成一条。返回 BGR ndarray。"""
    cols = []
    for f in FRAMES:
        tmp = os.path.join(ROOT, "output/_diag", "_tmp_%s_%d.png" % (tag, f))
        subprocess.run([FF, "-y", "-loglevel", "error", "-i", src,
                        "-vf", "select=eq(n\\,%d)" % f, "-frames:v", "1", tmp],
                       check=False)
        im = read_png(tmp) if os.path.isfile(tmp) else None
        if im is not None:
            h = int(im.shape[0] * cols_w / im.shape[1])
            cols.append(cv2.resize(im, (cols_w, h), interpolation=cv2.INTER_AREA))
            os.remove(tmp)
        else:
            cols.append(np.zeros((int(cols_w * 9 / 16), cols_w, 3), np.uint8))
    return np.hstack(cols)


def audio(p):
    raw = p + ".f32"
    subprocess.run([FF, "-y", "-loglevel", "error", "-i", p,
                    "-f", "f32le", "-ac", "2", "-ar", "48000", raw], check=True)
    a = np.fromfile(raw, dtype="<f4")
    os.remove(raw)
    L = a[0::2].astype(np.float64)
    R = a[1::2].astype(np.float64)
    corr = 1.0 if (L.std() < 1e-9 or R.std() < 1e-9) else float(np.corrcoef(L, R)[0, 1])
    mid = (L + R) / 2
    side = (L - R) / 2
    sm = 10 * np.log10((float(np.mean(side ** 2)) + 1e-12) /
                       (float(np.mean(mid ** 2)) + 1e-12))
    return corr, sm, float(np.max(np.abs(a)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--item", action="append", required=True,
                    help="label|path，可重复")
    ap.add_argument("--out", default="output/_diag/compare.png")
    ap.add_argument("--width", type=int, default=380)
    a = ap.parse_args()

    items = []
    for it in a.item:
        if "|" not in it:
            raise SystemExit("--item 格式应为 label|path：%s" % it)
        lab, p = it.split("|", 1)
        full = p if os.path.isabs(p) else os.path.join(ROOT, p)
        items.append((lab.strip(), full))

    print("=" * 92)
    print("%-40s %10s %11s %8s" % ("", "L/R相关", "Side/Mid", "Peak"))
    rows = []
    for i, (lab, p) in enumerate(items):
        if not os.path.isfile(p):
            print("%-40s  ✗ 文件不存在" % lab)
            continue
        c, s, pk = audio(p)
        flag = " ✓健康" if c >= 0.98 else (" 亚健康" if c >= 0.6 else " ✗损坏")
        print("%-40s %10.3f %8.1f dB %8.3f%s" % (lab, c, s, pk, flag))

        strip = timeline(p, a.width, "t%d" % i)
        bar = np.full((40, strip.shape[1], 3), 255, np.uint8)
        txt = "%s   |   L/R %.3f  Peak %.3f" % (lab, c, pk)
        cv2.putText(bar, txt, (12, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.62,
                    (0, 0, 0), 2, cv2.LINE_AA)
        rows.append(np.vstack([bar, strip]))
        rows.append(np.full((7, strip.shape[1], 3), 228, np.uint8))
    print("=" * 92)

    if rows:
        out = np.vstack(rows[:-1])
        dst = a.out if os.path.isabs(a.out) else os.path.join(ROOT, a.out)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        cv2.imencode(".png", out)[1].tofile(dst)
        print("对比图 → %s  (%dx%d, %d KB)"
              % (a.out, out.shape[1], out.shape[0], os.path.getsize(dst) // 1024))
    return 0


if __name__ == "__main__":
    sys.exit(main())
