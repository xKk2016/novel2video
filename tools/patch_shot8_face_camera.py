#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把镜 8 背景群雄的朝向由「背对镜头」修回「正脸朝镜头」。

**为什么**：镜 8 是女群雄（正道群雄丁）的正面特写，机位在方源这一侧 ——
她看镜头 = 看方源。她身后的群雄本该同她一个朝向（面朝画外的方源），
也就该**正脸朝镜头**。

上一轮（`patch_young_woman.py` + 出图）只写了 `all turned the same way toward
the man off frame`，模型把「同一个方向」解成了**背对镜头**（老版是正脸朝镜头）。
这里把朝向写成显式的「面朝镜头、脸朝镜头」，中英同步。

只动镜 8 的朝向措辞，其余（年轻清丽容貌 / 群雄驳杂服饰 / 台词）一律不碰。
幂等：已是新句则跳过。
用法：
  python tools/patch_shot8_face_camera.py --dry-run
  python tools/patch_shot8_face_camera.py --apply
"""
import argparse
import json
import os
import shutil
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SB = os.path.join(ROOT, "assets", "01_script", "storyboard", "storyboard_ch1_v3.json")

# 旧句 -> 新句（中英各一对）
EN_OLD = ("all turned the same way toward the man off frame, no weapon of theirs "
          "raised at her or at each other")
EN_NEW = ("every one of them FACING THE CAMERA, front-facing with their faces turned "
          "to the lens, squared the same way she faces toward the man off frame beyond "
          "the lens, no weapon of theirs raised at her or at each other")

ZH_OLD = "所有人朝向同一方向、面朝画外那个人，无人对她或对彼此举起兵器。"
ZH_NEW = "所有人面朝镜头方向、正脸朝镜头，与她的朝向一致、共同面朝镜头这一侧画外的方源，无人对她或对彼此举起兵器。"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    if not os.path.isfile(SB):
        sys.exit("找不到分镜文件 %s" % SB)

    with open(SB, encoding="utf-8") as f:
        data = json.load(f)

    hits = 0
    for s in data:
        try:
            idx = int(s.get("index"))
        except (TypeError, ValueError):
            continue
        if idx != 8:
            continue

        en = s.get("video_prompt", "")
        zh = s.get("video_prompt_zh", "")

        if EN_NEW in en and ZH_NEW in zh:
            print("  镜 8 已是目标状态，跳过")
            continue

        if EN_OLD in en:
            en = en.replace(EN_OLD, EN_NEW)
            s["video_prompt"] = en
            print("  镜 8 英文：朝向 -> 面朝镜头 ✓")
        else:
            print("  !! 镜 8 英文没匹配到旧句，请人工核对", file=sys.stderr)

        if ZH_OLD in zh:
            zh = zh.replace(ZH_OLD, ZH_NEW)
            s["video_prompt_zh"] = zh
            s["scene"] = zh[:80]
            print("  镜 8 中文：朝向 -> 面朝镜头 ✓")
        else:
            print("  !! 镜 8 中文没匹配到旧句，请人工核对", file=sys.stderr)

        hits += 1

    if hits == 0:
        print("无需改动。")
        return

    if a.dry_run or not a.apply:
        print("\n[dry-run] 将改动 1 镜。加 --apply 生效。")
        return

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = os.path.join(os.path.dirname(SB), "storyboard_ch1_v3.bak_before_shot8face_%s.json" % stamp)
    shutil.copy2(SB, bak)
    with open(SB, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print("\n已写入 %s\n备份 %s" % (SB, bak))


if __name__ == "__main__":
    main()
