"""Выбор голоса Alfred на слух. Запуск:
$ALFRED_HOME/.venv/bin/python $ALFRED_HOME/voice_demo.py
"""
import json
import subprocess
import sys
from pathlib import Path

HOME = Path(__file__).resolve().parent
sys.path.insert(0, str(HOME))
import voice  # noqa: E402

cfg = json.loads((HOME / "config.json").read_text(encoding="utf-8"))
RU = "Добрый вечер, сэр. Все системы в норме. Чем могу помочь?"
EN = "Good evening, sir. All systems are online. How may I help?"
VARIANTS = [
    ("Обычный голос (Дмитрий)", "ru-RU-DmitryNeural", None, RU),
    ("Голос ИИ: металлический отзвук и эхо", "ru-RU-DmitryNeural", "alfred", RU),
    ("Голос ИИ, ниже и глубже", "ru-RU-DmitryNeural", "alfred_deep", RU),
    ("Голос ИИ, больше «робота»", "ru-RU-DmitryNeural", "robot", RU),
    ("Британский английский (Ryan) + эффект ИИ", "en-GB-RyanNeural", "alfred", EN),
    ("Британский английский (Thomas) + эффект ИИ", "en-GB-ThomasNeural", "alfred", EN),
]

m = voice.Mouth(cfg)
for n, (name, v, fx, text) in enumerate(VARIANTS, 1):
    print(f"\n{n}. {name}")
    cfg["voice_fx"] = fx
    path = m._synth(text, voice=v, fx=fx)
    subprocess.run(["afplay", path])

choice = input("\nКакой вариант оставить? Введите номер (Enter — ничего не менять): ").strip()
if choice.isdigit() and 1 <= int(choice) <= len(VARIANTS):
    name, v, fx, _ = VARIANTS[int(choice) - 1]
    cfg = json.loads((HOME / "config.json").read_text(encoding="utf-8"))
    cfg["voice_fx"] = fx
    if v.startswith("en-"):
        cfg["voice_en"] = v
        print("Этим голосом Alfred будет говорить, когда отвечает по-английски (скажите ему: «отвечай по-английски»).")
    else:
        cfg["voice_ru"] = v
    (HOME / "config.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✓ Выбран: {name}. Перезапускаю Alfred…")
    subprocess.run(["pkill", "-f", "alfred.py"])
else:
    print("Голос не изменён.")
