# -*- coding: utf-8 -*-
"""出片体检：一次跑出「码率 / 分辨率 / 音频特征 / 抽帧目视图」（诊断糊、方块、噪音）。

为什么要有这个脚本：老板两次反馈「画面糊 + 奇怪的小方块」「声音有很大噪音」，
每次都要临时敲一堆 ffprobe / astats / 抽帧命令。固化下来，下次一条命令出结论。

判读口径（2026-10-06 实测标定）：

| 指标 | 健康 | 报警 |
|---|---|---|
| 视频码率 @1344x768@24fps | **≥ 6 Mbps** | < 4 Mbps → 平滑区出 16×16 方块（h264 macroblock） |
| 音频 Peak | **< −3 dBFS** | 接近 0（如 −0.5）→ 被限幅压死，噪声极刺耳 |
| 音频 RMS（纯环境音镜） | **−30 ~ −40 dB** | 高于 −25 dB → 环境音被当主体在放，听感=噪音 |
| 音频 Noise floor count | 低（几十） | 上千 → 持续底噪/对白质量差 |

跑法（必须用项目 .venv）：
    ./.venv/Scripts/python.exe tools/diagnose_clips.py --shots 1,2
    ./.venv/Scripts/python.exe tools/diagnose_clips.py --shots 1,2 --frames 4 --zoom 3
"""

import argparse
import glob
import os
import re
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLIPS = os.path.join(ROOT, "assets", "04_clips")
OUT = os.path.join(ROOT, "output", "_diag")


def ffmpeg_exe():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


def probe(exe, path):
    r = subprocess.run([exe, "-i", path], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    info = {"bitrate": "", "video": "", "audio": "", "duration": ""}
    for line in r.stderr.splitlines():
        s = line.strip()
        if s.startswith("Duration:"):
            info["duration"] = s.split(",")[0].replace("Duration:", "").strip()
        if "bitrate:" in s and "Duration" in s:
            m = re.search(r"bitrate:\s*(\d+)\s*kb/s", s)
            if m:
                info["bitrate"] = m.group(1) + " kb/s"
        if "Video:" in s and "Stream" in s:
            info["video"] = s.split("Video:")[1].strip()[:110]
        if "Audio:" in s and "Stream" in s:
            info["audio"] = s.split("Audio:")[1].strip()[:90]
    return info


def astats(exe, path):
    r = subprocess.run([exe, "-i", path, "-af", "astats=metadata=1:reset=0",
                        "-f", "null", "-"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    out = {}
    keys = {"Peak level dB": "peak", "RMS level dB": "rms",
            "Noise floor dB": "floor", "Noise floor count": "floor_n",
            "Entropy": "entropy"}
    for line in r.stderr.splitlines():
        for k, tag in keys.items():
            if k in line and ":" in line:
                try:
                    out.setdefault(tag, float(line.split(":", 1)[1].strip()))
                except ValueError:
                    pass
    return out


def channel_corr(exe, path):
    """左右声道相关系数 —— 判定「水泡音 / 人声回声」最灵的单一指标。

    健康 ≥ 0.98。**< 0.6 基本就是画风串里的否定式画质词污染了音频**
    （`no bloom` / `no atmospheric haze` 这类带听觉含义的词，在没有 negative 分支的
    H3 里会被登记成条件，见 SKILL §5.3）。实测血案：0.991 → 0.593 → 0.392 → 0.175。
    注意：这不是延迟问题（互相关 lag 恒为 0），也不是 H3 的固有特性 —— 是 prompt 变量引起的。
    """
    try:
        import numpy as np
    except ImportError:
        return None
    r = subprocess.run([exe, "-v", "error", "-i", path, "-f", "f32le",
                        "-acodec", "pcm_f32le", "-ac", "2", "-"],
                       capture_output=True)
    if r.returncode != 0 or not r.stdout:
        return None
    a = np.frombuffer(r.stdout, dtype=np.float32)
    n = (len(a) // 2) * 2
    if n < 256:
        return None
    x = a[:n].reshape(-1, 2)
    L, R = x[:, 0], x[:, 1]
    if L.std() < 1e-9 or R.std() < 1e-9:
        return None
    return float(np.corrcoef(L, R)[0, 1])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shots", default="", help="镜号，逗号分隔；缺省=全部")
    ap.add_argument("--dir", default="", help="覆盖片段目录（默认 assets/04_clips，可指向 _archive）")
    ap.add_argument("--frames", type=int, default=4, help="每镜抽帧数")
    ap.add_argument("--zoom", type=int, default=0, help=">0 时额外出一张放大细节图")
    a = ap.parse_args()

    base = os.path.abspath(a.dir) if a.dir else CLIPS
    if a.shots:
        want = [int(x) for x in a.shots.split(",") if x.strip()]
        paths = [os.path.join(base, "shot_%03d.mp4" % n) for n in want]
    else:
        paths = sorted(glob.glob(os.path.join(base, "shot_*.mp4")))
    paths = [p for p in paths if os.path.isfile(p)]
    if not paths:
        print("没有找到片段。")
        return 1

    os.makedirs(OUT, exist_ok=True)
    exe = ffmpeg_exe()
    print("ffmpeg:", exe)
    print("=" * 94)

    tiles = []
    for p in paths:
        n = int(re.search(r"shot_(\d+)\.mp4", os.path.basename(p)).group(1))
        pr = probe(exe, p)
        st = astats(exe, p)
        cc = channel_corr(exe, p)
        br = pr["bitrate"]
        brn = int(re.sub(r"\D", "", br) or 0)
        warn = []
        if brn and brn < 4000:
            warn.append("码率偏低(糊/方块)")
        if cc is not None and cc < 0.6:
            warn.append("左右声道不相关(水泡音/回声)")
        if st.get("peak", -99) > -3:
            warn.append("峰值顶满(噪声刺耳)")
        if st.get("rms", -99) > -25:
            warn.append("RMS偏高(环境音盖主体)")
        if st.get("floor_n", 0) > 300:
            warn.append("底噪计数高")
        print("镜%-3d %s  %s" % (n, br, pr["duration"]))
        print("       视频: %s" % pr["video"])
        print("       音频: %s" % pr["audio"])
        print("       astats: Peak %.2f  RMS %.2f  floor %.1f (n=%d)"
              % (st.get("peak", 0), st.get("rms", 0), st.get("floor", 0), st.get("floor_n", 0)))
        print("       L/R 相关: %s%s"
              % ("%.3f" % cc if cc is not None else "n/a",
                 "  （健康 ≥0.98）" if cc is not None else ""))
        print("       %s" % ("  ⚠ " + "、".join(warn) if warn else "  ✓ 指标正常"))

        if a.frames:
            dur = 0.0
            try:
                mm, ss = pr["duration"].split(":")
                dur = int(mm) * 60 + float(ss)
            except Exception:
                dur = 5.0
            for i in range(a.frames):
                t = dur * (i + 0.5) / a.frames
                dst = os.path.join(OUT, "s%03d_f%d.png" % (n, i))
                subprocess.run([exe, "-y", "-ss", "%.2f" % t, "-i", p,
                                "-frames:v", "1", dst], capture_output=True)
                if os.path.isfile(dst):
                    tiles.append(dst)
        print("-" * 94)

    if tiles:
        try:
            import cv2
            import numpy as np

            def load(q):
                return cv2.imdecode(np.fromfile(q, dtype=np.uint8), cv2.IMREAD_COLOR)

            imgs = [load(t) for t in tiles]
            if a.zoom:
                for i, im in enumerate(imgs):
                    h, w = im.shape[:2]
                    c = im[int(h * 0.15):int(h * 0.5), int(w * 0.35):int(w * 0.85)]
                    c = cv2.resize(c, (c.shape[1] * a.zoom, c.shape[0] * a.zoom),
                                   interpolation=cv2.INTER_NEAREST)
                    cv2.putText(c, os.path.basename(tiles[i]), (10, 32),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 255), 2)
                    imgs[i] = c
            hh = min(x.shape[0] for x in imgs)
            ww = min(x.shape[1] for x in imgs)
            imgs = [cv2.resize(x, (ww, hh)) for x in imgs]
            cols = min(4, len(imgs))
            rows = (len(imgs) + cols - 1) // cols
            canvas = np.full((hh * rows, ww * cols, 3), 24, np.uint8)
            for i, im in enumerate(imgs):
                r, c = divmod(i, cols)
                canvas[r * hh:(r + 1) * hh, c * ww:(c + 1) * ww] = im
            dst = os.path.join(OUT, "diag_overview_zoom.png" if a.zoom else "diag_overview.png")
            ok, buf = cv2.imencode(".png", canvas)
            buf.tofile(dst)
            print("抽帧总览 → %s" % dst)
        except ImportError:
            print("（无 cv2，跳过拼图；抽帧已存 %s）" % OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
