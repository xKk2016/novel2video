"""runner_support —— 长跑批处理的运行支撑（日志 / 留痕 / 断点 / 防并发）。

给 novel_to_video.py 的逐镜循环用，解决三件事：
  1. 日志清晰可读   —— RunLogger：控制台 + 日志文件双写，逐行时间戳、分级前缀。
  2. 产物留痕       —— RunState：run_state.json（总表，原子写，供断点续跑）+
                        shots.jsonl（追加流水，永不覆盖，供事后追溯每镜的输入/耗时）。
  3. 从断点续跑     —— clip_is_valid() 判定片段是否真正可用；SingleInstanceLock
                        防止两个 runner 同时跑同一批镜头（互相覆盖产物）。
"""
import datetime
import json
import os
import shutil
import time


# ---------------------------------------------------------------- 时间
def _hms():
    return datetime.datetime.now().strftime("%H:%M:%S")


def _full():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


full_stamp = _full  # 公开别名：供 novel_to_video.py 写留痕时使用


def now_stamp():
    return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")


def fmt_dur(seconds):
    """把秒数变成 8s / 3m05s / 1h12m 这种好读的形式。"""
    seconds = int(round(seconds))
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m{seconds % 60:02d}s"
    return f"{seconds // 3600}h{(seconds % 3600) // 60:02d}m"


def fmt_size(path):
    try:
        b = os.path.getsize(path)
    except OSError:
        return "?"
    for unit, div in (("GB", 1 << 30), ("MB", 1 << 20), ("KB", 1 << 10)):
        if b >= div:
            return f"{b / div:.1f} {unit}"
    return f"{b} B"


# ---------------------------------------------------------------- 日志
class RunLogger:
    """控制台 + 文件双写。文件为 UTF-8，追加模式；控制台打印失败时不致命。"""

    def __init__(self, log_path=None, echo=True):
        self.echo = echo
        self.path = log_path
        self._fh = None
        if log_path:
            os.makedirs(os.path.dirname(os.path.abspath(log_path)), exist_ok=True)
            self._fh = open(log_path, "a", encoding="utf-8")

    # -- 底层 --
    def _write(self, line):
        if self._fh:
            self._fh.write(line + "\n")
            self._fh.flush()
        if self.echo:
            try:
                print(line, flush=True)
            except UnicodeEncodeError:
                print(line.encode("ascii", "replace").decode("ascii"), flush=True)

    # -- 结构 --
    def rule(self, ch="-", n=76):
        self._write(ch * n)

    def banner(self, title, dry=False):
        self._write("=" * 76)
        self._write(f"[{_full()}] {title}" + ("   (计划模式，不生成)" if dry else ""))
        self._write("=" * 76)

    def kv(self, key, val):
        self._write(f"  {key:<10}: {val}")

    # -- 分级 --
    def info(self, msg):
        self._write(f"[{_hms()}] {msg}")

    def step(self, msg):
        self._write(f"[{_hms()}] [>>] {msg}")

    def ok(self, msg):
        self._write(f"[{_hms()}] [OK] {msg}")

    def skip(self, msg):
        self._write(f"[{_hms()}] [--] {msg}")

    def warn(self, msg):
        self._write(f"[{_hms()}] [!!] {msg}")

    def fail(self, msg):
        self._write(f"[{_hms()}] [XX] {msg}")

    def close(self):
        if self._fh:
            self._fh.close()
            self._fh = None


# ---------------------------------------------------------------- 分镜指纹
# 只比对「会影响生成结果」的字段，避免单纯重新序列化 / 加注释就误报错配。
_FP_KEYS = ("index", "scene_no", "shot_type", "continuity", "anchor", "ref",
            "protagonist", "speaker_key", "line", "length", "duration",
            "video_prompt", "appearance", "anchor_mode", "speech_mode",
            "audio_prompt")


def storyboard_fingerprint(path):
    """分镜指纹：文件名 + 内容哈希 + 镜数 + 改动时间。

    用途：状态表（run_state.json）记录它，runner 启动时比对 —— 换了分镜却沿用旧状态表，
    会把新分镜的镜头按旧记录误判为「已完成」而整段跳过，且**不报任何错**。
    """
    import hashlib
    fp = {"file": os.path.basename(path), "path": os.path.abspath(path),
          "hash": "", "shots": 0, "mtime": ""}
    try:
        raw = open(path, "rb").read()
        fp["mtime"] = datetime.datetime.fromtimestamp(
            os.path.getmtime(path)).strftime("%Y-%m-%d %H:%M:%S")
    except OSError:
        return fp
    shots = None
    try:
        obj = json.loads(raw.decode("utf-8"))
        if isinstance(obj, dict) and isinstance(obj.get("shots"), list):
            shots = obj["shots"]
        elif isinstance(obj, list):
            shots = obj
    except Exception:
        shots = None
    if shots is not None:
        canon = [{k: s.get(k) for k in _FP_KEYS if k in s} for s in shots]
        blob = json.dumps(canon, ensure_ascii=False, sort_keys=True)
        fp["hash"] = hashlib.sha256(blob.encode("utf-8")).hexdigest()[:12]
        fp["shots"] = len(shots)
    else:
        # 解析不了就退回整文件哈希，宁可多报也不要漏报
        fp["hash"] = hashlib.sha256(raw).hexdigest()[:12]
    return fp


# ---------------------------------------------------------------- 进度留痕
class RunState:
    """run_state.json —— 每个镜头的状态总表（原子写），断点续跑与汇报都读它。"""

    def __init__(self, path, total):
        self.path = path
        self.data = {
            "created": _full(), "updated": "",
            "total": int(total), "shots": {},
        }
        if os.path.exists(path):
            try:
                old = json.load(open(path, encoding="utf-8"))
                if isinstance(old, dict) and "shots" in old:
                    self.data = old
                    self.data["total"] = int(total)
            except Exception:
                pass

    # -- 分镜绑定（换分镜时防止沿用旧完成记录） --
    def storyboard_info(self):
        """本状态表绑定的分镜指纹；旧格式状态表可能没有，返回 {}。"""
        d = self.data.get("storyboard")
        return d if isinstance(d, dict) else {}

    def bind_storyboard(self, fp):
        """把状态表绑定到某个分镜（写入指纹并落盘）。"""
        self.data["storyboard"] = {
            "file": fp.get("file", ""), "hash": fp.get("hash", ""),
            "shots": fp.get("shots", 0), "at": _full(),
        }
        self.save()
        return self.data["storyboard"]

    def get(self, n):
        return self.data["shots"].get(str(n), {})

    def mark(self, n, **fields):
        rec = self.data["shots"].setdefault(str(n), {})
        rec.update(fields)
        rec["updated"] = _full()
        self.save()
        return rec

    def save(self):
        self.data["updated"] = _full()
        tmp = self.path + ".tmp"
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)

    @staticmethod
    def journal(journal_path, record):
        """追加一条流水（JSON Lines），永不覆盖 —— 产物留痕。"""
        os.makedirs(os.path.dirname(os.path.abspath(journal_path)), exist_ok=True)
        with open(journal_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def counts(self):
        done = sum(1 for r in self.data["shots"].values() if r.get("status") == "done")
        fail = sum(1 for r in self.data["shots"].values() if r.get("status") == "failed")
        return done, fail

    def failed_list(self):
        return sorted(int(k) for k, r in self.data["shots"].items()
                      if r.get("status") == "failed")


# ---------------------------------------------------------------- 片段校验
def clip_is_valid(path, min_bytes=10240):
    """片段是否真正可用：存在、够大、且像是个 MP4（含 ftyp box）。"""
    try:
        if not os.path.exists(path) or os.path.getsize(path) < min_bytes:
            return False
        with open(path, "rb") as f:
            head = f.read(16)
        return b"ftyp" in head
    except OSError:
        return False


# ---------------------------------------------------------------- 单实例锁
class SingleInstanceLock:
    """防止两个 runner 同时跑（会互相覆盖 output/clips）。

    Windows 用 msvcrt 文件锁（原子）；心跳 + 陈旧锁清理兜底（进程被强杀时锁不会永久残留）。
    """

    def __init__(self, path, stale_seconds=900):
        self.path = path
        self.stale = stale_seconds
        self._fh = None
        self.acquired = False

    def acquire(self):
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        # 陈旧锁：心跳超过 stale_seconds 未更新 → 认为上一个进程已死，归档后接管
        if os.path.exists(self.path):
            try:
                if time.time() - os.path.getmtime(self.path) > self.stale:
                    shutil.move(self.path, self.path + ".stale")
            except OSError:
                pass
        self._fh = open(self.path, "a+", encoding="utf-8")
        try:
            import msvcrt
        except ImportError:
            msvcrt = None
        if msvcrt is not None:
            try:
                self._fh.seek(0)
                self._fh.write("lock\n")
                self._fh.flush()
                self._fh.seek(0)
                msvcrt.locking(self._fh.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                self._fh.close()
                self._fh = None
                return False
        else:
            marker = self.path + ".held"
            if os.path.exists(marker) and \
                    time.time() - os.path.getmtime(marker) < self.stale:
                self._fh.close()
                self._fh = None
                return False
        self.acquired = True
        self.heartbeat()
        return True

    def heartbeat(self):
        """每镜更新一次：既是给陈旧锁判定的心跳，也记录当前进程。"""
        if self._fh:
            try:
                self._fh.seek(0)
                self._fh.truncate()
                self._fh.write(f"pid={os.getpid()} at={_full()}\n")
                self._fh.flush()
            except Exception:
                pass
        marker = self.path + ".held"
        try:
            open(marker, "a").close()
            os.utime(marker, None)
        except OSError:
            pass

    def release(self):
        if self._fh:
            try:
                import msvcrt
                self._fh.seek(0)
                msvcrt.locking(self._fh.fileno(), msvcrt.LK_UNLCK, 1)
            except Exception:
                pass
            try:
                self._fh.close()
            except Exception:
                pass
            self._fh = None
        try:
            os.remove(self.path + ".held")
        except OSError:
            pass
