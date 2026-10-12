# -*- coding: utf-8 -*-
"""提高 H3 出片编码质量：SaveVideo 用 re-encode + 自定义 CRF（幂等 + 备份）。

背景（2026-10-06，老板反馈「画面又变得有点糊了，有奇怪的小方块」）：

实测四个 workflow 的产出码率只有 1.5~4 Mbps（1344x768@24fps），天空等平滑区域
出现明显的 16x16 方块边界（h264 macroblock artifact）。对比归档里的旧片段
（shot_001 4050 / shot_002 2499 / shot_003 1545 kb/s），**码率一直偏低，是这套
工作流的固有水平，不是某次改动引入的**。

根因：`SaveVideo` 节点的 `codec` 只写了 `"h264"`，**没有指定 `encoding` 子参数**，
于是走 `auto` 模式（preserve 兼容流 / 默认质量），编码器自行压码率。

ComfyUI 的 SaveVideo 支持（见 comfy_extras/nodes_video.py:89-113）：
    codec = h264  ->  encoding = auto | re-encode(crf)

API 格式（后端会把点号参数重组成嵌套 dict，见 execution.py:286）：
    "codec": "h264",
    "codec.encoding": "re-encode",
    "codec.encoding.crf": 16

⚠️ 只改 CRF，不改 `CreateVideo.bit_depth`：
   虽然 bit_depth=10 能进一步压 banding，但 10-bit h264 是 High 10 profile，
   播放器/下游兼容性差；且 assemble.py 拼接时 `-pix_fmt yuv420p` 本来就会降回
   8-bit，最终交付仍是 8-bit，中间收益不确定而风险确定。故不动。

用法：
    python tools/patch_video_quality.py --dry-run
    python tools/patch_video_quality.py --apply [--crf 16]
"""

import argparse
import json
import os
import shutil
import sys
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKFLOWS = [
    "templates/h3_i2v_api.json",
    "templates/h3_r2v_api.json",
    "templates/h3_t2v_api.json",
    "templates/h3_fl2va_api.json",
]
DEFAULT_CRF = 16


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--crf", type=float, default=DEFAULT_CRF)
    a = ap.parse_args()
    if not (a.dry_run or a.apply):
        ap.error("请指定 --dry-run 或 --apply")

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    plan, skipped, failed = [], [], []

    for rel in WORKFLOWS:
        p = os.path.join(ROOT, rel)
        if not os.path.isfile(p):
            failed.append((rel, "文件不存在"))
            continue
        d = json.load(open(p, encoding="utf-8"))
        sv = None
        for node in d.values():
            if isinstance(node, dict) and node.get("class_type") == "SaveVideo":
                sv = node
                break
        if sv is None:
            failed.append((rel, "找不到 SaveVideo 节点"))
            continue
        ins = sv.setdefault("inputs", {})
        cur = ins.get("codec.encoding")
        cur_crf = ins.get("codec.encoding.crf")
        if cur == "re-encode" and cur_crf == a.crf:
            skipped.append((rel, "已是 re-encode/crf=%s" % a.crf))
        else:
            plan.append((rel, ins.get("codec"), cur, cur_crf))

    print("=" * 76)
    for rel, codec, cur, cur_crf in plan:
        print("  [改] %-34s codec=%s  encoding: %s/crf=%s → re-encode/crf=%s"
              % (rel, codec, cur, cur_crf, a.crf))
    for rel, why in skipped:
        print("  [跳] %-34s %s" % (rel, why))
    for rel, why in failed:
        print("  [!!] %-34s %s" % (rel, why))
    print("=" * 76)
    print("待改 %d 个，已是最新 %d 个，失败 %d 个" % (len(plan), len(skipped), len(failed)))
    if failed:
        print("存在失败项，未写入任何内容。")
        return 1
    if not plan:
        print("无事可做。")
        return 0
    if a.dry_run:
        print("（dry-run，未写入）")
        return 0

    for rel, _, _, _ in plan:
        p = os.path.join(ROOT, rel)
        shutil.copy2(p, p + ".bak_before_crf_%s" % stamp)

    for rel, _, _, _ in plan:
        p = os.path.join(ROOT, rel)
        d = json.load(open(p, encoding="utf-8"))
        for node in d.values():
            if isinstance(node, dict) and node.get("class_type") == "SaveVideo":
                node["inputs"]["codec"] = "h264"
                node["inputs"]["codec.encoding"] = "re-encode"
                node["inputs"]["codec.encoding.crf"] = a.crf
                break
        with open(p, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
            f.write("\n")
        print("  [写入] %s" % rel)

    print("完成。备份后缀 .bak_before_crf_%s" % stamp)
    return 0


if __name__ == "__main__":
    sys.exit(main())
