"""分镜体检 + 生成人工审核页。

用法：
    ./.venv/Scripts/python.exe tools/audit_storyboard.py            # 控制台摘要
    ./.venv/Scripts/python.exe tools/audit_storyboard.py --html     # 生成审核页（推荐）

检测项（全部来自本项目 2026-10-06/07 踩过的坑；已剔除误报项）：
  B  残留旧 2D 画风串 —— 文件卫生问题，运行时被 style_markers 剥掉，不影响生成
  C  主体零动作 —— 只给静态外观时 H3 会自行编运动（镜2「方源一直往前走」的根因）★最重要
  D  否定词偏多 —— H3 无 negative 分支，no/not/without 会被登记进条件
  E  镜头运动指向泛称 —— "pushes in on the X"，X 为泛称时易打错主体（镜2 实锤）
  F  无对白镜 —— 走 guard 分支，需确认音频层描述到位
  G  时长极端 —— <3.6s 信息量不足 / >11s 超模型训练区间

⚠️ 已撤掉的误报（别再当问题）：
  · `[Shot 1]` 标签 —— 逐镜生成，每镜都该是 [Shot 1]（见 novel_to_video.py:902 注释）
  · `appearance` 字段为空 —— 它是镜头级覆盖，空则回退 config 的 by_scene/default
"""
import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SB = os.path.join(ROOT, "assets/01_script/storyboard/storyboard_ch1_v3.json")
OUT_HTML = os.path.join(ROOT, "output/_diag/storyboard_audit.html")

OLD_STYLE = re.compile(r"donghua|cel[- ]shaded|anime style|manhua|flat coloring", re.I)
NEG = re.compile(r"\b(no|not|never|without|nor|none)\b", re.I)

# 真·动作（产生位移或姿态变化）
MOTION = re.compile(
    r"\b(walk|walks|walked|step|steps|stepped|stride|strides|run|runs|ran|turn|turns|"
    r"raise|raises|raised|lift|lifts|lifted|lower|lowers|move|moves|moved|shift|shifts|"
    r"lean|leans|swing|swings|reach|reaches|draw|draws|drew|nod|nods|shake|shakes|"
    r"inhale|exhale|breathe|breathes|drop|drops|fall|falls|fell|kneel|kneels|rise|rises|"
    r"push|pushes|pull|pulls|clench|clenches|glance|glances|stare|stares|fling|flings|flung|"
    r"plant|plants|press|presses|cover|covers|edge|edges|drift|drifts|sway|sways|"
    r"flutter|flutters|billow|billows|stir|stirs|tremble|trembles|lunge|lunges|"
    r"charge|charges|stagger|staggers|collapse|collapses|recoil|recoils|shout|shouts|"
    r"speak|speaks|say|says|whisper|whispers|mutter|mutters|cry|cries|snarl|snarls)\b", re.I)
# 静态姿态/状态（不算动作 —— 曾把镜2 误判为"有动作"）
STATIC = re.compile(r"\b(hang|hangs|hanging|hold|holds|holding|stand|stands|standing|"
                    r"sit|sits|sitting|wear|wears|wearing|lie|lies|kneel|remain|remains)\b", re.I)

MOTION_WORDS = (r"walk\w*|step\w*|stride\w*|run\w*|turn\w*|raise\w*|lift\w*|lower\w*|"
                r"move\w*|shift\w*|lean\w*|swing\w*|reach\w*|draw\w*|drew|nod\w*|shake\w*|"
                r"drop\w*|fall\w*|fell|rise\w*|push\w*|pull\w*|clench\w*|glance\w*|stare\w*|"
                r"fling\w*|flung|plant\w*|press\w*|cover\w*|edge\w*|drift\w*|sway\w*|stir\w*|"
                r"tremble\w*|recoil\w*|shout\w*|speak\w*|say\w*|whisper\w*|mutter\w*|cry|cries|"
                r"rise\w*|stand\w* up|turn\w*|bow\w*|wipe\w*|grip\w*|loosen\w*|slip\w*")
# 主角作为动作主语（这才是"主角有没有动作"）
# ⚠️ 只用**明确称呼**，不用 he/him/his —— 代词指代不可靠：
#    镜2 的 "his feet and keeps his ground, one arm flung" 里的 his 其实指对面白袍修士，
#    用代词判定会把镜2 误判成"主角有动作"（真凶漏报）。
SUBJ = (r"(?:the young man|the blood-soaked man|the boy|the protagonist|"
        r"the young cultivator|the young man in|the figure in the torn)")
SUBJ_MOTION = re.compile(r"\b" + SUBJ + r"\b[^.]{0,90}?\b(?:" + MOTION_WORDS + r")\b", re.I)
PRONOUN_ONLY = re.compile(r"\b(he|him|his)\b", re.I)
CAM_MOVE = re.compile(r"\bcamera\b[^.]{0,80}?\b(push|pushes|pull|pulls|track|tracks|pan|pans|"
                      r"dolly|dollies|zoom|zooms|drift|drifts|tilt|tilts|circle|circles|"
                      r"crane|cranes|follow|follows)\w*\b", re.I)
VAGUE = re.compile(r"\bon (the|a|his|her) [a-z\- ]{2,40}?(man|woman|figure|person|silhouette|"
                   r"crowd|host|group|one)\b", re.I)

# ---------------- H：参考帧矛盾（2026-10-07 第 20 轮新增）----------------
# I2V 首帧 = 硬约束。提示词点名首帧里**不存在**的环境元素 ⇒ H3 只能凭空生成。
# 镜1 的「草自己长出来」真因就是这个：锚图 peak_dusk.png 是纯裸岩，一根草都没有。
REF_ELEMENTS = {
    "草": [r"\bgrass\b", r"\btuft", r"\bweed"],
    "树/植被": [r"\btree", r"\bbranch\b", r"\bleaves\b", r"\bforest\b"],
    "雨": [r"\brain\b", r"\brainfall"],
    "雪": [r"\bsnow"],
    "水/水洼": [r"\bpuddle", r"\bpond\b"],
    "灯笼": [r"\blantern"],
    "蜡烛/油灯": [r"\bcandle", r"\boil lamp"],
    "牌位": [r"\btablet"],
    "旗帜": [r"\bbanner\b", r"\bflag\b"],
    "火/炽烈天光": [r"\bablaze\b", r"fiery crimson", r"\bblaze\b"],
}
# 人工核验后的锚图实有元素（ground truth）。True=有，False=没有，缺键=不判。
# ⚠️ 2026-10-07 16:26 peak_dusk 已重出（火红晚霞 + 石缝零星枯草），故「草」「火」改 True。
#    同步的守护脚本见 tools/check_ref_prompt_consistency.py（带 mtime 校验）。
ANCHOR_HAVE = {
    "peak_dusk": {
        "草": True, "树/植被": False, "雨": False, "雪": False, "水/水洼": False,
        "灯笼": False, "蜡烛/油灯": False, "牌位": False, "旗帜": False,
        "火/炽烈天光": True,
    },
    "peak_dusk_siege": {
        "草": False, "树/植被": False, "雨": False, "雪": False, "水/水洼": False,
        "灯笼": False, "蜡烛/油灯": False, "牌位": False, "旗帜": False,
        "火/炽烈天光": False,
    },
    "village_night": {"草": False, "雪": False, "灯笼": True, "雨": True},
    "ancestral_hall": {"草": False, "雨": False, "雪": False, "灯笼": False,
                       "蜡烛/油灯": True, "牌位": True},
    "corridor": {"草": False, "雪": False, "灯笼": True, "雨": True, "水/水洼": True},
    "window_view": {"草": False, "雪": False, "灯笼": True, "雨": True},
    "fangyuan_room": {"草": False, "雪": False, "灯笼": False, "雨": True,
                      "蜡烛/油灯": True},
    "flashback": {k: False for k in REF_ELEMENTS},
}



def detach_label(vp):
    """把 [Shot N] 之前的风格串剥掉，只留画面段（避免风格串里的词干扰判定）。"""
    i = vp.find("[Shot")
    return vp[i:] if i >= 0 else vp


def audit(shots):
    rows = []
    for s in shots:
        n = s.get("index")
        vp = str(s.get("video_prompt") or "")
        body = detach_label(vp)
        zh = str(s.get("video_prompt_zh") or "")
        line = str(s.get("line") or "").strip()
        dur = float(s.get("duration") or 0)
        prot = bool(s.get("protagonist"))
        refs = str(s.get("ref") or "")
        flags = []

        if OLD_STYLE.search(vp):
            flags.append(("B", "残留旧 2D 画风串（仅文件卫生，运行时会被剥掉）"))

        # C：关键不是"整镜有没有动作"，而是"动作是不是主角做的" ——
        # 镜2 整镜有动作（对面修士 plants his feet / flung out），但全给了别人，
        # 主角自己零动作 ⇒ H3 给前景主体自行编运动（「方源一直往前走」）。
        subj_motion = bool(SUBJ_MOTION.search(body))
        any_motion = bool(MOTION.search(body))
        if prot and not subj_motion:
            if PRONOUN_ONLY.search(body):
                flags.append(("C", "主角镜：主角无明确动作句（仅代词指代）← 待人工确认"))
            else:
                flags.append(("C", "主角镜：主角无任何动作描述 ← H3 会自行编运动"))
        elif not prot and not any_motion:
            flags.append(("c", "空镜：全镜无动作（可能偏静）"))

        negs = NEG.findall(vp)
        if len(negs) >= 5:
            flags.append(("D", "否定词 %d 个" % len(negs)))

        cm = CAM_MOVE.search(body)
        if cm and VAGUE.search(body[cm.start():cm.start() + 160]):
            flags.append(("E", "镜头推向泛称主体（易打错人）"))

        # H：参考帧矛盾 —— 首帧（关键帧/锚图）里不存在的环境元素被写进提示词。
        # I2V 首帧是硬约束，点名首帧没有的东西 ⇒ H3 只能凭空生成（镜1 草生长的真因）。
        aid = str(s.get("anchor") or "")
        have = ANCHOR_HAVE.get(aid, {})
        for elem, pats in REF_ELEMENTS.items():
            if not any(re.search(p, body, re.I) for p in pats):
                continue
            if have.get(elem) is False:
                flags.append(("H", "★首帧无「%s」却被写进提示词 ← 会被凭空生成" % elem))

        if not line:
            flags.append(("F", "无对白（走 guard）"))
        if dur and dur < 3.6:
            flags.append(("G", "过短 %.2fs" % dur))
        if dur and dur > 11.0:
            flags.append(("G", "过长 %.2fs" % dur))

        rows.append({"n": n, "scene": s.get("scene_no"), "dur": dur, "len": s.get("length"),
                     "prot": prot, "line": line, "ref": refs,
                     "mode": s.get("anchor_mode"), "cont": s.get("continuity"),
                     "anchor": s.get("anchor"), "speaker": s.get("speaker_key"),
                     "flags": flags, "vp": body, "zh": zh,
                     "audio": str(s.get("audio_prompt") or ""),
                     "audio_zh": str(s.get("audio_prompt_zh") or "")})
    return rows


LABEL = {"B": "旧画风串", "C": "★主体零动作", "c": "·空镜偏静", "D": "否定词多",
         "E": "镜头指向泛称", "F": "无对白", "G": "时长极端", "H": "★参考帧矛盾"}
COLOR = {"B": "#9aa0a6", "C": "#d93025", "c": "#f5a623", "D": "#e37400",
         "E": "#9334e6", "F": "#1a73e8", "G": "#188038", "H": "#c5221f"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--html", action="store_true")
    a = ap.parse_args()
    data = json.load(open(SB, encoding="utf-8"))
    shots = data if isinstance(data, list) else data["shots"]
    rows = audit(shots)

    cnt = Counter()
    for r in rows:
        for c, _ in r["flags"]:
            cnt[c] += 1
    total = len(rows)
    risk = [r for r in rows if any(c in ("C", "D", "E", "H") for c, _ in r["flags"])]

    print("=" * 88)
    print("分镜体检 —— 共 %d 镜" % total)
    print("-" * 88)
    for c in "H CcDEFGB".replace(" ", ""):
        if cnt[c]:
            print("  %-2s %-18s %2d 镜 (%.0f%%)" % (c, LABEL[c], cnt[c], cnt[c] * 100.0 / total))
    print("-" * 88)
    print("  ★ 需重点人工确认（H/C/D/E）：%d 镜" % len(risk))
    for r in risk:
        print("     镜%-3s 场%s %5.2fs  %s" % (r["n"], r["scene"], r["dur"],
              "；".join("%s %s" % (c, t) for c, t in r["flags"] if c in ("C", "D", "E", "H"))))
    print("=" * 88)

    if not a.html:
        return
    os.makedirs(os.path.dirname(OUT_HTML), exist_ok=True)
    scenes = sorted({r["scene"] for r in rows}, key=lambda x: (x is None, x))
    parts = ["""<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">
<title>分镜审核 · 第一章</title><style>
body{font-family:-apple-system,"Segoe UI","Microsoft YaHei",sans-serif;background:#f6f7f9;color:#202124;margin:0;padding:24px}
h1{font-size:20px;margin:0 0 4px}p.sub{color:#5f6368;margin:0 0 18px;font-size:13px}
.bar{position:sticky;top:0;background:#fff;border:1px solid #dadce0;border-radius:10px;padding:12px 14px;margin-bottom:16px;z-index:5;display:flex;gap:8px;flex-wrap:wrap;align-items:center}
button{font:inherit;font-size:13px;padding:5px 11px;border:1px solid #dadce0;background:#fff;border-radius:16px;cursor:pointer}
button.on{background:#1a73e8;border-color:#1a73e8;color:#fff}
.stat{font-size:13px;color:#5f6368;margin-left:auto}
.card{background:#fff;border:1px solid #dadce0;border-radius:10px;margin-bottom:10px;padding:12px 14px}
.card.risk{border-left:4px solid #d93025}
.card.done{opacity:.5}
.hd{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.no{font-weight:600;font-size:15px}
.meta{font-size:12px;color:#5f6368}
.bdg{font-size:11px;padding:2px 8px;border-radius:10px;color:#fff}
.line{margin:8px 0 0;font-size:13px;color:#188038;font-weight:500}
.prompt{margin:8px 0 0;font-size:13px;line-height:1.65;white-space:pre-wrap;word-break:break-word}
.zh{margin:6px 0 0;font-size:12px;color:#5f6368;line-height:1.6;white-space:pre-wrap}
.aud{margin-top:8px;font-size:12px;color:#5f6368}
details summary{cursor:pointer;font-size:12px;color:#1a73e8;margin-top:6px}
details.au{margin-top:8px;border-top:1px dashed #e0e0e0;padding-top:7px;border-radius:6px}
details.au summary{color:#188038;font-weight:500}
.aud_zh{font-size:13px;line-height:1.7;color:#202124;margin:5px 0 0 2px;white-space:pre-wrap;word-break:break-word}
.aud_en{font-size:11.5px;line-height:1.6;color:#80868b;margin:4px 0 0 2px;white-space:pre-wrap;
        word-break:break-word;font-style:italic;border-left:2px solid #e8eaed;padding-left:8px}
</style></head><body>
<h1>分镜审核 · 《大爱仙尊》第一章</h1>
<p class="sub">共 %d 镜 ｜ 场1=21 · 场2=15 · 场3=14 · 场4=8 ｜ 默认只显示有标记的镜</p>
<div class="bar">
<button data-f="risk" class="on">只看有标记</button>
<button data-f="all">全部</button>
<span style="color:#dadce0">｜</span>""" % total]
    for sc in scenes:
        parts.append('<button data-f="s%s">场%s</button>' % (sc, sc))
    parts.append('<span class="stat" id="stat"></span></div><div id="list">')

    for r in rows:
        is_risk = bool(r["flags"])
        cls = "card risk" if any(c in ("C", "D", "E", "H") for c, _ in r["flags"]) else ("card" if is_risk else "card ok")
        bdg = "".join('<span class="bdg" style="background:%s">%s %s</span>'
                      % (COLOR.get(c, "#5f6368"), c.upper(), t) for c, t in r["flags"])
        line = '<div class="line">对白 · %s：%s</div>' % (r["speaker"] or "—", r["line"]) if r["line"] else ""
        if r["audio"] or r["audio_zh"]:
            audio = ('<details class="au" open><summary>音频层 overall_soundscape</summary>'
                     '<div class="aud_zh">%s</div>'
                     '<div class="aud_en">%s</div></details>'
                     % (r["audio_zh"] or "—", r["audio"] or "—"))
        else:
            audio = ""
        parts.append("""<div class="card %s" data-scene="%s" data-risk="%d">
<div class="hd"><span class="no">镜 %s</span>
<span class="meta">场%s · %.2fs / %s帧 · %s · %s · ref=%s · 锚=%s</span>%s</div>%s
<div class="prompt">%s</div><div class="zh">%s</div>%s
<label class="aud"><input type="checkbox" class="ck" data-n="%s"> 已审</label></div>""" % (
            cls, r["scene"], 1 if is_risk else 0, r["n"], r["scene"], r["dur"], r["len"],
            "主角镜" if r["prot"] else "空镜", r["mode"], r["ref"] or "-", r["anchor"] or "-",
            bdg, line, r["vp"], r["zh"], audio, r["n"]))

    parts.append("""</div><script>
const cards=[...document.querySelectorAll('.card')];
const cks=[...document.querySelectorAll('.ck')];
cks.forEach(c=>{const k='audit_done_'+c.dataset.n;c.checked=localStorage.getItem(k)==='1';
  c.closest('.card').classList.toggle('done',c.checked);
  c.addEventListener('change',()=>{localStorage.setItem(k,c.checked?'1':'0');
    c.closest('.card').classList.toggle('done',c.checked);stat();});});
function stat(){const d=cks.filter(c=>c.checked).length;
  document.getElementById('stat').textContent='已审 '+d+' / '+cks.length;}
let cur='risk';
function apply(){cards.forEach(c=>{const sc=c.dataset.scene,rk=c.dataset.risk==='1';
  let show = cur==='all' ? true : (cur==='risk' ? rk : c.dataset.scene===cur.replace('s',''));
  c.style.display=show?'':'none';});stat();}
document.querySelectorAll('button[data-f]').forEach(b=>b.addEventListener('click',()=>{
  document.querySelectorAll('button[data-f]').forEach(x=>x.classList.remove('on'));
  b.classList.add('on');cur=b.dataset.f;apply();}));
apply();
</script></body></html>""")

    open(OUT_HTML, "w", encoding="utf-8").write("".join(parts))
    print("\n审核页 → %s" % OUT_HTML)


if __name__ == "__main__":
    main()
