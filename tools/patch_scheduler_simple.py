"""把 H3 四个工作流的采样调度器在 simple / normal 之间切换（幂等 + 备份）。

背景（2026-10-07 音频血案）
--------------------------
2026-10-06「下半场」按一条**出处无法回溯的推断**（"参考图重的 prompt 建议用
beta/normal"），把四模板的 `scheduler` 统一从 `simple` 改成了 `normal`。

后果：从那一刻起 H3 出的音频**全部损坏** —— 左右声道互不相关
（L/R 相关 0.99 → 0.18~0.59），mid/side 分析显示 **Side/Mid 从 −23 dB 暴涨到 −1.5 dB**，
主观听感就是「水泡音 + 人声回声 + 背景浑浊」。

实测标定（L/R 相关系数 / Side-Mid 能量比）：

    scheduler  样本                      L/R 相关    Side/Mid
    simple     i2v 88/89/90/91 (37次)    0.990~0.991  −22 ~ −24 dB   ✓ 健康
    normal     i2v 92/93/94              0.593→0.175  −5.9 → −1.5 dB ✗ 损坏

机制推断：`simple` 末步 σ=0.387 硬着陆直接归零；`normal` 收尾覆盖到 σ=0.126，
在低噪段多走 2 档。H3 是音视频联合生成、音频 latent 与视频共用同一个 DiT，
低噪段的额外细化让**音频的双声道失去一致性**（同族调度器的差别只在末端覆盖深度）。

⚠️ 说明：`normal` 对**画面**没有问题（它甚至更"细"）；它毁的是**音频的立体声一致性**。

用法
----
    python tools/patch_scheduler_simple.py --to simple [--dry-run]
    python tools/patch_scheduler_simple.py --to normal
"""

import argparse
import json
import os
import shutil
import sys
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TPL = os.path.join(ROOT, "templates")

# 文件 -> (含 scheduler 的节点 class_type 集合)
TARGETS = {
    "h3_i2v_api.json": {"KSampler"},
    "h3_r2v_api.json": {"BasicScheduler"},
    "h3_t2v_api.json": {"KSampler"},
    "h3_fl2va_api.json": {"KSampler"},
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--to", choices=["simple", "normal"], required=True,
                    help="目标调度器；健康值为 simple")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    plan, skipped = [], []

    for fname, classes in TARGETS.items():
        path = os.path.join(TPL, fname)
        if not os.path.isfile(path):
            skipped.append("%s 不存在" % fname)
            continue
        data = json.load(open(path, encoding="utf-8"))
        hits = 0
        for nid, node in data.items():
            if not isinstance(node, dict):
                continue
            if node.get("class_type") not in classes:
                continue
            ins = node.get("inputs") or {}
            if "scheduler" not in ins:
                continue
            cur = ins["scheduler"]
            if cur == a.to:
                skipped.append("%s 节点%s 已是 %s" % (fname, nid, a.to))
                continue
            plan.append("%s 节点%s: scheduler %r -> %r" % (fname, nid, cur, a.to))
            if not a.dry_run:
                ins["scheduler"] = a.to
            hits += 1
        if hits and not a.dry_run:
            bak = path + ".bak_before_sched_%s" % stamp
            shutil.copy2(path, bak)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                f.write("\n")

    print("== 计划 ==")
    for x in plan:
        print("  ", x)
    if skipped:
        print("== 跳过 ==")
        for x in skipped:
            print("  ", x)
    print()
    if a.dry_run:
        print("[dry-run] 未写入。去掉 --dry-run 生效。")
    else:
        print("已应用 %d 处；备份后缀 .bak_before_sched_%s" % (len(plan), stamp))
        if plan:
            print()
            print("⚠️ 采样器变了 => 产出音频会变，重跑前务必先 restage：")
            print("   ./.venv/Scripts/python.exe tools/restage_rerun.py --tag before_sched_%s" % a.to)


if __name__ == "__main__":
    main()
