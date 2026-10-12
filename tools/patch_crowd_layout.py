# -*- coding: utf-8 -*-
"""场1「正道群雄」排布 + 服饰修正。

老板指出的三个问题（2026-10-06）：
    ① 正道群雄没有一起对峙方源 —— 镜头里的群雄朝向是乱的，模型按「包围圈」字面
       把圈画在**画面中央那个人**身上（镜4 两侧黑甲对他举刀、镜18 一圈甲士全对他）。
    ② 群雄服饰统一 —— 原 prompt 里群雄只有 "a dozen armed figures" / "crowd" /
       "dark dense mass"，零服饰信息，模型默认给同款黑甲。
    ③ 群雄对中间声讨方源的正道人物拔刀相向 —— ②+①的合成结果。

修法（老板选定「各派驳杂混编」）：
    A. 朝向——所有正道修士**面朝同一方向**（画外的方源），兵器一致朝外；不围成圈、
       不对内、不对同伴、也不对声讨者亮兵器。
    B. 服饰——各派杂编：白/灰/靛青/赭褐/暗红杂色，道袍·短打·轻甲·斗篷混穿，
       头饰与兵器各异，无两人相同。
    C. 队形——松散开阔的弧形环伺（保留 distance_lock：无人敢上前、无肢体接触）。

仅改 11 镜（2/3/4/5/6/8/11/12/18/19/20），其余镜头群雄不突出。
镜 9/10/13/14/15/16/17 复核：9/10/13/15/16 是主角镜（背景空景），14 闪回，
17 只提「周围的人静了下来」→ 已一并处理（17 在列）。

用法：
    python tools/patch_crowd_layout.py --dry-run
    python tools/patch_crowd_layout.py --apply
"""
import argparse
import datetime
import json
import os
import shutil
import sys

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SB = os.path.join(ROOT, "assets", "01_script", "storyboard", "storyboard_ch1_v3.json")

# ---------------------------------------------------------------- 群雄统一描述块
# 英文与中文两块是同义的；各镜按上下文裁剪，但三项要点必到：
#   同向（toward the man off frame） / 杂编（no two dressed alike） / 不对内（none at each other）
CROWD_EN = (
    "the allied host of the righteous sects is a loose mixed crowd, no two of them "
    "dressed alike — off-white, ash-grey, dusty indigo, ochre-brown and faded dark-red "
    "robes of different cuts and lengths, some in plain loose cross-collar robes with "
    "cloth sashes, some in patched short jackets with leg wraps, a few in light riveted "
    "lamellar over padded cloth, one or two in fur-trimmed travelling cloaks; headwear "
    "differs too, cloth caps, headbands, wooden hairpins, high topknots, a few "
    "bare-headed; weapons differ as well, straight swords, broad sabres, spears, wooden "
    "staffs. Every one of them is turned the same way, facing the tattered white-haired "
    "man off frame in a loose open arc, every blade and spear levelled outward at him, "
    "none of them turned on the speaker and none at each other."
)
CROWD_ZH = (
    "正道各派联军的松散人群，无两人服饰相同——米白、灰、靛青、赭褐、褪色暗红的袍服，"
    "长短款式各异：有素色交领宽袍系布带，有打补丁的短打加绑腿，少数披轻质札甲，"
    "一两个裹毛边斗篷；头饰各异（布巾、抹额、木簪、高髻，少数光头）；兵器各异"
    "（直剑、阔刀、长枪、木杖）。所有人朝向同一方向——画外那位破烂袍的白发男子——"
    "在外围排成松散开阔的弧形，兵器一致朝外指向他，无人把兵器对着说话人，也无人彼此相对。"
)

PATCHES = {
    # ---------------------------------------------------------------- 镜2 R2V 锚
    2: {
        "video_prompt": (
            "Chinese donghua 2D cel-shaded anime style. [Shot 1] The camera sits behind "
            "the blood-soaked man in the torn dark jade-green robe, looking past his back "
            "toward the front: only his back is in frame, his long loose hair and the torn "
            "dark jade-green robe filling the left third of the picture in shadow. Facing "
            "the camera beyond him, across a wide stretch of bare rock, the allied host "
            "stands as a loose mixed crowd, no two of them dressed alike in colour or cut, "
            "every one of them turned the same way, inward and facing him. At the front a "
            "burly middle-aged cultivator in white robes with a thick grey-streaked beard "
            "plants his feet and keeps his ground, one arm flung out in accusation, jaw "
            "tight, eyes blazing, not daring to step any closer. Golden hour warm side "
            "light catches the crowd's shoulders from behind the ridge. The camera pushes "
            "in slowly on the shouting man's face across the empty ground left between them."
        ),
        "video_prompt_zh": (
            "[镜2] 镜头位于那位浴血、碧绿大袍残破的男子身后，越过他的背影朝前看：画面里只有他的"
            "背面，披散长发与破烂的碧绿大袍占据左侧三分之一并保持在暗部。他之外，隔着大片裸露"
            "岩石，正道各派联军松散地站着，无两人服饰相同，所有人朝向同一方向、都面朝着他。"
            "阵前一名留着花白浓须的白袍魁梧中年修士双脚钉在原地不敢靠近，只一臂挥出怒指，"
            "牙关紧咬，双目怒睁。黄昏暖侧光从山脊后方勾出人群肩线。镜头越过两人之间空出的地面，"
            "缓慢推向喊话者的脸。"
        ),
    },
    # ---------------------------------------------------------------- 镜3 蓝袍青年
    3: {
        "video_prompt": (
            "Chinese donghua 2D cel-shaded anime style. [Shot 1] Medium shot of a young "
            "cultivator in blue robes with his hair tied in a high topknot standing his "
            "ground at the edge of the ring, his whole body squared toward the tattered "
            "white-haired man off frame, his longsword held low with the tip pointed at the "
            "ground, chin lifted, mouth curled in cold contempt, his feet planted and "
            "refusing to come any closer. Behind and past him the rest of the allied host "
            "stretches away as a loose unfocused band of mixed sect robes, no two dressed "
            "alike, all of them turned the same way toward the man off frame. Low golden "
            "side light rims his cheekbone and the blade edge. The camera holds him from "
            "across the wide empty ground of the ring, the encirclement stretching away "
            "behind."
        ),
        "video_prompt_zh": (
            "[镜3] 中景。一名将长发束成高髻的蓝袍青年修士立在包围圈边缘，整个身形朝向画外那位"
            "破烂袍的白发男子，长剑低垂、剑尖指地，抬着下巴，嘴角挂着冷酷的轻蔑，双脚钉在原地"
            "不肯再上前一步。他身后远处，正道各派联军松散铺开、焦点虚化，无两人服饰相同，"
            "所有人朝向同一方向。低角度暖金侧光勾出他的颧骨与剑刃亮边。镜头隔着包围圈中大片"
            "空地对着他，整个包围阵型在他身后铺开。"
        ),
    },
    # ---------------------------------------------------------------- 镜4 蓝袍青年举剑
    4: {
        "video_prompt": (
            "Chinese donghua 2D cel-shaded anime style. [Shot 1] Medium close-up of the "
            "same young cultivator in blue robes with the high topknot, now snapping his "
            "sword up to point straight out of frame at the white-haired man, wrist "
            "flicking, teeth bared. Spread out behind him a dozen armed figures from "
            "different sects swing their weapons around and level them the same way — every "
            "blade aimed outward at that same off-frame man, none turned toward the speaker "
            "and none at each other. No two of them dressed alike: mixed off-white, grey, "
            "indigo, ochre and faded dark-red robes, some cloth sashes, some short jackets, "
            "a few light lamellar, headwear all different. Golden side light flares along "
            "the raised blade. The camera pushes in slowly on his face as the words come out."
        ),
        "video_prompt_zh": (
            "[镜4] 中近景。同一名束高髻的蓝袍青年修士，手腕一抖将长剑上扬、直指画外的方源，"
            "露出牙齿。他身后十余名来自不同门派的持械身影随之把兵器一致转向同一方向，"
            "齐齐指向画外那个人——无人把兵器对着说话人，也无人彼此相对。这些人无两人服饰相同："
            "米白、灰、靛青、赭褐、褪色暗红的袍服混杂，有系布带的，有穿短打的，少数披轻甲，"
            "头饰各不相同。暖金侧光顺着举起的长剑泛出亮光。台词迸出时，镜头缓慢推近他的面部。"
        ),
    },
    # ---------------------------------------------------------------- 镜5 灰袍老修士
    5: {
        "video_prompt": (
            "Chinese donghua 2D cel-shaded anime style. [Shot 1] Medium shot of a gaunt "
            "elderly cultivator in grey robes with a long white beard and sunken cheeks at "
            "the front of the ring, squared toward the white-haired man off frame, both "
            "hands shaking as they grip a wooden staff, his thin frame trembling with rage, "
            "spittle at the corner of his lips. Behind him the allied host stands as a "
            "loose mixed crowd, robes in many different colours and cuts, no two alike, all "
            "of them turned the same way and facing out. Cold side lighting with deep "
            "shadows cuts across the deep lines of his face. The camera pushes in slowly "
            "toward him."
        ),
        "video_prompt_zh": (
            "[镜5] 中景。包围圈前方一位留着长白须、双颊深陷的消瘦灰袍老修士，正面朝向画外的"
            "白发男子，双手抖着握紧木杖，瘦削身体因暴怒而颤抖，唇边溅着唾沫。他身后正道各派"
            "联军松散站立，袍服颜色款式驳杂、无两人相同，所有人朝向同一方向、面朝画外。"
            "冷侧光带着深重阴影切过他脸上深刻的皱纹。镜头缓慢向他推近。"
        ),
    },
    # ---------------------------------------------------------------- 镜6 老修士特写
    6: {
        "video_prompt": (
            "Chinese donghua 2D cel-shaded anime style. [Shot 1] Close-up of the elderly "
            "cultivator's face, long white beard and skin drawn tight over the bone, eyes "
            "wet and burning, his jaw working hard to force the words out. A raised "
            "trembling hand comes into the lower frame. Far behind him, softly out of "
            "focus, the allied host is turned the same way — many coloured and differently "
            "cut robes, all facing outward toward the man he is denouncing. Cold side "
            "lighting with deep shadow carves his cheek. The camera holds almost still with "
            "only a breath of slow push-in."
        ),
        "video_prompt_zh": (
            "[镜6] 特写。老修士的脸，长白须，皮肉紧绷贴骨，眼中湿亮而灼人，下颌费力开合把话"
            "挤出来。一只颤抖的手从画面下缘抬起入画。他身后极远处、虚化的人群服饰颜色款式驳杂，"
            "所有人朝向同一方向，一致面朝他所声讨的那个人。冷侧光与深影凿刻他的面颊。镜头几乎"
            "静止，只有一丝极缓的推近。"
        ),
    },
    # ---------------------------------------------------------------- 镜8 红袍妇人特写
    8: {
        "video_prompt": (
            "Chinese donghua 2D cel-shaded anime style. [Shot 1] Close-up of the woman's "
            "face, hair bound back in the wooden pin, as she tears her hand away from her "
            "mouth and shrieks, eyes wide, tendons standing in her neck, loose hair stuck "
            "across her cheek. Cold side light; behind her the allied host dissolves into "
            "shadow, a loose mixed crowd of many differently coloured and cut robes, all "
            "turned the same way toward the man off frame, no weapon of theirs raised at "
            "her or at each other. The camera pushes in a little harder on the scream."
        ),
        "video_prompt_zh": (
            "[镜8] 特写。以木簪束发的女修士把手从嘴边猛地扯开、尖声嘶吼，双目圆睁，脖颈青筋"
            "暴起，散发黏在颊侧。冷侧光；她身后正道各派联军溶入暗部，袍服颜色款式驳杂、"
            "无两人相同，所有人朝向同一方向、面朝画外那个人，无人对她或对彼此举起兵器。"
            "镜头在嘶吼中略加快推近。"
        ),
    },
    # ---------------------------------------------------------------- 镜11 背影大远景
    11: {
        "video_prompt": (
            "Chinese donghua 2D cel-shaded anime style. [Shot 1] Wide shot from directly "
            "behind him, seen from the back: the back of his head, his long straight "
            "silver-white hair falling loose down the back of the dark jade-green robe, the "
            "plain dark green belt knotted at his waist seen from behind, his slender "
            "blood-stained silhouette alone on the rock. Far below the ridge the crowd of "
            "cultivators stands facing him — a mixed host from many sects, robes in many "
            "different colours and cuts, weapons of every kind, all of them turned the same "
            "way, all facing him and none turned away. Cold wind lifts his hair and the "
            "torn hem. The camera pushes in very slowly on his back."
        ),
        "video_prompt_zh": (
            "[镜11] 背影大远景。从他正后方拍摄：后脑、顺碧绿袍背部落下的银白长直发、自背面"
            "可见的腰间墨绿素布腰带结，以及独自立在岩石上的浴血瘦削剪影。山脊下方远处，"
            "密集的修士人群正面对着他——那是各派杂编的联军，袍服颜色款式驳杂、兵器各异，"
            "所有人朝向同一方向，一致面朝他、无人转身向外。冷风掀起他的头发与破烂衣摆。"
            "镜头向他的背影极缓慢推近。"
        ),
    },
    # ---------------------------------------------------------------- 镜12 转身
    12: {
        "video_prompt": (
            "Chinese donghua 2D cel-shaded anime style. [Shot 1] He completes the turn and "
            "holds still: his long silver-white hair settles and swings on past his "
            "shoulder, the torn hem lifting in the cold wind. Behind him and far below, the "
            "crowd of distant cultivators recoils as one — a mixed host in many different "
            "robes, no two dressed alike, tiny figures stepping back and pressing away from "
            "him, all of them still turned toward him. Warm low side light catches half of "
            "his face. The camera holds steady on him with only a slight slow push-in."
        ),
        "video_prompt_zh": (
            "[镜12] 承接背影。他完成转身后定住：银白长发顺过肩头继续轻摆，破烂衣摆被冷风掀起。"
            "他身后远处那一圈正道群雄齐齐骚动后退，那是个各派杂编的联军、无两人服饰相同，"
            "细小的人影纷纷向外退避，但个个仍朝他转着。暖色低侧光打亮他半张脸。镜头稳住，"
            "只极缓地推近。"
        ),
    },
    # ---------------------------------------------------------------- 镜18 蓝袍青年战斗姿态（重灾区）
    18: {
        "video_prompt": (
            "Chinese donghua 2D cel-shaded anime style. [Shot 1] Medium shot of the young "
            "cultivator in blue robes with the high topknot snapping into a fighting "
            "stance, sword raised and levelled straight out of frame at the white-haired "
            "man, his head only half turning to shout a warning to the men beside him. On "
            "both sides of him the allied host in mixed sect robes brings every weapon up "
            "and levels them the same way — all of them pointing outward at that same "
            "off-frame man, the whole line shifting one step forward with him; not one of "
            "them turns on the speaker, and not one at another. No two of them dressed "
            "alike: off-white, grey, indigo, ochre and faded dark-red robes of different "
            "cuts, mixed headwear, mixed weapons. Cold light. The camera pushes in quickly "
            "on him."
        ),
        "video_prompt_zh": (
            "[镜18] 中景。束着高髻的蓝袍青年修士猛然进入战斗姿态，长剑横举、直指画外的方源，"
            "只半侧头朝身边的同伴喊话。他左右两侧各派修士随之把手中兵器一致举起、转向同一方向，"
            "齐齐指向画外那个人，整条阵线跟着他向前压上一步——无人把兵器对着他，也无人彼此相对。"
            "各派衣着各异：米白、灰、靛青、赭褐、褪色暗红的袍服款式不同，头饰兵器各不相同。"
            "冷光。镜头快速推近他。"
        ),
    },
    # ---------------------------------------------------------------- 镜19 老修士挥杖
    19: {
        "video_prompt": (
            "Chinese donghua 2D cel-shaded anime style. [Shot 1] Close-up of the elderly "
            "cultivator in grey robes with the long white beard standing rooted where he is "
            "and shaking his staff out at the man off frame from a distance, spittle "
            "flying, veins standing out on his forehead, too wary to move in. Behind and "
            "around him the allied host, a loose mixed crowd of many differently coloured "
            "and cut robes, all of them facing the same way, toward the man off frame. Cold "
            "side light with deep shadow. The camera pushes in hard on his face."
        ),
        "video_prompt_zh": (
            "[镜19] 特写。留着长白须的灰袍老修士双脚钉在原地，只远远地朝画外那个人挥杖怒喝，"
            "唾沫横飞，额上青筋暴起，忌惮得不敢上前。他身后与身侧正道各派联军松散站立，"
            "袍服颜色款式驳杂，所有人朝向同一方向、面朝画外。冷侧光带深影。镜头用力推近他的脸。"
        ),
    },
    # ---------------------------------------------------------------- 镜20 自爆
    20: {
        "video_prompt": (
            "Chinese donghua 2D cel-shaded anime style. [Shot 1] Wide shot: he stands alone "
            "at the centre as the loose ring of cultivators — a mixed host from many sects, "
            "robes in many different colours and cuts, weapons of every kind — edges a "
            "single wary step inward from every side, every weapon lifted and levelled at "
            "him yet still held back, no one daring to be the first. He does not move. Then "
            "a blinding white core ignites at his chest and blows outward in one expanding "
            "shockwave, throwing a wall of dust and debris down the ridge and flinging the "
            "nearest attackers backwards. The camera pushes in hard through the blast and "
            "the frame goes white."
        ),
        "video_prompt_zh": (
            "[镜20] 大远景。他独自立于中央，那圈各派杂编的修士——袍服颜色款式驳杂、兵器各异——"
            "终于从四面试探性地收拢一步，兵器齐齐举起指向他，却仍不敢落下，无人敢做第一个。"
            "他没有动。随后，一点炽白核心在他胸口亮起，向外炸开成一道猛烈扩张的冲击波，"
            "沿山脊推出一堵尘浪碎石墙，最靠前的攻击者被掀飞。镜头迎着爆风猛烈推近，"
            "画面转成一片炽白。"
        ),
    },
}


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--apply", action="store_true")
    g.add_argument("--dump-crowd", action="store_true", help="打印群雄描述块供复核")
    args = ap.parse_args()

    if args.dump_crowd:
        print("=== CROWD EN ===\n" + CROWD_EN + "\n\n=== CROWD ZH ===\n" + CROWD_ZH)
        return

    with open(SB, encoding="utf-8") as f:
        shots = json.load(f)

    by_idx = {int(s["index"]): s for s in shots}
    changed = 0

    for idx, patch in sorted(PATCHES.items()):
        s = by_idx.get(idx)
        if s is None:
            print(f"[SKIP] 镜{idx} 不存在")
            continue
        touched = []
        for field, new in patch.items():
            old = str(s.get(field) or "")
            if old == new:
                continue
            if args.dry_run:
                print(f"\n{'=' * 70}\n镜{idx} · {field}  (旧 {len(old)} 字符 → 新 {len(new)} 字符)")
                print(f"--- 旧 ---\n{old}\n--- 新 ---\n{new}")
            s[field] = new
            touched.append(field)
        if touched:
            changed += 1
            if args.apply:
                print(f"[OK] 镜{idx} 已更新 {touched}")

    if args.dry_run:
        print(f"\n[dry-run] 将修改 {changed} 镜，未落盘。")
        return

    bak = os.path.join(
        ROOT, "assets", "01_script", "storyboard",
        f"storyboard_ch1_v3.json.bak_before_crowd_{datetime.datetime.now():%Y%m%d_%H%M%S}",
    )
    shutil.copy2(SB, bak)
    with open(SB, "w", encoding="utf-8") as f:
        json.dump(shots, f, ensure_ascii=False, indent=1)
    print(f"\n[apply] 已修改 {changed} 镜；备份 → {os.path.basename(bak)}")


if __name__ == "__main__":
    main()
