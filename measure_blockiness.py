"""量化度量画面块状伪影（blockiness）。

原理：若画面被切成规则小方格，则每隔 p 像素会有一条"硬边"，
该列的相邻像素差会显著高于平均水平。
对若干候选周期 p（8/16/32），计算
    ratio(p) = mean(|dI| at x%p==0) / mean(|dI| elsewhere)
ratio 越接近 1 越干净；明显 >1 说明存在以 p 为周期的方块网格。
"""
import sys, os, subprocess
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tts_client as tc


def load_gray(png):
    """用 ffmpeg 把 png 转成裸灰度数据再读入。"""
    ff = tc.get_ffmpeg()
    w, h = _dims(ff, png)
    r = subprocess.run([ff, "-v", "error", "-i", png, "-f", "rawvideo",
                        "-pix_fmt", "gray", "-"], capture_output=True)
    a = np.frombuffer(r.stdout, dtype=np.uint8)
    return a[: w * h].reshape(h, w).astype(np.float32)


def _dims(ff, png):
    r = subprocess.run([ff, "-i", png], capture_output=True, text=True)
    for line in r.stderr.splitlines():
        if "Video:" in line and "x" in line:
            import re
            m = re.search(r"(\d{2,5})x(\d{2,5})", line)
            if m:
                return int(m.group(1)), int(m.group(2))
    raise RuntimeError("cannot get dims")


def blockiness(png, periods=(8, 16, 32)):
    g = load_gray(png)
    h, w = g.shape
    dx = np.abs(np.diff(g, axis=1))          # 水平相邻差 -> shape (h, w-1)
    col = dx.mean(axis=0)                    # 每列的平均跳变
    out = {}
    for p in periods:
        idx = np.arange(len(col))
        on = col[idx % p == 0].mean()
        off = col[idx % p != 0].mean()
        out[p] = float(on / off) if off > 0 else 0.0
    out["_sharp"] = float(col.mean())        # 整体锐度（越高越清晰）
    out["_size"] = f"{w}x{h}"
    return out


def grid_peak(png, pmax=48):
    """对"每列水平梯度"做 FFT，找出最突出的空间周期（像素）。

    规则方块网格会让梯度信号在固定周期上出现尖峰。
    返回 (周期, 尖峰相对强度 z)，z 越大说明周期结构越强。
    """
    g = load_gray(png)
    col = np.abs(np.diff(g, axis=1)).mean(axis=0)
    col = col - col.mean()
    n = len(col)
    spec = np.abs(np.fft.rfft(col * np.hanning(n)))
    freqs = np.fft.rfftfreq(n, d=1.0)          # 单位: 周期^-1
    # 只看周期 4..pmax 的频段
    mask = (freqs >= 1.0 / pmax) & (freqs <= 1.0 / 4)
    band = spec[mask]
    if band.size == 0:
        return None, 0.0
    k = int(np.argmax(band))
    peak = band[k]
    z = (peak - band.mean()) / (band.std() + 1e-6)
    period = 1.0 / freqs[mask][k]
    return period, float(z)


if __name__ == "__main__":
    for png in sys.argv[1:]:
        r = blockiness(png)
        per, z = grid_peak(png)
        print(f"{os.path.basename(png):24s} {r['_size']:10s} "
              f"网格周期={per:5.1f}px  尖峰强度z={z:5.2f}  sharp={r['_sharp']:.2f}")
