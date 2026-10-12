# -*- coding: utf-8 -*-
"""量化 LoRA 的有效更新量：eff = (alpha/rank) * ||B @ A||_F。

ComfyUI 施加的更新 = strength * (alpha/rank) * B@A，
所以 eff 就是 strength=1.0 时模型真正吃到的扰动幅度。
用 tr(A^T B^T B A) = <B^T B, A A^T> 算，只涉及 rank×rank 小矩阵。
"""
import json
import os
import struct
import sys

import numpy as np

LORA_DIR = (r"C:/ComfyUI/v0.30.0/ComfyUI_windows_portable_nvidia/"
            r"ComfyUI_windows_portable/ComfyUI/models/loras")

LAYERS = [
    "diffusion_model.blocks.0.attn.out_proj",
    "diffusion_model.blocks.0.attn.qkv_proj",
    "diffusion_model.blocks.0.mlp.fc1",
]


def np_dtype(dt):
    return {"F32": np.float32, "F16": np.float16}[dt]


def load_tensor(f, h, key, base):
    v = h[key]
    s, e = v["data_offsets"]
    f.seek(base + s)
    raw = f.read(e - s)
    if v["dtype"] == "BF16":
        u = np.frombuffer(raw, dtype=np.uint16).astype(np.uint32) << 16
        arr = u.view(np.float32)
    else:
        arr = np.frombuffer(raw, dtype=np_dtype(v["dtype"]))
    return arr.reshape(v["shape"]).astype(np.float32)


def fro_ba(f, h, base, prefix):
    A = load_tensor(f, h, prefix + ".lora_A.weight", base)   # [r, in]
    B = load_tensor(f, h, prefix + ".lora_B.weight", base)   # [out, r]
    G = B.T @ B            # [r, r]
    H = A @ A.T            # [r, r]
    return float(np.sqrt(max(0.0, np.sum(G * H.T))))


def analyze(path):
    with open(path, "rb") as f:
        n = struct.unpack("<Q", f.read(8))[0]
        h = json.loads(f.read(n).decode())
        base = 8 + n
        print("=" * 78)
        print(os.path.basename(path))
        meta = h.get("__metadata__", {})
        out = []
        for pfx in LAYERS:
            ka = pfx + ".alpha"
            alpha = None
            if ka in h:
                alpha = load_tensor(f, h, ka, base).reshape(-1)[0]
            kb = pfx + ".lora_B.weight"
            if kb not in h:
                print("  缺权重:", pfx)
                continue
            A = load_tensor(f, h, pfx + ".lora_A.weight", base)
            rank = A.shape[0]
            if alpha is None:
                scale = 1.0
            else:
                scale = float(alpha) / rank
            fro = fro_ba(f, h, base, pfx)
            out.append((pfx.split(".")[-2] + "." + pfx.split(".")[-1],
                        rank, float(alpha) if alpha is not None else None,
                        scale, fro, scale * fro))
        for name, rank, alpha, scale, fro, eff in out:
            print("  %-10s rank=%-4d alpha=%-7s scale=%-9.5f ||BA||=%-10.4f eff=%-10.4f"
                  % (name, rank, alpha, scale, fro, eff))
        return out


res = {}
for name in sys.argv[1:]:
    res[name] = analyze(os.path.join(LORA_DIR, name))

# 以 4step 为基准归一
if len(res) >= 2:
    names = list(res)
    print("=" * 78)
    print("相对有效强度（以第一个文件为 1.0）")
    base_eff = None
    for n in names:
        effs = [x[5] for x in res[n]]
        m = float(np.mean(effs))
        if base_eff is None:
            base_eff = m
        print("  %-58s 均值 eff=%.4f  相对=%.4fx" % (n[:58], m, m / base_eff))
