"""Daily insight: ONE useful proposal per day, opt-in (setting `insights`, default off). Silent; Telegram only.
Offered once ([Turn on] [Not now]). When on, once a day (9:00-21:00) the brain proposes one routine from memory,
learn_review's skills and the schedule; the user taps [Yes] (creates a scheduler job) or [Not now] (never proposed again).
Nothing is created without the tap. State: data/insights.json.
Callbacks: jv:io (turn on) jv:ix (not now) jv:iy:<id> (yes) jv:in:<id> (not now).
"""
import datetime as dt
import hashlib
import json
import re
import threading
from pathlib import Path

HOME = Path(__file__).resolve().parent
DATA = HOME / "data"
QUIET = (9, 21)  # only propose between these local hours

PROMPT = """You look at what you know about the user (a Mac user) and propose ONE useful automation they would likely want.
Pick something they do repeatedly (e.g. opens an app every evening) that could become a scheduled job.
Reply ONLY JSON: {"text": "<one friendly sentence ending with a question, max 140 chars>", "when": "<daily HH:MM | weekly mon HH:MM | every 2h>", "task": "<what Alfred should do then, one sentence>"}
If nothing is clearly useful reply {"none": true}. Never propose sending messages/emails, buying or deleting anything.
ALREADY SCHEDULED (do not repeat): %s
ALREADY DECLINED (do not repeat): %s
KNOWN:
%s"""


def _tail(p, n=1800):
    try:
        return Path(p).read_text(encoding="utf-8", errors="ignore")[-n:]
    except OSError:
        return ""


def gather(data=DATA):
    parts = [("memory", _tail(Path(data) / "memory.md")), ("lessons", _tail(Path(data) / "lessons.md", 800))]
    try:
        st = json.loads((Path(data) / "learn" / "skill_state.json").read_text())
        parts.append(("skills seen", ", ".join(f"{n}({e.get('state')})" for n, e in st.items())[:400]))
    except Exception:
        pass
    return "\n".join(f"[{k}]\n{v}" for k, v in parts if v)


class Insights:
    def __init__(self, send_kb, model_fn, get_on, set_on, data=DATA, now_fn=None, add_job=None, jobs_text=None):
        self.send_kb, self.model_fn, self.get_on, self.set_on = send_kb, model_fn, get_on, set_on
        self.data = Path(data)
        self.f = self.data / "insights.json"
        self.now = now_fn or dt.datetime.now
        self.add_job, self.jobs_text = add_job, jobs_text
        self.lock = threading.Lock()

    def _load(self):
        try:
            d = json.loads(self.f.read_text())
            return d if isinstance(d, dict) else {}
        except Exception:
            return {}

    def _save(self, d):
        self.f.parent.mkdir(parents=True, exist_ok=True)
        self.f.write_text(json.dumps(d, ensure_ascii=False, indent=1))

    def tick(self):
        """Call every few minutes. Returns 'offer'|'idea'|''."""
        with self.lock:
            d, now = self._load(), self.now()
            if not (QUIET[0] <= now.hour < QUIET[1]):
                return ""
            if not self.get_on():
                if d.get("offered"):
                    return ""
                self.send_kb("💡 Once a day I can suggest ONE useful routine, based on what I notice. "
                             "Nothing happens unless you tap Yes.", [[("Turn on", "jv:io"), ("Not now", "jv:ix")]])
                d["offered"] = now.isoformat()
                self._save(d)
                return "offer"
            today = now.strftime("%Y-%m-%d")
            if d.get("last_day") == today:
                return ""
            idea = self.propose(d)
            if not idea:
                return ""
            iid = hashlib.sha1(idea["text"].encode()).hexdigest()[:6]
            d.setdefault("pending", {})[iid] = idea
            d["last_day"] = today
            self._save(d)
            self.send_kb("💡 " + idea["text"], [[("Yes", f"jv:iy:{iid}"), ("Not now", f"jv:in:{iid}")]])
            return "idea"

    def propose(self, d):
        try:
            jobs = self.jobs_text() if self.jobs_text else ""
            out = self.model_fn(PROMPT % (jobs[:600] or "none", "; ".join(d.get("declined_text", [])[-10:]) or "none", gather(self.data)))
            m = re.search(r"\{.*\}", out or "", re.S)
            j = json.loads(m.group(0)) if m else {}
            if j.get("none") or not all(j.get(k) for k in ("text", "when", "task")):
                return None
            import scheduler
            scheduler.parse_when(j["when"])  # reject unparseable schedules
            if j["text"] in d.get("declined_text", []):
                return None
            return {k: str(j[k])[:200] for k in ("text", "when", "task")}
        except Exception as e:
            print("[insights]", type(e).__name__)
            return None

    def callback(self, verb, arg=""):
        """verb: io|ix|iy|in. Returns the reply/edit text."""
        with self.lock:
            d = self._load()
            if verb == "io":
                self.set_on(True)
                return "Insights on. One suggestion a day, only between 9:00 and 21:00."
            if verb == "ix":
                d["offered"] = d.get("offered") or "declined"
                self._save(d)
                return "OK, no daily suggestions. Turn on any time in /menu."
            idea = (d.get("pending") or {}).pop(arg, None)
            if not idea:
                return "That suggestion is no longer available."
            if verb == "iy":
                try:
                    j = self.add_job(idea["when"], idea["task"], deliver="telegram")
                    self._save(d)
                    return f"Done: {idea['when']} - {idea['task']} (job {j['id']})."
                except Exception as e:
                    self._save(d)
                    return "Could not create it: " + str(e)[:80]
            d.setdefault("declined_text", []).append(idea["text"])
            self._save(d)
            return "Got it. I will not suggest that again."
