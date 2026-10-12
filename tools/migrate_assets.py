"""资产分层迁移 —— 把散落的资产按「六环节流水线」归位到 assets/01..06。

目标结构（与 novel-to-video skill 的环节编号一一对应）

    assets/
      01_script/     剧本与分镜   source/ storyboard/ reports/ _archive/
      02_design/     定妆资产     characters/<角色>/ scenes/ props/
      03_keyframes/  分镜关键帧   shot_NNN.png（人工）/ shot_NNN_prev_last.png（运行时中间产物）
      04_clips/      视频片段     shot_NNN.mp4
      05_audio/      配音与音效
      06_release/    成片
      _archive/      废弃代次与历史产物

原则
  · 只移动，不删除。迁移前后各算一次 md5，不一致立即中止。
  · 幂等。源已消失且目标就位 = 已迁移，跳过（可反复执行）。
  · 默认只打印计划，`--apply` 才真正落盘。

用法
    python tools/migrate_assets.py             # 看计划
    python tools/migrate_assets.py --apply     # 执行
"""
import argparse
import glob
import hashlib
import os
import shutil
import sys

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
A = "assets"

SCENES = ["peak_dusk", "village_night", "ancestral_hall",
          "corridor", "window_view", "fangyuan_room"]
ROLES = ["fangyuan_adult", "fangyuan_youth"]
VIEWS = ["front", "side", "face", "back"]

# ---------------------------------------------------------------- 目标目录
DIRS = [
    f"{A}/01_script/source",
    f"{A}/01_script/storyboard",
    f"{A}/01_script/reports",
    f"{A}/01_script/_archive",
    f"{A}/02_design/characters/fangyuan_adult",
    f"{A}/02_design/characters/fangyuan_youth",
    f"{A}/02_design/scenes",
    f"{A}/02_design/props",
    f"{A}/03_keyframes",
    f"{A}/04_clips/_archive/round1_before_fix",
    f"{A}/05_audio",
    f"{A}/06_release",
    f"{A}/_archive/design/gen3",
    f"{A}/_archive/design/gen4",
    f"{A}/_archive/design/gen4_clean",
    f"{A}/_archive/raw",
    f"{A}/_archive/release",
]

# 迁完后可清理的空目录（仅限这些，避免误删）
PRUNE = ["refs/3d", "refs/3d_v3", "refs/3d_v3_clean", "refs/_archive/3d_gen3",
         "refs/_archive", "refs", "output/clips", "output/keyframes",
         "output/3d_raw", "output/_kf_raw"]

# ---------------------------------------------------------------- 迁移计划
MOVES = []


def add(src, dst):
    MOVES.append((src, dst))


def add_glob(pattern, dst_dir, rename=None):
    hits = sorted(glob.glob(os.path.join(ROOT, pattern)))
    for p in hits:
        rel = os.path.relpath(p, ROOT).replace("\\", "/")
        if rel in {s for s, _ in MOVES}:
            continue
        name = rename(p) if rename else os.path.basename(p)
        add(rel, f"{dst_dir}/{name}")


# ---- ① 剧本与分镜 ----
add("daxianzun_ch1.txt", f"{A}/01_script/source/daxianzun_ch1.txt")
add("sample_chapter.txt", f"{A}/01_script/source/sample_chapter.txt")
add("output/storyboard_ch1_v3.json", f"{A}/01_script/storyboard/storyboard_ch1_v3.json")
add("output/分镜v3_双语对照.md", f"{A}/01_script/reports/分镜v3_双语对照.md")

# 旧版剧本 / 旧版分镜 / 备份 / 旧报告 → 01_script/_archive
add_glob("output/script*.json", f"{A}/01_script/_archive")
add_glob("output/storyboard_pilot.json", f"{A}/01_script/_archive")
add_glob("output/storyboard_anime.json", f"{A}/01_script/_archive")
add_glob("output/storyboard_ch1_v2.json", f"{A}/01_script/_archive")
add_glob("output/storyboard_ch1_v3.bak_*.json", f"{A}/01_script/_archive")
add_glob("output/分镜v2_重写报告.md", f"{A}/01_script/_archive")

# ---- ② 定妆资产（先定妆再开拍）----
for role in ROLES:
    for view in VIEWS:
        add(f"refs/3d/{role}_{view}.png",
            f"{A}/02_design/characters/{role}/{view}.png")
for sc in SCENES:
    add(f"refs/3d/anchor_{sc}.png", f"{A}/02_design/scenes/{sc}.png")

# 废弃代次 → _archive/design
for gen, src in (("gen3", "refs/_archive/3d_gen3"),
                 ("gen4", "refs/3d_v3"),
                 ("gen4_clean", "refs/3d_v3_clean")):
    for sc in SCENES:
        add(f"{src}/anchor_{sc}.png", f"{A}/_archive/design/{gen}/{sc}.png")

# 原始出图（未裁剪/未去水印）
add_glob("output/3d_raw/*.png", f"{A}/_archive/raw")
add_glob("output/_kf_raw/*.png", f"{A}/_archive/raw")

# ---- ③ 分镜关键帧 ----
add_glob("output/keyframes/*.png", f"{A}/03_keyframes")
add_glob("output/_archive/keyframes/*.png", f"{A}/03_keyframes/_superseded",
         rename=lambda p: os.path.basename(p))

# ---- ④ 视频片段 ----
add_glob("output/clips/*.mp4", f"{A}/04_clips")
add_glob("output/_archive/round1_before_fix/*.mp4",
         f"{A}/04_clips/_archive/round1_before_fix")

# ---- ⑥ 成片 ----
add("output/final.mp4", f"{A}/06_release/final.mp4")
add("output/_bak_final_pre_v2_20261005.mp4",
    f"{A}/_archive/release/final_pre_v2_20261005.mp4")


# ---------------------------------------------------------------- 执行
def md5(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def human(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


def size_of(path):
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="真正执行迁移")
    args = ap.parse_args()

    print(f"项目根：{ROOT}")
    print(f"计划：{len(DIRS)} 个目录，{len(MOVES)} 个文件\n")

    if not args.apply:
        for src, dst in MOVES:
            mark = "OK " if os.path.exists(os.path.join(ROOT, src)) else "?? "
            if not os.path.exists(os.path.join(ROOT, src)) and \
                    os.path.exists(os.path.join(ROOT, dst)):
                mark = "-- "
            print(f" {mark}{src}\n      -> {dst}")
        print("\n（计划模式，未落盘。加 --apply 执行）")
        return 0

    # 1. 建目录
    for d in DIRS:
        os.makedirs(os.path.join(ROOT, d), exist_ok=True)
    print(f"[1/3] 目录就绪（{len(DIRS)} 个）")

    # 2. 搬文件
    done = skipped = missing = conflict = 0
    total_bytes = 0
    for src_rel, dst_rel in MOVES:
        src = os.path.join(ROOT, src_rel)
        dst = os.path.join(ROOT, dst_rel)

        if not os.path.exists(src):
            if os.path.exists(dst):
                skipped += 1
            else:
                missing += 1
                print(f"  [!!] 源缺失且目标不存在：{src_rel}")
            continue

        if os.path.exists(dst):
            if size_of(src) == size_of(dst) and md5(src) == md5(dst):
                skipped += 1
                print(f"  [--] 目标已存在且内容一致，源保留：{dst_rel}")
            else:
                conflict += 1
                print(f"  [XX] 目标已存在且内容不同，跳过：{dst_rel}")
            continue

        before = md5(src)
        nbytes = size_of(src)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.move(src, dst)
        after = md5(dst)
        if before != after:
            print(f"  [XX] md5 不一致！{src_rel} -> {dst_rel}（已中止）")
            return 1
        done += 1
        total_bytes += nbytes

    print(f"[2/3] 迁移完成：成功 {done}，已就位跳过 {skipped}，"
          f"缺失 {missing}，冲突 {conflict}（{human(total_bytes)}）")

    # 3. 清理空目录
    pruned = 0
    for d in PRUNE:
        p = os.path.join(ROOT, d)
        if os.path.isdir(p) and not os.listdir(p):
            try:
                os.rmdir(p)
                pruned += 1
            except OSError:
                pass
    print(f"[3/3] 清理空目录 {pruned} 个")

    if conflict:
        print("\n[!] 有冲突项需要人工确认，未做删除。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
