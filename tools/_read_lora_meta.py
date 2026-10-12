# -*- coding: utf-8 -*-
"""读 safetensors LoRA 头部元数据（找 training shift / 步数 / 分辨率线索）。"""
import json
import struct
import sys
import os

def read_header(path):
    with open(path, "rb") as f:
        n = struct.unpack("<Q", f.read(8))[0]
        raw = f.read(n)
    return json.loads(raw.decode("utf-8"))

for p in sys.argv[1:]:
    print("=" * 72)
    print(os.path.basename(p), "%.2f GB" % (os.path.getsize(p) / 1e9))
    try:
        h = read_header(p)
    except Exception as e:
        print("  读取失败:", e)
        continue
    meta = h.get("__metadata__", {})
    for k, v in meta.items():
        s = str(v)
        print("  %-34s %s" % (k, s[:200]))
    keys = [k for k in h.keys() if k != "__metadata__"]
    print("  张量数:", len(keys))
    print("  样例键:", keys[:3])
    # 找 shift 相关
    joined = json.dumps(meta, ensure_ascii=False).lower()
    for kw in ("shift", "sigma", "step", "nfe", "resolution", "768", "544"):
        if kw in joined:
            print("  [命中关键词]", kw)
