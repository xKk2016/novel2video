"""云端 LLM：小说章节 -> 短剧剧本 -> 分镜镜头表。

支持 OpenAI 兼容接口（DeepSeek / 通义 / GLM 均兼容）。
API key 通过 config.json 的 llm.api_key 配置，支持 env:// 前缀读取环境变量；
环境变量为空时自动回退读取 WorkBuddy 模型设置里的 DeepSeek key。
"""
import json
import os
import urllib.request


def _load_workbuddy_deepseek_key():
    """回退：从 WorkBuddy 模型配置 ~/.workbuddy/models.json 读取已配置的 DeepSeek key。
    这样用户在 WorkBuddy 里配过 DeepSeek 后，本工作流无需再单独 set 环境变量。"""
    for p in (os.path.expanduser("~/.workbuddy/models.json"),
              os.path.expanduser("~/WorkBuddy/models.json")):
        if not os.path.exists(p):
            continue
        try:
            data = json.load(open(p, encoding="utf-8"))
        except Exception:
            continue
        if isinstance(data, list):
            for m in data:
                if (isinstance(m, dict)
                        and m.get("vendor", "").lower() == "deepseek"
                        and m.get("apiKey")):
                    return m["apiKey"]
    return ""


def _resolve_key(cfg):
    key = cfg["llm"]["api_key"]
    if isinstance(key, str) and key.startswith("env://"):
        key = os.environ.get(key[6:], "")
    if not key:
        # 回退：复用 WorkBuddy 模型设置里已配置的 DeepSeek key
        key = _load_workbuddy_deepseek_key()
    return key


def _chat(cfg, system, user, temperature=0.7, timeout=300):
    """统一的 chat 调用，返回已解析的 JSON。"""
    key = _resolve_key(cfg)
    if not key:
        raise RuntimeError(
            "未配置 LLM api_key：请在 config.json 填写，或设置环境变量 "
            "（config 中写 \"env://DEEPSEEK_API_KEY\" 然后 set DEEPSEEK_API_KEY=xxx）")
    url = cfg["llm"]["base_url"].rstrip("/") + "/chat/completions"
    payload = {
        "model": cfg["llm"]["model"],
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "response_format": {"type": "json_object"},
        "temperature": temperature,
    }
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer " + key})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        resp = json.loads(r.read())
    return json.loads(resp["choices"][0]["message"]["content"])


# ==================== 1) 小说章节 -> 短剧剧本 ====================

SCRIPT_SYSTEM = """你是一位专业的短剧编剧。请把给定的小说章节改编成一支短剧剧本。

要求：
1. 按「场」组织（每场是一个连续时空的段落）。每场必须给出：场号、地点、时间、出场人物、
   action（动作与画面描写）、dialogue（对白/旁白列表）。
2. 严格忠于原著：保留原有叙事顺序、关键台词与人物设定，不要添加原著没有的情节或人物。
3. action 要写到「可直接拍摄」的程度：人物神态、动作细节、环境光影、声音氛围。
4. dialogue 要口语化、有张力；原作中的心理描写改用旁白（speaker 写「旁白」）来交代。
5. 节奏设计：开场要抓人，中段层层铺垫，结尾留钩子。
6. 请按用户消息中给出的目标时长控制场次数量与台词密度。

严格只输出如下 JSON，不要任何额外说明文字：
{"title":"剧名","logline":"一句话故事梗概","characters":[{"name":"方源","desc":"人物设定"}],
 "scenes":[{"no":1,"location":"青茅山山巅","time":"黄昏","characters":["方源","正道群雄"],
 "action":"画面描写…","dialogue":[{"speaker":"某人","text":"台词内容"}]}]}
"""


def make_script(text, cfg, minutes=5):
    """小说章节 -> 剧本（dict）。"""
    user = f"目标成片时长约 {minutes} 分钟。\n\n以下是小说章节内容：\n\n{text}"
    return _chat(cfg, SCRIPT_SYSTEM, user, temperature=0.6)


# ==================== 2) 剧本 -> 分镜镜头表 ====================

STORYBOARD_SYSTEM = """你是一位专业的 AI 漫剧分镜师。给定短剧剧本，请拆解为适合 AI 视频生成的镜头表（shots）。

【生成方式（极重要）】主线（chain）逐镜生成约 2~5 秒视频：**以 video_prompt 为主字段**，
画面由「参考图（主角三视图）/ 上一镜尾帧」或纯文字三种方式之一控制。仍要填 first_frame_prompt /
last_frame_prompt（该镜起止画面的英文描述，供备用与人工核对），二者是同一镜头内前后瞬间的画面，
空间、光线、人物造型须自洽。

【镜头衔接（极重要）】每个镜头必须标注 continuity，运行期据此决定「要不要接上一镜的尾帧」：
- "continue"：本镜与上一镜是**同一机位下的连续动作**（只是推进/延长），接上一镜尾帧零错位续拍。
- "new_angle"：同一场，但**换了机位/景别/被摄对象**（如从甲的特写切到乙的特写、从平视切到俯瞰），
  不接上一镜尾帧，重新构图。
- "new_scene"：跨场（scene_no 改变）或明显的空间/时空跳转（如闪回到另一个世界），重新构图并重锚。
判断口径：**绝大多数切镜都应是 new_angle / new_scene**，只有「同一镜头的延伸」才用 continue。
禁止把互不相干机位的镜头标成 continue，否则画面会长时间几乎不变。

每个镜头必须包含字段：
- index: 镜头序号，从 1 开始递增
- scene_no: 本镜头属于剧本第几「场」（整数，从 1 开始；跨场时必须改变编号）
- shot_type: 取 "detail" | "action" | "transition" | "dialogue" 之一
- protagonist: 布尔值。**该镜画面的拍摄主体是不是主角（本片主角=方源）** —— 只有方源本人是主体
  （他的脸/身/背影占画面主要地位）才 true；拍别人的特写（如群雄甲、家老丙）、纯空镜、群像远景
  一律 false。运行期只有 true 才给该镜注入方源的外貌/服装串与三视图参考图；标错会把方源的脸和
  黑袍串到配角身上、导致「台词人物不符」，务必逐镜判断。
- continuity: 取 "continue" | "new_angle" | "new_scene"（见上「镜头衔接」）。
- scene: 中文场景描述，**必须写明人物神态与场景细节**（供人工审阅）
- first_frame_prompt: 该镜头**起始画面**的英文提示词（主体、神态、景别、光影、构图、风格）
- last_frame_prompt: 该镜头**结束画面**的英文提示词（与首帧同一场景，动作/机位有推进）
- video_prompt: 英文运动与氛围提示词（镜头运动 + 主体动作 + 节奏感）。**这是 chain 模式的主用字段**
  （具体走 R2V/I2V/T2V 由上面的 continuity 决定，运行期自动选择）。
- line: 该镜头的台词/旁白（中文；无声则空字符串 ""）。**line 会被运行期转成 H3 原生对白语法
  `<d>[Chinese] 台词</d>` 连同说话人一起注入 video_prompt，由视频模型在生成画面时同步产出人声**，
  所以有台词的镜头必须同时给出 speaker/speech_mode/speech_verb。
- speaker_key: line 非空时，说话人的**中文姓名/身份**（取自剧本 dialogue.speaker，如 "方源" /
  "旁白" / "正道群雄甲" / "家老丙"）；同一人物全片必须用同一个 key，运行期据此给每人分配固定
  音色 ID（S1/S2…），避免多人串音。无台词留 ""。
- speaker: line 非空时，说话人的英文描述（**身份 + 音色语气**，如
  "An elderly righteous cultivator in grey robes with a hoarse, enraged voice"）；无台词留 ""。
- speech_mode: line 非空时取 "on-screen"（说话人在画面内、口型可见）或
  "off-screen"（画外音，要求画面人物嘴唇闭合）；无台词留 ""。
- speech_verb: line 非空时的说话动词，如 "shouts" / "sneers" / "cries out" / "says softly"；无台词留 ""。
- duration: 镜头时长（秒），取 2 到 5 之间的整数

【节奏原则】H3 单镜头上限约 5 秒，所以「某场戏占多久」由分配几个镜头决定，而非 duration：
- 关键细节 / 情绪特写 / 重要台词：拆成 2~4 个连续镜头（换景别、换角度），占更多时长；
- 激烈动作 / 冲击瞬间 / 剧情转折：只给 1 个短镜头（2~3 秒），干脆利落；
- 环境 / 过场 / 氛围：1 个镜头，3~4 秒。
禁止平均分配，全片必须明显有快有慢。

【画风（极重要）】本片是**中国彩色二维动画（国漫番剧风·淡彩）**，不是真人影视，也不是 3D CG。
所有英文提示词——**包括 video_prompt**——都必须以这句开头：
"Chinese donghua anime style, 2D cel-shaded illustration, clean line art, flat coloring with soft muted palette, lightly desaturated colors, "
（**淡彩**：平涂赛璐璐 + 柔和低饱和，不要高饱和艳丽色；video_prompt 常被漏写画风串，它会被直接喂给视频
模型，**无图可依的镜头全靠它锁画风**，务必带上。）
并禁止出现任何写实/摄影词：photorealistic、cinematic film still、real person、photograph、
hyperrealistic、DSLR、35mm 等；"cinematic lighting" 一律改写为 "anime dramatic lighting"，
"cinematic wuxia style" 一律改写为 "wuxia cultivation fantasy anime key visual"。

【风格统一】同一部片子里人物造型、服装、画风、色调必须一致。每镜英文提示词都要**重复写清
主角外貌**（例如 "a slender young man with a lean narrow face and a soft jawline, sharp narrow
half-lidded eyes, long straight black hair worn completely loose with no topknot no hair band,
pale skin"），不要用代词指代。
- 主角**永远面无表情、漠视一切、无情绪波动**：写 "completely expressionless with lips in a
  flat neutral line, no smile"；**禁止** smile / smiling / grin / smirk / gentle expression
  等任何笑容或柔和表情词。
- 主角头发**一律散发**：写 "long straight black hair worn completely loose"，并显式否定
  "no topknot, no bun, no hair band, no hairpin"（模型常自动补发髻/发带）。
- 主角服装为**黑交领长袍 + 白内衬 + 纯黑布腰带**（非主角不写）。服装与外貌串还会由运行期
  按 config 统一注入一份，分镜里也写一份以求稳，但**不得与之矛盾**。

严格只输出如下 JSON，不要任何额外说明文字：
{"shots":[{"index":1,"scene_no":1,"shot_type":"detail","protagonist":true,"continuity":"new_scene",
"scene":"…","first_frame_prompt":"…","last_frame_prompt":"…","video_prompt":"…","line":"…",
"speaker_key":"","speaker":"","speech_mode":"","speech_verb":"","duration":5}]}
"""


def make_storyboard(script, cfg, max_shots=0):
    """剧本 -> 分镜表（dict {"shots":[...]}）。

    script: make_script 返回的 dict，或已序列化的字符串。
    max_shots: >0 时只要求拆出前 N 个镜头（小样验证用）。
    """
    s = script if isinstance(script, str) else json.dumps(script, ensure_ascii=False)
    sys_p = STORYBOARD_SYSTEM
    if max_shots > 0:
        sys_p += ("\n\n【本次范围】只拆解剧本最开头的一部分内容，输出恰好 "
                  f"{max_shots} 个镜头，不要超出；即使剧本还有后续内容也请停下。")
    return _chat(cfg, sys_p, "以下是短剧剧本：\n\n" + s, temperature=0.7)
