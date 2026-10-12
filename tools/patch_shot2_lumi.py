# -*- coding: utf-8 -*-
"""为「Anime2Realsim__H3」LoRA 实验生成分镜副本，给镜2 注入触发词。

**为什么要副本**：触发词只在该 LoRA 挂载时才有意义，写进生产分镜会污染其他实验。
本脚本从生产分镜复制一份 `storyboard_ch1_v3_lumi.json`，只改镜2。

触发词来自 Civitai 模型页 2783657（"Anime to Realism - Minimax H3 ref2v v1.0"），
作者给了三套，这里选**「精致电影实拍」**那套 —— 与项目 3D CG 电影感路线最一致。

用法：
    ./.venv/Scripts/python.exe tools/patch_shot2_lumi.py          # 预览
    ./.venv/Scripts/python.exe tools/patch_shot2_lumi.py --apply  # 落盘
"""
import argparse
import json
import os
import shutil
import sys

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "assets/01_script/storyboard/storyboard_ch1_v3.json")
DST = os.path.join(ROOT, "assets/01_script/storyboard/storyboard_ch1_v3_lumi.json")

LUMI_EN = (
    "LumiReal, premium cinematic live-action style. Recreate the anime reference in a "
    "premium cinematic live-action style, with attractive character casting, refined yet "
    "natural facial features, realistic skin texture, professional film lighting, believable "
    "environments, and scene-appropriate cinematic effects, while preserving the subjects, "
    "distinctive character features, pose, composition, clothing, objects, setting, and "
    "color palette."
)
LUMI_ZH = (
    "LumiReal，顶级电影实拍风格。将动画参考重塑为顶级电影实拍质感：富有魅力的角色选角、"
    "精致而自然的面部特征、真实的皮肤质感、专业的电影灯光、可信的环境，以及契合场景的"
    "电影化效果；同时保持主体、角色独有特征、姿态、构图、服装、道具、场景与色彩基调不变。"
)
MARK = "LumiReal, premium cinematic live-action style."


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    if not os.path.isfile(SRC):
        raise SystemExit("生产分镜不存在：%s" % SRC)
    d = json.load(open(SRC, encoding="utf-8"))
    s2 = next((x for x in d if x["index"] == 2), None)
    if s2 is None:
        raise SystemExit("没找到镜2")
    orig_len = len(s2["video_prompt"])

    if MARK in s2["video_prompt"]:
        print("⚠️ 镜2 已含触发词，跳过（避免重复注入）")
    else:
        s2["video_prompt"] = LUMI_EN + " " + s2["video_prompt"]
        if "video_prompt_zh" in s2:
            s2["video_prompt_zh"] = LUMI_ZH + " " + s2["video_prompt_zh"]

    print("源分镜 : %s" % os.path.basename(SRC))
    print("目标   : %s" % os.path.basename(DST))
    print()
    print("镜2 video_prompt 前 300 字：")
    print("  " + s2["video_prompt"][:300])
    print()
    print("镜2 video_prompt 长度 %d（原 %d）" % (len(s2["video_prompt"]), orig_len))
    print("其他 57 镜：未改动")

    if not a.apply:
        print("\n[dry-run] 未写文件。加 --apply 落盘。")
        return 0
    json.dump(d, open(DST, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("\n✓ 已写入 %s" % DST)
    return 0


if __name__ == "__main__":
    sys.exit(main())
