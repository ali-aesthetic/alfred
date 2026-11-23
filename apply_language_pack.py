"""Apply an optional language pack to your config.json:   python apply_language_pack.py ru
English is the default. Packs live in languages/<code>.json and only add speech-recognition languages, voices and wake spellings."""
import json, sys
from pathlib import Path
from alfred_home import HOME

code = (sys.argv[1] if len(sys.argv) > 1 else "").strip()
pack = Path(__file__).resolve().parent / "languages" / f"{code}.json"
if not pack.exists():
    print("Available packs:", ", ".join(p.stem for p in (pack.parent).glob("*.json")) or "none"); sys.exit(1)
cfg_path = HOME / "config.json"
cfg = json.loads(cfg_path.read_text(encoding="utf-8")) if cfg_path.exists() else {}
cfg.update({k: v for k, v in json.loads(pack.read_text(encoding="utf-8")).items() if not k.startswith("_")})
cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(f"Language pack '{code}' applied to {cfg_path}. Restart Alfred.")
