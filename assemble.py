"""视频合成：逐镜头烧字幕 + 拼接成片。优先用 imageio-ffmpeg 自带的 ffmpeg。"""
import os
import shutil
import subprocess


def get_ffmpeg(config_ffmpeg=None):
    if config_ffmpeg and os.path.exists(config_ffmpeg):
        return config_ffmpeg
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


def _esc(t):
    """ffmpeg drawtext 文本转义。"""
    return (t.replace("\\", "\\\\").replace("'", "\\'")
             .replace(":", "\\:").replace("%", "\\%").replace("\n", " "))


def _esc_path(p):
    """ffmpeg drawtext 的 fontfile 路径转义。

    Windows 路径形如 C:/Windows/Fonts/msyh.ttc，其中的冒号在 filtergraph 语法里
    会被当作「选项分隔符」，导致 `No option name near '/Windows/...'` 报错。
    必须把盘符冒号转义成 \\: 再交给 drawtext。
    """
    return p.replace("\\", "/").replace(":", "\\:")


_FONT_CANDIDATES = [
    "C:/Windows/Fonts/msyh.ttc",     # 微软雅黑
    "C:/Windows/Fonts/msyhbd.ttc",
    "C:/Windows/Fonts/simhei.ttf",   # 黑体
    "C:/Windows/Fonts/simsun.ttc",   # 宋体
    "C:/Windows/Fonts/Deng.ttf",     # 等线
]


def resolve_font(font=None):
    """返回实际可用的中文字体路径；都找不到返回 None（调用方降级为不烧字）。"""
    for c in ([font] if font else []) + _FONT_CANDIDATES:
        if c and os.path.exists(c):
            return c
    return None


def extract_last_frame(video, out_png, ffmpeg=None):
    """抽取视频最后一帧存为 PNG —— 用于首尾帧链式接力（下一镜的首帧）。"""
    ffmpeg = ffmpeg or get_ffmpeg()
    cmd = [ffmpeg, "-y", "-sseof", "-0.1", "-i", video,
           "-frames:v", "1", "-update", "1", "-q:v", "2", out_png]
    subprocess.run(cmd, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return out_png


def concat_clips(clips, out_path, font=None, fps=24, audio_filter=None):
    """
    clips: list of (video_path, line, duration)
    1) 每个片段统一重编码为 libx264/aac（有台词的烧入字幕）
    2) concat demuxer 拼接
    字幕烧字失败会自动降级为「该片段不烧字」，不让整片拼接挂掉。

    audio_filter: ffmpeg 音频滤镜串，None/空 = 不做。
        例：`highpass=f=80,afftdn=nr=10:nf=-35,alimiter=limit=0.7:level=false`

        ⚠️ 为什么必须做（2026-10-06 实测）：H3 是原生音视频同步模型，它生成的音轨
        **一律把响度推到接近满刻度** —— 实测新片与归档旧片段全都 Peak −0.7~−3 dB、
        RMS −17~−22 dB（纯环境音镜应在 −30~−40），且底噪大（频谱 0–15kHz 全频段发亮）。
        听感就是「很吵、有噪音」。改 prompt 只能微调，**唯一能统一治理的位置就是这里**
        （逐片段重编码时加滤镜；concat 是 `-c copy` 不会再处理）。

        ⛔ **不要用 `loudnorm`**：它是「把整段拉到目标响度」，会把**安静镜头强行推响**
        （实测把镜1 从 Peak −6.19 推到 −1.40，反而更吵）。要用「峰值限制 + 降噪」型。
        ⚠️ `alimiter` 的 `limit` 是**线性值不是 dB**（0.7 ≈ −3dB），且必须带
        `level=false`，否则它的自动电平会抵消限制。
    """
    ffmpeg = get_ffmpeg()
    tmp_dir = os.path.join(os.path.dirname(os.path.abspath(out_path)), "_tmp_clips")
    os.makedirs(tmp_dir, exist_ok=True)
    use_font = resolve_font(font)
    if use_font:
        print(f"[assemble] 字幕字体：{use_font}")
    else:
        print("[assemble] ⚠ 未找到可用中文字体，跳过字幕烧入（仍会拼接成片）")
    font_arg = _esc_path(use_font) if use_font else None
    af_args = ["-af", audio_filter] if audio_filter else []
    if af_args:
        print(f"[assemble] 音频滤镜：{audio_filter}")
    burn_failed = 0
    processed = []
    for i, (vpath, line, _dur) in enumerate(clips):
        dst = os.path.join(tmp_dir, f"clip_{i:02d}.mp4")
        plain = [ffmpeg, "-y", "-i", vpath,
                 "-c:v", "libx264", "-preset", "fast", "-crf", "18",
                 *af_args,
                 "-c:a", "aac", "-pix_fmt", "yuv420p", dst]
        if line and font_arg:
            vf = (f"drawtext=fontfile='{font_arg}':text='{_esc(line)}':"
                  f"fontcolor=white:fontsize=48:borderw=3:bordercolor=black:"
                  f"x=(w-text_w)/2:y=h-th-40")
            cmd = [ffmpeg, "-y", "-i", vpath, "-vf", vf,
                   "-c:v", "libx264", "-preset", "fast", "-crf", "18",
                   *af_args,
                   "-c:a", "aac", "-pix_fmt", "yuv420p", dst]
            try:
                subprocess.run(cmd, check=True,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except subprocess.CalledProcessError:
                # 字幕烧入失败（字体/转义/滤镜问题）→ 降级：不烧字也要保证成片完整
                burn_failed += 1
                print(f"[assemble] ⚠ 片段 {i:02d} 烧字幕失败，降级为不烧字")
                subprocess.run(plain, check=True,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            subprocess.run(plain, check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        processed.append(dst)

    if burn_failed:
        print(f"[assemble] ⚠ 共 {burn_failed} 个片段未烧字幕（其余正常）")

    listf = os.path.join(tmp_dir, "list.txt")
    with open(listf, "w", encoding="utf-8") as f:
        for p in processed:
            f.write(f"file '{os.path.abspath(p)}'\n")
    cmd = [ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", listf,
           "-c", "copy", out_path]
    subprocess.run(cmd, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # 拼接成功 → 临时重编码目录已无用，就地清掉（失败时保留，便于排查）
    # 不清的话会在成片目录旁边留一堆 _tmp_clips/，污染 06_release。
    shutil.rmtree(tmp_dir, ignore_errors=True)
    return out_path
