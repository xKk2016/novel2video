#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把本轮画好的关键帧去水印、按镜号落地到 assets/03_keyframes/shot_NNN.png。

为什么需要脚本：关键帧的落点命名（shot_NNN.png）是**该镜走哪条路的开关** ——
`_plan_for()` 见到文件存在就把该镜强制切到 `I2V 关键帧`，优先级压过接力/换位/锚定。
所以改名必须与镜号严格对应，手工 cp 容易挂错。

⚠️ 已存在的同名文件会先移到 `assets/03_keyframes/_superseded/`（不删除）。

用法：
  python tools/build_keyframes.py --dry-run
  python tools/build_keyframes.py
"""
import argparse
import os
import shutil
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dewatermark  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KF_DIR = os.path.join(ROOT, "assets", "03_keyframes")
SUP_DIR = os.path.join(KF_DIR, "_superseded")

# 1536x864 关键帧的水印框（含外扩）。
# ⚠️ clean_one() 收的是 (x, y, w, h) 元组，不是 CLI 的 "x,y,w,h" 字符串。
# ⚠️ 框的**右边界与下边界必须贴住图像边界**（1536 / 864）：水印紧贴右下角，
#    贴边的那条边才会被 seam_fill 判定为「不羽化」而完整覆盖 —— 否则羽化带会把
#    水印下缘（WORKBUDDY）原样留下。旧值 118x102 就踩了这个坑。
BOX = (1416, 758, 120, 106)
MODE = "seam"

RAW = os.path.join(ROOT, "output", "_kf_raw")
RAW2 = os.path.join(ROOT, "output", "_kf_raw2")
RAW3 = os.path.join(ROOT, "output", "_kf_raw3")
RAW4 = os.path.join(ROOT, "output", "_kf_raw4")
RAW5 = os.path.join(ROOT, "output", "_kf_raw5")
RAW6 = os.path.join(ROOT, "output", "_kf_raw6")
RAW7 = os.path.join(ROOT, "output", "_kf_raw7")

# ⚠️ 3/4/5/6/8/17/18/19 于 2026-10-06 因「正道群雄排布 + 服饰」修正重出（RAW3）。
#    4 与 18 各有 v1/v2 两版：v1 = 群雄左右夹道版（废），v2 = 散兵线同向版（采用）。
# ⚠️ 7/8 于 2026-10-06 因「正道群雄丁（女）改年轻清丽」重出（RAW4），覆盖 RAW2/RAW3 版。
MAP = [
    (3, f"{RAW3}/Keyframe_shot_3__Clean_sharp_h_2026-10-06T07-00-45.png"),
    (4, f"{RAW3}/Keyframe_shot_4__Clean_sharp_h_2026-10-06T07-00-01.png"),
    (5, f"{RAW3}/Keyframe_shot_5__Clean_sharp_h_2026-10-06T07-00-01.png"),
    (6, f"{RAW3}/Keyframe_shot_6__Clean_sharp_h_2026-10-06T07-00-44.png"),
    (7, f"{RAW4}/Keyframe_shot_7__Clean_sharp_h_2026-10-06T07-06-47.png"),
    # 8 于 2026-10-06 二次重出：RAW4 版群雄背对镜头（废）-> RAW5 版正脸朝镜头（采用）
    (8, f"{RAW5}/Keyframe_shot_8__Clean_sharp_h_2026-10-06T07-10-00.png"),
    (9, f"{RAW2}/Tight_medium_shot_of_the_blood_2026-10-06T06-41-25.png"),
    (12, f"{RAW2}/Tight_medium_shot_of_the_silve_2026-10-06T06-42-07.png"),
    (13, f"{RAW2}/_pick_shot013_low.png"),
    (15, f"{RAW2}/Tight_close_up_of_the_silver_h_2026-10-06T06-42-03.png"),
    (16, f"{RAW2}/Tight_shot_of_the_silver_haire_2026-10-06T06-42-07.png"),
    (17, f"{RAW3}/Keyframe_shot_17__Clean_sharp__2026-10-06T07-00-44.png"),
    (18, f"{RAW3}/Keyframe_shot_18__Clean_sharp__2026-10-06T07-00-03.png"),
    (19, f"{RAW3}/Keyframe_shot_19__Clean_sharp__2026-10-06T07-00-45.png"),
    # 20 于 2026-10-06 新增：拆镜后新镜20 = 「群雄压上」。原走 peak_dusk_siege 当参考图，
    #    而那张图与它的文字锚都是旧「围成圈」口径（见 tools/patch_shot20_siege.py），
    #    故改为人工关键帧走 I2V（RAW7）。
    #    v1 方源背对镜头、与群雄同向（废）-> v2 方源正对镜头、与联军面对面（采用）。
    (20, f"{RAW7}/Keyframe_shot_20_v2__Clean_sha_2026-10-06T07-41-34.png"),
    # 21 于 2026-10-06 由「拆镜20」新增：
    #    原镜20 的「群雄压上 + 自爆」两拍拆开，自爆独立成镜 21（RAW6）。
    (21, f"{RAW6}/Keyframe_shot_21__Clean_sharp__2026-10-06T07-30-26.png"),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--only", default="", help="只处理这些镜号，逗号分隔，如 3,4,5")
    a = ap.parse_args()

    want = {int(x) for x in a.only.split(",") if x.strip()} if a.only else None
    todo = [kv for kv in MAP if want is None or kv[0] in want]

    missing = [(n, p) for n, p in todo if not os.path.isfile(p)]
    if missing:
        for n, p in missing:
            print("!! 源图缺失 镜%d：%s" % (n, p), file=sys.stderr)
        return 1

    os.makedirs(KF_DIR, exist_ok=True)
    os.makedirs(SUP_DIR, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    failed = []

    for n, src in todo:
        dst = os.path.join(KF_DIR, "shot_%03d.png" % n)
        if a.dry_run:
            print("[dry-run] 镜%-3d <- %s" % (n, os.path.basename(src)))
            continue
        # 先去水印到临时文件，成功后再归档旧图、原子替换 —— 失败不留半成品
        tmp = dst + ".tmp.png"
        if not dewatermark.clean_one(src, out_path=tmp, box=BOX, mode=MODE, verbose=False):
            print("  [失败] 镜%-3d 去水印未完成：%s" % (n, os.path.relpath(src, ROOT)), file=sys.stderr)
            failed.append(n)
            continue
        if os.path.isfile(dst):
            sup = os.path.join(SUP_DIR, "shot_%03d_%s.png" % (n, stamp))
            shutil.move(dst, sup)
            print("  [归档] 旧 %s -> %s" % (os.path.basename(dst), os.path.relpath(sup, ROOT)))
        os.replace(tmp, dst)
        print("  [落地] 镜%-3d -> %s" % (n, os.path.relpath(dst, ROOT)))

    if failed:
        print("!! %d 张失败：%s" % (len(failed), failed), file=sys.stderr)
        return 1
    print("完成 %d 张" % len(todo))
    return 0


if __name__ == "__main__":
    sys.exit(main())
