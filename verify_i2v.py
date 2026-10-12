#!/usr/bin/env python3
"""FL2VA 首尾帧工作流结构验证：造两张测试帧 -> 上传 -> 注入 first/last -> 低配提交，检查 node_errors。

用法: python verify_i2v.py
"""
import json
import os
import subprocess
import sys
import urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import comfyui_client as cc
import tts_client as tc

URL = "http://127.0.0.1:8188"
WF = os.path.join(HERE, "templates", "h3_i2v_api.json")
TMP = os.path.join(HERE, "output", "_verify")
PROMPT = ("Cinematic slow camera push-in, ancient Chinese fantasy, a wounded warrior "
          "in a tattered green robe standing on a mountain peak at sunset.")
LENGTH = 25
STEPS = 4


def make_png(path, color):
    ff = tc.get_ffmpeg()
    subprocess.run([ff, "-y", "-f", "lavfi", "-i", f"color=c={color}:s=864x480",
                    "-frames:v", "1", path],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return path


def main():
    if not cc.is_up(URL):
        print("COMFYUI_OFFLINE: 请先启动 ComfyUI (8188)")
        return 2
    os.makedirs(TMP, exist_ok=True)
    first = make_png(os.path.join(TMP, "vf_first.png"), "0x203040")
    last = make_png(os.path.join(TMP, "vf_last.png"), "0x804020")
    print("test frames:", os.path.basename(first), os.path.basename(last))

    api = cc.load_api_workflow(WF)
    print("nodes:", sorted(api.keys(), key=int))
    cc.inject_prompt(api, PROMPT, "6", "prompt")

    up1 = cc.upload_image(URL, first)
    up2 = cc.upload_image(URL, last)
    api["20"]["inputs"]["image"] = up1["filename"]
    api["21"]["inputs"]["image"] = up2["filename"]
    print("first_frame:", up1["filename"], "last_frame:", up2["filename"])

    api["6"]["inputs"]["length"] = LENGTH
    api["7"]["inputs"]["steps"] = STEPS
    print(f"validate spec: {api['6']['inputs']['width']}x{api['6']['inputs']['height']} "
          f"length={LENGTH} steps={STEPS}")

    try:
        r = cc.queue_prompt(URL, api)
        print(f"QUEUE_OK prompt_id={r.get('prompt_id')} node_errors={r.get('node_errors')}")
        return 0
    except urllib.error.HTTPError as e:
        print("QUEUE_FAILED HTTP", e.code)
        print(e.read().decode("utf-8", "ignore")[:4000])
        return 1
    except Exception as e:
        print("QUEUE_ERROR", type(e).__name__, e)
        return 1


if __name__ == "__main__":
    sys.exit(main())
