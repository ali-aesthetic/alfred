"""Bridge between the Python brain and Alfred.app (data/ui/*.jsonl, see mac-app/CONTRACT.md).

brain -> app : emit(type, **fields) appends to events.jsonl
app -> brain : commands.jsonl is tailed from its end; handlers registered with on(cmd, fn)
Also: settings.json, memory.json, routines.json helpers.
Only active when ALFRED_APP=1 (APP_MODE); emit() always works though (cheap, harmless) so tests can use it.
"""
import datetime as dt
import json
import os
import re
import threading
import time
import uuid

HOME = os.path.dirname(os.path.abspath(__file__))
APP_MODE = os.environ.get("ALFRED_APP") == "1"
MAX_EVENTS = 2 * 1024 * 1024

_lock = threading.Lock()
_handlers = {}
_tail_started = False
_settings = {}


def ui_dir():
    d = os.environ.get("ALFRED_UI_DIR") or os.path.join(HOME, "data", "ui")
    os.makedirs(d, exist_ok=True)
    return d


def _p(name):
    return os.path.join(ui_dir(), name)


# ---------------------------------------------------------------- events out
def _rotate(path):
    try:
        if os.path.getsize(path) <= MAX_EVENTS:
            return
        old = path + ".old"
        if os.path.exists(old):  # never delete: keep the previous .old under a stamped name
            keep = os.path.join(os.path.dirname(path), "old")
            os.makedirs(keep, exist_ok=True)
            os.replace(old, os.path.join(keep, f"events-{int(time.time())}.jsonl"))
        os.replace(path, old)
    except OSError:
        pass


_last_partial = {}


def emit(type, **fields):
    """Thread-safe append of one event line. Never raises."""
    # hide internal prompts like "[system] ..." from the pill, and drop duplicate partials
    txt = fields.get("text")
    if isinstance(txt, str) and txt.lstrip().startswith("[system]"):
        if type == "partial":
            return
        fields.pop("text", None)
    if isinstance(txt, str) and "Screen (only when asked" in txt:
        txt = txt.split("Screen (only when asked")[0].strip()
        fields["text"] = txt
    if type == "partial":
        now = time.time()
        if _last_partial.get("text") == txt and now - _last_partial.get("t", 0) < 1.0:
            return
        _last_partial.update(text=txt, t=now)
    try:
        line = json.dumps({"t": time.time(), "type": type, **fields}, ensure_ascii=False)
        path = _p("events.jsonl")
        with _lock:
            _rotate(path)
            with open(path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
    except Exception:
        pass


# ---------------------------------------------------------------- commands in
def on(cmd, fn):
    _handlers[cmd] = fn


def _dispatch(obj):
    fn = _handlers.get(obj.get("cmd"))
    if not fn:
        return
    try:
        fn(obj)
    except Exception:
        import traceback
        traceback.print_exc()


def start_tailer(poll=0.12):
    """Tail commands.jsonl from its current end (anything sent while the brain was off is ignored)."""
    global _tail_started
    if _tail_started:
        return
    _tail_started = True
    path = _p("commands.jsonl")
    if not os.path.exists(path):
        open(path, "a").close()
    pos = os.path.getsize(path)

    def loop():
        nonlocal pos
        buf = b""
        while True:
            time.sleep(poll)
            try:
                size = os.path.getsize(path)
                if size < pos:  # file was rotated / truncated
                    pos, buf = 0, b""
                if size == pos:
                    continue
                with open(path, "rb") as f:
                    f.seek(pos)
                    chunk = f.read()
                pos += len(chunk)
                buf += chunk
                *lines, buf = buf.split(b"\n")
                for ln in lines:
                    ln = ln.strip()
                    if not ln:
                        continue
                    try:
                        obj = json.loads(ln.decode("utf-8", "ignore"))
                    except ValueError:
                        continue
                    if isinstance(obj, dict):
                        # run in a thread so a slow handler (routine) never blocks the tailer
                        threading.Thread(target=_dispatch, args=(obj,), daemon=True).start()
            except Exception:
                pass

    threading.Thread(target=loop, daemon=True, name="ui-tailer").start()


# ---------------------------------------------------------------- settings
DEFAULTS = {
    "silent": False, "mic_off": False, "holo_mode": "off", "camera": True, "address": "sir", "name": "", "voice_follows_address": True,
    "voice": "bm_lewis", "brain": "claude-subscription", "concise": 0.7, "playful": 0.3, "humor": 75, "honesty": 90, "length": "short", "quiet_class": True, "class_hours": "Mon-Thu 10:00-14:00",
    "joke_a_day": True, "hotkey": "right_option",
    "computer_control": True, "onboarded": False, "insights": False, "stay_awake": False,
}


def claude_signed_in():
    """Cheap check: Claude Code stores the account in ~/.claude.json (oauthAccount)."""
    try:
        d = _read_json(os.path.expanduser("~/.claude.json"), {})
        return bool(d.get("oauthAccount") or d.get("userID"))
    except Exception:
        return False


def _read_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _write_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


VOICES = [  # curated: id decides the engine (bm_/bf_/am_ = Kokoro local, *Neural = edge-tts online, else macOS say)
    {"id": "bm_lewis", "name": "Lewis - British, local (default for Sir)", "lang": "en-GB"},
    {"id": "bf_isabella", "name": "Isabella - British, local (default for Ma'am)", "lang": "en-GB"},
    {"id": "bm_george", "name": "George - British, local", "lang": "en-GB"},
    {"id": "bm_daniel", "name": "Daniel - British, local", "lang": "en-GB"},
    {"id": "bm_fable", "name": "Fable - British, local", "lang": "en-GB"},
    {"id": "bf_emma", "name": "Emma - British, local", "lang": "en-GB"},
    {"id": "bf_alice", "name": "Alice - British, local", "lang": "en-GB"},
    {"id": "bf_lily", "name": "Lily - British, local", "lang": "en-GB"},
    {"id": "am_michael", "name": "Michael - American, local", "lang": "en-US"},
    {"id": "en-GB-RyanNeural", "name": "Ryan - British, online", "lang": "en-GB"},
    {"id": "en-GB-ThomasNeural", "name": "Thomas - British, online", "lang": "en-GB"},
    {"id": "en-GB-SoniaNeural", "name": "Sonia - British, online", "lang": "en-GB"},
    {"id": "en-US-GuyNeural", "name": "Guy - American, online", "lang": "en-US"},
]


def voice_ids():
    return {v["id"] for v in VOICES}


def load_settings(live=None):
    """settings.json (written by the app) over defaults; `live` = actual brain state for mirrored keys."""
    s = dict(DEFAULTS)
    s.update({k: v for k, v in _read_json(_p("settings.json"), {}).items() if k in DEFAULTS})
    if live:
        s.update(live)
    _settings.clear()
    _settings.update(s)
    return dict(s)


def settings():
    return dict(_settings) if _settings else load_settings()


def get(key, default=None):
    return settings().get(key, default)


def set_setting(key, value, save=True, announce=True):
    if key not in DEFAULTS:
        return False
    _settings[key] = value
    if save:
        try:
            _write_json(_p("settings.json"), dict(_settings))
        except OSError:
            pass
    if announce:
        emit("settings", data=dict(_settings))
    return True


def send_settings():
    emit("settings", data={**settings(), "voices": VOICES, "claude_signed_in": claude_signed_in()})


# ---------------------------------------------------------------- class hours
_DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def parse_class_hours(spec):
    """'Mon-Thu 10:00-14:00' -> (set of weekday numbers, start_minutes, end_minutes) or None."""
    try:
        m = re.match(r"\s*([A-Za-z,\- ]+?)\s+(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})\s*$", spec or "")
        if not m:
            return None
        days = set()
        for part in re.split(r"[,\s]+", m.group(1).strip()):
            if not part:
                continue
            if "-" in part:
                a, b = (_DAYS.index(x[:3].lower()) for x in part.split("-", 1))
                days |= set(range(a, b + 1)) if a <= b else set(list(range(a, 7)) + list(range(0, b + 1)))
            else:
                days.add(_DAYS.index(part[:3].lower()))
        return days, int(m.group(2)) * 60 + int(m.group(3)), int(m.group(4)) * 60 + int(m.group(5))
    except Exception:
        return None


def in_class(now=None, spec=None):
    now = now or dt.datetime.now()
    p = parse_class_hours(spec or get("class_hours"))
    if not p:
        return False
    days, a, b = p
    return now.weekday() in days and a <= now.hour * 60 + now.minute < b


def class_quiet_now():
    return bool(get("quiet_class", True)) and in_class()


# ---------------------------------------------------------------- memory cards
_TYPE_HINTS = [
    ("schedule", r"lecture|class|schedule|every (mon|tue|wed|thu|fri|sat|sun)|morning|at \d|o'clock|due|deadline|semester|\d{1,2}:\d{2}"),
    ("name", r"\bname\b|called|nickname|\bmy (editor|friend|brother|sister|mom|dad)\b|=|means"),
    ("preference", r"prefer|likes?|wants?|never|always|only|don't|do not|asks? before|ask before|english"),
    ("habit", r"often|usually|starts?|edits?|evening|night|every|habit|typically"),
]


def guess_type(fact):
    low = fact.lower()
    for t, rx in _TYPE_HINTS:
        if re.search(rx, low):
            return t
    return "preference"


def load_memory():
    d = _read_json(_p("memory.json"), [])
    return d if isinstance(d, list) else []


def save_memory(items):
    try:
        _write_json(_p("memory.json"), items)
    except OSError:
        pass


def add_memory(fact, type=None, announce=True):
    fact = fact.strip().lstrip("-• ").strip()
    if not fact:
        return None
    items = load_memory()
    if any(i.get("fact", "").strip().lower() == fact.lower() for i in items):
        return None
    item = {"id": uuid.uuid4().hex[:10], "type": type or guess_type(fact),
            "date": dt.date.today().isoformat(), "fact": fact}
    items.append(item)
    save_memory(items)
    if announce:
        emit("noted", text=fact, id=item["id"])
    return item


def forget_memory(mid):
    """Remove a card; also drop the matching bullet from data/memory.md (moved to .forgotten log, not deleted)."""
    items = load_memory()
    gone = [i for i in items if i.get("id") == mid]
    save_memory([i for i in items if i.get("id") != mid])
    mdp = os.path.join(HOME, "data", "memory.md")
    for g in gone:
        try:
            lines = open(mdp, encoding="utf-8").read().splitlines()
            keep = [l for l in lines if l.strip().lstrip("-• ").strip().lower() != g["fact"].lower()]
            if len(keep) != len(lines):
                with open(mdp + ".forgotten", "a", encoding="utf-8") as f:
                    f.write(f"{dt.datetime.now():%F %T} {g['fact']}\n")
                with open(mdp, "w", encoding="utf-8") as f:
                    f.write("\n".join(keep) + "\n")
        except OSError:
            pass
    return bool(gone)


def _bullets(path):
    try:
        return [l.strip().lstrip("-•").strip() for l in open(path, encoding="utf-8").read().splitlines()
                if l.strip().startswith(("-", "•")) and len(l.strip()) > 3]
    except OSError:
        return []


def seed_memory():
    """First start: turn data/memory.md bullets into memory cards (no 'noted' chips)."""
    if load_memory():
        return
    for fact in _bullets(os.path.join(HOME, "data", "memory.md")):
        add_memory(fact, announce=False)


def watch_memory(interval=5.0):
    """The brain appends '- fact' lines to data/memory.md: mirror new ones as cards + 'noted' chips."""
    path = os.path.join(HOME, "data", "memory.md")
    known = {b.lower() for b in _bullets(path)}

    def loop():
        nonlocal known
        while True:
            time.sleep(interval)
            try:
                now = _bullets(path)
                low = {b.lower() for b in now}
                for b in now:
                    if b.lower() not in known:
                        add_memory(b)
                known = low
            except Exception:
                pass

    threading.Thread(target=loop, daemon=True, name="memory-watch").start()


# ---------------------------------------------------------------- routines
def load_routines():
    d = _read_json(_p("routines.json"), None)
    if isinstance(d, list):
        return d
    default = [
        {"id": "edit", "name": "edit", "hotkey": "", "steps": [
            {"do": "open_app", "app": "Final Cut Pro"}, {"do": "music", "volume": 30},
            {"do": "dnd", "on": True, "minutes": 120}, {"do": "say", "text": "Edit mode on."}]},
        {"id": "class", "name": "class", "hotkey": "", "steps": [
            {"do": "silent", "on": True}, {"do": "music", "volume": 0}, {"do": "dnd", "on": True, "minutes": 240}]},
        {"id": "wind_down", "name": "wind_down", "hotkey": "", "steps": [
            {"do": "music", "volume": 20}, {"do": "dnd", "on": False}, {"do": "say", "text": "Winding down."}]},
    ]
    try:
        _write_json(_p("routines.json"), default)
    except OSError:
        pass
    return default


# ---------------------------------------------------------------- persona extras
def _num(v, d):
    try:
        return max(0, min(100, int(float(v))))
    except (TypeError, ValueError):
        return d


def dial_values(s=None):
    """(humor 0-100, honesty 0-100, length). Old concise/playful keys map in when the new ones were never set."""
    s = s or settings()
    raw = _read_json(_p("settings.json"), {})
    humor = _num(s.get("humor"), 75)
    if "humor" not in raw and "playful" in raw:
        humor = _num(float(raw["playful"]) * 100, 75)
    length = str(s.get("length") or "short").lower()
    if "length" not in raw and "concise" in raw:
        c = float(raw["concise"])
        length = "short" if c >= 0.7 else "normal" if c >= 0.35 else "detailed"
    if length not in ("short", "normal", "detailed"):
        length = "short"
    return humor, _num(s.get("honesty"), 90), length


def dials_text(s=None):
    """Personality dials as prompt text (also injected into the next turn whenever they change)."""
    humor, honesty, length = dial_values(s)
    h = ("no jokes at all, perfectly straight" if humor < 10 else "a rare, very dry remark only when it fits naturally" if humor < 35
         else "a dry deadpan remark in about every third reply" if humor < 65
         else "a dry deadpan quip in most replies, one short line, delivered flat" if humor < 90
         else "a deadpan joke in nearly every reply, sharp and flat, never at the cost of the answer")
    o = ("diplomatic and gentle" if honesty < 35 else "polite but straight" if honesty < 65
         else "direct; say plainly when an idea is bad or risky, no flattery" if honesty < 90
         else "brutally honest: blunt, no sugar-coating, no flattery, state the honest percentage or verdict when it helps")
    n = {"short": "at most 12 words out loud, answer first", "normal": "one to three short sentences, answer first",
         "detailed": "as long as needed to be complete, still answer first and no filler"}[length]
    return (f"Dial humor={humor}/100: {h}. Humor is deadpan and robotic-dry, never gushing, never in class hours or silent mode.\n"
            f"Dial honesty={honesty}/100: {o}.\nDial length={length}: {n}.")


def persona_extra():
    """Dials from settings, appended to the brain's system prompt at spawn."""
    s = settings()
    import address as _address
    addr = _address.word(s.get("address", "sir"), s.get("name", ""))
    lines = []
    lines.append(f'Address the user as "{addr}" once, at the end of the answer.' if addr else "Do not address the user by title or name.")
    lines.append(dials_text(s))
    if not s.get("computer_control", True):
        lines.append("Computer control is OFF: do NOT use alfred-ctl click, type, key, press or menu; you may still use open-app, open-url, find, front, screenshot and point.")
    if not s.get("joke_a_day", True):
        lines.append("No jokes at all, whatever the humor dial says.")
    return "\n".join(lines)


def start(mem_watch=True):
    """Call once at brain start (app mode)."""
    ui_dir()
    seed_memory()
    load_routines()
    start_tailer()
    if mem_watch:
        watch_memory()
