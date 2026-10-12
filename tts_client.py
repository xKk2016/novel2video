"""TTS 配音：edge-tts 中文台词合成 + 时长对齐 + 与视频音轨混音。

用法（被 novel_to_video.py 调用）：
  synth_line(text, voice, out_wav)         -> 生成单句 mp3/wav
  fit_audio_to_duration(src, dst, target)  -> 拉伸/裁剪到目标秒数
  mux_audio(video, voice_wav, out, ...)    -> 把配音混入视频（保留 H3 环境音，可选）
"""
import os
import asyncio
import subprocess


def get_ffmpeg(config_ffmpeg=None):
    if config_ffmpeg and os.path.exists(config_ffmpeg):
        return config_ffmpeg
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


def synth_line(text, voice, out_path, rate="+0%", volume="+0%"):
    """用 edge-tts 合成一句话到 out_path(.mp3)。

    注：edge-tts 7.2.8 的 Python Communicate API 在本机会抛 NoAudioReceived，
    故走 CLI（python -m edge_tts），实测稳定。
    """
    import sys
    py = sys.executable
    cmd = [py, "-m", "edge_tts",
           "--voice", voice,
           "--text", text,
           "--rate", rate,
           "--volume", volume,
           "--write-media", out_path]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if not os.path.exists(out_path) or os.path.getsize(out_path) == 0:
        raise RuntimeError(f"edge-tts 合成失败: {r.stderr[-500:]}")
    return out_path


def probe_duration(path, ffmpeg=None):
    """返回音频/视频时长（秒）。"""
    ffmpeg = ffmpeg or get_ffmpeg()
    ffprobe = ffmpeg.replace("ffmpeg", "ffprobe")
    if os.path.exists(ffprobe):
        cmd = [ffprobe, "-v", "error", "-show_entries", "format=duration",
               "-of", "default=nk=1:nw=1", path]
        out = subprocess.run(cmd, capture_output=True, text=True)
        try:
            return float(out.stdout.strip())
        except Exception:
            pass
    # 退化：用 ffmpeg -i 解析
    out = subprocess.run([ffmpeg, "-i", path], capture_output=True, text=True)
    import re
    m = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", out.stderr)
    if m:
        h, mm, s = int(m.group(1)), int(m.group(2)), float(m.group(3))
        return h * 3600 + mm * 60 + s
    return None


def fit_audio_to_duration(src, dst, target_sec, ffmpeg=None):
    """把 src 音频适配到 target_sec：
    - 比目标短：尾部补静音
    - 比目标长：用 atempo 加速（不超过 1.5x），仍超则裁剪
    """
    ffmpeg = ffmpeg or get_ffmpeg()
    dur = probe_duration(src, ffmpeg) or target_sec
    if dur <= target_sec:
        pad = target_sec - dur
        cmd = [ffmpeg, "-y", "-i", src,
               "-af", f"apad=pad_dur={pad:.3f}",
               "-t", f"{target_sec:.3f}", dst]
    else:
        ratio = dur / target_sec
        tempo = min(max(ratio, 1.0), 1.5)
        cmd = [ffmpeg, "-y", "-i", src,
               "-af", f"atempo={tempo:.4f}",
               "-t", f"{target_sec:.3f}", dst]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return dst


def has_audio_stream(path, ffmpeg=None):
    """检测文件是否含音频流。"""
    ffmpeg = ffmpeg or get_ffmpeg()
    out = subprocess.run([ffmpeg, "-i", path], capture_output=True, text=True)
    return "Audio:" in out.stderr


def mux_voice_into_video(video, voice_audio, out_path,
                         keep_ambient=True, voice_gain=1.0, ambient_gain=0.35,
                         ffmpeg=None):
    """把配音混入视频。
    - 若视频自带音轨（H3 环境音）：环境音降 ao_ambient_gain 后与配音混合
    - 若视频无音轨（纯视频）：直接以配音为音轨
    """
    ffmpeg = ffmpeg or get_ffmpeg()
    if keep_ambient and has_audio_stream(video, ffmpeg):
        filter_complex = (
            f"[0:a]volume={ambient_gain}[amb];"
            f"[1:a]volume={voice_gain}[voc];"
            f"[amb][voc]amix=inputs=2:duration=first:dropout_transition=0[aout]"
        )
        cmd = [ffmpeg, "-y", "-i", video, "-i", voice_audio,
               "-filter_complex", filter_complex,
               "-map", "0:v", "-map", "[aout]",
               "-c:v", "copy", "-c:a", "aac", "-shortest", out_path]
    else:
        # 视频无音轨：直接配音
        cmd = [ffmpeg, "-y", "-i", video, "-i", voice_audio,
               "-map", "0:v", "-map", "1:a",
               "-c:v", "copy", "-c:a", "aac", "-shortest", out_path]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return out_path
