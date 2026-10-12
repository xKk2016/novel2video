#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""ImageGen 产物去水印（右下角 "AI生成 WORKBUDDY"）。

背景：ImageGen 出的图右下角一律带白色水印。参考图是**整张**喂给 H3 的，
留着文字会污染输出，必须去掉。

为什么不用 ffmpeg delogo：delogo 是边缘线性插值，在**纯色/渐变背景**（如人物
三视图的浅灰底）上干净无痕，但在**复杂纹理背景**（岩石、木纹、植被）上会留下
明显横向条纹伪影。锚图全是复杂纹理，必须用内容填充（cv2.inpaint）或纹理移植。

两种模式（`--mode`）：
    inpaint（默认）—— cv2.inpaint 内容填充。**纯色/渐变背景**首选（影棚灰底、天空）。
    seam —— 纹理移植。从水印框正上方取同尺寸块羽化贴回。**复杂纹理背景**必用，
            inpaint 在这类背景上会填出一块显眼的平滑糊块（实测锚图右下岩壁）。

用法：
    python tools/dewatermark.py <图片或目录> [更多...] [-o 输出目录] [--mode seam]
    # 不指定 -o 时原地覆盖，并把原图备份到 <同目录上层>/xxx_raw/

    python tools/dewatermark.py refs/3d/anchor_*.png --box 1400,950,136,74 --mode seam
    python tools/dewatermark.py refs/3d/ --dry-run     # 只报检测到的位置，不写盘

检测：水印是**近白**像素（高亮度 + 低饱和），而画面高光多为暖色（R 明显 > B），
据此在右下角 ROI 内做阈值筛选，取包围盒外扩若干像素作为 inpaint 掩膜。
"""
import argparse
import glob
import os
import shutil
import sys

import cv2
import numpy as np

# 右下角 ROI（按图像尺寸的百分比）——水印永远贴着右下角
ROI_X0_FRAC = 0.80
ROI_Y0_FRAC = 0.78


def detect(im, pad=8):
    """在右下角 ROI 内检测近白水印像素，返回外扩后的 (x, y, w, h)；无则返回 None。"""
    h, w = im.shape[:2]
    x0, y0 = int(w * ROI_X0_FRAC), int(h * ROI_Y0_FRAC)
    roi = im[y0:h, x0:w]
    b, g, r = roi[:, :, 0].astype(np.int16), roi[:, :, 1].astype(np.int16), roi[:, :, 2].astype(np.int16)
    mx = np.maximum(np.maximum(b, g), r)
    mn = np.minimum(np.minimum(b, g), r)
    # 近白：整体够亮 + 通道差小（排除夕阳暖光那种 R>>B 的高光）
    mask = (mn > 140) & ((mx - mn) < 45)
    if mask.sum() < 30:          # 像素太少 → 没检测到（或图本来就干净）
        return None
    ys, xs = np.where(mask)
    bx0, bx1 = int(xs.min()) + x0, int(xs.max()) + x0
    by0, by1 = int(ys.min()) + y0, int(ys.max()) + y0
    # 外扩 + 夹紧到画面内（留 1px 边，避免 inpaint 无参考像素）
    bx0, by0 = max(0, bx0 - pad), max(0, by0 - pad)
    bx1, by1 = min(w - 2, bx1 + pad), min(h - 2, by1 + pad)
    return bx0, by0, bx1 - bx0 + 1, by1 - by0 + 1


def seam_fill(im, box, gap=6, edge=10):
    """纹理移植（seam）：从水印框正上方（不够则正左、再左上）取同尺寸块，羽化贴回。

    为什么需要它：`cv2.inpaint` 在**纯色/渐变背景**（影棚灰底、天空）上干净无痕，
    但在**复杂纹理背景**（岩石、木纹、植被）上会填出一块显眼的平滑糊块。
    实测锚图右下角岩壁：inpaint 留下明显灰雾，纹理移植则延续自然。

    ⚠️ **2026-10-06 血案：贴图像边界的框边不能羽化**。
    水印永远紧贴右下角，若框的右/下边正好落在图像边界上，那两条边的羽化会把 alpha
    从 1 渐隐到 0 —— **最外几圈的原始像素（= 水印）被原样保留**。
    实测 1536x864 关键帧：框 `1416,758,118,102` 时，"AI生成"（在框内）被完全覆盖，
    而贴底的 "WORKBUDDY" 落在底部羽化带里留下清晰残影。
    ⇒ 贴边的那条边**不羽化**（边界外侧本就没有内容要过渡），并在调用方把框扩到贴住边界。
    """
    x, y, w, h = box
    hh, ww = im.shape[:2]
    fade_l = x > 0
    fade_t = y > 0
    fade_r = (x + w) < ww
    fade_b = (y + h) < hh
    for dx, dy in ((x, y - h - gap), (x - w - gap, y), (x - w - gap, y - h - gap)):
        if dx < 0 or dy < 0 or dx + w > ww or dy + h > hh:
            continue
        patch = im[dy:dy + h, dx:dx + w].astype(np.float32)
        dst = im[y:y + h, x:x + w].astype(np.float32)
        blend = np.ones((h, w), np.float32)
        e = min(edge, h // 2, w // 2)
        for i in range(e):
            a = i / max(1, e)
            if fade_t:
                blend[i, :] = np.minimum(blend[i, :], a)
            if fade_b:
                blend[-1 - i, :] = np.minimum(blend[-1 - i, :], a)
            if fade_l:
                blend[:, i] = np.minimum(blend[:, i], a)
            if fade_r:
                blend[:, -1 - i] = np.minimum(blend[:, -1 - i], a)
        out = im.copy()
        out[y:y + h, x:x + w] = (dst * (1 - blend[..., None]) + patch * blend[..., None]).astype(np.uint8)
        return out
    return None


def clean_one(path, out_path=None, pad=8, radius=6, dry=False, verbose=True, box=None, mode="inpaint"):
    # ⚠️ cv2.imread **读不了含非 ASCII 的路径**（本项目根目录就是中文：
    #    「蛊真人视频生成/…」）——传绝对路径必然失败，传相对路径才侥幸能过。
    #    用 np.fromfile + imdecode 绕过（写回同理用 imencode + tofile）。
    try:
        im = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
    except Exception:  # noqa: BLE001
        im = None
    if im is None:
        print(f"  [skip] 读不了：{path}")
        return False
    if not box:
        box = detect(im, pad=pad)
    if not box:
        if verbose:
            print(f"  [clean] 未检测到水印：{os.path.basename(path)}")
        return False
    x, y, w, h = box
    if verbose:
        print(f"  [found] {os.path.basename(path)}  水印 {w}x{h} @ ({x},{y})  mode={mode}")
    if dry:
        return True
    fixed = None
    if mode == "seam":
        fixed = seam_fill(im, box)
        if fixed is None:
            print(f"  [warn] seam 取样越界，回退 inpaint：{os.path.basename(path)}")
    if fixed is None:
        mask = np.zeros(im.shape[:2], np.uint8)
        mask[y:y + h, x:x + w] = 255
        fixed = cv2.inpaint(im, mask, radius, cv2.INPAINT_TELEA)
    dst = out_path or path
    if dst == path:                       # 原地覆盖 → 先备份原图
        raw_dir = os.path.join(os.path.dirname(os.path.dirname(path)), "3d_raw")
        os.makedirs(raw_dir, exist_ok=True)
        bak = os.path.join(raw_dir, os.path.basename(path))
        if not os.path.exists(bak):
            shutil.copy2(path, bak)
    ext = os.path.splitext(dst)[1] or ".png"
    ok, buf = cv2.imencode(ext, fixed)
    if not ok:
        print(f"  [skip] 写不了：{dst}")
        return False
    buf.tofile(dst)          # 同样绕开 cv2.imwrite 的非 ASCII 路径限制
    if verbose:
        print(f"  [ write] {dst}")
    return True


def main():
    ap = argparse.ArgumentParser(description="ImageGen 产物去水印（内容填充）")
    ap.add_argument("paths", nargs="+", help="图片路径或目录（目录则递归取 *.png）")
    ap.add_argument("-o", "--out-dir", default=None, help="输出目录（不指定则原地覆盖 + 备份）")
    ap.add_argument("--pad", type=int, default=8, help="掩膜外扩像素（默认 8）")
    ap.add_argument("--radius", type=int, default=6, help="inpaint 半径（默认 6）")
    ap.add_argument("--dry-run", action="store_true", help="只检测不写盘")
    ap.add_argument("--box", default=None,
                    help="显式指定水印矩形 'x,y,w,h'。纹理背景（岩石/木纹）上自动检测不可靠"
                         "（画面高光与半透明灰白水印难以区分），此时必须显式给框。"
                         "1536x1024 锚图用 1400,950,136,74。")
    ap.add_argument("--mode", choices=["inpaint", "seam"], default="inpaint",
                    help="inpaint=内容填充（默认；纯色/渐变背景，如影棚灰底）"
                         " / seam=纹理移植（复杂纹理背景，如岩石木纹，从水印框正上方取块羽化贴回）")
    a = ap.parse_args()
    box = None
    if a.box:
        try:
            box = tuple(int(v) for v in a.box.split(","))
            assert len(box) == 4
        except Exception:
            print("--box 格式应为 x,y,w,h（如 1416,758,118,102）")
            return 2

    files = []
    for p in a.paths:
        if os.path.isdir(p):
            files += sorted(glob.glob(os.path.join(p, "*.png")))
        else:
            files += sorted(glob.glob(p))
    if not files:
        print("没有匹配到图片")
        return 1

    if a.out_dir:
        os.makedirs(a.out_dir, exist_ok=True)
    n = 0
    for f in files:
        dst = os.path.join(a.out_dir, os.path.basename(f)) if a.out_dir else None
        if clean_one(f, dst, pad=a.pad, radius=a.radius, dry=a.dry_run, box=box, mode=a.mode):
            n += 1
    print(f"\n共处理 {n}/{len(files)} 张" + ("（dry-run，未写盘）" if a.dry_run else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
