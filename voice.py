"""Слух и голос Alfred.

Ear   — микрофон, слово «Alfred», запись фразы до паузы.
STT   — распознавание речи (Whisper локально: mlx на Apple Silicon, faster-whisper на Intel).
Mouth — голос (нейроголоса Microsoft через edge-tts, запасной — системный say).
"""
import asyncio
import collections
import os
import platform
import queue
import re
import subprocess
import tempfile
import threading
import time

import numpy as np

import silent

SR = 16000
BLOCK = 1280  # 80 мс — размер кадра, который ждёт openWakeWord
BLOCK_SEC = BLOCK / SR

WHISPER_PROMPT = "Alfred, open Telegram. Wake up, daddy's home. Show me a hologram. Alfred, открой Telegram. Alfred, musiqani qo'y."
VOCAB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "vocab.txt")
DEFAULT_VOCAB = ["Telegram", "Claude", "Instagram", "YouTube", "Safari", "Chrome", "Spotify", "CapCut", "DaVinci"]


def clean_audio(audio_int16):
    """Cleanup before Whisper: remove DC hum, cut rumble under ~80 Hz, lift quiet voices to -3 dBFS."""
    a = audio_int16.astype(np.float32) / 32768.0
    if a.size == 0:
        return a
    a = a - float(np.mean(a))
    # high-pass ~80 Hz: subtract a 12.5 ms moving average (fans, desk knocks, AC hum). Vectorized, ~1 ms.
    k = 200
    y = a - np.convolve(a, np.ones(k, dtype=np.float32) / k, mode="same")
    peak = float(np.max(np.abs(y))) + 1e-6
    if peak < 0.7:  # quiet speaker / far from mic: normalize, but never boost pure noise more than 12x
        y = y * min(0.7 / peak, 12.0)
    return np.clip(y, -1.0, 1.0).astype(np.float32)


def whisper_prompt():
    """Подсказка для распознавания: частые фразы + имена и слова сэра (data/vocab.txt, пополняется при обучении)."""
    try:
        if not os.path.exists(VOCAB_PATH):
            os.makedirs(os.path.dirname(VOCAB_PATH), exist_ok=True)
            with open(VOCAB_PATH, "w", encoding="utf-8") as f:
                f.write("\n".join(DEFAULT_VOCAB) + "\n")
            os.chmod(VOCAB_PATH, 0o666)
        mt = os.path.getmtime(VOCAB_PATH)
        if getattr(whisper_prompt, "_mt", None) != mt:
            words = [w.strip() for w in open(VOCAB_PATH, encoding="utf-8") if w.strip() and not w.startswith("#")]
            whisper_prompt._mt, whisper_prompt._cache = mt, ", ".join(dict.fromkeys(words))[:260]
        vocab = whisper_prompt._cache
    except Exception:
        vocab = ", ".join(DEFAULT_VOCAB)
    return f"{WHISPER_PROMPT} {vocab}." if vocab else WHISPER_PROMPT


# слова, на которых фраза явно не закончена — ждём продолжения дольше
DANGLING = set("""и а но или либо что чтобы как когда если потому поэтому в во на с со к ко по для из от до за под над о об
про у при через между мне ему ей им нам вам ну это вот типа там тут э ээ эээ мм хм его её их мой моя мою моё мои
твой свой va bilan uchun ham keyin yoki lekin and the to of a an or with for""".split())
NEEDS_OBJECT = set("открой напиши отправь поставь найди включи покажи скажи сделай запусти ответь позвони och yoz yubor qo'y top"
                   .split())


def looks_complete(text: str) -> bool:
    """Похоже ли, что сэр договорил (по распознанному тексту)."""
    t = (text or "").strip()
    if not t:
        return False
    if t.endswith((",", "-", "—", "…", "...", ":")):
        return False
    words = re.findall(r"[\wʻ‘’'-]+", t.lower())
    if not words:
        return False
    if words[-1] in DANGLING:
        return False
    if len(words) == 1 and words[0] in NEEDS_OBJECT:
        return False
    return True

HALLUCINATIONS = (
    "продолжение следует", "субтитры", "спасибо за просмотр", "редактор субтитров",
    "dimatorzok", "amara.org", "thank you for watching", "подписывайтесь", "корректор",
)

YES_RE = re.compile(
    r"\b(да|давай|подтверждаю|конечно|ага|угу|делай|выполняй|ок|окей|хорошо|валяй|можно|"
    r"yes|yeah|ok|okay|ha|xa|xo['ʻ‘’]?p|хоп|ҳа|майли|mayli)\b", re.I)
NO_RE = re.compile(r"\b(нет|не надо|не нужно|отмена|отмени|стоп|отбой|no|yo['ʻ‘’]?q|йўқ|йук|кера[кг] эмас|kerak emas)\b", re.I)


def is_yes(text: str) -> bool:
    t = (text or "").lower()
    if NO_RE.search(t):
        return False
    return bool(YES_RE.search(t))


def is_hallucination(text: str) -> bool:
    t = (text or "").lower().strip(" .,!?…-")
    if len(t) < 2:
        return True
    if re.search(r"(.)\1{5,}", t):  # «аăăăăăăă…» — мусор от шума и музыки
        return True
    if re.search(r"(.{2,5})\1{4,}", t):  # «шершершершер…»
        return True
    # иероглифы, хангыль, арабская вязь, иврит, вьетнамские и прочие диакритики — это шум, не речь сэра
    if re.search(r"[\u0590-\u06ff\u0900-\u0dff\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af\u1e00-\u1eff\ufffd]", t):
        return True
    if len(re.findall(r"[\u00c0-\u024f]", t)) >= 2 and not re.search(r"[ʻ‘’`']", t):
        return True
    return any(h in t for h in HALLUCINATIONS)


def detect_lang(text: str) -> str:
    if re.search(r"[ўқғҳЎҚҒҲ]", text):
        return "uz"
    cyr = len(re.findall(r"[а-яёА-ЯЁ]", text))
    lat = len(re.findall(r"[a-zA-Z]", text))
    if lat > cyr:
        if re.search(r"(o['ʻ‘’`]|g['ʻ‘’`]|\b(va|bu|men|siz|uchun|kerak|bilan|qiling|xo['ʻ‘’]?p)\b|lar\b|ni\b|dir\b)", text, re.I):
            return "uz"
        return "en"
    return "ru"


_UZ_LAT = [("o'", "о"), ("g'", "г"), ("sh", "ш"), ("ch", "ч"), ("yo", "ё"), ("ya", "я"), ("yu", "ю"), ("ye", "е")]
_UZ_MAP = dict(zip("abdefghijklmnopqrstuvwxyzc", "абдефгхижклмнопкрстуввхйзк"))


def uz_to_cyr(text: str) -> str:
    """Узбекская латиница → кириллица, чтобы русский голос читал узбекский текст понятно (тем же голосом)."""
    t = re.sub(r"[ʻ‘’`]", "'", text)

    def word(m):
        w = m.group(0)
        low = w.lower()
        out = ""
        i = 0
        while i < len(low):
            two = low[i:i + 2]
            hit = next((b for a, b in _UZ_LAT if a == two), None)
            if hit:
                out += hit
                i += 2
                continue
            c = low[i]
            if c == "e" and (i == 0 or low[i - 1] in "aeiou'"):
                out += "э"
            elif c == "'":
                out += ""
            else:
                out += _UZ_MAP.get(c, c)
            i += 1
        return out.capitalize() if w[:1].isupper() else out
    return re.sub(r"[A-Za-z][A-Za-z']*", word, t)


def clean_for_speech(text: str) -> str:
    text = re.sub(r"https?://\S+", "", text or "")
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    text = re.sub(r"[*_#`>|]+", "", text)
    text = re.sub(r"^\s*[-•]\s+", "", text, flags=re.M)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def chime(name="Tink"):
    path = f"/System/Library/Sounds/{name}.aiff"
    if os.path.exists(path):
        subprocess.run(["afplay", path], timeout=5)


class STT:
    def __init__(self, cfg):
        self.backend = None
        if platform.machine() == "arm64":
            try:
                import mlx_whisper  # noqa
                self.mlx = mlx_whisper
                self.mlx_model = cfg.get("mlx_whisper_model", "mlx-community/whisper-large-v3-turbo")
                self.backend = "mlx"
                self.lang = cfg.get("stt_language") or None
                self.allowed = cfg.get("stt_allowed", ["en"])
            except Exception as e:
                print("mlx-whisper недоступен, беру faster-whisper:", e)
        if self.backend is None:
            from faster_whisper import WhisperModel
            self.fw = WhisperModel(cfg.get("faster_whisper_model", "small"), device="cpu", compute_type="int8")
            self.backend = "fw"
        self.lang = cfg.get("stt_language") or None
        self.allowed = cfg.get("stt_allowed", ["en"])

    _lock = threading.Lock()

    def _once(self, a, lang):
        with self._lock:  # модель одна — распознаём по очереди
            return self._once_inner(a, lang)

    def _once_inner(self, a, lang):
        prompt = whisper_prompt()
        if self.backend == "mlx":
            r = self.mlx.transcribe(a, path_or_hf_repo=self.mlx_model, initial_prompt=prompt,
                                    condition_on_previous_text=False, language=lang,
                                    temperature=(0.0, 0.2, 0.4),          # retry if the first pass looks like garbage
                                    compression_ratio_threshold=2.4,      # "шершершер" loops
                                    logprob_threshold=-1.0,
                                    no_speech_threshold=0.6)
            segs = [s for s in (r.get("segments") or [])
                    if not (s.get("no_speech_prob", 0) > 0.6 and s.get("avg_logprob", 0) < -1.0)]
            r["text"] = "".join(s.get("text", "") for s in segs) if segs else ""
            lp = sum(s.get("avg_logprob", -1.0) for s in segs) / len(segs) if segs else -9.0
            return r.get("text", "").strip(), r.get("language") or lang, lp
        segs, info = self.fw.transcribe(a, beam_size=3, initial_prompt=prompt,
                                        condition_on_previous_text=False, language=lang,
                                        temperature=(0.0, 0.2, 0.4), compression_ratio_threshold=2.4,
                                        log_prob_threshold=-1.0, no_speech_threshold=0.6)
        segs = [s for s in segs if not (s.no_speech_prob > 0.6 and s.avg_logprob < -1.0)]
        lp = sum(s.avg_logprob for s in segs) / len(segs) if segs else -9.0
        return "".join(s.text for s in segs).strip(), info.language, lp

    def transcribe_partial(self, audio_int16, max_sec=8.0):
        """Fast live-words pass for push-to-talk: last `max_sec` seconds only, one decode, no retries, no uz fallback.
        Returns (text, language); ('', None) if the model is busy (the final pass always has priority)."""
        if audio_int16.size > SR * max_sec:
            audio_int16 = audio_int16[-int(SR * max_sec):]
        a = clean_audio(audio_int16)
        if not self._lock.acquire(blocking=False):
            return "", None
        try:
            if self.backend == "mlx":
                r = self.mlx.transcribe(a, path_or_hf_repo=self.mlx_model, initial_prompt=whisper_prompt(),
                                        condition_on_previous_text=False, language=self.lang, temperature=0.0,
                                        compression_ratio_threshold=2.4, no_speech_threshold=0.6, verbose=None)
                segs = [x for x in (r.get("segments") or []) if not (x.get("no_speech_prob", 0) > 0.6)]
                return "".join(x.get("text", "") for x in segs).strip(), (r.get("language") or self.lang)
            segs, info = self.fw.transcribe(a, beam_size=1, initial_prompt=whisper_prompt(),
                                            condition_on_previous_text=False, language=self.lang, temperature=0.0)
            return "".join(x.text for x in segs if x.no_speech_prob <= 0.6).strip(), (info.language or self.lang)
        except Exception as e:
            print("[partial stt]", e)
            return "", None
        finally:
            self._lock.release()

    def transcribe(self, audio_int16):
        a = clean_audio(audio_int16)
        if self.lang:
            text, lang, lp = self._once(a, self.lang)
            # Сэр мог сказать по-узбекски: русская модель тогда даёт латиницу или неуверенный текст — пробуем узбекский
            words = re.findall(r"[^\W\d_]+", text)
            latin = sum(1 for w in words if re.match(r"[a-zA-Z]", w))
            uz_hint = bool(re.search(r"(o['ʻ‘’`]|g['ʻ‘’`]|\b(ni|ga|da|och|yoz|qo['ʻ‘’`]?y|qil|ber|kerak|yubor|rahmat)\b)", text, re.I))
            if "uz" in self.allowed and self.lang != "uz" and words and (
                    latin / len(words) >= 0.5 or uz_hint or lp < -0.85):
                t2, l2, lp2 = self._once(a, "uz")
                if lp2 > lp + 0.05 and t2.strip():
                    return t2, "uz"
            return text, lang
        text, lang, lp = self._once(a, None)
        if lang in self.allowed:
            return text, lang
        # Язык определился неверно (таджикский, турецкий…) — пробуем разрешённые и берём уверенный
        best = (text, lang, -99.0)
        for cand in self.allowed[:2]:
            t2, l2, lp2 = self._once(a, cand)
            if lp2 > best[2]:
                best = (t2, l2, lp2)
        return best[0], best[1]


class Ear:
    def __init__(self, cfg, active_fn=None):
        import sounddevice as sd
        self.cfg = cfg
        self.active_fn = active_fn
        self.q = queue.Queue(maxsize=1000)
        self.muted = threading.Event()
        self.noise = 200.0
        self._inject = None  # ответ жестом/кивком вместо слов
        dev = cfg.get("input_device")  # e.g. "AirPods", "MacBook Pro Microphone", "Blue Yeti"; null = system default
        if dev:
            print("Микрофон:", dev)
        self.stream = sd.InputStream(samplerate=SR, channels=1, dtype="int16", device=dev or None,
                                     blocksize=BLOCK, callback=self._cb)
        self.stream.start()
        self.oww = None
        # wake_model: path to your trained "Hey Alfred" .onnx (see docs/TRAIN-HEY-ALFRED.md). null = no neural model:
        # Alfred then listens for his name through speech recognition (and you can always hold the talk key / type).
        wm = cfg.get("wake_model")
        if wm:
            try:
                from openwakeword.model import Model
                wm = os.path.expanduser(str(wm))
                self.oww = Model(wakeword_models=[wm], inference_framework="onnx")
                print("Wake word model:", os.path.basename(wm))
            except Exception as e:
                print("openWakeWord could not load, listening for the name through speech recognition:", e)
        else:
            print("No wake-word model set: listening for 'Alfred' through speech recognition (or hold the talk key).")
        self.vad = None
        try:
            from openwakeword.vad import VAD
            self.vad = VAD()
            print("Детектор речи: Silero VAD")
        except Exception as e:
            print("VAD не загрузился, слушаю по громкости:", e)
        print("Загружаю распознавание речи…")
        self.stt = STT(cfg)
        self._calibrate()

    # --- микрофон
    def _cb(self, indata, frames, t, status):
        try:
            r = float(np.sqrt(np.mean(indata[:, 0].astype(np.float32) ** 2)))
            self.level = 0.7 * getattr(self, "level", 0.0) + 0.3 * min(1.0, r / 2500.0)
        except Exception:
            pass
        if self.muted.is_set():
            return
        try:
            self.q.put_nowait(indata[:, 0].copy())
        except queue.Full:
            pass

    def flush(self):
        try:
            while True:
                self.q.get_nowait()
        except queue.Empty:
            pass

    def mute(self):
        self.muted.set()

    def unmute(self):
        time.sleep(0.2)
        self.flush()
        self.muted.clear()

    def _read(self, timeout=None):
        return self.q.get(timeout=timeout)

    @staticmethod
    def _rms(x):
        return float(np.sqrt(np.mean(x.astype(np.float32) ** 2))) + 1e-6

    def _calibrate(self):
        vals = []
        end = time.time() + 1.0
        while time.time() < end:
            try:
                vals.append(self._rms(self._read(0.5)))
            except queue.Empty:
                break
        if vals:
            self.noise = max(80.0, float(np.median(vals)))
        if max(vals or [0]) < 1.0:
            print("ВНИМАНИЕ: микрофон молчит. Разрешите доступ: Настройки → Конфиденциальность → Микрофон → Терминал.")

    def _threshold(self):
        return max(self.noise * 2.8, 300.0)

    def _is_speech(self, f, r):
        """Silero VAD with hysteresis: harder to start, easier to keep going,
        so soft endings ("...пожалуйста") are not cut off mid-word."""
        on = float(self.cfg.get("vad_threshold", 0.5))
        off = float(self.cfg.get("vad_threshold_keep", max(0.2, on - 0.15)))
        if self.vad is not None:
            try:
                p = self.vad.predict(f, frame_size=640)
                thr = off if getattr(self, "_talking", False) else on
                self._talking = r > 60 and p >= thr
                return self._talking
            except Exception:
                pass
        return r > self._threshold()

    # --- ожидание имени
    WAKE_FORMS = ("alfred", "alford", "alfredo", "alfread", "alphred", "olfred", "elfred", "альфред")

    def match_wake(self, text):
        """Есть ли «Alfred» в начале фразы. Возвращает остаток фразы ('' если только имя) или None."""
        import difflib
        words = re.findall(r"[\wʻ‘’'-]+", (text or "").lower())
        extra = [w.lower() for w in self.cfg.get("wake_words_fallback", [])]
        forms = set(self.WAKE_FORMS) | set(extra)
        orig = re.findall(r"\S+", text or "")
        for i, w in enumerate(words[:3]):
            if w in ("эй", "хэй", "hey", "хей", "ну", "слушай", "ой") and i < 2:
                continue
            if w in forms or max(difflib.SequenceMatcher(None, w, f).ratio() for f in ("alfred",)) >= 0.78:
                rest = " ".join(orig[i + 1:]).strip(" ,.!?-—")
                return rest
        return None

    def wait_for_wake(self):
        """Ждёт «Hey Alfred» (быстрая нейросеть) или просто «Alfred» в начале фразы (распознавание речи).
        Возвращает команду, сказанную в той же фразе, или None."""
        by_name = bool(self.cfg.get("wake_by_name", True)) and self.vad is not None
        thr = float(self.cfg.get("wake_threshold", 0.5))
        if self.oww is not None:
            self.oww.reset()
        if self.vad is not None:
            try:
                self.vad.reset_states()
                self._talking = False
            except Exception:
                pass
        pre = collections.deque(maxlen=8)  # 640 ms pre-roll
        seg, in_speech, quiet = [], False, 0.0
        max_seg = float(self.cfg.get("wake_max_phrase_seconds", 12))
        while True:
            f = self._read()
            if self.active_fn and not self.active_fn():
                seg, in_speech = [], False
                continue
            r = self._rms(f)
            if getattr(self, "summon_fn", None) and self.summon_fn():
                self.last_wake = "click"
                return None
            if self.oww is not None:
                scores = self.oww.predict(f)
                if scores and max(scores.values()) >= thr:
                    self.oww.reset()
                    self.last_wake = "hey"
                    return None
            if not by_name:
                if self.oww is None:
                    break
                continue
            speech = self._is_speech(f, r)
            if not in_speech:
                pre.append(f)
                if speech:
                    in_speech, quiet = True, 0.0
                    seg = list(pre)
                else:
                    self.noise = 0.995 * self.noise + 0.005 * r
                continue
            seg.append(f)
            quiet = 0.0 if speech else quiet + BLOCK_SEC
            dur = len(seg) * BLOCK_SEC
            if quiet >= 0.6 or dur >= max_seg:
                audio = np.concatenate(seg)
                seg, in_speech = [], False
                pre.clear()
                if dur < 0.35 or dur >= max_seg:
                    continue
                head = int(SR * float(self.cfg.get("wake_head_seconds", 2.5)))
                if len(audio) > head * 1.3:  # idle diet: "Alfred" is at the start, so check only the head of long side-talk
                    htext, _ = self.stt.transcribe(audio[:head])
                    if is_hallucination(htext) or self.match_wake(htext) is None:
                        continue
                text, _ = self.stt.transcribe(audio)
                if is_hallucination(text):
                    continue
                rest = self.match_wake(text)
                if rest is not None:
                    if self.oww is not None:
                        self.oww.reset()
                    self.last_wake = "name"
                    self.last_wake_text = text
                    return rest or None
        # запасной режим без нейросетей
        while True:
            audio = self.record_utterance(start_timeout=None, max_len=8)
            if audio is None or (self.active_fn and not self.active_fn()):
                continue
            text, _ = self.stt.transcribe(audio)
            rest = self.match_wake(text)
            if rest is not None:
                return rest or None

    def inject(self, text):
        """Подставить «сказанное» без голоса: 👍 → «да», кивок → «да», ладонь → «стоп»."""
        self._inject = text

    def _take_inject(self):
        t, self._inject = self._inject, None
        return t

    # --- запись фразы
    def record_utterance(self, start_timeout=5.0, max_len=None, silence=None):
        max_len = max_len or float(self.cfg.get("max_utterance_seconds", 20))
        silence = silence or float(self.cfg.get("silence_seconds", 0.9))
        pre = collections.deque(maxlen=8)
        frames, started = [], False
        if self.vad is not None:
            try:
                self.vad.reset_states()
                self._talking = False
            except Exception:
                pass
        waited = 0.0
        quiet = 0.0
        total = 0.0
        self.pre_text = None
        early = None           # распознавание «на лету», пока сэр молчит
        early_at = float(self.cfg.get("early_stt_seconds", 0.3))
        need = silence
        long_pause = float(self.cfg.get("unfinished_silence_seconds", 1.4))
        while True:
            if self._inject or (getattr(self, "abort_fn", None) and self.abort_fn()):
                return None
            try:
                f = self._read(timeout=1.0)
            except queue.Empty:
                if start_timeout is not None and not started:
                    waited += 1.0
                    if waited > start_timeout:
                        return None
                continue
            r = self._rms(f)
            speech = self._is_speech(f, r)
            if not started:
                pre.append(f)
                waited += BLOCK_SEC
                if speech:
                    started = True
                    frames.extend(pre)
                elif start_timeout is not None and waited > start_timeout:
                    return None
                else:
                    self.noise = 0.97 * self.noise + 0.03 * r
                continue
            frames.append(f)
            total += BLOCK_SEC
            quiet = 0.0 if speech else quiet + BLOCK_SEC
            if speech:
                if early is not None:
                    early = None  # сэр продолжил говорить
                need = silence
            elif early is None and quiet >= early_at and total >= 0.5 and self.cfg.get("smart_endpoint", True):
                if not getattr(self, "_early_busy", None) or not self._early_busy.is_alive():
                    snap = np.concatenate(frames)
                    early = {"audio": snap, "res": None}

                    def job(e=early):
                        try:
                            e["res"] = self.stt.transcribe(e["audio"])
                        except Exception:
                            e["res"] = ("", None)
                    self._early_busy = threading.Thread(target=job, daemon=True)
                    self._early_busy.start()
                    early["th"] = self._early_busy
            if early is not None and early["res"] is not None:
                if looks_complete(early["res"][0]):
                    break  # договорил — не ждём остаток паузы
                need = max(silence, long_pause)  # фраза оборвалась на «и», «в», «открой»… — ждём дольше
            if quiet >= need or total >= max_len:
                break
        if early is not None:
            early["th"].join(8)
            if early["res"] is not None:
                if len(early["audio"]) < SR * 0.35:
                    return None
                self.pre_text = early["res"]
                return early["audio"]
        audio = np.concatenate(frames)
        if len(audio) < SR * 0.35:
            return None
        return audio

    def record_ptt(self, held_fn, max_len=45.0, min_after_release=0.15, on_partial=None, partial_every=0.6):
        """Push-to-talk: record while held_fn() is True (no wake word, no VAD endpointing). Returns text ('' if nothing).
        on_partial(text) is called every ~partial_every s with live words (fast pass on the growing buffer).
        Final transcript: normally the full pass over the whole recording. Shortcut: when the last live pass already
        covered everything up to the silence before the key was released (recording <= 8 s, language known), its text
        is reused, which saves the ~1 s final decode."""
        self.flush()
        frames, t0 = [], time.time()
        stop = threading.Event()
        best = {}
        flight = {"quiet": False}
        worker = None
        if on_partial:
            def live():
                last_n, last_text, last_quiet = 0, "", False
                while not stop.wait(0.05):
                    snap = list(frames)
                    n = len(snap)
                    if n * BLOCK_SEC < 0.7 or n == last_n:
                        continue
                    audio = np.concatenate(snap)
                    peak = float(np.abs(audio).max())
                    if peak < 400 or float(np.abs(audio[-SR * 2:]).max()) < 400:  # silence so far: nothing to show
                        last_n = n
                        continue
                    quiet = float(np.abs(audio[-int(SR * 0.3):]).max()) < 0.12 * peak  # speaker paused / finished
                    if quiet:
                        if last_quiet:
                            continue  # last pass already covered the end of speech: keep the model free for the final
                    elif n - last_n < 4:
                        continue  # need ~0.3 s of new audio
                    t1 = time.time()
                    last_n, last_quiet = n, quiet
                    flight["quiet"] = quiet
                    text, lang = self.stt.transcribe_partial(audio)
                    flight["quiet"] = False
                    self.last_partial_ms = round((time.time() - t1) * 1000)
                    if text:
                        best.update(text=text, lang=lang, n=n)
                    if stop.is_set():
                        break
                    if text and text != last_text and not is_hallucination(text):
                        last_text = text
                        try:
                            on_partial(text)
                        except Exception:
                            pass
                    if not quiet:
                        stop.wait(max(0.1, partial_every - (time.time() - t1)))
            worker = threading.Thread(target=live, daemon=True)
            worker.start()
        while time.time() - t0 < max_len:
            try:
                frames.append(self._read(timeout=0.04))
            except queue.Empty:
                pass
            if not held_fn() and time.time() - t0 > 0.25:
                break
        stop.set()
        try:  # tail: whatever is already queued
            while True:
                frames.append(self.q.get_nowait())
        except queue.Empty:
            pass
        self.last_info = {"ptt": True}
        if not frames:
            return ""
        audio = np.concatenate(frames)
        if len(audio) < SR * 0.3:
            return ""
        self.last_info["sec"] = round(len(audio) / SR, 1)
        self.last_info["peak"] = round(float(np.abs(audio).max()))
        t1 = time.time()
        if worker:
            if flight["quiet"]:
                worker.join(1.0)  # an in-flight pass over the finished sentence is about to give us the answer
            n = best.get("n", 0)
            tail = np.concatenate(frames[n:]) if n and len(frames) > n else np.zeros(0, dtype=np.int16)
            if (best.get("text") and best.get("lang") in getattr(self.stt, "allowed", ()) and len(audio) <= SR * 8
                    and len(tail) <= SR * 1.5 and (len(tail) == 0 or float(np.abs(tail).max()) < 0.15 * self.last_info["peak"])):
                text, lang = best["text"], best["lang"]
                self.last_info.update(stt=round(time.time() - t1, 2), reused=True, raw=text, lang=lang)
                return "" if is_hallucination(text) else text
        text, lang = self.stt.transcribe(audio)
        self.last_info["stt"] = round(time.time() - t1, 2)
        self.last_info["raw"], self.last_info["lang"] = text, lang
        return "" if is_hallucination(text) else text

    def listen_text(self, start_timeout=6.0):
        self.last_info = {"noise": round(self.noise), "thr": round(self._threshold())}
        inj = self._take_inject()
        if inj:
            self.last_info["inject"] = inj
            return inj
        audio = self.record_utterance(start_timeout=start_timeout)
        inj = self._take_inject()
        if inj:
            self.last_info["inject"] = inj
            return inj
        if audio is None:
            self.last_info["audio"] = "none"
            return ""
        self.last_info["sec"] = round(len(audio) / SR, 1)
        self.last_info["peak"] = round(float(np.abs(audio).max()))
        try:
            import wave
            path = self.cfg.get("_debug_wav")
            if path:
                with wave.open(path, "wb") as w:
                    w.setnchannels(1)
                    w.setsampwidth(2)
                    w.setframerate(SR)
                    w.writeframes(audio.astype(np.int16).tobytes())
                os.chmod(path, 0o666)
        except Exception as e:
            self.last_info["wav_err"] = str(e)[:80]
        t0 = time.time()
        pre = getattr(self, "pre_text", None)
        text, lang = pre if pre else self.stt.transcribe(audio)
        self.last_info["stt"] = round(time.time() - t0, 2)
        self.last_info["early"] = bool(pre)
        self.last_info["raw"] = text
        self.last_info["lang"] = lang
        if not text.strip() and self.stt.lang is None:
            text, lang = self.stt._once(audio.astype(np.float32) / 32768.0, "ru")[:2]
            self.last_info["raw_ru"] = text
        return "" if is_hallucination(text) else text


# ---------- better speech: text normalization + local / premium voices ----------
_ABBR = {"AI": "эй-ай", "iOS": "ай-о-эс", "macOS": "мак-о-эс", "USB": "ю-эс-би", "Wi-Fi": "вай-фай",
         "OK": "окей"}


def speakable(text: str) -> str:
    """Numbers, times, percents and abbreviations as they are spoken, so the voice never says 'эй и'."""
    t = text
    if not re.search(r"[а-яё]", t, re.I):  # English / Uzbek-Latin: the English voice reads numbers itself
        return re.sub(r"\s{2,}", " ", t).strip()
    for k, v in _ABBR.items():
        t = re.sub(rf"(?<!\w){re.escape(k)}(?!\w)", v, t)
    try:
        from num2words import num2words
        t = re.sub(r"\b(\d{1,2}):(\d{2})\b",
                   lambda m: f"{num2words(int(m[1]), lang='ru')} {num2words(int(m[2]), lang='ru')}"
                   if m[2] != "00" else f"{num2words(int(m[1]), lang='ru')} ноль ноль", t)
        t = re.sub(r"(\d+(?:[.,]\d+)?)\s?%", lambda m: m[1] + " процентов", t)
        t = re.sub(r"\d+(?:[.,]\d+)?", lambda m: num2words(float(m[0].replace(",", ".")) if re.search(r"[.,]", m[0])
                                                            else int(m[0]), lang="ru"), t)
    except Exception:
        pass
    return re.sub(r"\s{2,}", " ", t).strip()


_KOKORO = {}


GEMINI_STYLE = {
    "ru": "Говори как Alfred: спокойный, учтивый ИИ-дворецкий с лёгкой иронией. Тёплый низкий голос, "
          "естественный темп, живые паузы между мыслями, без спешки. Скажи: ",
    "en": "Speak as Alfred: a calm, polite AI butler with dry British wit. Warm, low voice, natural pace, "
          "living pauses between thoughts, unhurried. Say: ",
}


def gemini_key():
    k = os.environ.get("GEMINI_API_KEY", "").strip()
    if k:
        return k
    try:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "gemini_key")) as f:
            return f.read().strip()
    except OSError:
        return ""


def _gemini(text, cfg, lang="ru"):
    """Google Gemini voice (natural pauses and tone). Needs a free key in data/gemini_key. Returns a .wav path."""
    import base64
    import json as _json
    import urllib.request
    import wave
    key = gemini_key()
    if not key:
        raise RuntimeError("no Gemini key (run 'Set Gemini key.command')")
    model = cfg.get("gemini_tts_model", "gemini-2.5-flash-preview-tts")
    body = {"contents": [{"parts": [{"text": GEMINI_STYLE.get(lang, GEMINI_STYLE["en"]) + text}]}],
            "generationConfig": {"responseModalities": ["AUDIO"],
                                 "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": cfg.get("gemini_voice", "Charon")}}}}}
    req = urllib.request.Request(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                                 data=_json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "x-goog-api-key": key})
    with urllib.request.urlopen(req, timeout=float(cfg.get("gemini_timeout", 12))) as r:
        j = _json.loads(r.read())
    part = j["candidates"][0]["content"]["parts"][0]["inlineData"]
    pcm = base64.b64decode(part["data"])
    rate = 24000
    m = re.search(r"rate=(\d+)", part.get("mimeType", ""))
    if m:
        rate = int(m.group(1))
    fd, path = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return path


_PIPER = {"lock": __import__("threading").Lock()}


def _piper(text, cfg):
    """Local Russian voice (Piper ONNX: plain model data, runs on the Mac, ~0.2 s per sentence)."""
    import wave
    name = cfg.get("piper_voice_ru", "ru_RU-dmitri-medium")
    with _PIPER["lock"]:
        v = _PIPER.get(name)
        if v is None:
            from piper import PiperVoice
            v = _PIPER[name] = PiperVoice.load(os.path.join(os.path.dirname(os.path.abspath(__file__)), "models", "piper", name + ".onnx"))
        fd, path = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        with wave.open(path, "wb") as w:
            v.synthesize_wav(text, w)
    return path


def _kokoro(text, cfg):
    """Local British voice (Kokoro-82M, ONNX int8): offline, free, ~0.3 s per sentence on M1."""
    import wave
    if "m" not in _KOKORO:
        from kokoro_onnx import Kokoro
        import onnxruntime as ort
        d = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models", "kokoro")
        so = ort.SessionOptions()
        so.intra_op_num_threads = int(cfg.get("kokoro_threads", 4))  # M1: 4 performance cores; more threads = contention
        so.inter_op_num_threads = 1
        so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        sess = ort.InferenceSession(os.path.join(d, "kokoro-v1.0.int8.onnx"), so, providers=["CPUExecutionProvider"])
        _KOKORO["m"] = Kokoro.from_session(sess, os.path.join(d, "voices-v1.0.bin"))
    _KOKORO.setdefault("lock", threading.Lock())
    with _KOKORO["lock"]:  # one sentence at a time: parallel synthesis made every sentence 3 s slower
        samples, sr = _KOKORO["m"].create(text, voice=cfg.get("kokoro_voice", "bm_george"),
                                          speed=float(cfg.get("kokoro_speed", 1.05)), lang=cfg.get("kokoro_lang", "en-gb"))
    pcm = (np.asarray(samples) * 32767).clip(-32768, 32767).astype(np.int16)
    fd, path = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())
    return path


_KOKORO_ID = re.compile(r"^[ab][mf]_[a-z]+$")
_EDGE_ID = re.compile(r"^[a-z]{2}-[A-Z]{2}-\w+Neural$")


def voice_kind(vid):
    """kokoro (local, bm_george) / edge (en-GB-RyanNeural) / say (macOS voice name)."""
    vid = str(vid or "")
    if _KOKORO_ID.match(vid):
        return "kokoro"
    if _EDGE_ID.match(vid):
        return "edge"
    return "say"


def apply_voice(cfg, vid):
    """Switch the live TTS voice in cfg (shared with Mouth, so it works at once). Returns the kind."""
    kind = voice_kind(vid)
    if kind == "kokoro":
        cfg.update(tts_engine="kokoro", kokoro_voice=vid, kokoro_lang="en-gb" if vid[0] == "b" else "en-us")
    elif kind == "edge":
        if vid.startswith("ru-"):
            cfg["voice_ru"] = vid
        elif vid.startswith("uz-"):
            cfg["voice_uz"] = vid
        else:
            cfg.update(tts_engine="edge", voice_en=vid)
    else:
        cfg.update(tts_engine="say", fallback_say_voices=[vid])
    cfg["voice"] = vid
    return kind


def synth_voice_file(text, vid, cfg):
    """Synthesize `text` with voice `vid` to a temp file (no playback, no shared state). Returns the path."""
    kind = voice_kind(vid)
    if kind == "kokoro":
        c = dict(cfg)
        c.update(kokoro_voice=vid, kokoro_lang="en-gb" if vid[0] == "b" else "en-us")
        return _kokoro(text, c)
    if kind == "edge":
        import edge_tts
        fd, path = tempfile.mkstemp(suffix=".mp3")
        os.close(fd)
        asyncio.run(asyncio.wait_for(edge_tts.Communicate(text, vid).save(path), timeout=float(cfg.get("tts_timeout", 9)) + 6))
        if os.path.getsize(path) == 0:
            raise RuntimeError("empty voice reply")
        return path
    fd, path = tempfile.mkstemp(suffix=".aiff")
    os.close(fd)
    subprocess.run(["say", "-v", vid, "-o", path, text], timeout=60, check=True)
    return path


_SILERO = {}


def _silero(text, cfg):
    """Local Russian voice (Silero v5): offline, ~0.2 s per sentence on M1, proper stress and ё."""
    import torch
    import wave
    if "m" not in _SILERO:
        torch.set_num_threads(4)
        last = None
        for name in (cfg.get("silero_model", "v5_ru"), "v4_ru"):  # newest first, v4 as a safe fallback
            try:
                m, _ = torch.hub.load("snakers4/silero-models", "silero_tts", language="ru",
                                      speaker=name, trust_repo=True)
                _SILERO["m"] = m
                break
            except Exception as e:
                last = e
        if "m" not in _SILERO:
            raise RuntimeError(f"silero: {last}")
    sr = 48000
    audio = _SILERO["m"].apply_tts(text=text, speaker=cfg.get("silero_speaker", "aidar"),
                                   sample_rate=sr, put_accent=True, put_yo=True)
    pcm = (audio.numpy() * 32767).clip(-32768, 32767).astype(np.int16)
    fd, path = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())
    return path


class Mouth:
    """Голос. say(barge=True) — можно перебить словом «Alfred»."""

    def __init__(self, cfg, ear=None, cache_dir=None, active_fn=None):
        self.cfg = cfg
        self.ear = ear
        self.active_fn = active_fn
        self.cache_dir = cache_dir
        self.lock = threading.Lock()
        self._say_voice = None
        # потоковая речь: ответ звучит по предложениям, пока мозг ещё дописывает
        self._sq, self._pq = queue.Queue(), queue.Queue()
        self._sgen, self._spending, self._scnt = 0, 0, threading.Lock()
        self._cur_proc = None
        self.last_play_start = 0.0
        from concurrent.futures import ThreadPoolExecutor
        self._pool = ThreadPoolExecutor(max_workers=3)  # фразы озвучиваются параллельно, звучат по порядку
        self._abort = False
        threading.Thread(target=self._stream_play, daemon=True).start()

    # ---------- потоковая речь
    def _sdone(self):
        with self._scnt:
            self._spending = max(0, self._spending - 1)

    def stream(self, text):
        """Поставить фразу в очередь речи (порядок сохраняется, первая звучит сразу)."""
        if silent.is_on():
            silent.show(text)
            return
        text = clean_for_speech(text)
        if not text or (self.active_fn and not self.active_fn()):
            return
        with self._scnt:
            self._spending += 1
        self._pq.put((self._sgen, self._pool.submit(self._synth, text)))

    def stream_busy(self):
        return self._spending > 0

    def stream_stop(self):
        """Оборвать потоковую речь (сэр перебил)."""
        self._sgen += 1
        p = self._cur_proc
        if p is not None and p.poll() is None:
            try:
                p.terminate()
            except Exception:
                pass

    def is_speaking(self):
        p = self._cur_proc
        return (p is not None and p.poll() is None) or self.stream_busy()

    def set_voice(self, vid):
        """Live voice change: next sentence already uses it."""
        kind = apply_voice(self.cfg, vid)
        self._say_voice = None
        return kind

    def preview_voice(self, vid, text=None):
        """Speak a short sample in voice `vid` without changing the current voice. Silent mode: does nothing."""
        if silent.is_on():
            return False
        if not text:
            text = "Здравствуйте, я Alfred." if str(vid).startswith("ru-") else "Good day. Alfred, at your service."
        path = synth_voice_file(text, vid, self.cfg)
        with self.lock:
            try:
                self._play(path)
            finally:
                try:
                    os.remove(path)
                except OSError:
                    pass
        return True

    def stop_all(self):
        """Замолчать немедленно (жест «ладонь»)."""
        self._abort = True
        self.stream_stop()

    def _stream_play(self):
        while True:
            gen, fut = self._pq.get()
            try:
                path = fut.result(timeout=60)
            except Exception as e:
                print("(не смог озвучить кусок):", e)
                self._sdone()
                continue
            try:
                if gen == self._sgen:
                    with self.lock:
                        if gen == self._sgen:
                            self._play(path)
            finally:
                try:
                    os.remove(path)
                except OSError:
                    pass
                self._sdone()

    def _fallback_voice(self):
        if self._say_voice is None:
            self._say_voice = ""
            try:
                out = subprocess.run(["say", "-v", "?"], capture_output=True, text=True, timeout=10).stdout
                for v in self.cfg.get("fallback_say_voices", ["Yuri", "Milena"]):
                    if re.search(rf"^{re.escape(v)}\b", out, re.M):
                        self._say_voice = v
                        break
            except Exception:
                pass
        return self._say_voice

    def _rate(self):
        import voice_fx
        base = self.cfg.get("voice_rate", "+0%").strip().replace("%", "")
        try:
            val = int(base)
        except ValueError:
            val = 0
        val += voice_fx.rate_boost(self.cfg.get("voice_fx") or "")
        return f"{val:+d}%"

    def _synth(self, text, voice=None, fx="__cfg__"):
        """Возвращает путь к аудиофайлу с фразой (с эффектом голоса, если он включён)."""
        import voice_fx
        text = speakable(text)
        lang = detect_lang(text)
        engine = self.cfg.get("tts_engine", "edge")
        if engine == "say" and not voice and lang == "en" and self.cfg.get("fallback_say_voices"):
            try:
                path = synth_voice_file(text, self.cfg["fallback_say_voices"][0], self.cfg)
                fx2 = self.cfg.get("voice_fx") if fx == "__cfg__" else fx
                return voice_fx.apply(path, fx2) if fx2 else path
            except Exception as e:
                print("(say voice unavailable, using edge):", str(e)[:120])
        if engine == "kokoro" and not voice and lang == "en":
            try:
                t0k = time.time()
                path = _kokoro(text, self.cfg)
                cb = getattr(self, "on_tts", None)
                if cb:
                    cb(round(time.time() - t0k, 2), True, len(text))
                fx2 = self.cfg.get("voice_fx") if fx == "__cfg__" else fx
                return voice_fx.apply(path, fx2) if fx2 else path
            except Exception as e:
                print("(kokoro unavailable, using edge):", str(e)[:120])
        gem_langs = self.cfg.get("gemini_langs", ["ru"])
        if not voice and lang in gem_langs and self.cfg.get("tts_ru_engine", "gemini") == "gemini" and gemini_key():
            try:
                t0g = time.time()
                path = _gemini(text, self.cfg, lang)
                cb = getattr(self, "on_tts", None)
                if cb:
                    cb(round(time.time() - t0g, 2), True, len(text))
                fx2 = self.cfg.get("voice_fx") if fx == "__cfg__" else fx
                return voice_fx.apply(path, fx2) if fx2 else path
            except Exception as e:
                print("(gemini voice unavailable, using backup):", str(e)[:160])
        if lang == "ru" and not voice and self.cfg.get("tts_ru_engine", "gemini") == "piper":
            try:
                path = _piper(text, self.cfg)
                fx2 = self.cfg.get("voice_fx") if fx == "__cfg__" else fx
                return voice_fx.apply(path, fx2) if fx2 else path
            except Exception as e:
                print("(piper unavailable, using edge):", str(e)[:120])
        if engine == "silero" and not voice and lang != "uz":
            try:
                path = _silero(text, self.cfg)
                fx2 = self.cfg.get("voice_fx") if fx == "__cfg__" else fx
                return voice_fx.apply(path, fx2) if fx2 else path
            except Exception as e:
                print(f"({engine} недоступен, беру edge):", str(e)[:120])
        single = self.cfg.get("voice_single")
        if not voice and single:
            # один голос на все языки (сэр не любит, когда голос меняется)
            voice = single
            if lang == "uz" and voice.startswith("ru-"):
                text = uz_to_cyr(text)
        voice = voice or self.cfg.get({"uz": "voice_uz", "en": "voice_en"}.get(lang, "voice_ru"), "ru-RU-DmitryNeural")
        fx = self.cfg.get("voice_fx") if fx == "__cfg__" else fx
        rate = self._rate() if fx else self.cfg.get("voice_rate", "+0%")
        t0 = time.time()
        # частые короткие фразы («Готово, сэр.») берём из кэша — звучат мгновенно
        import hashlib
        import shutil
        cache_dir = os.path.join(self.cache_dir or tempfile.gettempdir(), "tts")
        key = hashlib.sha1(f"{voice}|{rate}|{fx}|{text}".encode()).hexdigest()[:20]
        cached = os.path.join(cache_dir, key + ".mp3")
        if len(text) <= 90 and os.path.exists(cached):
            fd, path = tempfile.mkstemp(suffix=".mp3")
            os.close(fd)
            shutil.copyfile(cached, path)
            return path
        path, ok, err = None, False, ""
        import edge_tts
        for attempt in range(2):  # онлайн-голос иногда не отвечает с первого раза — пробуем ещё раз, а не меняем голос
            try:
                fd, path = tempfile.mkstemp(suffix=".mp3")
                os.close(fd)

                async def _go(pth=path):
                    await asyncio.wait_for(edge_tts.Communicate(text, voice, rate=rate).save(pth),
                                           timeout=float(self.cfg.get("tts_timeout", 9)))
                asyncio.run(_go())
                if os.path.getsize(path) == 0:
                    raise RuntimeError("пустой ответ голоса")
                ok = True
                break
            except Exception as e:
                err = str(e)[:120]
                try:
                    os.remove(path)
                except OSError:
                    pass
        if not ok:
            print("(онлайн-голос недоступен, говорю системным):", err)
            fd, path = tempfile.mkstemp(suffix=".aiff")
            os.close(fd)
            v = self._fallback_voice()
            subprocess.run(["say"] + (["-v", v] if v else []) + ["-o", path, text], timeout=120)
        elif len(text) <= 90:
            try:
                os.makedirs(cache_dir, exist_ok=True)
                shutil.copyfile(path, cached)
                os.chmod(cached, 0o666)
                files = sorted(os.listdir(cache_dir), key=lambda f: os.path.getmtime(os.path.join(cache_dir, f)))
                for f in files[:-400]:
                    os.remove(os.path.join(cache_dir, f))
            except Exception:
                pass
        cb = getattr(self, "on_tts", None)
        if cb:
            try:
                cb(round(time.time() - t0, 2), ok, len(text))
            except Exception:
                pass
        if fx:
            path = voice_fx.apply(path, fx)
        return path

    def _envelope(self, path):
        """Громкость фразы по 20 мс — чтобы голограмма двигала челюстью в такт."""
        import wave
        wav, tmp = path, None
        try:
            if not path.endswith(".wav"):
                fd, tmp = tempfile.mkstemp(suffix=".wav")
                os.close(fd)
                subprocess.run(["afconvert", "-f", "WAVE", "-d", "LEI16@16000", "-c", "1", path, tmp],
                               check=True, capture_output=True, timeout=15)
                wav = tmp
            with wave.open(wav, "rb") as w:
                sr, ch = w.getframerate(), w.getnchannels()
                x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32)
            if ch > 1:
                x = x.reshape(-1, ch).mean(axis=1)
            hop = max(1, sr // 50)
            n = len(x) // hop
            if n == 0:
                return []
            e = np.sqrt((x[: n * hop].reshape(n, hop) ** 2).mean(axis=1))
            ref = np.percentile(e, 95) or 1.0
            return list(np.clip(np.sqrt(e / ref), 0, 1))
        except Exception:
            return []
        finally:
            if tmp and os.path.exists(tmp):
                os.remove(tmp)

    def level(self):
        env = getattr(self, "_env", None)
        if not env:
            return 0.0
        i = int((time.time() - self._env_t0) * 50)
        return float(env[i]) if 0 <= i < len(env) else 0.0

    def _play(self, path, barge=False):
        self._env = self._envelope(path)
        self._env_t0 = time.time()
        cb = getattr(self, "on_speak", None)
        if cb:
            cb(True)
        try:
            return self._play_inner(path, barge)
        finally:
            self._env = None
            if cb:
                cb(False)

    def _play_inner(self, path, barge=False):
        proc = subprocess.Popen(["afplay", path])
        self._cur_proc = proc
        self.last_play_start = time.time()
        interrupted = False
        ear = self.ear
        if barge and ear is not None and ear.oww is not None:
            ear.flush()
            ear.oww.reset()
            thr = float(self.cfg.get("barge_in_threshold", 0.6))
            while proc.poll() is None:
                try:
                    f = ear._read(timeout=0.2)
                except queue.Empty:
                    continue
                scores = ear.oww.predict(f)
                if scores and max(scores.values()) >= thr:
                    proc.terminate()
                    interrupted = True
                    break
            ear.oww.reset()
        proc.wait()
        return interrupted

    @staticmethod
    def split_sentences(text):
        """Режет ответ на куски: первый — короткий, чтобы голос начинался сразу."""
        parts = [p.strip() for p in re.split(r"(?<=[.!?…])\s+", text) if p.strip()]
        out = []
        for p in parts:
            if not out and len(p) > 90:
                m = re.search(r"^(.{20,90}?[,;:—])\s+", p)
                if m:
                    out.append(m.group(1))
                    p = p[m.end():]
            out.append(p)
        merged = []
        for p in out:
            if merged and len(merged[-1]) < 12:
                merged[-1] += " " + p
            else:
                merged.append(p)
        return merged

    def say(self, text, barge=False):
        """Говорит текст по предложениям: первое звучит, пока готовятся следующие.
        Возвращает True, если сэр перебил словом «Alfred»."""
        if silent.is_on():
            silent.show(text)
            return False
        text = clean_for_speech(text)
        if not text:
            return False
        if self.active_fn and not self.active_fn():
            return False
        chunks = self.split_sentences(text) or [text]
        with self.lock:
            use_barge = barge and self.ear is not None and self.ear.oww is not None
            if self.ear and not use_barge:
                self.ear.mute()
            ready = queue.Queue()
            stop = threading.Event()

            self._abort = False
            futs = [self._pool.submit(self._synth, c) for c in chunks]

            def producer():
                for fu in futs:
                    if stop.is_set():
                        break
                    try:
                        ready.put(fu.result(timeout=90))
                    except Exception as e:
                        print("(не смог озвучить кусок):", e)
                ready.put(None)

            threading.Thread(target=producer, daemon=True).start()
            interrupted = False
            files = []
            try:
                while True:
                    try:
                        path = ready.get(timeout=120)
                    except queue.Empty:
                        break
                    if path is None:
                        break
                    files.append(path)
                    if self._abort:
                        interrupted = True
                        break
                    if self._play(path, barge=use_barge) or self._abort:
                        interrupted = True
                        break
            finally:
                stop.set()

                def cleanup():
                    while True:
                        try:
                            pth = ready.get(timeout=30)
                        except queue.Empty:
                            break
                        if pth is None:
                            break
                        files.append(pth)
                    for f in files:
                        try:
                            os.remove(f)
                        except OSError:
                            pass

                threading.Thread(target=cleanup, daemon=True).start()
                if self.ear:
                    if use_barge:
                        self.ear.flush()
                    else:
                        self.ear.unmute()
            return interrupted

    def ack(self):
        """Мгновенный отклик на «Alfred»: заранее записанные фразы."""
        if silent.is_on():
            return
        import glob
        import random
        import shutil
        phrases = list(self.cfg.get("wake_acks") or [])
        try:  # add "sir" / "ma'am" / the name, or nothing, from the Address setting
            import address as _address
            import ui_bridge
            phrases = [_address.with_address(p, ui_bridge.get("address", "sir"), ui_bridge.get("name") or self.cfg.get("user_name", "")) for p in phrases]
        except Exception:
            pass
        if not phrases or not self.cache_dir:
            chime("Tink")
            return
        os.makedirs(self.cache_dir, exist_ok=True)
        i = random.randrange(len(phrases))
        import zlib
        vname = (self.cfg.get("voice_single") or self.cfg.get("voice_ru") or "ru").split("-")[-1]
        key = (f"ack_{i}_{os.getuid()}_{self.cfg.get('voice_fx') or 'plain'}_{vname}_"
               f"{zlib.crc32(phrases[i].encode()) % 100000}")
        found = glob.glob(os.path.join(self.cache_dir, key + ".*"))
        with self.lock:
            if self.ear:
                self.ear.mute()
            try:
                if found:
                    cached = found[0]
                else:
                    tmp = self._synth(phrases[i])
                    cached = os.path.join(self.cache_dir, key + os.path.splitext(tmp)[1])
                    shutil.move(tmp, cached)
                    os.chmod(cached, 0o666)
                self._play(cached)
            except Exception:
                chime("Tink")
            finally:
                if self.ear:
                    self.ear.unmute()
