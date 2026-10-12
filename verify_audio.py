"""快速验证 H3 音频分支：启动 ComfyUI -> 提交超小任务 -> 检查 mp4 是否含音轨。"""
import json, os, subprocess, time, urllib.request, uuid, sys, glob

COMFY_DIR = r"C:\ComfyUI\v0.30.0\ComfyUI_windows_portable_nvidia\ComfyUI_windows_portable"
OUT_DIR = os.path.join(COMFY_DIR, "ComfyUI", "output", "novel2video")
URL = "http://127.0.0.1:8188"
HERE = os.path.dirname(os.path.abspath(__file__))


def up():
    try:
        urllib.request.urlopen(URL + "/system_stats", timeout=4)
        return True
    except Exception:
        return False


def ffmpeg():
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


if not up():
    print("[1] ComfyUI 未运行，后台拉起...", flush=True)
    DETACHED = 0x00000008
    NEWGRP = 0x00000200
    subprocess.Popen(["cmd", "/c", os.path.join(COMFY_DIR, "run_nvidia_gpu.bat")],
                     cwd=COMFY_DIR, creationflags=DETACHED | NEWGRP,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, close_fds=True)
    for i in range(72):
        if up():
            print(f"[1] ComfyUI READY after ~{i*5}s", flush=True)
            break
        time.sleep(5)
    else:
        print("[1] ComfyUI 未就绪，退出"); sys.exit(1)
else:
    print("[1] ComfyUI 已在运行", flush=True)

# 极小测试工作流
wf = json.load(open(os.path.join(HERE, "templates", "h3_t2v_api.json"), encoding="utf-8"))
wf["6"]["inputs"]["prompt"] = "A lone swordsman stands on a cliff at dusk, wind, cinematic wide shot."
wf["6"]["inputs"]["width"] = 672
wf["6"]["inputs"]["height"] = 384
wf["6"]["inputs"]["length"] = 25
wf["7"]["inputs"]["steps"] = 4

before = set(glob.glob(os.path.join(OUT_DIR, "*.mp4")))

body = json.dumps({"prompt": wf, "client_id": str(uuid.uuid4())}).encode()
req = urllib.request.Request(URL + "/prompt", data=body, headers={"Content-Type": "application/json"})
try:
    resp = json.loads(urllib.request.urlopen(req, timeout=60).read())
except Exception as e:
    print("[2] 提交失败:", type(e).__name__, str(e)[:400]); sys.exit(1)

pid = resp.get("prompt_id")
print("[2] 提交 OK prompt_id=", pid, " node_errors=", resp.get("node_errors"), flush=True)

for i in range(80):
    try:
        with urllib.request.urlopen(f"{URL}/history/{pid}", timeout=10) as r:
            h = json.loads(r.read())
        if pid in h and h[pid].get("outputs"):
            print("[3] 任务完成，outputs=", json.dumps(h[pid]["outputs"], ensure_ascii=False)[:500], flush=True)
            break
    except Exception:
        pass
    time.sleep(15)
else:
    print("[3] 轮询超时"); sys.exit(1)

# 找新 mp4 并检查音轨
new = sorted(set(glob.glob(os.path.join(OUT_DIR, "*.mp4"))) - before,
             key=os.path.getmtime)
if not new:
    new = sorted(glob.glob(os.path.join(OUT_DIR, "*.mp4")), key=os.path.getmtime)
mp4 = new[-1]
print("[4] 产出文件:", mp4, os.path.getsize(mp4), "bytes", flush=True)

ff = ffmpeg()
p = subprocess.run([ff, "-i", mp4], capture_output=True, text=True, errors="ignore")
info = p.stderr
has_audio = "Audio:" in info
print("[5] === ffmpeg 流信息 ===")
for line in info.splitlines():
    if "Stream" in line or "Duration" in line:
        print("   ", line.strip())
print("[5] 含音轨:", has_audio)
print("RESULT:", "AUDIO_OK" if has_audio else "NO_AUDIO")
