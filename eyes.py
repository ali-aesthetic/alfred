"""Связь Alfred с его глазами (vision.py работает отдельным процессом, чтобы камера не мешала слуху)."""
import json
import subprocess
import sys
import threading
import time
from pathlib import Path

HOME = Path(__file__).resolve().parent


class EyesClient:
    def __init__(self, cfg, on_event):
        self.cfg = cfg
        self.on_event = on_event
        self.proc = None
        self.state = {"present": False, "x": 0.5, "y": 0.5, "expr": "neutral", "t": 0.0}
        self.enabled = bool(cfg.get("camera", True))
        self.paused = False
        self.camera_on = False

    def start(self):
        if not self.enabled or (self.proc and self.proc.poll() is None):
            return
        fps = str(self.cfg.get("camera_fps", 6))
        subprocess.run(["pkill", "-f", "gesture_window.py"], capture_output=True)  # старый скрипт жестов держал камеру
        now = time.time()
        self._starts = [t for t in getattr(self, "_starts", []) if now - t < 300] + [now]
        if len(self._starts) > 4:
            print("[зрение] не запускается — выключаю камеру до перезапуска Alfred")
            self.enabled = False
            return
        self.proc = subprocess.Popen([sys.executable, str(HOME / "vision.py"), fps], stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=open(HOME / "data" / "vision.err.log", "a"), text=True, bufsize=1,
                                     cwd=str(HOME))
        threading.Thread(target=self._reader, args=(self.proc,), daemon=True).start()

    def _reader(self, proc):
        for line in proc.stdout:
            try:
                ev = json.loads(line)
            except Exception:
                continue
            k = ev.get("ev")
            if k == "state":
                ev["t"] = time.time()
                self.state.update(ev)
                continue
            if k == "camera":
                self.camera_on = True
            try:
                self.on_event(ev)
            except Exception as e:
                print("[зрение] ошибка обработчика:", e)
        self.camera_on = False
        if self.enabled and not self.paused and proc is self.proc:
            time.sleep(5)  # упал во время просмотра — поднимаем снова
            if self.enabled:
                self.start()

    def _send(self, cmd):
        try:
            if self.proc and self.proc.poll() is None:
                self.proc.stdin.write(cmd + "\n")
                self.proc.stdin.flush()
        except Exception:
            pass

    def pause(self):
        if not self.paused:
            self.paused = True
            self.camera_on = False
            self._send("pause")

    def resume(self):
        if self.paused:
            self.paused = False
            self._send("resume")

    def set_enabled(self, on):
        self.enabled = bool(on)
        if on:
            self.paused = False
            self.start()
            self._send("resume")
        else:
            self.pause()

    def fresh(self, sec=3.0):
        return time.time() - self.state.get("t", 0) < sec

    def look(self):
        """Куда смотреть голограмме, чтобы глядеть сэру в глаза: (lx, ly) или None."""
        if not self.fresh() or not self.state.get("present"):
            return None
        k = float(self.cfg.get("camera_look_gain", 2.4))
        lx = max(-1.0, min(1.0, (0.5 - self.state["x"]) * k))
        ly = max(-1.0, min(1.0, (0.45 - self.state["y"]) * k))
        return lx, ly

    def stop(self):
        """Выключить камеру полностью: процесс зрения завершается, камера Mac освобождается."""
        self.enabled = False
        self.camera_on = False
        self.state["present"] = False
        p = self.proc
        self._send("quit")
        if p is not None:
            try:
                p.wait(3)
            except Exception:
                p.kill()
