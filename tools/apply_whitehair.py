#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把场1 分镜里**方源**的头发描写从「花白/斑白」改为**纯银白**。

背景（2026-10-06）：
    老板把成年方源的形象从「花白中年」改成「20 多岁、帅气、白发男魔头」。
    `config.video.character.by_scene["1"]` 同步改写了，但**分镜里写死的 hair 描写
    不会被外貌串覆盖** —— `grizzled silver-white hair` / `花白长直发` 会和注入串
    并存打架（模型同时收到「花白」和「银白」两个指令；且 `grizzled` 自带「苍老」
    语义，会把脸往老里带，正是要修的毛病）。

⚠️ **只改方源，配角一个都不能动**：
    - 镜2 / 镜17 的「白袍魁梧中年修士」有 `grey-streaked beard` / `花白浓须`
    - 镜5 的「灰袍老修士」有 `long white beard` / `长白须`
    这些是配角设定，改了就错。所以本脚本**只用精确串匹配**，绝不全局替换「花白」，
    并且再加一层上下文守卫（命中处附近出现 cultivator/修士/beard/须/elderly 就跳过）。

幂等：重复运行无副作用（改完的串不再匹配规则）。默认干跑，加 `--apply` 才落盘。
"""
import argparse
import json
import os
import re
import sys

SB = os.path.join("assets", "01_script", "storyboard", "storyboard_ch1_v3.json")

# 精确替换规则：方源专用串
RULES = [
    ("grizzled silver-white hair", "silver-white hair"),
    ("花白长直发", "银白长直发"),
    ("长长的花白头发", "银白头发"),
]

# 上下文守卫：命中处**紧邻**位置出现这些词 → 判定为配角描写，跳过。
# 只看向后 6 字符 —— 区分点是「花白**长直发**」（方源）vs「花白**浓须**」（配角），
# 跟着的词本身就能定性。窗口开大反而误伤（镜11 的「…花白长直发、…密集的修士人群」
# 曾因 60 字符内出现「修士」被错判成配角）。
GUARDS = ("须", "beard", "胡")

# 只扫这些文本字段（其余字段不改）
FIELDS = ("video_prompt", "video_prompt_zh", "appearance", "audio_prompt", "audio_prompt_zh")


def guarded(text, start, end):
    """命中处**紧后 6 字符**内是否出现守卫词。"""
    return any(g in text[end:end + 6].lower() for g in GUARDS)


def main():
    ap = argparse.ArgumentParser(description="场1 分镜：方源头发 花白 → 银白")
    ap.add_argument("--apply", action="store_true", help="真正落盘（默认只打印计划）")
    ap.add_argument("--file", default=SB, help="分镜路径")
    a = ap.parse_args()

    with open(a.file, encoding="utf-8") as f:
        raw = f.read()
    # 探测缩进风格（本项目为 1 空格）+ 尾部是否有换行
    indent = 1 if '\n "shots"' in raw or '\n {\n "shots"' in raw else 2
    trailing_nl = raw.endswith("\n")

    data = json.loads(raw)
    shots = data["shots"] if isinstance(data, dict) else data

    plan, changed = [], 0
    for s in shots:
        if s.get("scene_no") != 1:
            continue
        for fld in FIELDS:
            v = s.get(fld)
            if not v:
                continue
            new = v
            for old, rep in RULES:
                for m in re.finditer(re.escape(old), new):
                    if guarded(new, m.start(), m.end()):
                        plan.append(("SKIP", s["index"], fld, old, "上下文像配角"))
                        continue
                    plan.append(("CHG ", s["index"], fld, old, rep))
            # 逐条安全替换（守卫过的原样保留）
            for old, rep in RULES:
                out, pos = [], 0
                for m in re.finditer(re.escape(old), v):
                    if guarded(v, m.start(), m.end()):
                        continue
                    out.append((m.start(), m.end()))
                if out:
                    pieces, last = [], 0
                    for st, en in out:
                        pieces.append(v[last:st]); pieces.append(rep); last = en
                    pieces.append(v[last:])
                    v = "".join(pieces)
            if v != new:
                changed += 1
                s[fld] = v

    for tag, idx, fld, old, info in plan:
        print(f"  [{tag}] 镜{idx:>2} [{fld}]  {old!r} -> {info!r}" if tag == "CHG "
              else f"  [{tag}] 镜{idx:>2} [{fld}]  {old!r}  ({info})")
    print(f"\n共 {sum(1 for p in plan if p[0] == 'CHG ')} 处替换 / "
          f"{sum(1 for p in plan if p[0] == 'SKIP')} 处跳过（配角） / "
          f"{changed} 个字段受影响")

    if not a.apply:
        print("\n[干跑] 未写盘。确认无误后加 --apply。")
        return 0
    if changed == 0:
        print("\n[幂等] 无可改内容，未写盘。")
        return 0

    with open(a.file, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=indent)
        if trailing_nl:
            f.write("\n")
    print(f"\n[已写盘] {a.file}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
