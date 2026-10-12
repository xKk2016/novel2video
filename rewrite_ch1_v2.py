# -*- coding: utf-8 -*-
"""
《蛊真人·第一章》分镜 v2 重写器（2026-10-05）

修三件事：
  1) 时长按内容分配 —— 对白镜时长 = 台词字数/4.2 + 1.0s 反应缓冲，
     对齐 H3 的 17k+5 帧网格（124~277 帧 = 5.17~11.54s），写进 `length` 字段，
     由 novel_to_video.py 提交时使用（不再被模板的 124 帧写死）。
  2) 语言锁中文 —— 每个说话人描述带 "speaking Mandarin Chinese"；
     旁白改用官方画外音句式（off-screen voiceover + 嘴唇闭合说明）。
  3) 人物锁三视图 —— 主角镜 prompt 显式 `<Picture 1..4>` 引用（含背面），
     背影镜额外描述背后特征。

输出：
  output/script_ch1_v2.json        精简旁白后的剧本（与台词逐字一致）
  output/storyboard_ch1_v2.json    新分镜（全局连续 index）

用法：python rewrite_ch1_v2.py
"""
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "output")

STYLE = ("Chinese donghua anime style, 2D cel-shaded illustration, clean line art, "
         "flat coloring with soft muted palette, lightly desaturated colors")

# H3 MiniMaxH3ReferenceToVideo.length：17k+5 网格，训练范围 124~362 帧（24fps）
GRID = [5 + 17 * i for i in range(22)]
FRAME_LO, FRAME_HI = 124, 277       # 5.17s ~ 11.54s（老板选 ≤12s）
RATE = 4.2                          # 字/秒
BUFFER = 1.0                        # 每镜呼吸/反应缓冲（秒）

# 主角三视图引用串（顺序 = config.ref_images_by_scene：front, side, face, back）
SUBJ_FULL = "<Subject 1>, the same young man as in <Picture 1>, <Picture 2>, <Picture 3> and <Picture 4>"
SUBJ_BACK = "<Subject 1>, the same young man as in <Picture 4> and <Picture 1>"

# 说话人音色（一律带中文口音锚）
SPK = {
    "方源成年": "A calm young man in his late twenties in a black robe, with a low, indifferent, cold voice, speaking Mandarin Chinese",
    "方源少年": "A quiet teenage boy about sixteen in a black robe, with a low, calm, indifferent voice, speaking Mandarin Chinese",
    "旁白": "A deep, calm male narrator voice, speaking Mandarin Chinese",
    "古月族长": "An elderly clan leader in white ceremonial robes, with an aged, solemn, low voice, speaking Mandarin Chinese",
    "正道群雄甲": "A middle-aged righteous cultivator in white robes, with a furious, loud, sharp voice, speaking Mandarin Chinese",
    "正道群雄乙": "A young righteous cultivator in blue robes, with a sneering, cold, threatening voice, speaking Mandarin Chinese",
    "正道群雄丙": "An elderly righteous cultivator in grey robes, with a hoarse, enraged, trembling voice, speaking Mandarin Chinese",
    "正道群雄丁": "A middle-aged female cultivator in dark red robes, with a bitter, hateful, tearful voice, speaking Mandarin Chinese",
    "家老甲": "An elderly clan elder in white robes, with a weary, nostalgic voice, speaking Mandarin Chinese",
    "家老乙": "An elderly clan elder in white robes, with a gentle, reminiscent voice, speaking Mandarin Chinese",
    "家老丙": "An elderly clan elder in white robes, with a calm, thoughtful voice, speaking Mandarin Chinese",
    "家老丁": "An elderly clan elder in white robes, with a worried, hopeful voice, speaking Mandarin Chinese",
    "家老戊": "An elderly clan elder in white robes, with an anxious, low voice, speaking Mandarin Chinese",
    "家老己": "An elderly clan elder in white robes, with a mild, tentative voice, speaking Mandarin Chinese",
    "家老庚": "An elderly clan elder in white robes, with an eager, admiring voice, speaking Mandarin Chinese",
    "家老辛": "An elderly clan elder in white robes, with a knowing, delighted voice, speaking Mandarin Chinese",
}

QUNXIONG = ["正道群雄甲", "正道群雄乙", "正道群雄丙", "正道群雄丁"]
JIALAO = ["家老甲", "家老乙", "家老丙", "家老丁", "家老戊", "家老己", "家老庚", "家老辛"]


def speaker_of(key):
    """说话人 key -> (音色描述, speech_mode, speech_verb)"""
    if key == "方源":
        return None, "on-screen", "says"      # 按场由 _fy 分成年/少年
    if key == "旁白":
        return SPK["旁白"], "off-screen", "says"
    return SPK.get(key, "A character with a clear, distinctive voice"), "on-screen", "says"


def _fy(scene_no):
    """方源按场次分成年/少年音色；（音色, 口音）"""
    return SPK["方源成年"] if scene_no == 1 else SPK["方源少年"]


def frames_for(line):
    """按台词字数选最小可容纳的帧档（无台词返回 None）。"""
    if not line:
        return None
    need = len(line) / RATE + BUFFER
    for f in GRID:
        if f < FRAME_LO:
            continue
        if f > FRAME_HI:
            break
        if f / 24.0 >= need - 1e-9:
            return f
    raise ValueError(f"台词过长需拆镜（{len(line)}字 / 需 {need:.2f}s）：{line}")


# ============================== 分镜表 ==============================
# k = (场景中文描述, 英文镜头正文)。line/speaker/时长由代码按规则算。
S = []


def shot(scene_no, shot_type, protagonist, anchor, continuity, scene, prompt,
         speaker_key="", line="", speech_verb="", duration=None, ref="full",
         anchor_mode=None, appearance=None):
    """anchor_mode: i2v=锚图当首帧（环境空镜，保证同空间背景一致）
                     prompt=只用文字锚、重新构图（人物镜 —— 空景首帧长不出人脸）
    appearance: 镜头级外貌串，覆盖 config.character（背影镜必须换成背面口径，
                否则「眼睛/表情」这类正面特征会诱导模型把脸转过来）"""
    if anchor_mode is None:
        anchor_mode = "prompt" if (not protagonist and line) else "i2v"
    S.append(dict(scene_no=scene_no, shot_type=shot_type, protagonist=protagonist,
                  anchor=anchor, continuity=continuity, scene=scene, prompt=prompt,
                  speaker_key=speaker_key, line=line, speech_verb=speech_verb,
                  duration=duration, ref=ref, anchor_mode=anchor_mode,
                  appearance=appearance))

# 背影专用外貌串：只描述背面可见的东西，显式排除脸
FY_BACK_APPEARANCE = ("seen from behind, the back of his head and his long straight black hair "
                      "falling loose down the back of his black robe, the plain black cloth belt "
                      "knotted at the waist seen from the back, a slender build, "
                      "no face visible, no eyes visible, no expression visible")


# ---------------- 场 1：青茅山山巅（前世自爆） ----------------
SC1, AN1 = 1, "peak_dusk"

shot(SC1, "establishing", False, AN1, "new_scene",
     "青茅山山巅，残阳如血，乌云压顶。荒芜的灰白岩石山脊空无一人，石缝间积着一滩暗红的血水，山风呼啸，枯草伏地。",
     "Extreme wide establishing shot of a barren grey mountain summit at dusk, a blood-red setting sun burning through dark storm clouds, jagged grey boulders and a dark pool of blood seeping across the cracked stone, dead grass flattened by a howling wind, no people, desolate and still, slow drift to the right",
     duration=5.17)

shot(SC1, "dialogue", True, AN1, "new_angle",
     "过肩视角：前景是方源血污的背影，虚焦；画面前方一名白衣中年正道修士抬手指着他，满脸怒容。",
     f"Over-the-shoulder shot from behind the blood-soaked young man, {SUBJ_FULL} standing in the foreground with his back to camera, his torn black robe and long loose hair filling the left edge, a middle-aged righteous cultivator in white robes facing him with a raised accusing finger, furious, warm blood-red rim light from behind the ridge",
     "正道群雄甲", "方源，乖乖地交出春秋蝉，我给你个痛快！", "shouts")

shot(SC1, "dialogue", False, AN1, "new_angle",
     "中景：蓝袍青年修士挺剑前指，冷笑中透着威胁，剑身映着斜阳。",
     "Medium shot, a young righteous cultivator in blue robes thrusting his longsword forward, sneering with cold contempt, sunlight glinting along the blade, slow push-in, crowd blurred behind him",
     "正道群雄乙", "方老魔，你不要妄图反抗了！今日正道各派联合，就是要踏破你的魔窟。", "sneers")

shot(SC1, "dialogue", False, AN1, "new_angle",
     "大俯拍全景：数十名正道修士从四面八方合围，刀剑如林，包围圈正在收紧。",
     "High wide shot looking down at dozens of righteous cultivators closing in from every direction, a tightening ring of raised blades and fluttering robes, the mountain summit ringed by a wall of enemies, dust drifting, oppressive scale",
     "正道群雄乙", "这里早已布下天罗地网，这次你必定身首异处！", "shouts")

shot(SC1, "dialogue", False, AN1, "new_angle",
     "灰袍老修士面部特写，皱纹扭成一团，怒极咆哮，硬侧光刻出脸部沟壑。",
     "Tight close-up of an elderly cultivator in grey robes, his face contorted with rage, veins standing out on his temple, harsh side light carving deep wrinkles, slow push-in, spittle at the corner of his mouth",
     "正道群雄丙", "方源你个该死的魔头！你为炼春秋蝉，杀了千万人的性命。", "shouts")

shot(SC1, "dialogue", False, AN1, "new_angle",
     "群像中景：正道众人齐齐伸手指向前方，衣袖翻飞，怒火汇成一片。",
     "Group medium shot of the righteous crowd, dozens of accusing hands pointing forward in unison, sleeves snapping in the wind, faces twisted with anger, the mass of bodies pressing closer",
     "正道群雄丙", "你犯下滔天罪孽，罪无可恕，罄竹难书！", "shouts")

shot(SC1, "dialogue", False, AN1, "new_angle",
     "暗红衣中年女修士特写，眼中含泪，恨意几乎溢出画面，冷调补光。",
     "Close-up of a middle-aged female cultivator in dark red robes, tears brimming in her eyes while hatred hardens her jaw, cool fill light against warm dusk, slight handheld tremor",
     "正道群雄丁", "魔头！三百年前你夺我清白，杀我全家，诛我九族！", "cries out")

shot(SC1, "dialogue", False, AN1, "new_angle",
     "同一女修士近景，身体因悲愤而颤抖，指甲掐进掌心。",
     "Medium close-up of the same woman, her whole body trembling with grief and rage, her nails digging into her own palm, shallow focus on her tear-streaked face, dusk glow behind her",
     "正道群雄丁", "我恨不得吃你肉，喝你的血！今天要你生不如死！", "cries out")

shot(SC1, "action", True, AN1, "new_angle",
     "中景：方源浑身浴血，赤脚站在血泊里缓缓环顾四周，血袍被山风吹得猎猎翻卷。",
     f"Medium shot, {SUBJ_FULL} soaked in blood, turning his head slowly to scan his surroundings, hundreds of wounds weeping red through his torn black robe, the hem snapping in the mountain wind like a war banner, blood pooling around his bare feet",
     duration=6.58)

shot(SC1, "detail", True, AN1, "continue",
     "方源面部大特写：血污覆面，神情平淡得近乎漠然，目光幽幽如古井。",
     f"Extreme close-up of the face of {SUBJ_FULL}, blood spatter across his pale cheek, completely expressionless, lips pressed into a flat neutral line, an indifferent empty stare, warm blood-red rim light along his jaw, very slow push-in",
     "旁白", "方源对局势洞若观火，即便死亡将临，仍面不改色。", "says")

shot(SC1, "detail", True, AN1, "new_angle",
     "背影大远景：方源背对镜头独立山石之巅，散发披在后背的黑袍上，山下群敌密密麻麻仰望着他。",
     f"Wide shot from directly behind {SUBJ_BACK}, seen from the back, the back of his head and his long straight black hair falling loose down the back of his black robe, the plain black cloth belt knotted at his waist seen from behind, his slender blood-stained silhouette standing alone on the rock, the dense crowd of cultivators far below the ridge facing him, cold wind lifting his hair, desolate stillness, very slow push-in",
     duration=5.88, ref="back", appearance=FY_BACK_APPEARANCE)

shot(SC1, "action", True, AN1, "continue",
     "方源开始慢慢转身，从背影过渡到四分之三侧脸，长发随转身甩动。",
     f"Medium shot of {SUBJ_BACK} slowly turning from back view into a three-quarter profile, his long loose black hair swinging across his back as he turns, blood-soaked robe dragging, the crowd flinching backward in the blurred background, single continuous turn, no cut",
     duration=7.29, ref="back", appearance=FY_BACK_APPEARANCE)

shot(SC1, "dialogue", True, AN1, "new_angle",
     "方源侧脸中近景，望向远方青山与落日，唇角极淡地牵起一丝笑意。",
     f"Medium close-up in side profile of {SUBJ_FULL}, gazing at distant green mountains and the sinking red sun, a very faint smile at the corner of his mouth, the warm dusk glow brushing his blood-stained face, shallow focus, slow push-in",
     "方源", "青山落日，秋月春风。当真是朝如青丝暮成雪，是非成败转头空。", "says softly")

shot(SC1, "transition", False, "flashback", "new_angle",
     "闪回意象：温暖模糊的现代城市剪影与光斑，如梦似幻，与血色的山巅形成强烈反差。",
     "Hazy dreamlike memory vision, blurred warm streaks of light and the indistinct faraway silhouette of a modern earthly city skyline, glowing bokeh drifting across frame, nostalgic muted desaturated tones, soft and unfocused, slow tilt upward",
     "旁白", "他本是地球华夏学子，穿越此界，五百年光阴晃眼即逝。", "says")

shot(SC1, "detail", True, AN1, "new_angle",
     "超远景：方源渺小的身影被层层黑影般的群敌牢牢围在正中，天地间只剩他一人站着。",
     f"Extreme wide shot, the tiny slender figure of {SUBJ_FULL} standing alone at the exact center of frame, encircled by rings of dark silhouetted enemies stretching to the edges, vast empty dusk sky above, crushing sense of isolation",
     "旁白", "终究是失败了。他并不后悔——所谓魔道，本就举世皆敌。", "says")

shot(SC1, "action", True, AN1, "new_angle",
     "低角度英雄镜：方源仰头放声大笑，长发向后甩开，晚霞在头顶烧成一片火。",
     f"Low-angle hero shot looking up at {SUBJ_FULL}, his head tipped back as he laughs out loud, long loose hair thrown back off his face, the burning sunset sky filling the frame behind his head, slow push-in, defiant energy",
     "方源", "若是刚炼成的春秋蝉有效，来生还是要做邪魔！", "laughs")

shot(SC1, "dialogue", False, AN1, "new_angle",
     "白衣中年修士特写，得意的表情僵住，转为困惑与不安。",
     "Close-up on the middle-aged cultivator in white robes, his angry confidence cracking into confusion and unease, eyes narrowing as he leans slightly forward, dusk shadow across half his face",
     "正道群雄甲", "老魔，你笑什么？", "shouts")

shot(SC1, "dialogue", False, AN1, "new_angle",
     "蓝袍青年修士举剑戒备，脚步不自觉后错半步，衣袂绷紧。",
     "Medium shot of the young cultivator in blue robes raising his sword into a guard stance, shifting half a step backward, robes taut, alarm spreading across the surrounding crowd behind him",
     "正道群雄乙", "大家小心，魔头死到临头要反扑了！", "shouts")

shot(SC1, "dialogue", False, AN1, "new_angle",
     "群雄从画面两侧向中间压迫推进，脚步与翻飞的衣摆占满前景。",
     "Low tracking shot as the crowd of cultivators surges forward from both sides of frame, boots and flapping robes filling the foreground, faces set with greed and fear, the ring collapsing inward",
     "正道群雄丙", "快快交出春秋蝉！", "shouts")

shot(SC1, "action", True, AN1, "new_angle",
     "方源身躯骤然爆开一团刺目白光，光芒吞没画面，群敌身影被瞬间掀飞。",
     f"Blinding white light erupting outward from the body of {SUBJ_FULL}, the explosion swallowing the frame in a flood of overexposed radiance, silhouettes of the crowd thrown backward by the blast wave, embers and dust streaking past camera",
     "旁白", "群雄逼迫而来，恰在这时，轰的一声，方源悍然自爆。", "says")


# ---------------- 场 2：古月山寨夜 / 宗族祠堂 / 走廊 ----------------
SC2 = 2

shot(SC2, "establishing", False, "village_night", "new_scene",
     "春雨绵绵的深夜，青茅山从山腰到山脚亮着层层暖黄的灯火，高脚吊楼沿山势而建，如一条灿烂的光带。",
     "Wide establishing shot of an ancient mountain village at night under fine spring rain, tiered dark wooden stilt houses built along the hillside, warm yellow lantern light glowing from countless windows to form a luminous ribbon down the mountain, drifting mist, dark forested ridges behind, slow drift left",
     duration=5.17)

shot(SC2, "establishing", False, "ancestral_hall", "new_scene",
     "祠堂全景：正中三层黑漆台案供着先祖牌位，赤铜香炉香烟袅袅，深色木柱与横梁压出庄重的对称构图。",
     "Perfectly symmetrical static wide shot inside an ancient ancestral hall at night, a three-tiered black lacquered altar holding rows of ancestral tablets on the central axis, bronze incense burners trailing thin smoke, thick dark timber pillars and beams, dim candlelight, solemn stillness",
     duration=5.17)

shot(SC2, "dialogue", False, "ancestral_hall", "continue",
     "中景：古月族长素白祭服，跪在棕黄木地板上直着上身，双手合十闭目祈祷，身后十余位白袍家老同样跪伏。",
     "Medium shot, slow push-in on an elderly clan leader in white ceremonial robes kneeling upright on the brown wooden floor, hands pressed together and eyes shut in prayer, the row of white-robed clan elders kneeling behind him, candle flame and incense smoke in the foreground",
     "古月族长", "列祖列宗保佑，希望此次开窍大典中能多多涌现出资质优秀的少年，为家族增添新血和希望！", "prays")

shot(SC2, "action", False, "ancestral_hall", "continue",
     "低角度：族长弯腰将额头贴上地板磕头，身后白袍家老依次俯身，额碰地板的轻响回荡在祠堂里。",
     "Low-angle shot as the clan leader bends until his forehead touches the brown wooden floor, the row of white-robed elders bowing behind him in a slow wave, dust motes drifting in the candlelight, static camera, quiet ritual gravity",
     duration=5.17)

shot(SC2, "dialogue", False, "corridor", "new_scene",
     "走廊中景：一排橙黄纸灯笼均匀悬在檐下，族长最后一个走出祠堂，几名家老在廊下低声议论。",
     "Medium shot in a long wooden corridor at night, rows of matching orange-yellow paper lanterns hanging evenly from the eaves, weathered timber pillars, the clan leader walking out of the hall last while a few white-robed elders talk in low voices, warm pools of lantern light on wet stone",
     "家老甲", "时间过的真是太快了，一眨眼，一年就都过去了。", "says")

shot(SC2, "dialogue", False, "corridor", "new_angle",
     "家老近景：白发老者抚着胡须感慨，灯笼光在脸上投下暖影。",
     "Medium close-up of an elderly clan elder stroking his beard with a nostalgic expression, warm lantern light falling across his wrinkled face, shallow depth of field, the corridor receding into darkness behind him",
     "家老乙", "上一届的开窍大典就像是昨天发生的一样，依旧历历在目呢。", "says")

shot(SC2, "dialogue", False, "corridor", "new_angle",
     "两位家老并肩中景，一人抬眼望着廊外的雨幕，语气里带着期待。",
     "Medium shot of two clan elders side by side in the corridor, one lifting his gaze toward the curtain of spring rain beyond the eaves, faint hope in his expression, lantern glow rimming their white robes",
     "家老丙", "明日就是一年一度的开窍大典了，不知道今年会涌现出什么样的家族新血呢？", "says")

shot(SC2, "dialogue", False, "corridor", "new_angle",
     "家老特写，眉头因忧心而锁紧，叹气时肩膀明显塌了一下。",
     "Close-up of an elderly clan elder, his brows knit with hope and worry, shoulders dropping as he lets out a heavy sigh, warm lamplight tracing the lines of his face, very slight handheld float",
     "家老丁", "唉，希望有甲等资质的少年出现。我们古月一族已经有三年没有这样的天才出现了。", "sighs")

shot(SC2, "dialogue", False, "corridor", "new_angle",
     "家老皱眉压低声音，手里攥着袍角，周围几人脸色一沉。",
     "Medium shot of a clan elder lowering his voice with a troubled frown, his hand gripping the corner of his robe, the faces of the elders around him darkening as the name is spoken, lantern light flickering",
     "家老戊", "不错，白家寨、熊家寨这些年都有天才涌现。尤其是白家的白凝冰，天资真是恐怖。", "says gravely")

shot(SC2, "dialogue", False, "corridor", "new_angle",
     "群像中景：提及那个名字，众家老脸上的笑意齐齐褪去，只剩一层化不开的忧色。",
     "Group medium shot of the clan elders as the name is spoken, every trace of warmth draining from their faces into a shared look of worry, a silent beat of glances exchanged, lanterns swinging slightly overhead",
     "旁白", "提及白凝冰，众家老脸上浮现忧色——此子两年便修到三转。", "says")

shot(SC2, "dialogue", False, "corridor", "new_angle",
     "家老米白长眉微动，语气忽然一转，看向同伴。",
     "Medium close-up of an elderly clan elder with long white eyebrows, his tone shifting as he turns his head toward the elder beside him, a flicker of hope replacing the gloom, soft lantern key light",
     "家老己", "不过今年参加开窍大典的少年里，也不是没有希望。", "says")

shot(SC2, "dialogue", False, "corridor", "new_angle",
     "家老压低嗓音往前凑了半步，眼里放出光来，袍袖轻摆。",
     "Medium shot of a clan elder leaning half a step forward with a lowered voice, his eyes brightening with admiration, robe sleeves swaying faintly, the others turning toward him",
     "家老庚", "不错，方之一脉出现了一个天才少年。三月能言，四月能走。", "says eagerly")

shot(SC2, "dialogue", False, "corridor", "new_angle",
     "近景：家老感慨地摇头，指尖在空中虚点两下，满是惜才之意。",
     "Medium close-up of the elder shaking his head with feeling, his finger tapping the air twice as if reciting, genuine regret over the boy's dead parents, warm rim light separating him from the dark corridor",
     "家老庚", "五岁便能作诗诵词，聪慧异常，可惜父母死的早，如今被舅父舅母抚养。", "says")

shot(SC2, "dialogue", False, "corridor", "new_angle",
     "家老捻须点头，语气笃定地评价。",
     "Close-up of a clan elder nodding slowly while stroking his beard, a certainty in his bearing, lantern light catching the silver thread of his beard, shallow focus",
     "家老辛", "嗯，这是有早智的，而且有大志向。", "says")

shot(SC2, "dialogue", False, "corridor", "new_angle",
     "家老抚掌轻笑，眼里透着赏识，几人相视而笑。",
     "Medium shot of a clan elder clapping his palms together with a soft laugh, open admiration in his eyes, the elders around him exchanging knowing smiles, warm lantern glow pooling on the wooden floor",
     "家老辛", "他作的《将进酒》《咏梅》《江城子》，我也听过，真是天才！", "says")


# ---------------- 场 3：走廊议论 / 窗前望寨 ----------------
SC3 = 3

shot(SC3, "transition", False, "corridor", "new_scene",
     "中景：族长最后一个走出祠堂，回身慢慢合上厚重的木门，门轴发出低沉声响。",
     "Medium shot, camera follows the elderly clan leader in white ceremonial robes as he pulls the heavy hall doors shut behind him, the long corridor falling quiet, lantern light spilling across the wet floor, a slow dolly backward",
     duration=5.17)

shot(SC3, "dialogue", False, "corridor", "new_angle",
     "中近景：族长停在廊中，听见家老们的议论，神色未动，目光却沉了下来。",
     "Medium close-up of the clan leader pausing mid-corridor as the elders' murmuring reaches him, his expression unchanged while his gaze settles and darkens, warm lantern key light from the right, very slow push-in",
     "旁白", "族长顿时明白，家老们议论的是古月方源。", "says")

shot(SC3, "dialogue", False, "corridor", "new_angle",
     "族长面部特写，唇角几不可察地微微翘起，浮现一抹笑意。",
     "Close-up of the clan leader's face, his lips curving into a very faint smile, eyes growing thoughtful and measuring, warm lamplight on one side of his face, deep shadow on the other, static camera",
     "旁白", "若他测出甲等资质，未必不能与白凝冰抗衡。族长嘴角微翘。", "says")

shot(SC3, "dialogue", False, "corridor", "new_angle",
     "中景：族长咳嗽一声，转身面对众家老，语气转为郑重的嘱咐。",
     "Medium shot, the clan leader clears his throat and turns to face the gathered elders, his bearing shifting into formal authority, lanterns lining the corridor behind him, slow push-in",
     "古月族长", "诸位，时候不早了，为了明日的开窍大殿，今晚请务必好好休息，保养精神。", "says")

shot(SC3, "dialogue", False, "corridor", "new_angle",
     "群像中景：家老们齐齐一怔，彼此交换的眼神里藏着警惕的锋芒。",
     "Group medium shot of the clan elders, all briefly taken aback, then trading glances edged with wary calculation, a subtle tension rippling through the row of white robes, lantern light between them",
     "旁白", "家老们微微一怔，目光里藏着警惕。", "says")

shot(SC3, "dialogue", False, "corridor", "new_angle",
     "中近景：家老们各自垂目盘算，袖中的手暗自收紧，灯火在他们脸上明明灭灭。",
     "Medium close-up cluster of clan elders lowering their eyes to calculate, hands tightening inside their sleeves, lantern flame wavering across their faces, uneasy stillness",
     "旁白", "每年为争夺天才后辈，家老们都争得头破血流。", "says")

shot(SC3, "dialogue", False, "corridor", "new_angle",
     "族长近景，语气陡然严肃，目光扫过众人。",
     "Medium close-up of the clan leader, his tone hardening as his gaze sweeps across the elders, jaw set, lantern light sharpening the lines of his face, static camera",
     "古月族长", "不过，丑话先说在前头。", "says")

shot(SC3, "dialogue", False, "corridor", "new_angle",
     "族长面部特写，一字一顿地告诫，眼神不容置疑。",
     "Tight close-up of the clan leader delivering his warning word by word, unwavering eyes, the warm lantern glow giving way to cooler shadows around him, very slow push-in",
     "古月族长", "争要堂堂正正的争，不可以动用阴谋手段，损害家族的团结。诸位请牢记在心！", "says")

shot(SC3, "dialogue", False, "corridor", "new_angle",
     "家老低头拱手，语带恭顺。",
     "Medium shot of an elderly clan elder bowing his head with cupped hands, deferential in posture, lantern light outlining the white robe, background elders going still",
     "家老甲", "不敢，不敢。", "says")

shot(SC3, "dialogue", False, "corridor", "new_angle",
     "家老微微颔首，表情恭谨。",
     "Close-up of a clan elder giving a small solemn nod, hands folded, warm key light on his face, shallow depth of field",
     "家老乙", "一定牢记在心。", "says")

shot(SC3, "dialogue", False, "corridor", "new_angle",
     "家老拱手告辞，侧身让开通道。",
     "Medium shot of a clan elder cupping his hands in farewell and stepping aside to clear the corridor, the line of elders beginning to break up behind him, lanterns receding into the dark",
     "家老丙", "这就告辞了，族长大人请留步。", "says")

shot(SC3, "transition", False, "corridor", "new_angle",
     "大全景：家老们一一散去，长廊很快冷清下来，只剩雨丝斜穿窗棂，灯影摇晃。",
     "Wide shot of the long corridor emptying as the elders disperse one by one, the space falling quiet and cold, spring rain slanting through the open windows, lantern shadows swaying on the empty floor, slow drift right",
     "旁白", "家老们各怀心思散去，长长的走廊冷清下来。", "says")

shot(SC3, "dialogue", False, "window_view", "new_scene",
     "中景：族长走到第三层阁楼的窗前，推开窗，大半个古月山寨的灯火在雨夜里铺展开来。",
     "Medium shot of the clan leader stepping to a latticed window on the third floor of the pavilion, pushing it open onto a wide night vista of the ancient mountain village, scattered warm window lights spread across the dark hillside, fine rain streaking the air",
     "旁白", "族长走到窗前，第三层阁楼上，大半个古月山寨尽收眼底。", "says")

shot(SC3, "dialogue", False, "window_view", "new_angle",
     "族长侧脸特写，目光落在远处点点灯火上，长叹一声，眼中倒映着光。",
     "Close-up in profile of the clan leader gazing out at the scattered lights, a long sigh escaping him, tiny warm reflections of the village glowing in his eyes, rain-streaked window glass beside his face, static camera",
     "古月族长", "这就是家族未来的希望啊。", "sighs")


# ---------------- 场 4：方源房间窗边（重生后） ----------------
SC4 = 4

shot(SC4, "establishing", True, "fangyuan_room", "new_scene",
     "中景：少年方源静立在木格窗前，任凭夜雨斜打在单薄的黑袍上，屋里只有一盏油灯亮着。",
     f"Medium shot of {SUBJ_FULL}, a slender teenage boy standing at a plain wooden lattice window in a dim old room at night, letting the slanting rain strike his thin black robe, a single oil lamp burning on the wooden desk behind him, cool blue-grey interior with one warm pool of light",
     duration=5.17)

shot(SC4, "dialogue", True, "fangyuan_room", "new_angle",
     "方源侧影中近景，望着寨中深夜闪烁的灯火，神情平静复杂。",
     f"Medium close-up in profile of {SUBJ_FULL}, gazing at the scattered night lights of the village through the rain-streaked window, his expression calm and completely unreadable, warm lamp glow on his cheek against the cold room",
     "旁白", "同样有一双清亮的眸子，静静望着寨中深夜的灯火。", "says")

shot(SC4, "dialogue", True, "fangyuan_room", "new_angle",
     "方源面部特写：雨珠顺着窗框滑落，他眼神幽幽，神情微动。",
     f"Close-up of the face of {SUBJ_FULL} in faint lamplight, raindrops sliding down the window frame beside him, his eyes shifting with quiet realization, very slow push-in, cool blue-grey tones with warm lamp accent",
     "方源", "古月山寨，这是五百年前？！春秋蝉果真起作用了……", "says softly")

shot(SC4, "dialogue", False, "fangyuan_room", "new_angle",
     "意象特写：一只古朴的蝉形玉器在暗处泛起微光，与少年握紧的拳头叠化。",
     "Macro close-up of an ancient cicada-shaped jade vessel glimmering faintly in the shadows, slowly cross-dissolving into the boy's tightening fist, dim warm light, shallow focus, dreamlike",
     "旁白", "春秋蝉能逆转时光，在十大奇蛊中名列第七——即重生。", "says")

shot(SC4, "action", True, "fangyuan_room", "new_angle",
     "方源缓缓伸出手，掌心向上摊开在灯光下，凝视着自己稚嫩苍白的手。",
     f"Medium close-up of {SUBJ_FULL} slowly extending his hand palm-up into the lamplight, staring down at his own young, slender, pale hand, rain falling beyond the window behind him, very slow push-in",
     "方源", "利用春秋蝉重生了，回到了五百年前！", "says")

shot(SC4, "detail", True, "fangyuan_room", "continue",
     "手部特写：手指一根根收拢，最终握成紧实的拳头，指节泛起苍白。",
     "Tight close-up of the hand of the same young man as in <Picture 1> and <Picture 3>, his young pale hand closing finger by finger into a hard fist, knuckles going white, the oil lamp flame wavering beyond in the blurred background, macro shallow focus",
     "旁白", "他定定看着自己年轻苍白的手掌，缓缓握紧。", "says")

shot(SC4, "dialogue", True, "fangyuan_room", "new_angle",
     "方源闭眼近景，睫毛低垂，雨声在耳边清晰可闻。",
     f"Medium close-up of {SUBJ_FULL} closing his eyes, long lashes lowered, the faint sound of rain against the window the only motion in frame, lamp light soft on his face, static camera",
     "方源", "五百年的经历，真像是个梦啊。", "says softly")

shot(SC4, "detail", True, "fangyuan_room", "new_angle",
     "方源缓缓睁眼特写，目光重新变得深不见底。",
     f"Close-up of {SUBJ_FULL} slowly opening his eyes again, his gaze settling back into something deep and unfathomable, completely expressionless, the lamp flame reflected as a small point of light in each eye, very slow push-in",
     "旁白", "但他却清楚的知道，这绝不是梦。", "says")


# ============================== 组装 ==============================
def build():
    shots = []
    for i, s in enumerate(S, 1):
        scene_no = s["scene_no"]
        line = (s["line"] or "").strip()
        key = s["speaker_key"]

        if line:
            frames = frames_for(line)
        else:
            sec = float(s["duration"] or 5.88)
            frames = min([f for f in GRID if f >= FRAME_LO and f / 24.0 >= sec - 1e-9] or [FRAME_HI])
        dur = round(frames / 24.0, 2)

        # 说话人
        if key == "方源":
            spk, mode, verb = _fy(scene_no), "on-screen", (s["speech_verb"] or "says")
        elif key:
            spk, mode, verb = speaker_of(key)
        else:
            spk, mode, verb = "", "", ""

        base = f"{STYLE}, {s['prompt']}"
        shots.append({
            "index": i,
            "scene_no": scene_no,
            "shot_type": s["shot_type"],
            "protagonist": bool(s["protagonist"]),
            "scene": s["scene"],
            "first_frame_prompt": base,
            "last_frame_prompt": base + ", the action has advanced slightly to the end of the shot" if s["shot_type"] == "action" else base,
            "video_prompt": base,
            "line": line,
            "duration": dur,
            "length": frames,
            "speaker_key": key,
            "speaker": spk,
            "speech_mode": mode,
            "speech_verb": verb,
            "continuity": s["continuity"],
            "anchor": s["anchor"],
            "anchor_mode": s["anchor_mode"],
            "appearance": s["appearance"] or "",
            "ref": s["ref"],
        })
    return shots


def build_script(shots):
    """由分镜反推剧本（台词逐字一致，只重排说话人）。"""
    scenes_meta = {
        1: ("青茅山山巅", "黄昏", ["方源", "正道群雄"]),
        2: ("古月山寨宗族祠堂", "深夜", ["古月族长", "众家老"]),
        3: ("古月山寨楼阁走廊", "深夜", ["古月族长", "众家老"]),
        4: ("方源房间窗边", "深夜", ["方源"]),
    }
    actions = {
        1: "残阳如血，山风呼啸。方源一身残破黑袍，披头散发，浑身浴血，立于山石之上，脚下血水成泊。正道群雄四面合围，有人咆哮，有人冷笑，有人眯眼警惕，无人敢近。对峙三个时辰后，他慢慢转身，望向青山落日，轻声一笑，随即悍然自爆。",
        2: "春雨绵绵，夜色深沉。古月山寨灯火山腰铺到山脚。祠堂内，古月族长着素白祭服，跪地合十祈祷，身后十余名白袍家老跪伏。磕头声轻响，大典完毕，众人起身走出祠堂，走廊里议论声渐起。",
        3: "族长最后走出祠堂，听见家老们议论古月方源，嘴角微翘。他咳嗽一声，郑重嘱咐众人好好休息、正大光明地争。家老们各怀心思散去，走廊冷清下来。族长走到第三层窗前，望着满寨灯火，长叹一声。",
        4: "细雨绵绵，夜风微凉。少年方源站在窗边，任凭风雨打在身上，静静看着寨中深夜的灯火。他伸出手，看着自己年轻苍白的手掌，缓缓握紧，闭眼又睁开，喟然一叹。",
    }
    scenes = []
    for no in (1, 2, 3, 4):
        loc, tm, chars = scenes_meta[no]
        dlg = [{"speaker": s["speaker_key"], "text": s["line"]}
               for s in shots if s["scene_no"] == no and s["line"]]
        scenes.append({"no": no, "location": loc, "time": tm,
                       "characters": chars, "action": actions[no], "dialogue": dlg})
    return {
        "title": "春秋蝉",
        "logline": "魔道巨擘方源自爆身亡，却借春秋蝉逆转时光，重生回五百年前的开窍大典前夜，一切重新开始。",
        "characters": [
            {"name": "方源", "desc": "前世为地球华夏学子，穿越后纵横三百年，成为魔道巨擘，冷酷深沉，心思缜密，因炼制春秋蝉而遭正道围攻自爆，借春秋蝉重生回少年时代。"},
            {"name": "古月族长", "desc": "古月一族族长，中年模样，两鬓微霜，素白祭祀服，威严而稳重，对家族未来充满期望。"},
            {"name": "正道群雄", "desc": "围攻方源的正道各派高手，有长者、少年英豪，各怀仇恨与忌惮。"},
            {"name": "众家老", "desc": "古月一族的家老、话事人，各怀心思，为争夺天才后辈而暗中较劲。"},
            {"name": "旁白", "desc": "以画外音形式叙述方源的心理活动与背景信息。"},
        ],
        "scenes": scenes,
    }


def main():
    shots = build()
    sb_path = os.path.join(OUT, "storyboard_ch1_v2.json")
    json.dump(shots, open(sb_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    sc_path = os.path.join(OUT, "script_ch1_v2.json")
    json.dump(build_script(shots), open(sc_path, "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)

    lines = [s for s in shots if s["line"]]
    total = sum(s["duration"] for s in shots)
    chars = sum(len(s["line"]) for s in lines)
    print(f"分镜 {len(shots)} 镜 → {sb_path}")
    print(f"剧本 {sum(len(c['dialogue']) for c in build_script(shots)['scenes'])} 条台词 → {sc_path}")
    print(f"台词 {len(lines)} 条 / {chars} 字；成片总时长 {total:.0f}s = {total/60:.2f} 分钟")
    print()
    for no in (1, 2, 3, 4):
        sub = [s for s in shots if s["scene_no"] == no]
        print(f"  场{no}: {len(sub):>2} 镜 / {sum(s['duration'] for s in sub):>6.1f}s")
    print()
    print("时长分布：")
    from collections import Counter
    c = Counter(s["duration"] for s in shots)
    for d in sorted(c):
        print(f"  {d:>5.2f}s × {c[d]:>2} 镜")
    print()
    bad = [s for s in lines if (len(s["line"]) / RATE + BUFFER) > s["duration"] + 1e-9]
    print("时长不足的镜（应为 0）:", [s["index"] for s in bad] or "无 ✓")
    ok_ref = all(("<Picture" in s["video_prompt"]) for s in shots if s["protagonist"])
    print("主角镜均已带 <Picture 引用>:", "✓" if ok_ref else "✗")
    nolang = [s["index"] for s in shots if s["speaker"] and "Mandarin Chinese" not in s["speaker"]]
    print("说话人缺中文锚的镜（应为 0）:", nolang or "无 ✓")


if __name__ == "__main__":
    main()
