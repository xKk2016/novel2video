# -*- coding: utf-8 -*-
"""切换工作流模板的底模（UNETLoader.unet_name），输出为新模板文件。

背景：
    H3 有四档底模，pruned 版本有 AdaLN LoRA 形状不兼容问题（社区实测），
    非 pruned 版更稳但体积大（int8_convrot 31.7GB vs pruned 19.5GB）。
    需要能快速在「生产档 / 非 pruned 实验档」之间切换且可回退。

用法：
    # 只改底模
    ./.venv/Scripts/python.exe tools/switch_base_model.py \\
        --src templates/h3_i2v_api.json \\
        --out templates/h3_i2v_nonpruned_api.json \\
        --unet minimax_h3_fl2va_int8_convrot.safetensors

    # 看当地有哪些可选底模
    ./.venv/Scripts/python.exe tools/switch_base_model.py --list
"""
import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DM_DIR = (r"C:\ComfyUI\v0.30.0\ComfyUI_windows_portable_nvidia"
          r"\ComfyUI_windows_portable\ComfyUI\models\diffusion_models")


def find_unet_node(d):
    for nid, v in d.items():
        if isinstance(v, dict) and v.get("class_type") == "UNETLoader":
            return nid, v
    return None, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", help="源模板（相对项目根或绝对路径）")
    ap.add_argument("--out", help="输出模板")
    ap.add_argument("--unet", help="新底模文件名")
    ap.add_argument("--list", action="store_true", help="列出可用底模")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    if a.list:
        print("可用的 H3 底模（%s）:" % DM_DIR)
        if not os.path.isdir(DM_DIR):
            print("  ⛔ 目录不存在")
            return 1
        for f in sorted(os.listdir(DM_DIR)):
            if not f.endswith(".safetensors"):
                continue
            gb = os.path.getsize(os.path.join(DM_DIR, f)) / 1073741824
            tag = "pruned" if "pruned" in f else "非pruned"
            print("  %-56s %7.2f GB  [%s]" % (f, gb, tag))
        return 0

    for req in ("src", "out", "unet"):
        if not getattr(a, req):
            print("⛔ 缺 --%s" % req)
            return 1

    src = a.src if os.path.isabs(a.src) else os.path.join(ROOT, a.src)
    out = a.out if os.path.isabs(a.out) else os.path.join(ROOT, a.out)
    if not os.path.isfile(src):
        print("⛔ 源模板不存在：%s" % src)
        return 1

    d = json.load(open(src, encoding="utf-8"))
    nid, node = find_unet_node(d)
    if node is None:
        print("⛔ 模板里找不到 UNETLoader")
        return 1

    old = node["inputs"]["unet_name"]
    if not os.path.isfile(os.path.join(DM_DIR, a.unet)):
        print("⚠️ 底模文件在 %s 里不存在：%s" % (DM_DIR, a.unet))
        print("   仍会写入模板（ComfyUI 跑时才报错）。--list 可看可用列表。")
    if old == a.unet:
        print("⚠️ 底模没变化（%s）" % old)

    node["inputs"]["unet_name"] = a.unet
    d.setdefault("_comment_base", "")
    d["_comment_base"] = ("底模已切换：%s → %s。由 tools/switch_base_model.py 生成，"
                          "勿手改 —— 要换底模改脚本参数重跑。" % (old, a.unet))

    print("源模板 : %s" % os.path.relpath(src, ROOT))
    print("输出   : %s" % os.path.relpath(out, ROOT))
    print("节点 %s : %s" % (nid, old))
    print("      → %s" % a.unet)

    if a.dry_run:
        print("\n[DRY-RUN] 未落盘。")
        return 0

    with open(out, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
    chk = json.load(open(out, encoding="utf-8"))
    _, cnode = find_unet_node(chk)
    ok = cnode["inputs"]["unet_name"] == a.unet
    print("\n%s 已写入 %s" % ("✓" if ok else "⚠", os.path.relpath(out, ROOT)))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
