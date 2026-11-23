"""Telegram bridge: the user texts Alfred from his phone. Stdlib only (urllib long-polling).
Only the paired owner chat is ever answered or written to; every other chat is ignored silently.
Token: data/telegram_bot_token (never printed/logged). Owner: data/telegram_owner.json ({"chat_id": N}).
Pairing: data/telegram_pair.json holds a sha256 of the 6-digit code (written by "Set Telegram bot.command").
Silent: nothing here speaks.
"""
from alfred_home import HOME_STR as _AH, CTL as _CTL
import hashlib, json, os, re, subprocess, threading, time, uuid, urllib.request, urllib.error
from pathlib import Path

import away as away_mod

HOME = Path(__file__).resolve().parent
DATA = HOME / "data"
TOKEN_FILE = DATA / "telegram_bot_token"
OWNER_FILE = DATA / "telegram_owner.json"
PAIR_FILE = DATA / "telegram_pair.json"
INBOX = Path.home() / "Downloads" / "From phone"
CTL = _CTL
PAIR_TTL = 15 * 60
MAX_TRIES = 5

CB = "jv:"  # callback grammar: jv:<verb>[:<id>] (ASCII, <=64 bytes, no user text)
QUICK = [["What's on today?", "Screen"], ["Play my sleep playlist", "Stop"]]
COMMANDS = [("menu", "Open the menu"), ("status", "Alfred status"), ("screen", "Screenshot of the Mac"), ("tasks", "Away tasks"),
            ("jobs", "Scheduled jobs"), ("skills", "Active + pending skills"), ("stop", "Stop away tasks"), ("awake", "Keep the Mac awake on/off"), ("help", "Help")]
SCREENS = {"st": "Status", "ta": "Tasks", "jo": "Jobs", "sk": "Skills"}

HELP = ("/menu - buttons\n/status - awake, mic, battery, what I'm doing\n/screen - screenshot of the Mac\n/tasks - away tasks\n"
        "/stop - stop away tasks\n/awake - keep the Mac awake (on/off)\n/jobs - scheduled jobs\n/skills - active + pending skills\n/help\n\nJust text me a task. \"...until I get home\" = long background task. "
        "Voice notes, photos and files work too.")


def parse_command(text):
    """'/status@MyBot x' -> ('status', 'x'); not a command -> (None, text)."""
    m = re.match(r"^/(\w+)(?:@\w+)?(?:\s+(.*))?$", (text or "").strip(), re.S)
    if not m:
        return None, (text or "").strip()
    return m.group(1).lower(), (m.group(2) or "").strip()


def cb(*parts):
    """Build callback_data 'jv:a:b'. Raises if longer than Telegram's 64 bytes."""
    d = CB + ":".join(str(p) for p in parts)
    if len(d.encode()) > 64:
        raise ValueError("callback_data too long")
    return d


def inline_kb(rows):
    """rows [[(label, callback_data), ...], ...] -> Bot API reply_markup dict."""
    return {"inline_keyboard": [[{"text": t, "callback_data": d} for t, d in row] for row in rows]}


def quick_kb():
    return {"keyboard": [[{"text": t} for t in row] for row in QUICK], "resize_keyboard": True, "is_persistent": True}


def send_with_buttons(text, rows, tg=None, pairing=None):
    """Send text + inline buttons to the paired owner only. Returns message_id or None."""
    cid = (pairing or Pairing()).owner()
    if cid is None or not text:
        return None
    r = (tg or Telegram()).call("sendMessage", {"chat_id": cid, "text": text[:3900], "reply_markup": inline_kb(rows)})
    return (r.get("result") or {}).get("message_id")


def code_hash(code):
    return hashlib.sha256(str(code).strip().encode()).hexdigest()


class Pairing:
    def __init__(self, pair_file=PAIR_FILE, owner_file=OWNER_FILE, now_fn=time.time):
        self.pf, self.of, self.now = Path(pair_file), Path(owner_file), now_fn

    def owner(self):
        try:
            return int(json.loads(self.of.read_text())["chat_id"])
        except Exception:
            return None

    def try_pair(self, chat_id, code):
        """True only if a pending, unexpired code matches. Stores ONLY the chat id."""
        try:
            d = json.loads(self.pf.read_text())
        except Exception:
            return False
        if not d.get("hash") or self.now() > d.get("expires", 0) or d.get("tries", 0) >= MAX_TRIES:
            return False
        if code_hash(code) != d["hash"]:
            d["tries"] = d.get("tries", 0) + 1
            self.pf.write_text(json.dumps(d))
            return False
        old = os.umask(0o077)
        try:
            self.of.write_text(json.dumps({"chat_id": int(chat_id)}))
            os.chmod(self.of, 0o600)
            self.pf.write_text("{}")  # code is single-use
        finally:
            os.umask(old)
        return True


class Telegram:
    """Minimal Bot API client. Token is read from file, never exposed."""
    def __init__(self, token_file=TOKEN_FILE):
        self.tf = Path(token_file)

    def _tok(self):
        return self.tf.read_text().strip()

    def call(self, method, params=None, files=None, timeout=40):
        url = f"https://api.telegram.org/bot{self._tok()}/{method}"
        if files:
            b = uuid.uuid4().hex
            body = b""
            for k, v in (params or {}).items():
                body += f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
            for k, path in files.items():
                body += (f'--{b}\r\nContent-Disposition: form-data; name="{k}"; filename="{Path(path).name}"\r\n'
                         f'Content-Type: application/octet-stream\r\n\r\n').encode() + Path(path).read_bytes() + b"\r\n"
            body += f"--{b}--\r\n".encode()
            req = urllib.request.Request(url, body, {"Content-Type": f"multipart/form-data; boundary={b}"})
        else:
            req = urllib.request.Request(url, json.dumps(params or {}).encode(), {"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())

    def download(self, file_id, dest):
        info = self.call("getFile", {"file_id": file_id})["result"]
        url = f"https://api.telegram.org/file/bot{self._tok()}/{info['file_path']}"
        with urllib.request.urlopen(url, timeout=60) as r, open(dest, "wb") as f:
            f.write(r.read())
        return dest


class Bridge:
    def __init__(self, ask_fn, emit, get_settings, tg=None, pairing=None, away=None, stt_fn=None, inbox=INBOX,
                 set_setting=None, insights=None):
        self.ask_fn, self.emit, self.get_settings = ask_fn, emit or (lambda *a, **k: None), get_settings or (lambda: {})
        self.tg = tg or Telegram()
        self.pairing = pairing or Pairing()
        self.inbox = Path(inbox)
        self.stt_fn = stt_fn or self._stt
        self.stt = None
        self.busy = ""
        self.offset = 0
        self.away = away or away_mod.Away(self.ask_fn, self.send, self.send_photo, self._screenshot, send_kb=self.send_kb)
        self.set_setting = set_setting or self._set_setting
        self.insights = insights
        self.menu_msg = None
        self.commands_set = False

    # ----- outgoing: ONLY to the paired owner
    def send(self, text):
        cid = self.pairing.owner()
        if cid is None or not text:
            return
        try:
            for i in range(0, len(text), 3900):
                self.tg.call("sendMessage", {"chat_id": cid, "text": text[i:i + 3900]})
        except Exception as e:
            print("[telegram] send failed:", type(e).__name__)

    def send_kb(self, text, rows):
        """Message with inline buttons, owner only. Returns message_id or None."""
        try:
            return send_with_buttons(text, rows, self.tg, self.pairing)
        except Exception as e:
            print("[telegram] send_kb failed:", type(e).__name__)
            return None

    def send_photo(self, path, caption=""):
        cid = self.pairing.owner()
        if cid is None:
            return
        try:
            self.tg.call("sendPhoto", {"chat_id": cid, "caption": caption[:200]}, files={"photo": path})
        except Exception as e:
            print("[telegram] photo failed:", type(e).__name__)

    # ----- helpers
    def _screenshot(self, path):
        subprocess.run([CTL, "screenshot", path], capture_output=True, timeout=30)

    def _stt(self, wav_path):
        """Voice note -> text with the existing Whisper in voice.py."""
        import numpy as np, voice
        raw = subprocess.run(["ffmpeg", "-v", "quiet", "-i", wav_path, "-f", "s16le", "-ac", "1", "-ar", "16000", "-"],
                             capture_output=True, timeout=60).stdout
        a = np.frombuffer(raw, dtype=np.int16)
        if len(a) < 4800:
            return ""
        if self.stt is None:
            self.stt = voice.STT(json.loads((HOME / "config.json").read_text()))
        r = self.stt.transcribe(a)
        text = r[0] if isinstance(r, tuple) else r
        return "" if voice.is_hallucination(text) else (text or "").strip()

    def _battery(self):
        try:
            out = subprocess.run(["pmset", "-g", "batt"], capture_output=True, text=True, timeout=3).stdout
            m = re.search(r"(\d+)%;\s*([\w ]+);", out)
            return f"{m.group(1)}% ({m.group(2).strip()})" if m else "?"
        except Exception:
            return "?"

    def _ui_state(self):
        try:
            p = DATA / "ui" / "events.jsonl"
            with open(p, "rb") as f:
                f.seek(0, 2)
                f.seek(max(0, f.tell() - 20000))
                lines = f.read().decode("utf-8", "ignore").splitlines()
            for ln in reversed(lines):
                if '"type": "state"' in ln or '"type":"state"' in ln:
                    return json.loads(ln).get("state", "?")
        except Exception:
            pass
        return "?"

    def status_text(self):
        s = {}
        try:
            s = self.get_settings() or {}
        except Exception:
            pass
        awake = "asleep" if s.get("silent") or self._ui_state() == "asleep" else "awake"
        doing = self.away.doing() or self.busy or self._ui_state()
        return f"Alfred: {awake}\nStay awake: {'on' if self._awake_setting() else 'off'}\nMic: {'off' if s.get('mic_off') else 'on'}\nBattery: {self._battery()}\nDoing: {doing}"

    # ----- incoming
    def handle_update(self, u):
        """Process one Telegram update. Returns a tag (for tests): ignored|paired|command:x|away|answer|ask|file|voice."""
        if u.get("callback_query"):
            return self._callback(u["callback_query"])
        msg = u.get("message") or {}
        chat = (msg.get("chat") or {}).get("id")
        if chat is None:
            return "ignored"
        text = msg.get("text") or msg.get("caption") or ""
        owner = self.pairing.owner()
        if owner is None or chat != owner:
            cmd, arg = parse_command(text)
            if owner is None and cmd == "pair" and re.fullmatch(r"\d{6}", arg or ""):
                if self.pairing.try_pair(chat, arg):
                    self.send("Paired. Only this chat can talk to Alfred now. /help")
                    return "paired"
            return "ignored"  # silent for every other chat
        # voice notes
        if msg.get("voice") or msg.get("audio"):
            return self._voice(msg)
        if msg.get("photo") or msg.get("document"):
            return self._file(msg, text)
        cmd, arg = parse_command(text)
        if cmd:
            return self._command(cmd, arg)
        if not text.strip():
            return "ignored"
        return self._text(text)

    # ----- callbacks / menu
    def _set_setting(self, key, value):
        """Default setter for menu toggles (same effect as the app's h_set)."""
        import ui_bridge
        ui_bridge.set_setting(key, value, save=True, announce=False)
        if key == "silent":
            import silent
            silent.set_on(bool(value))
        elif key == "mic_off":
            import menubar
            menubar.set_mic_off(bool(value))
        try:
            ui_bridge.send_settings()
        except Exception:
            pass

    def _answer(self, qid, text=""):
        try:
            self.tg.call("answerCallbackQuery", {"callback_query_id": qid, "text": text[:100]})
        except Exception as e:
            print("[telegram] answer failed:", type(e).__name__)

    def _edit(self, chat, mid, text, rows=None):
        p = {"chat_id": chat, "message_id": mid, "text": text[:3900], "reply_markup": inline_kb(rows or [])}
        try:
            self.tg.call("editMessageText", p)
        except urllib.error.HTTPError as e:
            if e.code != 400:  # 400 = "message is not modified": fine
                print("[telegram] edit failed:", e.code)
        except Exception as e:
            print("[telegram] edit failed:", type(e).__name__)

    def _callback(self, q):
        """Owner-only. Anyone else (wrong chat OR wrong user) is ignored silently, not even answered."""
        m = q.get("message") or {}
        chat = (m.get("chat") or {}).get("id")
        owner = self.pairing.owner()
        if owner is None or chat != owner or (q.get("from") or {}).get("id") != owner:
            return "ignored"
        data, qid, mid = q.get("data") or "", q.get("id"), m.get("message_id")
        parts = data.split(":")
        if len(data.encode()) > 64 or parts[0] != "jv" or len(parts) < 2:
            self._answer(qid)
            return "cb:bad"
        verb, arg = parts[1], (parts[2] if len(parts) > 2 else "")
        a = self.away
        if verb == "m":  # menu: jv:m:<screen>
            self._menu(chat, mid, qid, arg)
        elif verb in ("sa", "sr"):  # skill approve / reject
            try:
                import skills_gate
                g = skills_gate.default_gate()
                res = g.approve(arg) if verb == "sa" else g.reject(arg)
            except Exception as e:
                res = "Skills unavailable: " + type(e).__name__
            self._answer(qid, res)
            self._edit(chat, mid, res)
        elif verb in ("ay", "an"):  # away irreversible yes/no
            ok = a.waiting_for_answer() and a.answer(verb == "ay")
            res = ("Yes - doing it." if verb == "ay" else "No - skipping it.") if ok else "That question is no longer waiting."
            self._answer(qid, res)
            self._edit(chat, mid, (m.get("text") or "")[:600] + "\n\n" + res)
        elif verb == "ap":
            r = a.pause_toggle(arg) or ""
            self._answer(qid, r.capitalize() or "Nothing to pause")
            if r:
                rows = [[("▶ Resume" if r == "paused" else "⏸ Pause", cb("ap", arg)), ("⏹ Stop", cb("as", arg)), ("📸 Screen", cb("asc", arg))]]
                self._edit(chat, mid, (m.get("text") or "").split("\n\n")[0] + f"\n\n{'Paused' if r == 'paused' else 'Running'}.", rows)
        elif verb == "as":
            n = a.stop_all()
            self._answer(qid, "Stopped" if n else "Nothing running")
            self._edit(chat, mid, (m.get("text") or "")[:600] + "\n\nStopped." if n else "Nothing running.")
        elif verb == "asc":
            self._answer(qid, "Sending screen")
            self._command("screen", "")
        elif verb in ("io", "ix", "iy", "in") and self.insights:
            res = self.insights.callback(verb, arg)
            self._answer(qid, res)
            self._edit(chat, mid, res)
        else:
            self._answer(qid)
            return "cb:unknown"
        return f"cb:{verb}"

    def _awake_setting(self):
        try:
            import ui_bridge
            return bool(ui_bridge.get("stay_awake", False))
        except Exception:
            return False

    def menu_rows(self):
        s = {}
        try:
            s = self.get_settings() or {}
        except Exception:
            pass
        ins = False
        try:
            import ui_bridge
            ins = bool(ui_bridge.get("insights", False))
        except Exception:
            pass
        return [[("📊 Status", cb("m", "st")), ("🖥 Screen", cb("m", "sc"))],
                [("📋 Tasks", cb("m", "ta")), ("⏱ Jobs", cb("m", "jo"))],
                [("🧩 Skills", cb("m", "sk")), (f"🎤 Mic: {'off' if s.get('mic_off') else 'on'}", cb("m", "mic"))],
                [(f"🔇 Silent: {'on' if s.get('silent') else 'off'}", cb("m", "sil")), (f"💡 Insights: {'on' if ins else 'off'}", cb("m", "ins"))],
                [(f"☕ Stay awake: {'on' if self._awake_setting() else 'off'}", cb("m", "aw"))],
                [("✖ Close", cb("m", "x"))]]

    def open_menu(self):
        """/menu: ONE message; every tap edits it in place."""
        self.menu_msg = self.send_kb("Alfred menu", self.menu_rows())

    def _menu(self, chat, mid, qid, scr):
        back = [[("‹ Back", cb("m", "r"))]]
        if scr in ("r", ""):
            self._answer(qid)
            self._edit(chat, mid, "Alfred menu", self.menu_rows())
        elif scr == "x":
            self._answer(qid, "Closed")
            self._edit(chat, mid, "Menu closed. /menu to open again.")
        elif scr == "sc":
            self._answer(qid, "Sending screen")
            self._command("screen", "")
        elif scr in ("mic", "sil", "ins", "aw"):
            try:
                s = self.get_settings() or {}
                if scr == "mic":
                    self.set_setting("mic_off", not s.get("mic_off"))
                elif scr == "sil":
                    self.set_setting("silent", not s.get("silent"))
                elif scr == "aw":
                    self.set_setting("stay_awake", not self._awake_setting())
                else:
                    import ui_bridge
                    self.set_setting("insights", not ui_bridge.get("insights", False))
            except Exception as e:
                print("[telegram] toggle failed:", type(e).__name__)
            self._answer(qid, "Done")
            # the app may need a moment to reflect the new state; rows read the live settings
            self._edit(chat, mid, "Alfred menu", self.menu_rows())
        elif scr in SCREENS:
            self._answer(qid)
            self._edit(chat, mid, self._screen_text(scr), back)
        else:
            self._answer(qid)

    def _screen_text(self, scr):
        try:
            if scr == "st":
                return self.status_text()
            if scr == "ta":
                return self.away.list_text()
            if scr == "jo":
                import scheduler
                return scheduler.list_text()
            import skills_gate
            return skills_gate.default_gate().list_text()
        except Exception as e:
            return "Unavailable: " + type(e).__name__

    def _setup_commands(self):
        """Fill the '/' menu in Telegram (once per run)."""
        if self.commands_set:
            return
        try:
            self.tg.call("setMyCommands", {"commands": [{"command": c, "description": d} for c, d in COMMANDS]})
            self.commands_set = True
        except Exception as e:
            print("[telegram] setMyCommands failed:", type(e).__name__)

    def _command(self, cmd, arg):
        if cmd == "menu":
            self.open_menu()
        elif cmd == "start":
            cid = self.pairing.owner()
            try:
                self.tg.call("sendMessage", {"chat_id": cid, "text": "Quick buttons are on. /help for commands.", "reply_markup": quick_kb()})
            except Exception as e:
                print("[telegram] kb failed:", type(e).__name__)
            self.open_menu()
        elif cmd == "help":
            self.send(HELP)
        elif cmd == "status":
            self.send(self.status_text())
        elif cmd == "screen":
            p = str(DATA / "away" / "screen.png")
            Path(p).parent.mkdir(parents=True, exist_ok=True)
            self._screenshot(p)
            if os.path.exists(p):
                self.send_photo(p, "Mac screen")
            else:
                self.send("Screenshot failed.")
        elif cmd == "stop":
            n = self.away.stop_all()
            self.send(f"Stopped {n} away task(s)." if n else "Nothing running.")
        elif cmd == "tasks":
            self.send(self.away.list_text())
        elif cmd == "jobs":
            try:
                import scheduler
                self.send(scheduler.list_text())
            except Exception as e:
                self.send("Jobs unavailable: " + type(e).__name__)
        elif cmd == "skills" or cmd.startswith(("approve_", "reject_")):
            try:
                import skills_gate
                self.send(skills_gate.default_gate().handle_command(cmd) or "Unknown command. /help")
            except Exception as e:
                self.send("Skills unavailable: " + type(e).__name__)
        elif cmd == "awake":
            v = {"on": True, "off": False}.get(arg.strip().lower(), not self._awake_setting())
            self.set_setting("stay_awake", v)
            self.send("☕ Stay awake: on. Keep it plugged in; the lid must stay open." if v else "Stay awake: off. The Mac can sleep normally.")
        elif cmd == "pair":
            self.send("Already paired.")
        else:
            self.send("Unknown command. /help")
        return f"command:{cmd}"

    def _text(self, text):
        alias = text.strip().lower()
        if alias in ("stop", "screen"):  # reply-keyboard quick buttons
            self._command(alias, "")
            return f"command:{alias}"
        if self.away.waiting_for_answer():
            yn = away_mod.parse_yes_no(text)
            if yn is not None:
                self.away.answer(yn)
                return "answer"
        p = away_mod.parse_away(text)
        if p:
            tid = self.away.submit(text, p)
            self.send(f"Queued #{tid}. I will work on it in the background.")
            return "away"
        threading.Thread(target=self._ask, args=(text,), daemon=True).start()
        return "ask"

    def _ask(self, text):
        self.busy = text[:60]
        try:
            self.emit("step", text="Telegram: " + text[:40], done=False)
        except Exception:
            pass
        try:
            try:
                reply = self.ask_fn(text, source="telegram")
            except TypeError:
                reply = self.ask_fn(text)
            self.send((reply or "Done.").strip())
        except Exception as e:
            self.send(f"Failed: {str(e)[:150]}")
        finally:
            self.busy = ""
            try:
                self.emit("step", text="Telegram", done=True)
            except Exception:
                pass

    def _voice(self, msg):
        v = msg.get("voice") or msg.get("audio")
        self.inbox.mkdir(parents=True, exist_ok=True)
        tmp = str(DATA / "away" / f"voice-{int(time.time())}.ogg")
        Path(tmp).parent.mkdir(parents=True, exist_ok=True)
        try:
            self.tg.download(v["file_id"], tmp)
            text = self.stt_fn(tmp)
        except Exception as e:
            self.send(f"Could not read the voice note: {str(e)[:100]}")
            return "voice"
        if not text:
            self.send("I heard nothing in that voice note.")
            return "voice"
        self.send(f"Heard: {text[:200]}")
        self._text(text)
        return "voice"

    def _file(self, msg, caption):
        self.inbox.mkdir(parents=True, exist_ok=True)
        if msg.get("photo"):
            fid, name = msg["photo"][-1]["file_id"], f"photo-{int(time.time())}.jpg"
        else:
            d = msg["document"]
            fid, name = d["file_id"], re.sub(r"[^\w.\- ]", "_", d.get("file_name") or f"file-{int(time.time())}")
        dest = self.inbox / name
        n = 1
        while dest.exists():  # never overwrite
            dest = self.inbox / f"{Path(name).stem}-{n}{Path(name).suffix}"
            n += 1
        try:
            self.tg.download(fid, str(dest))
        except Exception as e:
            self.send(f"Download failed: {str(e)[:100]}")
            return "file"
        self.send(f"Saved to {dest}")
        self._text(f"I sent you a file from my phone, saved at {dest}. {caption}".strip())
        return "file"

    # ----- loop
    def loop(self):
        while True:
            if not TOKEN_FILE.exists():
                time.sleep(30)
                continue
            self._setup_commands()
            try:
                r = self.tg.call("getUpdates", {"offset": self.offset, "timeout": 30, "allowed_updates": ["message", "callback_query"]}, timeout=45)
                for u in r.get("result", []):
                    self.offset = u["update_id"] + 1
                    try:
                        self.handle_update(u)
                    except Exception as e:
                        print("[telegram] update error:", type(e).__name__, str(e)[:100])
            except urllib.error.HTTPError as e:
                time.sleep(60 if e.code in (401, 404) else 5)  # bad token: slow retry
            except Exception:
                time.sleep(5)


def start(ask_fn, emit=None, get_settings=None):
    """Daemon thread. ask_fn(text, source=...) -> reply text."""
    b = Bridge(ask_fn, emit, get_settings)
    try:
        b.insights = _make_insights(b)
        threading.Thread(target=_insight_loop, args=(b,), daemon=True, name="insights").start()
    except Exception as e:
        print("[telegram] insights unavailable:", type(e).__name__)
    threading.Thread(target=b.loop, daemon=True, name="telegram").start()
    return b


def _make_insights(b):
    import insights, scheduler, ui_bridge, skills_gate

    def model(prompt):
        br = skills_gate.BRAIN  # set by learn_review after the first turn; None -> skip until then
        if br is None:
            raise RuntimeError("brain not ready")
        j = br._run(prompt, model=br.cfg.get("cc_model", "haiku"), persona=False, timeout=60, max_turns=1, light=True)
        return "" if j.get("is_error") else j.get("result", "")
    return insights.Insights(b.send_kb, model, lambda: bool(ui_bridge.get("insights", False)),
                             lambda v: b.set_setting("insights", v), add_job=scheduler.add_job, jobs_text=scheduler.list_text)


def _insight_loop(b):
    time.sleep(120)
    while True:
        try:
            if TOKEN_FILE.exists() and b.pairing.owner() is not None:
                b.insights.tick()
        except Exception as e:
            print("[insights]", type(e).__name__)
        time.sleep(600)


def send_file(path, caption=""):
    """Send any file (video, doc, image) to the paired owner. Videos ≤50 MB go as video, else as document."""
    p = Path(path).expanduser()
    if not p.exists():
        return {"ok": False, "error": "file not found"}
    cid = Pairing().owner()
    if cid is None:
        return {"ok": False, "error": "not paired"}
    size_mb = p.stat().st_size / 1e6
    if size_mb > 50:
        return {"ok": False, "error": f"too big for Telegram bots ({size_mb:.0f} MB > 50 MB)"}
    method, field = ("sendVideo", "video") if p.suffix.lower() in (".mp4", ".mov", ".m4v") else ("sendDocument", "document")
    try:
        Telegram().call(method, {"chat_id": cid, "caption": caption[:200], "supports_streaming": "true"}, files={field: str(p)})
        return {"ok": True, "sent": p.name, "mb": round(size_mb, 1)}
    except Exception as e:
        return {"ok": False, "error": type(e).__name__}


if __name__ == "__main__":
    import sys
    if len(sys.argv) >= 3 and sys.argv[1] == "send-file":
        print(json.dumps(send_file(sys.argv[2], " ".join(sys.argv[3:]))))
    else:
        print('usage: telegram_bridge.py send-file PATH [caption]')
