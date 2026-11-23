#!/usr/bin/env python3
"""Alfred Console: a real window for Alfred (feed, typed commands, status, quick actions, settings).

  .venv/bin/python console.py            open the window
  .venv/bin/python console.py --serve    server only (open http://127.0.0.1:8765 in a browser)

Own process, so if it crashes Alfred keeps running. Talks to Alfred through files in data/:
  console_inbox.jsonl   typed commands (alfred.py picks them up, same brain as voice)
  console_status.json   what Alfred is doing right now (alfred.py writes it)
  log.jsonl             conversation (read-only here)
Only listens on 127.0.0.1. Nothing leaves the Mac.
"""
import datetime as dt
import json
import os
import re
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HOME = Path(__file__).resolve().parent
DATA = HOME / "data"
PORT = 8765
PY = sys.executable
TOGGLES = {"camera": "Camera", "hologram": "Hologram", "console_speak": "Speak typed replies"}
TOOL_WORDS = {"Bash": "ran", "Write": "wrote", "Edit": "edited", "Read": "read", "WebSearch": "searched",
              "WebFetch": "opened page", "Glob": "looked for files", "Grep": "searched files", "Skill": "used skill"}


def cfg():
    try:
        return json.loads((HOME / "config.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def set_cfg(key, value):
    p = HOME / "config.json"
    c = cfg()
    c[key] = value
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(c, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)


def feed(limit=120):
    """Last conversation entries from log.jsonl (same kinds as journal.py)."""
    out = []
    try:
        with (DATA / "log.jsonl").open("rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 400_000))
            lines = f.read().decode("utf-8", "ignore").splitlines()[1:]
    except OSError:
        return out
    for line in lines:
        try:
            x = json.loads(line)
        except ValueError:
            continue
        k, ts = x.get("type"), x.get("ts", 0)
        if k == "request":
            out.append({"ts": ts, "k": "you", "t": re.sub(r"^\[Sent from[^\]]*\]\s*", "", x.get("text", ""), flags=re.S)})
        elif k == "reply" and x.get("text"):
            out.append({"ts": ts, "k": "alfred", "t": x["text"]})
        elif k == "quick":
            out += [{"ts": ts, "k": "you", "t": x.get("text", "")}, {"ts": ts, "k": "alfred", "t": x.get("reply", "")}]
        elif k == "action":
            out.append({"ts": ts, "k": "act", "t": f"{TOOL_WORDS.get(x.get('tool'), x.get('tool', ''))}: {x.get('detail', '')}"})
        elif k == "holo":
            out.append({"ts": ts, "k": "act", "t": f"hologram: {x.get('title', '')}"})
        elif k == "protocol":
            out.append({"ts": ts, "k": "act", "t": f"protocol: {x.get('name', '')}"})
        elif k == "error":
            out.append({"ts": ts, "k": "err", "t": f"{x.get('where', '')}: {x.get('error', '')}"})
    return out[-limit:]


def battery():
    try:
        s = subprocess.run(["pmset", "-g", "batt"], capture_output=True, text=True, timeout=3).stdout
        import re
        m = re.search(r"(\d+)%", s)
        return {"pct": int(m.group(1)), "charging": "AC Power" in s} if m else None
    except Exception:
        return None


_batt = {"t": 0, "v": None}


def state():
    now = time.time()
    if now - _batt["t"] > 30:
        _batt.update(t=now, v=battery())
    try:
        st = json.loads((DATA / "console_status.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        st = {}
    alive = now - st.get("ts", 0) < 8
    c = cfg()
    return {"status": st.get("status", "offline") if alive else "offline", "last": st.get("last", "") if alive else "",
            "alive": alive, "model": c.get("cc_model", "?"), "brain": c.get("brain", "?"),
            "mic": alive and not (DATA / "mic_off").exists() and st.get("status") != "paused", "battery": _batt["v"],
            "toggles": {k: {"label": v, "on": bool(c.get(k, k == "console_speak" and False))} for k, v in TOGGLES.items()},
            "feed": feed(), "now": now}


def send(text):
    DATA.mkdir(exist_ok=True)
    with (DATA / "console_inbox.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": time.time(), "text": text}, ensure_ascii=False) + "\n")


def log_add(kind, **kw):
    with (DATA / "log.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": int(time.time()), "type": kind, **kw}, ensure_ascii=False) + "\n")


def action(name):
    if name == "wake":
        subprocess.Popen([PY, str(HOME / "protocol.py"), "wake"], cwd=HOME)
    elif name == "focus":
        subprocess.Popen([PY, str(HOME / "protocol.py"), "focus"], cwd=HOME)
    elif name == "diag":
        sys.path.insert(0, str(HOME))
        import quick
        reply = quick.diagnostics(cfg().get("address", "sir"))
        log_add("quick", text="Diagnostics", reply=reply)
    elif name == "log":
        subprocess.Popen([PY, str(HOME / "journal.py")], cwd=HOME)
    elif name == "brain":
        subprocess.Popen([PY, str(HOME / "vault.py"), "--open"], cwd=HOME)
    elif name == "start":
        if subprocess.run(["pgrep", "-f", "[J]arvis/alfred.py"], capture_output=True).returncode != 0:
            subprocess.Popen(["bash", str(HOME / "Start Alfred.command")], cwd=HOME, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    elif name == "stop":
        (DATA / "STOP").touch()
        subprocess.run("pkill -f '[j]arvis.command'; pkill -f '[J]arvis/alfred.py'; pkill -f '[J]arvis/boot_hud.py'; true", shell=True)
    elif name == "restart":
        action("stop")
        time.sleep(2)
        action("start")
    elif name == "mic":
        f = DATA / "mic_off"
        if f.exists():
            f.replace(DATA / "mic_off.old")
        else:
            f.touch()
    elif name == "grow":
        subprocess.Popen([PY, str(HOME / "vault_grow.py")], cwd=HOME)
    elif name == "holo":
        set_cfg("hologram", not cfg().get("hologram", True))
    else:
        return False
    return True


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, obj, code=200):
        b = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        if self.path.startswith("/api/state"):
            return self._json(state())
        if self.path.startswith("/core.mp4"):  # the amber spark-shell film (with Range support for WebKit video)
            data = (HOME / "core_loop_a.mp4").read_bytes()
            rng = self.headers.get("Range")
            if rng and rng.startswith("bytes="):
                a, _, z = rng[6:].partition("-")
                a = int(a or 0)
                z = int(z) if z else len(data) - 1
                self.send_response(206)
                self.send_header("Content-Range", f"bytes {a}-{z}/{len(data)}")
                data = data[a:z + 1]
            else:
                self.send_response(200)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        b = (HOME / "console.html").read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(b)

    def do_POST(self):
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0)) or 0) or b"{}")
        except ValueError:
            return self._json({"ok": False}, 400)
        if self.headers.get("Host", "").split(":")[0] not in ("127.0.0.1", "localhost"):
            return self._json({"ok": False}, 403)  # blocks DNS-rebinding from web pages
        if self.path == "/api/say" and str(body.get("text", "")).strip():
            send(str(body["text"]).strip()[:2000])
            return self._json({"ok": True})
        if self.path == "/api/action":
            return self._json({"ok": action(str(body.get("name")))})
        if self.path == "/api/config" and body.get("key") in TOGGLES:
            set_cfg(body["key"], bool(body.get("value")))
            return self._json({"ok": True})
        self._json({"ok": False}, 404)


def serve():
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


_DELEGATE = None


def window():
    from AppKit import (NSApplication, NSApplicationActivationPolicyRegular, NSBackingStoreBuffered, NSColor, NSMakeRect,
                        NSWindow, NSAppearance)
    from Foundation import NSURL, NSURLRequest
    from WebKit import WKWebView, WKWebViewConfiguration
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyRegular)
    try:  # Dock name + icon instead of "Python"
        from AppKit import NSImage
        from Foundation import NSBundle
        NSBundle.mainBundle().infoDictionary()["CFBundleName"] = "Alfred Console"
        app.setApplicationIconImage_(NSImage.alloc().initWithContentsOfFile_(str(HOME / "console-icon.png")))
    except Exception:
        pass
    w = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
        NSMakeRect(0, 0, 760, 860), 1 | 2 | 4 | 8 | (1 << 15), NSBackingStoreBuffered, False)  # titled closable mini resizable fullsize
    w.setTitle_("Alfred Console")
    w.setTitlebarAppearsTransparent_(True)
    w.setTitleVisibility_(1)
    w.setAppearance_(NSAppearance.appearanceNamed_("NSAppearanceNameDarkAqua"))
    w.setFrameAutosaveName_("AlfredConsole")
    w.setReleasedWhenClosed_(False)
    from AppKit import NSVisualEffectView
    fx = NSVisualEffectView.alloc().initWithFrame_(w.contentView().bounds())
    fx.setMaterial_(13)  # HUD window: dark frosted Apple glass
    fx.setBlendingMode_(0)
    fx.setState_(1)
    fx.setAutoresizingMask_(18)
    w.setContentView_(fx)
    w.setOpaque_(False)
    w.setBackgroundColor_(NSColor.clearColor())
    w.setTitle_("")
    wv = WKWebView.alloc().initWithFrame_configuration_(fx.bounds(), WKWebViewConfiguration.alloc().init())
    wv.setAutoresizingMask_(18)
    try:
        wv.setValue_forKey_(False, "drawsBackground")
    except Exception:
        pass
    fx.addSubview_(wv)
    wv.loadRequest_(NSURLRequest.requestWithURL_(NSURL.URLWithString_(f"http://127.0.0.1:{PORT}/?native=1")))
    if not w.setFrameUsingName_("AlfredConsole"):
        w.center()
    w.makeKeyAndOrderFront_(None)
    app.activateIgnoringOtherApps_(True)

    from Foundation import NSObject

    class D(NSObject):
        def applicationShouldTerminateAfterLastWindowClosed_(self, a):
            return True
    d = D.alloc().init()
    app.setDelegate_(d)
    global _DELEGATE
    _DELEGATE = d  # keep a reference alive
    app.run()


if __name__ == "__main__":
    try:
        serve()
    except OSError:  # already running: just show the existing server in a window
        if "--serve" in sys.argv:
            sys.exit(0)
    if "--serve" in sys.argv:
        print(f"http://127.0.0.1:{PORT}")
        while True:
            time.sleep(3600)
    window()
