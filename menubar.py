"""Иконка Alfred в строке меню macOS (рядом с часами).

Показывает состояние: 🎙 ждёт имени · 🔴 слушает · 💭 думает · 🔊 говорит · ⏸ пауза.
Меню: последняя фраза, пауза, показать окно, перезапуск, выключение.
Если библиотеки rumps нет, Alfred просто работает без иконки.
"""
import os
import sys
import threading
import time

import silent as _silent

APP_MODE = os.environ.get("ALFRED_APP") == "1"
try:
    import ui_bridge as _bridge
except Exception:  # bridge is optional in the old mode
    _bridge = None
_last_bridge = {"state": None, "text": None}


def _bridge_state():
    """Map internal status to the contract states: idle·listening·thinking·speaking·silent·asleep."""
    if STATE["paused"]:
        return "asleep"
    st = shown_state()
    if st == "speaking":
        return "speaking"
    if st in ("listening", "thinking"):
        return st
    return "silent" if _silent.is_on() else "idle"


def _emit_state(force=False):
    if not (APP_MODE and _bridge):
        return
    st = _bridge_state()
    text = STATE.get("last") if st == "thinking" else None
    if force or st != _last_bridge["state"] or (st == "thinking" and text != _last_bridge["text"]):
        _last_bridge.update(state=st, text=text)
        if text:
            _bridge.emit("state", state=st, text=text)
        else:
            _bridge.emit("state", state=st)


def emit_event(type, **kw):
    if APP_MODE and _bridge:
        _bridge.emit(type, **kw)


def _mirror(key, value):
    if APP_MODE and _bridge:
        _bridge.set_setting(key, value)


_silent.on_change = lambda: (_emit_state(), _mirror("silent", _silent.is_on()))

ICONS = {"learning": "📚", "idle": "🎙", "listening": "🔴", "thinking": "💭", "speaking": "🔊", "paused": "🔇", "starting": "⏳"}
LABELS = {"learning": "Learning…", "idle": "Waiting for “Alfred”", "listening": "Listening", "thinking": "Thinking…",
          "speaking": "Speaking", "paused": "Microphone OFF — not listening", "starting": "Starting…"}

STATE = {"status": "starting", "last": "", "paused": False, "exit_code": None, "speaking": False, "summon": False,
         "holo": False}
HOLO_MODES = {"auto": "Hologram — appears when called", "always": "Hologram — always on screen",
              "off": "No hologram"}
_HOLO_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data",
                          f"holo_mode-{os.environ.get('USER', 'user')}.txt")


def holo(on):
    """Alfred просит показать (True) или убрать (False) голограмму."""
    STATE["holo"] = bool(on)


def holo_mode():
    return STATE.get("holo_mode") or _load_holo_mode()


def set_holo_mode_value(m):
    """App mode / Alfred.app: auto·always·off."""
    if m in HOLO_MODES:
        STATE["holo_mode"] = m
        _save_holo_mode(m)
        _mirror("holo_mode", m)


_CAM_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data",
                         f"camera-{os.environ.get('USER', 'user')}.txt")


def camera_enabled():
    try:
        return open(_CAM_FILE).read().strip() != "off"
    except Exception:
        return True


def set_camera(on):
    try:
        os.makedirs(os.path.dirname(_CAM_FILE), exist_ok=True)
        with open(_CAM_FILE, "w") as f:
            f.write("on" if on else "off")
    except Exception:
        pass
    _mirror("camera", bool(on))


def set_look(fn):
    """Откуда голограмме брать взгляд: камера (лицо сэра) вместо курсора мыши."""
    _hooks["look"] = fn


def _load_holo_mode():
    try:
        m = open(_HOLO_FILE).read().strip()
        return m if m in HOLO_MODES else "off"
    except Exception:
        return "off"


def _save_holo_mode(m):
    try:
        os.makedirs(os.path.dirname(_HOLO_FILE), exist_ok=True)
        with open(_HOLO_FILE, "w") as f:
            f.write(m)
    except Exception:
        pass
    _mirror("holo_mode", m)


_hooks = {"show_window": None, "level": None, "html": None}


def speaking(on):
    STATE["speaking"] = bool(on)
    _emit_state()


def take_summon():
    if STATE.get("summon"):
        STATE["summon"] = False
        return True
    return False


def shown_state():
    if STATE["paused"]:
        return "paused"
    if STATE["speaking"]:
        return "speaking"
    return STATE["status"]


def set_state(status, last=None):
    if STATE["paused"] and status != "paused":
        status = "paused"
    STATE["status"] = status
    if last:
        STATE["last"] = last[:60]
    _emit_state()


_MIC_OFF_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "mic_off")


def is_paused():
    return STATE["paused"]


def set_mic_off(off):
    """Mic off = paused + the mic stream is closed (alfred.py watches is_paused). Shared with Alfred.app via data/mic_off."""
    off = bool(off)
    try:
        if off:
            open(_MIC_OFF_FILE, "w").close()
        elif os.path.exists(_MIC_OFF_FILE):
            os.replace(_MIC_OFF_FILE, _MIC_OFF_FILE + ".old")  # rename, never delete
    except OSError:
        pass
    STATE["paused"] = off
    STATE["status"] = "paused" if off else "idle"
    _mirror("mic_off", off)
    _emit_state()


def sync_mic_file():
    """Pick up a mic on/off change made outside the menu (Alfred.app)."""
    off = os.path.exists(_MIC_OFF_FILE)
    if off != STATE["paused"]:
        STATE["paused"] = off
        STATE["status"] = "paused" if off else "idle"
        _mirror("mic_off", off)
        _emit_state()


STATE["paused"] = os.path.exists(_MIC_OFF_FILE)


def run(main_fn, show_window=None, level_fn=None, html_path=None):
    """Запускает Alfred в фоне, а в главном потоке — иконку в строке меню и голограмму."""
    _hooks["show_window"] = show_window
    _hooks["level"] = level_fn
    if APP_MODE:
        return _run_headless(main_fn, show_window, html_path)
    try:
        import rumps
    except Exception as e:
        print("Иконка в строке меню недоступна (нет rumps):", e)
        return main_fn()

    def worker():
        try:
            main_fn()
            STATE["exit_code"] = 0
        except SystemExit as e:
            STATE["exit_code"] = e.code if isinstance(e.code, int) else 0
        except BaseException:
            import traceback
            traceback.print_exc()
            STATE["exit_code"] = 1

    th = threading.Thread(target=worker, daemon=True)
    th.start()

    class AlfredApp(rumps.App):
        def __init__(self):
            super().__init__("Alfred", title=ICONS["starting"], quit_button=None)
            self.status_item = rumps.MenuItem(LABELS["starting"])
            self.last_item = rumps.MenuItem("—")
            self.pause_item = rumps.MenuItem("🔇 Turn microphone off", callback=self.toggle_pause)
            self.silent_item = rumps.MenuItem("🤫 Silent mode (text only)", callback=self.toggle_silent)
            self.silent_item.state = 1 if _silent.is_on() else 0
            self._silent_prev = _silent.is_on()
            self.card = None
            try:
                from card import Card
                self.card = Card(os.path.join(os.path.dirname(os.path.abspath(__file__)), "card.html"))
            except Exception as e:
                print("Карточка не запустилась:", e)
            self.holo = None
            if html_path and os.path.exists(html_path):
                try:
                    from hologram import Hologram
                    self.holo = Hologram(html_path, on_click=self.summon, on_double=self.show_cb)
                except Exception as e:
                    print("Голограмма не запустилась:", e)
            self.stage = None
            stage_html = os.path.join(os.path.dirname(os.path.abspath(__file__)), "stage.html")
            if os.path.exists(stage_html):
                try:
                    from holostage import HoloStage
                    spec = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data",
                                        f"holo-{os.environ.get('USER', 'user')}.json")
                    self.stage = HoloStage(stage_html, spec)
                    self.stage.on_show = self._face_front
                except Exception as e:
                    print("Голограммы на экране не запустились:", e)
            self.holo_mode = _load_holo_mode()
            self.holo_items = {m: rumps.MenuItem(t, callback=self.set_holo_mode) for m, t in HOLO_MODES.items()}
            self._mark_holo()
            self.cam_item = rumps.MenuItem("Camera on “look at me”", callback=self.toggle_camera)
            self.cam_item.state = 1 if camera_enabled() else 0
            self.menu = [
                self.status_item, self.last_item, None,
                self.pause_item, self.silent_item, None,
                *self.holo_items.values(), self.cam_item, None,
                rumps.MenuItem("Learn now", callback=self.learn_now),
                rumps.MenuItem("What I learned", callback=self.growth),
                None,
                rumps.MenuItem("Open Console", callback=self.open_console),
                rumps.MenuItem("Show window", callback=self.show),
                rumps.MenuItem("Restart", callback=self.restart),
                None,
                rumps.MenuItem("Quit Alfred", callback=self.shutdown),
            ]
            self.timer = rumps.Timer(self.tick, 0.25)
            self.timer.start()
            self.holo_timer = rumps.Timer(self.holo_tick, 1 / 30)
            self.holo_timer.start()

        def _mark_holo(self):
            for m, it in self.holo_items.items():
                it.state = 1 if m == self.holo_mode else 0

        def set_holo_mode(self, sender):
            for m, it in self.holo_items.items():
                if it is sender:
                    self.holo_mode = m
            _save_holo_mode(self.holo_mode)
            self._mark_holo()

        def _face_front(self):
            if self.holo and self.holo.visible:
                self.holo.w.orderFrontRegardless()  # лицо Alfred поверх голограммы

        def watch_panels(self):
            """Мозг кладёт панели в data/panels-<пользователь>.json — показываем их на голограмме."""
            if not self.holo:
                return
            try:
                import panels
                p = panels.path()
                mt = p.stat().st_mtime if p.exists() else 0
                if mt != getattr(self, "_panels_mt", None):
                    self._panels_mt = mt
                    self.holo.set_panels(panels.read())
            except Exception as e:
                print("панели:", e)

        def holo_tick(self, _):
            try:
                self.push_hand()
            except Exception:
                pass
            if not self.holo:
                return
            want = self.holo_mode == "always" or (
                self.holo_mode == "auto" and STATE["holo"] and not STATE["paused"])
            try:
                if want:
                    self.holo.show()
                else:
                    self.holo.hide()
            except Exception as e:
                print("голограмма:", e)
            st = shown_state()
            lvl = 0.0
            fn = _hooks.get("level")
            if fn and st in ("speaking", "listening"):
                try:
                    lvl = float(fn(st))
                except Exception:
                    lvl = 0.0
            look = None
            lf = _hooks.get("look")
            if lf:
                try:
                    look = lf()
                except Exception:
                    look = None
            try:
                self.holo.push(st, lvl, look)
            except Exception as e:
                print("голограмма:", e)
                self.holo = None

        def summon(self):
            STATE["summon"] = True

        def show_cb(self):
            self.show(None)

        def push_hand(self):
            h = STATE.get("hand")
            if h and self.stage and getattr(self.stage, "visible", False) and h.get("_n") != getattr(self, "_hand_n", None):
                self._hand_n = h.get("_n")
                import json as _json
                self.stage._js("window.holo&&holo.hand&&holo.hand(" + _json.dumps({k: v for k, v in h.items() if not k.startswith("_")}) + ");")

        def tick(self, _):
            sync_mic_file()
            self._mark_mic()
            self._silent_tick()
            if not th.is_alive():
                code = STATE["exit_code"]
                os._exit(1 if code is None else code)
            self.watch_panels()
            if self.stage:
                try:
                    self.stage.tick()
                except Exception as e:
                    print("голограмма на экране:", e)
            st = shown_state()
            if st == "idle" and STATE.get("learning"):
                st = "learning"
            title = ICONS.get(st, "🎙")
            if self.title != title:
                self.title = title
            label = LABELS.get(st, st)
            if self.status_item.title != label:
                self.status_item.title = label
            last = f"Last: {STATE['last']}" if STATE["last"] else "—"
            if self.last_item.title != last:
                self.last_item.title = last

        def toggle_silent(self, sender):
            _silent.set_on(not _silent.is_on())
            self._silent_tick()

        def _silent_tick(self):
            on = _silent.is_on()
            self.silent_item.state = 1 if on else 0
            if on and not self._silent_prev:
                _silent.show("Silent mode on — answers appear here.", "note")
            self._silent_prev = on
            if self.card:
                try:
                    for kind, text in _silent.drain():
                        self.card.show(kind, text)
                    self.card.tick()
                except Exception as e:
                    print("card:", e)

        def toggle_pause(self, sender):
            set_mic_off(not STATE["paused"])
            self._mark_mic()

        def _mark_mic(self):
            t = "🎙 Turn microphone on" if STATE["paused"] else "🔇 Turn microphone off"
            if self.pause_item.title != t:
                self.pause_item.title = t

        def toggle_camera(self, sender):
            on = not camera_enabled()
            set_camera(on)
            sender.state = 1 if on else 0

        def learn_now(self, _):
            STATE["learn_now"] = True

        def growth(self, _):
            import subprocess
            g = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "growth.md")
            if not os.path.exists(g):
                with open(g, "w", encoding="utf-8") as f:
                    f.write("# Чему научился Alfred\n\nПока пусто — первое обучение пройдёт ночью.\n")
            subprocess.Popen(["open", "-a", "TextEdit", g])

        def open_console(self, _):
            import subprocess
            d = os.path.dirname(os.path.abspath(__file__))
            subprocess.Popen([sys.executable, os.path.join(d, "console.py")], cwd=d)

        def show(self, _):
            fn = _hooks.get("show_window")
            if fn:
                fn()

        def restart(self, _):
            os._exit(1)  # окно перезапустит Alfred через 3 секунды

        def shutdown(self, _):
            os._exit(42)

    try:
        from AppKit import NSApplication
        NSApplication.sharedApplication().setActivationPolicy_(1)  # без значка в Dock
    except Exception:
        pass
    AlfredApp().run()


def _run_headless(main_fn, show_window, html_path):
    """Alfred.app owns the menu bar and the windows. Python keeps a bare AppKit main loop (holograms live here)."""
    def worker():
        try:
            main_fn()
            STATE["exit_code"] = 0
        except SystemExit as e:
            STATE["exit_code"] = e.code if isinstance(e.code, int) else 0
        except BaseException:
            import traceback
            traceback.print_exc()
            STATE["exit_code"] = 1

    th = threading.Thread(target=worker, daemon=True)
    th.start()
    try:
        from AppKit import NSApplication
        from Foundation import NSTimer
        app = NSApplication.sharedApplication()
        app.setActivationPolicy_(1)  # accessory: no Dock icon
    except Exception as e:
        print("headless loop unavailable:", e)
        th.join()
        os._exit(1 if STATE["exit_code"] is None else STATE["exit_code"])

    here = os.path.dirname(os.path.abspath(__file__))
    holo = stage = None
    if html_path and os.path.exists(html_path):
        try:
            from hologram import Hologram
            holo = Hologram(html_path, on_click=lambda: STATE.__setitem__("summon", True), on_double=lambda: None)
        except Exception as e:
            print("Голограмма не запустилась:", e)
    stage_html = os.path.join(here, "stage.html")
    if os.path.exists(stage_html):
        try:
            from holostage import HoloStage
            spec = os.path.join(here, "data", f"holo-{os.environ.get('USER', 'user')}.json")
            stage = HoloStage(stage_html, spec)
            stage.on_show = lambda: holo.w.orderFrontRegardless() if holo and holo.visible else None
        except Exception as e:
            print("Голограммы на экране не запустились:", e)
    mem = {"panels": None, "hand": None, "holo": holo}
    STATE["holo_mode"] = _load_holo_mode()

    def tick():
        sync_mic_file()
        if not th.is_alive():
            os._exit(1 if STATE["exit_code"] is None else STATE["exit_code"])
        _emit_state()
        # old silent card is replaced by Alfred.app: just keep the queue empty
        _silent.drain()
        h = mem["holo"]
        if h:
            try:
                import panels
                p = panels.path()
                mt = p.stat().st_mtime if p.exists() else 0
                if mt != mem["panels"]:
                    mem["panels"] = mt
                    h.set_panels(panels.read())
            except Exception as e:
                print("панели:", e)
        if stage:
            try:
                stage.tick()
            except Exception as e:
                print("голограмма на экране:", e)

    def holo_tick():
        hd = STATE.get("hand")
        if hd and stage and getattr(stage, "visible", False) and hd.get("_n") != mem["hand"]:
            mem["hand"] = hd.get("_n")
            import json as _json
            stage._js("window.holo&&holo.hand&&holo.hand(" + _json.dumps({k: v for k, v in hd.items() if not k.startswith("_")}) + ");")
        h = mem["holo"]
        if not h:
            return
        mode = STATE.get("holo_mode", "auto")
        want = mode == "always" or (mode == "auto" and STATE["holo"] and not STATE["paused"])
        try:
            h.show() if want else h.hide()
            st = shown_state()
            lvl = 0.0
            fn = _hooks.get("level")
            if fn and st in ("speaking", "listening"):
                try:
                    lvl = float(fn(st))
                except Exception:
                    lvl = 0.0
            lf = _hooks.get("look")
            look = None
            if lf:
                try:
                    look = lf()
                except Exception:
                    look = None
            h.push(st, lvl, look)
        except Exception as e:
            print("голограмма:", e)
            mem["holo"] = None

    t1 = NSTimer.scheduledTimerWithTimeInterval_repeats_block_(0.25, True, lambda t: tick())
    t2 = NSTimer.scheduledTimerWithTimeInterval_repeats_block_(1 / 30, True, lambda t: holo_tick())
    app.run()
