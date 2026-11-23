"""Alfred nudges: calm, proactive, rate-limited. Read-only sources, fail quietly.

start(emit, say, get_settings) -> daemon thread.
  emit(type, **fields)   ui_bridge.emit
  say(text)              speak (only called when silent is off)
  get_settings()         dict (silent, quiet_class, class_hours, nudges, address)
"""
from alfred_home import HOME_STR as _AH, CTL as _CTL
import datetime as dt
import glob
import os
import re
import subprocess
import threading
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
BRAIN = _AH + "/data/brain-copy"
MIN_GAP = 20 * 60
_DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
_last_nudge = 0.0
_fired = set()          # dedupe keys
_cal_cache = (0.0, [])


# ------------------------------------------------------------ helpers
def _addr(s):
    import address as _address
    w = _address.word((s or {}).get("address", "sir"), (s or {}).get("name", ""))
    return f", {w}" if w else ""


def _class_window(s, now):
    """(start_min, end_min) if today is a class day else None."""
    m = re.match(r"\s*([A-Za-z,\- ]+?)\s+(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})\s*$", s.get("class_hours") or "")
    if not m:
        return None
    try:
        days = set()
        for part in re.split(r"[,\s]+", m.group(1).strip()):
            if "-" in part:
                a, b = (_DAYS.index(x[:3].lower()) for x in part.split("-", 1))
                days |= set(range(a, b + 1))
            elif part:
                days.add(_DAYS.index(part[:3].lower()))
        if now.weekday() not in days:
            return None
        return int(m.group(2)) * 60 + int(m.group(3)), int(m.group(4)) * 60 + int(m.group(5))
    except Exception:
        return None


def _in_class(s, now):
    w = _class_window(s, now)
    return bool(w and w[0] <= now.hour * 60 + now.minute < w[1])


# ------------------------------------------------------------ calendar
_AS = '''
set out to ""
set t0 to current date
set t1 to t0 + 24 * hours
tell application "Calendar"
  repeat with c in calendars
    try
      repeat with e in (every event of c whose start date >= t0 and start date <= t1)
        set out to out & (summary of e) & "|" & ((start date of e) as «class isot» as string) & "|" & ((end date of e) as «class isot» as string) & linefeed
      end repeat
    end try
  end repeat
end tell
return out
'''


def calendar_events(now=None):
    """[(title, start_dt, end_dt)] for next 24h. Cached 5 min; [] on any failure."""
    global _cal_cache
    if time.time() - _cal_cache[0] < 300:
        return _cal_cache[1]
    evs = []
    try:
        ib = subprocess.run(["which", "icalBuddy"], capture_output=True, text=True, timeout=3).stdout.strip()
        if ib:
            out = subprocess.run([ib, "-nc", "-nrd", "-ea", "-iep", "title,datetime", "-df", "%Y-%m-%d", "-tf", "%H:%M",
                                  "eventsToday+1"], capture_output=True, text=True, timeout=10).stdout
            title = None
            for ln in out.splitlines():
                if ln.startswith("•"):
                    title = ln.lstrip("• ").strip()
                elif title:
                    m = re.search(r"(\d{4}-\d{2}-\d{2}) at (\d{2}:\d{2}) - (\d{2}:\d{2})", ln)
                    if m:
                        evs.append((title, dt.datetime.fromisoformat(f"{m[1]}T{m[2]}"),
                                    dt.datetime.fromisoformat(f"{m[1]}T{m[3]}")))
                        title = None
        else:
            r = subprocess.run(["osascript", "-e", _AS], capture_output=True, text=True, timeout=15)
            for ln in r.stdout.splitlines():
                p = ln.rsplit("|", 2)
                if len(p) == 3:
                    evs.append((p[0], dt.datetime.fromisoformat(p[1]), dt.datetime.fromisoformat(p[2])))
    except Exception:
        evs = []
    evs.sort(key=lambda e: e[1])
    _cal_cache = (time.time(), evs)
    return evs


# ------------------------------------------------------------ deadlines
_ISO = re.compile(r"(?:due|deadline|by)\D{0,12}?(\d{4}-\d{2}-\d{2})", re.I)
_RU = re.compile(r"(?:до|дедлайн)\s+(\d{1,2})[./](\d{1,2})(?:[./](\d{2,4}))?", re.I)
_ISO_LATE = re.compile(r"(\d{4}-\d{2}-\d{2})\s*\(?\s*(?:due|deadline)", re.I)


def deadlines(today=None, limit=3):
    """[(date, label)] upcoming within 14 days (or overdue by <=1 day), soonest first."""
    today = today or dt.date.today()
    found = {}
    try:
        for path in glob.glob(os.path.join(BRAIN, "**", "*.md"), recursive=True):
            base = os.path.basename(path)
            try:
                with open(path, encoding="utf-8", errors="ignore") as f:
                    lines = f.read().splitlines()
            except OSError:
                continue
            proj = os.path.basename(os.path.dirname(path))
            for ln in lines:
                is_status = base == "Status.md" or "next step" in ln.lower()
                if not (is_status or re.search(r"due|deadline|дедлайн", ln, re.I)):
                    continue
                ds = []
                for m in _ISO.finditer(ln):
                    ds.append(m[1])
                for m in _ISO_LATE.finditer(ln):
                    ds.append(m[1])
                for m in _RU.finditer(ln):
                    y = int(m[3]) if m[3] else today.year
                    y = y + 2000 if y < 100 else y
                    ds.append(f"{y:04d}-{int(m[2]):02d}-{int(m[1]):02d}")
                for d in ds:
                    try:
                        day = dt.date.fromisoformat(d)
                    except ValueError:
                        continue
                    if -1 <= (day - today).days <= 14:
                        label = re.sub(r"[|*`#>\[\]]", " ", ln)
                        label = re.sub(r"(?i)(next step|due|deadline|до|дедлайн|status)\W*", " ", label)
                        label = re.sub(r"\d{4}-\d{2}-\d{2}|\d{1,2}[./]\d{1,2}([./]\d{2,4})?", " ", label)
                        label = " ".join(label.split())[:40] or proj
                        found[(day, label)] = proj
    except Exception:
        pass
    return sorted(found)[:limit]


def _when(day, today):
    n = (day - today).days
    if n < 0:
        return "overdue"
    if n == 0:
        return "today"
    if n == 1:
        return "tomorrow"
    num = {2: "Two", 3: "Three", 4: "Four", 5: "Five", 6: "Six", 7: "Seven"}.get(n, str(n))
    return f"{day.strftime('%A')}. {num} days"


def deadline_lines(today=None):
    today = today or dt.date.today()
    out = []
    for day, label in deadlines(today):
        w = _when(day, today)
        out.append(f"{label} due {w}" if w in ("today", "tomorrow", "overdue") else f"{label} due {w}")
    return out


# ------------------------------------------------------------ plan (pure, testable)
def plan(now, s, events, dls, state):
    """Return list of (key, kind, text, is_class_end). `state` = dict with 'morning_done' date."""
    out = []
    a = _addr(s)
    # class end
    w = _class_window(s, now)
    if w and 0 <= now.hour * 60 + now.minute - w[1] < 10:
        out.append((f"classend-{now.date()}", "class_end", f"Lecture's over{a}.", True))
    # event reminders
    for title, st, en in events:
        mins = (st - now).total_seconds() / 60
        if 0 < mins <= 10:
            out.append((f"ev-{title}-{st:%Y%m%d%H%M}", "event", f"{title} in {int(round(mins)) or 1} minutes{a}.", False))
    # morning brief
    if now.hour >= 8 and state.get("morning_done") != now.date() and now.hour < 13:
        today_n = sum(1 for _, st, _ in events if st.date() == now.date() and st >= now.replace(hour=0, minute=0))
        bits = [f"{today_n} event{'s' if today_n != 1 else ''} today" if today_n else "No events today"]
        if dls:
            bits.append(dls[0])
        out.append((f"morning-{now.date()}", "morning", f"Good morning{a}. " + ". ".join(bits) + ".", False))
        for extra in dls[1:3]:
            out[-1] = (out[-1][0], out[-1][1], out[-1][2].rstrip(".") + f". {extra}.", False)
    return out


# ------------------------------------------------------------ runtime
def _deliver(emit, say, s, kind, text, class_end):
    global _last_nudge
    now = time.time()
    if now - _last_nudge < MIN_GAP:
        return False
    d = dt.datetime.now()
    if not class_end and s.get("quiet_class", True) and _in_class(s, d):
        return False
    quiet = bool(s.get("silent"))
    if quiet:
        emit("toast", text=text)
    else:
        emit("nudge", text=text, kind=kind)
        try:
            say(text)
        except Exception:
            pass
    _last_nudge = now
    return True


def _loop(emit, say, get_settings):
    state = {}
    while True:
        try:
            s = get_settings() or {}
            if s.get("nudges", True) and not s.get("mic_off_nudges"):
                now = dt.datetime.now()
                evs = calendar_events() if (now.minute % 1 == 0) else []
                dls = deadline_lines(now.date()) if now.hour >= 8 and state.get("morning_done") != now.date() else []
                for key, kind, text, ce in plan(now, s, evs, dls, state):
                    if key in _fired:
                        continue
                    if _deliver(emit, say, s, kind, text, ce):
                        _fired.add(key)
                        if kind == "morning":
                            state["morning_done"] = now.date()
                    elif kind == "event" and (now - now).total_seconds() == 0:
                        pass
        except Exception:
            pass
        time.sleep(60)


def start(emit, say, get_settings):
    t = threading.Thread(target=_loop, args=(emit, say, get_settings), daemon=True, name="nudges")
    t.start()
    return t


if __name__ == "__main__":
    now = dt.datetime.now()
    s = {"address": "sir", "class_hours": "Mon-Thu 10:00-14:00", "quiet_class": True, "silent": True, "nudges": True}
    try:
        import json
        s.update({k: v for k, v in json.load(open(os.path.join(ROOT, "data/ui/settings.json"))).items()
                  if k in ("address", "name", "class_hours", "quiet_class", "nudges")})
    except Exception:
        pass
    evs = calendar_events()
    dls = deadline_lines(now.date())
    print(f"now {now:%a %Y-%m-%d %H:%M}  nudges={s.get('nudges', True)}  class_now={_in_class(s, now)}")
    print(f"calendar events next 24h: {len(evs)}")
    for t, st, en in evs[:5]:
        print(f"  {st:%a %H:%M}-{en:%H:%M} {t}")
    print(f"deadlines: {dls or 'none found'}")
    probe = now.replace(hour=max(now.hour, 8), minute=0)
    for key, kind, text, ce in plan(probe, s, evs, dls, {}):
        print(f"WOULD NUDGE [{kind}] {text}")
    w = _class_window(s, now)
    if w:
        end = now.replace(hour=w[1] // 60, minute=w[1] % 60)
        for key, kind, text, ce in plan(end + dt.timedelta(minutes=1), s, evs, dls, {"morning_done": now.date()}):
            print(f"WOULD NUDGE at class end [{kind}] {text}")
