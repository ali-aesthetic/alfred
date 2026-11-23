"""Мгновенные команды без мозга: приложения, звук, музыка, время, таймер."""
from alfred_home import HOME_STR as _AH, CTL as _CTL
import datetime as dt
import glob
import os
import re
import subprocess
import threading

UNITS = {"ноль": 0, "один": 1, "одну": 1, "одна": 1, "два": 2, "две": 2, "три": 3, "четыре": 4, "пять": 5,
         "шесть": 6, "семь": 7, "восемь": 8, "девять": 9, "десять": 10, "одиннадцать": 11, "двенадцать": 12,
         "тринадцать": 13, "четырнадцать": 14, "пятнадцать": 15, "шестнадцать": 16, "семнадцать": 17,
         "восемнадцать": 18, "девятнадцать": 19, "двадцать": 20, "тридцать": 30, "сорок": 40,
         "пятьдесят": 50, "шестьдесят": 60, "семьдесят": 70, "восемьдесят": 80, "девяносто": 90, "сто": 100,
         "полторы": 1.5, "полчаса": 30, "пол": 0.5}
UZ_UNITS = {"bir": 1, "ikki": 2, "uch": 3, "to'rt": 4, "tort": 4, "besh": 5, "olti": 6, "yetti": 7,
            "sakkiz": 8, "to'qqiz": 9, "toqqiz": 9, "o'n": 10, "on": 10, "yigirma": 20, "o'ttiz": 30,
            "ottiz": 30, "qirq": 40, "ellik": 50, "oltmish": 60, "yetmish": 70, "sakson": 80,
            "to'qson": 90, "yuz": 100, "yarim": 0.5}

ALIASES = {
    "телеграм": "Telegram", "телеграмм": "Telegram", "телегу": "Telegram", "телега": "Telegram",
    "сафари": "Safari", "хром": "Google Chrome", "гугл хром": "Google Chrome", "chrome": "Google Chrome",
    "музыку": "Music", "музыка": "Music", "эпл мьюзик": "Music", "спотифай": "Spotify",
    "финдер": "Finder", "файлы": "Finder", "заметки": "Notes", "календарь": "Calendar",
    "напоминания": "Reminders", "давинчи": "DaVinci Resolve", "давинчи резолв": "DaVinci Resolve",
    "да винчи": "DaVinci Resolve", "настройки": "System Settings", "терминал": "Terminal",
    "фото": "Photos", "фотографии": "Photos", "почту": "Mail", "почта": "Mail", "карты": "Maps",
    "капкат": "CapCut", "кап кат": "CapCut", "фотошоп": "Adobe Photoshop", "лайтрум": "Adobe Lightroom",
    "иллюстратор": "Adobe Illustrator", "ворд": "Microsoft Word", "эксель": "Microsoft Excel",
    "калькулятор": "Calculator", "сообщения": "Messages", "фейстайм": "FaceTime", "ватсап": "WhatsApp",
    "вотсап": "WhatsApp", "зум": "zoom.us", "клод": "Claude", "claude": "Claude", "превью": "Preview",
    "telegram": "Telegram", "telegramm": "Telegram", "safari": "Safari", "musiqa": "Music",
    "kalkulyator": "Calculator", "sozlamalar": "System Settings", "eslatmalar": "Notes", "davinchi": "DaVinci Resolve",
}
SITES = {
    "ютуб": "https://youtube.com", "youtube": "https://youtube.com", "инстаграм": "https://instagram.com",
    "инсту": "https://instagram.com", "гугл": "https://google.com", "почту гугл": "https://mail.google.com",
    "чат гпт": "https://chatgpt.com", "gmail": "https://mail.google.com", "claude code on the web": "https://claude.ai/code",
}


# ---------- fast paths added 2026-11-16: files, web search, quit app, new tab (no LLM)
DRY = False          # tests: collect commands instead of running them
LAST_CMDS = []
_DIRS = ["~/Desktop", "~/Documents", "~/Downloads", "~/Movies", "~/Pictures"]
_KIND = {"video": ("mov", "mp4", "m4v"), "movie": ("mov", "mp4", "m4v"), "pdf": ("pdf",), "image": ("png", "jpg", "jpeg", "heic"),
         "photo": ("png", "jpg", "jpeg", "heic"), "picture": ("png", "jpg", "jpeg", "heic"), "doc": ("docx", "doc", "pages"),
         "document": ("docx", "doc", "pages", "pdf"), "spreadsheet": ("xlsx", "numbers", "csv"), "presentation": ("pptx", "key")}
_FILLER = {"the", "my", "a", "an", "file", "called", "named", "document", "please", "that", "one"}


def _sh(cmd, timeout=15):
    if DRY:
        LAST_CMDS.append(cmd)
        return ""
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout
    except Exception:
        return ""


def find_file(query):
    """Spotlight search -> ranked list of paths (best first). Name match, then recency, then favourite folders."""
    q = query.lower().strip()
    exts = ()
    words = []
    for w in re.findall(r"[\w'-]+", q):
        if w in _KIND:
            exts = _KIND[w]
            if w in ("document", "doc", "pdf", "image", "photo", "picture", "video", "movie", "spreadsheet", "presentation"):
                continue
        if w not in _FILLER:
            words.append(w)
    home = os.path.expanduser("~")
    if re.search(r"(last|latest|recent|newest)\s+(screenshot|screen shot)", q) or q.strip() in ("screenshot", "the screenshot"):
        # real macOS screenshots: "Screenshot 2026-…png" / "Screen Shot …png" in the usual folders (newest first)
        ps = []
        for d in ["~/Desktop", "~/Downloads", "~/Pictures", "~/Pictures/Screenshots", "~/Documents"]:
            for pat in ("Screenshot*", "Screen Shot*", "Screen Recording*"):
                if pat == "Screen Recording*":
                    continue
                ps += [x for x in glob.glob(os.path.join(os.path.expanduser(d), pat)) if x.lower().endswith((".png", ".jpg", ".jpeg", ".heic"))]
        ps = sorted(set(ps), key=lambda x: os.path.getmtime(x), reverse=True)
        if ps or DRY:
            return ps
        out = _sh(["mdfind", "-onlyin", home, "kMDItemIsScreenCapture == 1"])
        ps = [p for p in out.splitlines() if p and "/to delete/" not in p]
        ps.sort(key=lambda p: os.path.getmtime(p) if os.path.exists(p) else 0, reverse=True)
        return ps
    words = [w for w in words if w not in ("last", "latest", "recent", "newest", "open")] or words
    if not words and not exts:
        return []
    cond = " && ".join(f'kMDItemDisplayName == "*{w}*"cd' for w in words) if words else "kMDItemDisplayName == \"*\"cd"
    if exts:
        cond += " && (" + " || ".join(f'kMDItemFSName == "*.{x}"c' for x in exts) + ")"
    out = _sh(["mdfind", "-onlyin", home, cond])
    paths = [p for p in out.splitlines() if p and "/Library/" not in p and "/.Trash" not in p and "/node_modules/" not in p
             and "/to delete/" not in p and not os.path.basename(p).startswith(".") and not os.path.isdir(p) or p.endswith((".app", ".key", ".pages", ".numbers"))]
    if DRY:
        return paths
    fav = [os.path.expanduser(d) for d in _DIRS]

    def score(p):
        base = os.path.splitext(os.path.basename(p))[0].lower()
        name = 3 if all(w in base.split() or base.startswith(w) for w in words) else 0
        name += 2 if base == " ".join(words) else 0
        try:
            used = _sh(["mdls", "-raw", "-name", "kMDItemLastUsedDate", p]).strip()
            age = (dt.datetime.now(dt.timezone.utc) - dt.datetime.strptime(used[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=dt.timezone.utc)).days if used and used != "(null)" else 999
        except Exception:
            age = 999
        try:
            age = min(age, (time_now() - os.path.getmtime(p)) / 86400)
        except Exception:
            pass
        fv = 1 if any(p.startswith(d + "/") for d in fav) else 0
        return (name + fv, -age)
    paths = sorted(paths[:60], key=score, reverse=True)
    return paths


def time_now():
    import time
    return time.time()


def open_file(query, addr="sir"):
    """'open my essay' -> best Spotlight match opened; say which. None if nothing found at all."""
    paths = find_file(query)
    if not paths:
        return f"Couldn't find {query.strip()[:30]}, {addr}."
    best = paths[0]
    _sh(["open", best])
    name = os.path.basename(best)
    extra = f" ({len(paths) - 1} others match)" if len(paths) > 1 else ""
    return f"Opening {name}{extra}."


def web_search(q, youtube=False):
    from urllib.parse import quote_plus
    url = ("https://www.youtube.com/results?search_query=" if youtube else "https://www.google.com/search?q=") + quote_plus(q.strip())
    _sh(["open", url])
    return f"Searching {'YouTube' if youtube else 'Google'}."


def parse_num(s):
    s = s.strip().lower()
    m = re.search(r"\d+(?:[.,]\d+)?", s)
    if m:
        return float(m.group(0).replace(",", "."))
    total, found = 0.0, False
    s = re.sub(r"[ʻ‘’`]", "'", s)
    for w in re.findall(r"[а-яё]+|[a-z']+", s):
        if w in UNITS:
            total += UNITS[w]
            found = True
        elif w in UZ_UNITS:
            total += UZ_UNITS[w]
            found = True
    return total if found else None


def _osa(script):
    if DRY:
        LAST_CMDS.append(["osascript", script])
        return ""
    r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=15)
    return r.stdout.strip()


_apps = None


def _app_index():
    global _apps
    if _apps is None:
        _apps = {}
        for d in ("/Applications", "/System/Applications", "/System/Applications/Utilities",
                  os.path.expanduser("~/Applications"), "/Applications/Utilities"):
            for p in glob.glob(os.path.join(d, "*.app")):
                name = os.path.basename(p)[:-4]
                _apps[name.lower()] = name
    return _apps


def find_app(spoken):
    s = spoken.lower().strip(" .,!?")
    if s in ALIASES:
        return ALIASES[s]
    apps = _app_index()
    if s in apps:
        return apps[s]
    for low, name in apps.items():
        if low.startswith(s) or s.startswith(low):
            return name
    for low, name in apps.items():
        if len(s) >= 4 and s in low:
            return name
    return None


def _media_app():
    r = subprocess.run(["pgrep", "-x", "Spotify"], capture_output=True)
    return "Spotify" if r.returncode == 0 else "Music"


def diagnostics(addr="sir"):
    """Stark-style system check: battery, memory, disk, CPU load, network → spoken summary + hologram panel."""
    import shutil
    def sh(c):
        try:
            return subprocess.run(["/bin/zsh", "-c", c], capture_output=True, text=True, timeout=5).stdout.strip()
        except Exception:
            return ""
    batt = re.search(r"(\d+)%", sh("pmset -g batt")); batt = int(batt.group(1)) if batt else None
    charging = "AC Power" in sh("pmset -g batt")
    free_pct = re.search(r"(\d+)%", sh("memory_pressure | tail -1")); free_pct = int(free_pct.group(1)) if free_pct else None
    du = shutil.disk_usage("/"); disk_free = du.free / 1e9
    load = os.getloadavg()[0]; cores = os.cpu_count() or 8
    online = sh("ping -c1 -t2 1.1.1.1 >/dev/null && echo up") == "up"
    rows = [["Power", f"{batt}%{' charging' if charging else ''}" if batt is not None else "n/a"],
            ["Memory free", f"{free_pct}%" if free_pct is not None else "n/a"],
            ["Mac disk free", f"{disk_free:.0f} GB"], ["CPU load", f"{load / cores * 100:.0f}%"],
            ["Network", "online" if online else "offline"]]
    try:
        import panels
        panels.push({"type": "table", "title": "Diagnostics", "columns": ["System", "Status"], "rows": rows})
    except Exception:
        pass
    warn = []
    if batt is not None and batt < 20 and not charging:
        warn.append(f"power is at {batt} percent")
    if free_pct is not None and free_pct < 25:
        warn.append("memory is running low, close a few apps")
    if disk_free < 10:
        warn.append(f"only {disk_free:.0f} gigabytes left on the Mac")
    if not online:
        warn.append("we are offline")
    if warn:
        return f"Diagnostics complete, {addr}. " + "; ".join(warn).capitalize() + "."
    return f"All systems nominal, {addr}. Power {batt} percent, {disk_free:.0f} gigabytes free."


def _project_dir(text):
    """Finds a project folder named in the request ("in my-app", "for the website project")."""
    import json as _j
    from pathlib import Path as _P
    try:
        cfg = _j.loads((_P(__file__).resolve().parent / "config.json").read_text())
    except Exception:
        cfg = {}
    roots = cfg.get("claude_project_roots") or ["~/Desktop", "~/Documents", "~/Projects", "~/Developer"]
    norm = lambda x: re.sub(r"[^a-z0-9а-я]", "", x.lower())
    said = norm(text)
    best = None
    for r in roots:
        d = _P(os.path.expanduser(r))
        if not d.is_dir():
            continue
        for sub in d.iterdir():
            n = norm(sub.name)
            if sub.is_dir() and len(n) >= 3 and n in said and (best is None or len(n) > len(norm(best.name))):
                best = sub
    for alias, path in (cfg.get("claude_projects") or {}).items():
        if norm(alias) in said and os.path.isdir(os.path.expanduser(path)):
            best = _P(os.path.expanduser(path))
    return best


def claude_task(task, addr="sir"):
    """Opens a NEW Claude Code chat in the Claude app with the task already typed in (he presses Enter)."""
    from urllib.parse import quote
    task = task.strip(" .,!?")
    if len(task) < 3:
        return None
    url = "claude://code/new?q=" + quote(task[0].upper() + task[1:])
    proj = _project_dir(task)
    if proj:
        url += "&folder=" + quote(str(proj))
    subprocess.Popen(["open", url])
    where = f" in {proj.name}" if proj else ""
    return f"New Claude chat{where} is ready with your task, {addr}. Press Enter to start it."


_DIAL_RE = re.compile(r"^(?:(?:please )?(?:set|change|put|turn|adjust)\s+)?(?:your |the |my )?(humou?r|honesty)(?:\s+(?:level|setting|dial))?(?:\s+(?:to|at|on|=))?\s*(\d{1,3})\s*(?:%|percent|per cent)?$")


def parse_dial(e):
    """'set humor to 60 percent' / 'humor 40%' / 'honesty 100' -> ('humor'|'honesty', 0-100) or None."""
    m = _DIAL_RE.match(e.strip(" .!?,"))
    if not m:
        return None
    return ("humor" if m.group(1).startswith("humo") else "honesty"), max(0, min(100, int(m.group(2))))


def dial_reply(key, n):
    if key == "humor":
        tail = "Entirely serious." if n == 0 else "Noted." if n < 90 else "Heaven help us."
        return f"Humor at {n} percent. {tail}"
    tail = "Diplomacy engaged." if n < 35 else "Noted." if n < 90 else "Brace yourself."
    return f"Honesty at {n} percent. {tail}"


# ---------- computer-control fast paths (2026-11-21, no LLM): window snap, settings panes, folders, menu path, music volume
CTL = _CTL
_PANES = {"displays": "com.apple.Displays-Settings.extension", "display": "com.apple.Displays-Settings.extension",
          "wifi": "com.apple.wifi-settings-extension", "wi-fi": "com.apple.wifi-settings-extension",
          "bluetooth": "com.apple.BluetoothSettings", "sound": "com.apple.Sound-Settings.extension",
          "battery": "com.apple.Battery-Settings.extension", "notifications": "com.apple.Notifications-Settings.extension",
          "keyboard": "com.apple.Keyboard-Settings.extension", "trackpad": "com.apple.Trackpad-Settings.extension",
          "mouse": "com.apple.Mouse-Settings.extension", "wallpaper": "com.apple.Wallpaper-Settings.extension",
          "appearance": "com.apple.Appearance-Settings.extension", "general": "com.apple.systempreferences.GeneralSettings",
          "accessibility": "com.apple.Accessibility-Settings.extension", "privacy": "com.apple.settings.PrivacySecurity.extension",
          "network": "com.apple.Network-Settings.extension", "storage": "com.apple.settings.Storage",
          "desktop and dock": "com.apple.Desktop-Settings.extension", "dock": "com.apple.Desktop-Settings.extension",
          "control center": "com.apple.ControlCenter-Settings.extension", "siri": "com.apple.Siri-Settings.extension",
          "lock screen": "com.apple.Lock-Screen-Settings.extension", "printers": "com.apple.Print-Scan-Settings.extension"}
_FOLDERS = {"downloads": "~/Downloads", "desktop": "~/Desktop", "documents": "~/Documents", "movies": "~/Movies", "pictures": "~/Pictures",
            "music": "~/Music", "home": "~", "applications": "/Applications", "home folder": "~"}
_SNAP = {"right": "right", "right half": "right", "left": "left", "left half": "left", "top": "top", "top half": "top", "bottom": "bottom",
         "bottom half": "bottom", "full": "full", "full screen": "full", "fullscreen": "full", "maximize": "full", "maximized": "full",
         "center": "center", "the center": "center", "top left": "top-left", "top right": "top-right", "bottom left": "bottom-left", "bottom right": "bottom-right"}


def _ctl(*a, timeout=15):
    """Run alfred-ctl; returns parsed JSON dict (ok False on any problem)."""
    if DRY:
        LAST_CMDS.append([CTL, *a])
        return {"ok": True}
    try:
        import json as _j
        r = subprocess.run([CTL, *a], capture_output=True, text=True, timeout=timeout)
        return _j.loads((r.stdout or "{}").strip().splitlines()[-1])
    except Exception as ex:
        return {"ok": False, "error": str(ex)[:100]}


_BGW = re.compile(r"in the background|quietly|silently|without (?:switching|interrupting|stealing|bringing|opening it)|don'?t (?:switch|bring|interrupt)|behind the scenes")
_LAST_APP = {"name": None}


def _bg_mode():
    """Background mode preference (settings.json background_mode, default True): automation never steals mouse/keyboard/focus."""
    try:
        import json as _j
        return bool(_j.load(open(_AH + "/data/ui/settings.json")).get("background_mode", True))
    except Exception:
        return True


def _app_arg(spoken):
    spoken = re.sub(r"\b(the|my|app)\b", "", spoken).strip()
    return find_app(spoken) or (spoken.title() if spoken else None)


def control_fast(e, addr, text=None):
    text = text or e
    """Deterministic computer-control phrases. Returns a reply or None (brain handles it)."""
    nuanced = re.search(r"\b(don'?t|do not|but|tell me|where|which|without|then|and then)\b", e)
    bgreq = bool(_BGW.search(e))
    e = re.sub(r"\s*\b(in the background|quietly|silently|behind the scenes)\b\s*", " ", e).strip()
    fr = [] if bgreq else ["--front"]          # the user asked to see it -> raise it, unless he said "in the background"
    og = ["-g"] if bgreq else []               # `open -g` = do not steal focus
    # "show it" / "bring it up": raise the last app Alfred opened quietly
    if re.fullmatch(r"(?:show|bring)(?: me)?(?: it| that| this)?(?: up| forward| to the front| here)?|show me", e) and _LAST_APP["name"]:
        r = _ctl("focus", _LAST_APP["name"])
        return f"{_LAST_APP['name']} is up, {addr}." if r.get("ok") else None
    # "Safari > File > New Window" / "use the menu path Safari>File>New Window"
    m = re.search(r"(?:menu(?: path| item)?|click|choose)\s*[:,]?\s*([\w .'…-]+(?:\s*>\s*[\w .'…-]+)+)$", e)
    if m:
        parts = [x.strip() for x in m.group(1).split(">") if x.strip()]
        app = _app_arg(parts[0]) if len(parts) >= 3 else None
        if app and parts[0].lower() not in ("file", "edit", "view", "window", "help"):
            r = _ctl("menu", ">".join(parts[1:]), "--app", app)
            _LAST_APP["name"] = app
            return (f"Done: {' > '.join(parts)}." if r.get("ok") else f"That menu item failed: {str(r.get('error', ''))[:80]}") if r else None
    # window snap: "move safari to the right half", "put chrome on the left"
    m = re.fullmatch(r"(?:move|put|snap|send|resize|make)\s+(?:the\s+|my\s+)?(.+?)(?:\s+window)?\s+(?:to|on|in|at)\s+(?:the\s+)?(.+?)(?:\s+(?:of the screen|side))?", e)
    if m and m.group(2).strip() in _SNAP and not nuanced:
        app = _app_arg(m.group(1))
        if app:
            r = _ctl("window", app, _SNAP[m.group(2).strip()])
            _LAST_APP["name"] = app
            if r.get("ok"):
                return f"{app} moved {_SNAP[m.group(2).strip()]}, {addr}."
            if "NO_ACCESSIBILITY" in str(r.get("error", "")):
                return f"I need Accessibility permission to move windows, {addr}. Allow Alfred in Privacy settings."
            return None
    # system settings panes
    m = re.fullmatch(r"(?:open|show|go to|pull up)\s+(?:the\s+)?(?:system\s+)?(?:settings|preferences)?\s*(?:and\s+)?(?:go to\s+|open\s+)?(?:the\s+)?([a-z' -]+?)(?:\s+(?:settings|pane|preferences))?", e)
    if m and m.group(1).strip() in _PANES and ("setting" in e or "preferences" in e or m.group(1).strip() in ("displays", "display", "wifi", "wi-fi", "bluetooth", "wallpaper", "trackpad")):
        _sh(["open", *og, f"x-apple.systempreferences:{_PANES[m.group(1).strip()]}"])
        return f"{m.group(1).strip().title()} settings are open, {addr}."
    # folders: "open downloads", "open the downloads folder in finder"
    m = re.fullmatch(r"(?:in finder\s+)?(?:open|show|go to|pull up)\s+(?:my\s+|the\s+)?([a-z ]+?)(?:\s+(?:folder|directory))?(?:\s+in finder)?", e)
    if m and m.group(1).strip() in _FOLDERS and not nuanced:
        _sh(["open", *og, os.path.expanduser(_FOLDERS[m.group(1).strip()])])
        return f"{m.group(1).strip().title()} is open, {addr}."
    # Music app volume (app volume, not system)
    m = re.search(r"\bmusic\b.*\bvolume\b.*?(\d{1,3})|\bvolume\b.*\bmusic\b.*?(\d{1,3})|\b(?:set|turn)\b.*\b(?:in|of)\s+(?:the\s+)?music\b.*?(\d{1,3})", e)
    if m:
        v = max(0, min(100, int(next(g for g in m.groups() if g))))
        if not DRY and _osa('application "Music" is running') != "true":
            return f"Music isn't open, {addr}, so I left it closed."
        _osa(f'tell application "Music" to set sound volume to {v}')
        return f"Music volume {v}."
    # "open safari and search X on youtube"
    m = re.fullmatch(r"(?:open\s+(\w[\w ]*?)\s+and\s+)?(?:search(?: for)?|look up|find)\s+(.+?)\s+on\s+(youtube|google)(?:\s+(?:in|with|using)\s+(\w[\w ]*))?", e)
    if m and not nuanced:
        q, site = m.group(2), m.group(3)
        browser = _app_arg(m.group(1) or m.group(4) or "") if (m.group(1) or m.group(4)) else None
        from urllib.parse import quote_plus
        url = ("https://www.youtube.com/results?search_query=" if site == "youtube" else "https://www.google.com/search?q=") + quote_plus(q.strip())
        if browser:
            _ctl("open-url", url, "--app", browser, *fr)
            _LAST_APP["name"] = browser
        else:
            _sh(["open", *og, url])
        return f"Searching {site.title()}{' in ' + browser if browser else ''}{' in the background' if bgreq else ''}, {addr}."

    # ---- screenshot to a given path (ScreenCaptureKit via alfred-ctl)
    m = re.search(r"screenshot.*?(?:save|put|write|store)\w*\s+(?:it\s+)?(?:to|as|at|in)\s+(\S+\.(?:png|jpe?g))", e)
    if m:
        path = os.path.expanduser(m.group(1))
        r = _ctl("screenshot", path)
        if r.get("ok"):
            return f"Screenshot saved to {path}, {addr}."
        return f"The screenshot failed: {str(r.get('error', ''))[:90]}"
    # ---- find a file and tell the path
    m = re.fullmatch(r"(?:find|locate|search for)\s+(?:me\s+)?(?:a\s+|the\s+|my\s+)?(?:file|document|doc)s?\s+(?:(?:named|called)\s+)?(?:like\s+)?(.{2,40}?)(?:\s+and\s+(?:tell|show|give) me\s+(?:the\s+)?(?:path|location|where it is))?", e)
    if m:
        paths = find_file(m.group(1))
        if not paths:
            return f"I couldn't find a file like {m.group(1)}, {addr}."
        more = f" ({len(paths) - 1} more match)" if len(paths) > 1 else ""
        return f"Best match: {paths[0].replace(os.path.expanduser('~'), '~')}{more}."
    # ---- Notes: draft a note
    m = re.search(r"(?:create|make|add|write|start)\s+(?:a\s+)?(?:new\s+)?(?:draft\s+)?note\s+(?:titled|called|named)\s+[\"']?(.+?)[\"']?(?:\s+(?:and|but|,)\s.*)?$", e)
    if m:
        title = m.group(1).strip().rstrip(".").replace('"', "")
        title = (text.lower().find(title) >= 0 and text[text.lower().find(title):text.lower().find(title) + len(title)]) or title
        scr = f'tell application "Notes" to make new note at default account with properties {{name:"{title}", body:"<div><h1>{title}</h1></div>"}}'
        if DRY:
            _osa(scr)
        else:  # Notes scripting can take 30-60 s on first use: run it in the background, answer at once, never retry (no duplicates)
            threading.Thread(target=lambda: subprocess.run(["osascript", "-e", scr], capture_output=True, timeout=180), daemon=True).start()
        return f"Creating the note \"{title}\" in Notes, {addr}. It can take a moment. I'll leave it there."
    # ---- TextEdit: new document with a sentence (left unsaved)
    m = re.search(r"(?:new|blank)\s+textedit\s+(?:document|doc|file)\s+and\s+(?:type|write)\s+(?:the\s+sentence\s*:?\s*)?[\"']?(.+?)[\"']?(?:\s+(?:do not|don'?t|but)\s.*)?$", e)
    if m:
        sent = m.group(1).strip().replace('"', "")
        orig = text.lower().find(sent)
        sent = text[orig:orig + len(sent)] if orig >= 0 else sent
        _osa(f'tell application "TextEdit"\nactivate\nmake new document\nset text of front document to "{sent}"\nend tell')
        return f"Typed it in a new TextEdit document, unsaved, {addr}."
    # ---- chat apps: open and focus search, type the name, never send
    m = re.search(r"open\s+(telegram|whatsapp|slack|messages|discord|signal)\s+and\s+search\s+(?:for\s+)?(?:a\s+|the\s+)?(?:chat\s+|contact\s+|conversation\s+)?(?:named\s+|called\s+|with\s+)?[\"']?([\w .@+'-]+?)[\"']?(?:\s*,?\s*(?:but|and)\s.*)?$", e)
    if m:
        app = find_app(m.group(1)) or m.group(1).title()
        who = text[text.lower().find(m.group(2)):][:len(m.group(2))] or m.group(2)
        # no mouse, no raise needed: AX-focus the search field, then send the keys to that app only (type --app)
        r = _ctl("do", f"open-app {app}" + (" --front" if fr else ""), "sleep 0.6", f"press Search --app {app} --role TextField", "sleep 0.2", f"type {who} --app {app}", timeout=30)
        _LAST_APP["name"] = app
        if r.get("ok"):
            return f"{app} is open and searching {who}. Nothing sent, {addr}."
        return f"Couldn't drive {app}: {str(r.get('steps', [{}])[-1].get('error', r.get('error', '')))[:80]}"
    # ---- unsaved-work sheet: "don't save"
    if re.fullmatch(r"(?:click |press |choose |hit )?(?:the )?don'?t save(?: button)?", e):
        r = _ctl("press", "Don't Save")
        return f"Not saved, {addr}." if r.get("ok") else f"I don't see a Don't Save button, {addr}."
    return None


def handle(text, say, addr="sir"):
    """Run a simple command and return the reply, or None (then the brain thinks). Handles the address commands first."""
    try:
        import address as _address
        import ui_bridge
        conf = _address.apply_spoken(text, ui_bridge.get, ui_bridge.set_setting)
        if conf:
            return conf
    except Exception as ex:
        print("[address]", str(ex)[:120])
    r = _handle(text, say, addr)
    if r and not addr:  # user chose "no address": drop the dangling ', sir'-style gaps
        r = re.sub(r"\s*,\s*(?=[.!?]|$)", "", r)
        r = re.sub(r"^\s*,\s*", "", r)
    return r


def _handle(text, say, addr="sir"):
    """Выполняет простую команду и возвращает фразу для ответа, или None — тогда думает мозг."""
    t = text.lower().strip(" .!?,…")
    t = re.sub(r"^(джарвис|alfred|жарвис)[,\s]+", "", t)
    A = addr.capitalize()

    # ---------- English (instant, no brain)
    e = re.sub(r"^(hey |ok )?(alfred)[,\s]+", "", t)
    e = re.sub(r"^(please|can you|could you)\s+", "", e)
    d = parse_dial(e)
    if d:
        try:
            import ui_bridge
            ui_bridge.set_setting(d[0], d[1])
            ui_bridge.send_settings()
        except Exception as ex:
            print("[dial]", str(ex)[:120])
        return dial_reply(*d)
    try:
        _cf = control_fast(e, addr, text)
    except Exception as ex:
        print("[control_fast]", str(ex)[:120])
        _cf = None
    if _cf:
        return _cf
    if re.search(r"\b(what time is it|what'?s the time|time is it)\b", e):
        n = dt.datetime.now()
        return f"It's {n.strftime('%I:%M').lstrip('0')}, {addr}."
    m = re.match(r"^(?:tell|ask|have|get|make)\s+(?:claude|cloud|clod|clawed)(?:\s+code)?\s+(?:to\s+)?(.{6,})$", e) or \
        re.match(r"^(?:new |start a |open a )?(?:claude|cloud|clod)(?: code)? (?:task|job|chat)[:,]?\s+(?:to\s+)?(.{6,})$", e)
    if m:
        r = claude_task(text[len(text) - len(m.group(1)):] if text.lower().endswith(m.group(1)) else m.group(1), addr)
        if r:
            return r
    if re.search(r"\b(claude|cloud|clod)\b.*\b(chats?|sessions?|doing|up to|status|progress)\b|\bstatus of (my )?(chats|sessions)\b|\bhow are my (chats|sessions)\b", e):
        import claude_watch
        import panels
        chats = claude_watch.recent()
        if chats:
            panels.push(claude_watch.summary_panel(chats))
        return claude_watch.spoken(chats, addr)
    if re.search(r"\b(run (a )?diagnostics?|diagnostics|system (status|check|report)|status report|how('?s| is) (my|the) (mac|system))\b", e):
        return diagnostics(addr)
    if re.search(r"\b(open|show)( me)? (the |my |today'?s |your )?(log|journal|history)\b|\bwhat did (we|you|i) do today\b|\bconversation log\b", e):
        import journal
        p, es = journal.build()
        return f"Today's log is open, {addr}. {sum(1 for x in es if x[1] == 'you')} requests so far."
    # ---- instant Mac controls (no brain, ~0.1 s)
    if re.fullmatch(r"(lock (the |my )?(screen|mac|computer|laptop)|screen off|turn off (the )?screen|sleep (the )?(screen|display))", e):
        threading.Timer(1.6, lambda: subprocess.run(["pmset", "displaysleepnow"])).start()
        return f"Locking up, {addr}."
    if re.fullmatch(r"(take (a )?screenshot|screenshot( (this|it|the screen))?|capture (the )?screen)", e):
        out = os.path.expanduser(f"~/Desktop/Screenshot {dt.datetime.now().strftime('%Y-%m-%d at %H.%M.%S')}.png")
        subprocess.run(["screencapture", "-x", out])
        return f"Screenshot saved to your Desktop, {addr}."
    if re.search(r"\b(dark mode|light mode|night mode)\b", e) and re.search(r"\b(turn|switch|toggle|set|go|enable|disable|on|off)\b", e):
        want = "not dark mode" if "toggle" in e else "false" if ("light" in e or " off" in e or "disable" in e) else "true"
        _osa(f'tell application "System Events" to tell appearance preferences to set dark mode to {want}')
        return f"Done, {addr}."
    if re.search(r"\b(battery|charge)\b", e) and re.search(r"\b(how much|level|left|status|percent|what'?s)\b", e):
        out = subprocess.run(["pmset", "-g", "batt"], capture_output=True, text=True).stdout
        m = re.search(r"(\d+)%", out)
        if m:
            plug = "charging" if "AC Power" in out else "on battery"
            return f"Battery at {m.group(1)} percent, {plug}, {addr}."
    if re.fullmatch(r"(hide (all|everything|all windows|the windows)|show (me )?(the )?desktop|clear (my )?desk(top)?)", e):
        _osa('tell application "System Events" to set visible of every application process whose visible is true and name is not "Finder" to false')
        return f"Desk cleared, {addr}."
    if re.fullmatch(r"(empty|empty the) trash", e):
        return f"I don't empty the trash, {addr}. That one is yours."
    m = re.search(r"(?:set )?(?:the )?volume (?:to |at )?(\d{1,3})", e)
    if m:
        v = int(max(0, min(100, int(m.group(1)))))
        _osa(f"set volume output volume {v}")
        return f"Volume {v}."
    if re.fullmatch(r"(turn it |make it )?(down|quieter|lower|volume down)( a bit)?", e):
        cur = int(_osa("output volume of (get volume settings)") or 50)
        _osa(f"set volume output volume {max(0, cur - 15)}")
        return "Quieter."
    if re.fullmatch(r"(turn it |make it )?(up|louder|volume up)( a bit)?", e):
        cur = int(_osa("output volume of (get volume settings)") or 50)
        _osa(f"set volume output volume {min(100, cur + 15)}")
        return "Louder."
    if re.fullmatch(r"(mute|mute (the )?sound)", e):
        _osa("set volume with output muted")
        return "Muted."
    if re.fullmatch(r"(pause|pause (the )?music|stop (the )?music)", e):
        _osa(f'tell application "{_media_app()}" to pause')
        return "Paused."
    if re.fullmatch(r"(next|next (song|track)|skip( (it|this))?)", e):
        _osa(f'tell application "{_media_app()}" to next track')
        return "Next track."
    if re.fullmatch(r"(previous|previous (song|track)|go back)", e):
        _osa(f'tell application "{_media_app()}" to previous track')
        return "Previous track."
    if re.fullmatch(r"(play|play (some )?music|resume( (the )?music)?)", e):
        _osa(f'tell application "{_media_app()}" to play')
        return "Playing."
    m = re.search(r"timer for (\d+|an?|one|two|three|five|ten|fifteen|twenty|thirty)\s*(second|sec|minute|min|hour)", e)
    if m:
        words = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "five": 5, "ten": 10, "fifteen": 15, "twenty": 20, "thirty": 30}
        v = int(m.group(1)) if m.group(1).isdigit() else words[m.group(1)]
        secs = v * (3600 if m.group(2).startswith("hour") else 60 if m.group(2).startswith("min") else 1)
        def ring_en():
            from voice import chime
            chime("Glass")
            say(f"{A}, your timer is done.")
        th = threading.Timer(secs, ring_en)
        th.daemon = True
        th.start()
        return f"Timer set, {addr}."
    m = re.fullmatch(r"(?:search|google|look up|look for)\s+(?:for\s+)?(.+?)\s+on\s+youtube|(?:youtube|search youtube for|search youtube)\s+(.+)", e)
    if m:
        return web_search(m.group(1) or m.group(2), youtube=True)
    m = re.fullmatch(r"(?:search(?: the web| google)?(?: for)?|google|look up|search for)\s+(.{2,})", e)
    if m:
        return web_search(m.group(1))
    m = re.fullmatch(r"(?:quit|close|exit|kill)\s+(?:the\s+|my\s+)?(.+?)(?:\s+app)?", e)
    if m and len(m.group(1).split()) <= 3 and m.group(1) not in ("it", "this", "that", "window", "tab", "everything", "all"):
        app = find_app(m.group(1).strip())
        if app:
            if DRY:
                LAST_CMDS.append(["osascript", f'quit {app}'])
                return f"Quit {app}, {addr}."
            r = _ctl("quit", app)
            if r.get("ok") and r.get("quit", True):
                return f"Quit {app}, {addr}."
            if r.get("ok"):
                return f"{app} is asking to save first, {addr}. Say Don't Save or Cancel."
            _osa(f'tell application "{app}" to quit')
            return f"Quit {app}, {addr}."
    if re.fullmatch(r"(open |make |start )?(a )?new (browser )?tab", e):
        if DRY:
            LAST_CMDS.append(["osascript", "cmd+t"])
        else:
            _osa('tell application "System Events" to keystroke "t" using command down')
        return "New tab."
    if re.fullmatch(r"play ?/? ?pause( (the )?music)?|toggle (the )?music|(un)?pause( (the )?music)?", e) and not e.startswith("pause"):
        _osa(f'tell application "{_media_app()}" to playpause')
        return "Done."
    if re.fullmatch(r"(alfred,? )?(quit|close|exit|shut down|turn off)( yourself| alfred)?", e):
        subprocess.Popen(["osascript", "-e", 'tell application id "com.alfred.app" to quit'])
        return f"Shutting down, {addr}."
    _nuanced = re.search(r"\b(don'?t|do not|but|tell me|where|which|name|without)\b", e)
    m = None if _nuanced else re.fullmatch(r"(?:open|show|find|pull up|get|launch)\s+(?:me\s+)?(?:the\s+|my\s+)?((?:last|latest|recent|newest)\s+(?:screenshot|screen shot)|screenshot)", e)
    if m:
        return open_file(m.group(1), addr)
    m = re.fullmatch(r"(?:open|launch|start)\s+(?:the\s+|my\s+)?(.+?)(?:\s+app)?", e)
    if m and len(m.group(1).split()) <= 3:
        target = m.group(1).strip()
        if target in SITES:
            subprocess.run(["open", SITES[target]], timeout=15)
            return f"Opening, {addr}."
        app = find_app(target)
        if app:
            r = subprocess.run(["open", "-a", app], capture_output=True, timeout=20)
            if r.returncode == 0:
                return f"{app} is open, {addr}."
    m2 = None if _nuanced else re.fullmatch(r"(?:open|show|pull up|find|launch)\s+(?:me\s+)?(.{3,60})", e)
    if m2:
        q = m2.group(1)
        if q and not re.search(r"\b(http|www\.|\.com)\b", q) and q not in SITES and not find_app(q):
            return open_file(q, addr)

    if re.search(r"(который час|сколько (сейчас )?времени|сколько время)", t):
        n = dt.datetime.now()
        return f"Сейчас {n.hour}:{n.minute:02d}, {addr}."

    m = re.search(r"громкост\w*\s+(?:на\s+)?(.+)$", t)
    if m:
        v = parse_num(m.group(1))
        if v is not None:
            v = int(max(0, min(100, v)))
            _osa(f"set volume output volume {v}")
            return f"Громкость {v}."
    if re.fullmatch(r"(сделай )?(тише|потише)", t):
        cur = int(_osa("output volume of (get volume settings)") or 50)
        _osa(f"set volume output volume {max(0, cur - 15)}")
        return "Тише."
    if re.fullmatch(r"(сделай )?(громче|погромче)", t):
        cur = int(_osa("output volume of (get volume settings)") or 50)
        _osa(f"set volume output volume {min(100, cur + 15)}")
        return "Громче."
    if re.fullmatch(r"(выключи звук|без звука|убери звук)", t):
        _osa("set volume with output muted")
        return "Звук выключен."

    if re.fullmatch(r"(пауза|поставь на паузу|останови музыку|стоп музыка|выключи музыку)", t):
        _osa(f'tell application "{_media_app()}" to pause')
        return "Пауза."
    if re.fullmatch(r"(следующ\w+ (трек|песн\w+)|дальше|переключи (трек|песню))", t):
        _osa(f'tell application "{_media_app()}" to next track')
        return "Следующий трек."
    if re.fullmatch(r"(предыдущ\w+ (трек|песн\w+)|назад трек)", t):
        _osa(f'tell application "{_media_app()}" to previous track')
        return "Предыдущий трек."
    if re.fullmatch(r"(включи музыку|продолжи музыку|играй музыку|музыку)", t):
        _osa(f'tell application "{_media_app()}" to play')
        return "Включаю."

    m = re.search(r"таймер на (.+?)\s*(секунд\w*|сек|минут\w*|мин|час\w*)", t)
    if m:
        v = parse_num(m.group(1)) or (1 if m.group(1).strip() in ("", "одну", "один") else None)
        if v:
            unit = m.group(2)
            secs = int(v * (3600 if unit.startswith("час") else 60 if unit.startswith("мин") else 1))
            def ring():
                from voice import chime
                chime("Glass")
                say(f"{A}, время вышло.")
            th = threading.Timer(secs, ring)
            th.daemon = True
            th.start()
            mins, s = divmod(secs, 60)
            return f"Таймер на {mins} минут{' ' + str(s) + ' секунд' if s else ''} запущен." if mins else f"Таймер на {s} секунд запущен."

    # ---------- узбекский
    u = re.sub(r"[ʻ‘’`]", "'", t)
    if re.search(r"(soat necha|vaqt qancha|hozir soat)", u):
        n = dt.datetime.now()
        return f"Soat {n.hour}:{n.minute:02d}, ser."
    m = re.search(r"ovoz\w*\s+(.+?)(?:\s+qil)?$", u)
    if m and parse_num(m.group(1)) is not None:
        v = int(max(0, min(100, parse_num(m.group(1)))))
        _osa(f"set volume output volume {v}")
        return f"Ovoz {v}."
    if re.search(r"(pasaytir|pastroq|sekinroq)", u):
        cur = int(_osa("output volume of (get volume settings)") or 50)
        _osa(f"set volume output volume {max(0, cur - 15)}")
        return "Pasaytirdim."
    if re.search(r"(baland qil|balandroq|ko'tar)", u):
        cur = int(_osa("output volume of (get volume settings)") or 50)
        _osa(f"set volume output volume {min(100, cur + 15)}")
        return "Balandladim."
    if re.search(r"(musiqa\w* (to'xtat|o'chir)|pauza|to'xtat)$", u):
        _osa(f'tell application "{_media_app()}" to pause')
        return "Pauza."
    if re.search(r"^(keyingi|keyingisi)( qo'shiq| trek)?$", u):
        _osa(f'tell application "{_media_app()}" to next track')
        return "Keyingi qo'shiq."
    if re.search(r"^(oldingi|oldingisi)( qo'shiq| trek)?$", u):
        _osa(f'tell application "{_media_app()}" to previous track')
        return "Oldingi qo'shiq."
    if re.search(r"musiqa\w* (qo'y|yoq|ijro et)", u):
        _osa(f'tell application "{_media_app()}" to play')
        return "Qo'yaman."
    m = re.search(r"taymer\w*\s+(.+?)\s*(daqiqa|minut|soniya|sekund|soat)", u)
    if m and parse_num(m.group(1)):
        secs = int(parse_num(m.group(1)) * (3600 if m.group(2) == "soat" else 60 if m.group(2) in ("daqiqa", "minut") else 1))
        def ring_uz():
            from voice import chime
            chime("Glass")
            say("Ser, vaqt tugadi.")
        th = threading.Timer(secs, ring_uz)
        th.daemon = True
        th.start()
        return "Taymer qo'yildi."
    m = re.fullmatch(r"(.+?)(?:ni|ga)?\s+(och|ochib ber|ochgin|ishga tushir)", u) or re.fullmatch(r"(?:och|ochib ber)\s+(.+)", u)
    if m:
        target = re.sub(r"(ni|ga)$", "", m.group(1).strip()).strip()
        if target in SITES:
            subprocess.run(["open", SITES[target]], timeout=15)
            return "Ochyapman."
        app = find_app(target)
        if app:
            r = subprocess.run(["open", "-a", app], capture_output=True, timeout=20)
            if r.returncode == 0:
                return f"{app} ochildi."

    m = re.fullmatch(r"(открой|запусти|включи|открыть)\s+(.+)", t)
    if m:
        target = m.group(2).strip()
        if target in SITES:
            subprocess.run(["open", SITES[target]], timeout=15)
            return "Открываю."
        app = find_app(target)
        if app:
            r = subprocess.run(["open", "-a", app], capture_output=True, timeout=20)
            if r.returncode == 0:
                return f"Открываю {app}."
    return None
