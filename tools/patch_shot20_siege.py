# -*- coding: utf-8 -*-
"""修掉「围成圈」旧口径的最后一圈漏网 —— 镜20 / sieg 锚图 / 场1 距离锁。

背景（2026-10-06）
------------------
老板要求：正道群雄是**一起对峙方源**，不是围成圈；群雄服饰不统一。
`patch_crowd_layout.py` 改的是「镜头提示词」，但同一个旧口径还藏在**三处非镜头文本**里，
它们照样会注进最终 prompt：

  ① `video.scene_anchor.anchors.peak_dusk_siege.prompt`
     明文 `a large loose ring of dozens of distant hostile figures ... around him`。
     镜20 是**主角镜**（_uses_protagonist=True）→ `anchor_is_first_frame=False`
     → 文字锚**照常注入**（见 novel_to_video._with_anchor）。
     镜2/11 同样中招（都是主角镜）。

  ② `video.distance_lock.by_scene["1"]`
     明文 `the encircling crowd keeps a wide, wary distance ... no one closes in`。
     这段对镜1–19 是对的（原文「都忌惮着方源的临死反扑」），但**镜20 语义相反** ——
     原文「群雄逼迫而来，恰在这时，轰的一声，方源悍然自爆」，是要压上来的。

  ③ 分镜镜20 的 `anchor`
     还挂在 `peak_dusk_siege` 上。走人工关键帧后锚图不再是首帧，但**文字锚仍会注入**，
     等于把①那句 ring 又拉回来一次。

本脚本做三件事
--------------
  1. 重写 `peak_dusk_siege.prompt`：ring → **同一阵线的散兵线**（同向对峙）+ 服饰驳杂。
     （镜20 改用关键帧后，这张锚图只剩镜2/11 在用，正好安全重画。）
  2. 重写场1 距离锁：`the encircling crowd` → `the scattered host ... on one shared front`，
     并补「兵器一律朝方源、无人对着同伴」。
  3. 镜20：`anchor` = `peak_dusk_siege` → `peak_dusk`；新增 `distance_lock: false`。
     （`distance_lock: false` 由 novel_to_video._with_distance 的单镜开关消费。）

幂等 + 备份；`--dry-run` 只打印。
"""
import argparse
import json
import os
import shutil
import sys
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CFG = os.path.join(ROOT, "config.json")
SB = os.path.join(ROOT, "assets", "01_script", "storyboard", "storyboard_ch1_v3.json")

# ---------------------------------------------------------------- 新文本
SIEGE_OLD_KEYS = ("a large loose ring", "around him")

SIEGE_NEW = (
    "on the flat cracked stone plateau of a bare grey mountain summit at dusk, "
    "a lone man seen from behind standing in the middle distance in a tattered "
    "dark jade-green robe with long loose silver-white hair falling down his back, "
    "and beyond him on the far side of the open rock a loose scattered rank of "
    "dozens of distant hostile cultivators drawn up along one shared front, "
    "no two of them dressed alike in ancient martial robes of many different "
    "colours and cuts, every one of them turned the same way facing him with "
    "weapons of every kind levelled the same way toward him and not one weapon "
    "turned on a companion, broad clear empty ground between him and the nearest "
    "of them, a soft muted dusk sky with a low red sun, distant mountain ridges "
    "receding"
)

DIST_OLD_KEYS = ("the encircling crowd",)

DIST_NEW = (
    "the scattered host stands drawn up on one shared front facing him, keeping "
    "a wide, wary distance, standing well back with clear open ground between him "
    "and the nearest enemy, every weapon levelled the same way toward him and not "
    "one turned on a companion, no one closes in, no one reaches out, no physical "
    "contact"
)

SHOT20_ANCHOR_OLD = "peak_dusk_siege"
SHOT20_ANCHOR_NEW = "peak_dusk"


def _backup(path):
    bak = "%s.bak_before_shot20siege_%s%s" % (
        os.path.splitext(path)[0],
        datetime.now().strftime("%Y%m%d_%H%M%S"),
        os.path.splitext(path)[1],
    )
    shutil.copy2(path, bak)
    return os.path.basename(bak)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    dry = not a.apply

    cfg = json.load(open(CFG, encoding="utf-8"))
    sb = json.load(open(SB, encoding="utf-8"))
    todos = []

    # ---- ① sieg 锚图 prompt ------------------------------------------------
    anc = cfg["video"]["scene_anchor"]["anchors"]["peak_dusk_siege"]
    old = anc["prompt"]
    if any(k in old for k in SIEGE_OLD_KEYS):
        todos.append(("config", "scene_anchor.peak_dusk_siege.prompt", old, SIEGE_NEW))
        anc["prompt"] = SIEGE_NEW
    else:
        print("[跳过] peak_dusk_siege.prompt 已是新口径")

    # ---- ② 场1 距离锁 ------------------------------------------------------
    dl = cfg["video"]["distance_lock"]["by_scene"]
    old = dl.get("1", "")
    if any(k in old for k in DIST_OLD_KEYS):
        todos.append(("config", "distance_lock.by_scene['1']", old, DIST_NEW))
        dl["1"] = DIST_NEW
    else:
        print("[跳过] 场1 距离锁已是新口径")

    # ---- ③ 镜20 ------------------------------------------------------------
    s20 = next((s for s in sb if int(s["index"]) == 20), None)
    if s20 is None:
        print("[错误] 分镜里找不到镜20")
        return 1
    if s20.get("anchor") == SHOT20_ANCHOR_OLD:
        todos.append(("storyboard", "#20 anchor", SHOT20_ANCHOR_OLD, SHOT20_ANCHOR_NEW))
        s20["anchor"] = SHOT20_ANCHOR_NEW
    else:
        print("[跳过] 镜20 anchor 已是 %r" % s20.get("anchor"))
    if s20.get("distance_lock") is not False:
        todos.append(("storyboard", "#20 distance_lock", repr(s20.get("distance_lock")), "False"))
        s20["distance_lock"] = False
    else:
        print("[跳过] 镜20 distance_lock 已关闭")

    # ---- 报告 --------------------------------------------------------------
    for where, key, o, n in todos:
        print("-" * 74)
        print("[%s] %s" % (where, key))
        print("  旧:", o)
        print("  新:", n)
    print("-" * 74)
    print("共 %d 处改动" % len(todos))

    if dry:
        print("\n（试运行，未写入。加 --apply 生效）")
        return 0

    if not todos:
        print("无需改动。")
        return 0

    b1 = _backup(CFG)
    b2 = _backup(SB)
    with open(CFG, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
        f.write("\n")
    with open(SB, "w", encoding="utf-8") as f:
        json.dump(sb, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print("\n已写入。备份：%s / %s" % (b1, b2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
