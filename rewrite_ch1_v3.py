# -*- coding: utf-8 -*-
"""《大爱仙尊》第一章 分镜 v3 —— 逐镜双语重写 + 音频层。

与 v2 的区别（针对"生成出来不太行"的根因）：
  1. 每条提示词补上音频层（H3 是原生音视频同步模型，v2 全程零声音描述，白扔一半能力）。
  2. 风格串由 8 个标签压到 3 个，腾出的注意力预算全部给画面与表演。
  3. 运镜改写为镜头内的自然动作句，不再堆在句尾当标签（H3 官方规范 base-en.txt:117）。
  4. 每镜写明光线（对齐 h3-fenjing-storyboard 光线库）与动作起止状态，不再是静态快照。
  5. 新增 video_prompt_zh / audio_prompt_zh 中文字段，供人工核对。
  6. 不生成 first_frame_prompt / last_frame_prompt（已确认是 fl2va 旧法遗留、chain 主线从不读取）。

用法：
    python rewrite_ch1_v3.py            # 生成 output/storyboard_ch1_v3.json
"""
import io
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "output")

# 精简风格串：v2 的 8 标签 -> 3 个（style_markers 仍能命中 donghua / cel-shaded / anime style）
STYLE = "Chinese donghua 2D cel-shaded anime style"

# 背面口径外貌串：方源只露背影/过肩时用它覆盖 config 的正面外貌串。
# 实测（2026-10-06 抽帧核验）：过肩镜若注入正面外貌串（"lean narrow face / sharp half-lidded
# eyes / pale skin"），模型会在画面正中另画一个正面人脸，三人同框、构图全乱。背影镜必须只给背面特征。
FY_BACK = ("viewed from behind so that only his back is in frame, the back of his head and his long "
           "straight black hair falling loose down the back of the torn black robe, the plain black "
           "cloth belt knotted at the waist seen from behind, a slender blood-stained back, "
           "no face and no eyes in frame")

# 音色档案（skill 要求：说话人必须有固定音色 + 稳定 ID，情绪只改说话方式不改音色）
VOICE = {
    "正道群雄甲": "the burly middle-aged cultivator in white robes, a loud sharp furious voice, speaking Mandarin Chinese",
    "正道群雄乙": "the young cultivator in blue robes, a cold sneering voice, speaking Mandarin Chinese",
    "正道群雄丙": "the gaunt elderly cultivator in grey robes, a hoarse trembling voice cracking with rage, speaking Mandarin Chinese",
    "正道群雄丁": "the middle-aged female cultivator in dark red robes, a bitter tearful voice rising into a shriek, speaking Mandarin Chinese",
    "古月族长": "the clan leader in white ceremonial robes, an aged solemn low voice, speaking Mandarin Chinese",
    "家老甲": "an elderly clan elder in white robes, a weary nostalgic voice, speaking Mandarin Chinese",
    "家老乙": "an elderly clan elder in white robes, a gentle reminiscent voice, speaking Mandarin Chinese",
    "家老丙": "an elderly clan elder in white robes, a calm thoughtful voice, speaking Mandarin Chinese",
    "家老丁": "an elderly clan elder in white robes, a worried hopeful voice, speaking Mandarin Chinese",
    "家老戊": "an elderly clan elder in white robes, an anxious lowered voice, speaking Mandarin Chinese",
    "家老己": "an elderly clan elder in white robes, a mild tentative voice, speaking Mandarin Chinese",
    "家老庚": "an elderly clan elder in white robes, an eager admiring voice, speaking Mandarin Chinese",
    "家老辛": "an elderly clan elder in white robes, a knowing delighted voice, speaking Mandarin Chinese",
    "方源": "the blood-soaked man in the torn black robe, a low unhurried indifferent voice, speaking Mandarin Chinese",
    "方源少年": "the teenage boy in the black robe, a low calm voice with a faint catch in it, speaking Mandarin Chinese",
    "旁白": "a deep calm male narrator voice, speaking Mandarin Chinese",
}

S = []


def shot(scene_no, shot_type, anchor, length, continuity, en, zh,
         amb, amb_zh, sfx, sfx_zh, ref="full", protagonist=False,
         speaker_key="", line="", anchor_mode=None, speech_mode=None, appearance=None):
    """一镜。en/zh = 画面提示词（中英）；amb/sfx = 音频层（中英）。

    speech_mode 自动判定：旁白走官方画外音句式（并声明画内角色嘴唇闭合），
    其余角色一律画内对白。误判会让画内台词被生成成"嘴唇不动"的旁白。
    appearance：显式覆盖该镜的外貌串（背影镜给 FY_BACK，避免注入正面特征）。
    """
    if anchor_mode is None:
        anchor_mode = "prompt" if (not protagonist and line) else "i2v"
    if speech_mode is None:
        speech_mode = "off-screen voiceover" if speaker_key == "旁白" else "on-screen"
    S.append(dict(
        scene_no=scene_no, shot_type=shot_type, anchor=anchor, length=length,
        continuity=continuity, ref=ref, protagonist=protagonist,
        speaker_key=speaker_key, line=line, anchor_mode=anchor_mode,
        speech_mode=speech_mode, appearance=appearance or "",
        en=en.strip(), zh=zh.strip(),
        amb=amb.strip(), amb_zh=amb_zh.strip(),
        sfx=sfx.strip(), sfx_zh=sfx_zh.strip(),
    ))


# ==================================================================== 场 1
# 青茅山山巅 · 黄昏。正道围攻，方源转身眺望青山落日，放声大笑，悍然自爆。

shot(1, "establishing", "peak_dusk", 141, "new_scene",
     en="[Shot 1] Extreme wide establishing shot from high on the ridge, golden hour warm side "
        "light raking low across the rock as the sun sinks into burning clouds. A bare grey "
        "mountain summit, cracked stone underfoot, a wide dark pool of spilled blood spreading "
        "between the boulders, dry grass flattened and shivering. No one in frame. The camera "
        "drifts slowly to the right along the silent ridge, the last red light sliding across the "
        "wet stone.",
     zh="[镜1] 大远景建立镜头，机位在山脊高处。黄昏暖金侧光低角度扫过岩面，落日正沉入燃烧般的云海。"
        "光秃的灰白山巅，脚下岩面龟裂，巨石之间摊着一大片暗红血泊，枯草被风压伏、簌簌发抖。画面无人。"
        "镜头沿寂静山脊缓慢右移，最后一抹红光在湿石上缓缓滑过。",
     amb="a thin high mountain wind keening across bare rock, dry grass hissing, a hollow echo "
         "rolling off the empty valley",
     amb_zh="尖细的高山风掠过裸露岩面呜咽作响，枯草簌簌，空旷山谷传来空洞回声",
     sfx="one long low gust scraping loose gravel across stone",
     sfx_zh="一阵低沉的长风推动碎石在岩石上摩擦滚过")

shot(1, "dialogue", "peak_dusk", 141, "new_angle",
     en="[Shot 1] The camera sits behind the blood-soaked man in the torn black robe, looking past "
        "his back toward the front: only his back is in frame, his long loose hair and the torn "
        "black robe filling the left third of the picture in shadow. Facing the camera beyond him, "
        "a burly middle-aged cultivator in white robes with a thick grey-streaked beard leans "
        "forward out of the encircling crowd, one arm flung out, jaw tight, eyes blazing. Golden "
        "hour warm side light catches the crowd's shoulders from behind the ridge. The camera "
        "pushes in slowly past the shoulder onto the shouting man's face.",
     zh="[镜2] 镜头位于那位浴血、黑袍残破的男子身后，越过他的背影朝前看：画面里只有他的背面，"
        "披散长发与破烂黑袍占据左侧三分之一并保持在暗部。他之外，一名留着花白浓须的白袍魁梧中年修士"
        "面向镜头从包围人群中探出，身体前倾，一臂挥出，牙关紧咬，双目怒睁。黄昏暖侧光从山脊后方"
        "勾出人群肩线。镜头从他的肩后缓慢向内推近，推向喊话者的脸。",
     amb="mountain wind pressing through the crowd, sleeves and robes snapping",
     amb_zh="高山风穿过人群，衣袖与袍角啪啪作响",
     sfx="a sharp indrawn breath right before the shout, boots grinding on gravel",
     sfx_zh="喊话前猛地吸气，靴底在碎石上碾磨",
     ref="back", protagonist=True, speaker_key="正道群雄甲",
     line="方源，乖乖地交出春秋蝉，我给你个痛快！")

shot(1, "dialogue", "peak_dusk", 209, "new_angle",
     en="[Shot 1] Medium shot of a young cultivator in blue robes with his hair tied in a high topknot striding one step forward out of "
        "the ring, his longsword held low with the tip pointed at the ground, chin lifted, mouth "
        "curled in cold contempt. Crowd silhouettes close in behind him, out of focus. Low golden "
        "side light rims his cheekbone and the blade edge. The camera tracks back slowly ahead of "
        "him at walking pace as he advances, so the ring widens around him.",
     zh="[镜3] 中景。一名将长发束成高髻的蓝袍青年修士从包围圈中向前踏出一步，长剑低垂、剑尖指地，抬着下巴，嘴角挂着"
        "冷酷的轻蔑。身后人群剪影逼近，焦点虚化。低角度暖金侧光勾出他的颧骨与剑刃亮边。他前进时，"
        "镜头以行走速度在他前方缓慢后退跟随，包围圈随之在画面中张开。",
     amb="wind gusting hard over the ridgeline, cloth flapping",
     amb_zh="大风在山脊上呼啸，布料抽打翻飞",
     sfx="a boot striking stone, then the dry tap of a sword tip touching rock",
     sfx_zh="皮靴砸在石上，紧接着剑尖轻叩岩石的干响",
     speaker_key="正道群雄乙",
     line="方老魔，你不要妄图反抗了！今日正道各派联合，就是要踏破你的魔窟。")

shot(1, "dialogue", "peak_dusk", 158, "new_angle",
     en="[Shot 1] Medium close-up of the same young cultivator in blue robes with the high topknot, now snapping his "
        "sword up to point straight out of frame, wrist flicking, teeth bared. Behind him a dozen "
        "armed figures lift their weapons into a ragged line, faces set. Golden side light flares "
        "along the raised blade. The camera pushes in slowly on his face as the words come out.",
     zh="[镜4] 中近景。同一名束高髻的蓝袍青年修士，手腕一抖将长剑上扬、直指画外的方源，露出牙齿。身后十余名"
        "持械身影参差举起兵器，面色冷硬。暖金侧光顺着举起的长剑泛出亮光。台词迸出时，镜头缓慢推近"
        "他的面部。",
     amb="wind, the distant clatter of many weapons shifting",
     amb_zh="风声，远处众多兵器挪动的细碎铿锵",
     sfx="steel rasping as the blade snaps up, a chorus of boots stepping in as one",
     sfx_zh="剑刃上扬的金属摩擦声，众多靴子齐步向内的踏响",
     speaker_key="正道群雄乙",
     line="这里早已布下天罗地网，这次你必定身首异处！")

shot(1, "dialogue", "peak_dusk", 175, "new_angle",
     en="[Shot 1] Medium shot of a gaunt elderly cultivator in grey robes with a long white beard and sunken cheeks at the front of the ring, "
        "both hands shaking as they grip a wooden staff, his thin frame trembling with rage, spittle "
        "at the corner of his lips. The crowd behind him is a dark dense mass. Cold side lighting "
        "with deep shadows cuts across the deep lines of his face. The camera pushes in slowly "
        "toward him.",
     zh="[镜5] 中景。包围圈前方一位留着长白须、双颊深陷的消瘦灰袍老修士，双手抖着握紧木杖，瘦削身体因暴怒而颤抖，唇边溅着"
        "唾沫。身后人群是稠密的暗色块面。冷侧光带着深重阴影切过他脸上深刻的皱纹。镜头缓慢向他推近。",
     amb="wind keening, the massed low murmur of a hostile crowd",
     amb_zh="风声呜咽，敌意人群稠密的低语",
     sfx="a wooden staff tapping stone, a dry rattling breath",
     sfx_zh="木杖点地的轻响，喉咙里干涩的呼哧声",
     speaker_key="正道群雄丙",
     line="方源你个该死的魔头！你为炼春秋蝉，杀了千万人的性命。")

shot(1, "dialogue", "peak_dusk", 141, "new_angle",
     en="[Shot 1] Close-up of the elderly cultivator's face, long white beard and skin drawn tight over the bone, eyes "
        "wet and burning, his jaw working hard to force the words out. A raised trembling hand "
        "comes into the lower frame. Cold side lighting with deep shadow carves his cheek. The "
        "camera holds almost still with only a breath of slow push-in.",
     zh="[镜6] 特写。老修士的脸，长白须，皮肉紧绷贴骨，眼中湿亮而灼人，下颌费力开合把话挤出来。一只颤抖的手"
        "从画面下缘抬起入画。冷侧光与深影凿刻他的面颊。镜头几乎静止，只有一丝极缓的推近。",
     amb="wind, a low hostile crowd rumble underneath",
     amb_zh="风声，底下压着人群的低沉轰鸣",
     sfx="a dry cracked voice straining, cloth rustling at the frame edge",
     sfx_zh="干裂的嗓音用力挤出，画幅边缘的布料摩擦声",
     speaker_key="正道群雄丙",
     line="你犯下滔天罪孽，罪无可恕，罄竹难书！")

shot(1, "dialogue", "peak_dusk", 158, "new_angle",
     en="[Shot 1] Medium shot of a middle-aged female cultivator in dark red robes with her hair bound back in a plain wooden pin, standing at the "
        "far edge of the ring, one hand pressed hard over her own mouth, the other gripping her "
        "sleeve, tears cutting pale tracks through the dust on her face. Cold blue-grey side light, "
        "with the last warm rim still burning behind her. The camera pushes in slowly as grief "
        "turns into hatred.",
     zh="[镜7] 中景。一名以素木簪束发的暗红袍中年女修士立在包围圈远端，一只手死死压住自己的嘴，另一只手攥紧袖口，"
        "泪水在她沾尘的脸上冲出浅痕。冷蓝灰侧光，她身后还燃着最后一点暖色轮廓光。镜头缓慢推近，捕捉"
        "悲恸转为怨恨的过程。",
     amb="wind and damp cold air, the crowd breathing as one",
     amb_zh="风声与湿冷的空气，人群呼吸如一人",
     sfx="stifled sobbing, fabric twisting inside a clenched fist",
     sfx_zh="压抑的啜泣，攥紧的拳头里布料拧绞",
     speaker_key="正道群雄丁",
     line="魔头！三百年前你夺我清白，杀我全家，诛我九族！")

shot(1, "dialogue", "peak_dusk", 158, "new_angle",
     en="[Shot 1] Close-up of the woman's face, hair bound back in the wooden pin, as she tears her hand away from her mouth and "
        "shrieks, eyes wide, tendons standing in her neck, loose hair stuck across her cheek. Cold "
        "side light, the crowd behind her dissolving into darkness. The camera pushes in a little "
        "harder on the scream.",
     zh="[镜8] 特写。以木簪束发的女修士把手从嘴边猛地扯开、尖声嘶吼，双目圆睁，脖颈青筋暴起，散发黏在颊侧。冷侧光，"
        "身后人群溶入黑暗。镜头在嘶吼中略加快推近。",
     amb="wind, the crowd's breath hitching together",
     amb_zh="风声，人群吸气同时一滞",
     sfx="a raw tearing scream, wet gasping for air afterwards",
     sfx_zh="撕裂般的嘶吼，随后湿重的喘息",
     speaker_key="正道群雄丁",
     line="我恨不得吃你肉，喝你的血！今天要你生不如死！")

shot(1, "action", "peak_dusk", 158, "new_angle",
     en="[Shot 1] Medium shot reframing the blood-soaked man in the torn black robe from the front, "
        "as he turns his head slowly and scans the ring of enemies. Hundreds of small wounds weep "
        "dark red through the ruined cloth, and the hem lifts and cracks in the wind like a war "
        "banner. Low warm side light on a face drained pale. The camera arcs slowly around him to "
        "the right, holding his face steady in frame.",
     zh="[镜9] 中景，正面重新取景那位浴血、黑袍残破的男子。他缓慢转头，扫视围成一圈的敌人。数百道细小"
        "伤口在破烂衣料上渗着暗红，衣摆被风掀起、啪啪作响如战旗。低角度暖侧光落在一张失血苍白的脸上。"
        "镜头缓慢绕他向右弧形移动，保持他的面部稳定在画面中。",
     amb="a hard wind hammering across the summit",
     amb_zh="狂风在山巅反复抽打",
     sfx="a blood-stiffened robe snapping and crackling in the gale, blood dripping onto stone",
     sfx_zh="被血浸硬的袍子在狂风中噼啪翻响，血滴滴落岩石",
     protagonist=True)

shot(1, "detail", "peak_dusk", 158, "continue",
     en="[Shot 1] Close-up on his eyes: unhurried and depthless like an old well, blinking once "
        "without a trace of fear. Warm low side light, the red glow of the dying sun caught in the "
        "iris, deep shadow sinking into the sockets. The camera pushes in very slowly; nothing else "
        "in the frame moves.",
     zh="[镜10] 特写他的眼睛：从容而深不见底，如古井一般，只眨了一下，没有一丝恐惧。暖色低侧光，落日"
        "残红映在瞳孔里，阴影沉入眼窝。镜头极缓慢推近，画面中其余一切静止不动。",
     amb="wind thinning into a steady hiss",
     amb_zh="风声退成一条平稳的嘶响",
     sfx="a slow even breath in, and out",
     sfx_zh="一次缓慢均匀的吸气，与呼气",
     protagonist=True, speaker_key="旁白",
     line="方源对局势洞若观火，即便死亡将临，仍面不改色。")

shot(1, "detail", "peak_dusk", 158, "new_angle", ref="back",
     en="[Shot 1] Wide shot from directly behind him, seen from the back: the back of his head, his "
        "long straight black hair falling loose down the back of the black robe, the plain black "
        "belt knotted at his waist seen from behind, his slender blood-stained silhouette alone on "
        "the rock. Far below the ridge the dense crowd of cultivators stands facing him. Cold wind "
        "lifts his hair and the torn hem. The camera pushes in very slowly on his back.",
     zh="[镜11] 背影大远景。从他正后方拍摄：后脑、顺黑袍背部垂落的乌长直发、自背面可见的腰间黑色素布"
        "腰带结，以及独自立在岩石上的浴血瘦削剪影。山脊下方远处，密集的修士人群正面对着他。冷风掀起"
        "他的头发与破烂衣摆。镜头向他的背影极缓慢推近。",
     amb="wind crossing an enormous open height, a faint mass murmur far below",
     amb_zh="风掠过开阔的高处，下方极远处有微弱的人群低语",
     sfx="hair and torn cloth fluttering, then a single drop striking rock",
     sfx_zh="头发与破布猎猎翻动，随后一滴血砸在岩石上",
     protagonist=True)

shot(1, "action", "peak_dusk", 175, "continue", ref="back",
     en="[Shot 1] Still from behind him: he begins to turn, slowly, with his whole body. The camera "
        "stays behind him and travels with the turn, so the crowd below swings across the frame "
        "from the left toward the centre, and his long hair and the torn black robe trail through "
        "the movement. The instant his face comes into view the crowd recoils as one, a dozen "
        "figures stepping back. Warm low side light now catches half of his face.",
     zh="[镜12] 承接背影。他开始慢慢地、带动整个身体转身。镜头保持在他身后并随转身同行，于是下方人群"
        "从画面左侧扫向中央，他的长发与破烂黑袍在转动中拖曳。他的脸转出画面的瞬间，人群齐齐一缩，"
        "十余个身影不由自主后撤一步。暖色低侧光此刻照亮他半张脸。",
     amb="a sharp gust, then the crowd's robes shifting together",
     amb_zh="一阵骤风，随后人群袍角齐齐挪动",
     sfx="many boots scraping backwards on stone in unison, cloth sweeping through the air",
     sfx_zh="众多靴底同时向后磨石，布料划过空气",
     protagonist=True)

shot(1, "dialogue", "peak_dusk", 192, "new_angle",
     en="[Shot 1] Medium close-up of him now facing camera with his back to the ring, the burning "
        "sunset and green ridgelines behind his shoulder. His pale face takes on a faint flush in "
        "the red light. He looks out over the view, then smiles quietly, almost gently, the smile "
        "of a man who has already conceded. Golden hour warm side light, the sun a low disc behind "
        "him. The camera pushes in slowly on his face.",
     zh="[镜13] 中近景。此刻他面向镜头、背对包围圈，肩后是燃烧般的落日与层层青翠山脊。他苍白的脸在"
        "红光里泛起一层淡薄血色。他远眺风景，随后轻轻一笑，近乎温柔——那是一个已经认输的人的微笑。"
        "黄昏暖侧光，落日低悬在他身后。镜头缓慢推近他的面庞。",
     amb="the wind settling to a low steady tone, silence off the ridgeline",
     amb_zh="风声落成低而稳定的长音，山脊之外一片寂静",
     sfx="a soft exhale that turns into a quiet laugh",
     sfx_zh="一声轻缓的呼气，转成极轻的笑",
     protagonist=True, speaker_key="方源",
     line="青山落日，秋月春风。当真是朝如青丝暮成雪，是非成败转头空。")

shot(1, "transition", "flashback", 175, "new_angle",
     en="[Shot 1] A dreamlike flashback: the image slips into a soft hazy memory of a present-day "
        "earthly city at night, blurred warm streaks of window and street light, indistinct far "
        "silhouettes, glowing bokeh, no readable text or signage anywhere. The camera drifts "
        "upward slowly through the haze. Desaturated nostalgic tones, no hard edges in the shot.",
     zh="[镜14] 梦境式闪回：画面滑入一段柔焦模糊的记忆——现代地球城市的夜晚，窗户与街灯晕成暖色光带，"
        "远处人形轮廓依稀，光斑虚化成圆，不出现任何可读文字或招牌。镜头在雾气中缓缓上浮。去饱和的"
        "怀旧色调，画面里没有硬边。",
     amb="a soft hollow room tone with a faint city hum far away",
     amb_zh="柔软空荡的室内底噪，远处有极淡的城市嗡鸣",
     sfx="almost none, the memory is nearly silent",
     sfx_zh="几乎没有音效，这段记忆近乎无声",
     speaker_key="旁白",
     line="他本是地球华夏学子，穿越此界，五百年光阴晃眼即逝。")

shot(1, "detail", "peak_dusk", 175, "new_angle",
     en="[Shot 1] Medium close-up of his face returning from the memory: eyes lowered, then lifting "
        "again with something like relief in them. Blood at the corner of his mouth, hair stuck to "
        "his cheek. The sunset behind him is nearly spent and the light has gone cold and flat. "
        "The camera pushes in slowly.",
     zh="[镜15] 中近景。从记忆中回神的他：眼帘低垂，随后抬起，眼中竟像有一丝释然。嘴角带血，发丝粘在"
        "颊上。身后的落日几乎燃尽，光线转冷、转平。镜头缓慢推近。",
     amb="cold wind rising again over the whole ridge",
     amb_zh="冷风重新在整个山脊上扬起",
     sfx="a slow breath out through the nose",
     sfx_zh="一次从鼻腔里缓缓呼出的气",
     protagonist=True, speaker_key="旁白",
     line="终究是失败了。他并不后悔——所谓魔道，本就举世皆敌。")

shot(1, "action", "peak_dusk", 158, "new_angle",
     en="[Shot 1] Medium shot as he throws his head back and bursts out laughing, chest shaking, "
        "flecks of blood flying from his lips, both arms hanging loose at his sides. Against the "
        "last red sky his whole body reads as a black silhouette with one pale face. The camera "
        "pushes in slowly and stops just short of a close-up.",
     zh="[镜16] 中景。他仰头放声大笑，胸膛震动，血沫从唇边飞散，双臂松垂在身侧。衬着最后一点红天，"
        "他整个人是一道黑色剪影，只有一张苍白的脸清晰。镜头缓慢推近，停在接近特写之前。",
     amb="wind gusting hard, the crowd's murmur spiking behind him",
     amb_zh="狂风大作，身后人群的低语陡然拔高",
     sfx="raw ragged laughter tearing out of a dry throat, boots shifting behind him",
     sfx_zh="粗砺的大笑从干涸喉咙里撕扯而出，身后靴声挪动",
     protagonist=True, speaker_key="方源",
     line="若是刚炼成的春秋蝉有效，来生还是要做邪魔！")

shot(1, "dialogue", "peak_dusk", 124, "new_angle",
     en="[Shot 1] Medium close-up of the burly middle-aged cultivator in white robes with the thick grey-streaked beard, his raised "
        "arm frozen halfway through the gesture, confusion cracking through the fury as he stares "
        "off frame. The men around him go still. Cold flat light against a dead sky. The camera "
        "holds on him without moving.",
     zh="[镜17] 中近景。留着花白浓须的白袍魁梧中年修士，举起的手臂僵在半途，怒意里裂出一丝困惑，怔怔望向画外。周围"
        "的人静了下来。衬着死灰的天，冷平光。镜头固定在他身上不动。",
     amb="wind dropping away to nearly nothing, an uneasy crowd silence",
     amb_zh="风声几乎落尽，人群陷入不安的死寂",
     sfx="a half-spoken breath catching in the throat",
     sfx_zh="半句未出的话卡在喉咙里的一顿",
     speaker_key="正道群雄甲",
     line="老魔，你笑什么？")

shot(1, "dialogue", "peak_dusk", 124, "new_angle",
     en="[Shot 1] Medium shot of the young cultivator in blue robes with the high topknot snapping into a fighting stance, "
        "sword raised across his chest, head turning to shout at the men on both sides of him. The "
        "ring collapses inward a step, weapons coming up together. Cold light. The camera pushes in "
        "quickly on him.",
     zh="[镜18] 中景。束着高髻的蓝袍青年修士猛然进入战斗姿态，长剑横举胸前，扭头对左右的人大喊。包围圈齐刷刷"
        "向内收了一步，兵器同时举起。冷光。镜头快速推近他。",
     amb="wind, the sharp shuffle of a crowd arming itself",
     amb_zh="风声，人群举起兵刃的急促窸窣",
     sfx="dozens of blades clearing scabbards at once, boots planting hard on stone",
     sfx_zh="数十把兵器同时出鞘，靴底重重踏石",
     speaker_key="正道群雄乙",
     line="大家小心，魔头死到临头要反扑了！")

shot(1, "dialogue", "peak_dusk", 124, "new_angle",
     en="[Shot 1] Close-up of the elderly cultivator in grey robes with the long white beard lunging half a step forward, "
        "staff thrust out, spittle flying, veins standing out on his forehead. Cold side light with "
        "deep shadow. The camera pushes in hard on his face.",
     zh="[镜19] 特写。留着长白须的灰袍老修士猛地上前半步，木杖前戳，唾沫横飞，额上青筋暴起。冷侧光带深影。镜头"
        "用力推近他的脸。",
     amb="wind, the ring closing in",
     amb_zh="风声，包围圈收拢",
     sfx="a staff butt cracking down on stone, one raw shout",
     sfx_zh="杖尾重砸石面，一声粗厉的叫喊",
     speaker_key="正道群雄丙",
     line="快快交出春秋蝉！")

shot(1, "action", "peak_dusk", 175, "new_angle",
     en="[Shot 1] Wide shot: he stands alone at the centre as the ring of cultivators surges inward "
        "from every side, weapons converging on him. He does not move. Then a blinding white core "
        "ignites at his chest and blows outward in one expanding shockwave, throwing a wall of dust "
        "and debris down the ridge and flinging the nearest attackers backwards. The camera pushes "
        "in hard through the blast and the frame goes white.",
     zh="[镜20] 大远景。他独自立于中央，包围圈从四面涌来，兵器齐齐指向他。他没有动。随后，一点炽白核心"
        "在他胸口亮起，向外炸开成一道猛烈扩张的冲击波，沿山脊推出一堵尘浪碎石墙，最靠前的攻击者被掀飞。"
        "镜头迎着爆风猛烈推近，画面转成一片炽白。",
     amb="wind roaring to a peak, then a sudden pressure drop into total silence",
     amb_zh="狂风啸到顶点，随后气压骤降，陷入彻底的静默",
     sfx="a deep concussive boom, rock shattering, debris tearing through the air",
     sfx_zh="沉闷巨大的爆响，岩石迸裂，碎块撕裂空气",
     protagonist=True, speaker_key="旁白",
     line="群雄逼迫而来，恰在这时，轰的一声，方源悍然自爆。")


# ==================================================================== 场 2
# 古月山寨 · 深夜 · 春雨。祠堂祭祀大典，礼毕后家老们在走廊议论明日开窍大典。

shot(2, "establishing", "village_night", 141, "new_scene",
     en="[Shot 1] Extreme wide establishing shot of an ancient mountain village at night in spring "
        "drizzle. Tiered dark wooden stilt houses climb the whole hillside from the mid-slope down "
        "to the foot, warm lantern light glowing from hundreds of windows and joining into one "
        "luminous ribbon across the dark mountain. Fine rain drifts through cold blue-grey air. The "
        "camera rises slowly, the ribbon of light lengthening below it.",
     zh="[镜21] 大远景建立镜头。一座古老山寨的春夜细雨。层叠的深色木构高脚吊楼从山腰一路铺到山脚，"
        "数百扇窗透出暖黄灯光，在暗色山体上连成一条明亮光带。细密雨丝在冷蓝灰的空气中飘浮。镜头缓慢"
        "升起，下方的光带随之延伸。",
     amb="fine spring rain hissing softly on eaves and leaves, a low breeze moving through the "
         "valley, a distant village hum",
     amb_zh="春雨细密地落在屋檐与叶片上，山谷里有低缓的风，远处传来山寨的嗡鸣",
     sfx="rainwater dripping from eave tiles at irregular intervals",
     sfx_zh="雨水从檐瓦上不规则地滴落")

shot(2, "establishing", "ancestral_hall", 141, "new_scene",
     en="[Shot 1] Wide establishing shot inside an ancestral hall at night. Rows of dark wooden "
        "ancestral tablets fill a three-tiered black lacquer altar along the back wall, flanked by "
        "bronze censers with thin incense smoke curling upward. A dozen white-robed figures kneel in "
        "a line on the brown-yellow plank floor, seen from behind. Dim practical candle light, "
        "low-key, deep shadow in the rafters. The camera pushes in slowly down the hall.",
     zh="[镜22] 祠堂内大远景建立镜头。后墙的高大黑漆台案分三层，密排着深色木质先祖牌位，两侧立着"
        "赤铜香炉，细长香烟袅袅上升。十余名白袍身影跪在棕黄色地板上，从背后看去排成一行。昏暗的烛火"
        "实景光，低调照明，梁柱间阴影深重。镜头沿祠堂缓慢向内推进。",
     amb="a deep enclosed hall tone, faint incense drifting, soft rain on the roof tiles above",
     amb_zh="祠堂内部深沉的底噪，淡淡香烟浮动，屋顶瓦上落着细雨",
     sfx="a collective rustle of wide robes settling, one wooden plank creaking",
     sfx_zh="宽大祭服齐齐落定的窸窣，一块木板轻响")

shot(2, "dialogue", "ancestral_hall", 260, "continue",
     en="[Shot 1] Medium shot of an elderly clan leader in white ceremonial robes kneeling upright "
        "on the brown-yellow floor, hands pressed palm to palm at his chest, eyes shut, grey at his "
        "temples. Before him a three-tiered black altar holds rows of ancestral tablets, red-gold "
        "candle flames steady on either side, incense smoke rising in a slow column past his face. "
        "Dim practical candle light, low-key. The camera pushes in very slowly on his face.",
     zh="[镜23] 中景。一位白袍祭祀服的年长族长直身跪在棕黄地板上，双手在胸前合十，双目紧闭，两鬓"
        "微霜。他面前是一台三层的黑漆案，层层排着先祖牌位，两侧红金烛火稳稳燃着，香烟绕过他的脸上升"
        "成一柱。昏暗烛火实景光，低调照明。镜头极缓慢推近他的脸。",
     amb="a deep quiet hall, incense smoke drifting, fine rain on the roof tiles, one candle guttering",
     amb_zh="幽深安静的祠堂，香烟浮动，屋顶细雨，一支烛火轻轻摇曳",
     sfx="robes shifting against the floor, one slow breath",
     sfx_zh="祭服在地板上挪动，一次缓慢的呼吸",
     speaker_key="古月族长",
     line="列祖列宗保佑，希望此次开窍大典中能多多涌现出资质优秀的少年，为家族增添新血和希望！")

shot(2, "action", "ancestral_hall", 141, "continue",
     en="[Shot 1] Medium shot from behind and to the side: the clan leader bends forward, lays both "
        "palms flat, and presses his forehead to the floor. In the same motion the whole line of "
        "white-robed elders behind him bows as one, foreheads meeting the boards. Dim candle light, "
        "low-key. The camera holds still.",
     zh="[镜24] 中景，自后方偏侧拍摄。族长俯身，双掌平摊贴地，额头叩上地板。同一个动作里，身后整排"
        "白袍家老如一人般伏身，额头齐齐触板。昏暗烛光，低调照明。镜头静止不动。",
     amb="a deep enclosed hall tone, rain steady on the roof above",
     amb_zh="祠堂内部深沉底噪，雨声在上方屋顶持续",
     sfx="a soft hollow thud of forehead on wood, then a dozen more almost together, robes brushing "
         "the floorboards",
     sfx_zh="额头碰木的轻闷一声，随后十余声几乎同时响起，祭服擦过地板",
     protagonist=False)

shot(2, "dialogue", "corridor", 158, "new_scene",
     en="[Shot 1] Medium shot in a long wooden corridor at night: three or four white-robed elders "
        "walk slowly away from the hall doors, shoulders loosening, one of them letting out a long "
        "breath. Rows of matching orange-yellow paper lanterns hang evenly overhead, weathered dark "
        "timber pillars on both sides, cold blue-grey night beyond with drizzle falling into the wet "
        "courtyard. Warm pools of lantern light. The camera tracks alongside them at walking pace.",
     zh="[镜25] 中景。夜里的长木走廊：三四个白袍家老从祠堂门口缓步走出，肩背松下来，其中一个长长"
        "吐出一口气。头顶橙黄纸灯笼成排均匀悬挂，两侧是风化的深色木柱，廊外是冷蓝灰夜色，细雨落进湿漉"
        "庭院。灯笼光投下暖色光斑。镜头以行走速度与他们并行跟拍。",
     amb="rain falling steadily into a stone courtyard, water running off eave tiles, a soft wet "
         "breeze through the corridor",
     amb_zh="雨持续落进石铺庭院，水从檐瓦流下，湿风穿过走廊",
     sfx="slow footsteps on wooden floorboards, wide sleeves brushing past one another",
     sfx_zh="木地板上缓慢的脚步，宽袖彼此相擦",
     speaker_key="家老甲",
     line="时间过的真是太快了，一眨眼，一年就都过去了。")

shot(2, "dialogue", "corridor", 192, "new_angle",
     en="[Shot 1] Medium shot of an elderly elder in white robes pausing mid-step and half turning "
        "toward the man beside him, one hand lifting slightly as though setting something down on a "
        "table that is not there. Lantern light from above and to the left, cold blue night filling "
        "the gaps between the lights. The camera pushes in slowly as he speaks.",
     zh="[镜26] 中景。一位白袍家老在行走中停住半步，半转向身旁的人，一只手微微抬起，像是在往一张"
        "并不存在的桌上放东西。灯笼光自上方偏左照下，冷蓝夜色填满灯与灯之间的空隙。他开口时镜头缓慢"
        "推近。",
     amb="rain on the eaves, a low draught moving down the corridor",
     amb_zh="雨打屋檐，低缓的气流沿走廊流动",
     sfx="a footstep halting, fabric settling around the legs",
     sfx_zh="脚步停住，衣料在腿边落定",
     speaker_key="家老乙",
     line="上一届的开窍大典就像是昨天发生的一样，依旧历历在目呢。")

shot(2, "dialogue", "corridor", 226, "new_angle",
     en="[Shot 1] Medium wide shot down the length of the corridor: four elders walking in a loose "
        "line, one of them gesturing out toward the courtyard with an open palm, another nodding "
        "slowly. The lanterns recede into the distance as a chain of warm dots. The camera leads "
        "them, retreating slowly down the corridor.",
     zh="[镜27] 中远景，顺着走廊纵深向外拍。四位家老松散地排成一行走着，其中一人张开手掌朝廊外"
        "庭院示意，另一人缓缓点头。灯笼向远处退去，连成一串暖色亮点。镜头在他们前方引路，沿走廊"
        "缓慢后退。",
     amb="rain steady on the tiles, water dripping into the courtyard, faint night insects",
     amb_zh="雨点持续落在瓦上，水滴滴入庭院，远处有微弱的夜虫声",
     sfx="measured footsteps on plank floor, robes swaying against each other",
     sfx_zh="均匀的脚步踩在木地板上，袍角彼此轻摆相碰",
     speaker_key="家老丙",
     line="明日就是一年一度的开窍大典了，不知道今年会涌现出什么样的家族新血呢？")

shot(2, "dialogue", "corridor", 243, "new_angle",
     en="[Shot 1] Medium close-up of a heavyset elderly elder in white robes stopping to look up at "
        "the lanterns, a long sigh escaping him, the skin around his eyes slack with weariness. Two "
        "other elders stand just behind him, out of focus. Warm lantern light from above, cold blue "
        "filling the corridor behind. The camera pushes in slowly.",
     zh="[镜28] 中近景。一位身形厚实的白袍家老停下来，抬头望向灯笼，长长叹出一口气，眼周皮肤因"
        "疲惫而松弛。另两位家老站在他身后不远处，虚焦。暖色灯光自上照下，身后走廊填着冷蓝。镜头"
        "缓慢推近。",
     amb="rain and a soft draught in the corridor, water dripping somewhere behind",
     amb_zh="雨声与走廊里柔软的气流，身后某处有水滴声",
     sfx="a long tired sigh, floorboards easing under his weight",
     sfx_zh="一声疲惫的长叹，地板在他体重下轻响",
     speaker_key="家老丁",
     line="唉，希望有甲等资质的少年出现。我们古月一族已经有三年没有这样的天才出现了。")

shot(2, "dialogue", "corridor", 243, "new_angle",
     en="[Shot 1] Medium shot of a lean elderly elder mid-sentence, one hand raised at chest height "
        "ticking off a point, his expression souring as he names something unpleasant. The elder "
        "beside him turns his head to listen, brow lowering. Warm lantern light from the left, cool "
        "night behind. The camera pushes in slowly.",
     zh="[镜29] 中景。一位清瘦的白袍家老正说到一半，一只手抬在胸口高度点着要点，表情在提到不快"
        "之事时阴沉下来。身旁的家老转头听着，眉峰压低。暖色灯笼光自左侧照来，背后是冷夜。镜头缓慢"
        "推近。",
     amb="rain on the roof, a low wind moving through the corridor",
     amb_zh="雨打在屋顶，低风穿过走廊",
     sfx="cloth shifting as a hand rises, a low murmur from the listening elder",
     sfx_zh="抬手时布料挪动，旁听家老的低低一声应和",
     speaker_key="家老戊",
     line="不错，白家寨、熊家寨这些年都有天才涌现。尤其是白家的白凝冰，天资真是恐怖。")

shot(2, "dialogue", "corridor", 192, "new_angle",
     en="[Shot 1] Medium shot of three elders falling quiet at once, faces turning inward with a "
        "shared frown, eyes dropping to the floor. The corridor behind them is empty and cold blue, "
        "the lantern line stretching away. The camera pushes in very slowly on the group.",
     zh="[镜30] 中景。三位家老同时安静下来，脸转向内侧，露出相同的愁容，目光落到地板上。身后走廊"
        "空荡冷蓝，灯笼串向远处延伸。镜头极缓慢推近这一小群。",
     amb="rain steady, a draught moving the lantern flames",
     amb_zh="雨声持续，气流吹动灯笼火焰",
     sfx="three shallow breaths at once, no footsteps",
     sfx_zh="三个人同时变浅的呼吸，没有脚步",
     speaker_key="旁白",
     line="提及白凝冰，众家老脸上浮现忧色——此子两年便修到三转。")

shot(2, "dialogue", "corridor", 158, "new_angle",
     en="[Shot 1] Medium close-up of an elder raising his head again, a lighter note coming into "
        "his face as he turns back to the group behind him. Lantern light warms one side of his "
        "face, the other side falling into night blue. The camera pushes in slowly.",
     zh="[镜31] 中近景。一位家老重新抬起头，转向身后众人，脸上浮起一丝轻快。灯笼光暖着他半边脸，"
        "另一半沉入夜蓝。镜头缓慢推近。",
     amb="rain, and a faint easing in the corridor air",
     amb_zh="雨声，走廊里的空气似乎稍稍松动",
     sfx="fabric shifting, a short intake of breath before speaking",
     sfx_zh="布料挪动，开口前短促的一吸",
     speaker_key="家老己",
     line="不过今年参加开窍大典的少年里，也不是没有希望。")

shot(2, "dialogue", "corridor", 192, "new_angle",
     en="[Shot 1] Medium shot of a wiry elder striding half a step forward into the middle of the "
        "group, both hands rising to shape something in the air, eyes brightening. The other elders "
        "turn toward him. Warm lantern light from directly overhead, cold blue beyond. The camera "
        "pushes in slowly.",
     zh="[镜32] 中景。一位精瘦家老向前半步迈到人群中间，双手抬起在空中比划出一个形状，眼睛亮起来。"
        "其他家老转向他。暖色灯笼光自正上方照下，外围是冷蓝。镜头缓慢推近。",
     amb="rain on the tiles, lantern flames trembling in a draught",
     amb_zh="雨点在瓦上，气流中灯笼火焰微微发颤",
     sfx="a quick step on boards, sleeves lifting through the air",
     sfx_zh="木板上一记快步，衣袖划过空气",
     speaker_key="家老庚",
     line="不错，方之一脉出现了一个天才少年。三月能言，四月能走。")

shot(2, "dialogue", "corridor", 209, "new_angle",
     en="[Shot 1] Medium close-up of the same wiry elder, now counting off on his fingers, voice "
        "rising with relish, then his face sobering on the last phrase as he lowers his hand. Warm "
        "lantern light on his cheekbones, cold blue night behind. The camera pushes in slowly and "
        "then holds.",
     zh="[镜33] 中近景。同一位精瘦家老，此刻扳着手指一件件数着，嗓音越说越起劲，说到最后一句时"
        "表情沉静下来，把手放下。暖色灯笼光落在他的颧骨上，背后是冷蓝夜色。镜头缓慢推近后稳住。",
     amb="rain steady, the corridor draught rising slightly",
     amb_zh="雨声平稳，走廊气流略略抬头",
     sfx="a hand sliding down against a sleeve, one short exhaled breath",
     sfx_zh="手沿衣袖滑落，一次短促的吐气",
     speaker_key="家老庚",
     line="五岁便能作诗诵词，聪慧异常，可惜父母死的早，如今被舅父舅母抚养。")

shot(2, "dialogue", "corridor", 124, "new_angle",
     en="[Shot 1] Medium close-up of an elder with a narrow face nodding once with quiet "
        "satisfaction, one corner of his mouth pulling up. Lantern light from the left, cold blue "
        "filling the right of frame. The camera pushes in slowly.",
     zh="[镜34] 中近景。一位脸型狭长的家老，带着笃定的满意点了点头，一边嘴角挑起。灯笼光自左侧"
        "照来，画面右侧填着冷蓝。镜头缓慢推近。",
     amb="rain on the eaves, a soft hum through the corridor",
     amb_zh="雨打屋檐，走廊里一片柔和的嗡响",
     sfx="a short knowing hum low in the throat",
     sfx_zh="喉咙里一声短促的了然低哼",
     speaker_key="家老辛",
     line="嗯，这是有早智的，而且有大志向。")

shot(2, "dialogue", "corridor", 192, "new_angle",
     en="[Shot 1] Medium shot of the narrow-faced elder reciting with his eyes half closed, one "
        "hand lifting as though reading something aloud from memory, the others exchanging glances "
        "behind him. Warm lantern light above, cold blue behind. The camera pushes in slowly.",
     zh="[镜35] 中景。狭长脸的家老半闭着眼背诵，一只手抬起，像是在凭记忆朗读什么，身后众人交换"
        "眼神。暖色灯笼光在上，背后冷蓝。镜头缓慢推近。",
     amb="rain steady, a low draft passing the pillars",
     amb_zh="雨声持续，低气流擦过廊柱",
     sfx="a rhythmic cadence murmured under the breath, floorboards creaking",
     sfx_zh="压在气声下的一段有节奏的吟诵，地板吱呀作响",
     speaker_key="家老辛",
     line="他作的《将进酒》《咏梅》《江城子》，我也听过，真是天才！")


# ==================================================================== 场 3
# 祠堂外走廊 → 阁楼三层窗边。族长听完议论，立规矩，散场后独望满寨灯火。

shot(3, "transition", "corridor", 141, "new_scene",
     en="[Shot 1] Medium shot at the end of the corridor: the clan leader steps out through the hall "
        "doors behind the others and draws the double doors shut with both hands, head tilted "
        "slightly as he listens to the murmur drifting back down the corridor. Warm lantern light "
        "on his white robes, cold blue night on both sides. The camera pushes in slowly on his face "
        "as he listens.",
     zh="[镜36] 中景。走廊尽头：族长从众人身后走出祠堂大门，双手合上两扇门，头微微偏着，听着沿走廊"
        "飘回来的议论声。暖色灯笼光照在他的白袍上，两侧是冷蓝夜色。他侧耳倾听时，镜头缓慢推近他的脸。",
     amb="rain beyond the doors, water running off the tiles, a low murmur of voices further down "
         "the corridor",
     amb_zh="门外雨声，水从瓦上流下，走廊更远处有一片低低的人声",
     sfx="two heavy wooden doors closing with a soft boom, the latch settling",
     sfx_zh="两扇厚木门合上的一声闷响，门闩落定")

shot(3, "dialogue", "corridor", 141, "new_angle",
     en="[Shot 1] Medium close-up of the clan leader standing still by the closed doors, eyes "
        "narrowing slightly in thought, chin dipping once as he works something out. Lantern light "
        "from the left, cold blue to the right, his white ceremonial robes bright against the dark "
        "timber. The camera pushes in very slowly.",
     zh="[镜37] 中近景。族长静静立在合拢的门边，双眼因思量而微微眯起，下巴轻轻一点，像想通了什么。"
        "灯笼光自左侧照来，右侧是冷蓝，白祭服在深色木构前格外醒目。镜头极缓慢推近。",
     amb="rain steady beyond the doors, a low draught through the corridor",
     amb_zh="门外雨声平稳，低气流穿过走廊",
     sfx="a quiet breath out through the nose",
     sfx_zh="一声从鼻腔里悄悄呼出的气",
     speaker_key="旁白",
     line="族长顿时明白，家老们议论的是古月方源。")

shot(3, "dialogue", "corridor", 192, "new_angle",
     en="[Shot 1] Close-up on the clan leader's mouth and eyes as one corner of his mouth lifts "
        "into a small private smile, then he schools his face back to calm. Lantern light catches "
        "the fine lines at the corner of his eye, cold blue night behind. The camera holds nearly "
        "still with only a slow push-in.",
     zh="[镜38] 特写，取族长的嘴与眼。他的嘴角微微翘起，浮出一个只属于自己的微笑，随即又把表情"
        "收回平静。灯笼光照出他眼角的细纹，背后是冷蓝夜色。镜头几乎静止，只极缓慢推近。",
     amb="rain on the eaves, faint distant voices",
     amb_zh="雨打屋檐，远处极淡的人声",
     sfx="a soft exhale, then a deliberate clearing of the throat",
     sfx_zh="轻轻呼气，随后刻意地清了一下嗓子",
     speaker_key="旁白",
     line="若他测出甲等资质，未必不能与白凝冰抗衡。族长嘴角微翘。")

shot(3, "dialogue", "corridor", 226, "new_angle",
     en="[Shot 1] Medium shot of the clan leader turning back to face the group of white-robed "
        "elders, both hands folded loosely in front of him, his expression settling into the "
        "authority of a clan head. The elders stand in a loose arc facing him with lanterns between "
        "them. Warm lantern light from above, cold blue at the corridor mouth. The camera pushes in "
        "slowly.",
     zh="[镜39] 中景。族长转回身面对这群白袍家老，双手松松交叠在身前，神情落定为一族之长的威严。"
        "家老们松散地围成半弧面对他，灯笼夹在人之间。暖色灯笼光自上方照下，走廊出口处是冷蓝。"
        "镜头缓慢推近。",
     amb="rain steady, a hush coming over the corridor",
     amb_zh="雨声平稳，走廊上安静下来",
     sfx="robes shifting as the group settles, one throat cleared",
     sfx_zh="众人站定时衣料挪动，一声清嗓",
     speaker_key="古月族长",
     line="诸位，时候不早了，为了明日的开窍大殿，今晚请务必好好休息，保养精神。")

shot(3, "dialogue", "corridor", 124, "new_angle",
     en="[Shot 1] Medium shot of the elders' faces in a row, all of them going rigid for a beat, "
        "then eyes sliding sideways to check one another, several mouths pressing flat. Warm lantern "
        "light from above, cold blue in the gaps. The camera holds still.",
     zh="[镜40] 中景。一排家老的脸，齐齐僵了一瞬，随后眼珠向旁边滑去互相打量，好几张嘴抿平。"
        "暖色灯笼光自上照下，间隙里是冷蓝。镜头静止不动。",
     amb="rain, and the corridor holding its breath",
     amb_zh="雨声，走廊像屏住了呼吸",
     sfx="a small collective intake of breath, fabric tightening",
     sfx_zh="众人齐齐一吸气，衣料绷紧",
     speaker_key="旁白",
     line="家老们微微一怔，目光里藏着警惕。")

shot(3, "dialogue", "corridor", 158, "new_angle",
     en="[Shot 1] Medium wide shot of the group as the elders begin measuring each other with their "
        "eyes, shoulders turning away one by one, hands folding and refolding. The lantern line runs "
        "off into the dark behind them. Warm light overhead, cold blue beyond. The camera pushes in "
        "slowly.",
     zh="[镜41] 中远景。这一群家老开始用眼神彼此打量，肩膀一个个转开，手反复交叠又松开。灯笼串"
        "在他们身后伸进黑暗。暖光在上，外围冷蓝。镜头缓慢推近。",
     amb="rain steady, low wind moving through the pillars",
     amb_zh="雨声持续，低风穿过廊柱",
     sfx="sleeves and hems shifting restlessly, floorboards creaking under shifting weight",
     sfx_zh="衣袖袍角不安地挪动，地板在重心变换下吱呀作响",
     speaker_key="旁白",
     line="每年为争夺天才后辈，家老们都争得头破血流。")

shot(3, "dialogue", "corridor", 124, "new_angle",
     en="[Shot 1] Medium close-up of the clan leader lifting one hand palm-out, a small gesture "
        "that stops every other movement in the corridor. His face stays calm and level. Warm "
        "lantern light on his hand and cheek. The camera pushes in slowly.",
     zh="[镜42] 中近景。族长抬起一只手，掌心朝外，一个不大的动作便让走廊里所有其他动作都停了下来。"
        "他面容平静而持平。暖色灯笼光落在他的手与颊上。镜头缓慢推近。",
     amb="rain, and the corridor going completely still",
     amb_zh="雨声，走廊彻底静下来",
     sfx="fabric falling silent, one hand stopping mid-gesture",
     sfx_zh="布料静住，一只手停在半途",
     speaker_key="古月族长",
     line="不过，丑话先说在前头。")

shot(3, "dialogue", "corridor", 226, "new_angle",
     en="[Shot 1] Medium close-up of the clan leader speaking with deliberate weight, both hands "
        "folded together in front of his chest, his gaze travelling slowly from one elder to the "
        "next. Lantern light from above and left, cold blue filling the corridor behind him. The "
        "camera pushes in slowly and then holds on his eyes.",
     zh="[镜43] 中近景。族长带着刻意的分量说话，双手已在胸前交叠，目光缓慢地从一位家老移到下一位。"
        "灯笼光自上偏左照下，身后走廊填满冷蓝。镜头缓慢推近，最后停在他的眼睛上。",
     amb="rain on the roof tiles, a draught worrying the lantern flames",
     amb_zh="雨点落在屋顶瓦上，气流把灯笼火焰吹得轻晃",
     sfx="a level voice carrying the length of the corridor, robes shifting as heads turn",
     sfx_zh="平稳的嗓音贯穿整条走廊，众人转头时衣料摩擦",
     speaker_key="古月族长",
     line="争要堂堂正正的争，不可以动用阴谋手段，损害家族的团结。诸位请牢记在心！")

shot(3, "dialogue", "corridor", 124, "new_angle",
     en="[Shot 1] Medium shot of an elderly elder bowing his head and cupping one hand over the "
        "other in front of his chest, a quick placating gesture. His neighbour copies him half a "
        "beat late. Warm lantern light from the left. The camera holds still.",
     zh="[镜44] 中景。一位家老低下头，一手覆在另一手上作揖，是个迅速安抚的姿态。旁边的人慢了半拍"
        "跟着学。暖色灯笼光自左侧照来。镜头静止不动。",
     amb="rain, a soft rustle moving through the group",
     amb_zh="雨声，人群里一阵轻微的窸窣",
     sfx="two quick bows, sleeves brushing together",
     sfx_zh="两次急促的躬身，衣袖彼此相擦",
     speaker_key="家老甲",
     line="不敢，不敢。")

shot(3, "dialogue", "corridor", 124, "new_angle",
     en="[Shot 1] Medium close-up of another elder nodding firmly, one hand pressed flat over his "
        "own chest as if swearing to something. Lantern light warms his face, cold blue night "
        "behind. The camera pushes in slowly.",
     zh="[镜45] 中近景。另一位家老用力点头，一只手平压在胸口，像在对什么立誓。灯笼光暖着他的脸，"
        "背后是冷蓝夜色。镜头缓慢推近。",
     amb="rain on the eaves, a low draught",
     amb_zh="雨打屋檐，低缓的气流",
     sfx="a firm nod, fabric pressed flat under a hand",
     sfx_zh="一记用力的点头，布料被手掌压平",
     speaker_key="家老乙",
     line="一定牢记在心。")

shot(3, "dialogue", "corridor", 124, "new_angle",
     en="[Shot 1] Medium shot of an elder already turning to leave, one hand raised briefly in "
        "farewell toward the clan leader, the first step of a general dispersal behind him. Lantern "
        "light from above, the corridor mouth dark and cold. The camera holds still as he moves off.",
     zh="[镜46] 中景。一位家老已经转身要走，一只手朝族长匆匆一抬作别，身后众人正要散开的第一个"
        "动作已经起势。灯笼光在上，走廊出口暗而冷。他迈步离开时镜头静止不动。",
     amb="rain outside, several pairs of feet beginning to move",
     amb_zh="廊外雨声，好几双脚开始挪动",
     sfx="wooden floorboards taking many steps at once, a brief polite murmur",
     sfx_zh="木地板同时接住许多脚步，一片简短的客套低语",
     speaker_key="家老丙",
     line="这就告辞了，族长大人请留步。")

shot(3, "transition", "corridor", 141, "new_angle",
     en="[Shot 1] Wide shot of the corridor emptying: the elders file away in different directions "
        "and dissolve into the dark at both ends, leaving the long wooden corridor completely still, "
        "lanterns burning evenly in a row, drizzle visible beyond the railing. Warm lantern pools, "
        "cold blue beyond. The camera retreats slowly down the empty corridor.",
     zh="[镜47] 大远景。走廊渐渐空去：家老们朝不同方向散去，在两端溶进黑暗，只留下长木走廊彻底"
        "静止，灯笼成排均匀燃烧，栏杆外可见细雨。暖色灯笼光斑，外围冷蓝。镜头沿空走廊缓慢后退。",
     amb="rain falling steadily, water dripping from the eaves, the corridor now nearly silent",
     amb_zh="雨持续落下，水从檐口滴落，走廊已近乎无声",
     sfx="the last soft footsteps fading out, one lantern wick ticking",
     sfx_zh="最后几声轻步远去，一盏灯笼的灯芯轻响",
     speaker_key="旁白",
     line="家老们各怀心思散去，长长的走廊冷清下来。")

shot(3, "dialogue", "window_view", 175, "new_scene",
     en="[Shot 1] Medium shot from behind the clan leader as he walks to the window on the third "
        "floor and stands looking out, one hand resting on the wooden sill. Beyond him the window "
        "opens onto a broad vista of the night village, scattered warm window lights spread across "
        "the dark hillside, fine rain streaking the air. Warm lantern light behind him, cool blue "
        "night through the window. The camera pushes in slowly past his shoulder.",
     zh="[镜48] 中景，从族长背后拍。他走到三层窗前站定远望，一只手搭在木质窗棂上。他之外，窗户"
        "敞开一大片夜景——散落的暖色窗光铺满暗色山坡，细雨中空气被拉出丝丝斜痕。他身后是暖色灯笼光，"
        "窗外是冷蓝夜色。镜头从他肩后缓慢向内推近。",
     amb="rain hissing across a wide valley, a fresh wet wind coming through the window, distant "
         "village sounds",
     amb_zh="雨声在开阔山谷里作响，湿润的新风从窗口灌入，远处有山寨的声响",
     sfx="a wooden window frame creaking slightly, robes lifting in the draft",
     sfx_zh="木窗框轻轻吱呀，袍角在气流中抬起",
     speaker_key="旁白",
     line="族长走到窗前，第三层阁楼上，大半个古月山寨尽收眼底。")

shot(3, "dialogue", "window_view", 124, "new_angle",
     en="[Shot 1] Close-up of the clan leader's face turned to the window, the small warm lights of "
        "the village reflected as dots in his eyes, his expression open and unguarded for the first "
        "time, ending on a long slow exhalation. Cool blue night light on his skin with a warm edge "
        "from the lantern behind. The camera holds still.",
     zh="[镜49] 特写。族长的脸转向窗外，山寨点点暖灯倒映在他眼中，神情第一次毫无防备地舒展，最后"
        "落在一口悠长的呼气上。冷蓝夜色打在他皮肤上，身后灯笼补出一道暖边。镜头静止不动。",
     amb="rain across the valley, the window draught steady",
     amb_zh="雨落在山谷各处，窗口的气流平稳",
     sfx="a long slow exhale, rain tapping the sill",
     sfx_zh="一声悠长的呼气，雨点敲在窗台上",
     speaker_key="古月族长",
     line="这就是家族未来的希望啊。")


# ==================================================================== 场 4
# 方源房间 · 深夜 · 细雨。重生后的少年方源在窗边确认自己回到了五百年前。

shot(4, "establishing", "fangyuan_room", 141, "new_scene",
     en="[Shot 1] Medium wide establishing shot inside a simple old wooden room at night. A young "
        "man in a plain black robe stands at the open paper-lattice window with his back "
        "three-quarters to camera, letting the drizzle and the cold wind fall on him. A single oil "
        "lamp burns on a small wooden desk behind him, throwing a warm flickering pool across "
        "weathered wood and clay walls. His long black hair stirs in the draught. The camera pushes "
        "in slowly from behind him toward the window.",
     zh="[镜50] 中远景建立镜头。夜里一间简朴的旧木屋。一名穿素黑长袍的少年站在敞开的纸格窗前，背身"
        "四分之三朝镜头，任凭细雨与冷风落在身上。身后小木桌上燃着一盏油灯，在风化的木料与土墙上投出"
        "摇曳的暖色光斑。他的乌黑长发在气流中微动。镜头从他身后缓慢向窗口推近。",
     amb="rain on the window lattice and the roof, a thin wet wind coming through the opening, one "
         "oil lamp guttering",
     amb_zh="雨落在窗格与屋顶上，湿润的细风从窗口灌入，一盏油灯轻摇",
     sfx="rain tapping the paper window, cloth moving in the draught",
     sfx_zh="雨点轻敲窗纸，布料在气流中拂动",
     protagonist=True)

shot(4, "dialogue", "fangyuan_room", 158, "new_angle",
     en="[Shot 1] Close-up on his eyes in profile against the window light: clear and bright, fixed "
        "calmly on the scattered night lights of the village beyond the lattice. Warm lamplight "
        "rims one side of his face, cool blue night the other. Rain streaks the window. The camera "
        "pushes in very slowly.",
     zh="[镜51] 特写他的眼睛（侧脸衬着窗光）：清亮，平静地定在格窗外山寨散落的夜灯上。暖色灯光勾出"
        "他半边脸的轮廓，另一半是冷蓝夜色。雨痕划过窗面。镜头极缓慢推近。",
     amb="rain steady against the window, faint distant village sounds",
     amb_zh="雨持续打在窗上，远处有极淡的山寨声响",
     sfx="a slow quiet breath",
     sfx_zh="一次缓慢安静的呼吸",
     protagonist=True, speaker_key="旁白",
     line="同样有一双清亮的眸子，静静望着寨中深夜的灯火。")

shot(4, "dialogue", "fangyuan_room", 175, "new_angle",
     en="[Shot 1] Medium close-up of the young man turning his face from the window toward camera, "
        "disbelief and a strange calm mixing on his features as he speaks, rain on his cheeks and "
        "hair. Warm lamp light from behind-left, cold blue on his face from the window. The camera "
        "pushes in slowly and holds.",
     zh="[镜52] 中近景。少年把脸从窗口转向镜头，五官上惊疑与一种奇异的镇定交叠，边说话边任由雨落在"
        "脸颊与发上。暖色灯光自左后方来，窗口方向的冷蓝打在他脸上。镜头缓慢推近后稳住。",
     amb="rain on the lattice, a wet draught moving through the room",
     amb_zh="雨打窗格，湿润的气流在屋内游走",
     sfx="a breath caught halfway out, rain shaken from his hair",
     sfx_zh="一口气卡在半途，头发上的雨水被抖落",
     protagonist=True, speaker_key="方源少年",
     line="古月山寨，这是五百年前？！春秋蝉果真起作用了……")

shot(4, "dialogue", "fangyuan_room", 175, "new_angle",
     en="[Shot 1] Insert shot: the oil lamp on the wooden desk, its flame bending in the draught, "
        "the plain clay wall behind it carrying a huge soft shadow that sways. Everything below the "
        "desk is out of focus. Warm practical light, low-key. The camera pushes in very slowly on "
        "the flame.",
     zh="[镜53] 插入镜头。木桌上的油灯，火焰在气流中偏斜，身后素土墙上投下一大片柔软游移的影子。"
        "桌面以下的一切都在焦外。暖色实景光，低调照明。镜头极缓慢推近火焰。",
     amb="rain on the roof and the window, a low draught in the room",
     amb_zh="雨落在屋顶与窗上，屋内气流低缓",
     sfx="the oil lamp wick ticking, faint rain dripping from the eave outside",
     sfx_zh="油灯灯芯轻响，屋外檐口有细微滴水",
     speaker_key="旁白",
     line="春秋蝉能逆转时光，在十大奇蛊中名列第七——即重生。")

shot(4, "action", "fangyuan_room", 124, "new_angle",
     en="[Shot 1] Medium shot of the young man looking down at his own open palm, then closing the "
        "hand slowly into a fist and pressing it once, testing the strength in it. Rain rolls off "
        "his sleeve, wet hair hanging forward. Warm lamplight from the left across his hand, cold "
        "blue from the window. The camera pushes in slowly, holding the hand and the face together.",
     zh="[镜54] 中景。少年低头看着自己摊开的手掌，随后缓缓收拢成拳，再用力按了一下，试探其中的力量。"
        "雨水顺袖口滚落，湿发垂在身前。暖色灯光自左侧扫过他的手，窗口方向是冷蓝。镜头缓慢推近，"
        "将手与脸一并收入。",
     amb="rain steady, a thin wind through the window",
     amb_zh="雨声持续，细风穿过窗户",
     sfx="skin and tendon tightening as the fist closes, water dripping from a sleeve",
     sfx_zh="握拳时皮肉与筋骨收紧，袖口有水珠滴落",
     protagonist=True, speaker_key="方源少年",
     line="利用春秋蝉重生了，回到了五百年前！")

shot(4, "detail", "fangyuan_room", 141, "continue",
     en="[Shot 1] Extreme close-up on the young man's pale hand: slim and young, unmarked by any "
        "scar, the fingers curling deliberately in against the palm, a few drops of rain running "
        "through the creases. Warm lamplight rakes across the knuckles, deep shadow beneath. The "
        "camera pushes in very slowly.",
     zh="[镜55] 特写，取少年苍白的手：纤细年轻，没有任何疤痕，手指一节节刻意地向掌心收拢，几滴雨"
        "顺着掌纹流过。暖色灯光斜扫过指节，下方是深影。镜头极缓慢推近。",
     amb="rain against the window, a hush inside the room",
     amb_zh="雨打在窗上，屋里一片静默",
     sfx="a faint creak of skin under pressure, one drop falling onto wood",
     sfx_zh="受力时皮肤发出的细微声响，一滴水落上木板",
     protagonist=True, speaker_key="旁白",
     line="他定定看着自己年轻苍白的手掌，缓缓握紧。")

shot(4, "dialogue", "fangyuan_room", 124, "new_angle",
     en="[Shot 1] Medium close-up of the young man with his eyes closed, face tilted slightly "
        "toward the rain, then opening them again and letting out a long breath that softens into a "
        "sigh, as though setting down something very heavy. Warm lamplight on one cheek, cold blue "
        "on the other. The camera pushes in slowly.",
     zh="[镜56] 中近景。少年闭着眼，脸微微朝向雨的方向，随后重新睁眼，长长吐出一口气，那口气化成"
        "一声轻叹，像把极沉重的东西放了下来。暖色灯光落在半边脸颊，另一半是冷蓝。镜头缓慢推近。",
     amb="rain steady on the lattice, a low wind behind it",
     amb_zh="雨点稳定地落在窗格上，背后有低声的风",
     sfx="a long exhale that softens into a sigh",
     sfx_zh="一口长气徐徐吐出，最终化成一声叹息",
     protagonist=True, speaker_key="方源少年",
     line="五百年的经历，真像是个梦啊。")

shot(4, "detail", "fangyuan_room", 124, "new_angle",
     en="[Shot 1] Close-up on the young man's face in the final beat: eyes open and completely "
        "steady, no trace of doubt left in them, rain sliding down the lattice in the background, "
        "everything else still. Warm lamplight on the left, cold blue on the right. The camera holds "
        "absolutely still.",
     zh="[镜57] 特写少年的脸（收尾定格）：双眼睁开、彻底沉稳，里面再无半分犹疑，背景里雨水沿窗格"
        "滑落，其余一切静止。暖色灯光在左，冷蓝在右。镜头完全静止。",
     amb="rain steady outside, the room very quiet",
     amb_zh="屋外雨声持续，屋内极静",
     sfx="one slow breath, then silence",
     sfx_zh="一次缓慢的呼吸，随后归于沉默",
     protagonist=True, speaker_key="旁白",
     line="但他却清楚的知道，这绝不是梦。")


# ================================================================ 组装与输出

def build():
    shots = []
    for i, s in enumerate(S):
        n = i + 1
        vp = f"{STYLE}. {s['en']}" if not s["en"].startswith(STYLE) else s["en"]
        amb_en = s["amb"]
        sfx_en = s["sfx"]
        audio = f"Ambient sound: {amb_en}. SFX: {sfx_en}."
        audio_zh = f"环境音：{s['amb_zh']}。音效：{s['sfx_zh']}。"
        spk_voice = VOICE.get(s["speaker_key"], "")
        shots.append(dict(
            index=n, scene_no=s["scene_no"], shot_type=s["shot_type"],
            protagonist=s["protagonist"], anchor=s["anchor"],
            continuity=s["continuity"], ref=s["ref"], anchor_mode=s["anchor_mode"],
            length=s["length"], duration=round(s["length"] / 24, 2),
            video_prompt=vp,
            video_prompt_zh=s["zh"],
            audio_prompt=audio,
            audio_prompt_zh=audio_zh,
            # 中文字段：人类可读的场景备忘（不进模型）
            scene=s["zh"].split("]", 1)[-1].strip().lstrip("。").strip()[:60],
            line=s["line"], speaker_key=s["speaker_key"],
            speaker=spk_voice,
            speech_mode=s["speech_mode"], speech_verb="says",
            # 背影/过肩镜（ref=back）自动改用背面口径外貌串，覆盖 config 的正面外貌串
            appearance=(s["appearance"] or (FY_BACK if s["ref"] == "back" else "")),
            # v3 每条提示词自带完整环境与光线，无需再注入场景锚的文字串
            # （注入会造成「同一环境说两遍」，稀释注意力）；图锚仍照常生效。
            anchor_text=False,
        ))
    return shots


def main():
    shots = build()
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, "storyboard_ch1_v3.json")
    with io.open(path, "w", encoding="utf-8") as f:
        json.dump(shots, f, ensure_ascii=False, indent=1)

    total = sum(s["length"] for s in shots) / 24
    n_dlg = sum(1 for s in shots if s["line"])
    chars = sum(len(s["line"]) for s in shots if s["line"])
    print(f"已写出 {path}")
    print(f"  镜头 {len(shots)}｜含台词 {n_dlg}｜台词共 {chars} 字")
    print(f"  总时长 {total:.1f} 秒 = {total/60:.2f} 分钟")
    print(f"  单镜时长 {min(s['duration'] for s in shots):.2f} ~ "
          f"{max(s['duration'] for s in shots):.2f} 秒")
    print(f"  平均提示词 {sum(len(s['video_prompt']) for s in shots)//len(shots)} 字符")
    print(f"  音频层覆盖率 {sum(1 for s in shots if s['audio_prompt'])}/{len(shots)}")


if __name__ == "__main__":
    main()

