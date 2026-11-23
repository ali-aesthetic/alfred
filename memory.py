"""Память Alfred: факты о сэре, уроки из ошибок, журнал и состояние."""
import json
import os
import threading
import time
from pathlib import Path


class Memory:
    def __init__(self, home: Path):
        self.dir = home / "data"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.facts_path = self.dir / "memory.json"
        self.lessons_path = self.dir / "lessons.md"
        self.lock = threading.Lock()
        self.facts = []
        if self.facts_path.exists():
            try:
                self.facts = json.loads(self.facts_path.read_text(encoding="utf-8"))
            except Exception:
                self.facts = []

    def _save(self):
        tmp = self.facts_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.facts, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.facts_path)

    def add(self, fact: str) -> str:
        fact = " ".join(str(fact).split())
        if not fact:
            return "Пустой факт, ничего не сохранено."
        with self.lock:
            low = fact.lower()
            for f in self.facts:
                if f["text"].lower() == low:
                    return "Это я уже помню."
            self.facts.append({"text": fact, "ts": int(time.time())})
            self.facts = self.facts[-300:]
            self._save()
        return "Запомнил."

    def forget(self, needle: str) -> str:
        needle = str(needle).lower().strip()
        if not needle:
            return "Не понял, что забыть."
        with self.lock:
            before = len(self.facts)
            self.facts = [f for f in self.facts if needle not in f["text"].lower()]
            removed = before - len(self.facts)
            self._save()
        return f"Забыл записей: {removed}." if removed else "Такого в памяти не нашёл."

    def as_text(self) -> str:
        if not self.facts:
            return "(пока ничего)"
        return "\n".join(f"- {f['text']}" for f in self.facts[-120:])

    def lessons(self) -> str:
        if self.lessons_path.exists():
            text = self.lessons_path.read_text(encoding="utf-8").strip()
            if text:
                return text
        return "(пока нет)"

    def set_lessons(self, text: str):
        lines = [l.rstrip() for l in text.strip().splitlines() if l.strip().startswith("-")]
        self.lessons_path.write_text("\n".join(lines[:20]) + "\n", encoding="utf-8")


class Log:
    """Журнал в формате JSON Lines: запросы, вызовы инструментов, ошибки, расход токенов."""

    def __init__(self, home: Path):
        self.path = home / "data" / "log.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()

    def add(self, kind: str, **fields):
        rec = {"ts": int(time.time()), "type": kind, **fields}
        with self.lock:
            if self.path.exists() and self.path.stat().st_size > 8_000_000:
                self.path.replace(self.path.with_suffix(".old.jsonl"))
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")

    def since(self, ts: float):
        out = []
        if not self.path.exists():
            return out
        with self.path.open(encoding="utf-8") as f:
            for line in f:
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                if rec.get("ts", 0) > ts:
                    out.append(rec)
        return out


class State:
    def __init__(self, home: Path):
        self.path = home / "data" / "state.json"
        self.data = {}
        if self.path.exists():
            try:
                self.data = json.loads(self.path.read_text(encoding="utf-8"))
            except Exception:
                self.data = {}

    def _reload(self):
        """Файл общий для обоих пользователей Mac — перечитываем, если его изменил другой процесс."""
        try:
            mt = self.path.stat().st_mtime
        except OSError:
            return
        if mt != getattr(self, "_mt", None):
            try:
                self.data = json.loads(self.path.read_text(encoding="utf-8"))
                self._mt = mt
            except Exception:
                pass

    def get(self, key, default=None):
        self._reload()
        return self.data.get(key, default)

    def set(self, key, value):
        self._reload()
        self.data[key] = value
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=1), encoding="utf-8")
        try:
            self._mt = self.path.stat().st_mtime
            os.chmod(self.path, 0o666)
        except OSError:
            pass
