"""Глаза Alfred: камера Mac → лицо, мимика, жесты рук, кивки. Работает отдельным процессом.

Камера включается ТОЛЬКО по просьбе сэра («посмотри на меня») и выключается вместе с концом разговора
или по «не смотри» — в остальное время процесса нет и камера Mac не открывается.

Всё распознаётся прямо на Mac (MediaPipe), кадры никуда не отправляются и не сохраняются.
Снимок делается только по просьбе сэра (jlook.py) — тогда кадр кладётся в data/look-<пользователь>.jpg.

Пишет события в stdout по одному JSON на строку:
  {"ev":"state","present":true,"x":0.48,"y":0.41,"expr":"smile"}   ~2 раза в секунду
  {"ev":"gesture","name":"Thumb_Up"}     Open_Palm, Closed_Fist, Pointing_Up, Thumb_Up, Thumb_Down, Victory, ILoveYou
  {"ev":"nod"} / {"ev":"shake"}           кивок «да» / покачивание «нет»
  {"ev":"expr","name":"smile"}           смена выражения: smile, surprise, frown, sad, neutral
  {"ev":"yawn"} / {"ev":"eyes_closed"}
  {"ev":"arrive","away":312} / {"ev":"leave"}
  {"ev":"error","msg":"camera"}
Команды в stdin: pause, resume, quit.
"""
import collections
import getpass
import json
import os
import sys
import threading
import time
import urllib.request
from pathlib import Path

HOME = Path(__file__).resolve().parent
MODELS = HOME / "models" / "vision"
URLS = {
    "face_landmarker.task": "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task",
    "gesture_recognizer.task": "https://storage.googleapis.com/mediapipe-models/gesture_recognizer/gesture_recognizer/float16/1/gesture_recognizer.task",
}
USER = getpass.getuser()
LOOK_REQ = HOME / "data" / f"look_req-{USER}"
LOOK_JPG = HOME / "data" / f"look-{USER}.jpg"


def emit(**kw):
    try:
        sys.stdout.write(json.dumps(kw, ensure_ascii=False) + "\n")
        sys.stdout.flush()
    except Exception:
        pass


# ---------------------------------------------------------------- анализ (без камеры — удобно проверять)
class Analyzer:
    GESTURES = {"Open_Palm", "Closed_Fist", "Pointing_Up", "Thumb_Up", "Thumb_Down", "Victory", "ILoveYou"}

    def __init__(self, leave_sec=10.0):
        self.leave_sec = leave_sec
        self.present = False
        self.last_seen = 0.0
        self.away_since = None
        self.seen_since = None
        self.track = collections.deque()          # (t, x, y, fw) — для кивков
        self.head_cool = 0.0
        self.g_name, self.g_count, self.g_cool = None, 0, {}
        self.expr_hist = collections.deque()      # (t, expr)
        self.expr = "neutral"
        self.jaw_since = None
        self.closed_since = None
        self.yawn_cool = 0.0
        self.closed_cool = 0.0
        self.x = self.y = 0.5

    @staticmethod
    def classify(bs):
        g = lambda k: bs.get(k, 0.0)  # noqa: E731
        smile = (g("mouthSmileLeft") + g("mouthSmileRight")) / 2
        frown = (g("mouthFrownLeft") + g("mouthFrownRight")) / 2
        brow_down = (g("browDownLeft") + g("browDownRight")) / 2
        wide = (g("eyeWideLeft") + g("eyeWideRight")) / 2
        if smile > 0.45:
            return "smile"
        if g("browInnerUp") > 0.45 and (wide > 0.25 or g("jawOpen") > 0.35):
            return "surprise"
        if brow_down > 0.45 and smile < 0.1:
            return "frown"
        if frown > 0.3:
            return "sad"
        return "neutral"

    def update(self, t, face=None, gesture=None):
        """face: {"x","y","fw","bs":{blendshape: score}} или None; gesture: (name, score) или None."""
        ev = []
        # --- присутствие
        if face:
            self.last_seen = t
            self.x, self.y = face["x"], face["y"]
            if not self.present:
                self.seen_since = self.seen_since or t
                if t - self.seen_since >= 1.0:
                    self.present = True
                    away = round(t - self.away_since) if self.away_since else 0
                    ev.append({"ev": "arrive", "away": away})
                    self.away_since = None
        else:
            self.seen_since = None
            if self.present and t - self.last_seen > self.leave_sec:
                self.present = False
                self.away_since = self.last_seen
                ev.append({"ev": "leave"})
        # --- голова: кивок / покачивание
        if face:
            self.track.append((t, face["x"], face["y"], face["fw"]))
        while self.track and t - self.track[0][0] > 1.6:
            self.track.popleft()
        if face and len(self.track) >= 6 and t > self.head_cool:
            hv = self._head_gesture()
            if hv:
                ev.append({"ev": hv})
                self.head_cool = t + 3.0
                self.track.clear()
        # --- мимика
        if face and face.get("bs"):
            bs = face["bs"]
            e = self.classify(bs)
            self.expr_hist.append((t, e))
            while self.expr_hist and t - self.expr_hist[0][0] > 1.2:
                self.expr_hist.popleft()
            cnt = collections.Counter(x for _, x in self.expr_hist)
            top, n = cnt.most_common(1)[0]
            if top != self.expr and n >= max(3, 0.7 * len(self.expr_hist)):
                self.expr = top
                ev.append({"ev": "expr", "name": top})
            jaw = bs.get("jawOpen", 0.0)
            if jaw > 0.55:
                self.jaw_since = self.jaw_since or t
                if t - self.jaw_since > 1.2 and t > self.yawn_cool:
                    ev.append({"ev": "yawn"})
                    self.yawn_cool = t + 8
            else:
                self.jaw_since = None
            closed = (bs.get("eyeBlinkLeft", 0) + bs.get("eyeBlinkRight", 0)) / 2 > 0.6
            if closed:
                self.closed_since = self.closed_since or t
                if t - self.closed_since > 2.5 and t > self.closed_cool:
                    ev.append({"ev": "eyes_closed"})
                    self.closed_cool = t + 30
            else:
                self.closed_since = None
        # --- жесты рук (держать ~полсекунды)
        name = gesture[0] if gesture and gesture[1] >= 0.62 and gesture[0] in self.GESTURES else None
        if name and name == self.g_name:
            self.g_count += 1
        else:
            self.g_name, self.g_count = name, 1 if name else 0
        if name and self.g_count == 3 and t > self.g_cool.get(name, 0):
            ev.append({"ev": "gesture", "name": name})
            self.g_cool[name] = t + 2.0
        return ev

    def _head_gesture(self):
        xs = [p[1] for p in self.track]
        ys = [p[2] for p in self.track]
        fw = max(1e-3, sum(p[3] for p in self.track) / len(self.track))
        rx, ry = (max(xs) - min(xs)) / fw, (max(ys) - min(ys)) / fw

        def reversals(v, thr):
            n, d, ref = 0, 0, v[0]
            for a in v[1:]:
                if a - ref > thr:
                    if d < 0:
                        n += 1
                    d, ref = 1, a
                elif ref - a > thr:
                    if d > 0:
                        n += 1
                    d, ref = -1, a
            return n
        if ry > 0.25 and rx < 0.6 * ry and reversals(ys, 0.07 * fw) >= 2:
            return "nod"
        if rx > 0.3 and ry < 0.6 * rx and reversals(xs, 0.08 * fw) >= 2:
            return "shake"
        return None


# ---------------------------------------------------------------- камера и нейросети
def ensure_models():
    MODELS.mkdir(parents=True, exist_ok=True)
    for name, url in URLS.items():
        p = MODELS / name
        if not p.exists() or p.stat().st_size < 100_000:
            tmp = p.with_suffix(".part")
            urllib.request.urlretrieve(url, tmp)
            tmp.replace(p)
    return MODELS / "face_landmarker.task", MODELS / "gesture_recognizer.task"


class Eyes:
    def __init__(self, fps=6.0, cam_index=0):
        import mediapipe as mp
        from mediapipe.tasks import python as mpt
        from mediapipe.tasks.python import vision as mpv
        self.mp = mp
        fpath, gpath = ensure_models()
        self.face = mpv.FaceLandmarker.create_from_options(mpv.FaceLandmarkerOptions(
            base_options=mpt.BaseOptions(model_asset_path=str(fpath)), running_mode=mpv.RunningMode.VIDEO,
            num_faces=1, output_face_blendshapes=True))
        self.gest = mpv.GestureRecognizer.create_from_options(mpv.GestureRecognizerOptions(
            base_options=mpt.BaseOptions(model_asset_path=str(gpath)), running_mode=mpv.RunningMode.VIDEO,
            num_hands=1))
        self.fps = fps
        self.cam_index = cam_index
        self.cap = None
        self.paused = False
        self.quit = False
        self.ts = 0
        self.an = Analyzer()
        self.hand = None

    def _mac_check(self):
        """macOS: camera permission state + which camera is the built-in one. Saved to data/camera_check.json."""
        info = {"t": time.time(), "status": None, "devices": [], "pick": None}
        try:
            import AVFoundation as AV
            st = int(AV.AVCaptureDevice.authorizationStatusForMediaType_(AV.AVMediaTypeVideo))
            info["status"] = {0: "not asked yet", 1: "restricted", 2: "denied", 3: "allowed"}.get(st, str(st))
            if st == 0:  # ask once; the dialog names the app that started Alfred (Terminal)
                done = threading.Event()
                AV.AVCaptureDevice.requestAccessForMediaType_completionHandler_(AV.AVMediaTypeVideo, lambda ok: done.set())
                done.wait(30)
                st = int(AV.AVCaptureDevice.authorizationStatusForMediaType_(AV.AVMediaTypeVideo))
                info["status_after_ask"] = {2: "denied", 3: "allowed"}.get(st, str(st))
            devs = list(AV.AVCaptureDevice.devicesWithMediaType_(AV.AVMediaTypeVideo) or [])
            info["devices"] = [str(d.localizedName()) for d in devs]
            for i, n in enumerate(info["devices"]):
                if any(k in n.lower() for k in ("facetime", "built-in", "macbook")):
                    info["pick"] = i
                    break
        except Exception as e:
            info["error"] = str(e)[:200]
        try:
            (Path(__file__).resolve().parent / "data" / "camera_check.json").write_text(json.dumps(info, ensure_ascii=False, indent=1))
        except Exception:
            pass
        return info

    def open(self):
        import cv2
        order = [self.cam_index]
        if sys.platform == "darwin":
            info = self._mac_check()
            if info.get("pick") is not None:
                order = [info["pick"]] + [i for i in (0, 1, 2) if i != info["pick"]]
            else:
                order = [0, 1, 2]
        cap = None
        for idx in order:
            cap = cv2.VideoCapture(idx, cv2.CAP_AVFOUNDATION) if sys.platform == "darwin" else cv2.VideoCapture(idx)
            if cap.isOpened():
                ok, fr = cap.read()
                if ok and fr is not None:
                    break
            cap.release()
            cap = None
        if cap is None:
            return False
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
        cap.set(cv2.CAP_PROP_FPS, 15)
        self.cap = cap
        return True

    def close(self):
        if self.cap is not None:
            self.cap.release()
            self.cap = None

    def analyse(self, frame_bgr):
        import cv2
        h, w = frame_bgr.shape[:2]
        small = cv2.resize(frame_bgr, (480, int(480 * h / w)))
        rgb = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
        img = self.mp.Image(image_format=self.mp.ImageFormat.SRGB, data=rgb)
        self.ts = max(self.ts + 1, int(time.monotonic() * 1000))
        fr = self.face.detect_for_video(img, self.ts)
        gr = self.gest.recognize_for_video(img, self.ts)
        face = None
        if fr.face_landmarks:
            lm = fr.face_landmarks[0]
            nose, le, re_ = lm[1], lm[33], lm[263]
            face = {"x": nose.x, "y": nose.y, "fw": abs(re_.x - le.x) + 1e-3, "bs": {}}
            if fr.face_blendshapes:
                face["bs"] = {c.category_name: c.score for c in fr.face_blendshapes[0]}
        gesture = None
        self.hand = gr.hand_landmarks[0] if gr.hand_landmarks else None
        if gr.gestures and gr.gestures[0]:
            c = gr.gestures[0][0]
            gesture = (c.category_name, c.score)
        return face, gesture

    def snapshot(self, frame_bgr):
        import cv2
        tmp = LOOK_JPG.with_suffix(".tmp.jpg")
        cv2.imwrite(str(tmp), frame_bgr, [cv2.IMWRITE_JPEG_QUALITY, 88])
        tmp.replace(LOOK_JPG)
        try:
            os.chmod(LOOK_JPG, 0o666)
        except OSError:
            pass

    def control(self):
        for line in sys.stdin:
            cmd = line.strip().lower()
            if cmd == "pause":
                self.paused = True
            elif cmd == "resume":
                self.paused = False
            elif cmd == "quit":
                self.quit = True
                break
        self.quit = True  # Alfred закрылся — выходим и мы

    def run(self):
        threading.Thread(target=self.control, daemon=True).start()
        last_proc, last_state, err_t = 0.0, 0.0, 0.0
        while not self.quit:
            if self.paused:
                self.close()
                time.sleep(0.3)
                continue
            if self.cap is None:
                if not self.open():
                    if time.time() - err_t > 60:
                        emit(ev="error", msg="camera")
                        err_t = time.time()
                    time.sleep(5)
                    continue
                emit(ev="camera", on=True)
            ok, frame = self.cap.read()
            if not ok or frame is None:
                self.close()
                time.sleep(1)
                continue
            now = time.monotonic()
            if LOOK_REQ.exists():
                try:
                    self.snapshot(frame)
                    LOOK_REQ.unlink()
                except Exception as e:
                    emit(ev="error", msg=f"snapshot: {e}")
            if now - last_proc < 1.0 / self.fps:
                continue
            last_proc = now
            try:
                face, gesture = self.analyse(frame)
            except Exception as e:
                emit(ev="error", msg=f"analyse: {e}"[:200])
                time.sleep(1)
                continue
            for e in self.an.update(now, face, gesture):
                emit(**e)
            if self.hand:  # Stark-style hologram control: palm position, distance to camera, grab/pinch
                h = self.hand
                size = ((h[0].x - h[9].x) ** 2 + (h[0].y - h[9].y) ** 2) ** 0.5
                pinch = ((h[4].x - h[8].x) ** 2 + (h[4].y - h[8].y) ** 2) ** 0.5 / max(size, 1e-3)
                tips_folded = sum(1 for tip, pip in ((8, 6), (12, 10), (16, 14), (20, 18)) if h[tip].y > h[pip].y)
                emit(ev="hand", x=round(h[9].x, 4), y=round(h[9].y, 4), size=round(size, 4),
                     pinch=round(pinch, 3), grab=bool(tips_folded >= 3 or pinch < 0.35),
                     g=(gesture[0] if gesture else ""))
            if now - last_state > 0.5:
                last_state = now
                emit(ev="state", present=bool(face), x=round(self.an.x, 3), y=round(self.an.y, 3), expr=self.an.expr)
        self.close()


if __name__ == "__main__":
    fps = float(sys.argv[1]) if len(sys.argv) > 1 else 6.0
    try:
        Eyes(fps=fps).run()
    except Exception as e:
        emit(ev="error", msg=f"start: {e}"[:300])
        sys.exit(1)
