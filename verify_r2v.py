#!/usr/bin/env python3
"""R2V 工作流结构验证：上传参考图 -> 注入 ref_images -> 提交低配任务，检查是否被 ComfyUI 接受。

重点验证 COMFY_AUTOGROW_V3 输入在 API 格式里的 dict 写法（ref_image_0/1/...）。
只提交、不等待生成；返回 QUEUE_OK 即说明节点结构与自动增长槽写法合法。

用法: python verify_r2v.py
"""
import json
import os
import sys
import urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import comfyui_client as cc

URL = "http://127.0.0.1:8188"
WF = os.path.join(HERE, "templates", "h3_r2v_api.json")
REFS = [os.path.join(HERE, "refs", "fangyuan_youth_front.png"),
        os.path.join(HERE, "refs", "fangyuan_youth_face.png")]
PROMPT = ("A blood-soaked warrior in a tattered green robe stands on a mountain "
          "peak at sunset, cinematic wide shot, slow pan, dramatic lighting.")
# 低配：只为快速验证结构合法，不追求画质
LOWSPEC = {"width": 448, "height": 256, "length": 25}
STEPS = 4


def main():
    if not cc.is_up(URL):
        print("COMFYUI_OFFLINE: 请先启动 ComfyUI (8188)")
        return 2
    for p in REFS:
        if not os.path.exists(p):
            print("MISSING_REF:", p)
            return 2

    api = cc.load_api_workflow(WF)
    print("nodes:", sorted(api.keys(), key=int))
    cc.inject_prompt(api, PROMPT, "5", "prompt")

    ups = [cc.upload_image(URL, p) for p in REFS]
    print("uploaded:", [u.get("filename") for u in ups])
    ref = cc.inject_ref_images(api, ups, "5", "ref_images")
    print("ref_images dict:", json.dumps(ref))

    api["5"]["inputs"].update(LOWSPEC)
    api["8"]["inputs"]["steps"] = STEPS
    print(f"validate spec: {LOWSPEC} steps={STEPS} ref_image_size={api['5']['inputs']['ref_image_size']}")

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
