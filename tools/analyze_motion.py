# -*- coding: utf-8 -*-
"""逐镜动作幅度体检（第 22 轮）。

用途：老板反馈「动作不够细节、比较呆滞」—— 先把"呆滞"量化，定位到具体镜号，
再看是与提示词（没写动作）相关，还是与参数（步数等）相关。

指标：
  · MAD     —— 相邻帧平均绝对差（0-255），整体运动能量
  · FLOW    —— Farneback 光流平均幅度（像素/帧），位移强度
  · 分区域  —— 画面中心 1/2 的 FLOW（人物通常在中心）

参考（本项目实测标定，见输出）：
  MAD < 1.5  : 几乎静止（适合空镜/静物）
  MAD 1.5-4  : 轻微动（呼吸/风/发丝）
  MAD 4-10   : 中等动作
  MAD > 10   : 大动作 / 快速运镜

用法：
    ./.venv/Scripts/python.exe tools/analyze_motion.py --shots 1-21
    ./.venv/Scripts/python.exe tools/analyze_motion.py --shots 1,9,19 --save-frames
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile

import cv2
import imageio_ffmpeg
import numpy as np

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLIPS = os.path.join(ROOT, "assets", "04_clips")
SB = os.path.join(ROOT, "assets", "01_script", "storyboard", "storyboard_ch1_v3.json")
OUTDIR = os.path.join(ROOT, "output", "_diag", "motion")


def parse_shots(spec):
    out = set()
    for part in str(spec).split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            out.update(range(int(a), int(b) + 1))
        else:
            out.add(int(part))
    return sorted(out)


def extract_frames(video, dst, n=16):
    """用 ffmpeg 抽帧到 ASCII 路径（cv2 读中文路径会失败）。"""
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    os.makedirs(dst, exist_ok=True)
    # 先拿总帧数
    probe = subprocess.run([ff, "-i", video], capture_output=True, text=True, errors="ignore")
    total = None
    for ln in probe.stderr.splitlines():
        if "Stream" in ln and "Video" in ln and "fps" in ln:
            # 解析 Duration
            pass
    dur = None
    for ln in probe.stderr.splitlines():
        if "Duration:" in ln:
            t = ln.split("Duration:")[1].split(",")[0].strip()
            h, m, s = t.split(":")
            dur = int(h) * 3600 + int(m) * 60 + float(s)
    if not dur:
        return []
    fps = 24.0
    step = max(1, int(round(dur * fps / n)))
    subprocess.run([ff, "-y", "-loglevel", "error", "-i", video,
                    "-vf", "select='not(mod(n\\,%d))'" % step,
                    "-vsync", "0", "-frames:v", str(n),
                    os.path.join(dst, "f%03d.png")], check=False)
    return sorted(os.path.join(dst, f) for f in os.listdir(dst) if f.endswith(".png"))


def imread_u(p):
    return cv2.imdecode(np.fromfile(p, np.uint8), cv2.IMREAD_COLOR)


def measure(frames):
    imgs = [imread_u(f) for f in frames]
    imgs = [i for i in imgs if i is not None]
    if len(imgs) < 2:
        return None
    h, w = imgs[0].shape[:2]
    # 统一尺寸并转灰度
    grays = [cv2.cvtColor(cv2.resize(i, (w, h)), cv2.COLOR_BGR2GRAY) for i in imgs]

    mads, flows, cflows = [], [], []
    ch, cw = h // 4, w // 4
    for a, b in zip(grays, grays[1:]):
        mads.append(float(np.mean(np.abs(a.astype(np.float32) - b.astype(np.float32)))))
        fl = cv2.calcOpticalFlowFarneback(a, b, None, 0.5, 3, 15, 3, 5, 1.2, 0)
        mag = np.sqrt(fl[..., 0] ** 2 + fl[..., 1] ** 2)
        flows.append(float(mag.mean()))
        cflows.append(float(mag[ch:3 * ch, cw:3 * cw].mean()))
    return dict(mad=float(np.mean(mads)), flow=float(np.mean(flows)),
                cflow=float(np.mean(cflows)), n=len(grays), size="%dx%d" % (w, h))


def verdict(mad):
    if mad < 1.5:
        return "几乎静止"
    if mad < 4:
        return "轻微动"
    if mad < 10:
        return "中等动作"
    return "大动作"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shots", default="1-21")
    ap.add_argument("--frames", type=int, default=16)
    ap.add_argument("--save-frames", action="store_true", help="把抽帧保存到 output/_diag/motion/")
    a = ap.parse_args()

    shots = parse_shots(a.shots)
    sb = {int(s["index"]): s for s in json.load(open(SB, encoding="utf-8"))}
    os.makedirs(OUTDIR, exist_ok=True)

    tmp = tempfile.mkdtemp(prefix="motion_")
    rows = []
    try:
        for n in shots:
            p = os.path.join(CLIPS, "shot_%03d.mp4" % n)
            if not os.path.isfile(p):
                continue
            d = os.path.join(tmp, "s%03d" % n)
            fr = extract_frames(p, d, a.frames)
            m = measure(fr)
            if not m:
                continue
            s = sb.get(n, {})
            m["n_sh"] = n
            m["scene"] = s.get("scene_no")
            m["mode"] = s.get("anchor_mode")
            m["dur"] = s.get("duration")
            m["prompt"] = str(s.get("video_prompt") or "")
            rows.append(m)
            if a.save_frames:
                keep = os.path.join(OUTDIR, "shot_%03d" % n)
                shutil.rmtree(keep, ignore_errors=True)
                shutil.copytree(d, keep)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("=" * 96)
    print("%-5s %-6s %-8s %-7s %8s %8s %9s   %s" % (
        "镜", "场", "模式", "时长", "MAD", "FLOW", "中心FLOW", "判定"))
    print("-" * 96)
    for r in rows:
        print("%-5d %-6s %-8s %-7s %8.2f %8.2f %9.2f   %s" % (
            r["n_sh"], r["scene"], r["mode"], r["dur"],
            r["mad"], r["flow"], r["cflow"], verdict(r["mad"])))
    print("=" * 96)
    if rows:
        mads = [r["mad"] for r in rows]
        print("MAD 均值 %.2f ｜ 中位 %.2f ｜ 最小 %.2f(镜%d) ｜ 最大 %.2f(镜%d)" % (
            np.mean(mads), np.median(mads), min(mads),
            rows[int(np.argmin(mads))]["n_sh"], max(mads),
            rows[int(np.argmax(mads))]["n_sh"]))
        print("低于 1.5（几乎静止）的镜：%s" % (
            ", ".join(str(r["n_sh"]) for r in rows if r["mad"] < 1.5) or "无"))
    if a.save_frames:
        print("抽帧 → %s" % os.path.relpath(OUTDIR, ROOT))


if __name__ == "__main__":
    main()
