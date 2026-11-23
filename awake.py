"""Keep the Mac awake (no password): runs `caffeinate` while the "Stay awake" switch is on
or an away task is running. Display may still turn off; the Mac stays online for Telegram.
caffeinate is tied to Alfred's pid (-w), so it ends by itself if Alfred quits."""
import os
import subprocess
import threading
import time

_proc = None
_lock = threading.Lock()


def is_on():
    return _proc is not None and _proc.poll() is None


def _set(want):
    global _proc
    with _lock:
        if want and not is_on():
            # -i no idle sleep, -m no disk sleep, -s no system sleep on charger
            _proc = subprocess.Popen(["caffeinate", "-ims", "-w", str(os.getpid())],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            print("[awake] on")
        elif not want and is_on():
            _proc.terminate()
            _proc = None
            print("[awake] off")


def start(setting_fn, busy_fn=None, every=5):
    """setting_fn() -> bool (the switch); busy_fn() -> bool (away task running)."""
    def loop():
        while True:
            try:
                want = bool(setting_fn()) or bool(busy_fn and busy_fn())
            except Exception:
                want = False
            try:
                _set(want)
            except Exception as e:
                print("[awake]", type(e).__name__)
            time.sleep(every)
    threading.Thread(target=loop, daemon=True, name="awake").start()
