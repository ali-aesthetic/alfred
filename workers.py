#!/usr/bin/env python3
"""Alfred parallel workers: run up to N headless `claude -p` helpers at once.

  python3 workers.py run --tasks tasks.json [--model haiku|sonnet] [--max 3] [--timeout 300]

tasks.json: ["prompt", ...]  or  [{"id": "a", "prompt": "...", "gui": false, "model": "haiku", "timeout": 120, "tools": true}, ...]
GUI tasks ("gui": true) take a global file lock: only one worker touches the screen at a time.
Prints one JSON summary. Logs: data/workers/<run>/<id>/{prompt.txt,out.json,err.txt}
"""
from alfred_home import HOME_STR as _AH, CTL as _CTL
import argparse, concurrent.futures as cf, fcntl, json, os, shutil, signal, subprocess, sys, time
from pathlib import Path

HOME = Path(_AH)
LOCK = HOME / "data" / "workers" / ".gui.lock"
# same deny list the brain uses (brain_cc.DENIED)
DENIED = ["Bash(rm *)", "Bash(rmdir *)", "Bash(sudo *)", "Bash(diskutil *)", "Bash(shutdown *)", "Bash(reboot *)",
          "Bash(halt *)", "Bash(dd *)", "Bash(mkfs *)", "Bash(security *)", "Bash(launchctl *)", "Bash(killall *)",
          "Bash(defaults write *)", "Bash(chmod -R *)", "Bash(chown *)", "Bash(srm *)", "Bash(shred *)"]
ALLOWED = ["Bash", "Read", "Glob", "Grep", "WebSearch", "WebFetch", "Write", "Edit"]
PERSONA = ("You are a Alfred worker, one of several running in parallel. Do ONLY your sub-task. "
           "No GUI clicking or computer control unless the task explicitly says so. "
           "Never send messages/emails, never remove anything (move it to a 'to delete' folder instead), never play sound. "
           "Reply with a result of at most 10 short lines, key answer first. No preamble.")


def find_claude():
    for p in (shutil.which("claude"), str(Path.home() / ".local/bin/claude"), "/opt/homebrew/bin/claude", "/usr/local/bin/claude"):
        if p and os.path.exists(p):
            return p


def run_one(t, claude, run_dir, default_model, default_timeout):
    tid, model = str(t["id"]), t.get("model") or default_model
    timeout = float(t.get("timeout") or default_timeout)
    d = run_dir / tid
    d.mkdir(parents=True, exist_ok=True)
    (d / "prompt.txt").write_text(t["prompt"])
    args = [claude, "-p", t["prompt"], "--output-format", "json", "--model", model,
            "--permission-mode", "acceptEdits", "--allowedTools", ",".join(ALLOWED),
            "--disallowedTools", ",".join(DENIED), "--max-turns", str(t.get("max_turns", 12)),
            "--append-system-prompt", PERSONA]
    if "haiku" not in model:
        args += ["--effort", "low"]
    if not t.get("tools", True):  # pure text job: no tools/plugins = fast
        args += ["--tools", "", "--strict-mcp-config", "--disable-slash-commands", "--setting-sources", ""]
    env = os.environ.copy()
    env.pop("ANTHROPIC_API_KEY", None)  # subscription only
    env["PATH"] = f"{HOME}/bin:/opt/homebrew/bin:/usr/local/bin:{Path.home()}/.local/bin:" + env.get("PATH", "")
    res = {"id": tid, "ok": False, "result": "", "secs": 0.0}
    lockf = None
    t0 = time.time()
    try:
        if t.get("gui"):
            LOCK.parent.mkdir(parents=True, exist_ok=True)
            lockf = open(LOCK, "w")
            fcntl.flock(lockf, fcntl.LOCK_EX)  # one screen user at a time
            res["gui_wait"] = round(time.time() - t0, 1)
        p = subprocess.Popen(args, cwd=str(HOME), env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True, start_new_session=True)
        try:
            out, err = p.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(p.pid, signal.SIGKILL)
            p.communicate()
            res.update(result=f"TIMEOUT after {int(timeout)}s", timeout=True)
            return res
        (d / "err.txt").write_text(err or "")
        (d / "out.json").write_text(out or "")
        data = None
        for line in reversed((out or "").strip().splitlines() or [""]):
            if line.strip().startswith("{"):
                try:
                    data = json.loads(line)
                    break
                except json.JSONDecodeError:
                    pass
        if data is None:
            res["result"] = ((out or err or "empty reply")[-500:]).strip()
        else:
            res["ok"] = not data.get("is_error")
            res["result"] = str(data.get("result", "")).strip()
            res["cost_usd"] = data.get("total_cost_usd")
    except Exception as e:
        res["result"] = f"ERROR {type(e).__name__}: {e}"
    finally:
        res["secs"] = round(time.time() - t0, 1)
        if lockf:
            fcntl.flock(lockf, fcntl.LOCK_UN)
            lockf.close()
    return res


def run(tasks, model="sonnet", max_workers=3, timeout=300):
    claude = find_claude()
    if not claude:
        return {"ok": False, "error": "NO_CLAUDE", "results": []}
    norm = []
    for i, t in enumerate(tasks, 1):
        t = {"prompt": t} if isinstance(t, str) else dict(t)
        t.setdefault("id", i)
        norm.append(t)
    run_dir = HOME / "data" / "workers" / time.strftime("%Y%m%d-%H%M%S")
    run_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    with cf.ThreadPoolExecutor(max_workers=max(1, min(int(max_workers), 3))) as ex:
        results = list(ex.map(lambda t: run_one(t, claude, run_dir, model, timeout), norm))
    return {"ok": all(r["ok"] for r in results), "wall_secs": round(time.time() - t0, 1),
            "sum_secs": round(sum(r["secs"] for r in results), 1), "log_dir": str(run_dir), "results": results}


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--tasks", required=True)
    r.add_argument("--model", default="sonnet", choices=["haiku", "sonnet"])
    r.add_argument("--max", type=int, default=3)
    r.add_argument("--timeout", type=float, default=300)
    a = ap.parse_args()
    out = run(json.loads(Path(a.tasks).read_text()), a.model, a.max, a.timeout)
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
