"""Away tasks: long jobs the user texts from their phone ("do X until I get home").

Loop per task: PLAN (<=8 steps, each with a "done when") -> DO step -> CHECK (screenshot + brain verifies)
 -> on fail retry once with another method -> re-plan the remaining steps once -> blocked.
States: queued -> planning -> running -> (waiting_confirm <-> running) -> done | blocked | stopped | failed
Plan + checkpoints: data/away/<id>.md (human) and <id>.json (machine). Tasks resume after a restart/sleep.
Tasks can also arrive as files in data/away/inbox/*.txt (CLI: python away.py submit "text").
No Telegram code here: the bridge hands in send(text), send_photo(path), screenshot(path).
Silent by design: nothing here speaks.
"""
from alfred_home import HOME_STR as _AH, CTL as _CTL
import json, os, re, subprocess, threading, time, datetime as dt
from pathlib import Path

HOME = Path(__file__).resolve().parent
DIR = HOME / "data" / "away"
MAX_STEPS = 14
PROGRESS_EVERY = 15 * 60  # at most one progress message per 15 min

# ---------- parsing ----------
AWAY_RE = re.compile(
    r"(until|till|til|before)\s+i\s*(get|am|'m|come|’m)?\s*(back|home)"
    r"|until\s+i\s+return|while\s+i['’]?m\s+(out|away|gone|not\s+home|at\s+(work|school|uni))"
    r"|while\s+i\s+am\s+(out|away|gone)|while\s+i['’]?m\s+not\s+(here|home)"
    r"|пока\s+(меня\s+нет|я\s+не\s+(вернусь|приду)|я\s+вне)|до\s+моего\s+(прихода|возвращения)"
    r"|(?:by|before)\s+\d{1,2}(?::\d{2})?\s*(am|pm)\b|(?:by|before)\s+\d{1,2}:\d{2}\b"
    r"|(?:до|к)\s+\d{1,2}[:.]\d{2}", re.I)
TIME_RE = re.compile(r"(?:by|before|до|к)\s+(\d{1,2})(?:[:.](\d{2}))?\s*(am|pm)?", re.I)
YES_RE = re.compile(r"^\s*(yes|y|yep|yeah|ok|okay|go|go ahead|do it|confirm|sure|да|давай|ок|угу|ага|делай)\W*$", re.I)
NO_RE = re.compile(r"^\s*(no|n|nope|cancel|don'?t|stop|skip|нет|не надо|отмена|не|стоп)\W*$", re.I)


TASK_RE = re.compile(r"^\s*(?:make\s+(?:it|this|that)\s+a\s+task|сделай\s+(?:это\s+)?задачей)\s*[:,\-]\s*(.+)$", re.I | re.S)


def parse_away(text, now=None):
    """-> None if not an away request, else {"task": str, "deadline": unix|None}.
    Also accepts the explicit phrase "make it a task: ..." (Mac app / voice / Telegram)."""
    if not text:
        return None
    m0 = TASK_RE.match(text)
    if m0:
        inner = parse_away(m0.group(1)) if AWAY_RE.search(m0.group(1)) else None
        return inner or {"task": m0.group(1).strip(), "deadline": None}
    if not AWAY_RE.search(text):
        return None
    now = now or dt.datetime.now()
    deadline = None
    m = TIME_RE.search(text)
    if m:
        h, mi, ap = int(m.group(1)), int(m.group(2) or 0), (m.group(3) or "").lower()
        if ap == "pm" and h < 12:
            h += 12
        if ap == "am" and h == 12:
            h = 0
        if h < 24 and mi < 60:
            t = now.replace(hour=h, minute=mi, second=0, microsecond=0)
            if t <= now:
                t += dt.timedelta(days=1)
            deadline = t.timestamp()
    task = AWAY_RE.sub("", text)
    task = re.sub(r"\s+", " ", task).strip(" ,.;:-")
    return {"task": task or text.strip(), "deadline": deadline}


def parse_yes_no(text):
    if YES_RE.match(text or ""):
        return True
    if NO_RE.match(text or ""):
        return False
    return None


def parse_status(reply):
    """Last 'STATUS:' line of the brain's reply -> (kind, detail, clean_text)."""
    kind, detail = "CONTINUE", ""
    lines = (reply or "").strip().splitlines()
    keep = []
    for ln in lines:
        m = re.match(r"\s*STATUS:\s*(DONE|CONTINUE|BLOCKED|CONFIRM)\b[:\s-]*(.*)$", ln, re.I)
        if m:
            kind, detail = m.group(1).upper(), m.group(2).strip()
        else:
            keep.append(ln)
    return kind, detail, "\n".join(keep).strip()


# ---------- power / awake ----------
def on_ac():
    try:
        return "AC Power" in subprocess.run(["pmset", "-g", "batt"], capture_output=True, text=True, timeout=3).stdout
    except Exception:
        return False


class Awake:
    """caffeinate -i -s only while on AC power and while at least one away task runs."""
    def __init__(self, ac_fn=on_ac, popen=subprocess.Popen):
        self.p = None
        self.ac_fn, self.popen = ac_fn, popen

    def hold(self):
        if self.p is not None and self.p.poll() is None:
            return True
        if not self.ac_fn():
            return False
        try:
            self.p = self.popen(["caffeinate", "-i", "-s"])
            return True
        except Exception:
            self.p = None
            return False

    def release(self):
        p, self.p = self.p, None
        if p is not None:
            try:
                p.terminate()
            except Exception:
                pass


MAX_PLAN = 8
MAX_STEPS = 14  # kept for compatibility: hard cap on brain calls = MAX_STEPS * 3 per task (see _budget)
RULES = ("Rules: silent (no sound). Chrome only. Never delete anything (move to `to delete/`). Never send, buy, pay, "
         "submit or delete without the user's yes. Optional helpers if they exist: `chrome_ctl.py`, `workers.py`.")

PLAN_PROMPT = """You are planning a long task for the user, who is away from the Mac. Do NOT do anything yet, only plan.
TASK #{id}: {task}
{context}Write a plan of at most {maxn} steps. Each step must be small, doable on this Mac, and checkable on a screenshot of the screen.
Reply with ONLY a JSON list, nothing else:
[{{"step": "what to do", "done_when": "what must be visible/true when it worked", "irreversible": false}}]
Set irreversible=true for any step that sends a message/email/post, deletes, buys/pays, submits a form or changes an account.
{rules}"""

DO_PROMPT = """Do ONE step of a long task for the user, who is away from the Mac. Do it, then stop.
TASK #{id}: {task}
{deadline}Plan:
{plan}
Done so far:
{progress}
NOW: step {n}: {step}
Done when: {done_when}
{extra}{rules}
Reply short (max 3 lines of what you did). The LAST line must be exactly one of:
STATUS: DONE   (this step is finished)
STATUS: BLOCKED: <why, one line>   (you need the user or something is impossible)
STATUS: CONFIRM: <exact action>   (you are about to do something irreversible)"""

VERIFY_PROMPT = """Check a step. Read the screenshot image at {img} (use the Read tool), and use any other quick check you need.
Step: {step}
Done when: {done_when}
The step reported: {report}
Reply with ONE line only: `VERDICT: PASS` or `VERDICT: FAIL: <short reason>`. Be strict: PASS only if the condition is really true."""

RETRY_EXTRA = "The last attempt FAILED the check ({why}). Use a DIFFERENT method than before.\n"

REPLAN_CTX = ("Done so far:\n{done}\nThe plan got stuck on step {n} ({step}) after two different methods: {why}.\n"
              "Write a NEW plan for ONLY the remaining work (start from what is still not done).\n")


def parse_plan(text, maxn=MAX_PLAN):
    """Brain reply -> [{"step","done_when","irreversible"}]. JSON list first, numbered lines as fallback."""
    text = text or ""
    out = []
    m = re.search(r"\[.*\]", text, re.S)
    if m:
        try:
            for it in json.loads(m.group(0)):
                if isinstance(it, dict) and str(it.get("step", "")).strip():
                    out.append({"step": str(it["step"]).strip(), "done_when": str(it.get("done_when", "")).strip() or "the step visibly worked",
                                "irreversible": bool(it.get("irreversible"))})
        except Exception:
            out = []
    if not out:
        for ln in text.splitlines():
            m = re.match(r"\s*\d+[.)]\s*(.+?)(?:\s*[|\-–—]\s*done when:?\s*(.+))?$", ln, re.I)
            if m:
                out.append({"step": m.group(1).strip(), "done_when": (m.group(2) or "the step visibly worked").strip(),
                            "irreversible": bool(re.search(r"\b(send|delete|buy|pay|submit|post|publish)\b", m.group(1), re.I))})
    return out[:maxn]


def parse_verdict(reply):
    """-> (ok: bool, why). Anything that is not a clear PASS counts as a fail."""
    m = re.search(r"VERDICT:\s*(PASS|FAIL)\b[:\s-]*(.*)", reply or "", re.I)
    if not m:
        return False, "no clear verdict"
    return m.group(1).upper() == "PASS", m.group(2).strip()[:200]


def ctl_screenshot(path):
    subprocess.run([_CTL, "screenshot", path], capture_output=True, timeout=30)


ACTIVE = ("queued", "planning", "running", "waiting_confirm")
RESUME_MAX_AGE = 24 * 3600


class Away:
    def __init__(self, ask_fn, send, send_photo=None, screenshot=None, ac_fn=on_ac, popen=subprocess.Popen,
                 now_fn=time.time, directory=DIR, max_steps=MAX_STEPS, progress_every=PROGRESS_EVERY,
                 autostart=True, poll_every=5, send_kb=None):
        self.ask_fn, self.send, self.send_photo = ask_fn, send, send_photo
        self.send_kb = send_kb  # optional send_kb(text, rows[[(label, callback_data)]]) -> inline buttons
        self.paused = set()
        self.screenshot = screenshot or ctl_screenshot
        self.now = now_fn
        self.dir = Path(directory)
        self.max_steps, self.progress_every = max_steps, progress_every
        self.poll_every = poll_every
        self.awake = Awake(ac_fn, popen)
        self.tasks = {}
        self.q = []
        self.cv = threading.Condition()
        self.worker = None
        self.current = None
        self.confirm = None  # {"event", "answer"} of the task waiting for yes/no
        self.poller = None
        if autostart:
            self.resume()
            self.poller = threading.Thread(target=self._poll_inbox, daemon=True, name="away-inbox")
            self.poller.start()

    # ----- brain helper (muted; works with ask_fn(prompt, source=...) or ask_fn(prompt))
    def _ask(self, prompt, source="away"):
        try:
            return self.ask_fn(prompt, source=source) or ""
        except TypeError:
            return self.ask_fn(prompt) or ""

    # ----- public
    def submit(self, text, parsed=None):
        p = parsed or parse_away(text)
        if not p:
            return None
        tid = dt.datetime.fromtimestamp(self.now()).strftime("%m%d-%H%M%S")
        while tid in self.tasks:
            tid += "x"
        t = {"id": tid, "task": p["task"], "deadline": p["deadline"], "state": "queued", "step": 0, "cur": 0,
             "created": self.now(), "last_progress": 0, "log": [], "waiting": "", "plan": [], "replans": 0,
             "attempt": 0, "calls": 0, "approved": -1}
        with self.cv:
            self.tasks[tid] = t
            self._enqueue(tid)
        return tid

    def _enqueue(self, tid):
        self.q.append(tid)
        self._save(self.tasks[tid])
        if self.worker is None or not self.worker.is_alive():
            self.worker = threading.Thread(target=self._run, daemon=True, name="away")
            self.worker.start()
        self.cv.notify_all()

    def resume(self):
        """After a restart or sleep: pick up unfinished tasks from data/away/*.json (not older than 24 h)."""
        n = 0
        try:
            files = sorted(self.dir.glob("*.json"))
        except Exception:
            return 0
        for f in files:
            try:
                t = json.loads(f.read_text())
                if t.get("state") not in ACTIVE or t["id"] in self.tasks:
                    continue
                if self.now() - t.get("created", 0) > RESUME_MAX_AGE or (t.get("deadline") and self.now() > t["deadline"] + 3600):
                    t["state"] = "stopped"
                    self.tasks[t["id"]] = t
                    t.setdefault("log", [])
                    self._save(t)
                    continue
                t.setdefault("log", [])
                lines = (self.dir / f"{t['id']}.md").read_text().splitlines() if (self.dir / f"{t['id']}.md").exists() else []
                t["log"] = [l[2:] for l in lines if l.startswith("- ") and "[" not in l[:3]] or t["log"]
                for k, v in (("plan", []), ("cur", 0), ("replans", 0), ("attempt", 0), ("calls", 0), ("approved", -1)):
                    t.setdefault(k, v)
                t["resumed"] = True
                self.tasks[t["id"]] = t
                with self.cv:
                    self._enqueue(t["id"])
                n += 1
            except Exception:
                continue
        return n

    def _poll_inbox(self):
        inbox = self.dir / "inbox"
        while True:
            try:
                for f in sorted(inbox.glob("*.txt")):
                    text = f.read_text().strip()
                    done = inbox / "done"
                    done.mkdir(parents=True, exist_ok=True)
                    f.rename(done / f.name)  # moved, never deleted
                    p = parse_away(text) or {"task": text, "deadline": None}
                    if p["task"]:
                        tid = self.submit(text, p)
                        self.send(f"Queued #{tid}: {p['task'][:80]}")
            except Exception:
                pass
            time.sleep(self.poll_every)

    def waiting_for_answer(self):
        return self.confirm is not None

    def answer(self, yes):
        c = self.confirm
        if not c:
            return False
        c["answer"] = bool(yes)
        c["event"].set()
        return True

    def _say(self, text, rows=None):
        """Send text; with inline buttons when the bridge gave us send_kb (text-only fallback)."""
        if rows and self.send_kb:
            try:
                return self.send_kb(text, rows)
            except Exception:
                pass
        return self.send(text)

    def pause_toggle(self, tid=None):
        """Pause/resume the running task (between steps). Returns 'paused'|'resumed'|''."""
        t = self.current if not tid else self.tasks.get(tid)
        if not t or t["state"] not in ACTIVE:
            return ""
        if t["id"] in self.paused:
            self.paused.discard(t["id"])
            return "resumed"
        self.paused.add(t["id"])
        return "paused"

    def stop_all(self):
        n = 0
        with self.cv:
            for t in self.tasks.values():
                if t["state"] in ACTIVE:
                    t["state"] = "stopped"
                    self._save(t)
                    n += 1
            self.q.clear()
        if self.confirm:
            self.confirm["answer"] = False
            self.confirm["event"].set()
        return n

    def list_text(self):
        rows = [f"#{t['id']} {t['state']} (step {t['cur'] + 1 if t['state'] in ACTIVE else t['cur']}/{len(t['plan']) or '?'}): {t['task'][:60]}"
                for t in sorted(self.tasks.values(), key=lambda x: x["created"])[-8:]]
        return "\n".join(rows) or "No away tasks."

    def doing(self):
        t = self.current
        return f"away #{t['id']}: {t['task'][:60]} (step {t['cur'] + 1}/{len(t['plan']) or '?'})" if t else ""

    # ----- files
    def _save(self, t):
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            (self.dir / f"{t['id']}.json").write_text(json.dumps({k: v for k, v in t.items() if k != "log"}))
            mark = {"done": "x", "failed": "!"}
            plan = "\n".join(
                f"{i + 1}. [{'x' if i < t['cur'] else ('>' if i == t['cur'] and t['state'] in ACTIVE else ' ')}] {s['step']}"
                f"{'  (asks the user first)' if s.get('irreversible') else ''}\n   done when: {s['done_when']}"
                for i, s in enumerate(t["plan"])) or "(planning)"
            head = (f"# Away task {t['id']}\n\n**Task:** {t['task']}\n**State:** {t['state']}  (re-plans: {t['replans']})\n\n"
                    f"## Plan\n{plan}\n\n## Progress\n")
            (self.dir / f"{t['id']}.md").write_text(head + "\n".join(f"- {x}" for x in t["log"]) + "\n")
        except Exception:
            pass

    def _note(self, t, s):
        t["log"].append(f"{dt.datetime.fromtimestamp(self.now()):%H:%M} {s}")
        self._save(t)

    def _tail(self, t, n=6):
        return "\n".join(t["log"][-n:])

    # ----- worker
    def _run(self):
        while True:
            with self.cv:
                tid = self.q.pop(0) if self.q else None
            if tid is None:
                self.awake.release()
                return
            t = self.tasks[tid]
            if t["state"] == "stopped":
                continue
            try:
                self._do_task(t)
            except Exception as e:
                t["state"] = "failed"
                self._note(t, f"crashed: {e}")
                self._finish(t, f"Task #{t['id']} failed: {str(e)[:120]}")
            finally:
                self.current = None

    def _stopped(self, t):
        if t["state"] == "stopped":
            self._finish(t, f"Stopped #{t['id']} at step {t['cur'] + 1}.")
            return True
        return False

    def _plan(self, t, replan_ctx=""):
        t["state"] = "planning"
        self._save(t)
        reply = self._ask(PLAN_PROMPT.format(id=t["id"], task=t["task"], context=replan_ctx, maxn=MAX_PLAN, rules=RULES),
                          source="away-plan")
        plan = parse_plan(reply)
        t["calls"] += 1
        return plan

    def _do_task(self, t):
        self.current = t
        self.awake.hold()
        if not t["plan"]:
            self._note(t, "planning")
            self.send(f"Started #{t['id']}: {t['task'][:80]}. Planning, then I will report when done or blocked.")
            plan = self._plan(t)
            if not plan:
                t["state"] = "blocked"
                return self._finish(t, f"Blocked #{t['id']}: could not make a plan.")
            t["plan"], t["cur"], t["attempt"] = plan, 0, 0
            self._note(t, f"plan ready: {len(plan)} steps")
            self.send(f"#{t['id']} plan ({len(plan)} steps):\n" + "\n".join(f"{i + 1}. {s['step'][:70]}" for i, s in enumerate(plan))[:700])
        else:
            self._note(t, "resumed after restart" if t.get("resumed") else "continuing")
            self.send(f"Resumed #{t['id']} at step {t['cur'] + 1}/{len(t['plan'])}.")
            t["resumed"] = False
        t["state"] = "running"
        extra = ""
        budget = len(t["plan"]) * 4 + 12
        while t["cur"] < len(t["plan"]):
            if self._stopped(t):
                return
            if t["deadline"] and self.now() > t["deadline"]:
                t["state"] = "done"
                return self._finish(t, f"Time is up for #{t['id']}. Done so far: {self._tail(t)}")
            if t["calls"] > budget:
                t["state"] = "blocked"
                return self._finish(t, f"#{t['id']} hit the work limit. Done so far: {self._tail(t)}")
            self.awake.hold()
            while t["id"] in self.paused and t["state"] != "stopped":
                time.sleep(1 if self.poll_every >= 1 else 0.05)
            if self._stopped(t):
                return
            i = t["cur"]
            s = t["plan"][i]
            t["step"] = i + 1
            # irreversible step: ask the user first (one yes covers only this step)
            if s.get("irreversible") and t["approved"] != i:
                ok = self._ask_yes(t, s["step"])
                if ok is None:
                    return self._finish(t, f"Stopped #{t['id']} while waiting for your answer.")
                self._note(t, f"the user said {'YES' if ok else 'NO'} to: {s['step'][:100]}")
                if not ok:
                    t["cur"] += 1
                    t["attempt"] = 0
                    self._save(t)
                    continue
                t["approved"] = i
            res = self._do_step(t, i, s, extra)
            extra = ""
            if res == "stop":
                return
            if res[0] == "confirm":  # ("confirm", action) from the brain mid-step
                ok = self._ask_yes(t, res[1])
                if ok is None:
                    return self._finish(t, f"Stopped #{t['id']} while waiting for your answer.")
                self._note(t, f"the user said {'YES' if ok else 'NO'} to: {res[1][:100]}")
                extra = (f"the user answered YES: do exactly this and nothing more: {res[1]}\n" if ok
                         else f"the user answered NO to: {res[1]}. Do NOT do it; skip it or find another way.\n")
                continue
            if res == "ok":
                t["cur"] += 1
                t["attempt"] = 0
                self._save(t)
                self._progress(t)
                continue
            # res = ("fail", why)
            why = res[1]
            t["attempt"] += 1
            if t["attempt"] == 1:
                extra = RETRY_EXTRA.format(why=why)
                self._note(t, f"step {i + 1} failed ({why[:100]}); retrying another way")
                continue
            if t["replans"] < 1:
                t["replans"] += 1
                self._note(t, f"step {i + 1} failed twice; re-planning the rest")
                new = self._plan(t, REPLAN_CTX.format(done=self._tail(t, 10), n=i + 1, step=s["step"], why=why))
                if new:
                    t["plan"] = t["plan"][:i] + new[:MAX_PLAN]
                    t["attempt"] = 0
                    t["state"] = "running"
                    budget = t["calls"] + len(t["plan"]) * 4 + 12
                    self._save(t)
                    self.send(f"#{t['id']} changed plan after a problem: {len(new)} steps left.")
                    continue
            t["state"] = "blocked"
            return self._finish(t, f"Blocked #{t['id']} at step {i + 1} ({s['step'][:80]}): {why}")
        t["state"] = "done"
        self._finish(t, f"Done #{t['id']}: {t['task'][:200]}\n{self._tail(t, 3)}")

    def _do_step(self, t, i, s, extra):
        """DO then CHECK one step -> "ok" | ("fail", why) | ("confirm", action) | "stop"."""
        dl = f"Deadline: {dt.datetime.fromtimestamp(t['deadline']):%H:%M}.\n" if t["deadline"] else ""
        plan = "\n".join(f"{k + 1}. {x['step']}" for k, x in enumerate(t["plan"]))
        reply = self._ask(DO_PROMPT.format(id=t["id"], task=t["task"], deadline=dl, plan=plan,
                                           progress=self._tail(t) or "(nothing yet)", n=i + 1, step=s["step"],
                                           done_when=s["done_when"], extra=extra, rules=RULES), source="away")
        t["calls"] += 1
        if t["state"] == "stopped":
            self._stopped(t)
            return "stop"
        kind, detail, clean = parse_status(reply)
        self._note(t, f"step {i + 1}: " + (clean or "(no text)")[:240].replace("\n", " "))
        if kind == "CONFIRM":
            return ("confirm", detail or clean[:200])
        if kind == "BLOCKED":
            return ("fail", detail or clean[:160] or "brain says blocked")
        ok, why = self._check(t, i, s, clean)
        if t["state"] == "stopped":
            self._stopped(t)
            return "stop"
        self._note(t, f"check step {i + 1}: {'PASS' if ok else 'FAIL ' + why}")
        return "ok" if ok else ("fail", why or "check failed")

    def _check(self, t, i, s, report):
        img = str(self.dir / f"{t['id']}-s{i + 1}.png")
        try:
            self.screenshot(img)
        except Exception:
            pass
        shot = img if os.path.exists(img) else "(no screenshot available, check another way)"
        reply = self._ask(VERIFY_PROMPT.format(img=shot, step=s["step"], done_when=s["done_when"], report=report[:300]),
                          source="away-verify")
        t["calls"] += 1
        return parse_verdict(reply)

    def _progress(self, t):
        now = self.now()
        if t["last_progress"] == 0:
            t["last_progress"] = now
        elif now - t["last_progress"] >= self.progress_every:
            t["last_progress"] = now
            self._say(f"#{t['id']} step {t['cur']}/{len(t['plan'])} done: {t['plan'][t['cur'] - 1]['step'][:150]}",
                      [[("⏸ Pause", f"jv:ap:{t['id']}"), ("⏹ Stop", f"jv:as:{t['id']}"), ("📸 Screen", f"jv:asc:{t['id']}")]])

    def _ask_yes(self, t, action):
        """Send the question, wait for yes/no. None = stopped."""
        ev = threading.Event()
        self.confirm = {"event": ev, "answer": None}
        t["state"] = "waiting_confirm"
        t["waiting"] = action
        self._save(t)
        self._say(f"Need your OK for #{t['id']}:\n{action}\nTap a button, or reply yes / no.",
                  [[("Yes, do it", f"jv:ay:{t['id']}"), ("No", f"jv:an:{t['id']}")]])
        while not ev.wait(5 if self.poll_every >= 1 else 0.05):
            if t["state"] == "stopped":
                break
            if t["deadline"] and self.now() > t["deadline"] + 3600:
                break
        c, self.confirm = self.confirm, None
        if t["state"] == "stopped" or c["answer"] is None:
            return None
        t["state"] = "running"
        t["waiting"] = ""
        self._save(t)
        return c["answer"]

    def _finish(self, t, text):
        self._save(t)
        self.send(text[:900])
        if self.screenshot and self.send_photo:
            try:
                p = str(self.dir / f"{t['id']}-final.png")
                self.screenshot(p)
                if os.path.exists(p):
                    self.send_photo(p, f"#{t['id']} final screen")
            except Exception:
                pass
        with self.cv:
            busy = bool(self.q)
        if not busy:
            self.awake.release()


if __name__ == "__main__":  # python away.py submit "make it a task: ..."  -> picked up by the running Alfred
    import sys
    if len(sys.argv) >= 3 and sys.argv[1] == "submit":
        (DIR / "inbox").mkdir(parents=True, exist_ok=True)
        f = DIR / "inbox" / f"{int(time.time() * 1000)}.txt"
        f.write_text(" ".join(sys.argv[2:]))
        print("queued", f.name)
    else:
        print('usage: away.py submit "text"')
