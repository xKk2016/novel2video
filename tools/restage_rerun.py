# -*- coding: utf-8 -*-
"""改完分镜后一键「重新开跑」：归档派生资产，避免被断点续跑误判为已完成。

**为什么必须有这个脚本（反复踩过）**：
`novel_to_video.py` 的跳过判据**唯一**是
    `if not force and rs.clip_is_valid(out_clip): 跳过`
——**只看 `assets/04_clips/shot_NNN.mp4` 在不在**，`run_state.json` 的 done
不参与判断（只在跳过时被顺手补记）。

所以**只要改过某镜的提示词，那条镜头就必须重生成**，但 `--fresh-state` 只重置状态表，
**管不到片段文件**。结果是：
    改了分镜 → 跑 `run_chain.bat 1 2 --fresh-state` → 日志显示「已完成，跳过」
    → 本次新生成 0 镜 → 用户以为生成失败
（2026-10-06/07 连踩两次；上次归档后忘了归档下一次的产物，又踩第三次。）

**标准动作**：改完分镜 → 跑本脚本 → 再开 `run_chain.bat`。

它会做三件事：
1. `assets/04_clips/*.mp4`     → `_archive/<tag>/`（移动，不删除）
2. `assets/03_keyframes/*_prev_last.png`（I2V 接力尾帧）→ `_superseded/prev_last_<tag>/`
3. 过期成片 `assets/06_release/final.mp4` → 删除（它只由拼接生成，留着会误导）

用法：
    python tools/restage_rerun.py --dry-run
    python tools/restage_rerun.py --tag round5_before_xxx
    python tools/restage_rerun.py            # tag 自动用时间戳
"""

import argparse
import glob
import os
import shutil
import sys
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLIPS = os.path.join(ROOT, "assets", "04_clips")
KEYFRAMES = os.path.join(ROOT, "assets", "03_keyframes")
RELEASE = os.path.join(ROOT, "assets", "06_release")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="", help="归档批次名，默认用时间戳")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    tag = a.tag or ("round_%s" % datetime.now().strftime("%Y%m%d_%H%M%S"))
    clips = sorted(glob.glob(os.path.join(CLIPS, "shot_*.mp4")))
    tails = sorted(glob.glob(os.path.join(KEYFRAMES, "*_prev_last.png")))
    final = os.path.join(RELEASE, "final.mp4")

    print("=" * 74)
    print("批次名: %s" % tag)
    print("=" * 74)
    if clips:
        print("  片段 %d 个 → assets/04_clips/_archive/%s/" % (len(clips), tag))
        for p in clips:
            print("     %s  %.1f MB" % (os.path.basename(p),
                                        os.path.getsize(p) / 1048576))
    else:
        print("  片段: 无（clips 已经干净）")
    if tails:
        print("  接力尾帧 %d 个 → assets/03_keyframes/_superseded/prev_last_%s/" % (len(tails), tag))
        for p in tails:
            print("     %s" % os.path.basename(p))
    else:
        print("  接力尾帧: 无")
    if os.path.isfile(final):
        print("  过期成片 %s → 删除（%.1f MB）"
              % (os.path.relpath(final, ROOT), os.path.getsize(final) / 1048576))
    else:
        print("  过期成片: 无")

    if a.dry_run:
        print("（dry-run，未动任何文件）")
        return 0

    moved = 0
    if clips:
        dst = os.path.join(CLIPS, "_archive", tag)
        os.makedirs(dst, exist_ok=True)
        for p in clips:
            shutil.move(p, os.path.join(dst, os.path.basename(p)))
            moved += 1
    if tails:
        dst = os.path.join(KEYFRAMES, "_superseded", "prev_last_%s" % tag)
        os.makedirs(dst, exist_ok=True)
        for p in tails:
            shutil.move(p, os.path.join(dst, os.path.basename(p)))
            moved += 1
    if os.path.isfile(final):
        os.remove(final)

    print("=" * 74)
    print("完成：移动 %d 个文件（原位置留空，全部可恢复）" % moved)
    print()
    print("下一步：")
    print("  run_chain.bat <from> <to> [--fresh-state]")
    print("  （改了分镜 ⇒ 分镜 hash 变了 ⇒ 首次必须加 --fresh-state）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
