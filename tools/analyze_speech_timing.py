# -*- coding: utf-8 -*-
"""实测每镜「H3 实际念台词的语速」与「末尾余量」—— 诊断「台词说不完」。

**为什么需要它**：分镜时长是按 **字数 ÷ 4.0 字/秒** 规划（见 §4.11），
但 H3 是视频+音频联合生成，实际念台词的语速与规划未必一致。
余量不足的镜就会「念到片尾还没完」→ 被硬切。

**方法（两次迭代后的可靠版）**：
  ① 取 **mid 通道** `(L+R)/2` —— 对白在中置
  ② **谱平坦度（SFM）** 判人声：`SFM = 几何均值(|FFT|) / 算术均值(|FFT|)`
     人声有强谐波结构 ⇒ SFM 低（<0.42）；风声/噪声是宽带 ⇒ SFM 接近 1
  ③ 与能量阈值取交集（`max(P25×1.6, 峰值×0.05)`）
  ④ 合并 gap ≤ 0.40s 的相邻段（句子内部停顿），丢弃 <0.15s 碎片
  ⑤ 输出 **语音跨度 = 末次结束 − 首次开始**（不是累计发声时长 —— 后者会把停顿算掉，严重低估）

⚠️ **纯能量法不可用**（2026-10-09 实测）：不加 SFM 时，持续风声全天候高于阈值，
   连「无台词的镜1」都会被误检出 4.4s「语音」。**别退回能量法。**

⚠️ 用**原始片段**（`assets/04_clips/`），别用成片（过 loudnorm 后动态被压平）。

判读：
  · **余量 = 视频时长 − 末次语音结束**
    - `< 0.30s` ⇒ **★贴片尾**：极可能"说不完"被切
    - `0.30~0.6s` ⇒ 偏紧
    - `> 0.6s`   ⇒ 从容
  · **实测语速 = 字数 / 语音跨度**：H3 实测约 **3.5~4.1 字/秒**（比 edge-TTS 的 3.8~4.6 略慢）
  · 全镜无人声段 + 有台词 ⇒ H3 没生成对白（另一类缺陷）

用法：
    ./.venv/Scripts/python.exe tools/analyze_speech_timing.py --shots 1-21
    ./.venv/Scripts/python.exe tools/analyze_speech_timing.py --shots all --csv
"""
import argparse
import csv
import json
import os
import re
import subprocess
import sys

import imageio_ffmpeg
import numpy as np

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FF = imageio_ffmpeg.get_ffmpeg_exe()
SR = 16000
SFM_THR = 0.42          # 谱平坦度阈值：低于它视为「有谐波结构 ⇒ 人声」
GAP = 0.40              # 合并间隔（秒）
MIN_SEG = 0.15          # 最短人声段


def load_mid(path):
    raw = path + ".mid.f32"
    subprocess.run([FF, "-y", "-loglevel", "error", "-i", path,
                    "-af", "pan=mono|c0=0.5*c0+0.5*c1",
                    "-f", "f32le", "-ac", "1", "-ar", str(SR), raw], check=True)
    a = np.fromfile(raw, dtype="<f4").astype(np.float64)
    os.remove(raw)
    return a


def voice_segments(x, gap=GAP, min_seg=MIN_SEG):
    W, H = int(SR * 0.032), int(SR * 0.016)
    n = (len(x) - W) // H
    if n < 10:
        return []
    win = np.hanning(W)
    sfm = np.empty(n)
    rms = np.empty(n)
    for i in range(n):
        seg = x[i * H:i * H + W] * win
        rms[i] = np.sqrt((seg ** 2).mean())
        mag = np.abs(np.fft.rfft(seg)) + 1e-10
        sfm[i] = np.exp(np.mean(np.log(mag))) / np.mean(mag)
    thr = max(np.percentile(rms, 25) * 1.6, rms.max() * 0.05)
    on = (sfm < SFM_THR) & (rms > thr)
    raw, s = [], None
    for i, v in enumerate(on):
        t = i * H / SR
        if v and s is None:
            s = t
        elif not v and s is not None:
            raw.append((s, t))
            s = None
    if s is not None:
        raw.append((s, n * H / SR))
    merged = []
    for a, b in raw:
        if merged and a - merged[-1][1] <= gap:
            merged[-1] = (merged[-1][0], b)
        else:
            merged.append((a, b))
    return [(a, b) for a, b in merged if b - a >= min_seg]


def probe_duration(path):
    out = subprocess.run([FF, "-i", path], capture_output=True, text=True,
                         errors="ignore").stderr
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", out)
    if not m:
        return 0.0
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shots", default="1-21")
    ap.add_argument("--clips", default="assets/04_clips")
    ap.add_argument("--storyboard",
                    default="assets/01_script/storyboard/storyboard_ch1_v3.json")
    ap.add_argument("--csv", action="store_true")
    a = ap.parse_args()

    sb = json.load(open(os.path.join(ROOT, a.storyboard), encoding="utf-8"))
    info = {s["index"]: s for s in sb}

    if a.shots == "all":
        ids = sorted(info)
    else:
        ids = []
        for part in a.shots.split(","):
            if "-" in part:
                lo, hi = part.split("-")
                ids += list(range(int(lo), int(hi) + 1))
            else:
                ids.append(int(part))

    print("=" * 108)
    print("%-5s %7s %6s %8s %8s %8s %7s  %s"
          % ("镜", "视频s", "字数", "语音跨度", "实测字/s", "末尾余量", "人声段", "判定"))
    rows = []
    for i in ids:
        p = os.path.join(ROOT, a.clips, "shot_%03d.mp4" % i)
        if not os.path.isfile(p):
            continue
        s = info.get(i) or {}
        line = (s.get("line") or "").strip()
        n = len(line)
        dur = probe_duration(p)
        segs = voice_segments(load_mid(p))

        if not segs:
            verdict = "⚠ 有台词但无人声段（H3 没生成对白）" if n else "无台词（正常）"
            rows.append((i, dur, n, 0, 0, dur, 0, verdict))
            print("%-5d %7.2f %6d %8s %8s %8.2f %7d  %s"
                  % (i, dur, n, "-", "-", dur, 0, verdict))
            continue

        span = segs[-1][1] - segs[0][0]
        last = segs[-1][1]
        margin = dur - last
        cps = n / span if (n and span) else 0
        if n == 0:
            verdict = "纯环境音（无台词镜，正常）"
        elif margin < 0.30:
            verdict = "★ 贴片尾：很可能说不完被切"
        elif margin < 0.60:
            verdict = "偏紧"
        elif cps > 4.3:
            verdict = "赶（语速超 TTS）"
        else:
            verdict = "正常"
        print("%-5d %7.2f %6d %8.2f %8.2f %8.2f %7d  %s"
              % (i, dur, n, span, cps, margin, len(segs), verdict))
        rows.append((i, dur, n, span, cps, margin, len(segs), verdict))

    print("=" * 108)
    bad = [r for r in rows if "贴片尾" in r[7]]
    tight = [r for r in rows if "偏紧" in r[7]]
    nodlg = [r for r in rows if "没生成对白" in r[7]]
    print("★贴片尾 %d 镜 ｜ 偏紧 %d 镜 ｜ 有台词无人声 %d 镜 ｜ 共 %d 镜"
          % (len(bad), len(tight), len(nodlg), len(rows)))
    if bad:
        print("  贴片尾: " + ", ".join("镜%d(余%.2fs)" % (r[0], r[5]) for r in bad))
    if tight:
        print("  偏紧  : " + ", ".join("镜%d(余%.2fs)" % (r[0], r[5]) for r in tight))
    if nodlg:
        print("  无对白: " + ", ".join("镜%d" % r[0] for r in nodlg))

    if a.csv:
        out = os.path.join(ROOT, "output/_diag/speech_timing.csv")
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["镜", "视频s", "字数", "语音跨度s", "实测字每秒",
                        "末尾余量s", "人声段数", "判定"])
            w.writerows(rows)
        print("CSV → %s" % out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
