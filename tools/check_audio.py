"""H3 出片音频体检：一眼判断「水泡音 / 人声回声」是否发生。

用法
----
    ./.venv/Scripts/python.exe tools/check_audio.py --shots 1,2
    ./.venv/Scripts/python.exe tools/check_audio.py --dir <目录> [更多目录...]
    ./.venv/Scripts/python.exe tools/check_audio.py --shots 2 --spectrum   # 顺便出频谱/波形图

背景（2026-10-07 定标）
----------------------
H3 是**原生立体声**模型（音频 latent `[B, 32, 2, T40]`，两个声道各生成各的）。
正常产出里左右声道高度一致；一旦某个开关把 stereo 一致性打破，听感就是
「水泡音 + 人声回声 + 背景浑浊」，而**画面完全正常**，所以只靠看片发现不了。

两个客观指标（都是对任意音频都通用的量）：

    L/R 相关系数      左声道 vs 右声道 的皮尔逊相关
                      ≥0.98 健康 ／ <0.6 损坏
    Side/Mid (dB)     Side=(L−R)/2、Mid=(L+R)/2 的能量比
                      正常立体声 ≈ −20 ~ −24 dB ／ 损坏时涨到 −1 ~ −6 dB

实测标定：

    scheduler   样本                   L/R 相关        Side/Mid
    simple      i2v 88/89/90/91        0.990~0.991     −22 ~ −24 dB   ✓
    normal      i2v 92/93/94/95        0.59→0.18       −5.9 → −1.9 dB ✗

⇒ `Side/Mid` 比 L/R 相关更灵敏、更直观（20 dB 的暴涨，一眼可辨）。
"""

import argparse
import glob
import os
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8")

import numpy as np
import imageio_ffmpeg

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLIPS = os.path.join(ROOT, "assets", "04_clips")
DIAG = os.path.join(ROOT, "output", "_diag")

HEALTHY_SIDE = -16.0   # 高于此值 = 立体声一致性受损
ALARM_SIDE = -10.0     # 高于此值 = 明确损坏（水泡音）
HEALTHY_CORR = 0.90


def _exe():
    return imageio_ffmpeg.get_ffmpeg_exe()


def pcm2(exe, path):
    r = subprocess.run([exe, "-v", "error", "-i", path,
                        "-f", "f32le", "-acodec", "pcm_f32le", "-ac", "2", "-"],
                       capture_output=True)
    a = np.frombuffer(r.stdout, dtype=np.float32)
    n = (len(a) // 2) * 2
    return a[:n].reshape(-1, 2)


def measure(exe, path):
    x = pcm2(exe, path)
    if len(x) < 512:
        return None
    L, R = x[:, 0], x[:, 1]
    if L.std() < 1e-9 or R.std() < 1e-9:
        return {"corr": float("nan"), "side": float("nan")}
    corr = float(np.corrcoef(L, R)[0, 1])
    mid = (L + R) / 2.0
    side = (L - R) / 2.0
    ratio = 10 * np.log10(((side ** 2).mean() + 1e-12) / ((mid ** 2).mean() + 1e-12))
    return {"corr": corr, "side": float(ratio)}


def verdict(m):
    if m is None or m["side"] != m["side"]:
        return "静音/无法分析", "?"
    s = m["side"]
    if s <= HEALTHY_SIDE and m["corr"] >= HEALTHY_CORR:
        return "✓ 健康", "ok"
    if s >= ALARM_SIDE:
        return "✗ 水泡/回声（立体声一致性已坏）", "bad"
    return "⚠ 轻度受损", "warn"


def spectrum(exe, path, out_png):
    subprocess.run([exe, "-y", "-i", path, "-lavfi",
                    "showspectrumpic=s=1000x300:legend=0:scale=log",
                    "-frames:v", "1", out_png], capture_output=True)
    return os.path.isfile(out_png)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shots", default="", help="镜号，逗号分隔")
    ap.add_argument("--dir", action="append", default=[], help="目录（可多次）")
    ap.add_argument("--spectrum", action="store_true", help="顺便出频谱图")
    a = ap.parse_args()

    paths = []
    if a.shots:
        for x in a.shots.split(","):
            x = x.strip()
            if x:
                paths.append(os.path.join(CLIPS, "shot_%03d.mp4" % int(x)))
    for d in a.dir:
        paths += sorted(glob.glob(os.path.join(d, "*.mp4")))
    if not paths:
        paths = sorted(glob.glob(os.path.join(CLIPS, "shot_*.mp4")))
    paths = [p for p in paths if os.path.isfile(p)]
    if not paths:
        print("没有可分析的片段。")
        return

    exe = _exe()
    bad = 0
    print("=" * 86)
    print("%-42s %9s %11s  %s" % ("文件", "L/R相关", "Side/Mid", "判定"))
    print("-" * 86)
    for p in paths:
        m = measure(exe, p)
        v, tag = verdict(m)
        if tag == "bad":
            bad += 1
        name = os.path.basename(p)
        if m and m["side"] == m["side"]:
            print("%-42s %9.3f %8.1f dB  %s" % (name, m["corr"], m["side"], v))
        else:
            print("%-42s %9s %11s  %s" % (name, "-", "-", v))
        if a.spectrum:
            os.makedirs(DIAG, exist_ok=True)
            out = os.path.join(DIAG, "spec_%s.png" % os.path.splitext(name)[0])
            spectrum(exe, p, out)
    print("=" * 86)
    print("合格线：L/R 相关 ≥ %.2f 且 Side/Mid ≤ %+.0f dB" % (HEALTHY_CORR, HEALTHY_SIDE))
    print("损坏 %d / %d 个" % (bad, len(paths)))
    if bad:
        print()
        print("⚠ 出现「水泡音/回声」时，先查这四个工作流的 scheduler：")
        print("    ./.venv/Scripts/python.exe tools/patch_scheduler_simple.py --to simple --dry-run")
        print("  不健康值：scheduler=normal ／ 健康值：scheduler=simple（详见 skill §7.7.1）")


if __name__ == "__main__":
    main()
