"""ComfyUI 客户端：启动检测、UI->API 转换、提示词/图片注入、队列、轮询、下载。"""
import json
import os
import time
import urllib.request
import urllib.parse
import subprocess

CONN_TYPES = {"IMAGE", "VIDEO", "MODEL", "CLIP", "VAE", "LATENT",
              "CONDITIONING", "MASK", "AUDIO"}


# ---------- 基础 HTTP ----------
def _get_json(url, timeout=10):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read())


def _post_json(url, data, timeout=180):
    req = urllib.request.Request(
        url, data=json.dumps(data).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def is_up(url, timeout=4):
    try:
        urllib.request.urlopen(url + "/system_stats", timeout=timeout)
        return True
    except Exception:
        return False


def ensure_running(url, launch_bat=None, auto_start=True, max_wait=240):
    """检测 ComfyUI 是否在跑；不在则尝试用便携版启动器拉起，直到可访问。"""
    if is_up(url):
        return True
    if auto_start and launch_bat and os.path.exists(launch_bat):
        cwd = os.path.dirname(launch_bat)
        subprocess.Popen([launch_bat], shell=True, cwd=cwd,
                         creationflags=0x00000008)
        t0 = time.time()
        while time.time() - t0 < max_wait:
            if is_up(url):
                return True
            time.sleep(5)
    return False


# ---------- 工作流加载 / 转换 ----------
def convert_ui_to_api(ui):
    """把 ComfyUI UI 工作流（含 nodes/links）尽量转成 /prompt 能用的 API 格式。
    说明：H3 官方模板使用了 subgraph 子图节点，子图内部 widget 无法被通用转换覆盖，
    因此 H3 模板请改用 ComfyUI 导出的 API 格式文件（见 SKILL.md）。本函数作为通用兜底。"""
    link_map = {l[0]: (l[1], l[2]) for l in ui.get("links", [])}
    api = {}
    for n in ui.get("nodes", []):
        nid = str(n["id"])
        inputs = {}
        wv = list(n.get("widgets_values", []) or [])
        wv_idx = 0
        for inp in n.get("inputs", []):
            name = inp.get("name")
            lk = inp.get("link")
            if lk is not None:
                frm = link_map.get(lk)
                if frm:
                    inputs[name] = [str(frm[0]), frm[1]]
            else:
                if inp.get("type") in CONN_TYPES:
                    continue  # 连接型输入，无 widget
                if wv_idx < len(wv):
                    inputs[name] = wv[wv_idx]
                    wv_idx += 1
        api[nid] = {"class_type": n["type"], "inputs": inputs}
    return api


def load_api_workflow(path):
    """自动判断是 UI 格式还是 API 格式。以 _ 开头的键视为注释并剔除（ComfyUI 只收纯数字节点 id）。"""
    d = json.load(open(path, encoding="utf-8"))
    if "nodes" in d and isinstance(d.get("nodes"), list) \
            and any("widgets_values" in n for n in d["nodes"]):
        d = convert_ui_to_api(d)
    return {k: v for k, v in d.items() if not str(k).startswith("_")}


# ---------- 注入 ----------
def _parse_pair(p):
    if isinstance(p, (list, tuple)) and len(p) == 2:
        return (str(p[0]), str(p[1]))
    return (None, None)


def inject_prompt(api, prompt, node_id=None, input_name=None):
    nid, name = _parse_pair(node_id) if node_id else (None, None)
    if nid and name and nid in api and name in api[nid].get("inputs", {}):
        api[nid]["inputs"][name] = prompt
        return
    # 自动探测：第一个长度 > 80 的字符串输入
    for _nid, node in api.items():
        for k, v in node.get("inputs", {}).items():
            if isinstance(v, str) and len(v) > 80:
                node["inputs"][k] = prompt
                return
    raise ValueError("未找到提示词注入点，请在 config.json 的 video.prompt_input 指定 [节点id, 输入名]")


def inject_image(api, upload_resp, node_id=None, input_name=None):
    img_ref = {
        "filename": upload_resp["filename"],
        "subfolder": upload_resp.get("subfolder", ""),
        "type": upload_resp.get("type", "input"),
    }
    nid, name = _parse_pair(node_id) if node_id else (None, None)
    if nid and name and nid in api and name in api[nid].get("inputs", {}):
        api[nid]["inputs"][name] = img_ref
        return
    for _nid, node in api.items():
        for k, v in node.get("inputs", {}).items():
            if v is None and str(k).lower() in ("image", "first_frame", "frame", "init_image"):
                node["inputs"][k] = img_ref
                return
    raise ValueError("未找到图片注入点，请在 config.json 的 video.image_input 指定 [节点id, 输入名]")


def inject_ref_images(api, upload_resps, node_id="5", input_name="ref_images"):
    """把多张参考图注入 H3 R2V 节点的自动增长输入（COMFY_AUTOGROW_V3）。

    该输入在 API 格式里的值是一个 dict：{"ref_image_0": [节点id, 槽位], ...}
    （键名规则 = 模板 prefix + 序号，见 comfy_api/latest/_io.py Autogrow.TemplatePrefix）。
    会复用工作流里已有的 LoadImage 节点；图数量超出时自动新增 LoadImage 节点。
    """
    nid, name = _parse_pair([node_id, input_name])
    if nid not in api:
        raise ValueError(f"找不到 R2V 节点 {nid}")
    load_ids = sorted([k for k, n in api.items()
                       if n.get("class_type") == "LoadImage"], key=lambda x: int(x))
    next_new = max([int(k) for k in api if str(k).isdigit()] or [0]) + 1
    ref = {}
    for i, up in enumerate(upload_resps):
        if i < len(load_ids):
            lnid = load_ids[i]
            api[lnid]["inputs"]["image"] = up["filename"]
        else:
            lnid = str(next_new)
            next_new += 1
            api[lnid] = {"class_type": "LoadImage",
                         "inputs": {"image": up["filename"]}}
        ref[f"ref_image_{i}"] = [lnid, 0]
    api[nid]["inputs"][name] = ref
    return ref


# ---------- 时长（帧数）注入 ----------
# H3 的 length 是「24fps 下的帧数」，且必须落在模型的 17k+5 网格上
# （节点 tooltip：124 = ~5s，训练范围 ~124-362）。模板里写死 124，
# 导致所有镜头都被截成 5.17s —— 分镜的 duration 必须在提交前改写这个值。
H3_FRAME_GRID = [5 + 17 * i for i in range(22)]
H3_FRAME_LO, H3_FRAME_HI = 124, 362


def snap_length(frames, lo=H3_FRAME_LO, hi=H3_FRAME_HI):
    """把目标帧数吸附到 17k+5 网格（向上取，不超过训练范围）。"""
    if not frames:
        return None
    f = int(round(float(frames)))
    f = max(lo, min(hi, f))
    for g in H3_FRAME_GRID:
        if g < lo:
            continue
        if g > hi:
            break
        if g >= f:
            return g
    return hi


def apply_length(api, frames):
    """改写 H3 视频节点的 length（I2V / R2V 两支）。返回实际生效的帧数。"""
    f = snap_length(frames)
    if not f:
        return None
    for _nid, node in api.items():
        if node.get("class_type") in ("MiniMaxH3ImageToVideo",
                                      "MiniMaxH3ReferenceToVideo") \
                and "length" in node.get("inputs", {}):
            node["inputs"]["length"] = f
    return f


# ---------- 队列 / 轮询 / 下载 ----------
def upload_image(url, image_path, overwrite=True):
    """上传一张图到 ComfyUI 的 input 目录，返回 {"name","subfolder","type"(,"filename")}。

    overwrite=True（2026-10-06 起默认）：同名文件**直接覆盖**，input 目录永远只留最新一份。
    之前的默认行为（不传该字段）是「同名内容相同则复用、内容不同则另存 `xxx (1).png` 且保留原文件」，
    换过参考图（如 2D→3D）后会新旧并存，重跑 N 次就堆出 `(1)(2)(3)…`，单张 1~2.8MB，很快吃满磁盘，
    且旧图残留容易被手动误选。传 overwrite 可根治。
    ⚠️ 老版 ComfyUI 若不认该字段会静默忽略，行为退回「改名」，无副作用。
    """
    boundary = "----n2vboundary"
    with open(image_path, "rb") as f:
        raw = f.read()
    parts = []
    if overwrite:
        # overwrite 必须是独立的 form field（值为字符串 "true"），且不能塞进 image 那一段
        parts.append((f'--{boundary}\r\nContent-Disposition: form-data; '
                      f'name="overwrite"\r\n\r\ntrue\r\n').encode("utf-8"))
    parts.append((f'--{boundary}\r\nContent-Disposition: form-data; name="image"; '
                  f'filename="{os.path.basename(image_path)}"\r\n'
                  f'Content-Type: application/octet-stream\r\n\r\n').encode("utf-8"))
    body = b"".join(parts) + raw + f"\r\n--{boundary}--\r\n".encode("utf-8")
    req = urllib.request.Request(
        url + "/upload/image", data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(req, timeout=60) as r:
        resp = json.loads(r.read())
    # ComfyUI 返回 {"name","subfolder","type"}；统一补 filename 别名供内部使用
    if "filename" not in resp and "name" in resp:
        resp["filename"] = resp["name"]
    return resp


def queue_prompt(url, api_prompt, client_id="n2v"):
    return _post_json(url + "/prompt",
                      {"prompt": api_prompt, "client_id": client_id})


def wait_history(url, prompt_id, timeout=3600, interval=5):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            h = _get_json(url + f"/history/{prompt_id}", timeout=10)
        except Exception:
            h = {}
        if prompt_id in h:
            return h[prompt_id]
        time.sleep(interval)
    raise TimeoutError("ComfyUI 生成超时，请检查显存/模型是否就绪")


def fetch_outputs(url, history, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    files = []
    outputs = history.get("outputs", {})
    for _node_id, out in outputs.items():
        for v in out.get("videos", []):
            files.append(_download(url, v, out_dir))
        for v in out.get("images", []):
            files.append(_download(url, v, out_dir))
    if not files:
        raise RuntimeError("ComfyUI 未返回任何视频/图片输出，请检查工作流 SaveVideo/SaveImage 节点")
    return files


def _download(url, v, out_dir):
    fn = v["filename"]
    sub = urllib.parse.quote(v.get("subfolder", ""))
    typ = v.get("type", "output")
    urlp = f"{url}/view?filename={urllib.parse.quote(fn)}&subfolder={sub}&type={typ}"
    with urllib.request.urlopen(urlp, timeout=60) as r:
        data = r.read()
    dst = os.path.join(out_dir, fn)
    with open(dst, "wb") as f:
        f.write(data)
    return dst


def generate(url, workflow_path, prompt, image_path=None,
             prompt_pair=None, image_pair=None,
             ref_image_paths=None, ref_pair=None,
             first_frame_path=None, last_frame_path=None,
             first_pair=None, last_pair=None, out_dir=None,
             timeout=3600, meta=None, length=None):
    """一条龙：加载工作流 -> 注入 -> 队列 -> 轮询 -> 下载，返回输出文件路径列表。

    ref_image_paths: R2V 模式下的参考图路径列表（多张），注入自动增长输入 ref_images。
    first_frame_path / last_frame_path: FL2VA 模式下的首帧/尾帧图片，直接写入 LoadImage 的 image。
    length: 本镜帧数（24fps）。给了就改写模板里的 length —— H3 模板默认写死 124（≈5.17s），
            不改的话无论分镜标多长，成片每镜都是 5.17s。会自动吸附到 17k+5 网格。
    timeout: 单镜等待上限（秒）。超时抛 TimeoutError，由调用方决定重试或中止。
    meta: 传入一个 dict 时，回填本次运行的溯源信息（prompt_id / workflow / 原始输出），
          供 runner 写留痕。不改动返回值。
    """
    api = load_api_workflow(workflow_path)
    real_len = apply_length(api, length)
    if meta is not None and real_len:
        meta["length_frames"] = real_len
    inject_prompt(api, prompt, *(prompt_pair or (None, None)))
    if image_path:
        up = upload_image(url, image_path)
        inject_image(api, up, *(image_pair or (None, None)))
    if ref_image_paths:
        ups = [upload_image(url, p) for p in ref_image_paths]
        inject_ref_images(api, ups, *(ref_pair or ("5", "ref_images")))
    if first_frame_path:
        _inject_frame(api, upload_image(url, first_frame_path), first_pair or ("20", "image"))
    if last_frame_path:
        _inject_frame(api, upload_image(url, last_frame_path), last_pair or ("21", "image"))
    if meta is not None:
        meta["workflow"] = os.path.basename(workflow_path)
    pid = queue_prompt(url, api)["prompt_id"]
    if meta is not None:
        meta["prompt_id"] = pid
    hist = wait_history(url, pid, timeout=timeout)
    files = fetch_outputs(url, hist, out_dir or os.path.join("output", "clips"))
    if meta is not None:
        meta["raw_files"] = [os.path.basename(p) for p in files]
    return files


def _inject_frame(api, upload_resp, pair):
    """把上传结果写进指定 LoadImage 节点的 image 输入（字符串文件名）。"""
    nid, name = _parse_pair(pair)
    if nid not in api:
        raise ValueError(f"找不到节点 {nid}（首/尾帧注入点）")
    api[nid]["inputs"][name] = upload_resp["filename"]
