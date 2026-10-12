# -*- coding: utf-8 -*-
"""提示词构成分析：动作描述 vs 静态样板（第 22 轮）。

起因：老板反馈「人物动作不够细节、比较呆滞」，怀疑是采样步数不够。
但实测所有采样参数都在官方档位（20 步 = 官方非 turbo 档），且运动量 MAD 均值 12.55
（不低）。真正的问题在**提示词构成**：动作指令被大量静态样板稀释，
而且其中几条样板**主动压制运动**（"no physical contact"、"lips remain completely closed"）。

本脚本逐镜拆解最终 prompt：
  · 动作段（[Shot 1] 之后、第一个样板串之前）
  · 静态样板（风格/外貌/服装/场景锚/距离锁/对白 guard）
  · 冲突项（与动作要求打架的样板）

用法：
    ./.venv/Scripts/python.exe tools/analyze_prompt_composition.py
    ./.venv/Scripts/python.exe tools/analyze_prompt_composition.py --html
"""
import argparse
import json
import os
import re
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SB = os.path.join(ROOT, "assets", "01_script", "storyboard", "storyboard_ch1_v3.json")
CFG = os.path.join(ROOT, "config.json")
PY = os.path.join(ROOT, ".venv", "Scripts", "python.exe")
OUT = os.path.join(ROOT, "output", "_diag", "prompt_composition.md")
DUMP = os.path.join(ROOT, "output", "_diag", "_dump_all.txt")

# ⚠️ 引导性措辞：这些样板词会主动压制运动
MOTION_SUPPRESSORS = [
    (r"no physical contact", "禁肢体接触"),
    (r"no one closes in", "禁靠近"),
    (r"no one reaches out", "禁伸手"),
    (r"lips remain completely closed", "禁张嘴（对白 guard）"),
    (r"cold composed resting face", "冷脸/无表情"),
    (r"calm indifferent gaze", "淡漠凝视"),
    (r"no topknot no bun no hair band and no hairpin", "发型静态约束"),
    (r"holding still|holds still|perfectly motionless|rooted and", "显式静止"),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--html", action="store_true")
    a = ap.parse_args()

    # ---- dump 全片提示词 ----
    os.makedirs(os.path.dirname(DUMP), exist_ok=True)
    r = subprocess.run([PY, "novel_to_video.py",
                        "--storyboard-file", SB, "--mode", "chain",
                        "--range", "1-58", "--dump-prompts", "--fresh-state"],
                       cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="ignore")
    open(DUMP, "w", encoding="utf-8").write(r.stdout or "")
    raw = r.stdout or ""

    shots = {int(s["index"]): s for s in json.load(open(SB, encoding="utf-8"))}
    cfg = json.load(open(CFG, encoding="utf-8"))
    V = cfg["video"]

    def comp(name, scene):
        """返回该镜用到的静态样板串（名字, 文本）。"""
        items = [("3D风格串", V["style_prefix"])]
        ch = V["character"]["by_scene"].get(str(scene)) or V["character"]["default"]
        items.append(("人物外貌串", ch))
        cs = V["costume"]["by_scene"].get(str(scene)) or V["costume"]["default"]
        items.append(("服装串", cs))
        aid = shots.get(name, {}).get("anchor") or ""
        ap_ = V["scene_anchor"]["anchors"].get(aid, {})
        if ap_.get("prompt"):
            items.append(("场景锚串", ap_["prompt"]))
        dl = V["distance_lock"]["by_scene"].get(str(scene))
        if dl:
            items.append(("距离锁串", dl))
        return items

    rows = []
    for i in sorted(shots):
        seg = raw.find("### 镜 %d " % i)
        if seg < 0:
            continue
        nxt = raw.find("### 镜 ", seg + 5)
        chunk = raw[seg:nxt if nxt > 0 else len(raw)]
        m = re.search(r"integrated_multimodal_description: (.*?)\n\noverall_soundscape",
                      chunk, re.S)
        if not m:
            continue
        full = m.group(1).strip()
        s = shots[i]
        j = full.find("[Shot 1]")
        body = full[j:] if j >= 0 else full

        items = comp(i, s["scene_no"])
        static_total = sum(len(t) for _, t in items)

        # 动作段 = 从 [Shot 1] 到第一个出现的样板串起点
        cut = len(body)
        for _, t in items:
            head = t[:40]
            k = body.find(head)
            if k > 0:
                cut = min(cut, k)
        action = body[:cut].strip()

        # 对白 guard
        has_video_body = "while all on-screen characters' lips" in body

        supp = []
        for pat, label in MOTION_SUPPRESSORS:
            if re.search(pat, full, re.I):
                supp.append(label)

        total = len(full)
        rows.append(dict(n=i, sc=s["scene_no"], total=total,
                         act=len(action), stat=static_total,
                         act_pct=round(len(action) * 100.0 / total, 1),
                         supp=sorted(set(supp)), action=action))

    print("=" * 100)
    print("%-5s %-5s %8s %9s %10s   %s" % (
        "镜", "场", "总长", "动作段", "动作占比", "压制运动的样板"))
    print("-" * 100)
    for r in rows:
        print("%-5d %-5d %8d %9d %9.1f%%   %s" % (
            r["n"], r["sc"], r["total"], r["act"], r["act_pct"],
            "、".join(r["supp"]) or "-"))
    print("=" * 100)
    if rows:
        ap_ = [r["act_pct"] for r in rows]
        print("动作占比：均值 %.1f%% ｜ 中位 %.1f%% ｜ 最低 %.1f%%(镜%d) ｜ 最高 %.1f%%(镜%d)" % (
            sum(ap_) / len(ap_), sorted(ap_)[len(ap_) // 2], min(ap_),
            rows[ap_.index(min(ap_))]["n"], max(ap_),
            rows[ap_.index(max(ap_))]["n"]))
        low = [r["n"] for r in rows if r["act_pct"] < 15]
        print("动作占比 <15%% 的镜（%d 个）：%s" % (len(low), low))
        sup_cnt = {}
        for r in rows:
            for s_ in r["supp"]:
                sup_cnt[s_] = sup_cnt.get(s_, 0) + 1
        print()
        print("压制性样板出现次数：")
        for k, v in sorted(sup_cnt.items(), key=lambda x: -x[1]):
            print("   %-24s %d 镜" % (k, v))

    # ---- 报表 ----
    L = ["# 提示词构成分析：动作描述被稀释",
         "",
         "> 结论：**呆滞不是步数问题**（采样参数全在官方档位）。",
         "> 真因是动作指令只占 prompt 的极小部分，且多条样板主动压制运动。",
         "",
         "| 镜 | 场 | 总长(字符) | 动作段 | 动作占比 | 压制性样板 |",
         "|---|---|---|---|---|---|"]
    for r in rows:
        L.append("| %d | %d | %d | %d | **%.1f%%** | %s |" % (
            r["n"], r["sc"], r["total"], r["act"], r["act_pct"],
            "、".join(r["supp"]) or "-"))
    L += ["", "## 动作段原文（前 5 个最短的镜）", ""]
    for r in sorted(rows, key=lambda x: x["act"])[:5]:
        L += ["### 镜 %d（动作段仅 %d 字符，占 %.1f%%）" % (r["n"], r["act"], r["act_pct"]),
              "", "```", r["action"][:600], "```", ""]
    open(OUT, "w", encoding="utf-8").write("\n".join(L))
    print()
    print("报表 → %s" % os.path.relpath(OUT, ROOT))


if __name__ == "__main__":
    main()
