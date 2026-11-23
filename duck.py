"""Приглушает музыку (Music, Spotify), пока Alfred слушает и говорит, — чтобы лучше слышать сэра."""
import subprocess
import threading

APPS = ("Spotify", "Music")
_saved = {}
_lock = threading.Lock()


def _osa(script, timeout=3):
    try:
        r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip()
    except Exception:
        return ""


def _running():
    out = []
    for a in APPS:
        try:
            if subprocess.run(["pgrep", "-x", a], capture_output=True, timeout=2).returncode == 0:
                out.append(a)
        except Exception:
            pass
    return out


def duck(level=15):
    """Тише музыку, если играет. Вызывать при «Alfred»."""
    def work():
        with _lock:
            for app in _running():
                if app in _saved:
                    continue
                vol = _osa(f'tell application "{app}" to if player state is playing then get sound volume')
                if vol.isdigit() and int(vol) > level:
                    _saved[app] = int(vol)
                    _osa(f'tell application "{app}" to set sound volume to {level}')
    threading.Thread(target=work, daemon=True).start()


def restore():
    """Вернуть громкость музыки. Вызывать в конце разговора."""
    def work():
        with _lock:
            for app, vol in list(_saved.items()):
                _osa(f'tell application "{app}" to set sound volume to {vol}')
                _saved.pop(app, None)
    threading.Thread(target=work, daemon=True).start()


_paused = []


def pause_players():
    """Сэр ушёл от компьютера — ставим музыку на паузу (вернём, когда вернётся)."""
    def work():
        with _lock:
            for app in _running():
                st = _osa(f'tell application "{app}" to get player state as string')
                if st == "playing":
                    _osa(f'tell application "{app}" to pause')
                    if app not in _paused:
                        _paused.append(app)
    threading.Thread(target=work, daemon=True).start()


def resume_players():
    def work():
        with _lock:
            while _paused:
                app = _paused.pop()
                _osa(f'tell application "{app}" to play')
    threading.Thread(target=work, daemon=True).start()
