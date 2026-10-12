# -*- coding: utf-8 -*-
"""锚图 ↔ 提示词 一致性体检（声明式 + mtime 守护 · 第 21 轮）。

⚠️ 为什么不自动读像素：试过用像素阈值判别「图里有没有草/血/雪」，
   结果祠堂锚图（木质暖褐）被判成 25% 草 + 36% 血，完全不可靠。
   色域重叠无法用简单阈值区分 ⇒ **锚图里有什么，必须人眼核验后显式声明**。

本脚本做三件事：
  1. **mtime 守护**：锚图文件的修改时间若晚于 `ANCHOR_FACTS_AT`（声明日期），
     说明换过图但声明没更新 → 报警。防止「改了锚图忘了改提示词」这类事故复发。
  2. 逐镜比对：提示词点名了「首帧里没有」的元素 → 列出，并区分硬/软约束。
  3. 输出可读报表。

用法：
    ./.venv/Scripts/python.exe tools/check_ref_prompt_consistency.py
"""
import datetime
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SB = os.path.join(ROOT, "assets", "01_script", "storyboard", "storyboard_ch1_v3.json")
CFG = os.path.join(ROOT, "config.json")
OUT = os.path.join(ROOT, "output", "_diag", "ref_prompt_consistency.md")

# 声明日期：锚图事实的人工核验时间。任何锚图 mtime 晚于此日期即报警。
ANCHOR_FACTS_AT = "2026-10-07 16:30"

# ⚠️ 人工核验后的锚图事实（True=图里有，False=图里没有，缺键=不判）
#    改动锚图后必须同步更新这里，并把 ANCHOR_FACTS_AT 推到当前时间。
ANCHOR_HAVE = {
    # 2026-10-07 16:26 重出：天空改火红晚霞 + 石缝加零星贴地枯草（图生图保构图）
    "peak_dusk": {
        "草": True, "树/植被": False, "雨": False, "雪": False, "水/水洼": False,
        "灯笼": False, "蜡烛/油灯": False, "牌位": False, "柱子": False,
        "旗帜": False, "火/炽烈天光": True, "地面血泊": False, "尸体": False,
    },
    "peak_dusk_siege": {
        "草": False, "树/植被": False, "雨": False, "雪": False, "水/水洼": False,
        "灯笼": False, "蜡烛/油灯": False, "牌位": False, "柱子": False,
        "旗帜": False, "火/炽烈天光": False, "地面血泊": False, "尸体": False,
    },
    "village_night": {"草": False, "雪": False, "灯笼": True, "雨": True,
                      "蜡烛/油灯": False, "火/炽烈天光": False,
                      "地面血泊": False, "尸体": False, "牌位": False, "柱子": False,
                      "树/植被": True, "水/水洼": False, "旗帜": False},
    "ancestral_hall": {"草": False, "雨": False, "雪": False, "灯笼": False,
                       "蜡烛/油灯": True, "牌位": True, "火/炽烈天光": False,
                       "地面血泊": False, "尸体": False, "柱子": True,
                       "树/植被": False, "水/水洼": False, "旗帜": False},
    "corridor": {"草": False, "雪": False, "灯笼": True, "雨": True, "水/水洼": True,
                 "蜡烛/油灯": False, "火/炽烈天光": False, "地面血泊": False,
                 "尸体": False, "牌位": False, "柱子": True,
                 "树/植被": False, "旗帜": False},
    "window_view": {"草": False, "雪": False, "灯笼": True, "雨": True,
                    "蜡烛/油灯": False, "火/炽烈天光": False, "地面血泊": False,
                    "尸体": False, "牌位": False, "柱子": False,
                    "树/植被": True, "水/水洼": False, "旗帜": False},
    "fangyuan_room": {"草": False, "雪": False, "灯笼": False, "雨": True,
                      "蜡烛/油灯": True, "火/炽烈天光": False, "地面血泊": False,
                      "尸体": False, "牌位": False, "柱子": True,
                      "树/植被": False, "水/水洼": False, "旗帜": False},
    "flashback": {k: False for k in ("草", "树/植被", "雨", "雪", "水/水洼", "灯笼",
                                     "蜡烛/油灯", "牌位", "柱子", "旗帜",
                                     "火/炽烈天光", "地面血泊", "尸体")},
}

ELEMENTS = {
    "草": [r"\bgrass\b", r"\btuft", r"\bweed"],
    "树/植被": [r"\btree", r"\bbranch\b", r"\bleaves\b", r"\bforest\b"],
    "雨": [r"\brain\b", r"\brainfall"],
    "雪": [r"\bsnow"],
    "水/水洼": [r"\bpuddle", r"\bpond\b"],
    "灯笼": [r"\blantern"],
    "蜡烛/油灯": [r"\bcandle", r"\boil lamp"],
    "牌位": [r"\btablet"],
    "柱子": [r"\bpillar"],
    "旗帜": [r"\bbanner\b", r"\bflag\b"],
    "火/炽烈天光": [r"\bablaze\b", r"fiery crimson", r"burning sunset", r"\bblaze\b"],
    "地面血泊": [r"pool of blood", r"dark pool", r"puddle of blood",
                 r"blood on the (ground|stone|rock)"],
    "尸体": [r"\bcorpse", r"\bbodies\b", r"\bdead body\b"],
}

# 「角色身上有血」由人物定妆图承担，不算锚图矛盾 —— 从断言里排除。
# 地面血泊才算（见 镜20 已处置为「脚下岩面染暗红」）。


def main():
    shots = json.load(open(SB, encoding="utf-8"))
    cfg = json.load(open(CFG, encoding="utf-8"))
    anchors = cfg["video"]["scene_anchor"]["anchors"]

    L = []
    W = L.append
    W("# 锚图 ↔ 提示词 一致性体检")
    W("")
    W("> 判据：`anchor_mode=i2v` **且无专属关键帧**时，锚图就是首帧（**硬约束**）；")
    W("> 提示词点名首帧里没有的元素 → H3 只能凭空生成。")
    W("> 镜1「草自己长出来」的真因就是这个（锚图原来是纯裸岩）。")
    W("")

    # ---- mtime 守护 ----
    facts_dt = datetime.datetime.strptime(ANCHOR_FACTS_AT, "%Y-%m-%d %H:%M")
    stale = []
    for name, spec in anchors.items():
        p = spec.get("image", "")
        if not p:
            continue
        full = os.path.join(ROOT, p)
        if os.path.isfile(full):
            mt = datetime.datetime.fromtimestamp(os.path.getmtime(full))
            if mt > facts_dt:
                stale.append((name, os.path.basename(p), mt))
    if stale:
        W("## ⚠️ 锚图已更新，但事实声明未同步")
        W("")
        W("以下锚图的修改时间晚于声明日期 `%s` —— 请重新核验图片内容，" % ANCHOR_FACTS_AT)
        W("更新本脚本的 `ANCHOR_HAVE`，并把 `ANCHOR_FACTS_AT` 推到当前时间：")
        W("")
        for name, fn, mt in stale:
            W("- **%s**（%s）改动于 %s" % (name, fn, mt.strftime("%Y-%m-%d %H:%M")))
        W("")

    # ---- 逐镜比对 ----
    rows = []
    for s in shots:
        idx = int(s["index"])
        aid = s.get("anchor") or ""
        have = ANCHOR_HAVE.get(aid)
        if not have:
            continue
        kf = os.path.isfile(os.path.join(
            ROOT, "assets", "03_keyframes", "shot_%03d.png" % idx))
        hard = (s.get("anchor_mode") == "i2v") and not kf
        body = str(s.get("video_prompt") or "")
        hits = [e for e, pats in ELEMENTS.items()
                if have.get(e) is False and any(re.search(p, body, re.I) for p in pats)]
        if hits:
            rows.append(dict(n=idx, sc=s["scene_no"], aid=aid, hard=hard,
                             kf=kf, hits=hits, body=body))

    hard = [r for r in rows if r["hard"]]
    soft = [r for r in rows if not r["hard"]]

    W("## ★ 硬约束矛盾（锚图=首帧）")
    W("")
    if hard:
        W("| 镜 | 场 | 锚 | 点名但首帧没有 |")
        W("|---|---|---|---|")
        for r in hard:
            W("| **%d** | %d | %s | %s |" % (r["n"], r["sc"], r["aid"], "、".join(r["hits"])))
        W("")
        for r in hard:
            W("### 镜 %d（场%d，锚 %s）" % (r["n"], r["sc"], r["aid"]))
            W("")
            W("- **点名但首帧没有**：" + "、".join(r["hits"]))
            for e in r["hits"]:
                for p in ELEMENTS[e]:
                    m = re.search(p + r"[\w\s,'-]{0,70}", r["body"], re.I)
                    if m:
                        W("- `…%s…`" % m.group(0).strip())
                        break
            W("")
    else:
        W("（无）")
        W("")

    W("## · 软影响（有专属关键帧覆盖，首帧不是锚图）")
    W("")
    if soft:
        W("| 镜 | 场 | 锚 | 点名但锚图没有 |")
        W("|---|---|---|---|")
        for r in soft:
            W("| %d | %d | %s | %s |" % (r["n"], r["sc"], r["aid"], "、".join(r["hits"])))
    else:
        W("（无）")
    W("")

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    open(OUT, "w", encoding="utf-8").write("\n".join(L))

    print("=" * 78)
    if stale:
        print("⚠️ 锚图已更新但声明未同步：")
        for name, fn, mt in stale:
            print("   %s（%s）改动于 %s" % (name, fn, mt.strftime("%Y-%m-%d %H:%M")))
        print()
    print("★ 硬约束矛盾（锚图=首帧）：%d 镜" % len(hard))
    for r in hard:
        print("   镜%-3d 场%d 锚%-16s 缺: %s" % (r["n"], r["sc"], r["aid"], "、".join(r["hits"])))
    print("· 软影响（有关键帧）：%d 镜" % len(soft))
    for r in soft:
        print("   镜%-3d 场%d 锚%-16s 缺: %s" % (r["n"], r["sc"], r["aid"], "、".join(r["hits"])))
    print("=" * 78)
    print("报表 → %s" % os.path.relpath(OUT, ROOT))


if __name__ == "__main__":
    main()
