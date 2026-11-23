"""Learning review after turns: a cheap background pass that turns recent chat into durable learning.

Idea borrowed from Hermes Agent `agent/background_review.py` (MIT, Nous Research): after turns, a
side run asks "is there anything worth saving?" and writes it, never touching the main conversation.
Own implementation (no code copied).

After a real user turn (not [system]; the fast lane never reaches brain.ask) `note_turn()` queues the
turn. At most once per 5 min a daemon thread sends the queued turns to a Haiku one-shot (light=True)
and applies the JSON answer:
  facts   -> memory cards (data/ui/memory.json via ui_bridge.add_memory, emits `noted`; deduped)
  lessons -> data/lessons.md (one line each, deduped)
  skills  -> data/learn/staged/<name>.md drafts (NEVER auto-activated)
Never writes to your notes folder. Never blocks a turn.
"""
import json
import re
import threading
import time
from pathlib import Path

HOME = Path(__file__).resolve().parent
DATA = HOME / "data"
MIN_GAP = 300          # seconds between reviews
MAX_FACTS, MAX_LESSONS, MAX_SKILLS = 3, 3, 1

PROMPT = """You review a short chat between the user and their assistant Alfred and extract things worth remembering.
Output ONLY one JSON object, no prose, no code fence:
{"facts": [], "lessons": [], "skills": [], "worked_again": []}
- facts: NEW durable facts about the user (people, projects, preferences, habits, accounts they use). Not passing requests, not secrets/passwords/keys. Each one short sentence. Max 3.
- lessons: corrections the user made to Alfred ("no, I meant...", "you didn't play it", "stop doing X"), each as ONE line telling Alfred what to do differently next time. Only if the user really corrected something. Max 3.
- skills: a reusable multi-step procedure that worked and would help again. {"name": "kebab-case-name", "when": "when to use it", "triggers": ["phrase the user says"], "steps": ["step 1 (use alfred-ctl / chrome commands)", "step 2"], "verify": "how to check it worked"}. Max 1, only if 3+ real steps.
- worked_again: names from KNOWN PROCEDURES below that Alfred just successfully did again in this chat (or a near-identical task). Usually [].
Empty lists are the normal answer. Do not repeat anything obvious or already known.

Chat:
"""


def _norm(s):
    return " ".join(re.findall(r"\w+", str(s).lower()))


def parse_json(text):
    """Pull the first JSON object out of model output (tolerates code fences and chatter)."""
    t = str(text or "").strip()
    t = re.sub(r"^```(?:json)?|```$", "", t, flags=re.M).strip()
    try:
        d = json.loads(t)
    except Exception:
        m = re.search(r"\{.*\}", t, re.S)
        if not m:
            return {}
        try:
            d = json.loads(m.group(0))
        except Exception:
            return {}
    return d if isinstance(d, dict) else {}


def _clean_line(s, cap=200):
    return re.sub(r"\s+", " ", str(s or "")).strip().lstrip("-•* ").strip()[:cap]


def apply(result, add_memory=None, lessons_path=None, staged_dir=None, gate=None):
    """Write a parsed review result. Returns counts. Pure of any model call, so it is testable."""
    lessons_path = Path(lessons_path or DATA / "lessons.md")
    staged_dir = Path(staged_dir or DATA / "learn" / "staged")
    out = {"facts": 0, "lessons": 0, "skills": 0, "ready": 0}
    if add_memory is None:
        import ui_bridge
        add_memory = ui_bridge.add_memory
    for f in (result.get("facts") or [])[:MAX_FACTS]:
        f = _clean_line(f)
        if len(f) < 8 or re.search(r"password|passcode|api[_ ]?key|token|secret", f, re.I):
            continue
        if add_memory(f):  # add_memory dedupes exact repeats and returns None for them
            out["facts"] += 1
    try:
        existing = lessons_path.read_text(encoding="utf-8") if lessons_path.exists() else ""
    except OSError:
        existing = ""
    have = {_norm(l) for l in existing.splitlines()}
    new_lines = []
    for l in (result.get("lessons") or [])[:MAX_LESSONS]:
        l = _clean_line(l)
        if len(l) < 8 or _norm(l) in have:
            continue
        have.add(_norm(l))
        new_lines.append("- " + l)
    if new_lines:
        lessons_path.parent.mkdir(parents=True, exist_ok=True)
        with open(lessons_path, "a", encoding="utf-8") as fh:
            if existing and not existing.endswith("\n"):
                fh.write("\n")
            fh.write("\n".join(new_lines) + "\n")
        out["lessons"] = len(new_lines)
    used = set()
    for s in (result.get("skills") or [])[:MAX_SKILLS]:
        if not isinstance(s, dict):
            continue
        name = re.sub(r"[^a-z0-9]+", "-", str(s.get("name", "")).lower()).strip("-")[:50]
        steps = [_clean_line(x, 300) for x in (s.get("steps") or []) if _clean_line(x, 300)]
        if not name or len(steps) < 2:
            continue
        p = staged_dir / f"{name}.md"
        if gate is not None and gate.find_match(name, str(s.get("when", ""))):
            used.add(gate.find_match(name, str(s.get("when", ""))))  # same/near-identical procedure again = one more success
            continue
        if p.exists():
            continue  # never overwrite a draft
        trig = "; ".join(_clean_line(x, 80) for x in (s.get("triggers") or [])[:6] if _clean_line(x, 80))
        body = f"# {name} (DRAFT, staged by learning review; not active)\n\nWhen: {_clean_line(s.get('when'), 300)}\n"
        if trig:
            body += f"Triggers: {trig}\n"
        if _clean_line(s.get("verify"), 300):
            body += f"Verify: {_clean_line(s.get('verify'), 300)}\n"
        body += "\n" + "\n".join(f"{i}. {x}" for i, x in enumerate(steps[:12], 1)) + "\n"
        staged_dir.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
        out["skills"] += 1
        if gate is not None:
            gate.register(name, _clean_line(s.get("when"), 160))
    if gate is not None:
        for n in (result.get("worked_again") or [])[:5]:
            m = gate.find_match(_clean_line(n, 60))
            if m:
                used.add(m)
        for m in used:
            gate.record_use(m)
        out["ready"] = len(gate.offer_ready())
    return out


class Reviewer:
    def __init__(self, brain, min_gap=MIN_GAP):
        self.brain, self.min_gap = brain, min_gap
        self.pending = []
        self.last = 0.0
        self.running = False
        self.lock = threading.Lock()

    def note_turn(self, user, reply, now=None):
        now = now or time.time()
        if not user or user.lstrip().startswith("[system]"):
            return False
        with self.lock:
            self.pending.append((user[:400], (reply or "")[:400]))
            self.pending = self.pending[-12:]
            if self.running or now - self.last < self.min_gap:
                return False  # batched: next turn after the gap picks these up
            self.running = True
            self.last = now
            batch, self.pending = self.pending, []
        threading.Thread(target=self._work, args=(batch,), daemon=True, name="learn-review").start()
        return True

    def _model_json(self, batch):
        convo = "\n".join(f"User: {u}\nAlfred: {r}" for u, r in batch)
        known = ""
        try:
            import skills_gate
            names = skills_gate.default_gate().staged_names()
            known = "KNOWN PROCEDURES: " + (", ".join(names) or "(none)") + "\n\n"
        except Exception:
            pass
        j = self.brain._run(PROMPT + known + convo, model=self.brain.cfg.get("cc_model", "haiku"), persona=False,
                            timeout=60, max_turns=1, light=True)
        return {} if j.get("is_error") else parse_json(j.get("result", ""))

    def _work(self, batch):
        try:
            gate = None
            try:
                import skills_gate
                gate = skills_gate.default_gate()
            except Exception:
                pass
            counts = apply(self._model_json(batch), gate=gate)
            if any(counts.values()):
                try:
                    self.brain.log.add("learn_review", **counts)
                except Exception:
                    pass
        except Exception as e:  # incl. timeouts: a failed review is just skipped
            print("[learn_review]", type(e).__name__, str(e)[:120])
        finally:
            self.running = False


_R = None


def note_turn(brain, user, reply):
    """Hook called from brain_cc.ask. Never raises, never blocks."""
    global _R
    try:
        if _R is None:
            _R = Reviewer(brain)
            try:
                import skills_gate
                skills_gate.BRAIN = brain
            except Exception:
                pass
        return _R.note_turn(user, reply)
    except Exception as e:
        print("[learn_review]", e)
        return False
