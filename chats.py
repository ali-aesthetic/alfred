"""Chat search: SQLite FTS5 index of every past turn (data/log.jsonl request/reply pairs, data/sessions/*.md).
Idea borrowed from Hermes Agent `hermes_state.py` (FTS5 over sessions, MIT). Own implementation.
Telegram messages are indexed too: they go through brain.ask and land in log.jsonl.
Incremental: log.jsonl by byte offset, sessions by file name. Index is refreshed on every search.

  chats.py search "query" [--days N] [--limit 8]      chats.py reindex
"""
import argparse
import datetime as dt
import json
import re
import sqlite3
import sys
import time
from pathlib import Path

HOME = Path(__file__).resolve().parent
DATA = HOME / "data"
DB = DATA / "chats.db"


def connect(db=None):
    c = sqlite3.connect(str(db or DB), timeout=10)
    c.executescript("""
    CREATE TABLE IF NOT EXISTS msgs(id INTEGER PRIMARY KEY, src TEXT, who TEXT, ts REAL, text TEXT);
    CREATE VIRTUAL TABLE IF NOT EXISTS msgs_fts USING fts5(text, content='msgs', content_rowid='id', tokenize='unicode61 remove_diacritics 2');
    CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT);
    """)
    return c


def _meta(c, k, default=None):
    r = c.execute("SELECT v FROM meta WHERE k=?", (k,)).fetchone()
    return r[0] if r else default


def _put(c, k, v):
    c.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", (k, str(v)))


def _add(c, src, who, ts, text):
    cur = c.execute("INSERT INTO msgs(src,who,ts,text) VALUES(?,?,?,?)", (src, who, ts, text))
    c.execute("INSERT INTO msgs_fts(rowid,text) VALUES(?,?)", (cur.lastrowid, text))


def index(c=None, data=None):
    """Add anything new. Returns number of rows added."""
    data = Path(data or DATA)
    own = c is None
    c = c or connect()
    n0 = c.execute("SELECT COUNT(*) FROM msgs").fetchone()[0]
    log = data / "log.jsonl"
    if log.exists():
        off = int(_meta(c, "log_off", 0))
        size = log.stat().st_size
        if size < off:
            off = 0
        with open(log, "rb") as f:
            f.seek(off)
            while True:
                line = f.readline()
                if not line or not line.endswith(b"\n"):
                    break  # partial last line: pick it up next time
                off += len(line)
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                t, text = d.get("type"), str(d.get("text") or "")
                if t not in ("request", "reply") or not text.strip():
                    continue
                if t == "request":
                    if text.lstrip().startswith("[system]"):
                        continue
                    text = text.split("Screen (only when asked")[0].strip()
                _add(c, "log", "You" if t == "request" else "Alfred", d.get("ts", 0), text)
        _put(c, "log_off", off)
    seen = set(json.loads(_meta(c, "sessions", "[]")))
    sd = data / "sessions"
    if sd.is_dir():
        for f in sorted(sd.glob("*.md")):
            if f.name in seen:
                continue
            try:
                ts = dt.datetime.strptime(f.stem[:15], "%Y-%m-%d-%H%M").timestamp()
            except ValueError:
                ts = f.stat().st_mtime
            t = f.read_text(encoding="utf-8").strip()
            if t:
                _add(c, "session", "summary", ts, t)
            seen.add(f.name)
        _put(c, "sessions", json.dumps(sorted(seen)))
    c.commit()
    n = c.execute("SELECT COUNT(*) FROM msgs").fetchone()[0] - n0
    if own:
        c.close()
    return n


def _fts_query(q, mode="and"):
    toks = re.findall(r"\w+", q.lower())
    if not toks:
        return ""
    return (" AND " if mode == "and" else " OR ").join(f'"{t}"*' if len(t) > 2 else f'"{t}"' for t in toks)


def search(q, days=None, limit=8, c=None):
    own = c is None
    c = c or connect()
    index(c)
    cut = time.time() - days * 86400 if days else 0
    rows = []
    for mode in ("and", "or"):
        fq = _fts_query(q, mode)
        if not fq:
            break
        rows = c.execute(
            "SELECT m.ts, m.who, m.src, snippet(msgs_fts, 0, '[', ']', '…', 24) FROM msgs_fts "
            "JOIN msgs m ON m.id = msgs_fts.rowid WHERE msgs_fts MATCH ? AND m.ts >= ? "
            "ORDER BY bm25(msgs_fts) LIMIT ?", (fq, cut, limit)).fetchall()
        if rows:
            break
    if own:
        c.close()
    return rows


def format_rows(rows):
    if not rows:
        return "No matches."
    out = []
    for ts, who, src, snip in sorted(rows, key=lambda r: -r[0]):
        d = dt.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M") if ts else "?"
        out.append(f"{d} {who}: {' '.join(snip.split())[:220]}")
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="chats.py")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("search")
    s.add_argument("query")
    s.add_argument("--days", type=int)
    s.add_argument("--limit", type=int, default=8)
    sub.add_parser("reindex")
    a = ap.parse_args(argv)
    if a.cmd == "reindex":
        print("indexed", index())
    else:
        print(format_rows(search(a.query, a.days, a.limit)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
