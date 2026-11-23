"""alfred-say «текст» — Alfred произносит фразу (для таймеров и напоминаний)."""
import json
import sys
from pathlib import Path

HOME = Path(__file__).resolve().parent
sys.path.insert(0, str(HOME))
import voice  # noqa: E402

cfg = json.loads((HOME / "config.json").read_text(encoding="utf-8"))
text = " ".join(sys.argv[1:]).strip()
if text:
    voice.chime("Glass")
    voice.Mouth(cfg).say(text)
