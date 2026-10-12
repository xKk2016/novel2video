# novel2video

把小说变成漫剧短视频的本地流水线 —— **剧本 → 分镜 → 定妆资产 → 关键帧 → 逐镜图生视频 → 拼接成片**。

底层模型是 **MiniMax H3**（原生同步立体声），跑在本机 **ComfyUI** 上，不依赖任何云服务。
本仓库收录的是**源资产、分镜、配置与脚本**；体量大的生成产物（片段、成片、关键帧）不入库，
它们靠 ComfyUI + 模型重新生成。

---

## 目录结构

```
novel2video/
├── novel_to_video.py        # 主入口：读分镜 → 逐镜生成 → 拼接
├── run_chain.bat            # Windows 一键跑（包装 novel_to_video.py）
├── comfyui_client.py        # ComfyUI HTTP API 客户端
├── runner_support.py        # 运行状态 / 断点续跑 / 文件锁
├── assemble.py              # 拼接 + 音频滤镜链
├── llm_client.py            # LLM 调用（剧本改写用）
├── tts_client.py            # TTS 调用
├── verify_*.py              # 三条链的连通性自检
├── rewrite_ch1_v*.py        # 剧本 → 分镜 的改写脚本（含全部提示词）
├── config.json              # 全局配置（模型路径、采样参数、音频滤镜）
├── requirements.txt
├── templates/               # ComfyUI 工作流模板（API 格式 JSON）
│   ├── h3_i2v_turbo4_api.json      # ← 生产：i2v，4 步
│   ├── h3_t2v_turbo4_api.json      # ← 生产：t2v，4 步
│   ├── h3_fl2va_turbo4_api.json    # ← 生产：fl2va，4 步
│   ├── h3_r2v_turbo4_api.json      # ← 生产：r2v，4 步
│   ├── h3_*_turbo8_api.json        # 8 步变体（备用）
│   ├── h3_*_api.json               # 非 turbo，20 步（基准档）
│   └── _archive_before_v11_20261009/   # 升级 LoRA v1.1 前的模板快照
├── tools/                   # 55 个工具脚本（体检 / 补丁 / 诊断 / 切换）
└── assets/
    ├── 01_script/           # ✅ 入库：分镜 JSON、剧本、审查报告、小说源文
    │   ├── storyboard/storyboard_ch1_v3.json   # ★ 主分镜（58 镜）
    │   ├── reports/                            # 分镜审查报告
    │   ├── source/                             # 原小说片段
    │   └── _archive/                           # 旧版分镜（v2 / pilot / anime）
    └── 02_design/           # ✅ 入库：定妆资产
        ├── characters/      #   角色四视图：face / front / side / back
        └── scenes/          #   场景锚图
```

### 不入库的目录（跑起来会自己生成）

| 目录 | 内容 | 生成方式 |
|---|---|---|
| `assets/03_keyframes/` | 逐镜关键帧 PNG | 分镜里的关键帧提示词 + `tools/build_keyframes.py` |
| `assets/04_clips/` | 逐镜视频片段 | `run_chain.bat` |
| `assets/05_audio/` | 配音 / 混音中间产物 | `assemble.py` |
| `assets/06_release/` | 成片 `final.mp4` 与实验导出 | `run_chain.bat` |
| `output/` | 运行日志、诊断拼图、中间数据 | 运行期 |

---

## 环境准备

### 1. ComfyUI

需要 **v0.31.0 或更高**（要 `ModelSamplingAV`，否则 4 步 turbo LoRA 的音频会崩）。
本项目验证于 **v0.39.2**。

### 2. 模型（放在 ComfyUI 的 models/ 下）

| 文件 | 目录 | 约 |
|---|---|---|
| `minimax_h3_fl2va_pruned_int8_convrot.safetensors` | `diffusion_models/` | 21 GB |
| `minimax_h3_ref2va_pruned_int8_convrot.safetensors` | `diffusion_models/` | 21 GB |
| `qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors` | `text_encoders/` | 15 GB |
| `minimax_h3_video_vae_fp16.safetensors` | `vae/` | 5 GB |
| `minimax_h3_audio_vae_fp32.safetensors` | `vae/` | 0.6 GB |

下载源：`hf-mirror.com` 的 `Comfy-Org/MiniMax-H3`（国内直连 huggingface.co 不通，用镜像）。

### 3. Turbo LoRA（4 步加速，放在 `models/loras/`）

| 文件 | 用于 | 来源 |
|---|---|---|
| `minimax_h3_fl2v_turbo_4step_v1.1_768p_comfyui_bf16.safetensors` | i2v / t2v / fl2va | `lightx2v/Minimax-h3-Turbo` |
| `minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors` | r2v | `Comfy-Org/MiniMax-H3` |

> ⚠️ **必须用 v1.1，不要用 v1.0。** v1.0 在复杂画面镜（多人中景）会出暗紫色块，俗称"黑雾"：
> 同一镜对比，v1.0 暗部占比 17.7%、亮度 100.4；v1.1 是 10.8% / 120.5（与 20 步基线的 120.3 持平）。
> 两个文件结构完全一致，换版本只需改模板里的 `lora_name` 一项。

> ⚠️ **fl2v 与 ref2v 两个 LoRA 不能混挂。** 两个底模的张量层名 100% 相同（932 个键全重合），
> 挂错**不会报错**，会静默按错误条件推理 —— 只能靠文件名前缀 `fl2v` / `ref2v` 分辨。

### 4. Python 环境

```bash
cd novel2video
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt
```

`requirements.txt` 只有两个包（`imageio-ffmpeg`、`python-docx`）——其余（cv2 / numpy / PIL）
脚本里都是**按需可选**的，缺了会降级而不是崩。

---

## 运行

**先启动 ComfyUI**（本项目不代启动任何常驻服务），然后：

```cmd
run_chain.bat 1 21                 :: 跑场1（第 1~21 镜）
run_chain.bat 5 10 --no-concat     :: 跑 5~10 镜，不拼接
run_chain.bat 20                   :: 从第 20 镜跑到结尾
run_chain.bat --plan-only          :: 只打印逐镜计划，不占 GPU
run_chain.bat                      :: 交互式：列出场次/镜号让你选范围
```

- **断点续跑**：已有合法 `assets/04_clips/shot_NNN.mp4` 的镜会**自动跳过**。
  强制重跑用 `--redo-from N`。
- **分镜版本切换**后状态表 hash 会失配，需要 `--fresh-state`（从零）或 `--accept-state`（沿用旧记录）。
- 跑完自动拼接成 `assets/06_release/final.mp4`；加 `--no-concat` 可跳过。

---

## 生产采样配置

四条链**全部 4 步**，采样器 `euler`、调度器 `simple`（换 `normal` 会崩成满屏网纹，
换 `res_multistep` 在 4 步下音频会崩）：

| 链 | 用在哪 | 底模 | LoRA | shift |
|---|---|---|---|---|
| i2v / t2v / fl2va | 有首帧关键帧 / 空镜 / 无角色 | `fl2va_pruned_int8` | `fl2v_turbo_4step_v1.1_768p` | 6 / 3 |
| r2v | 无关键帧但需同角色换机位 | `ref2va_pruned_int8` | `ref2v_turbo_4step_v0.1` | 12 / 3 |

> `shift` 必须逐 LoRA 对齐训练配置：**768p 系列一律 6/3，544p 系列一律 12/3**。

选型判据：
- **有首帧关键帧 → i2v**（构图锁死，最可控）
- **无关键帧、但要同一角色出镜（换机位 / 新场景）→ r2v**（参考图锁身份）
- **无角色的环境 / 空镜 → t2v**

切换档位：`./.venv/Scripts/python.exe tools/switch_workflow.py --turbo 4 | --turbo 8 | --off | --status`

---

## 硬性约束（踩过坑的）

- **帧数网格**：`length` 只能是 **`124 + 17k`**（5 ~ 362 帧），即 0.708 秒网格；`duration = round(length/24, 2)`
- **音频滤镜顺序不可换**：开头瞬态压制 → `highpass` → mid/side 压制 → `loudnorm`
- **剪片跳过判据只看片段在不在** ⇒ 改配置 / 改提示词后要重跑，必须先归档旧片段
  （`tools/restage_rerun.py --tag <名>`），否则新旧混用
- **加载过大模型（如 34 GB 非剪枝版）后必须重启 ComfyUI**。`POST /free` 只卸模型、不重置进程状态；
  污染状态下推理会产出碎片错位 / 黑雾等假象，而且**连稳定配置都会产出完全不同的结果**
- **提示词不要点名首帧里不存在的东西** —— 模型会把它实体化生成出来
- **生产底模是 `pruned_int8_convrot`**。非剪枝（34 GB）实测清晰度反而低 10%、耗时多 14 秒，
  且超过本机物理内存

---

## 工具速查

| 用途 | 命令 |
|---|---|
| 分镜体检（开拍前） | `tools/audit_storyboard.py --html` |
| 台词时长体检 | `tools/audit_duration.py --csv` |
| 改台词时长帧数 | `tools/patch_speech_length.py --apply` |
| 多版同镜抽帧对比 | `tools/_diag_frame_grid.py --item "标签\|路径" ...` |
| LoRA 有效强度探针 | `tools/_lora_strength_probe.py <lora 文件...>` |
| 调度器 sigma 枚举 | `tools/_sched_matrix.py`（用 ComfyUI 内嵌 python 跑） |
| 挂任意 LoRA | `tools/make_lora_template.py --src ... --out ... --lora ...` |
| 换底模 | `tools/switch_base_model.py --list` / `--src ... --unet ...` |
| 归档旧片段 | `tools/restage_rerun.py --tag <名>` |
| 切 turbo 档 | `tools/switch_workflow.py --turbo 4 / --off / --status` |

---

## 排查画质异常的顺序

1. **先验权重版本** —— 同系列有没有更新 checkpoint？换版本是纯权重替换、零风险。（最容易被忽略，本项目走了 6 条弯路才发现）
2. **再验可复现性** —— 同配置连跑两次 `md5sum` 比对。不一致 ⇒ 会话被污染，前面结论全部作废，先重启 ComfyUI。
3. **再验单变量** —— 一次只改一个参数，其余字节级不动。
4. **最后才动步数 / 调度器 / 底模** —— 这三样本项目实测全部无效：步数 4→6 无变化；`beta` 比 `simple` 更差；非剪枝底模更慢更糊。
5. **判画面必须全尺寸逐帧目视** —— 人物数量、暗块、镜头漂移这类语义问题，指标测不出来。

---

## 说明

- 本仓库**不包含**模型权重与生成产物。模型适用 MiniMax H3 社区许可，使用前请自行确认授权范围。
- `assets/01_script/source/` 下的文本为小说原文片段，仅供本项目内部对照使用。
