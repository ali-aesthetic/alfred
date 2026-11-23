"""Alfred journal: everything said and done, as a readable chat page per day.

  journal.py              build today's page and open it
  journal.py 2026-11-08   that day
  journal.py --no-open    build only

Reads data/log.jsonl (Alfred writes every heard phrase, reply, action, hologram and protocol there)
and writes data/journal/YYYY-MM-DD.html. Nothing leaves the Mac.
"""
import datetime as dt
import html
import json
import subprocess
import sys
from pathlib import Path

HOME = Path(__file__).resolve().parent
LOG = HOME / "data" / "log.jsonl"
OUT = HOME / "data" / "journal"

TOOL_WORDS = {"Bash": "ran", "Write": "wrote", "Edit": "edited", "Read": "read", "WebSearch": "searched",
              "WebFetch": "opened page", "Glob": "looked for files", "Grep": "searched files", "Skill": "used skill"}


def entries(day):
    out = []
    try:
        lines = LOG.read_text(encoding="utf-8").splitlines()
    except OSError:
        return out
    for line in lines:
        try:
            x = json.loads(line)
        except ValueError:
            continue
        t = dt.datetime.fromtimestamp(x.get("ts", 0))
        if t.date() != day:
            continue
        k = x.get("type")
        if k == "request":
            out.append((t, "you", x.get("text", "")))
        elif k == "reply" and x.get("text"):
            out.append((t, "alfred", x["text"] + (f"  ·  {x['seconds']} s" if x.get("seconds") else "")))
        elif k == "quick":
            out.append((t, "you", x.get("text", "")))
            out.append((t, "alfred", x.get("reply", "") + "  ·  instant"))
        elif k == "action":
            out.append((t, "act", f"{TOOL_WORDS.get(x.get('tool'), x.get('tool', ''))}: {x.get('detail', '')}"))
        elif k == "holo":
            out.append((t, "act", f"hologram: {x.get('title', '')} ({x.get('archetype', '')}, {x.get('seconds', '?')} s)"))
        elif k == "protocol":
            out.append((t, "act", f"protocol: {x.get('name', '')}"))
        elif k == "claude_watch":
            out.append((t, "alfred", x.get("text", "")))
        elif k == "error":
            out.append((t, "err", f"{x.get('where', '')}: {x.get('error', '')}"))
        elif k == "start":
            out.append((t, "sys", "Alfred started"))
    return out


PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Alfred log · {day}</title><style>
:root{{--bg:#07090c;--fg:#f4ece0;--muted:#9c9182;--gold:#ffb04a;--you:#1f2a3a;--jar:#2a1f10;--line:#232a33}}
body{{margin:0;background:var(--bg);color:var(--fg);font:16px/1.45 -apple-system,"Helvetica Neue",sans-serif}}
.w{{max-width:820px;margin:0 auto;padding:24px 16px 60px;display:grid;gap:8px}}
h1{{font:600 28px/1 "Avenir Next Condensed",sans-serif;letter-spacing:.12em;color:#ffe2b0;margin:0 0 4px}}
.sub{{color:var(--muted);margin-bottom:14px}}
.r{{display:flex;gap:10px;align-items:flex-start}} .r.you{{justify-content:flex-end}}
.b{{max-width:78%;padding:10px 14px;border-radius:16px;white-space:pre-wrap;word-wrap:break-word}}
.you .b{{background:var(--you);border-bottom-right-radius:4px}}
.alfred .b{{background:var(--jar);border:1px solid #4a3418;border-bottom-left-radius:4px}}
.act .b{{background:none;color:var(--muted);font:13px/1.4 ui-monospace,Menlo,monospace;padding:2px 14px;border-left:2px solid var(--gold)}}
.err .b{{color:#ff8a8a;font-size:13px;padding:2px 14px;border-left:2px solid #ff6b6b}}
.sys .b{{color:var(--muted);font-size:13px;margin:10px auto}}
.t{{color:var(--muted);font:12px ui-monospace,Menlo,monospace;min-width:44px;padding-top:12px}}
.you .t{{order:2}}
</style></head><body><div class="w"><h1>Alfred LOG</h1><div class="sub">{day} · {n_you} things you said · {n_act} actions · newest at the bottom</div>
{rows}
</div></body></html>"""


def build(day=None, open_it=True):
    day = day or dt.date.today()
    es = entries(day)
    rows = "\n".join(f'<div class="r {k}"><span class="t">{t:%H:%M}</span><div class="b">{html.escape(str(txt))}</div></div>'
                     for t, k, txt in es)
    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / f"{day.isoformat()}.html"
    p.write_text(PAGE.format(day=day.strftime("%A %d %B %Y"), rows=rows or '<div class="sub">Nothing yet today.</div>',
                             n_you=sum(1 for e in es if e[1] == "you"), n_act=sum(1 for e in es if e[1] == "act")), encoding="utf-8")
    if open_it:
        subprocess.Popen(["open", str(p)])
    return p, es


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    d = dt.date.fromisoformat(args[0]) if args else None
    p, es = build(d, open_it="--no-open" not in sys.argv)
    print(p, len(es), "entries")
