#!/usr/bin/env python3
"""FL2VA 首尾帧链式端到端验证：低配快速跑 2 镜，验证结构与「上一镜尾帧→下一镜首帧」接力。

低配规格: 448x256 / length=25 / steps=4（只验链路与耗时，不追求画质）
产出: output/clips/shot_001.mp4, shot_002.mp4

用法: python verify_fl2va_chain.py
"""
import json
import os
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import comfyui_client as cc
import assemble as ac

URL = "http://127.0.0.1:8188"
WF = os.path.join(HERE, "templates", "h3_i2v_api.json")
KF = os.path.join(HERE, "output", "keyframes")
CLIPS = os.path.join(HERE, "output", "clips")
RAW = os.path.join(HERE, "output", "_raw")
LOW = {"width": 448, "height": 256, "length": 25}
STEPS = 4
T0 = time.time()


def log(m):
    print(f"[{time.time() - T0:6.1f}s] {m}", flush=True)


def run_shot(n, first_img, last_img, prompt):
    out = os.path.join(CLIPS, f"shot_{n:03d}.mp4")
    if os.path.exists(out) and os.path.getsize(out) > 0:
        log(f"shot {n}: 已存在，跳过")
        return out
    api = cc.load_api_workflow(WF)
    cc.inject_prompt(api, prompt, "6", "prompt")
    uf = cc.upload_image(URL, first_img)
    ul = cc.upload_image(URL, last_img)
    api["20"]["inputs"]["image"] = uf["filename"]
    api["21"]["inputs"]["image"] = ul["filename"]
    api["6"]["inputs"].update(LOW)
    api["7"]["inputs"]["steps"] = STEPS
    log(f"shot {n}: first={os.path.basename(first_img)} last={os.path.basename(last_img)}")
    try:
        r = cc.queue_prompt(URL, api)
    except Exception as e:
        body = getattr(e, "read", lambda: b"")()
        log(f"shot {n}: QUEUE_FAILED {type(e).__name__} {body[:1500]!r}")
        return None
    log(f"shot {n}: queued {r.get('prompt_id')} node_errors={r.get('node_errors')}")
    hist = cc.wait_history(URL, r["prompt_id"])
    st = hist.get("status", {})
    log(f"shot {n}: status={st.get('status_str')}")
    outs = cc.fetch_outputs(URL, hist, RAW)
    os.makedirs(CLIPS, exist_ok=True)
    shutil.copy(outs[0], out)
    log(f"shot {n}: done -> {out} ({os.path.getsize(out)} bytes)")
    return out


def main():
    cfg = json.load(open(os.path.join(HERE, "config.json"), encoding="utf-8"))
    if not cc.ensure_running(cfg["comfyui_url"], cfg.get("comfyui_launch_bat"),
                             True, max_wait=420):
        log("ComfyUI 启动失败"); return 1
    log("ComfyUI ready")
    os.makedirs(CLIPS, exist_ok=True)
    sh = json.load(open(os.path.join(HERE, "output", "storyboard_pilot.json"),
                        encoding="utf-8"))

    run_shot(1, os.path.join(KF, "shot_001_first.png"),
             os.path.join(KF, "shot_001_last.png"), sh[0]["video_prompt"])

    prev_last = os.path.join(KF, "shot_002_prev_last.png")
    c1 = os.path.join(CLIPS, "shot_001.mp4")
    if os.path.exists(c1):
        ac.extract_last_frame(c1, prev_last)
        log(f"已从 shot_001.mp4 抽取真实尾帧 -> {os.path.basename(prev_last)}")
    run_shot(2, prev_last, os.path.join(KF, "shot_002_last.png"), sh[1]["video_prompt"])

    log("ALL DONE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
