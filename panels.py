"""Панели голограммы: таблицы, графики, картинки, видео, списки и текст рядом с лицом Alfred.

Состояние хранится в data/panels-<пользователь>.json (список до 3 панелей).
Пишет его jshow.py (по просьбе мозга) и сам Alfred; голограмма следит за файлом.
"""
import getpass
import json
import os
import time
from pathlib import Path

HOME = Path(__file__).resolve().parent
MAX_PANELS = 3
TYPES = {"text", "list", "table", "chart", "image", "video", "stat"}


def path(user=None):
    return HOME / "data" / f"panels-{user or getpass.getuser()}.json"


def read(user=None):
    try:
        data = json.loads(path(user).read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def write(items, user=None):
    p = path(user)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(f".tmp{os.getpid()}")
    tmp.write_text(json.dumps(items[-MAX_PANELS:], ensure_ascii=False), encoding="utf-8")
    try:
        os.chmod(tmp, 0o666)
    except Exception:
        pass
    tmp.replace(p)


def push(specs, replace=False, user=None):
    """Добавляет панели (новые — внизу, ближе к лицу). Возвращает итоговый список."""
    if isinstance(specs, dict):
        specs = [specs]
    cur = [] if replace else read(user)
    now = time.time()
    for i, s in enumerate(specs):
        s = dict(s)
        s.setdefault("id", f"p{int(now * 1000)}{i}")
        if s.get("id") in {c.get("id") for c in cur}:
            cur = [c if c.get("id") != s["id"] else s for c in cur]
        else:
            cur.append(s)
    write(cur, user)
    return cur[-MAX_PANELS:]


def clear(user=None):
    if read(user):
        write([], user)
