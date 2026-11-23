#!/usr/bin/env python3
"""Alfred для Mac.

Запуск голосом:    $ALFRED_HOME/.venv/bin/python $ALFRED_HOME/alfred.py
Запуск текстом:    … alfred.py --text
"""
from alfred_home import HOME_STR as _AH, CTL as _CTL
import datetime as dt
import fcntl
import getpass
import json
import os
import queue
import random
import re
import shutil
import subprocess
import sys
import threading
import time
import traceback
from pathlib import Path

HOME = Path(__file__).resolve().parent
sys.path.insert(0, str(HOME))

from memory import Memory, Log, State  # noqa: E402
from skills_manager import Skills  # noqa: E402
import voice  # noqa: E402
import silent  # noqa: E402
import quick  # noqa: E402
import menubar  # noqa: E402
import ui_bridge  # noqa: E402
import address as _address_mod  # noqa: E402
import panels  # noqa: E402
import duck  # noqa: E402
from tools_mac import Hands  # noqa: E402
from brain import Brain  # noqa: E402
from brain_cc import ClaudeCodeBrain  # noqa: E402

USER = getpass.getuser()
APP = os.environ.get("ALFRED_APP") == "1"  # running headless under Alfred.app
BYE_RE = re.compile(r"^\s*(спасибо|отбой|всё|все|пока|свободен|rahmat|раҳмат|thanks|thank you|that's all|that is all|bye|goodbye|dismissed|bo['ʻ‘’]?ldi|xayr)[\s,.!]*(джарвис|alfred|сэр|sir)?[\s,.!]*$", re.I)
YES_RE = re.compile(r"^\s*(да|ага|подтверждаю|давай|делай|yes|yeah|yep|sure|do it|go ahead|confirm(ed)?|ha|xa|mayli)[\s,.!]*(джарвис|alfred|сэр|sir)?[\s,.!]*$", re.I)
WAKE_PROTO_RE = re.compile(r"(wake up\W.{0,25}\bhome|dadd?y'?s? (is )?home|dad is home|i'?m home|i am home|"
                           r"start (my|the) (day|workstation)|workstation|wake up,? alfred|папочка дома|я дома|dadang uyda)", re.I)
LEARN_RE = re.compile(r"(learn now|go learn|study now|поучись|подучись|займись (само)?обучением|самообучени|иди учись|o['ʻ‘’`]?rgan)", re.I)
LEARNED_RE = re.compile(r"(what (have|did) you learn|чему (ты )?(уже |нового |сегодня |за ночь )?научил|что (ты )?нового (ты )?(умеешь|выучил|узнал)|что ты выучил|nimani o['ʻ‘’`]?rgand)", re.I)
# камера включается только по этим словам и выключается в конце разговора
LOOK_RE = re.compile(r"\b(look at me|watch me|can you see me|do you see me|turn on (the |your )?(camera|eyes)|camera on|open your eyes)\b|((по)?смотри|глянь|взгляни|последи|следи)\s+((на|за)\s+)?(меня|мной|сюда)|включи\s+(камеру|глаза|зрение)|"
                     r"menga\s+qara|qarab\s+tur|kamerani\s+yoq|smotri\s+na\s+menya", re.I)
UNLOOK_RE = re.compile(r"(stop (looking|watching)|don'?t look|(turn|switch) off (the )?camera|не\s+смотри|хватит\s+смотреть|перестань\s+смотреть|отвернись|(выключи|отключи)\s+(камеру|глаза|зрение)|"
                       r"kamerani\s+o['ʻ‘’`]?chir|qarama)", re.I)
CLEAR_RE = re.compile(r"^\s*(clear|close|hide|remove)\s+(the\s+|all\s+|everything|it|that|panels?|hologram|screen)|^\s*(убери|закрой|очисти|спрячь|скрой|выключи)\s+(все\s+|всё\s+)?(панел|экран|это|таблиц|график|картин|фото|видео|всё|все|голограмм)|"
                      r"(gologrammani|panellarni)\s+(yop|olib\s+tashla|o['ʻ‘’`]?chir)", re.I)
STOP_RE = re.compile(r"^\s*(stop|quiet|silence|shut up|enough|hush|молчи|замолчи|помолчи|молчать|тихо|хватит|стоп|заткнись|умолкни|jim|jim bo['ʻ‘’]?l|sus|tinch|o['ʻ‘’]?chir|bas)\b", re.I)


def grant_confirm():
    """Owner said yes: guard.py lets the next risky action through (60 s)."""
    p = HOME / "data" / "confirm.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"t": time.time()}))


def load_config():
    return json.loads((HOME / "config.json").read_text(encoding="utf-8"))


def get_key():
    k = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if k:
        return k
    r = subprocess.run(["security", "find-generic-password", "-s", "alfred-anthropic", "-w"],
                       capture_output=True, text=True)
    if r.returncode == 0 and r.stdout.strip():
        return r.stdout.strip()
    shared = HOME / "data" / "key"
    if shared.exists() and shared.read_text().strip():
        return shared.read_text().strip()
    print("Нет ключа API. Запустите:  bash $ALFRED_HOME/install.sh --key")
    sys.exit(42)


def single_instance():
    """Не даёт запустить двух Alfredов в одном пользователе."""
    lock_path = HOME / "data" / f"lock-{USER}"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fh = open(lock_path, "w")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("Alfred уже работает в этом пользователе.")
        sys.exit(42)
    return fh


_active_cache = {"t": 0.0, "v": True}


def is_active_user():
    """Слушать и говорить, только когда этот пользователь сейчас за экраном и Alfred не на паузе."""
    if menubar.is_paused():
        return False
    now = time.time()
    if now - _active_cache["t"] > 2:
        try:
            _active_cache["v"] = os.stat("/dev/console").st_uid == os.getuid()
        except OSError:
            _active_cache["v"] = True
        _active_cache["t"] = now
    return _active_cache["v"]


def alfred_window(show, cfg):
    """Окно Alfred появляется на «Alfred» и сворачивается после разговора."""
    if not cfg.get("window_follows_voice", True):
        return
    state = "false" if show else "true"
    script = ('tell application "Terminal"\n'
              '  repeat with w in windows\n'
              '    if name of w contains "J.A.R.V.I.S" then\n'
              f'      set miniaturized of w to {state}\n'
              + ('      set index of w to 1\n' if show else '') +
              '    end if\n'
              '  end repeat\n'
              + ('  activate\n' if show else '') +
              'end tell')
    subprocess.Popen(["osascript", "-e", script], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


_RUNTIME = {}


def current_level(state):
    """Громкость для голограммы: свой голос, когда говорит; микрофон, когда слушает."""
    if state == "speaking" and _RUNTIME.get("mouth"):
        return _RUNTIME["mouth"].level()
    if state == "listening" and _RUNTIME.get("ear"):
        return getattr(_RUNTIME["ear"], "level", 0.0)
    return 0.0


def greeting_text(addr):
    h = dt.datetime.now().hour
    part = ("Good morning" if 5 <= h < 12 else "Good afternoon" if 12 <= h < 18
            else "Good evening")
    return _address_mod.with_address(f"{part}. At your service.", "sir" if addr else "none") if not addr else f"{part}, {addr}. At your service."


def _fresh_screen(max_age=60):
    """data/ui/screen.png saved by Alfred.app while the key was held (only if fresh)."""
    p = Path(ui_bridge.ui_dir()) / "screen.png"
    try:
        if p.exists() and time.time() - p.stat().st_mtime < max_age:
            return str(p)
    except OSError:
        pass
    return None


def _selection_line(text, app):
    """Prompt line for text that was selected in the front app when the user pressed the hotkey."""
    t = (text or "").strip() if isinstance(text, str) else ""
    if not t:
        return ""
    return f"\nSelected text in {(app or 'the front app').strip() or 'the front app'}: \"{t[:6000]}\""


def _take_selection(max_age=90):
    v = _RUNTIME.pop("selection", None)
    if v and time.time() - v[2] < max_age:
        return _selection_line(v[0], v[1])
    return ""


def _addr_word(cfg):
    import address as _address
    return _address.word(ui_bridge.get("address", "sir"), ui_bridge.get("name") or cfg.get("user_name", ""))


def _run_step(step, mouth):
    do = step.get("do")
    ctl = _CTL
    if do == "open_app":
        subprocess.run(["open", "-a", step.get("app") or step.get("name") or ""], timeout=15)
    elif do == "open_url":
        url = step.get("url") or ""
        if not url and step.get("query"):
            import urllib.parse
            url = "https://www.google.com/search?q=" + urllib.parse.quote(step["query"])
        if url:
            subprocess.run(["open", url], timeout=15)
    elif do == "window":
        app = step.get("app") or step.get("name") or ""
        f = step.get("frame") or [step.get(k) for k in ("x", "y", "w", "h")]
        if not all(v is not None for v in f):
            W, H, top = 1440, 900, 25
            f = {"left": (0, top, W // 2, H - top), "left_half": (0, top, W // 2, H - top),
                 "right": (W // 2, top, W // 2, H - top), "right_half": (W // 2, top, W // 2, H - top),
                 "left_third": (0, top, W // 3, H - top), "right_third": (2 * W // 3, top, W // 3, H - top),
                 "middle_third": (W // 3, top, W // 3, H - top), "center": (W // 6, top, 2 * W // 3, H - top),
                 "full": (0, top, W, H - top), "fullscreen": (0, top, W, H - top)}.get(
                str(step.get("where", "")).lower().replace(" ", "_"))
        if f and app:
            subprocess.run([ctl, "window", app, *[str(int(v)) for v in f]], timeout=15)
    elif do == "music":
        if step.get("volume") is not None:
            v = max(0, min(100, int(step["volume"])))
            subprocess.run(["osascript", "-e", f'tell application "Music" to set sound volume to {v}'], timeout=10)
        act = step.get("action")
        if act in ("play", "pause", "playpause"):
            subprocess.run(["osascript", "-e", f'tell application "Music" to {act}'], timeout=10)
    elif do == "dnd":
        want = "on" if step.get("on", True) else "off"
        names = subprocess.run(["shortcuts", "list"], capture_output=True, text=True, timeout=10).stdout.splitlines() \
            if shutil.which("shortcuts") else []
        pick = next((n for n in names if n.strip().lower() in (f"alfred dnd {want}", f"dnd {want}")), None) or \
            (next((n for n in names if n.strip().lower() in ("do not disturb", "focus")), None) if want == "on" else None)
        if pick:
            subprocess.run(["shortcuts", "run", pick], timeout=15)
    elif do == "silent":
        silent.set_on(bool(step.get("on", True)))
    elif do == "say":
        mouth.say(step.get("text", ""))


def _persist_voice(cfg, vid):
    """Write the voice choice into config.json (only the voice keys, rest untouched)."""
    keys = ("voice", "tts_engine", "kokoro_voice", "kokoro_lang", "voice_en", "voice_ru", "voice_uz", "fallback_say_voices")
    try:
        p = HOME / "config.json"
        d = json.loads(p.read_text(encoding="utf-8"))
        d.update({k: cfg[k] for k in keys if k in cfg})
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, p)
    except Exception as e:
        print("[voice persist]", str(e)[:120])


def _current_voice(cfg):
    e = cfg.get("tts_engine", "edge")
    if e == "kokoro":
        return cfg.get("kokoro_voice", "bm_george")
    if e == "say" and cfg.get("fallback_say_voices"):
        return cfg["fallback_say_voices"][0]
    return cfg.get("voice_en", "en-GB-RyanNeural")


def _setup_app(cfg, brain, mouth, ear, respond, run_learning, show_learned, last_report, watch_off, text_mode, quick, log, addr):
    """Alfred.app mode: wire data/ui commands to the brain."""
    ui_bridge.start()
    s = ui_bridge.load_settings({"silent": silent.is_on(), "mic_off": menubar.is_paused(),
                                 "holo_mode": menubar.holo_mode(), "camera": menubar.camera_enabled()})
    # file values for mirrored keys win when the app already stored a choice
    raw = ui_bridge._read_json(ui_bridge._p("settings.json"), {})
    if "silent" in raw:
        silent.set_on(bool(raw["silent"]))
    if "holo_mode" in raw:
        menubar.set_holo_mode_value(raw["holo_mode"])
    if "camera" in raw:
        menubar.set_camera(bool(raw["camera"]))
    if "mic_off" in raw and bool(raw["mic_off"]) != menubar.is_paused():
        menubar.set_mic_off(bool(raw["mic_off"]))
    if raw.get("name"):
        cfg["user_name"] = raw["name"]
    if raw.get("voice") in ui_bridge.voice_ids():  # the app's saved choice wins; legacy "Daniel" is ignored
        mouth.set_voice(raw["voice"])
    ui_bridge.load_settings({"silent": silent.is_on(), "mic_off": menubar.is_paused(),
                             "holo_mode": menubar.holo_mode(), "camera": menubar.camera_enabled(),
                             "voice": _current_voice(cfg)})
    ui_bridge.send_settings()
    menubar._emit_state(force=True)

    def respawn_brain():
        if hasattr(brain, "_kill") and not _RUNTIME.get("talking"):
            try:
                brain._kill()
                threading.Thread(target=brain.warm, daemon=True).start()
            except Exception:
                pass

    def h_ptt_down(_):
        if menubar.is_paused():
            ui_bridge.emit("toast", text="Microphone is off")
            return
        _RUNTIME["ptt_held"] = True
        _RUNTIME["ptt_req"] = True
        _RUNTIME.pop("selection", None)  # a new hold = a new selection (arrives with ptt_up)
        try:
            mouth.stop_all()
        except Exception:
            pass
        menubar.set_state("listening")

    def h_ptt_up(c):
        sel = (c.get("selection") or "").strip() if isinstance(c, dict) else ""
        if sel:  # set BEFORE ptt_held flips: the listener thread reads it right after the key is up
            _RUNTIME["selection"] = (sel[:6000], str(c.get("selection_app") or "").strip(), time.time())
        was_held = _RUNTIME.get("ptt_held")
        _RUNTIME["ptt_held"] = False
        if was_held:
            menubar.set_state("thinking")  # pill switches within ~100 ms; an empty recording drops back to idle
        ui_bridge.emit("mood", move="nod")

    busy = {"v": False}
    ask_q = {"next": 0, "serving": 0, "gen": 0}
    ask_cv = threading.Condition()

    def h_ask(c):
        text = (c.get("text") or "").strip()
        if not text:
            return
        screen = c.get("screen") or None
        sel_line = _selection_line(c.get("selection"), c.get("selection_app"))
        # queue (never drop): each ask waits its turn in order; Stop clears the waiting ones
        with ask_cv:
            ticket = ask_q["next"]
            ask_q["next"] += 1
            gen = ask_q["gen"]
            ahead = ticket - ask_q["serving"]
            if ahead > 0:
                ui_bridge.emit("toast", text="Got it — next up" if ahead == 1 else f"Got it — {ahead} ahead")
            while ticket != ask_q["serving"]:
                ask_cv.wait()
            stale = gen != ask_q["gen"]
        busy["v"] = True
        try:
            if stale:
                return
            ui_bridge.emit("partial", text=text)
            speak = silent.is_on()
            try:
                speak = speak or bool(json.loads((HOME / "config.json").read_text(encoding="utf-8")).get("console_speak", False))
            except Exception:
                pass
            fast = None
            try:
                fast = quick.handle(text, mouth.say if speak else (lambda *a, **k: None), _addr_word(cfg)) if cfg.get("fast_commands", True) else None
            except Exception as e:
                print("[ask] quick:", e)
            if fast:
                log.add("quick", text=text, reply=fast)
                reply = fast
            else:
                menubar.set_state("thinking", text)
                reply = brain.ask(text + (f"\nScreen (only when asked about it): {screen}" if screen else "") + sel_line)
            if reply:
                if speak:
                    mouth.say(reply)  # silent mode: shows (and emits) the reply itself
                if not silent.is_on():
                    ui_bridge.emit("reply", text=reply, long=len(reply) > 200 or "\n" in reply)
        except Exception as e:
            traceback.print_exc()
            log.add("error", where="app-ask", error=str(e)[:300])
        finally:
            menubar.set_state("idle")
            busy["v"] = False
            with ask_cv:
                ask_q["serving"] += 1
                ask_cv.notify_all()

    def h_stop(_):
        with ask_cv:
            ask_q["gen"] += 1  # drop asks still waiting in the queue
        _RUNTIME["ptt_held"] = False
        try:
            mouth.stop_all()
            if hasattr(brain, "cancel"):
                brain.cancel()
        except Exception:
            pass
        if not _RUNTIME.get("talking"):
            menubar.set_state("idle")

    def h_set(c):
        k, v = c.get("key"), c.get("value")
        if k not in ui_bridge.DEFAULTS:
            return
        ui_bridge.set_setting(k, v, save=False, announce=False)
        if k == "silent":
            silent.set_on(bool(v))
        elif k == "mic_off":
            menubar.set_mic_off(bool(v))
        elif k == "holo_mode":
            menubar.set_holo_mode_value(v)
        elif k == "camera":
            menubar.set_camera(bool(v))
            if not v:
                try:
                    watch_off()
                except Exception:
                    pass
        elif k in ("humor", "honesty", "length"):
            pass  # live: brain_cc injects the new dials into the next turn, no respawn
        elif k in ("address", "name", "concise", "playful", "joke_a_day"):
            if k == "name":
                cfg["user_name"] = v
            if k == "address":
                cfg["address"] = _addr_word(cfg)
            respawn_brain()
        elif k == "brain":
            try:  # takes effect after "Restart my brain"
                p = HOME / "config.json"
                d = json.loads(p.read_text(encoding="utf-8"))
                d["brain"] = str(v)
                tmp = p.with_suffix(".json.tmp")
                tmp.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                os.replace(tmp, p)
            except Exception as e:
                print("[brain persist]", str(e)[:120])
        elif k == "voice":
            if not c.get("_auto"):
                ui_bridge.set_setting("voice_follows_address", False, save=False, announce=False)  # user picked a voice: stop following the address
            _apply_voice_live(v)
        if k == "address" and ui_bridge.get("voice_follows_address") is not False and _address_mod.default_voice(v):
            nv = _address_mod.default_voice(v)
            ui_bridge.set_setting("voice", nv, save=False, announce=False)
            _apply_voice_live(nv)
        if k in ("humor", "honesty", "length", "address", "name", "concise", "playful", "joke_a_day", "voice", "stay_awake", "voice_follows_address", "brain"):
            try:
                ui_bridge._write_json(ui_bridge._p("settings.json"), ui_bridge.settings())
            except OSError:
                pass
        ui_bridge.send_settings()

    def _apply_voice_live(v):
        v = str(v or "")
        if v == "Daniel" or not v:  # legacy placeholder from the old picker: keep the current voice
            return
        mouth.set_voice(v)
        _persist_voice(cfg, v)

    def h_voice_preview(c):
        v = str(c.get("voice") or ui_bridge.get("voice") or "")
        if not v or silent.is_on():
            return
        def run():
            try:
                mouth.preview_voice(v)
            except Exception as e:
                ui_bridge.emit("toast", text="Voice preview failed")
                print("[voice_preview]", str(e)[:120])
        threading.Thread(target=run, daemon=True).start()

    def h_learn_now(_):
        menubar.STATE["learn_now"] = True

    def h_show_learned(_):
        if not show_learned(last_report()):
            ui_bridge.emit("toast", text="Nothing learned yet")

    def h_routine(c):
        name = str(c.get("name", "")).lower().replace("-", "_").replace(" ", "_")
        r = next((x for x in ui_bridge.load_routines()
                  if name in (str(x.get("id", "")).lower(), str(x.get("name", "")).lower().replace(" ", "_"))), None)
        if not r:
            ui_bridge.emit("toast", text=f"No routine “{c.get('name')}”")
            return
        ui_bridge.emit("toast", text=f"{r.get('name', name).title()} mode")
        for st in r.get("steps", []):
            try:
                ui_bridge.emit("step", text=str(st.get("do", "")).replace("_", " ").title(), done=False)
                _run_step(st, mouth)
                ui_bridge.emit("step", text=str(st.get("do", "")).replace("_", " ").title(), done=True)
            except Exception as e:
                print("[routine]", st, e)
        ui_bridge.emit("mood", move="glint")

    def h_forget(c):
        ui_bridge.forget_memory(c.get("id"))

    def h_holo_show(_):
        menubar.holo(True)

        def off():
            time.sleep(12)
            if not _RUNTIME.get("talking"):
                menubar.holo(False)
        threading.Thread(target=off, daemon=True).start()

    def h_restart(_):
        ui_bridge.emit("toast", text="Restarting…")
        try:
            getattr(brain, "session_flush", lambda *a, **k: None)("restart", wait=14)
        except Exception:
            pass
        time.sleep(0.3)
        os._exit(1)

    def h_point_done(_):
        if time.time() - getattr(brain, "last_point", 0) < 300 and not busy["v"]:
            h_ask({"text": "[system] He clicked the highlighted step. Point at the next step now; if there is none, just say Done in two words."})

    def _on_spoken_address(new, voice):
        h_set({"key": "address", "value": new, "_auto": True})
        if voice:
            h_set({"key": "voice", "value": voice, "_auto": True})
    _address_mod.on_change = _on_spoken_address

    for name, fn in (("ptt_down", h_ptt_down), ("ptt_up", h_ptt_up), ("ask", h_ask), ("stop", h_stop), ("set", h_set),
                     ("learn_now", h_learn_now), ("show_learned", h_show_learned), ("routine", h_routine),
                     ("memory_forget", h_forget), ("holo_show", h_holo_show), ("restart", h_restart), ("voice_preview", h_voice_preview),
                     ("point_done", h_point_done)):
        ui_bridge.on(name, fn)

    def class_loop():
        st = {"auto": False, "prev": False}
        while True:
            try:
                q = ui_bridge.class_quiet_now()
                if q and not st["auto"]:
                    st.update(auto=True, prev=silent.is_on())
                    silent.set_on(True)
                    menubar._emit_state(force=True)
                elif not q and st["auto"]:
                    st["auto"] = False
                    if not st["prev"]:
                        silent.set_on(False)
                    w = _addr_word(cfg)
                    mouth.say("Lecture's over" + (f", {w}." if w else "."))
            except Exception as e:
                print("[class]", e)
            time.sleep(20)
    threading.Thread(target=class_loop, daemon=True).start()


def main():
    text_mode = "--text" in sys.argv
    cfg = load_config()
    import brains
    brain_id = brains.canonical(cfg.get("brain"))
    use_sub = brain_id == "claude-subscription"
    use_plugin = brain_id not in ("claude-subscription", "claude-api")
    key = get_key() if brain_id == "claude-api" else None
    _lock = single_instance()  # noqa: F841
    memory, log, state, skills = Memory(HOME), Log(HOME), State(HOME), Skills(HOME)
    try:
        panels.clear()  # never show leftover panels from a previous run
    except Exception:
        pass
    addr = _addr_word(cfg)

    cfg["_debug_wav"] = str(HOME / "data" / f"last-{USER}.wav")
    ear = None
    if not text_mode:
        print("Включаю слух…")
        ear = voice.Ear(cfg, active_fn=is_active_user)

        def _mic_switch():
            """Mic off in the menu bar / Alfred.app really closes the microphone (no orange dot)."""
            on = True
            while True:
                want = not menubar.is_paused()
                if want != on:
                    try:
                        if want:
                            ear.flush()
                            ear.stream.start()
                        else:
                            ear.stream.stop()
                        on = want
                        print("Микрофон:", "ON" if on else "OFF")
                    except Exception as e:
                        print("[mic switch]", e)
                time.sleep(0.3)
        threading.Thread(target=_mic_switch, daemon=True).start()
    mouth = voice.Mouth(cfg, ear, cache_dir=str(HOME / "data" / "acks"),
                        active_fn=None if text_mode else is_active_user)
    # Warm the ears and the voice NOW, so the first command is as fast as the tenth (a cold load can take 20+ s)
    _t0 = time.time()
    try:
        import numpy as _np
        if ear is not None:
            ear.stt.transcribe(_np.zeros(16000, dtype=_np.int16))
        os.remove(mouth._synth("Systems warming up."))
        threading.Thread(target=lambda: os.remove(mouth._synth("Системы готовы.")), daemon=True).start()  # warm the Russian voice
    except Exception as _e:
        print("[warm-up]", _e)
    print(f"Warm-up done in {time.time() - _t0:.1f} s")
    if not text_mode:
        def _summon():
            if _RUNTIME.get("ptt_req"):  # push-to-talk from Alfred.app: no wake word
                _RUNTIME["ptt_req"] = False
                _RUNTIME["ptt_mode"] = True
                return True
            return menubar.take_summon()
        ear.abort_fn = lambda: _RUNTIME.get("ptt_req")
        mouth.on_speak = menubar.speaking
        mouth.on_tts = lambda sec, ok, n: (log.add("tts", sec=sec, ok=ok, chars=n) if (sec > 3 or not ok) else None)
        ear.summon_fn = _summon
        _RUNTIME["mouth"], _RUNTIME["ear"] = mouth, ear

    def confirm(summary):
        question = f"{addr.capitalize()}, {summary}. Shall I proceed?"
        print("Alfred:", question)
        if text_mode:
            return voice.is_yes(input("Вы (да/нет): "))
        mouth.say(question)
        answer = ear.listen_text(start_timeout=7)
        print("Вы:", answer)
        return voice.is_yes(answer)

    if use_sub:
        brain = ClaudeCodeBrain(cfg, HOME, memory, log, state)
        if not text_mode:
            def progress(t):
                print("Alfred:", t)
                mouth.stream(t)  # звучит сразу, по предложениям, пока мозг дописывает ответ
            brain.on_progress = progress
        threading.Thread(target=brain.warm, daemon=True).start()
        print("Мозг: подписка Claude (Claude Code)")
    elif use_plugin:
        brain = brains.Adapter(brains.make_plugin(cfg, HOME), cfg)
        _ok, _why = brain._b.check()
        print(f"Brain: {brain.info.label} ({brain.info.status}; computer control: {brain.info.computer_control})", "" if _ok else "- NOT READY: " + _why)
        threading.Thread(target=brain.warm, daemon=True).start()
    else:
        hands = Hands(cfg, mouth, memory, skills, log, confirm)
        brain = Brain(cfg, key, hands, memory, skills, log, state)
        hands.brain = brain
        print("Мозг: Claude API")

    def respond(text, barge=True, screen=None):
        print("Вы:", text)
        sel_line = _take_selection()
        if APP:
            ui_bridge.emit("partial", text=text)
        menubar.set_state("thinking", text)
        thinking = threading.Timer(2.5, lambda: voice.chime("Pop"))
        thinking.daemon = True
        result = {}

        def work():
            try:
                ctx = vision_context()
                q = f"{ctx} {text}" if ctx else text
                if screen:
                    q += f"\nScreen (only when asked about it): {screen}"
                q += sel_line
                result["reply"] = brain.ask(q)
            except Exception as e:
                traceback.print_exc()
                log.add("error", where="ask", error=str(e)[:500])
                result["reply"] = f"{addr.capitalize()}, I hit an internal error. Details are in the log."

        t0 = time.time()
        worker = threading.Thread(target=work, daemon=True)
        worker.start()
        if text_mode or not barge or ear is None or ear.oww is None:
            worker.join()
            while mouth.stream_busy():
                time.sleep(0.05)
        else:
            thinking.start()
            ear.flush()
            ear.oww.reset()
            thr = float(cfg.get("barge_in_threshold", 0.6))
            said_wait = False
            # слушаем «Alfred», пока мозг думает И пока звучит потоковый ответ — можно перебить в любой момент
            while worker.is_alive() or mouth.stream_busy():
                if _RUNTIME.get("ptt_req"):  # new push-to-talk cancels the current turn
                    thinking.cancel()
                    mouth.stream_stop()
                    if worker.is_alive():
                        brain.cancel()
                        worker.join(10)
                    return True
                if mouth.last_play_start > t0:
                    thinking.cancel()  # уже говорим — «думающий» звук не нужен
                try:
                    f = ear._read(timeout=0.2)
                except queue.Empty:
                    continue
                scores = ear.oww.predict(f)
                if scores and max(scores.values()) >= thr:
                    thinking.cancel()
                    mouth.stream_stop()
                    ear.oww.reset()
                    if worker.is_alive():
                        brain.cancel()
                        worker.join(10)
                        print("(задача отменена)")
                        mouth.say(f"Cancelled, {addr}.")
                    return True
                quiet_for = time.time() - max(t0, mouth.last_play_start)
                if not said_wait and worker.is_alive() and quiet_for > 25:
                    said_wait = True
                    mouth.stream(f"One moment, {addr}, still working on it.")
            ear.flush()
        thinking.cancel()
        reply = result.get("reply", "")
        said = reply or " ".join(getattr(brain, "stream_spoken", []) or [])
        _RUNTIME["asked"] = said.strip().endswith("?")
        first = mouth.last_play_start - t0 if mouth.last_play_start > t0 else None
        log.add("timing", stt=((getattr(ear, "last_info", None) or {}).get("stt") if ear else None),
                early=((getattr(ear, "last_info", None) or {}).get("early") if ear else None),
                first_voice=round(first, 2) if first else None, brain=round(time.time() - t0, 2))
        if reply:
            print("Alfred:", reply)
            rows = [l for l in reply.splitlines() if l.count("|") >= 2 or re.match(r"^\s*([-*•]|\d+\.)\s", l)]
            if len(rows) >= 3 and not silent.is_on():  # tables and long lists go on screen, not into the voice
                try:
                    trs = [[c.strip() for c in l.strip().strip("|").split("|")] for l in rows
                           if l.count("|") >= 2 and not re.match(r"^\s*\|?[-:| ]+\|?\s*$", l)]
                    if len(trs) >= 2:
                        panels.push({"type": "table", "title": "Details", "columns": trs[0], "rows": trs[1:]})
                    else:
                        panels.push({"type": "list", "title": "Details", "items": [re.sub(r"^\s*([-*•]|\d+\.)\s*", "", l) for l in rows]})
                except Exception:
                    pass
                spoken = " ".join(l for l in reply.splitlines() if l.strip() and l not in rows and not re.match(r"^\s*\|?[-:| ]+\|?\s*$", l))
                reply = (spoken + " " if spoken else "") + f"Details on screen, {addr}."
        if APP and not silent.is_on():
            full = " ".join(x for x in (said, "") if x).strip()
            if full:
                ui_bridge.emit("reply", text=full, long=len(full) > 200 or len(rows) >= 3 if reply else False)
                if getattr(brain, "_tool_ran", False):
                    ui_bridge.emit("mood", move="glint")
        menubar.set_state("speaking")
        return mouth.say(reply, barge=barge and not text_mode)

    # ---------- самообучение ----------
    growth_path = HOME / "data" / "growth.md"
    _RUNTIME["last_talk"] = time.time()

    def record_growth(items):
        months = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября",
                  "октября", "ноября", "декабря"]
        d = dt.date.today()
        lines = [f"\n## {d.day} {months[d.month - 1]} {d.year}"]
        for it in items:
            mark = "✓" if it.get("tested") else "·"
            line = f"- {mark} **{it.get('title', '').strip()}** — {it.get('detail', '').strip()}"
            if it.get("skill"):
                line += f" (навык `{it['skill']}`)"
            if it.get("try"):
                line += f" Попросите: {it['try']}"
            lines.append(line)
        head = "" if growth_path.exists() else "# Чему научился Alfred\n\nКаждое обучение — новые проверенные навыки. Новые сверху вниз по датам.\n"
        with growth_path.open("a", encoding="utf-8") as f:
            f.write(head + "\n".join(lines) + "\n")
        try:
            os.chmod(growth_path, 0o666)
        except Exception:
            pass

    def last_report():
        try:
            p = state.get("learn_news")
            return json.loads(Path(p).read_text(encoding="utf-8")) if p else None
        except Exception:
            return None

    def show_learned(rep):
        items = (rep or {}).get("items") or []
        if not items:
            return False
        panels.push({"type": "list", "title": "Чему я научился",
                     "items": [("✓ " if it.get("tested") else "") + it.get("title", "") for it in items]})
        tips = [it.get("try") for it in items if it.get("try")]
        if tips:
            panels.push({"type": "text", "title": "Попробуйте сказать", "text": "\n".join(f"- {t}" for t in tips)})
        return True

    def announce_learning(in_conversation=False, force=False):
        """Докладывает о новых умениях: голосом и списком на голограмме."""
        news = state.get("learn_news")
        if not news or (not force and state.get(f"learn_heard_{USER}") == news):
            return False
        rep = last_report()
        if not rep or not rep.get("items"):
            return False
        state.set(f"learn_heard_{USER}", news)
        if not in_conversation:
            menubar.holo(True)
        try:
            show_learned(rep)
            n = len(rep["items"])
            mouth.say(rep.get("summary") or f"{addr.capitalize()}, я освоил новых умений: {n}. Список на экране.")
            if not in_conversation:
                time.sleep(6)  # дать прочитать список
        finally:
            if not in_conversation:
                panels.clear()
                menubar.holo(False)
        return True

    def run_learning(announce=False):
        if _RUNTIME.get("learning") or not hasattr(brain, "learn"):
            return
        _RUNTIME["learning"] = menubar.STATE["learning"] = True
        try:
            print("[обучение] начинаю разбор журнала…")
            if APP:
                ui_bridge.emit("toast", text="Learning…")
            rep = brain.learn()
            state.set("learn_ts", time.time())
            items = rep.get("items") or []
            print("[обучение]", rep.get("summary") or rep.get("note") or rep.get("error") or "без изменений",
                  f"(умений: {len(items)})")
            if items:
                record_growth(items)
                state.set("learn_news", rep.get("report"))
            if announce:
                while _RUNTIME.get("talking"):
                    time.sleep(2)
                if not announce_learning(force=True):
                    msg = (f"{addr.capitalize()}, обучение не удалось, попробую позже."
                           if rep.get("error") else f"{addr.capitalize()}, я всё разобрал: новых ошибок не нашёл, учиться пока нечему.")
                    mouth.say(msg)
        finally:
            _RUNTIME["learning"] = menubar.STATE["learning"] = False

    def learning_loop():
        """Ночью (или после долгой тишины) Alfred сам учится; «Учиться сейчас» в меню — сразу."""
        time.sleep(90)
        while True:
            try:
                manual = menubar.STATE.pop("learn_now", False)
                now = dt.datetime.now()
                due = time.time() - float(state.get("learn_ts", 0) or 0) > 20 * 3600
                idle = time.time() - _RUNTIME.get("last_talk", time.time())
                if manual:
                    threading.Thread(target=mouth.say, args=(f"Начинаю обучение, {addr}. Доложу, когда закончу.",), daemon=True).start()
                if manual or (due and is_active_user() and not _RUNTIME.get("talking")
                              and (1 <= now.hour < 6 or idle > 40 * 60)):
                    run_learning(announce=manual)
            except Exception as e:
                print("[обучение] ошибка:", e)
            time.sleep(15)

    def welcome():
        """Приветствие при входе и после пробуждения Mac; утром — сводка дня и доклад о новых умениях."""
        now = dt.datetime.now()
        day_key = f"briefing_day_{USER}"
        menubar.holo(True)
        try:
            if cfg.get("morning_briefing", True) and 5 <= now.hour < 12 and state.get(day_key) != dt.date.today().isoformat():
                state.set(day_key, dt.date.today().isoformat())
                respond("[system] The user just turned on the Mac. Greet them briefly and give a morning briefing: "
                        "weather and today's events.", barge=False)
            else:
                mouth.say(greeting_text(addr))
            if announce_learning(in_conversation=True):
                time.sleep(6)
        finally:
            panels.clear()
            menubar.holo(False)

    # ---------- зрение: камера, жесты, мимика
    EXPR_RU = {"smile": "is smiling", "frown": "is frowning", "sad": "looks sad", "surprise": "looks surprised"}
    vis = {"yawns": [], "yawn_said": 0.0, "greeted": 0.0, "err_said": False}

    def vision_context():
        e = _RUNTIME.get("eyes")
        if not e or not e.fresh() or not e.state.get("present"):
            return ""
        bits = []
        ex = EXPR_RU.get(e.state.get("expr"))
        if ex:
            bits.append(f"the user {ex}")
        if len([y for y in vis["yawns"] if time.time() - y < 600]) >= 2:
            bits.append("is yawning, probably tired")
        return f"[camera: {', '.join(bits)}]" if bits else ""

    def greet_back(away):
        menubar.holo(True)
        try:
            mins = away // 60
            line = random.choice([f"Welcome back, {addr}.", f"Good to see you, {addr}.",
                                  f"Welcome back, {addr}. You were away {mins} minutes." if mins < 120 else f"Welcome back, {addr}."])
            mouth.say(line)
            if announce_learning(in_conversation=True):
                time.sleep(5)
            time.sleep(1.5)
        finally:
            panels.clear()
            if not _RUNTIME.get("talking"):
                menubar.holo(False)

    def on_vision(ev):
        k = ev.get("ev")
        talking = _RUNTIME.get("talking")
        if k == "hand":  # Stark-style: grab / rotate / zoom / swipe the hologram with your hand
            ev["_n"] = _RUNTIME["hand_n"] = _RUNTIME.get("hand_n", 0) + 1
            menubar.STATE["hand"] = ev
            _RUNTIME["watch_active"] = time.time()
            return
        if k == "gesture":
            g = ev.get("name")
            print("[жест]", g)
            log.add("gesture", name=g, talking=bool(talking))
            _RUNTIME["watch_active"] = time.time()
            if g == "Open_Palm" and (talking or mouth.is_speaking()):
                _RUNTIME["gesture_stop"] = True          # ✋ — замолчать
                mouth.stop_all()
                ear.inject("стоп")
            elif g == "Thumb_Up" and talking and menubar.STATE.get("status") == "listening":
                ear.inject("да")                         # 👍 — да
            elif g == "Thumb_Down" and talking and menubar.STATE.get("status") == "listening":
                ear.inject("нет")                        # 👎 — нет
            elif g == "Closed_Fist":
                panels.clear()                           # ✊ — убрать панели
            elif g == "ILoveYou" and not talking and not mouth.is_speaking():
                threading.Thread(target=mouth.say, args=(random.choice([
                    f"Взаимно, {addr}.", f"Ценю, {addr}. Но обниматься не умею.", f"И я рад служить вам, {addr}."]),),
                    daemon=True).start()
        elif k in ("nod", "shake"):
            log.add("gesture", name=k, talking=bool(talking))
            if talking and _RUNTIME.get("asked") and menubar.STATE.get("status") == "listening":
                print("[голова]", "кивок → да" if k == "nod" else "покачал → нет")
                ear.inject("да" if k == "nod" else "нет")
        elif k == "arrive":
            log.add("presence", what="arrive", away=int(ev.get("away") or 0))
            _RUNTIME["left_at"] = None
            _RUNTIME["watch_active"] = time.time()
        elif k == "leave":
            log.add("presence", what="leave")
            _RUNTIME["left_at"] = time.time()
        elif k == "yawn":
            now = time.time()
            vis["yawns"] = [y for y in vis["yawns"] if now - y < 900] + [now]
            if (len(vis["yawns"]) >= 3 and not talking and not mouth.is_speaking()
                    and now - vis["yawn_said"] > 5400 and cfg.get("camera_care", True)):
                vis["yawn_said"] = now
                h = dt.datetime.now().hour
                line = (f"{addr.capitalize()}, вы зеваете уже который раз. Уже поздно — может, на сегодня хватит?"
                        if h >= 22 or h < 5 else
                        f"{addr.capitalize()}, вы зеваете. Может, сделать перерыв и выпить воды?")
                threading.Thread(target=mouth.say, args=(line,), daemon=True).start()
        elif k == "error":
            msg = ev.get("msg", "")
            print("[зрение]", msg)
            if msg == "camera" and not vis["err_said"]:
                vis["err_said"] = True
                why = ""
                try:
                    cc = json.loads((HOME / "data" / "camera_check.json").read_text())
                    why = f"status={cc.get('status_after_ask') or cc.get('status')} devices={cc.get('devices')}"
                except Exception:
                    pass
                log.add("error", where="camera", error=("no camera access " + why).strip())
                if "denied" in why or "restricted" in why:
                    threading.Thread(target=mouth.say, args=(f"{addr.capitalize()}, macOS is blocking my camera. In Privacy and Security, Camera, switch Terminal off and on, then restart me.",), daemon=True).start()
                elif "devices=[]" in why:
                    threading.Thread(target=mouth.say, args=(f"I can't find a camera at all, {addr}.",), daemon=True).start()
        elif k == "camera":
            print("[зрение] камера включена — вижу вас")

    def watching():
        e = _RUNTIME.get("eyes")
        return bool(e and e.enabled)

    def watch_on():
        """«Посмотри на меня» — включить камеру на время разговора."""
        import eyes as eyes_mod
        if watching():
            return True
        if not menubar.camera_enabled():
            return False
        py = sys.executable
        import importlib.util as _iu
        if not (_iu.find_spec("mediapipe") and _iu.find_spec("cv2")):  # instant check instead of starting a second Python
            mouth.stream(f"One moment, {addr}, installing my eyes.")
            subprocess.run([str(HOME / "bin" / "uv"), "pip", "install", "--python", py, "-q", "mediapipe==1.2.2"], timeout=1200)
        e = _RUNTIME.get("eyes") or eyes_mod.EyesClient(cfg, on_vision)
        _RUNTIME["eyes"] = e
        e.enabled, e.paused = True, False
        e.start()
        menubar.set_look(e.look)
        _RUNTIME["watch_active"], _RUNTIME["left_at"] = time.time(), None
        log.add("camera", on=True)
        return True

    def watch_off():
        """Камеру выключить полностью — без просьбы сэра она не открывается."""
        e = _RUNTIME.get("eyes")
        if e and e.enabled:
            e.stop()
            menubar.set_look(None)
            log.add("camera", on=False)
            print("[зрение] камера выключена")

    def watch_sleep():
        """Замечает пробуждение Mac из сна и приветствует."""
        last_wall, last_mono = time.time(), time.monotonic()
        while True:
            time.sleep(5)
            wall, mono = time.time(), time.monotonic()
            slept = (wall - last_wall) - (mono - last_mono)
            last_wall, last_mono = wall, mono
            if slept > 120:
                time.sleep(3)
                if is_active_user():
                    try:
                        welcome()
                    except Exception as e:
                        print("[приветствие] ошибка:", e)

    if hasattr(brain, "learn") and not text_mode:
        threading.Thread(target=learning_loop, daemon=True).start()
    else:
        def reflection():
            """API-режим: раз в день обновляет уроки."""
            while True:
                try:
                    today = dt.date.today().isoformat()
                    if state.get("reflect_day") != today and dt.datetime.now().hour >= 3:
                        state.set("reflect_day", today)
                        print("[самоанализ]", brain.reflect())
                except Exception as e:
                    print("[самоанализ] ошибка:", e)
                time.sleep(1800)

        threading.Thread(target=reflection, daemon=True).start()

    if text_mode:
        mouth.say(greeting_text(addr))
        print("Текстовый режим. Пишите команды, «выход» — завершить.")
        while True:
            try:
                t = input("\nВы: ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if t.lower() in ("выход", "exit", "quit"):
                break
            if t:
                respond(t)
        sys.exit(42)

    log.add("start", user=USER, stt=getattr(ear.stt, "backend", "?"), wake="oww" if ear.oww is not None else "stt")
    # mic off must not block start-up: typed Console questions still need the loops below
    while not menubar.is_paused() and not is_active_user():
        time.sleep(2)
    if not menubar.is_paused():
        menubar.set_state("speaking")
        welcome()
        menubar.set_state("idle")
    if cfg.get("hide_terminal", True):
        alfred_window(False, {"window_follows_voice": True})  # прячем Терминал — вместо него голограмма
    alfred_window(False, cfg)
    threading.Thread(target=watch_sleep, daemon=True).start()

    def prefetch_holo():
        """Заранее скачать модели голограмм и нейросеть глубины — чтобы голограммы появлялись мгновенно."""
        key = f"holo_prefetch_{USER}"
        if state.get(key) == dt.date.today().isoformat():
            return
        try:
            subprocess.run([sys.executable, str(HOME / "jholo.py"), "prefetch"], timeout=1800, capture_output=True)
            state.set(key, dt.date.today().isoformat())
        except Exception as e:
            print("[голограммы] предзагрузка:", e)
    threading.Thread(target=prefetch_holo, daemon=True).start()

    def holo_server():
        """Warm hologram builder: jholo.py hands its work here, so photos become 3D in ~1-3 s, not 10-50 s."""
        try:
            import jholo
            jholo.serve()
        except Exception as e:
            print("[голограммы] сервер:", e)
    threading.Thread(target=holo_server, daemon=True).start()
    if cfg.get("phone_bridge", False):  # iPhone app bridge (phone_bridge.py), off by default
        try:
            import phone_bridge
            phone_bridge.start(cfg, brain=brain, mouth=mouth, ear=ear, log=log, home=HOME)
        except Exception as e:
            print("[phone bridge]", e)

    # ---------- Alfred Console (console.py): status file out, typed commands in ----------
    def console_loop():
        inbox, status = HOME / "data" / "console_inbox.jsonl", HOME / "data" / "console_status.json"
        done_at = inbox.stat().st_size if inbox.exists() else 0  # ignore anything typed while Alfred was off
        busy = False
        while True:
            time.sleep(1)
            try:
                st = dict(menubar.STATE)
                status.write_text(json.dumps({"ts": time.time(), "status": st.get("status", "idle"), "last": st.get("last", "")}), encoding="utf-8")
                if busy or not inbox.exists() or inbox.stat().st_size <= done_at:
                    continue
                if _RUNTIME.get("talking") or st.get("status") not in ("idle", "paused", "starting"):
                    continue  # wait until the voice turn is over: one brain, one thing at a time
                with inbox.open("rb") as f:
                    f.seek(done_at)
                    chunk = f.read()
                done_at += len(chunk)
                texts = [json.loads(l).get("text", "") for l in chunk.decode("utf-8", "ignore").splitlines() if l.strip()]
                busy = True

                def run_typed(texts=texts):
                    nonlocal busy
                    try:
                        try:
                            speak = bool(json.loads((HOME / "config.json").read_text(encoding="utf-8")).get("console_speak", False))
                        except Exception:
                            speak = False
                        speak = speak or silent.is_on()
                        for text in texts:
                            if not text.strip():
                                continue
                            say = mouth.say if speak else (lambda *a, **k: None)
                            fast = None
                            try:
                                fast = quick.handle(text, say, _addr_word(cfg)) if cfg.get("fast_commands", True) else None
                            except Exception as e:
                                print("[console] quick:", e)
                            if fast:
                                log.add("quick", text=text, reply=fast)
                                if speak:
                                    mouth.say(fast)
                                continue
                            menubar.set_state("thinking", text)
                            reply = brain.ask(text)  # brain logs request + reply itself
                            if speak and reply:
                                mouth.say(reply)
                    except Exception as e:
                        traceback.print_exc()
                        log.add("error", where="console", error=str(e)[:300])
                    finally:
                        menubar.set_state("idle")
                        busy = False
                threading.Thread(target=run_typed, daemon=True).start()
            except Exception as e:
                print("[console]", e)
    threading.Thread(target=console_loop, daemon=True).start()

    def vault_loop():  # OPTIONAL (config "obsidian_vault": true): keep a readable copy of memory, lessons and the daily log in ~/Documents/Alfred Brain
        while True:
            if not cfg.get("obsidian_vault", False):
                time.sleep(3600)
                continue
            try:
                import vault
                vault.sync()
            except Exception as e:
                print("[vault]", e)
            try:  # once a day after 21:00: learn from the day (Haiku, ~1 small call)
                gf = HOME / "data" / "vault_grow.json"
                today = time.strftime("%Y-%m-%d")
                last = json.loads(gf.read_text()).get("day") if gf.exists() else None
                if time.localtime().tm_hour >= 21 and last != today:
                    import vault_grow
                    print("[memory]", vault_grow.grow())
                    gf.write_text(json.dumps({"day": today}))
            except Exception as e:
                print("[memory grow]", e)
            time.sleep(300)
    threading.Thread(target=vault_loop, daemon=True).start()

    # ---------- spoken timers: bin/alfred-timer writes notes, Alfred speaks them when due (works from the sandbox) ----------
    def timer_loop():
        tf = HOME / "data" / "timers.jsonl"
        while True:
            time.sleep(1)
            try:
                if not tf.exists() or tf.stat().st_size == 0:
                    continue
                now, keep, due = time.time(), [], []
                for line in tf.read_text(encoding="utf-8").splitlines():
                    try:
                        t = json.loads(line)
                    except ValueError:
                        continue
                    (due if t.get("at", 0) <= now else keep).append(t)
                if due:
                    tf.write_text("".join(json.dumps(t, ensure_ascii=False) + "\n" for t in keep), encoding="utf-8")
                    for t in due:
                        log.add("timer", text=t.get("text", ""))
                        voice.chime("Glass")
                        mouth.say(t.get("text", ""))
            except Exception as e:
                print("[timer]", e)
    threading.Thread(target=timer_loop, daemon=True).start()

    if APP:  # proactive nudges (calendar, deadlines, morning brief); never speaks in silent mode
        try:
            import nudges
            nudges.start(ui_bridge.emit, mouth.say, ui_bridge.settings)
        except Exception as e:
            print("[nudges]", e)
        _tgb = None
        # Telegram bridge: only runs once the user has set a bot token (Set Telegram bot.command)
        if (HOME / "data" / "telegram_bot_token").exists():
            try:
                import telegram_bridge
                def _tg_ask(t, source="telegram"):
                    # Telegram: never speak out loud (the user may be asleep or away); always return the full answer text
                    prev = brain.on_progress
                    brain.on_progress = None
                    try:
                        r = brain.ask(t)
                    finally:
                        brain.on_progress = prev
                    return r or getattr(brain, "last_final", "") or ""
                _tgb = telegram_bridge.start(_tg_ask, ui_bridge.emit,
                                             lambda: {"silent": silent.is_on(), "mic_off": menubar.is_paused()})
            except Exception as e:
                print("[telegram]", e)

        # Stay awake: caffeinate while the switch is on or an away task runs (no password)
        try:
            import awake
            awake.start(lambda: ui_bridge.get("stay_awake", False),
                        lambda: bool(_tgb is not None and getattr(_tgb, "away", None) and _tgb.away.current))
        except Exception as e:
            print("[awake]", e)

        # Scheduler: due jobs run through the brain, muted (like _tg_ask); result goes to Telegram and/or the pill
        try:
            import scheduler
            def _sched_ask(t):
                prev = brain.on_progress
                brain.on_progress = None
                try:
                    r = brain.ask(t)
                finally:
                    brain.on_progress = prev
                return r or getattr(brain, "last_final", "") or ""
            def _sched_deliver(job, text):
                d = job.get("deliver", "telegram")
                if d in ("telegram", "both") and _tgb is not None:
                    _tgb.send("Scheduled: " + text)
                if d in ("pill", "both") or _tgb is None:
                    ui_bridge.emit("reply", text="Scheduled: " + text, long=True)
            scheduler.start(_sched_ask, _sched_deliver)
        except Exception as e:
            print("[scheduler]", e)

    # ---------- Claude chat watcher: "Your chat X has finished." ----------
    claude_news = []

    def on_claude(ev):
        claude_news.append(ev)

    def claude_announcer():
        while True:
            time.sleep(2)
            if not claude_news or _RUNTIME.get("talking") or time.time() - _RUNTIME.get("last_talk", 0) < 4:
                continue
            time.sleep(3)  # let near-simultaneous events batch up
            evs, claude_news[:] = list(claude_news), []
            done = [e["title"] for e in evs if e["kind"] == "done"]
            wait = [e["title"] for e in evs if e["kind"] == "waiting"]
            lines = []
            if len(done) == 1:
                lines.append(f"{addr.capitalize()}, your Claude chat {done[0]} has finished.")
            elif done:
                lines.append(f"{addr.capitalize()}, {len(done)} Claude chats have finished: {', '.join(done[:3])}.")
            if wait:
                lines.append(f"{wait[0]} seems to be waiting for you." if len(wait) == 1 else f"{len(wait)} chats are waiting for you.")
            text = " ".join(lines)
            log.add("claude_watch", text=text)
            print("Alfred (Claude):", text)
            try:
                subprocess.Popen(["osascript", "-e", f'display notification "{text[:180]}" with title "Alfred"'])
            except Exception:
                pass
            try:
                import protocol as _pq
                quiet = _pq.is_quiet()
            except Exception:
                quiet = False
            if not quiet:
                menubar.set_state("speaking", "Claude")
                mouth.say(text)
                menubar.set_state("idle")

    if cfg.get("claude_watch", True):
        try:
            import claude_watch
            claude_watch.Watcher(on_claude, min_work=float(cfg.get("claude_watch_min_seconds", 45))).start()
            threading.Thread(target=claude_announcer, daemon=True).start()
        except Exception as e:
            print("[claude watch]", e)
    if APP:
        _setup_app(cfg, brain, mouth, ear, respond, run_learning, show_learned, last_report, watch_off, text_mode, quick, log, addr)
    print("\nСкажите «Alfred» («Эй, Alfred»), затем команду. «Молчи» — замолчать. Ctrl+C — выключить.\n")

    while True:
        try:
            menubar.set_state("idle")
            pending = ear.wait_for_wake()
            ptt = _RUNTIME.pop("ptt_mode", False)
            log.add("wake", user=USER, how=getattr(ear, "last_wake", "?"), text=getattr(ear, "last_wake_text", "") if getattr(ear, "last_wake", "") == "name" else "")
            menubar.set_state("listening")
            _RUNTIME["talking"], _RUNTIME["last_talk"] = True, time.time()
            menubar.holo(True)  # голограмма эффектно появляется
            if cfg.get("duck_music", True):
                duck.duck()  # музыку тише — чтобы лучше слышать сэра
            alfred_window(True, cfg)
            if ptt:
                pass  # held-key talk: the pill is already listening, no chime
            elif pending:
                voice.chime("Tink")  # команда уже сказана вместе с именем — сразу выполняем
            else:
                mouth.ack()
            followup = False
            while True:
                if pending:
                    text, pending = pending, None
                elif ptt:
                    ptt = False
                    if _RUNTIME.get("ptt_held"):
                        menubar.set_state("listening")
                    text = ear.record_ptt(lambda: _RUNTIME.get("ptt_held", False),
                                          on_partial=(lambda t: ui_bridge.emit("partial", text=t)
                                                      if APP and _RUNTIME.get("ptt_held") else None))
                    _RUNTIME["screen"] = _fresh_screen()
                    if text and APP:
                        ui_bridge.emit("partial", text=text)
                else:
                    menubar.set_state("listening")
                    text = ear.listen_text(start_timeout=(cfg.get("followup_seconds", 12) if _RUNTIME.get("asked") else cfg.get("followup_short_seconds", 5)) if followup else 7)  # long window only after a question
                log.add("heard", user=USER, text=text or "", **getattr(ear, "last_info", {}))
                if not text and watching():
                    # пока Alfred смотрит на сэра, разговор не обрывается на паузе (жесты, кивки работают)
                    left = _RUNTIME.get("left_at")
                    idle = time.time() - max(_RUNTIME.get("watch_active", 0), _RUNTIME.get("last_talk", 0))
                    if not (left and time.time() - left > 90) and idle < float(cfg.get("watch_idle_seconds", 300)):
                        followup = True
                        continue
                if not text:
                    break
                pk = float((getattr(ear, "last_info", {}) or {}).get("peak") or 0)
                if not followup and pk:
                    _RUNTIME["ref_peak"] = pk  # how loud he is when he talks TO Alfred
                elif followup and pk and _RUNTIME.get("ref_peak") and pk < 0.3 * _RUNTIME["ref_peak"] \
                        and not (STOP_RE.match(text) or BYE_RE.match(text) or YES_RE.match(text)):
                    print("Вы (тихо, не мне):", text, "→ пропускаю")  # side talk in the room, much quieter than his commands
                    log.add("ignored", text=text, peak=pk, ref=_RUNTIME["ref_peak"])
                    followup = True
                    continue
                if STOP_RE.match(text):
                    print("Вы:", text, "→ молчу")
                    break
                if BYE_RE.match(text):
                    print("Вы:", text)
                    mouth.say(f"Always at your service, {addr}." if voice.detect_lang(text) == "en" else f"Всегда к вашим услугам, {addr}.")
                    break
                if YES_RE.match(text) and _RUNTIME.get("asked"):  # a stray "yes" with no question pending unlocks nothing
                    grant_confirm()  # guard.py: one yes = one risky action, valid 60 s; "yes" still goes to the brain
                try:
                    import protocol as _proto
                    pname = _proto.match(text, cfg) if len(text.split()) <= 9 else None
                except Exception:
                    pname = None
                if pname:
                    print("Вы:", text, "→ protocol", pname)
                    log.add("protocol", name=pname, text=text)
                    _proto.run(pname, mouth=mouth, cfg=cfg)
                    if pname in ("leaving", "night"):
                        break  # end the conversation, orb fades
                    followup = True
                    continue
                if WAKE_PROTO_RE.search(text) and len(text.split()) <= 8:
                    print("Вы:", text, "→ wake-up protocol")
                    log.add("protocol", name="wake", text=text)
                    try:
                        import protocol
                        protocol.wake(mouth=mouth, cfg=cfg)
                    except Exception as e:
                        traceback.print_exc()
                        log.add("error", where="protocol", error=str(e)[:300])
                    followup = True
                    continue
                _RUNTIME["last_talk"] = time.time()
                short = len(text.split()) <= 7
                if UNLOOK_RE.search(text) and len(text.split()) <= 6:
                    print("Вы:", text, "→ камера выкл")
                    watch_off()
                    mouth.say(f"Camera off, {addr}.")
                    followup = True
                    continue
                if LOOK_RE.search(text):
                    print("Вы:", text, "→ камера вкл")
                    if not watch_on():
                        mouth.say(f"The camera is disabled in my menu, {addr}.")
                        followup = True
                        continue
                    rest = LOOK_RE.sub("", text).strip(" ,.!?-—")
                    if len(re.findall(r"\w+", rest)) < 2:  # просто «посмотри на меня»
                        mouth.say(random.choice([f"I see you, {addr}.", f"Watching, {addr}.", f"All eyes, {addr}."]))
                        followup = True
                        continue
                    time.sleep(1.5)  # «посмотри на меня — как я выгляжу?»: дать камере проснуться, дальше отвечает мозг
                if short and CLEAR_RE.search(text):
                    print("Вы:", text, "→ убираю панели и голограмму")
                    panels.clear()
                    try:
                        import jholo
                        jholo.write({"hide": True, "id": f"x{int(time.time() * 1000)}"})
                    except Exception as e:
                        print("голограмма:", e)
                    mouth.say(f"Cleared, {addr}.")
                    followup = True
                    continue
                if short and LEARNED_RE.search(text) and hasattr(brain, "learn"):
                    print("Вы:", text, "→ чему научился")
                    rep = last_report()
                    if show_learned(rep):
                        mouth.say(rep.get("summary") or f"Вот что я освоил, {addr}. Список на экране.")
                    elif _RUNTIME.get("learning"):
                        mouth.say(f"Я как раз учусь, {addr}. Доложу, когда закончу.")
                    else:
                        mouth.say(f"Пока докладывать нечего, {addr}. Первое обучение пройдёт ночью, "
                                  f"или скажите «поучись», и я займусь сейчас.")
                    followup = True
                    continue
                if short and LEARN_RE.search(text) and hasattr(brain, "learn"):
                    print("Вы:", text, "→ обучение")
                    if _RUNTIME.get("learning"):
                        mouth.say(f"Я уже учусь, {addr}.")
                    else:
                        mouth.say(f"Хорошо, {addr}. Разберу наши разговоры, научусь тому, что не получалось, "
                                  f"проверю и доложу. Это примерно десять–пятнадцать минут.")
                        threading.Thread(target=run_learning, kwargs={"announce": True}, daemon=True).start()
                    followup = True
                    continue
                fast = None
                if cfg.get("fast_commands", True):
                    try:
                        fast = quick.handle(text, mouth.say, _addr_word(cfg))
                    except Exception as e:
                        print("[быстрая команда] ошибка:", e)
                if fast:
                    menubar.set_state("speaking", text)
                    print("Вы:", text)
                    print("Alfred (быстро):", fast)
                    log.add("quick", text=text, reply=fast)
                    _RUNTIME["asked"] = fast.strip().endswith("?")
                    interrupted = mouth.say(fast, barge=True)
                else:
                    interrupted = respond(text, screen=_RUNTIME.pop("screen", None))
                if interrupted and _RUNTIME.pop("gesture_stop", False):
                    print("(жест ✋ — замолчал)")
                    break
                if interrupted:
                    print("(перебили)")
                    if not _RUNTIME.get("ptt_req"):
                        mouth.ack()
                    followup = False
                    continue
                followup = True
            _RUNTIME["talking"], _RUNTIME["last_talk"] = False, time.time()
            watch_off()
            panels.clear()
            duck.restore()
            menubar.holo(False)  # «стоп» / «спасибо» / тишина — голограмма испаряется
            alfred_window(False, cfg)
            menubar.set_state("idle")
        except KeyboardInterrupt:
            mouth.say(f"Powering down, {addr}.")
            sys.exit(42)
        except Exception as e:
            traceback.print_exc()
            _RUNTIME["talking"] = False
            watch_off()
            menubar.holo(False)
            for _undo in (duck.restore, panels.clear):  # don't leave music turned down or panels on screen
                try:
                    _undo()
                except Exception:
                    pass
            log.add("error", where="loop", error=str(e)[:500])
            time.sleep(1)


if __name__ == "__main__":
    if "--text" in sys.argv:
        main()
    else:
        _cfg = load_config()
        try:
            import rumps  # noqa: F401
            import WebKit  # noqa: F401
        except ImportError:
            print("Ставлю иконку и голограмму (один раз, около минуты)…")
            subprocess.run([str(HOME / "bin" / "uv"), "pip", "install", "--python", sys.executable, "-q",
                            "rumps", "pyobjc-framework-WebKit"], timeout=600)

        def _show():
            c = dict(_cfg)
            c["window_follows_voice"] = True
            alfred_window(True, c)

        html = str(HOME / "robot.html") if _cfg.get("hologram", True) else None
        menubar.run(main, show_window=_show, level_fn=current_level, html_path=html)
