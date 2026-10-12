# -*- coding: utf-8 -*-
"""全片台词时长体检：找出「语音顶到片尾、说不完」的镜头，给出建议帧数。

背景（2026-10-09 诊断）：
    分镜时长原按「字数 ÷ 4.0 字/秒」估算，但 H3 实际念白只有 3.5~3.75 字/秒，
    且短句会被模型拖长（实测镜20：7 字占 5.15s）。
    ⇒ 长台词镜语音贴死在最后一帧，没有收尾气口，听感"赶 / 没说完"。

两路依据：
    ① 【实测】片段已生成 → 用谱平坦度分离人声，量出真实语音跨度
    ② 【估算】片段未生成 → 按 3.5 字/秒 + 下限 4.8s + 0.8s 收尾（偏保守）

用法：
    ./.venv/Scripts/python.exe tools/audit_duration.py                 # 全片
    ./.venv/Scripts/python.exe tools/audit_duration.py --shots 1-21
    ./.venv/Scripts/python.exe tools/audit_duration.py --csv
"""
import argparse
import csv
import json
import os
import re
import subprocess
import sys

import numpy as np

import imageio_ffmpeg

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SB = os.path.join(ROOT, "assets", "01_script", "storyboard",
                  "storyboard_ch1_v3.json")
CLIPS = os.path.join(ROOT, "assets", "04_clips")
CSV_OUT = os.path.join(ROOT, "output", "_diag", "duration_fix_all.csv")

FF = imageio_ffmpeg.get_ffmpeg_exe()
SR = 16000

GRID = list(range(124, 363, 17))          # 17k+5 网格
TAIL_PAD = 0.8                            # 收尾余量（秒）
CPS_FALLBACK = 3.5                        # 估算语速（字/秒），场1 实测 3.5~3.75
MIN_SPAN = 4.8                            # 跨度下限（短句被拖长，纯字数公式会低估）


def snap(frames):
    f = max(124, min(362, int(round(frames))))
    for g in GRID:
        if g >= f:
            return g
    return 362


def ff_probe_dur(path):
    r = subprocess.run([FF, "-i", path], capture_output=True, text=True,
                       errors="ignore")
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", r.stderr or "")
    return (int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
            if m else 0.0)


def measure_span(path):
    """谱平坦度法分离人声，返回 (首声起点, 末声终点)。失败返回 (0, 0)。"""
    raw = path + ".span.f32"
    try:
        subprocess.run([FF, "-y", "-loglevel", "error", "-i", path,
                        "-af", "pan=mono|c0=0.5*c0+0.5*c1",
                        "-f", "f32le", "-ac", "1", "-ar", str(SR), raw],
                       check=True)
        x = np.fromfile(raw, dtype="<f4").astype(np.float64)
    except Exception:
        return 0.0, 0.0
    finally:
        if os.path.isfile(raw):
            os.remove(raw)

    W, H = int(SR * 0.032), int(SR * 0.016)
    n = (len(x) - W) // H
    if n < 10:
        return 0.0, 0.0

    win = np.hanning(W)
    sfm = np.empty(n)
    rms = np.empty(n)
    for i in range(n):
        seg = x[i * H:i * H + W] * win
        rms[i] = np.sqrt((seg ** 2).mean())
        mag = np.abs(np.fft.rfft(seg)) + 1e-10
        sfm[i] = np.exp(np.mean(np.log(mag))) / np.mean(mag)

    thr = max(np.percentile(rms, 25) * 1.6, rms.max() * 0.05)
    on = (sfm < 0.42) & (rms > thr)

    raw_segs = []
    st = None
    for i, v in enumerate(on):
        t = i * H / SR
        if v and st is None:
            st = t
        elif not v and st is not None:
            raw_segs.append((st, t))
            st = None
    if st is not None:
        raw_segs.append((st, n * H / SR))

    merged = []
    for a, b in raw_segs:
        if merged and a - merged[-1][1] <= 0.40:
            merged[-1] = (merged[-1][0], b)
        else:
            merged.append((a, b))
    merged = [(a, b) for a, b in merged if b - a >= 0.15]
    return (merged[0][0], merged[-1][1]) if merged else (0.0, 0.0)


def parse_range(s):
    out = set()
    for part in s.split(","):
        if "-" in part:
            a, b = part.split("-")
            out.update(range(int(a), int(b) + 1))
        else:
            out.add(int(part))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default=SB)
    ap.add_argument("--shots", default=None, help="如 1-21；默认全部")
    ap.add_argument("--csv", action="store_true")
    a = ap.parse_args()

    d = json.load(open(a.file, encoding="utf-8"))
    want = parse_range(a.shots) if a.shots else None

    rows = []
    for s in d:
        i = s.get("index")
        if want and i not in want:
            continue
        line = (s.get("line") or "").strip()
        if not line:
            continue
        n = len(line)
        cur = s["length"]
        clip = os.path.join(CLIPS, "shot_%03d.mp4" % i)

        if os.path.isfile(clip):
            f0, f1 = measure_span(clip)
            span = round(f1 - f0, 2) if f1 else 0.0
            src = "实测"
        else:
            span = round(max(n / CPS_FALLBACK, MIN_SPAN), 2)
            src = "估算"

        need = span + TAIL_PAD
        nf = snap(need * 24)
        gap = round(nf / 24 - cur / 24, 2)
        rows.append(dict(idx=i, scene=s.get("scene_no"), chars=n,
                         cur_frame=cur, cur_sec=round(cur / 24, 2),
                         span=span, src=src, need=round(need, 2),
                         new_frame=nf, new_sec=round(nf / 24, 2), gap=gap,
                         line=line))

    print("=" * 92)
    print("台词时长体检 —— 建议规则：语音跨度 + %.2fs 收尾，向上吸附 0.708s 网格" % TAIL_PAD)
    print("=" * 92)
    print("%-4s %-4s %-5s %-7s %-7s %-8s %-6s %-8s %-8s %s"
          % ("镜", "场", "字数", "现帧", "现时长", "语音跨度", "依据",
             "建议帧", "建议时长", "缺口"))
    print("-" * 92)
    for r in rows:
        flag = " ★" if r["gap"] > 0.4 else ""
        print("%-4d %-4d %-5d %-7d %-7.2f %-8.2f %-6s %-8d %-8.2f %+.2fs%s"
              % (r["idx"], r["scene"], r["chars"], r["cur_frame"], r["cur_sec"],
                 r["span"], r["src"], r["new_frame"], r["new_sec"], r["gap"],
                 flag))
    print("-" * 92)

    fix = [r for r in rows if r["gap"] > 0.4]
    print("台词镜 %d ｜ 需加长 %d 镜 ｜ 净增 %.1f 秒"
          % (len(rows), len(fix), sum(r["gap"] for r in fix if r["gap"] > 0)))
    print("  其中 场1 %d 镜（实测依据）｜ 场2/3/4 %d 镜（估算依据）"
          % (len([r for r in fix if r["scene"] == 1]),
             len([r for r in fix if r["scene"] != 1])))
    ok = [r for r in rows if r["gap"] <= 0.4]
    print("  已够用 %d 镜（平均余量 %.2fs）"
          % (len(ok), np.mean([-r["gap"] for r in ok]) if ok else 0))
    print("=" * 92)

    if a.csv:
        os.makedirs(os.path.dirname(CSV_OUT), exist_ok=True)
        with open(CSV_OUT, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["镜", "场", "字数", "现帧数", "现时长s", "语音跨度s", "依据",
                        "建议帧数", "建议时长s", "缺口s", "台词"])
            for r in rows:
                w.writerow([r["idx"], r["scene"], r["chars"], r["cur_frame"],
                            r["cur_sec"], r["span"], r["src"], r["new_frame"],
                            r["new_sec"], r["gap"], r["line"]])
        print("CSV → %s" % os.path.relpath(CSV_OUT, ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
