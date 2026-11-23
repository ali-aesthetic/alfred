#!/usr/bin/env python3
"""Alfred Brain: Alfred's own Obsidian vault (~/Documents/Alfred Brain).

  vault.py            sync now (memory, lessons, today's log) and print the path
  vault.py --open     sync, then open the vault in Obsidian

What lands in the vault (Obsidian-friendly markdown, [[links]] between notes):
  Home.md                 start page
  Notes for Alfred.md     YOU write here; Alfred reads it before every answer (brain_cc.py)
  Memory/About the user.md     what Alfred remembers (copy of data/memory.md)
  Memory/Lessons.md       what Alfred learned from mistakes
  Daily/YYYY-MM-DD.md     the day's conversation, one note per day (the long-term log)
Sync is one-way (Alfred -> vault) except "Notes for Alfred.md". alfred.py runs it every 5 minutes.
"""
import datetime as dt
import json
import subprocess
import sys
from pathlib import Path

HOME = Path(__file__).resolve().parent
VAULT = Path.home() / "Documents" / "Alfred Brain"
NOTES = VAULT / "Notes for Alfred.md"
TOOL = {"Bash": "ran", "Write": "wrote", "Edit": "edited", "Read": "read", "WebSearch": "searched",
        "WebFetch": "opened page", "Glob": "looked for files", "Grep": "searched files", "Skill": "used skill"}


def _w(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists() or path.read_text(encoding="utf-8") != text:
        path.write_text(text, encoding="utf-8")


def notes_text():
    try:
        t = NOTES.read_text(encoding="utf-8")
        return t.split("---", 2)[-1].strip() if t.startswith("---") else t.strip()
    except OSError:
        return ""


def day_note(day):
    rows = []
    try:
        lines = (HOME / "data" / "log.jsonl").read_text(encoding="utf-8").splitlines()
    except OSError:
        lines = []
    for line in lines:
        try:
            x = json.loads(line)
        except ValueError:
            continue
        t = dt.datetime.fromtimestamp(x.get("ts", 0))
        if t.date() != day:
            continue
        k, hm = x.get("type"), f"{t:%H:%M}"
        if k == "request":
            rows.append(f"**{hm} User:** {x.get('text', '')}")
        elif k == "reply" and x.get("text"):
            rows.append(f"**{hm} Alfred:** {x['text']}")
        elif k == "quick":
            rows.append(f"**{hm} User:** {x.get('text', '')}\n**{hm} Alfred:** {x.get('reply', '')}")
        elif k == "action":
            rows.append(f"- {hm} {TOOL.get(x.get('tool'), x.get('tool', ''))}: `{x.get('detail', '')}`")
        elif k == "holo":
            rows.append(f"- {hm} hologram: {x.get('title', '')}")
        elif k == "protocol":
            rows.append(f"- {hm} protocol: {x.get('name', '')}")
        elif k == "error":
            rows.append(f"- {hm} ⚠ {x.get('where', '')}: {x.get('error', '')}")
    if not rows:
        return None
    n = sum(1 for r in rows if r.startswith("**") and "User:" in r.split("\n")[0])
    return (f"---\ndate: {day.isoformat()}\ntags: [alfred, daily]\nasked: {n}\n---\n# {day:%A %d %B %Y}\n\n"
            f"[[Home]] · [[About the user]]\n\n" + "\n\n".join(rows) + "\n")


def sync(days=2):
    VAULT.mkdir(parents=True, exist_ok=True)
    _w(VAULT / ".obsidian" / "app.json", '{"alwaysUpdateLinks": true, "newFileLocation": "root"}')
    if not NOTES.exists():
        _w(NOTES, "# Notes for Alfred\n\nWrite anything here that Alfred should know or follow. "
                  "He reads this note before every answer.\n\n- \n")
    mem = (HOME / "data" / "memory.md")
    _w(VAULT / "Memory" / "About the user.md",
       "---\ntags: [alfred, memory]\n---\n# About the user\n\n_Copy of Alfred's memory, updated automatically. "
       "To change what Alfred knows, write in [[Notes for Alfred]] or tell him by voice._\n\n"
       + (mem.read_text(encoding="utf-8") if mem.exists() else ""))
    les = HOME / "data" / "lessons.md"
    _w(VAULT / "Memory" / "Lessons.md", "---\ntags: [alfred, lessons]\n---\n# Lessons\n\n"
       + (les.read_text(encoding="utf-8") if les.exists() else ""))
    today = dt.date.today()
    for i in range(days):
        d = today - dt.timedelta(days=i)
        n = day_note(d)
        if n:
            _w(VAULT / "Daily" / f"{d.isoformat()}.md", n)
    daily = sorted((VAULT / "Daily").glob("*.md"), reverse=True)[:14] if (VAULT / "Daily").exists() else []
    _w(VAULT / "Home.md", "---\ntags: [alfred]\n---\n# Alfred Brain\n\n"
       "- [[Notes for Alfred]]: you write, he reads\n- [[About the user]]: what he remembers\n- [[Lessons]]: what he learned\n\n"
       "## Daily log\n" + "\n".join(f"- [[{p.stem}]]" for p in daily) + "\n")
    return VAULT


if __name__ == "__main__":
    p = sync(days=3650 if "--all" in sys.argv else 2)
    print(p)
    if "--open" in sys.argv:
        subprocess.Popen(["open", "-a", "Obsidian", str(p)])
