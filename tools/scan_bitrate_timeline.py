"""全量扫描原始产物：按时间排序输出「视频码率 / 音频相关 / 体积」。
视频码率是比 Side/Mid 更早、更明显的变质信号（噪声画面 → H.264 码率暴涨）。
"""
import os
import re
import subprocess
import sys
import glob
import datetime

sys.stdout.reconfigure(encoding="utf-8")
import numpy as np
import imageio_ffmpeg

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXE = imageio_ffmpeg.get_ffmpeg_exe()


def probe(path):
    r = subprocess.run([EXE, "-i", path], capture_output=True, text=True)
    dur = None
    vkb = None
    for l in r.stderr.splitlines():
        m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", l)
        if m:
            dur = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
        if "Video: h264" in l:
            m2 = re.search(r"(\d+) kb/s, 24 fps", l)
            if m2:
                vkb = int(m2.group(1))
        if "Video: h264" in l and vkb is None:
            m3 = re.search(r", (\d+) kb/s", l)
            if m3:
                vkb = int(m3.group(1))
    return dur, vkb


def astat(path):
    r = subprocess.run([EXE, "-v", "error", "-i", path,
                        "-f", "f32le", "-acodec", "pcm_f32le", "-ac", "2", "-"],
                       capture_output=True)
    a = np.frombuffer(r.stdout, dtype=np.float32)
    n = (len(a) // 2) * 2
    if n < 1024:
        return None, None
    x = a[:n].reshape(-1, 2)
    L, R = x[:, 0].astype(np.float64), x[:, 1].astype(np.float64)
    if L.std() < 1e-9 or R.std() < 1e-9:
        return None, None
    corr = float(np.corrcoef(L, R)[0, 1])
    mid, side = (L + R) / 2.0, (L - R) / 2.0
    return corr, float(10 * np.log10(((side ** 2).mean() + 1e-12) / ((mid ** 2).mean() + 1e-12)))


def main():
    dirs = [os.path.join(ROOT, "output/_raw")]
    for d in sys.argv[1:]:
        dirs.append(d)
    files = []
    for d in dirs:
        files += glob.glob(os.path.join(d, "*.mp4"))
    files = sorted(set(files), key=os.path.getmtime)

    print("=" * 108)
    print("%-26s %-17s %6s %10s %8s %9s %9s" %
          ("文件", "mtime", "时长", "视频kb/s", "体积KB", "L/R相关", "Side/Mid"))
    print("-" * 108)
    prev = None
    for f in files:
        mt = datetime.datetime.fromtimestamp(os.path.getmtime(f))
        dur, vkb = probe(f)
        corr, side = astat(f)
        kb = os.path.getsize(f) / 1024.0
        flag = ""
        if vkb is not None and vkb >= 2000:
            flag = "  <<< 噪声画面"
        if prev is not None and vkb is not None and prev > 0 and vkb / prev >= 2.5:
            flag += "  [码率突变]"
        print("%-26s %s %6s %10s %8.0f %9s %9s%s" %
              (os.path.basename(f), mt.strftime("%m-%d %H:%M"),
               ("%.2fs" % dur) if dur else "-",
               vkb if vkb else "-", kb,
               ("%.3f" % corr) if corr is not None else "-",
               ("%+.1f" % side) if side is not None else "-", flag))
        if vkb:
            prev = vkb
    print("=" * 108)
    print("判读：视频码率 >2000 kb/s 基本就是噪声画面（同分辨率干净 CG 约 900-1300）。")


if __name__ == "__main__":
    main()
