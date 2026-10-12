# -*- coding: utf-8 -*-
"""MiniMax H3 噪声调度探针（纯 Python，不依赖 torch）。

起因：4 步 turbo 下 H3 的音频流几乎完全失相关（L/R 相关 0.023）。
社区建议把 `shift_audio` 从 3.0 提到 5.0，但**先从源码推出机制**再决定改不改。

源码依据（ComfyUI 0.30.0）：
  comfy/model_sampling.py
      ModelSamplingDiscreteFlow.set_parameters(shift) → sigmas[i] = time_snr_shift(shift, (i+1)/1000)
      time_snr_shift(alpha, t) = alpha*t / (1 + (alpha-1)*t)
      timestep(sigma) = sigma * 1000 ;  sigma(timestep) = time_snr_shift(shift, timestep/1000)
  comfy/samplers.py
      simple_scheduler: ss = len(sigmas)/steps; 取 sigmas[-(1+int(x*ss))]  ← 从高档往低档跳
      normal_scheduler: timesteps = linspace(timestep(sigma_max), timestep(sigma_min), steps)
  comfy_extras/nodes_minimax_h3.py (MiniMaxH3SigmaShift)
      shift_video 进采样器；shift_audio 交给 DiT
  comfy/ldm/minimax/model.py
      sigma_v = timestep/1000 ; t_v = 1 - sigma_v
      t_a = 1 - time_shift_sigma(sigma_v, shift_v, shift_a)
      time_shift_sigma(sigma, s, t) = t*base/(1+(t-1)*base),  base = sigma/(s + sigma*(1-s))

⚠️ 约定：H3 内部 t = 1 - sigma ⇒ **t 越大越干净、t=0 是纯噪声**。

用法：
    ./.venv/Scripts/python.exe tools/probe_shift_schedule.py
"""
import sys

sys.stdout.reconfigure(encoding="utf-8")

TS = 1000          # ModelSamplingDiscreteFlow 的 timesteps
MUL = 1000.0


def snr_shift(alpha, t):
    if alpha == 1.0:
        return t
    return alpha * t / (1.0 + (alpha - 1.0) * t)


def make_sigmas(shift):
    return [snr_shift(shift, (i + 1) / TS) for i in range(TS)]


def sigma_of(shift, timestep):
    return snr_shift(shift, timestep / MUL)


def sched_simple(sigmas, steps):
    ss = len(sigmas) / steps
    return [sigmas[-(1 + int(x * ss))] for x in range(steps)] + [0.0]


def sched_normal(sigmas, shift, steps):
    start = sigmas[-1] * MUL          # timestep(sigma_max)
    end = sigmas[0] * MUL             # timestep(sigma_min)
    ts = [start + (end - start) * i / (steps - 1) for i in range(steps)]
    return [sigma_of(shift, t) for t in ts] + [0.0]


def time_shift_sigma(sigma, frm, to):
    base = sigma / (frm + sigma * (1.0 - frm))
    return to * base / (1.0 + (to - 1.0) * base)


def audio_from_video(sig_v_list, shift_v, shift_a):
    """DiT 里音频轨的时间由视频轨的 sigma 换算而来。"""
    out = []
    for s in sig_v_list:
        if s <= 0:
            out.append(0.0)
            continue
        out.append(1.0 - time_shift_sigma(s, shift_v, shift_a))
    return out


def report(shift_v=12.0, shift_a=3.0):
    sig = make_sigmas(shift_v)
    print("=" * 94)
    print("ModelSamplingDiscreteFlow  shift_video=%.1f  shift_audio=%.1f" % (shift_v, shift_a))
    print("  sigma_min = %.4f   sigma_max = %.4f" % (sig[0], sig[-1]))
    print("=" * 94)

    for steps in (4, 20):
        for name, fn in (("simple", lambda: sched_simple(sig, steps)),
                         ("normal", lambda: sched_normal(sig, shift_v, steps))):
            sv = fn()
            # 采样器实际使用的（去掉末尾补的 0）
            used = [x for x in sv[:-1]]
            ta = audio_from_video(used, shift_v, shift_a)
            print()
            print("【%d 步 · %s】" % (steps, name))
            print("  视频 sigma 序列: " + " ".join("%.3f" % x for x in used) + "  → 0")
            print("  末档 sigma=%.3f  ⇒ 最后一步要从 %.3f 直接跳到 0（降幅 %.3f）"
                  % (used[-1], used[-1], used[-1]))
            print("  音频 t 序列    : " + " ".join("%.3f" % x for x in ta) + "  → 1.000")
            print("  音频末档 t=%.3f（t 越大越干净）⇒ 音频最后一步跨度 %.3f"
                  % (ta[-1], 1.0 - ta[-1]))
            lo = [x for x in used if x < 0.3]
            print("  低噪区(sigma<0.3)档数: %d" % len(lo))
        print("-" * 94)


def main():
    report(12.0, 3.0)
    print()
    print("=" * 94)
    print("【对照】只改 shift_audio：3.0 vs 5.0（4 步 simple）")
    print("=" * 94)
    sig = make_sigmas(12.0)
    used = sched_simple(sig, 4)[:-1]
    print("  视频 sigma: " + " ".join("%.3f" % x for x in used))
    for sa in (3.0, 5.0):
        ta = audio_from_video(used, 12.0, sa)
        print("  shift_audio=%.1f ⇒ 音频 t: %s → 1.000   末档 t=%.3f"
              % (sa, " ".join("%.3f" % x for x in ta), ta[-1]))
    print()
    print("  判读：t 越大越干净。shift_audio 调大反而让音频末档 t 更小")
    print("        ⇒ 按代码推导，**调大 shift_audio 不会改善低噪段细化**，")
    print("          社区那个「audio sigma shift 5」的建议无法从源码得到支持，需实测。")
    print()
    print("  ⭐ 更可疑的是调度器本身：4 步 simple 的 sigma 只覆盖 %.3f→%.3f，"
          % (used[0], used[-1]))
    print("     然后一步跳到 0。低噪区档数 = %d。" % len([x for x in used if x < 0.3]))
    print("     ⇒ 真正的病根可能是「4 步 + simple」档位太糙，而不是 shift_audio。")


if __name__ == "__main__":
    main()
