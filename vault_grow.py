#!/usr/bin/env python3
"""Memory that grows by itself: reads the day's conversation, asks a small model (Haiku) what is worth
remembering, and writes it into Alfred's Obsidian vault and their memory file.

  vault_grow.py            grow from today's conversation (skips if nothing new)
  vault_grow.py --day 2026-11-11

Writes: data/memory.md (new lasting facts, de-duplicated), vault People/<name>.md, Projects/<name>.md,
Memory/Growth log.md. Never deletes anything. alfred.py runs it once a day in the evening.
"""
import datetime as dt
import json
import os
import re
import subprocess
import sys
from pathlib import Path

HOME = Path(__file__).resolve().parent
sys.path.insert(0, str(HOME))
import vault  # noqa: E402

PROMPT = """You maintain the long-term memory of Alfred, the user's voice assistant. Below is one day of conversation, then what Alfred already remembers.
Pick only LASTING things worth remembering: preferences, habits, decisions, names of people, ongoing projects, goals. Skip small talk, one-off commands, and anything already remembered.
Reply with ONLY JSON, no other text:
{"facts":["short fact about the user, one line each, max 6"],
 "people":[{"name":"First Last","note":"who they are to the user, one line"}],
 "projects":[{"name":"Project name","note":"what changed or what it is, one line"}]}
Empty lists are fine. Never include passwords, keys or secrets.

ALREADY REMEMBERED:
%s

CONVERSATION (%s):
%s
"""


def conversation(day):
    out = []
    try:
        lines = (HOME / "data" / "log.jsonl").read_text(encoding="utf-8").splitlines()
    except OSError:
        return ""
    for line in lines:
        try:
            x = json.loads(line)
        except ValueError:
            continue
        if dt.datetime.fromtimestamp(x.get("ts", 0)).date() != day:
            continue
        k = x.get("type")
        if k in ("request", "quick") and x.get("text"):
            out.append("User: " + re.sub(r"^\[Sent from[^\]]*\]\s*", "", x["text"]))
        if k == "reply" and x.get("text"):
            out.append("Alfred: " + x["text"][:300])
        elif k == "quick" and x.get("reply"):
            out.append("Alfred: " + x["reply"][:300])
    return "\n".join(out)[-9000:]


def ask_model(prompt):
    import brain_cc
    claude = brain_cc.find_claude()
    if not claude:
        return None
    env = os.environ.copy()
    env.pop("ANTHROPIC_API_KEY", None)
    r = subprocess.run([claude, "-p", prompt, "--model", "haiku", "--output-format", "json", "--max-turns", "1",
                        "--disallowedTools", "Bash,Write,Edit,Read,WebFetch,WebSearch,Glob,Grep"],
                       cwd=str(HOME), capture_output=True, text=True, timeout=180, env=env)
    try:
        text = json.loads(r.stdout.strip().splitlines()[-1]).get("result", "")
    except (ValueError, IndexError):
        return None
    m = re.search(r"\{.*\}", text, re.S)
    try:
        return json.loads(m.group(0)) if m else None
    except ValueError:
        return None


def safe(name):
    return re.sub(r"[\\/:*?\"<>|#^\[\]]", "", name).strip()[:60]


def add_note(folder, name, note, day):
    name = safe(name)
    if not name or not note:
        return False
    p = vault.VAULT / folder / f"{name}.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    line = f"- {day.isoformat()}: {note.strip()}\n"
    if p.exists():
        t = p.read_text(encoding="utf-8")
        if note.strip() in t:
            return False
        p.write_text(t.rstrip("\n") + "\n" + line, encoding="utf-8")
    else:
        p.write_text(f"---\ntags: [alfred, {folder.lower().rstrip('s')}]\n---\n# {name}\n\n[[Home]] · [[About the user]]\n\n{line}", encoding="utf-8")
    return True


def grow(day=None):
    day = day or dt.date.today()
    convo = conversation(day)
    if convo.count("User:") < 2:
        return "nothing to learn yet"
    mem = HOME / "data" / "memory.md"
    have = mem.read_text(encoding="utf-8") if mem.exists() else ""
    res = ask_model(PROMPT % (have[-3000:], day.isoformat(), convo))
    if not res:
        return "model gave no answer"
    new_facts = []
    for f in res.get("facts", [])[:6]:
        f = " ".join(str(f).split())
        if f and f.lower() not in have.lower() and not re.search(r"password|api key|token|secret", f, re.I):
            new_facts.append(f)
    if new_facts:
        mem.write_text(have.rstrip("\n") + "\n" + "\n".join("- " + f for f in new_facts) + "\n", encoding="utf-8")
    n_people = sum(add_note("People", p.get("name", ""), p.get("note", ""), day) for p in res.get("people", [])[:5] if isinstance(p, dict))
    n_proj = sum(add_note("Projects", p.get("name", ""), p.get("note", ""), day) for p in res.get("projects", [])[:5] if isinstance(p, dict))
    log = vault.VAULT / "Memory" / "Growth log.md"
    log.parent.mkdir(parents=True, exist_ok=True)
    entry = f"\n## {day.isoformat()}\n" + "".join(f"- fact: {f}\n" for f in new_facts) + f"- people notes: {n_people}, project notes: {n_proj}\n"
    log.write_text((log.read_text(encoding="utf-8") if log.exists() else "---\ntags: [alfred, memory]\n---\n# Growth log\n\nWhat Alfred learned on their own, day by day.\n") + entry, encoding="utf-8")
    vault.sync()
    return f"{len(new_facts)} facts, {n_people} people, {n_proj} projects"


if __name__ == "__main__":
    d = dt.date.fromisoformat(sys.argv[sys.argv.index("--day") + 1]) if "--day" in sys.argv else None
    print(grow(d))
