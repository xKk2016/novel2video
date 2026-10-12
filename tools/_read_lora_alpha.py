# -*- coding: utf-8 -*-
"""读 LoRA 各张量的真实 alpha 值 + rank，推算 ComfyUI 实际 scale = alpha/rank。"""
import json
import struct
import sys
import os
from collections import Counter


def read_header(path):
    with open(path, "rb") as f:
        n = struct.unpack("<Q", f.read(8))[0]
        return json.loads(f.read(n).decode("utf-8"))


for p in sys.argv[1:]:
    print("=" * 74)
    print(os.path.basename(p))
    h = read_header(p)
    meta = h.get("__metadata__", {})
    print("  training_rank=%s training_alpha=%s training_scale=%s" % (
        meta.get("training_rank"), meta.get("training_alpha"),
        meta.get("training_scale")))
    alphas = []
    ranks = Counter()
    for k, v in h.items():
        if k == "__metadata__":
            continue
        if k.endswith(".alpha"):
            alphas.append(v.get("data_offsets") and None)
    # 需要读实际数值: alpha 是 1 元素 float。用 numpy 读。
    import numpy as np
    with open(p, "rb") as f:
        n = struct.unpack("<Q", f.read(8))[0]
        f.read(n)
        base = 8 + n
        vals = []
        for k, v in h.items():
            if k == "__metadata__":
                continue
            if k.endswith(".alpha"):
                s, e = v["data_offsets"]
                f.seek(base + s)
                vals.append(np.frombuffer(f.read(e - s), dtype=np.float32)[0])
        for k, v in h.items():
            if k == "__metadata__":
                continue
            if k.endswith(".lora_a.weight") and isinstance(v.get("shape"), list):
                ranks[tuple(v["shape"])] += 1
    c = Counter(round(float(x), 6) for x in vals)
    print("  alpha 张量数=%d  取值分布=%s" % (len(vals), dict(c.most_common(5))))
    print("  lora_* 权重键样例:", [k for k in h if k.endswith(".weight")][:2])
