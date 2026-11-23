"""Downloads Alfred's models once into ALFRED_HOME (ears, voice, wake-word helpers).

Usage:
    python setup_models.py            # human-readable lines
    python setup_models.py --json     # one JSON object per line, for the Mac app's progress bar
    python setup_models.py --only voice,ears,wake      # pick steps
    python setup_models.py --ru                         # also the optional Russian voice pack (Piper)

Progress lines (--json):
    {"step":"ears","label":"Ears (Whisper small)","pct":41.2,"done":197000000,"total":480000000,"eta":12.5,"state":"running"}
state = running | done | error.  Real bytes only: no fake percentages.
Everything is resumable: files that are already complete are skipped, partial downloads are restarted from the file.
"""
import argparse
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

from alfred_home import HOME

ap = argparse.ArgumentParser()
ap.add_argument("--json", action="store_true")
ap.add_argument("--only", default="")
ap.add_argument("--ru", action="store_true")
args = ap.parse_args()
ONLY = {s for s in args.only.split(",") if s}

os.environ.setdefault("HF_HOME", str(HOME / "models"))
CFG = {}
try:
    CFG = json.loads((HOME / "config.json").read_text(encoding="utf-8"))
except Exception:
    pass


class Progress:
    """Turns byte counts into one line per update (max ~4 per second)."""

    def __init__(self, step, label):
        self.step, self.label = step, label
        self.t0 = time.time()
        self.last = 0.0

    def emit(self, done, total, state="running", note=""):
        now = time.time()
        if state == "running" and now - self.last < 0.25:
            return
        self.last = now
        pct = (100.0 * done / total) if total else 0.0
        el = max(now - self.t0, 0.001)
        eta = ((total - done) / (done / el)) if (done and total and done < total) else None
        d = {"step": self.step, "label": self.label, "pct": round(pct, 1), "done": int(done), "total": int(total or 0),
             "eta": None if eta is None else round(eta, 1), "state": state, "note": note}
        if args.json:
            print(json.dumps(d), flush=True)
        else:
            mb = lambda b: f"{b / 1e6:.0f} MB"
            print(f"\r{self.label}: {pct:5.1f}%  {mb(done)} / {mb(total)}" + (f"  ~{eta:.0f}s left" if eta else "") + (f" {note}" if note else "") + ("\n" if state != "running" else ""), end="", flush=True)


def fetch(url, dest: Path, prog: Progress, base_done=0, grand_total=0):
    """Download one file with a real progress callback. Skips files that already look complete."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 1000:
        return dest.stat().st_size
    tmp = dest.with_suffix(dest.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": "alfred-setup"})
    with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as f:
        size = int(r.headers.get("Content-Length") or 0)
        got = 0
        while True:
            chunk = r.read(1 << 18)
            if not chunk:
                break
            f.write(chunk)
            got += len(chunk)
            prog.emit(base_done + got, grand_total or size)
    os.replace(tmp, dest)
    return got


def step_wake():
    """Small helper models openWakeWord always needs (features + voice-activity detector)."""
    import openwakeword
    p = Progress("wake", "Wake-word helpers")
    d = Path(openwakeword.__file__).parent / "resources" / "models"
    jobs = []
    for m in list(openwakeword.FEATURE_MODELS.values()) + list(openwakeword.VAD_MODELS.values()):
        u = m["download_url"]
        jobs += [u, u.replace(".tflite", ".onnx")]
    for i, u in enumerate(jobs):
        try:
            fetch(u, d / u.split("/")[-1], p)
        except Exception as e:  # tflite variants may not exist; onnx is what we use
            if u.endswith(".onnx"):
                raise
        p.emit(i + 1, len(jobs))
    wm = CFG.get("wake_model")
    if wm and not str(wm).endswith(".onnx") and "/" not in str(wm):  # a pretrained name (non-commercial licence!)
        from openwakeword.utils import download_models
        download_models(model_names=[str(wm)])
    p.emit(1, 1, "done")


def step_ears():
    from huggingface_hub import snapshot_download
    from tqdm.auto import tqdm
    p = Progress("ears", "Ears (Whisper small)")

    class Bar(tqdm):
        def update(self, n=1):
            r = super().update(n)
            if self.total and (self.unit or "") in ("B", "iB"):
                p.emit(self.n, self.total)
            return r

    model = CFG.get("mlx_whisper_model", "mlx-community/whisper-small-mlx")
    snapshot_download(model, tqdm_class=Bar)
    p.emit(1, 1, "done")


def step_voice():
    base = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/"
    d = HOME / "models" / "kokoro"
    files = ("kokoro-v1.0.int8.onnx", "voices-v1.0.bin")
    p = Progress("voice", "Voice (Kokoro, British)")
    done = 0
    est_total = 120_000_000
    for f in files:
        done += fetch(base + f, d / f, p, done, est_total)
    p.emit(done, done, "done")


def step_ru():
    p = Progress("ru", "Russian voice pack (Piper)")
    d = HOME / "models" / "piper"
    base = "https://huggingface.co/rhasspy/piper-voices/resolve/main/ru/ru_RU/dmitri/medium/"
    done = 0
    for f in ("ru_RU-dmitri-medium.onnx", "ru_RU-dmitri-medium.onnx.json"):
        done += fetch(base + f, d / f, p, done, 62_000_000)
    p.emit(done, done, "done")


STEPS = [("wake", step_wake), ("voice", step_voice), ("ears", step_ears)] + ([("ru", step_ru)] if args.ru else [])
failed = 0
for name, fn in STEPS:
    if ONLY and name not in ONLY:
        continue
    try:
        fn()
    except Exception as e:
        failed += 1
        d = {"step": name, "state": "error", "note": str(e)[:300]}
        print(json.dumps(d) if args.json else f"\n{name} failed: {e}", flush=True)
if not failed:
    print(json.dumps({"step": "all", "state": "done", "pct": 100}) if args.json else "Models ready.", flush=True)
sys.exit(1 if failed else 0)
