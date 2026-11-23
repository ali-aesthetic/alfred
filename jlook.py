"""jlook — снимок с камеры по просьбе сэра. Печатает путь к JPEG; его можно открыть инструментом Read.

  $ALFRED_HOME/.venv/bin/python $ALFRED_HOME/jlook.py
"""
import getpass
import sys
import time
from pathlib import Path

HOME = Path(__file__).resolve().parent
USER = getpass.getuser()
REQ = HOME / "data" / f"look_req-{USER}"
JPG = HOME / "data" / f"look-{USER}.jpg"


def main():
    t0 = time.time()
    old = JPG.stat().st_mtime if JPG.exists() else 0
    REQ.parent.mkdir(parents=True, exist_ok=True)
    REQ.write_text(str(t0))
    while time.time() - t0 < 6:
        if JPG.exists() and JPG.stat().st_mtime > old and not REQ.exists():
            print(JPG)
            return 0
        time.sleep(0.1)
    try:
        REQ.unlink()
    except OSError:
        pass
    print("Камера не ответила: она выключена или нет доступа (Настройки → Конфиденциальность → Камера → Терминал).",
          file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
