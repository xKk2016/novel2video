"""在"平色区"上检测方块网格：纯色区几乎无梯度，方块边界会形成周期性尖峰。

用相对坐标取固定区域（画面中部的袍子/腰带），对不同周期 p 计算
    excess(p) = mean(|dI| at x%p==0) - mean(|dI| 其他列)
取绝对值最大的 p 作为探测到的网格周期，excess 越大越明显。
"""
import os
import subprocess
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tts_client as tc

FF = tc.get_ffmpeg()


def gray(png):
    r = subprocess.run([FF, "-i", png], capture_output=True, text=True)
    import re
    m = re.search(r"(\d{2,5})x(\d{2,5})", r.stderr)
    w, h = int(m.group(1)), int(m.group(2))
    r = subprocess.run([FF, "-v", "error", "-i", png, "-f", "rawvideo",
                        "-pix_fmt", "gray", "-"], capture_output=True)
    a = np.frombuffer(r.stdout, dtype=np.uint8)
    return a[: w * h].reshape(h, w).astype(np.float32)


def analyze(png, x0=0.40, x1=0.60, y0=0.45, y1=0.75, pmin=4, pmax=32):
    g = gray(png)
    h, w = g.shape
    patch = g[int(h * y0):int(h * y1), int(w * x0):int(w * x1)]
    d = np.abs(np.diff(patch, axis=1)).mean(axis=0)
    best = []
    for p in range(pmin, pmax + 1):
        idx = np.arange(len(d))
        on = d[idx % p == 0].mean()
        off = d[idx % p != 0].mean()
        best.append((on - off, p, on, off))
    best.sort(reverse=True)
    top = best[:3]
    flat = d.mean()
    print(f"{os.path.basename(png):20s} {w}x{h} p({pmin}-{pmax}) 基线梯度={flat:5.2f}")
    for exc, p, on, off in top:
        print(f"     周期{p:2d}px  excess={exc:+.3f}  (边界{on:.2f} vs 普通{off:.2f})")


if __name__ == "__main__":
    for png in sys.argv[1:]:
        analyze(png)
        print()
