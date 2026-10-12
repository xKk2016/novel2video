"""A/B 听感对比：把「健康基准 / normal 版 / simple 版」三段**统一响度**后并排，
消除音量差异的干扰，让耳朵只判断音质本身（是否还有水泡/空间错乱）。

用法：
    ./.venv/Scripts/python.exe tools/ab_listen_test.py

产出：output/_diag/AB_health_normal_simple.mp4（黑屏 + 三段音频，各 6 秒）
      A = h3_i2v_00091（11:53 健康基准，L/R 0.991）
      B = h3_i2v_00095（01:27 normal，L/R 0.216）
      C = h3_i2v_00096（01:40 simple，L/R 0.421）★ 老板刚听的那条
"""
import os
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8")
import imageio_ffmpeg

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXE = imageio_ffmpeg.get_ffmpeg_exe()
DIAG = os.path.join(ROOT, "output", "_diag")
os.makedirs(DIAG, exist_ok=True)

SEGS = [
    ("A 健康基准 00091 (11:53) L/R=0.991", os.path.join(ROOT, "output/_raw/h3_i2v_00091_.mp4")),
    ("B normal  00095 (01:27) L/R=0.216", os.path.join(ROOT, "output/_raw/h3_i2v_00095_.mp4")),
    ("C simple  00096 (01:40) L/R=0.421", os.path.join(ROOT, "output/_raw/h3_i2v_00096_.mp4")),
]

out = os.path.join(DIAG, "AB_health_normal_simple.mp4")

inputs = []
for _, p in SEGS:
    if not os.path.isfile(p):
        print("缺文件:", p)
        sys.exit(1)
    inputs += ["-i", p]

fc, labels = [], []
for i, _ in enumerate(SEGS):
    fc.append(
        f"[{i}:a]loudnorm=I=-20:TP=-2:LRA=11,"
        f"aformat=sample_rates=32000:channel_layouts=stereo,"
        f"atrim=0:6,asetpts=N/SR/TB[s{i}]"
    )
    labels.append(f"[s{i}]")
fc.append("".join(labels) + f"concat=n={len(SEGS)}:v=0:a=1[aout]")

cmd = [EXE, "-y", *inputs,
       "-f", "lavfi", "-i", "color=c=black:s=854x480:r=24",
       "-filter_complex", ";".join(fc),
       "-map", "[aout]", "-map", f"{len(SEGS)}:v",
       "-c:v", "libx264", "-preset", "veryfast", "-crf", "30",
       "-c:a", "aac", "-b:a", "192k", "-shortest", out]
subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
print("已生成:", out)
for i, (n, _) in enumerate(SEGS, 1):
    print("  第 %d 段（第 %d-%d 秒）: %s" % (i, (i - 1) * 6, i * 6, n))
print()
print("⚠ 必须戴耳机听：立体声错乱只有在左右耳分开时才听得出，笔记本扬声器会掩盖。")
