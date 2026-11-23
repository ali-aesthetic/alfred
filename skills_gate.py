"""Skills gate: staged procedure drafts -> ready (worked twice) -> offered once -> the user approves -> real Claude Code skill.

Flow: learn_review stages data/learn/staged/<name>.md (uses=1). Each time the review sees the same (or a
near-identical) procedure succeed again, record_use() bumps uses; at 2 the draft is "ready" and offered ONCE on
Telegram (with [Approve] [Reject] buttons, callback jv:sa:<id> / jv:sr:<id>) + as an app toast. /approve_<id> writes <home>/.claude/skills/<name>/SKILL.md; /reject_<id>
moves the draft to `to delete/skills-rejected/` (never deleted). Nothing is sent unless the owner chat exists.
State: data/learn/skill_state.json {name: {id, uses, state, one_line, ts}}; states: staged|ready|offered|active|rejected.
"""
from alfred_home import HOME_STR as _AH, CTL as _CTL
import hashlib
import json
import re
import shutil
import threading
import time
from pathlib import Path

HOME = Path(__file__).resolve().parent
DATA = HOME / "data"
SKILLS_DIR = Path(_AH + "/.claude/skills")
READY_USES = 2
MATCH = 0.6  # token overlap (Jaccard) that counts as "near-identical"
_lock = threading.RLock()
BRAIN = None  # set by learn_review.note_turn; used for the quiet recycle


class Gate:
    def __init__(self, data=None, skills_dir=None, trash=None, send=None, emit=None, recycle=None, send_kb=None):
        self.data = Path(data or DATA)
        self.staged = self.data / "learn" / "staged"
        self.approved = self.data / "learn" / "approved"
        self.state_file = self.data / "learn" / "skill_state.json"
        self.skills_dir = Path(skills_dir or SKILLS_DIR)
        self.trash = Path(trash or HOME / "to delete" / "skills-rejected")
        self._send, self._emit, self._recycle = send, emit, recycle
        self._send_kb = send_kb  # send_kb(text, rows) -> message with inline buttons

    # ---- state
    def _load(self):
        try:
            d = json.loads(self.state_file.read_text(encoding="utf-8"))
            return d if isinstance(d, dict) else {}
        except Exception:
            return {}

    def _save(self, st):
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.state_file)

    @staticmethod
    def sid(name):
        return hashlib.sha1(name.encode()).hexdigest()[:6]

    @staticmethod
    def _toks(s):
        return {w for w in re.findall(r"[a-z0-9а-яё]+", str(s).lower()) if len(w) > 2}

    # ---- drafts
    def parse_draft(self, path):
        """Draft .md -> {name, when, triggers, steps, verify}. Tolerant of the older plain format."""
        t = Path(path).read_text(encoding="utf-8")
        name = Path(path).stem

        def g(k):
            m = re.search(rf"^{k}:\s*(.+)$", t, re.M | re.I)
            return m.group(1).strip() if m else ""
        steps = [re.sub(r"^\d+\.\s*", "", l).strip() for l in t.splitlines() if re.match(r"^\d+\.\s", l)]
        trig = [x.strip().strip('"') for x in re.split(r"\s*[;|]\s*", g("Triggers")) if x.strip()]
        return {"name": name, "when": g("When"), "triggers": trig, "steps": steps, "verify": g("Verify")}

    def register(self, name, one_line=""):
        """A new draft was staged (the first success). Returns its state entry."""
        with _lock:
            st = self._load()
            e = st.setdefault(name, {"id": self.sid(name), "uses": 0, "state": "staged",
                                     "one_line": one_line[:160], "ts": time.time()})
            if e["state"] == "staged" and e["uses"] < 1:
                e["uses"] = 1
            self._save(st)
            return e

    def find_match(self, name, text=""):
        """Name of a still-open draft that is the same or near-identical to name/text, else ''."""
        st = self._load()
        open_ = [n for n, e in st.items() if e["state"] in ("staged", "ready", "offered")]
        if name in open_:
            return name
        q = self._toks(name.replace("-", " ") + " " + text)
        best, score = "", 0.0
        for n in open_:
            c = self._toks(n.replace("-", " ") + " " + st[n].get("one_line", ""))
            j = len(q & c) / len(q | c) if q | c else 0
            if j > score:
                best, score = n, j
        return best if score >= MATCH else ""

    def record_use(self, name, text="", ok=True):
        """Count one more success of a staged procedure. Returns the matched name or ''."""
        if not ok:
            return ""
        with _lock:
            m = self.find_match(name, text)
            if not m:
                return ""
            st = self._load()
            e = st[m]
            e["uses"] += 1
            if e["state"] == "staged" and e["uses"] >= READY_USES:
                e["state"] = "ready"
            self._save(st)
            return m

    def staged_names(self, cap=20):
        return [n for n, e in self._load().items() if e["state"] in ("staged", "ready", "offered")][:cap]

    # ---- offer (once)
    def offer_ready(self):
        """Offer every 'ready' skill once (Telegram + toast). Returns names offered."""
        done = []
        with _lock:
            st = self._load()
            for n, e in st.items():
                if e["state"] != "ready":
                    continue
                msg = f"New skill: {n} - {(e.get('one_line') or n)[:120]}. /approve_{e['id']} or /reject_{e['id']}"
                try:
                    rows = [[("✅ Approve", f"jv:sa:{e['id']}"), ("✖ Reject", f"jv:sr:{e['id']}")]]
                    if self._send_kb:
                        self._send_kb(msg.replace(f" /approve_{e['id']} or /reject_{e['id']}", "") + "\nTap a button (or /approve_" + e['id'] + ")", rows)
                    elif self._send:
                        self._send(msg)
                    if self._emit:
                        self._emit("toast", text=f"New skill: {n} - approve on Telegram")
                except Exception as ex:
                    print("[skills_gate] offer failed:", type(ex).__name__)
                    continue
                e["state"] = "offered"
                done.append(n)
            if done:
                self._save(st)
        return done

    # ---- decisions
    def _by_id(self, sid):
        for n, e in self._load().items():
            if e["id"] == sid:
                return n
        return ""

    def _draft_path(self, name):
        p = self.staged / f"{name}.md"
        return p if p.exists() else None

    def approve(self, sid):
        n = self._by_id(sid)
        if not n:
            return "No such skill."
        with _lock:
            st = self._load()
            if st[n]["state"] == "active":
                return f"{n} is already active."
            dp = self._draft_path(n)
            if not dp:
                return f"Draft for {n} is missing."
            d = self.parse_draft(dp)
            out = self.skills_dir / n / "SKILL.md"
            if out.exists():  # never overwrite: park the old one
                self.trash.mkdir(parents=True, exist_ok=True)
                shutil.move(str(out), str(self.trash / f"{n}-SKILL-old-{int(time.time())}.md"))
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(self.render(d), encoding="utf-8")
            self.approved.mkdir(parents=True, exist_ok=True)
            shutil.move(str(dp), str(self.approved / dp.name))
            st[n]["state"] = "active"
            self._save(st)
        self.recycle()
        return f"Skill {n} is active."

    def reject(self, sid):
        n = self._by_id(sid)
        if not n:
            return "No such skill."
        with _lock:
            st = self._load()
            dp = self._draft_path(n)
            if dp:
                self.trash.mkdir(parents=True, exist_ok=True)
                shutil.move(str(dp), str(self.trash / dp.name))
            st[n]["state"] = "rejected"
            self._save(st)
        return f"Rejected {n}. Draft moved to to delete/."

    @staticmethod
    def render(d):
        name = d["name"]
        when = d["when"].rstrip(". ") or name.replace("-", " ")
        trig = d["triggers"] or [name.replace("-", " ")]
        desc = f"{when}. Use when the user says: " + ", ".join(f'"{t}"' for t in trig[:6]) + "."
        steps = "\n".join(f"{i}. {s}" for i, s in enumerate(d["steps"], 1))
        verify = d["verify"] or "Check the result yourself (command output or a screenshot) before telling the user it is done."
        return (f"---\nname: {name}\ndescription: {desc}\n---\n\n# {name.replace('-', ' ').title()}\n\n"
                "Mac control: `alfred-ctl` and the Chrome helper. Never delete files "
                "(move to `to delete/`). Never send anything without the user's yes.\n\n"
                f"## Steps\n{steps}\n\n## Verify\n{verify}\n")

    def recycle(self):
        """Quietly restart the brain process so Claude Code rescans the skills dir.
        VERIFIED (2026-11-23): the app brain is ONE long-lived `claude -p --input-format stream-json` process
        (brain_cc._spawn). Claude Code scans .claude/skills when a session starts, not per turn, so a new SKILL.md
        is live on the NEXT turn only because this recycle respawns it (warm()). One-shot `_run` calls rescan
        every call. Bad SKILL.md files are skipped by Claude Code, they cannot break the other skills."""
        try:
            if self._recycle:
                return self._recycle()
            b = BRAIN
            if b is None:
                return

            def go():
                try:
                    if time.time() - (getattr(b, "last", 0) or 0) < 20:
                        time.sleep(20)  # a turn is probably running; wait it out
                    with b.lock:
                        b._kill()
                        b.last = 0.0
                    b.warm()
                except Exception as ex:
                    print("[skills_gate] recycle:", type(ex).__name__)
            threading.Thread(target=go, daemon=True, name="skills-recycle").start()
        except Exception:
            pass

    # ---- listing / Telegram commands
    def list_text(self):
        st = self._load()
        act = sorted(p.parent.name for p in self.skills_dir.glob("*/SKILL.md")) if self.skills_dir.exists() else []
        pend = [(n, e) for n, e in st.items() if e["state"] in ("staged", "ready", "offered")]
        lines = [f"Active ({len(act)}): " + (", ".join(act) or "none")]
        lines.append(f"Pending ({len(pend)}):" if pend else "Pending: none")
        for n, e in pend:
            if e["state"] == "offered":
                lines.append(f"- {n}: /approve_{e['id']} /reject_{e['id']}")
            else:
                lines.append(f"- {n}: seen {e['uses']}/{READY_USES}")
        return "\n".join(lines)

    def handle_command(self, cmd):
        """Telegram: skills | approve_<id> | reject_<id>. Returns reply text, or None if not ours."""
        if cmd == "skills":
            return self.list_text()
        m = re.fullmatch(r"(approve|reject)_([0-9a-f]{6})", cmd or "")
        if not m:
            return None
        return self.approve(m.group(2)) if m.group(1) == "approve" else self.reject(m.group(2))


_G = None


def default_gate():
    """Gate wired to the real Telegram owner chat and the app event stream (lazy singleton)."""
    global _G
    if _G is None:
        def send(text):
            import telegram_bridge as tb
            cid = tb.Pairing().owner()
            if cid is None:
                raise RuntimeError("no owner")
            tb.Telegram().call("sendMessage", {"chat_id": cid, "text": text})

        def emit(*a, **k):
            import ui_bridge
            ui_bridge.emit(*a, **k)
        def send_kb(text, rows):
            import telegram_bridge as tb
            if not tb.send_with_buttons(text, rows):
                raise RuntimeError("no owner")
        _G = Gate(send=send, emit=emit, send_kb=send_kb)
    return _G
