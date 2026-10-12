import sys
sys.path.insert(0, r"C:/ComfyUI/v0.30.0/ComfyUI_windows_portable_nvidia/ComfyUI_windows_portable/ComfyUI")
import numpy as np
from comfy.model_sampling import ModelSamplingDiscreteFlow
from comfy.samplers import simple_scheduler, normal_scheduler, beta_scheduler

m = ModelSamplingDiscreteFlow()
m.set_parameters(shift=12.0)          # H3 的 sampling_settings
print("shift =", m.shift, " sigma_max =", round(float(m.sigma_max),4), " sigma_min =", round(float(m.sigma_min),4))
print("表长 =", len(m.sigmas), "  => sigma(t)=12t/(1+11t)")
print()
STEPS = 20
names = [("simple", simple_scheduler), ("normal", normal_scheduler), ("beta", beta_scheduler)]
data = {}
for name, fn in names:
    s = fn(m, STEPS)
    v = [float(x) for x in s]
    data[name] = v
    print(f"--- {name} ({len(v)} 档) ---")
    print("  sigma:", " ".join(f"{x:.3f}" for x in v))
    # 反推 t（sigma -> t）
    t = [(x/(12-11*x)) if x < 1 else 1.0 for x in v]
    print("  t    :", " ".join(f"{x:.3f}" for x in t))
    d = np.diff([x for x in v])
    print(f"  末段每步 sigma 降幅 (低噪区前5步): {[round(float(x),4) for x in d[-5:]]}")
    print()
# 低噪声段（sigma<0.3）步数分布
print("低噪区(sigma<0.3)步数：", {n: sum(1 for x in v if x < 0.3) for n, v in data.items()})
print("高噪区(sigma>0.85)步数：", {n: sum(1 for x in v if x > 0.85) for n, v in data.items()})
