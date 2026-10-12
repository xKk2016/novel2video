"""增益标定：在 D 方案（side×0.15）基础上，找出"不太响但够听"的增益值。

判据：跟健康基准 00091 对齐但**不超过**（老板要求「不要太响」）。
输出 Peak / RMS / 集成响度(LUFS)，供选档。

用法：
    ./.venv/Scripts/python.exe tools/tune_gain.py
"""
import os
import re
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8")
import numpy as np
import imageio_ffmpeg

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXE = imageio_ffmpeg.get_ffmpeg_exe()
TMP = os.path.join(ROOT, "output", "_diag", "_gain")
os.makedirs(TMP, exist_ok=True)

HEALTHY = os.path.join(ROOT, "output/_raw/h3_i2v_00091_.mp4")
SIMPLE = os.path.join(ROOT, "output/_raw/h3_i2v_00096_.mp4")

# D 方案核心：保留 Mid、Side 乘 0.15
K = 0.15
A = 0.5 + K / 2.0
B = 0.5 - K / 2.0
PAN = "pan=stereo|c0=%.4f*c0+%.4f*c1|c1=%.4f*c0+%.4f*c1" % (A, B, B, A)


def af(gain):
    return ("highpass=f=80," + PAN +
            ",volume=%.1fdB,alimiter=limit=0.9:level=false" % gain)


def run(src, afilter, dst):
    cmd = [EXE, "-y", "-i", src]
    if afilter:
        cmd += ["-af", afilter]
    cmd += ["-c:a", "aac", "-b:a", "192k", dst]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return dst


def basic(path):
    r = subprocess.run([EXE, "-v", "error", "-i", path,
                        "-f", "f32le", "-acodec", "pcm_f32le", "-ac", "2", "-"],
                       capture_output=True)
    a = np.frombuffer(r.stdout, dtype=np.float32)
    n = (len(a) // 2) * 2
    x = a[:n].reshape(-1, 2)
    L, R = x[:, 0].astype(np.float64), x[:, 1].astype(np.float64)
    corr = float(np.corrcoef(L, R)[0, 1])
    mid, side = (L + R) / 2.0, (L - R) / 2.0
    sm = 10 * np.log10(((side ** 2).mean() + 1e-12) / ((mid ** 2).mean() + 1e-12))
    peak = 20 * np.log10(max(np.abs(x).max(), 1e-9))
    rms = 20 * np.log10(max(np.sqrt((x ** 2).mean()), 1e-9))
    return corr, sm, peak, rms


def lufs(path):
    r = subprocess.run([EXE, "-i", path, "-af", "ebur128=peak=true", "-f", "null", "-"],
                       capture_output=True, text=True)
    out = r.stderr
    m = re.findall(r"I:\s+(-?[\d.]+)\s+LUFS", out)
    return float(m[-1]) if m else float("nan")


def main():
    print("=" * 108)
    print("基准")
    print("-" * 108)
    for label, p in [("健康 00091（参照）", HEALTHY), ("simple 00096（待修）", SIMPLE)]:
        c, s, pk, rms = basic(p)
        print("%-24s L/R=%.3f Side/Mid=%+7.2f Peak=%+7.2f RMS=%+7.2f LUFS=%+6.2f"
              % (label, c, s, pk, rms, lufs(p)))

    print()
    print("=" * 108)
    print("D 方案（side×%.2f）下各增益档" % K)
    print("-" * 108)
    print("%-12s %8s %10s %9s %9s %9s" % ("增益", "L/R相关", "Side/Mid", "Peak", "RMS", "LUFS"))
    rows = []
    for g in [3.0, 4.5, 6.0, 7.5, 9.0]:
        p = run(SIMPLE, af(g), os.path.join(TMP, "g%04.1f.mp4" % (g * 10)))
        c, s, pk, rms = basic(p)
        l = lufs(p)
        rows.append((g, p, c, s, pk, rms, l))
        mark = ""
        if -19.5 <= pk <= -17.5:
            mark = "  ← 推荐区间（比健康略轻）"
        print("%-12s %8.3f %+9.2f %+8.2f %+8.2f %+8.2f%s"
              % ("+%.1f dB" % g, c, s, pk, rms, l, mark))
    hc, hs, hpk, hrms = basic(HEALTHY)
    print("=" * 108)
    print("健康基准 Peak=%+.2f dB / RMS=%+.2f dB / LUFS=%+.2f" % (hpk, hrms, lufs(HEALTHY)))
    print("⇒ 对齐健康约需 +3.3 dB(LUFS)；\"不要太响\" 取对齐值上下 1 dB 内。")
    print("文件在:", TMP)


if __name__ == "__main__":
    main()
