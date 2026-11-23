"""Scheduler: recurring / one-shot jobs run through the Alfred brain, delivered to Telegram and/or the pill.

Idea borrowed from Hermes Agent `cron/scheduler.py` (MIT, Nous Research): a tick loop, jobs in a JSON
file, results delivered to a chat. Own implementation.

Jobs live in data/schedule.json: [{id, when, task, deliver: telegram|pill|both, enabled, created, last_run, note}]
when: "daily 08:00" | "weekly mon 09:00" | "every 2h" / "every 30m" | 5-field cron "m h dom mon dow"
      | ISO time "2026-11-25T09:00" (one-shot).
Missed while the Mac slept: run once on wake if late by < 2 h, otherwise skip and note it.

CLI (the brain uses this):  scheduler.py add "daily 08:00" "morning brief" --deliver telegram
                            scheduler.py list | remove ID | pause ID | resume ID
"""
import argparse
import datetime as dt
import fcntl
import json
import os
import re
import sys
import threading
import time
import uuid
from pathlib import Path

HOME = Path(__file__).resolve().parent
SCHEDULE = HOME / "data" / "schedule.json"
LOG = HOME / "data" / "schedule.log"
GRACE = 2 * 3600
TICK = 30
DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


# ---------------------------------------------------------------- parsing
def _field(spec, lo, hi):
    out = set()
    for part in spec.split(","):
        step = 1
        if "/" in part:
            part, s = part.split("/", 1)
            step = int(s)
        if part in ("*", ""):
            a, b = lo, hi
        elif "-" in part:
            a, b = (int(x) for x in part.split("-", 1))
        else:
            a = int(part)
            b = hi if step > 1 else a
        if a < lo or b > hi or step < 1:
            raise ValueError("bad cron field")
        out.update(range(a, b + 1, step))
    return out


def parse_when(when):
    """-> dict(kind=cron|every|once, ...). Raises ValueError."""
    w = " ".join(str(when).strip().lower().split())
    m = re.fullmatch(r"daily (\d{1,2}):(\d{2})", w)
    if m:
        return _cron(f"{int(m[2])} {int(m[1])} * * *")
    m = re.fullmatch(r"weekly (mon|tue|wed|thu|fri|sat|sun) (\d{1,2}):(\d{2})", w)
    if m:
        return _cron(f"{int(m[3])} {int(m[2])} * * {(DAYS.index(m[1]) + 1) % 7}")
    m = re.fullmatch(r"every (\d+) ?(m|min|mins|minutes?|h|hr|hrs|hours?)", w)
    if m:
        n = int(m[1]) * (60 if m[2].startswith("h") else 1)
        if n < 1:
            raise ValueError("interval too small")
        return {"kind": "every", "seconds": n * 60}
    if len(w.split()) == 5:
        return _cron(w)
    try:
        t = dt.datetime.fromisoformat(str(when).strip())
        return {"kind": "once", "ts": t.timestamp()}
    except ValueError:
        raise ValueError(f"cannot understand schedule: {when!r}")


def _cron(expr):
    mi, h, dom, mon, dow = expr.split()
    try:
        d = {"kind": "cron", "min": _field(mi, 0, 59), "hour": _field(h, 0, 23), "dom": _field(dom, 1, 31),
             "mon": _field(mon, 1, 12), "dow": {x % 7 for x in _field(dow, 0, 7)},
             "dom_star": dom == "*", "dow_star": dow == "*"}
    except (ValueError, TypeError):
        raise ValueError(f"bad cron: {expr!r}")
    return d


def _cron_match(c, t):
    if t.minute not in c["min"] or t.hour not in c["hour"] or t.month not in c["mon"]:
        return False
    dom_ok, dow_ok = t.day in c["dom"], ((t.weekday() + 1) % 7) in c["dow"]
    if c["dom_star"] or c["dow_star"]:
        return dom_ok and dow_ok
    return dom_ok or dow_ok  # cron rule when both are restricted


def prev_fire(c, now, days=8):
    """Latest cron fire time (epoch) <= now within `days`, else None."""
    t = dt.datetime.fromtimestamp(now).replace(second=0, microsecond=0)
    for _ in range(days * 1440):
        if _cron_match(c, t):
            return t.timestamp()
        t -= dt.timedelta(minutes=1)
    return None


def check_due(job, now):
    """-> (action, fire_ts, note). action: 'run' | 'skip' | None."""
    if not job.get("enabled", True):
        return None, None, ""
    try:
        s = parse_when(job["when"])
    except Exception:
        return None, None, ""
    base = max(job.get("last_run") or 0, job.get("created") or 0)
    if s["kind"] == "once":
        if job.get("last_run") or now < s["ts"]:
            return None, None, ""
        if now - s["ts"] > GRACE:
            return "skip", s["ts"], "missed (Mac was asleep or off), skipped"
        return "run", s["ts"], ""
    if s["kind"] == "every":
        due = base + s["seconds"]
        if now < due:
            return None, None, ""
        if now - due > GRACE:
            return "skip", now, "missed while Mac was asleep, skipped; interval restarts now"
        return "run", due, ""
    f = prev_fire(s, now)
    if f is None or f <= base:
        return None, None, ""
    if now - f > GRACE:
        return "skip", f, "missed " + dt.datetime.fromtimestamp(f).strftime("%a %H:%M") + " (Mac was asleep or off), skipped"
    return "run", f, ""


# ---------------------------------------------------------------- storage
def load(path=None):
    try:
        d = json.loads(Path(path or SCHEDULE).read_text(encoding="utf-8"))
        return d if isinstance(d, list) else []
    except (OSError, ValueError):
        return []


def _locked_update(fn, path=None):
    p = Path(path or SCHEDULE)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(str(p) + ".lock", "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        jobs = load(p)
        res = fn(jobs)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(jobs, indent=1, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, p)
        return res


def add_job(when, task, deliver="telegram", path=None):
    parse_when(when)
    if deliver not in ("telegram", "pill", "both"):
        raise ValueError("deliver must be telegram|pill|both")
    job = {"id": uuid.uuid4().hex[:6], "when": when, "task": task.strip(), "deliver": deliver,
           "enabled": True, "created": time.time(), "last_run": None, "note": ""}
    _locked_update(lambda jobs: jobs.append(job), path)
    return job


def _set(jid, path, **kw):
    def fn(jobs):
        for j in jobs:
            if j["id"] == jid:
                j.update(kw)
                return True
        return False
    return _locked_update(fn, path)


def remove_job(jid, path=None):
    # "remove" = disable and mark removed (nothing is ever deleted; the job stays in the file as history)
    return _set(jid, path, enabled=False, removed=True)


def list_text(path=None):
    jobs = [j for j in load(path) if not j.get("removed")]
    if not jobs:
        return "No scheduled jobs."
    rows = []
    for j in jobs:
        st = "on" if j.get("enabled", True) else "paused"
        last = dt.datetime.fromtimestamp(j["last_run"]).strftime("%d %b %H:%M") if j.get("last_run") else "never"
        rows.append(f"{j['id']} [{st}] {j['when']} -> {j['deliver']}\n  {j['task'][:80]} (last: {last})" + (f"\n  note: {j['note']}" if j.get("note") else ""))
    return "\n".join(rows)


# ---------------------------------------------------------------- runner
def tick(ask_fn, deliver_fn, now=None, path=None, log_fn=None):
    """Run what is due. ask_fn(prompt)->text, deliver_fn(job, text). Returns list of (id, action)."""
    now = now or time.time()
    done = []
    for j in load(path):
        if j.get("removed"):
            continue
        action, fire, note = check_due(j, now)
        if not action:
            continue
        once = parse_when(j["when"])["kind"] == "once"
        kw = {"last_run": fire, "note": note}
        if once:
            kw["enabled"] = False
        _set(j["id"], path, **kw)  # mark first so a slow run is never repeated
        if action == "skip":
            (log_fn or _log)(f"skip {j['id']}: {note}")
            continue
        try:
            prompt = (f"[system] Scheduled job {j['id']} (set up by the user). Do this now and reply with ONLY the short message to deliver "
                      f"(max ~6 lines, no preamble). Do not send messages/emails to anyone, do not delete anything, do not speak; "
                      f"just report to the user.\nTask: {j['task']}")
            text = (ask_fn(prompt) or "").strip()
            if text:
                deliver_fn(j, text)
            (log_fn or _log)(f"ran {j['id']} ({len(text)} chars)")
        except Exception as e:
            (log_fn or _log)(f"error {j['id']}: {type(e).__name__} {str(e)[:100]}")
        done.append((j["id"], action))
    return done


def _log(msg):
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(f"{dt.datetime.now():%Y-%m-%d %H:%M:%S} {msg}\n")
    except OSError:
        pass


def start(ask_fn, deliver_fn):
    """Daemon thread: tick every 30 s. Wake from sleep is handled by check_due (late < 2 h runs once)."""
    def loop():
        time.sleep(20)  # let the app finish booting
        while True:
            try:
                tick(ask_fn, deliver_fn)
            except Exception as e:
                print("[scheduler]", e)
            time.sleep(TICK)
    th = threading.Thread(target=loop, daemon=True, name="scheduler")
    th.start()
    return th


def main(argv=None):
    ap = argparse.ArgumentParser(prog="scheduler.py")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add")
    a.add_argument("when")
    a.add_argument("task")
    a.add_argument("--deliver", default="telegram", choices=["telegram", "pill", "both"])
    sub.add_parser("list")
    for c in ("remove", "pause", "resume"):
        sub.add_parser(c).add_argument("id")
    args = ap.parse_args(argv)
    try:
        if args.cmd == "add":
            j = add_job(args.when, args.task, args.deliver)
            print(f"added {j['id']}: {j['when']} -> {j['deliver']}")
        elif args.cmd == "list":
            print(list_text())
        elif args.cmd == "remove":
            print("removed" if remove_job(args.id) else "no such job")
        else:
            ok = _set(args.id, None, enabled=(args.cmd == "resume"))
            print(args.cmd + "d" if ok else "no such job")
    except ValueError as e:
        print("error:", e)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
