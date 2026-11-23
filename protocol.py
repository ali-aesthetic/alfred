#!/usr/bin/env python3
"""'Wake up, daddy's home' — the workstation protocol.

Order:  theme music starts → boot HUD fills the screen → Alfred greets + briefing → workstation apps open.
Run from voice (alfred.py) or by hand:  .venv/bin/python protocol.py wake
Everything it opens is listed in config.json → "workstation". Music: data/protocol/theme.mp3 if you put
your own file there, otherwise the Spotify track in config.json → "protocol_spotify_uri".
"""
import datetime as dt
import json
import re
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

HOME = Path(__file__).resolve().parent
PY = str(HOME / ".venv" / "bin" / "python")


def _cfg():
    try:
        return json.loads((HOME / "config.json").read_text(encoding="utf-8"))
    except Exception:
        return {}


def _osa(script, timeout=8):
    try:
        return subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=timeout).stdout.strip()
    except Exception:
        return ""


def play_theme(cfg):
    local = HOME / "data" / "protocol" / "theme.mp3"
    if local.exists():
        subprocess.Popen(["afplay", "-v", str(cfg.get("protocol_volume", 0.6)), str(local)])
        return "file"
    uri = cfg.get("protocol_spotify_uri")
    if uri and Path("/Applications/Spotify.app").exists():
        _osa('tell application "Spotify" to activate', 10)
        time.sleep(1.2)
        _osa(f'tell application "Spotify"\n set sound volume to {int(cfg.get("protocol_spotify_volume", 70))}\n'
             f' play track "{uri}"\nend tell', 10)
        _osa('tell application "System Events" to set visible of process "Spotify" to false')
        return "spotify"
    return None


def music_down():
    _osa('if application "Spotify" is running then tell application "Spotify" to set sound volume to 35')


def weather(city):
    try:
        req = urllib.request.Request(f"https://wttr.in/{urllib.request.quote(city)}?format=%t+%C", headers={"User-Agent": "curl/8"})
        with urllib.request.urlopen(req, timeout=3) as r:
            return r.read().decode().strip().replace("+", "")
    except Exception:
        return ""


def open_workstation(cfg):
    opened = []
    for item in cfg.get("workstation", []):
        kind, target, label = item.get("type"), item.get("target"), item.get("label") or item.get("target")
        try:
            if kind == "app":
                subprocess.Popen(["open"] + (["-g"] if item.get("background") else []) + ["-a", target])
            elif kind == "url":
                subprocess.Popen(["open", target])
            elif kind == "claude_code":
                folder = str(Path(target).expanduser())
                _osa(f'tell application "Terminal"\n set w to do script "clear; cd \\"{folder}\\" && claude"\n'
                     f' set custom title of front window to "Claude Code"\n activate\nend tell', 10)
            elif kind == "shell":  # your own automation script (must live inside the Alfred folder)
                subprocess.Popen(["/bin/zsh", "-lc", target], cwd=str(HOME))
            opened.append(label)
            time.sleep(0.35)
        except Exception as e:
            print("[protocol]", label, e)
    return opened


def boot_hud(lines, seconds=11):
    """Separate process: full-screen, click-through HUD (boot_hud.py + boot.html)."""
    try:
        return subprocess.Popen([PY, str(HOME / "boot_hud.py"), json.dumps({"lines": lines, "seconds": seconds})])
    except Exception as e:
        print("[protocol] hud:", e)


def today_events(timeout=14):
    """Rest of today's calendar events → [(title, "3:30 PM")]. Empty on any problem (no permission, slow Calendar)."""
    script = (
        'set d0 to current date\nset d1 to d0 - (time of d0) + (24 * hours)\nset out to ""\n'
        'tell application "Calendar"\n repeat with c in calendars\n  try\n'
        '   repeat with e in (every event of c whose start date >= d0 and start date < d1)\n'
        '    set t to start date of e\n'
        '    set out to out & (summary of e) & "|" & (hours of t) & ":" & (minutes of t) & linefeed\n'
        '   end repeat\n  end try\n end repeat\nend tell\nreturn out')
    try:
        r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=timeout)
    except Exception:
        return []
    ev = []
    for line in r.stdout.splitlines():
        if "|" in line:
            title, hm = line.rsplit("|", 1)
            h, m = (int(x) for x in hm.split(":"))
            ev.append((h * 60 + m, title.strip(), dt.time(h, m).strftime("%I:%M %p").lstrip("0").replace(":00", "")))
    return [(t, s) for _, t, s in sorted(ev)][:5]


def briefing_line(cal, addr="sir"):
    bits = []
    if cal:
        first = f"{cal[0][0]} at {cal[0][1]}"
        bits.append(f"You have one event left today: {first}." if len(cal) == 1
                    else f"You have {len(cal)} events left today, starting with {first}.")
    try:
        import claude_watch
        done = [c for c in claude_watch.recent(8) if c["status"] == "done" and c["idle"] > 600]
        wait = [c for c in claude_watch.recent(8) if c["status"] == "waiting"]
        if wait:
            bits.append(f"{wait[0]['title']} is waiting for you." if len(wait) == 1 else f"{len(wait)} Claude chats are waiting for you.")
        elif done:
            bits.append("One Claude chat finished while you were away." if len(done) == 1
                        else f"{len(done)} Claude chats finished while you were away.")
    except Exception:
        pass
    return " ".join(bits)


def wake(mouth=None, cfg=None):
    cfg = cfg or _cfg()
    import address as _address
    name = cfg.get("user_name", "")
    addr = _address.word(cfg.get("address", "sir"), name)
    city = cfg.get("city") or ""
    now = dt.datetime.now()
    w = {}
    set_quiet(0)  # he is home and awake
    tw = threading.Thread(target=lambda: w.setdefault("v", weather(city)), daemon=True)
    tw.start()
    cal = {}
    if cfg.get("protocol_calendar", True):
        threading.Thread(target=lambda: cal.setdefault("v", today_events()), daemon=True).start()
    src = play_theme(cfg)
    tw.join(3.2)
    wx = w.get("v", "")
    lines = ["Alfred ONLINE", f"WELCOME HOME, {name.upper() or addr.upper() or ''}".strip(" ,"),
             f"{now:%H:%M} · {now:%A %d %B}".upper(), f"{city.upper()} · {wx.upper()}" if wx else city.upper(),
             "VOICE ✓  BRAIN ✓  HOLOGRAM ✓", "WORKSTATION: DEPLOYING"]
    boot_hud(lines, seconds=float(cfg.get("protocol_hud_seconds", 11)))
    time.sleep(2.5 if src else 0.8)
    part = "Good morning" if 5 <= now.hour < 12 else "Good afternoon" if now.hour < 18 else "Good evening"
    hour = now.strftime("%I:%M").lstrip("0")
    greet = (f"Welcome home{', ' + addr if addr else ''}. {part}. It's {hour}"
             + (f", {wx.split(' ', 1)[0].replace('°C', ' degrees')} in {city}." if (wx and city) else ".")
             + " Bringing your workstation online.")
    opened = []
    t = threading.Thread(target=lambda: opened.extend(open_workstation(cfg)), daemon=True)
    if mouth:
        t.start()
        mouth.say(greet)
    else:
        subprocess.Popen([str(HOME / "bin" / "alfred-say"), greet])
        t.start()
    t.join(30)
    time.sleep(1.0)
    music_down()
    extra = briefing_line(cal.get("v") or [], addr)
    if extra and mouth:
        mouth.say(extra)
    last = cfg.get("protocol_last_line") or f"Everything is ready{', ' + addr if addr else ''}. What are we building today?"
    if mouth:
        mouth.say(last)
    return opened


# ---------- named protocols ("focus mode", "I'm heading out", "good night") — edit them in config.json → "protocols"
DEFAULT_PROTOCOLS = {
    "focus": {"phrases": ["focus mode", "focus protocol", "let's get to work", "time to work"],
              "steps": [{"say": "Focus mode{addr}. Notifications are yours to ignore."},
                        {"volume": 35}, {"music": "pause"}, {"quiet": 2}, {"url": "claude://code/new"}]},
    "leaving": {"phrases": ["i'm heading out", "i am heading out", "i'm leaving", "going to the gym", "heading to the gym"],
                "steps": [{"music": "pause"}, {"say": "Very good{addr}. I'll hold the fort until you're back."}]},
    "night": {"phrases": ["good night", "goodnight", "night protocol", "going to sleep", "go to sleep"],
              "steps": [{"music": "pause"}, {"volume": 20}, {"quiet": 9}, {"say": "Good night{addr}. Systems on standby."}]},
}


def protocols(cfg):
    return cfg.get("protocols") or DEFAULT_PROTOCOLS


def match(text, cfg):
    t = re.sub(r"[^a-z' ]", " ", (text or "").lower())
    t = re.sub(r"\s+", " ", t)
    for name, p in protocols(cfg).items():
        for ph in p.get("phrases", []):
            if re.search(r"(^|\b)" + re.escape(ph.lower()) + r"(\b|$)", t):
                return name
    return None


QUIET = HOME / "data" / "quiet_until"


def set_quiet(hours):
    """Quiet hours: Alfred still works when called, but does not speak up on his own (Claude chat news → notification only)."""
    QUIET.write_text(str(time.time() + hours * 3600 if hours > 0 else 0))


def is_quiet():
    try:
        return time.time() < float(QUIET.read_text())
    except Exception:
        return False


def run(name, mouth=None, cfg=None):
    cfg = cfg or _cfg()
    p = protocols(cfg).get(name) or {}
    said = []
    import address as _address
    _w = _address.word(cfg.get("address", "sir"), cfg.get("user_name", ""))
    _suffix = f", {_w}" if _w else ""
    for st in p.get("steps", []):
        try:
            if "say" in st:
                line = st["say"].replace("{addr}", _suffix)
                said.append(line)
                if mouth:
                    mouth.say(line)
                else:
                    subprocess.Popen([str(HOME / "bin" / "alfred-say"), line])
            elif "volume" in st:
                _osa(f"set volume output volume {int(st['volume'])}")
            elif "music" in st:
                verb = {"pause": "pause", "play": "play", "next": "next track"}.get(st["music"], "pause")
                _osa(f'if application "Spotify" is running then tell application "Spotify" to {verb}')
            elif "spotify" in st:
                _osa(f'tell application "Spotify" to play track "{st["spotify"]}"', 10)
            elif "url" in st:
                subprocess.Popen(["open", st["url"]])
            elif "app" in st:
                subprocess.Popen(["open", "-a", st["app"]])
            elif "quiet" in st:
                set_quiet(float(st["quiet"]))
            elif "wait" in st:
                time.sleep(float(st["wait"]))
        except Exception as e:
            print("[protocol]", name, e)
    return " ".join(said)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "wake":
        print(wake())
    elif len(sys.argv) > 1:
        print(run(sys.argv[1]))
    else:
        print(__doc__)
