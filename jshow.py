"""jshow — показать панель на голограмме Alfred.

  jshow - <<'EOF'            JSON панели (объект или массив до 3) из stdin — так безопаснее всего
  {"type":"table","title":"…","columns":["…"],"rows":[["…"]]}
  EOF
  jshow '{"type":"text","title":"…","text":"…"}'
  jshow image /путь/или/https://…  [заголовок]
  jshow video /путь/к/видео.mp4    [заголовок]
  jshow text "Заголовок" "текст"
  jshow --replace …                заменить показанные панели вместо добавления
  jshow clear                      убрать все панели

Типы: text, list, table, chart (kind bar|line, labels, series[{name,values}], unit), image, video, stat (value, note).
"""
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import panels  # noqa: E402

CACHE = panels.HOME / "data" / "panel_cache"
IMG_OK = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".bmp"}
IMG_CONVERT = {".heic", ".heif", ".tif", ".tiff", ".psd", ".dng", ".cr2", ".arw", ".nef", ".raw"}
VID_OK = {".mp4", ".mov", ".m4v"}


def _local(src):
    p = Path(os.path.expanduser(str(src))).resolve()
    if not p.exists():
        raise SystemExit(f"Файл не найден: {p}")
    return p


def _image_src(src):
    if str(src).startswith(("http://", "https://", "data:")):
        return src
    p = _local(src)
    ext = p.suffix.lower()
    big = p.stat().st_size > 6_000_000
    if ext in IMG_CONVERT or big or ext not in IMG_OK:
        CACHE.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(CACHE, 0o777)
        except OSError:
            pass
        out = CACHE / (hashlib.md5(f"{p}{p.stat().st_mtime}".encode()).hexdigest()[:16] + ".jpg")
        if not out.exists():
            r = subprocess.run(["sips", "-s", "format", "jpeg", "-Z", "1600", str(p), "--out", str(out)],
                               capture_output=True, text=True)
            if r.returncode != 0 or not out.exists():
                raise SystemExit(f"Не удалось подготовить картинку: {r.stderr.strip()[:200]}")
        p = out
    return p.as_uri()


def _video_src(src):
    if str(src).startswith(("http://", "https://")):
        return src
    p = _local(src)
    if p.suffix.lower() not in VID_OK:
        print(f"Внимание: формат {p.suffix} может не проиграться, лучше mp4/mov.", file=sys.stderr)
    return p.as_uri()


def normalize(s):
    if not isinstance(s, dict):
        raise SystemExit("Панель должна быть JSON-объектом.")
    t = s.get("type", "text")
    if t not in panels.TYPES:
        raise SystemExit(f"Неизвестный тип панели «{t}». Есть: {', '.join(sorted(panels.TYPES))}.")
    s["type"] = t
    if t == "image":
        s["src"] = _image_src(s.get("src") or s.get("path") or s.get("url") or "")
    elif t == "video":
        s["src"] = _video_src(s.get("src") or s.get("path") or s.get("url") or "")
    elif t == "table":
        s["rows"] = [[("" if c is None else str(c)) for c in r] for r in (s.get("rows") or [])][:200]
        s["columns"] = [str(c) for c in (s.get("columns") or [])]
    elif t == "chart":
        if "values" in s and "series" not in s:
            s["series"] = [{"name": s.get("title", ""), "values": s.pop("values")}]
        for ser in s.get("series") or []:
            ser["values"] = [float(v) if v not in (None, "") else 0.0 for v in ser.get("values", [])]
        s["labels"] = [str(x) for x in (s.get("labels") or [])]
        s.setdefault("kind", "bar")
    elif t == "list":
        s["items"] = [str(x) for x in (s.get("items") or [])][:30]
    return s


def main(argv):
    replace = False
    if argv and argv[0] in ("--replace", "-r"):
        replace, argv = True, argv[1:]
    if not argv:
        print(__doc__)
        return 1
    cmd = argv[0]
    if cmd in ("clear", "--clear", "убрать"):
        panels.clear()
        print("Панели убраны.")
        return 0
    if cmd == "-":
        data = json.loads(sys.stdin.read())
    elif cmd in ("image", "video"):
        data = {"type": cmd, "src": argv[1] if len(argv) > 1 else "", "title": argv[2] if len(argv) > 2 else ""}
    elif cmd == "text":
        data = {"type": "text", "title": argv[1] if len(argv) > 1 else "", "text": argv[2] if len(argv) > 2 else ""}
    else:
        data = json.loads(" ".join(argv))
    items = data if isinstance(data, list) else [data]
    items = [normalize(s) for s in items][: panels.MAX_PANELS]
    panels.push(items, replace=replace)
    print(f"Показано на голограмме: {len(items)} панел{'ь' if len(items) == 1 else 'и'}.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except json.JSONDecodeError as e:
        print(f"Ошибка JSON: {e}", file=sys.stderr)
        sys.exit(2)
