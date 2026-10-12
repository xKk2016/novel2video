"""响度策略对比：解决「各镜原始电平差 23 dB，统一增益会顶爆响镜」。

现状问题（2026-10-07 实测）
--------------------------
    raw 镜1(空镜)   Peak −24.61  RMS −39.20   ← 很轻
    raw 镜2(对白)   Peak  −1.63  RMS −19.38   ← 很响
两者差 23 dB。统一 +4.5 dB 后镜2 直接顶到 −0.83 dB（削顶风险），
而镜1 仍只有 −22.55 dB（偏轻）。

⇒ 需要「逐片段」而不是「全片统一」的电平策略。本脚本对比四种。

用法
----
    ./.venv/Scripts/python.exe tools/tune_loudness.py
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
TMP = os.path.join(ROOT, "output", "_diag", "_loud")
os.makedirs(TMP, exist_ok=True)

K = 0.15
A, B = 0.5 + K / 2.0, 0.5 - K / 2.0
PAN = "pan=stereo|c0=%.4f*c0+%.4f*c1|c1=%.4f*c0+%.4f*c1" % (A, B, B, A)

SRC = {
    "镜1": os.path.join(ROOT, "assets/04_clips/shot_001.mp4"),
    "镜2": os.path.join(ROOT, "assets/04_clips/shot_002.mp4"),
}

# 方案：名称 → 在 highpass+pan 之后追加的滤镜
PLANS = {
    "P1 现状 +4.5dB/lim0.9": "volume=4.5dB,alimiter=limit=0.9:level=false",
    "P2 +4.5dB/lim0.7": "volume=4.5dB,alimiter=limit=0.7:level=false",
    "P3 loudnorm I-20 TP-3": "loudnorm=I=-20:TP=-3:LRA=11",
    "P4 loudnorm I-24 TP-6": "loudnorm=I=-24:TP=-6:LRA=11",
}


def meas(path):
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
    r2 = subprocess.run([EXE, "-i", path, "-af", "ebur128", "-f", "null", "-"],
                        capture_output=True, text=True)
    mm = re.findall(r"I:\s*(-?[\d.]+)\s*LUFS", r2.stderr)
    lufs = float(mm[-1]) if mm else float("nan")
    return corr, sm, peak, rms, lufs


def run(src, tail, dst):
    af = "highpass=f=80," + PAN + "," + tail
    subprocess.run([EXE, "-y", "-i", src, "-af", af,
                    "-c:a", "aac", "-b:a", "192k", dst],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return dst


def main():
    print("=" * 116)
    print("原始片段（未处理）")
    print("-" * 116)
    print("%-8s %9s %11s %9s %9s %9s" % ("", "L/R相关", "Side/Mid", "Peak", "RMS", "LUFS"))
    for name, p in SRC.items():
        if not os.path.isfile(p):
            print("%-8s (缺)" % name); continue
        c, s, pk, rms, l = meas(p)
        print("%-8s %9.3f %8.2f dB %8.2f %8.2f %8.2f" % (name, c, s, pk, rms, l))

    for pname, tail in PLANS.items():
        print()
        print("=" * 116)
        print(pname)
        print("-" * 116)
        print("%-8s %9s %11s %9s %9s %9s   %s" % ("", "L/R相关", "Side/Mid", "Peak", "RMS", "LUFS", "判定"))
        lufs_list = []
        for name, p in SRC.items():
            if not os.path.isfile(p):
                continue
            dst = run(p, tail, os.path.join(TMP, "%s_%s.mp4" % (pname.split()[0], name)))
            c, s, pk, rms, l = meas(dst)
            lufs_list.append(l)
            warn = ""
            if pk > -1.0:
                warn = " ⚠ 削顶风险"
            elif pk > -3.0:
                warn = " ~ 接近满刻度"
            print("%-8s %9.3f %8.2f dB %8.2f %8.2f %8.2f%s" % (name, c, s, pk, rms, l, warn))
        if len(lufs_list) == 2 and lufs_list[0] == lufs_list[0]:
            print("   ⇒ 两镜响度差 %+.1f dB（越小越均匀）" % abs(lufs_list[0] - lufs_list[1]))
    print("=" * 116)
    print("理想：两镜 LUFS 接近（差 < 3 dB），且两镜 Peak 都 ≤ −3 dB（留削顶余量）。")
    print("文件在:", TMP)


if __name__ == "__main__":
    main()
