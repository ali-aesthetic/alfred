"""Where Alfred lives. One setting: the ALFRED_HOME environment variable.

Default: ~/Library/Application Support/Alfred  (code, data/, models/, .venv/, bin/ all sit inside it).
"""
import os
from pathlib import Path


def _resolve() -> Path:
    env = os.environ.get("ALFRED_HOME")
    if env:
        return Path(env).expanduser().resolve()
    here = Path(__file__).resolve().parent
    # running from inside an installed home (has data/ or .venv/) -> use it
    if (here / ".venv").exists() or (here / "data").exists():
        return here
    return Path.home() / "Library" / "Application Support" / "Alfred"


HOME: Path = _resolve()
HOME_STR: str = str(HOME)
DATA: Path = HOME / "data"
BIN: Path = HOME / "bin"
PY: str = str(HOME / ".venv" / "bin" / "python")
CTL: str = str(BIN / "alfred-ctl")
