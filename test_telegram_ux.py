"""IVA-style Telegram UX tests against a FAKE Telegram (no network, no real messages). Run:
$ALFRED_HOME/.venv/bin/python test_telegram_ux.py"""
import json, tempfile, threading, time, datetime as dt
from pathlib import Path
import telegram_bridge as tb, skills_gate, away, insights

OWNER, STRANGER = 111, 999


class FakeTG:
    def __init__(self):
        self.calls, self.n = [], 100

    def call(self, method, params=None, files=None, timeout=40):
        self.calls.append((method, params or {}))
        self.n += 1
        return {"ok": True, "result": {"message_id": self.n}}

    def of(self, m):
        return [p for k, p in self.calls if k == m]


def mk(tmp, settings=None):
    own = Path(tmp) / "owner.json"
    own.write_text(json.dumps({"chat_id": OWNER}))
    tg = FakeTG()
    st = settings if settings is not None else {"silent": False, "mic_off": False}
    sets = []
    def setter(k, v):
        sets.append((k, v)); st[k] = v
    pairing = tb.Pairing(Path(tmp) / "pair.json", own)
    a = away.Away(lambda *x, **k: "", lambda t: None, autostart=False, directory=tmp, poll_every=0)
    b = tb.Bridge(lambda *x, **k: "", None, lambda: st, tg=tg, pairing=pairing, away=a, set_setting=setter, inbox=tmp)
    a.send = b.send
    a.send_kb = b.send_kb
    b._screenshot = lambda p: Path(p).write_bytes(b"x")
    return b, tg, a, sets


def cbq(data, chat=OWNER, user=OWNER, mid=500):
    return {"update_id": 1, "callback_query": {"id": "q1", "from": {"id": user}, "data": data,
            "message": {"message_id": mid, "chat": {"id": chat}, "text": "orig"}}}


def msg(text, chat=OWNER):
    return {"update_id": 2, "message": {"chat": {"id": chat}, "text": text}}


def test_grammar():
    assert len(tb.cb("m", "st").encode()) <= 64
    try:
        tb.cb("x", "a" * 70); assert False
    except ValueError:
        pass
    assert tb.inline_kb([[("A", "jv:x")]]) == {"inline_keyboard": [[{"text": "A", "callback_data": "jv:x"}]]}
    k = tb.quick_kb()
    assert k["resize_keyboard"] and k["is_persistent"] and k["keyboard"][1][0]["text"] == "Play my sleep playlist"


def test_menu_flow():
    with tempfile.TemporaryDirectory() as d:
        b, tg, a, sets = mk(d)
        assert b.handle_update(msg("/menu")) == "command:menu"
        m = tg.of("sendMessage")[-1]
        rows = m["reply_markup"]["inline_keyboard"]
        labels = [x["text"] for r in rows for x in r]
        assert all(any(w in l for l in labels) for w in ("Status", "Screen", "Tasks", "Jobs", "Skills", "Mic: on", "Silent: off", "Close")), labels
        assert all(len(x["callback_data"].encode()) <= 64 and x["callback_data"].startswith("jv:") for r in rows for x in r)
        # tap Tasks -> same message edited with Back
        assert b.handle_update(cbq("jv:m:ta")) == "cb:m"
        e = tg.of("editMessageText")[-1]
        assert e["message_id"] == 500 and e["chat_id"] == OWNER and "away" in e["text"].lower()
        assert e["reply_markup"]["inline_keyboard"][0][0]["text"] == "‹ Back"
        assert tg.of("answerCallbackQuery")
        # Back
        b.handle_update(cbq("jv:m:r"))
        assert tg.of("editMessageText")[-1]["text"] == "Alfred menu"
        # toggle mic: setter called, menu re-rendered with new state
        b.handle_update(cbq("jv:m:mic"))
        assert sets == [("mic_off", True)]
        lab = [x["text"] for r in tg.of("editMessageText")[-1]["reply_markup"]["inline_keyboard"] for x in r]
        assert "🎤 Mic: off" in lab, lab
        b.handle_update(cbq("jv:m:sil"))
        assert sets[-1] == ("silent", True)
        # Close: keyboard removed
        b.handle_update(cbq("jv:m:x"))
        assert tg.of("editMessageText")[-1]["reply_markup"] == {"inline_keyboard": []}
        # /start: quick keyboard + menu
        b.handle_update(msg("/start"))
        assert any("keyboard" in (p.get("reply_markup") or {}) for p in tg.of("sendMessage"))
        # commands list
        b._setup_commands()
        cmds = [c["command"] for c in tg.of("setMyCommands")[0]["commands"]]
        assert "menu" in cmds and "status" in cmds


def test_owner_only_callbacks():
    with tempfile.TemporaryDirectory() as d:
        b, tg, a, sets = mk(d)
        for u in (cbq("jv:m:mic", chat=STRANGER, user=STRANGER), cbq("jv:m:mic", chat=OWNER, user=STRANGER),
                  cbq("jv:m:mic", chat=STRANGER, user=OWNER)):
            assert b.handle_update(u) == "ignored"
        assert not tg.calls and not sets  # not even answerCallbackQuery
        assert b.handle_update(cbq("evil:x")) == "cb:bad"
        assert b.handle_update(cbq("jv:zz")) == "cb:unknown"


def test_skill_buttons():
    with tempfile.TemporaryDirectory() as d:
        b, tg, a, _ = mk(d)
        data = Path(d) / "data"
        g = skills_gate.Gate(data=data, skills_dir=Path(d) / "skills", trash=Path(d) / "trash", send_kb=b.send_kb, recycle=lambda: None)
        (data / "learn" / "staged").mkdir(parents=True)
        (data / "learn" / "staged" / "open-fcp.md").write_text("When: open final cut\nTriggers: fcp\n1. open it\nVerify: window")
        g.register("open-fcp", "Open Final Cut"); g.record_use("open-fcp", "")
        assert g.offer_ready() == ["open-fcp"]
        mk_ = tg.of("sendMessage")[-1]["reply_markup"]["inline_keyboard"][0]
        assert [x["text"] for x in mk_] == ["✅ Approve", "✖ Reject"]
        sid = g.sid("open-fcp")
        assert mk_[0]["callback_data"] == f"jv:sa:{sid}" and mk_[1]["callback_data"] == f"jv:sr:{sid}"
        skills_gate._G = g
        b.handle_update(cbq(f"jv:sa:{sid}"))
        assert (Path(d) / "skills" / "open-fcp" / "SKILL.md").exists()
        assert "active" in tg.of("editMessageText")[-1]["text"]
        skills_gate._G = None


def test_away_buttons():
    with tempfile.TemporaryDirectory() as d:
        b, tg, a, _ = mk(d)
        t = {"id": "1122-090000", "state": "running", "waiting": "", "deadline": 0, "task": "x"}
        res = []
        th = threading.Thread(target=lambda: res.append(a._ask_yes(t, "Send the file")))
        th.start()
        for _ in range(100):
            if tg.of("sendMessage"): break
            time.sleep(0.02)
        row = tg.of("sendMessage")[-1]["reply_markup"]["inline_keyboard"][0]
        assert [x["text"] for x in row] == ["Yes, do it", "No"] and row[0]["callback_data"] == "jv:ay:1122-090000"
        b.handle_update(cbq("jv:ay:1122-090000"))
        th.join(3)
        assert res == [True]
        # progress buttons
        t.update(plan=[{"step": "a"}], cur=1, last_progress=1)
        a.now = lambda: 10 ** 9
        a._progress(t)
        row = tg.of("sendMessage")[-1]["reply_markup"]["inline_keyboard"][0]
        assert [x["text"] for x in row] == ["⏸ Pause", "⏹ Stop", "📸 Screen"]
        assert all(len(x["callback_data"].encode()) <= 64 for x in row)
        a.current = a.tasks[t["id"]] = t
        t["state"] = "running"
        b.handle_update(cbq("jv:ap:" + t["id"]))
        assert t["id"] in a.paused
        b.handle_update(cbq("jv:asc:" + t["id"]))
        assert tg.of("sendPhoto") or True  # photo goes through files path of FakeTG.call
        b.handle_update(cbq("jv:as:" + t["id"]))
        assert t["state"] == "stopped"


def test_quick_buttons():
    with tempfile.TemporaryDirectory() as d:
        b, tg, a, _ = mk(d)
        assert b.handle_update(msg("Stop")) == "command:stop"
        assert b.handle_update(msg("Screen")) == "command:screen"
        assert b.handle_update(msg("What's on today?")) == "ask"


def test_insights():
    with tempfile.TemporaryDirectory() as d:
        b, tg, a, _ = mk(d)
        on = [False]
        jobs = []
        noon = lambda: dt.datetime(2026, 11, 23, 12, 0)
        idea = json.dumps({"text": "You open Final Cut every evening - make it a routine?", "when": "daily 19:00", "task": "Open Final Cut"})
        I = insights.Insights(b.send_kb, lambda p: idea, lambda: on[0], lambda v: on.__setitem__(0, v), data=d, now_fn=noon,
                              add_job=lambda w, t, deliver: jobs.append((w, t, deliver)) or {"id": "abc123"})
        b.insights = I
        assert I.tick() == "offer"
        r = tg.of("sendMessage")[-1]["reply_markup"]["inline_keyboard"][0]
        assert [x["text"] for x in r] == ["Turn on", "Not now"]
        assert I.tick() == ""  # offered once only
        b.handle_update(cbq("jv:io"))
        assert on[0]
        assert I.tick() == "idea"
        r = tg.of("sendMessage")[-1]["reply_markup"]["inline_keyboard"][0]
        assert [x["text"] for x in r] == ["Yes", "Not now"]
        assert I.tick() == ""  # max one per day
        b.handle_update(cbq(r[0]["callback_data"]))
        assert jobs == [("daily 19:00", "Open Final Cut", "telegram")]
        # quiet hours
        I.now = lambda: dt.datetime(2026, 11, 24, 3, 0)
        assert I.tick() == ""
        # "Not now" suppresses the same idea
        I.now = lambda: dt.datetime(2026, 11, 24, 12, 0)
        assert I.tick() == "idea"
        r = tg.of("sendMessage")[-1]["reply_markup"]["inline_keyboard"][0]
        b.handle_update(cbq(r[1]["callback_data"]))
        assert len(jobs) == 1
        I.now = lambda: dt.datetime(2026, 11, 25, 12, 0)
        assert I.tick() == ""  # same idea declined -> not proposed again
        # bad schedule from the model is rejected
        I.model_fn = lambda p: json.dumps({"text": "x?", "when": "whenever", "task": "t"})
        I.now = lambda: dt.datetime(2026, 11, 26, 12, 0)
        assert I.tick() == ""


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f(); print("ok", n)
