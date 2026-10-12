"""音频修复方案对比：同时解决「simple 版声音小 + 立体声仍错乱」。

背景（2026-10-07 定标）
----------------------
把 scheduler 从 normal 切回 simple 后，听感变好，但实测立体声一致性仍坏
（L/R 0.421 vs 健康 0.991）。真实原因是 **simple 把整体电平压低了 17.6 dB**
（Peak −7.0 → −24.6 dB），噪声的绝对能量随之下塌 → "听着不浑了"。
老板戴耳机仍能听出与健康版的区别 ⇒ 立体声错乱并未消失。

于是两个待解问题：
  ① 立体声错乱仍在
  ② simple 版比健康版安静约 8 dB → 成片整体偏小声

修复思路
--------
H3 音频 latent 是 [B,32,2,T40]，**左右声道各生成各的**。正常时两者高度相关；
一旦失相关，双耳收到两段不相关信号 → 听感为"水泡/空间错乱/浑浊"。

把信号拆成 Mid=(L+R)/2 与 Side=(L−R)/2 后：
  - Mid 是两个声道的**共同成分**（真正的内容）
  - Side 是**差异成分**（错乱就住在这里）
⇒ 压制 Side 就能在不牺牲太多空间感的前提下消除错乱；
   折叠单声道（Side=0）最彻底，但完全失去立体声。

用法
----
    ./.venv/Scripts/python.exe tools/audio_fix_variants.py

产出
----
    output/_diag/audio_fix_AB.mp4    响度统一的听感素材（供老板戴耳机判断）
    output/_diag/_audiofix/*.mp4     各变体单独文件
"""
import os
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8")
import numpy as np
import imageio_ffmpeg

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXE = imageio_ffmpeg.get_ffmpeg_exe()
DIAG = os.path.join(ROOT, "output", "_diag")
TMP = os.path.join(DIAG, "_audiofix")
os.makedirs(TMP, exist_ok=True)

HEALTHY = os.path.join(ROOT, "output/_raw/h3_i2v_00091_.mp4")   # 11:53 健康基准
SIMPLE = os.path.join(ROOT, "output/_raw/h3_i2v_00096_.mp4")    # 01:40 simple 版

GAIN = 9.0   # dB，对齐健康基准（−24.6 → −15.6）
LIMIT = 0.9  # 线性峰值上限（≈ −0.9 dB）

# ★ 关键语法：pan=stereo|c0=<左输出>|c1=<右输出>，右侧用输入 c0=L / c1=R
def mid_side(k):
    """保留 Mid、把 Side 乘以 k。k=0 → 单声道；k=1 → 原样。"""
    a = 0.5 + k / 2.0
    b = 0.5 - k / 2.0
    return ("pan=stereo|c0=%.4f*c0+%.4f*c1|c1=%.4f*c0+%.4f*c1" % (a, b, b, a))


VARIANTS = [
    ("A_healthy_base", HEALTHY, ""),
    ("B_simple_raw", SIMPLE, ""),
    ("C_gain_only", SIMPLE, "volume=%.1fdB,alimiter=limit=%.2f:level=false" % (GAIN, LIMIT)),
    ("D_side_k015", SIMPLE, mid_side(0.15) + ",volume=%.1fdB,alimiter=limit=%.2f:level=false" % (GAIN, LIMIT)),
    ("E_side_k035", SIMPLE, mid_side(0.35) + ",volume=%.1fdB,alimiter=limit=%.2f:level=false" % (GAIN, LIMIT)),
    ("F_mono_fold", SIMPLE, mid_side(0.0) + ",volume=%.1fdB,alimiter=limit=%.2f:level=false" % (GAIN, LIMIT)),
]


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
    mid, side = (L + R) / 2.0, (L - R) / 2.0
    ratio = 10 * np.log10(((side ** 2).mean() + 1e-12) / ((mid ** 2).mean() + 1e-12))
    peak = 20 * np.log10(max(np.abs(x).max(), 1e-9))
    rms = 20 * np.log10(max(np.sqrt((x ** 2).mean()), 1e-9))
    return {"corr": corr, "side": float(ratio), "peak": float(peak), "rms": float(rms)}


def build(name, src, af):
    dst = os.path.join(TMP, name + ".mp4")
    cmd = [EXE, "-y", "-i", src]
    if af:
        cmd += ["-af", af]
    cmd += ["-c:a", "aac", "-b:a", "192k", dst]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return dst


def main():
    print("=" * 112)
    print("客观指标（GAIN=+%.1f dB，LIMIT=%.2f）" % (GAIN, LIMIT))
    print("-" * 112)
    print("%-20s %9s %11s %9s %9s   %s" % ("变体", "L/R相关", "Side/Mid", "Peak", "RMS", "判定"))
    files = []
    for name, src, af in VARIANTS:
        p = build(name, src, af)
        files.append((name, p))
        m = measure(p)
        if m is None:
            print("%-20s  无法分析" % name)
            continue
        if m["side"] <= -16 and m["corr"] >= 0.90:
            v = "✓ 立体声健康"
        elif m["side"] <= -12:
            v = "~ 接近健康"
        else:
            v = "✗ 错乱仍在"
        print("%-20s %9.3f %8.2f dB %8.2f %8.2f   %s"
              % (name, m["corr"], m["side"], m["peak"], m["rms"], v))
    print("=" * 112)

    # 生成响度统一的听感素材：A / C / D / F（跳过 B 原样——音量差太大，会干扰判断）
    pick = ["A_healthy_base", "C_gain_only", "D_side_k015", "F_mono_fold"]
    d = dict(files)
    inputs = []
    for n in pick:
        inputs += ["-i", d[n]]
    fc, labels = [], []
    for i, _ in enumerate(pick):
        fc.append(f"[{i}:a]loudnorm=I=-20:TP=-1.5:LRA=11,"
                  f"aformat=sample_rates=32000:channel_layouts=stereo,"
                  f"atrim=0:5,asetpts=N/SR/TB[s{i}]")
        labels.append(f"[s{i}]")
    fc.append("".join(labels) + f"concat=n={len(pick)}:v=0:a=1[aout]")

    out = os.path.join(DIAG, "audio_fix_AB.mp4")
    subprocess.run([EXE, "-y", *inputs,
                    "-f", "lavfi", "-i", "color=c=black:s=854x480:r=24",
                    "-filter_complex", ";".join(fc),
                    "-map", "[aout]", "-map", f"{len(pick)}:v",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "30",
                    "-c:a", "aac", "-b:a", "192k", "-shortest", out],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print("听感素材（已统一响度 −20 LUFS，各 5 秒）：", out)
    for i, n in enumerate(pick, 1):
        print("  第 %d 段（%2d-%2d 秒）: %s" % (i, (i - 1) * 5, i * 5, n))
    print()
    print("⚠ 戴耳机听。重点比第 1 段（健康基准）和第 3/4 段：还有没有'散/飘'的感觉。")


if __name__ == "__main__":
    main()
