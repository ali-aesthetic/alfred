"""Эффект «голос ИИ» в стиле фильмов: чуть ниже тон, металлический отзвук, лёгкое эхо комнаты.
Это обработка обычного голоса, а не копия чьего-то голоса."""
import os
import subprocess
import tempfile
import wave

import numpy as np

PRESETS = {
    # pitch < 1 — ниже и медленнее (скорость компенсируется в синтезе)
    "alfred":      {"pitch": 0.95, "chorus": 0.22, "reverb": 0.16, "ring": 0.0},
    "alfred_deep": {"pitch": 0.90, "chorus": 0.28, "reverb": 0.20, "ring": 0.0},
    "robot":       {"pitch": 0.97, "chorus": 0.30, "reverb": 0.12, "ring": 0.10},
}


def rate_boost(preset):
    p = PRESETS.get(preset)
    return 0 if not p else int(round((1 / p["pitch"] - 1) * 100))


def _read_wav(path):
    with wave.open(path, "rb") as w:
        sr, n, ch, sw = w.getframerate(), w.getnframes(), w.getnchannels(), w.getsampwidth()
        raw = w.readframes(n)
    x = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if ch > 1:
        x = x.reshape(-1, ch).mean(axis=1)
    return x, sr


def _write_wav(path, x, sr):
    y = np.clip(x, -1, 1)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((y * 32767).astype(np.int16).tobytes())


def process(x, sr, preset):
    p = PRESETS[preset]
    # 1. тон ниже: растягиваем сигнал
    idx = np.arange(0, len(x) - 1, p["pitch"])
    x = np.interp(idx, np.arange(len(x)), x).astype(np.float32)
    t = np.arange(len(x)) / sr
    # 2. металлический отзвук (короткий хорус с плавающей задержкой)
    d = sr * (0.0045 + 0.0015 * np.sin(2 * np.pi * 0.35 * t))
    y = np.interp(np.arange(len(x)) - d, np.arange(len(x)), x, left=0.0)
    out = x + p["chorus"] * y
    if p["ring"]:
        out = (1 - p["ring"]) * out + p["ring"] * out * np.sin(2 * np.pi * 55 * t)
    # 3. эхо комнаты: ранние отражения + короткий хвост
    n_ir = int(0.35 * sr)
    ir = np.zeros(n_ir, dtype=np.float32)
    ir[0] = 1.0
    for ms, g in ((19, 0.22), (31, 0.16), (47, 0.12), (67, 0.08)):
        ir[int(sr * ms / 1000)] += g
    rng = np.random.default_rng(7)
    tail = rng.standard_normal(n_ir).astype(np.float32) * np.exp(-np.arange(n_ir) / (0.07 * sr))
    ir += p["reverb"] * tail / (np.abs(tail).sum() / 40 + 1e-9)
    n = len(out) + n_ir
    nfft = 1 << (n - 1).bit_length()
    out = np.fft.irfft(np.fft.rfft(out, nfft) * np.fft.rfft(ir, nfft), nfft)[:n]
    # 4. убрать гул снизу
    try:
        from scipy.signal import butter, lfilter
        b, a = butter(2, 90 / (sr / 2), "highpass")
        out = lfilter(b, a, out)
    except Exception:
        pass
    peak = np.abs(out).max() or 1.0
    return (out / peak * 0.9).astype(np.float32)


def apply(src_path, preset):
    """Возвращает путь к WAV с эффектом (исходник удаляется) или исходный путь при ошибке."""
    if preset not in PRESETS:
        return src_path
    fd, wav_in = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    try:
        if src_path.endswith(".wav"):
            wav_in, cleanup = src_path, False
        else:
            subprocess.run(["afconvert", "-f", "WAVE", "-d", "LEI16@24000", "-c", "1", src_path, wav_in],
                           check=True, capture_output=True, timeout=30)
            cleanup = True
        x, sr = _read_wav(wav_in)
        fd, out = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        _write_wav(out, process(x, sr, preset), sr)
        if cleanup:
            os.remove(wav_in)
        if src_path != out and os.path.exists(src_path):
            os.remove(src_path)
        return out
    except Exception as e:
        print("(эффект голоса не применился):", e)
        return src_path
