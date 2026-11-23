"""Silent mode: Alfred doesn't speak. Every answer shows as a glowing card on top of everything, then dissolves.

On/off is a flag file data/silent_on (menu bar, Alfred.app and the console all share it).
voice.Mouth sends text here instead of speaking; menubar's main-thread timer drains it into card.py.
No AppKit here, so any thread can call show().
"""
import os
import queue
import time

_HOME = os.path.dirname(os.path.abspath(__file__))
FLAG = os.path.join(_HOME, "data", "silent_on")
_q = queue.Queue()
_cache = {"t": 0.0, "v": False}
on_change = None  # hook set by menubar (app mode): called after set_on()


def is_on():
    now = time.time()
    if now - _cache["t"] > 0.5:
        _cache["v"] = os.path.exists(FLAG)
        _cache["t"] = now
    return _cache["v"]


def set_on(on):
    try:
        if on:
            open(FLAG, "w").close()
        elif os.path.exists(FLAG):
            os.replace(FLAG, FLAG + ".old")  # rename, never delete
    except OSError:
        pass
    _cache["t"] = 0.0
    if on_change:
        try:
            on_change()
        except Exception:
            pass


def show(text, kind="say"):
    """Queue text for the card. kind: 'say' (answer) or 'note' (small status line)."""
    text = (text or "").strip()
    if text:
        if os.environ.get("ALFRED_APP") == "1":  # Alfred.app shows it (reply card / toast)
            try:
                import ui_bridge
                if kind == "note":
                    ui_bridge.emit("toast", text=text)
                else:
                    ui_bridge.emit("reply", text=text, long=len(text) > 160 or "\n" in text)
            except Exception:
                pass
            return
        _q.put((kind, text))


def drain():
    out = []
    try:
        while True:
            out.append(_q.get_nowait())
    except queue.Empty:
        pass
    return out
