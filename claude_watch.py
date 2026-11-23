"""Claude chat watcher (read-only).

Looks at the Claude Code chat logs on this Mac (~/.claude/projects/*/*.jsonl) and tells Alfred when
a chat has FINISHED a piece of work, or seems to be WAITING for the owner (an approval or a question).
Nothing is sent anywhere and nothing is written: it only reads the end of each log file.

  python claude_watch.py        print the chats active in the last 3 hours
"""
from alfred_home import HOME_STR as _AH, CTL as _CTL
import datetime as dt
import json
import os
import threading
import time
from pathlib import Path

ROOT = Path.home() / ".claude" / "projects"
ALFRED_DIRS = (_AH,)  # Alfred's own brain — never report it


def _ts(s):
    try:
        return dt.datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def _tail_lines(path, size=200_000):
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            n = f.tell()
            f.seek(max(0, n - size))
            data = f.read()
        lines = data.decode("utf-8", "ignore").splitlines()
        return lines[1:] if n > size else lines
    except OSError:
        return []


def _is_prompt(x):
    """A real message typed by the owner (not a tool result)."""
    if x.get("type") != "user" or x.get("isMeta"):
        return False
    c = (x.get("message") or {}).get("content")
    if isinstance(c, str):
        return not c.startswith("<")
    if isinstance(c, list):
        return any(i.get("type") == "text" and not str(i.get("text", "")).startswith("<") for i in c if isinstance(i, dict))
    return False


def chat_state(path, now=None):
    now = now or time.time()
    title = cwd = entry = None
    last = prompt_t = None
    for line in _tail_lines(path):
        try:
            x = json.loads(line)
        except ValueError:
            continue
        t = x.get("type")
        if t == "custom-title":
            title = x.get("customTitle") or title
            continue
        if t not in ("user", "assistant"):
            continue
        if x.get("isSidechain"):
            continue
        cwd = x.get("cwd") or cwd
        entry = x.get("entrypoint") or entry
        last = x
        if _is_prompt(x):
            prompt_t = _ts(x.get("timestamp"))
    if not last:
        return None
    if cwd and cwd.startswith(ALFRED_DIRS):
        return None
    if entry == "sdk-cli":  # scripted runs, not a chat
        return None
    lt = _ts(last.get("timestamp")) or os.path.getmtime(path)
    msg = last.get("message") or {}
    kinds = [i.get("type") for i in msg.get("content", []) if isinstance(i, dict)] if isinstance(msg.get("content"), list) else []
    idle = now - lt
    if last["type"] == "assistant" and msg.get("stop_reason") == "end_turn":
        status = "done"
    elif last["type"] == "assistant" and "tool_use" in kinds:
        status = "waiting" if idle > 150 else "working"
    else:
        status = "working" if idle < 600 else "stalled"
    if not title:
        base = os.path.basename(cwd or "") or "Claude chat"
        title = "a scratch chat" if base.startswith("scratch-") else base
    return {"id": path.stem, "title": title, "status": status, "last": lt, "idle": idle,
            "work_seconds": (lt - prompt_t) if (prompt_t and status == "done") else None,
            "uuid": last.get("uuid"), "cwd": cwd}


def recent(hours=3.0):
    now = time.time()
    out = []
    for p in ROOT.glob("*/*.jsonl"):
        try:
            if now - p.stat().st_mtime > hours * 3600:
                continue
        except OSError:
            continue
        s = chat_state(p, now)
        if s and s["idle"] < hours * 3600:
            out.append(s)
    return sorted(out, key=lambda s: -s["last"])


class Watcher(threading.Thread):
    """Calls on_event({"kind": "done"|"waiting", "title": ...}) once per finished turn / per wait."""

    def __init__(self, on_event, min_work=45, every=5):
        super().__init__(daemon=True)
        self.on_event, self.min_work, self.every = on_event, min_work, every
        self.seen = {}
        self.started = time.time()

    def run(self):
        for s in recent(6):  # what is already finished before Alfred started is old news
            self.seen[s["id"]] = (s["status"], s["uuid"])
        while True:
            time.sleep(self.every)
            try:
                self.tick()
            except Exception as e:
                print("[claude watch]", e)

    def tick(self):
        now = time.time()
        for p in ROOT.glob("*/*.jsonl"):
            try:
                if now - p.stat().st_mtime > 600:
                    continue
            except OSError:
                continue
            s = chat_state(p, now)
            if not s:
                continue
            key = (s["status"], s["uuid"])
            if self.seen.get(s["id"]) == key:
                continue
            self.seen[s["id"]] = key
            if s["status"] == "done" and (s["work_seconds"] or 0) >= self.min_work and s["idle"] < 180:
                self.on_event({"kind": "done", "title": s["title"], "seconds": s["work_seconds"]})
            elif s["status"] == "waiting" and s["idle"] < 900:
                self.on_event({"kind": "waiting", "title": s["title"]})


def _ago(sec):
    sec = int(sec)
    if sec < 90:
        return "just now"
    if sec < 3600:
        return f"{sec // 60} min ago"
    return f"{sec // 3600} h {sec % 3600 // 60} min ago"


def summary_panel(chats):
    label = {"done": "✓ finished", "working": "● working", "waiting": "⏸ needs you", "stalled": "– idle"}
    rows = [[c["title"][:42], label.get(c["status"], c["status"]), _ago(c["idle"])] for c in chats[:8]]
    return {"type": "table", "title": "Claude chats", "columns": ["Chat", "Status", "Last activity"], "rows": rows}


def spoken(chats, addr="sir"):
    if not chats:
        return f"No Claude chats were active in the last three hours, {addr}."
    w = [c for c in chats if c["status"] == "working"]
    q = [c for c in chats if c["status"] == "waiting"]
    d = [c for c in chats if c["status"] == "done" and c["idle"] < 3600]
    parts = []
    if w:
        parts.append(f"{len(w)} working" if len(w) > 1 else f"{w[0]['title']} is working")
    if q:
        parts.append(f"{q[0]['title']} needs you" if len(q) == 1 else f"{len(q)} need you")
    if d:
        parts.append(f"{len(d)} finished this hour")
    if not parts:
        return f"All quiet, {addr}. Nothing running right now. Details on screen."
    return f"{', '.join(parts).capitalize()}, {addr}. Details on screen."


if __name__ == "__main__":
    for c in recent():
        print(f"{c['status']:8} {_ago(c['idle']):>14}  {c['title']}")
