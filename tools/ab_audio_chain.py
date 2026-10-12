"""对照实验：分离「生成端损坏」与「后处理端损坏」。

对同一个 raw 文件依次施加：
    A) 原样量测
    B) assemble 的音频滤镜（highpass + alimiter）
    C) 滤镜 + (-c:a aac)   ← 即 assemble.py 实际做的
再看 raw 与最终成片的关系，判定损坏发生在哪一环。
"""
import os
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8")
import numpy as np
import imageio_ffmpeg

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXE = imageio_ffmpeg.get_ffmpeg_exe()
TMP = os.path.join(ROOT, "output", "_diag")
os.makedirs(TMP, exist_ok=True)

AF = "highpass=f=80,alimiter=limit=0.7:level=false"


def measure(path):
    r = subprocess.run([EXE, "-v", "error", "-i", path,
                        "-f", "f32le", "-acodec", "pcm_f32le", "-ac", "2", "-"],
                       capture_output=True)
    a = np.frombuffer(r.stdout, dtype=np.float32)
    n = (len(a) // 2) * 2
    if n < 1024:
        return None
    x = a[:n].reshape(-1, 2)
    L, R = x[:, 0].astype(np.float64), x[:, 1].astype(np.float64)
    if L.std() < 1e-9 or R.std() < 1e-9:
        return None
    corr = float(np.corrcoef(L, R)[0, 1])
    mid = (L + R) / 2.0
    side = (L - R) / 2.0
    ratio = 10 * np.log10(((side ** 2).mean() + 1e-12) / ((mid ** 2).mean() + 1e-12))
    peak = 20 * np.log10(max(np.abs(x).max(), 1e-9))
    rms = 20 * np.log10(max(np.sqrt((x ** 2).mean()), 1e-9))
    return {"corr": corr, "side": float(ratio), "peak": float(peak), "rms": float(rms)}


def dur(path):
    r = subprocess.run([EXE, "-v", "error", "-i", path, "-f", "null", "-"],
                       capture_output=True, stderr=subprocess.STDOUT)
    return None


def transcode(src, dst, af=None, aac=False):
    cmd = [EXE, "-y", "-i", src]
    if af:
        cmd += ["-af", af]
    if aac:
        cmd += ["-c:a", "aac"]
    cmd += [dst]
    subprocess.run(cmd, capture_output=True)
    return dst


def show(label, path):
    m = measure(path)
    if not m:
        print("%-46s  静音/无法分析" % label)
        return
    size = os.path.getsize(path) / 1024.0
    print("%-46s corr=%.3f  Side/Mid=%+7.2f dB  Peak=%+6.2f  RMS=%+6.2f  %6.0f KB"
          % (label, m["corr"], m["side"], m["peak"], m["rms"], size))


def main():
    raw_healthy = os.path.join(ROOT, "output/_raw/h3_i2v_00091_.mp4")
    raw_broken = os.path.join(ROOT, "output/_raw/h3_i2v_00096_.mp4")
    clip = os.path.join(ROOT, "assets/04_clips/shot_001.mp4")

    print("=" * 118)
    print("A. 原始产物 / 成片（未经我加工）")
    print("-" * 118)
    show("[RAW 健康] h3_i2v_00091_ (11:53, simple)", raw_healthy)
    show("[RAW 损坏] h3_i2v_00096_ (01:40, simple)", raw_broken)
    if os.path.isfile(clip):
        show("[成片    ] assets/04_clips/shot_001.mp4", clip)

    print()
    print("=" * 118)
    print("B. 把「健康 raw」灌进 assemble 的处理链，看会不会被搞坏")
    print("-" * 118)
    show("健康 raw 原样", raw_healthy)
    p1 = transcode(raw_healthy, os.path.join(TMP, "h_af.mp4"), af=AF)
    show("  + highpass+alimiter", p1)
    p2 = transcode(raw_healthy, os.path.join(TMP, "h_af_aac.mp4"), af=AF, aac=True)
    show("  + highpass+alimiter + aac", p2)
    p3 = transcode(raw_healthy, os.path.join(TMP, "h_aac.mp4"), aac=True)
    show("  + 仅 aac", p3)

    print()
    print("=" * 118)
    print("C. 把「损坏 raw」的滤镜去掉，看能不能救回来")
    print("-" * 118)
    show("损坏 raw 原样", raw_broken)
    p4 = transcode(raw_broken, os.path.join(TMP, "b_nofilter.mp4"))
    show("  + 纯重封装 aac（无滤镜）", p4)
    p5 = transcode(raw_broken, os.path.join(TMP, "b_mono.mp4"), af="pan=mono|c0=0.5*c0+0.5*c1")
    show("  + 强制折叠单声道（诊断用）", p5)

    print("=" * 118)


if __name__ == "__main__":
    main()
