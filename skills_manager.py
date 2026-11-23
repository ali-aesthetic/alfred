"""Навыки, которые Alfred пишет себе сам (с разрешения сэра).

Каждый навык — файл skills/<имя>.py с константами DESCRIPTION, SCHEMA
и функцией run(**kwargs) -> str. Навык запускается в отдельном процессе,
поэтому ошибка в нём не уронит Alfred.
"""
import ast
import json
import re
import subprocess
import sys
from pathlib import Path

NAME_RE = re.compile(r"^[a-z][a-z0-9_]{1,40}$")

RUNNER = (
    "import json,sys,importlib.util\n"
    "s=importlib.util.spec_from_file_location('skill',sys.argv[1])\n"
    "m=importlib.util.module_from_spec(s);s.loader.exec_module(m)\n"
    "r=m.run(**json.loads(sys.argv[2]))\n"
    "print(r if r is not None else 'готово')\n"
)


class Skills:
    def __init__(self, home: Path):
        self.dir = home / "skills"
        self.dir.mkdir(parents=True, exist_ok=True)

    def _read_meta(self, path: Path):
        """Достаёт DESCRIPTION и SCHEMA, не выполняя код навыка."""
        tree = ast.parse(path.read_text(encoding="utf-8"))
        meta = {}
        for node in tree.body:
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                if node.targets[0].id in ("DESCRIPTION", "SCHEMA"):
                    meta[node.targets[0].id] = ast.literal_eval(node.value)
        has_run = any(isinstance(n, ast.FunctionDef) and n.name == "run" for n in tree.body)
        if "DESCRIPTION" not in meta or "SCHEMA" not in meta or not has_run:
            raise ValueError("в навыке нет DESCRIPTION, SCHEMA или run()")
        return meta

    def list(self):
        out = []
        for p in sorted(self.dir.glob("*.py")):
            try:
                meta = self._read_meta(p)
                out.append({"name": p.stem, "description": meta["DESCRIPTION"], "schema": meta["SCHEMA"]})
            except Exception:
                continue
        return out

    def tool_defs(self):
        return [
            {
                "name": f"skill_{s['name']}",
                "description": f"[Мой навык] {s['description']}",
                "input_schema": s["schema"],
            }
            for s in self.list()
        ]

    def summary(self) -> str:
        items = self.list()
        if not items:
            return "(пока нет)"
        return "\n".join(f"- {s['name']}: {s['description']}" for s in items)

    def run(self, name: str, args: dict, timeout: int = 120) -> str:
        path = self.dir / f"{name}.py"
        if not path.exists():
            return f"Навык {name} не найден."
        r = subprocess.run(
            [sys.executable, "-c", RUNNER, str(path), json.dumps(args, ensure_ascii=False)],
            capture_output=True, text=True, timeout=timeout,
        )
        if r.returncode != 0:
            raise RuntimeError((r.stderr or "навык упал").strip()[-1500:])
        return r.stdout.strip()[-4000:] or "готово"

    def create(self, name: str, description: str, input_schema: dict, code: str) -> str:
        if not NAME_RE.match(name or ""):
            raise ValueError("имя навыка: латиница в нижнем регистре, цифры и _, до 40 символов")
        if not isinstance(input_schema, dict) or input_schema.get("type") != "object":
            raise ValueError("input_schema должна быть JSON-схемой с type=object")
        tree = ast.parse(code)  # синтаксическая проверка
        if not any(isinstance(n, ast.FunctionDef) and n.name == "run" for n in tree.body):
            raise ValueError("в коде нет функции run(**kwargs)")
        header = (
            f"# Навык Alfred: {name}\n"
            f"DESCRIPTION = {json.dumps(description, ensure_ascii=False)}\n"
            f"SCHEMA = {repr(input_schema)}\n\n"
        )
        path = self.dir / f"{name}.py"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(header + code.strip() + "\n", encoding="utf-8")
        self._read_meta(tmp)
        tmp.replace(path)
        return f"Навык {name} создан и уже доступен."
