# -*- coding: utf-8 -*-
"""枚举 ComfyUI 各 scheduler 在 4/8/20 步 + H3 shift 下的 sigma 序列与收敛指标。

直接用 ComfyUI 自己的调度函数算（内嵌 python 运行），不是手工复刻。

用法:
    <ComfyUI>/python_embeded/python.exe tools/_sched_matrix.py
"""
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, r"C:\ComfyUI\v0.30.0\ComfyUI_windows_portable_nvidia"
                   r"\ComfyUI_windows_portable\ComfyUI")

import comfy.model_sampling as cms          # noqa: E402
import comfy.samplers as cs                 # noqa: E402
from comfy.samplers import KSampler, calculate_sigmas   # noqa: E402


def sched_funcs():
    """KSampler.SCHEDULERS 是名字列表；统一用官方 calculate_sigmas 计算。"""
    return [(name, None) for name in KSampler.SCHEDULERS]


def make_ms(shift_video=6.0, shift_audio=3.0):
    m = cms.ModelSamplingAV()
    m.set_parameters(shift=shift_video, audio_shift=shift_audio)
    return m


def metrics(sig):
    s = [float(x) for x in sig]
    body = s[:-1]                       # 去掉末尾的 0
    last_span = body[-1] - s[-1]        # 最后一步：sig[-2] -> 0
    low = sum(1 for x in body if x < 0.3)
    spans = [body[i] - body[i + 1] for i in range(len(body) - 1)] + [body[-1]]
    return last_span, low, max(spans)


def run(shift_video):
    for steps in (4, 8, 20):
        print("=" * 104)
        print("steps = %-3d   shift_video = %.1f" % (steps, shift_video))
        print("%-18s %-52s %10s %8s %10s" % ("scheduler", "sigma 序列(含末尾0)", "末步跨度", "低噪档", "最大单步"))
        for name, fn in sched_funcs():
            try:
                sig = calculate_sigmas(make_ms(shift_video), name, steps)
            except Exception as e:                       # noqa: BLE001
                print("%-18s ERROR: %s" % (name, e))
                continue
            ls, low, mx = metrics(sig)
            seq = " ".join("%.3f" % float(x) for x in sig)
            flag = ""
            if ls > 0.55:
                flag = "   <== 末步跨度过大(欠收敛)"
            elif low == 0:
                flag = "   <== 无低噪档"
            print("%-18s %-52s %10.3f %8d %10.3f%s"
                  % (name, seq[:52], ls, low, mx, flag))
        print()


if __name__ == "__main__":
    run(6.0)
    print("#" * 104)
    print("# 对照：shift_video = 12.0（544p 系列训练配置）")
    print("#" * 104)
    run(12.0)
