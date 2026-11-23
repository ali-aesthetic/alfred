"""Automatic recall: in-process search of the user's Brain copy + memory cards, as a compact block for a brain turn."""
import json
import re
import time
from pathlib import Path

HOME = Path(__file__).resolve().parent
MEM_JSON = HOME / "data" / "ui" / "memory.json"
MIN_SCORE = 7.0      # brain_rag BM25-ish score below this = weak, skip
MAX_CHARS = 1200
_rag = None
_cards = {"mtime": 0, "items": []}
_STOP = set("what which that this with have from your about when where would could should there their them then than into just like really want need please alfred sir tell show give make the and for you are was how why can".split())


def warm():
    """Load the index once (background) so the first turn pays nothing."""
    global _rag
    try:
        import brain_rag
        brain_rag.load()
        _rag = brain_rag
    except Exception as e:
        print("[recall warm]", e)


def _words(t):
    return [w for w in re.findall(r"[\w']+", t.lower()) if len(w) >= 4 and w not in _STOP]


def _cards_list():
    try:
        m = MEM_JSON.stat().st_mtime
        if m != _cards["mtime"]:
            _cards["items"] = json.loads(MEM_JSON.read_text(encoding="utf-8"))
            _cards["mtime"] = m
    except Exception:
        pass
    return _cards["items"]


def _card_hits(q, n=2):
    qw = set(_words(q))
    if not qw:
        return []
    scored = []
    for c in _cards_list():
        f = str(c.get("fact", ""))
        ov = qw & set(_words(f))
        sc = len(ov) + (0.5 if any(len(w) >= 6 for w in ov) else 0)
        if sc >= 1.5:
            scored.append((sc, f))
    scored.sort(key=lambda x: -x[0])
    return [f for _, f in scored[:n]]


def block(text, min_score=MIN_SCORE):
    """Return '' or the context block to prepend. Never raises."""
    try:
        q = text.split("\n", 1)[0]
        q = re.sub(r"^\[[^\]]*\]\s*", "", q).strip()[:300]
        if len(q) < 6:
            return ""
        lines, used = [], 0
        qw = set(_words(q)) - {"today", "next", "step", "steps", "notes", "note"}
        global _rag
        if _rag is None:
            import brain_rag
            _rag = brain_rag
        for r in _rag.search(q, 3):
            if r.get("score", 0) < min_score:
                continue
            sn = re.sub(r"\s+", " ", r.get("snippet", ""))[:260]
            if not (qw & set(_words((r.get("title") or "") + " " + r.get("snippet", "")))):
                continue  # high score but no shared content word = noise
            ln = f"- [{r.get('note') or r.get('title')}] {sn}"
            if used + len(ln) > MAX_CHARS - 200:
                break
            lines.append(ln)
            used += len(ln)
        for f in _card_hits(q):
            ln = f"- (memory) {f[:200]}"
            if used + len(ln) > MAX_CHARS - 40:
                break
            lines.append(ln)
            used += len(ln)
        if not lines:
            return ""
        return "[Context from the user's notes — use if relevant, cite note name briefly]\n" + "\n".join(lines) + "\n[/Context]\n"
    except Exception as e:
        print("[recall]", e)
        return ""
