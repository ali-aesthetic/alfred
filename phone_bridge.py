#!/usr/bin/env python3
"""Alfred phone bridge: lets the "Alfred" iPhone app talk to the Alfred running on this Mac.

Runs as a thread inside alfred.py (config.json "phone_bridge": true), so it shares the warm brain,
the Whisper ears and the voice. Nothing extra is loaded into RAM.

Network
  - Listens on 127.0.0.1, the Mac's home-network address(es) and the Tailscale address (100.x) only.
    Never 0.0.0.0, never the internet (no port forwarding, no tunnels).
  - Announces itself on the home network with Bonjour (_alfred._tcp) so the app finds the Mac.

Pairing (once per phone)
  - The phone asks to pair; the Mac shows a 6-digit code (notification + http://127.0.0.1:PORT/pair page with a QR).
  - Both sides do an X25519 key exchange and mix in the code (HKDF). The code and the final key never cross the network.
  - The 32-byte key lives in the iPhone Keychain and in data/phone_tokens.json (chmod 600) on the Mac.
  - Wrong codes are rate-limited: 5 tries per code, 20 failures per hour locks pairing for an hour.

Requests
  - Every request is signed: X-Alfred-Device, X-Alfred-Time, X-Alfred-Nonce, X-Alfred-Sig = HMAC-SHA256(key, method\\npath\\ntime\\nnonce\\nsha256(body)).
  - Phone requests go to the same brain, so guard.py and all safety rules apply exactly as to voice.

API (JSON unless noted)
  GET  /api/hello                      no auth: name, version, pairing state
  POST /api/pair/start                 no auth: {device_name} -> {session, mac_pub, code_shown}
  POST /api/pair/finish                no auth: {session, phone_pub, proof, device_name} -> {device_id, proof}
  POST /api/text   {text, speak_mac}   -> {turn, heard, reply, chunks:[{seq,text,audio}]}
  POST /api/voice  (audio/wav body)    -> same, "heard" is what Whisper understood
  GET  /api/audio/<id>.wav             reply audio (WAV)
  GET  /api/status                     state, panels, hologram title
  POST /api/stop                       stop the current answer
  POST /api/unpair                     forget this phone
  GET  /ws                             live events: state, heard, say (sentence + audio id), reply, panels
"""
import asyncio
import getpass
import hashlib
import hmac
import io
import ipaddress
import json
import os
import re
import secrets
import socket
import subprocess
import threading
import time
import traceback
import wave
from pathlib import Path

HOME = Path(__file__).resolve().parent
USER = getpass.getuser()
VERSION = "1.0"
DEFAULT_PORT = 47390
TOKENS = HOME / "data" / "phone_tokens.json"
PAIR_INFO = "alfred-phone-v1"
# the user is away from the Mac and listens on the phone: English voice, short spoken answers
PHONE_PREFIX = ("[Sent from the user's iPhone app; they may be away from the Mac. Reply in English only, including any "
                "confirmation question (ask \"Shall I proceed, sir?\"). Keep it short and conversational, it is read "
                "aloud. For numbers you may add one small markdown table.] ")
YES_RE = re.compile(r"^\s*(да|ага|подтверждаю|давай|делай|yes|yeah|yep|sure|do it|go ahead|confirm(ed)?|ha|xa|mayli)"
                    r"[\s,.!]*(джарвис|alfred|сэр|sir)?[\s,.!]*$", re.I)


# ---------------------------------------------------------------- crypto (pure Python, no extra packages)
_P = 2 ** 255 - 19
_A24 = 121665


def x25519(k: bytes, u: bytes) -> bytes:
    """RFC 7748 X25519 (Montgomery ladder). Same math as Apple CryptoKit Curve25519.KeyAgreement."""
    kb = bytearray(k)
    kb[0] &= 248
    kb[31] &= 127
    kb[31] |= 64
    k_int = int.from_bytes(kb, "little")
    ub = bytearray(u)
    ub[31] &= 127
    x1 = int.from_bytes(ub, "little") % _P
    x2, z2, x3, z3, swap = 1, 0, x1, 1, 0
    for t in reversed(range(255)):
        kt = (k_int >> t) & 1
        swap ^= kt
        if swap:
            x2, x3, z2, z3 = x3, x2, z3, z2
        swap = kt
        a = (x2 + z2) % _P
        aa = a * a % _P
        b = (x2 - z2) % _P
        bb = b * b % _P
        e = (aa - bb) % _P
        c = (x3 + z3) % _P
        d = (x3 - z3) % _P
        da = d * a % _P
        cb = c * b % _P
        x3 = (da + cb) ** 2 % _P
        z3 = x1 * (da - cb) ** 2 % _P
        x2 = aa * bb % _P
        z2 = e * (aa + _A24 * e) % _P
    if swap:
        x2, z2 = x3, z3
    return (x2 * pow(z2, _P - 2, _P) % _P).to_bytes(32, "little")


def x25519_keypair():
    priv = secrets.token_bytes(32)
    return priv, x25519(priv, (9).to_bytes(32, "little"))


def hkdf_sha256(ikm: bytes, salt: bytes, info: bytes, n=32) -> bytes:
    prk = hmac.new(salt, ikm, hashlib.sha256).digest()
    out, t, i = b"", b"", 1
    while len(out) < n:
        t = hmac.new(prk, t + info + bytes([i]), hashlib.sha256).digest()
        out += t
        i += 1
    return out[:n]


def _mac(key: bytes, msg: bytes) -> str:
    return hmac.new(key, msg, hashlib.sha256).hexdigest()


# ---------------------------------------------------------------- paired phones
class Tokens:
    def __init__(self, path=TOKENS):
        self.path = path
        self.lock = threading.Lock()

    def load(self):
        try:
            d = json.loads(self.path.read_text(encoding="utf-8"))
            return d if isinstance(d, dict) else {}
        except Exception:
            return {}

    def save(self, d):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(d, f, indent=1)
        os.chmod(tmp, 0o600)
        tmp.replace(self.path)

    def key(self, device_id):
        d = self.load().get(device_id)
        return bytes.fromhex(d["key"]) if d and not d.get("revoked") else None

    def add(self, device_id, key: bytes, name):
        with self.lock:
            d = self.load()
            d[device_id] = {"key": key.hex(), "name": name[:60], "paired": int(time.time()), "last": int(time.time())}
            self.save(d)

    def touch(self, device_id):
        with self.lock:
            d = self.load()
            if device_id in d and time.time() - d[device_id].get("last", 0) > 300:
                d[device_id]["last"] = int(time.time())
                self.save(d)

    def revoke(self, device_id):
        with self.lock:
            d = self.load()
            if device_id in d:
                d[device_id]["revoked"] = int(time.time())  # keep the record, just switch it off
                d[device_id]["key"] = ""
                self.save(d)


# ---------------------------------------------------------------- network addresses
def _ifaddrs():
    """[(interface, ipv4)] for interfaces that are up."""
    out = []
    try:
        txt = subprocess.run(["ifconfig"], capture_output=True, text=True, timeout=5).stdout
    except Exception:
        return out
    cur = None
    for line in txt.splitlines():
        m = re.match(r"^(\S+?):\s+flags=\S*<([^>]*)>", line)
        if m:
            cur = m.group(1) if "UP" in m.group(2).split(",") else None
            continue
        m = re.match(r"^\s+inet (\d+\.\d+\.\d+\.\d+)", line)
        if m and cur:
            out.append((cur, m.group(1)))
    return out


_TAILNET = ipaddress.ip_network("100.64.0.0/10")


def bind_hosts():
    """127.0.0.1 + home-network (private) addresses + Tailscale address. Never 0.0.0.0."""
    hosts = ["127.0.0.1"]
    lan, ts = [], []
    for ifname, ip in _ifaddrs():
        a = ipaddress.ip_address(ip)
        if a.is_loopback or a.is_link_local:
            continue
        if a in _TAILNET:
            ts.append(ip)
        elif a.is_private and (ifname.startswith("en") or ifname.startswith("bridge")):
            lan.append(ip)
    return hosts + lan + ts, lan, ts


# ---------------------------------------------------------------- the bridge
class Bridge:
    def __init__(self, cfg, brain, mouth, ear=None, log=None, home=HOME, stt=None):
        self.cfg = cfg
        self.brain = brain
        self.mouth = mouth
        self.ear = ear
        self.stt = stt or (ear.stt if ear is not None else None)
        self.log = log
        self.home = Path(home)
        self.port = int(cfg.get("phone_bridge_port", DEFAULT_PORT))
        self.tokens = Tokens(self.home / "data" / "phone_tokens.json")
        self.turn_lock = threading.Lock()
        self.turn = None          # {"id", "state", "sink"} while a phone request is running
        self.audio = {}           # id -> (created, wav bytes)
        self.pending = None       # pairing in progress
        self.fail_log = []        # times of wrong codes
        self.start_log = {}       # ip -> [times]
        self.seen_sigs = {}       # replay protection
        self.ws_clients = set()
        self.ws_device = {}       # websocket -> paired device id
        self.loop = None
        self.sites = {}
        self.runner = None
        self.bonjour = None
        self.last_heard = ""
        self.last_reply = ""
        self._vitals = (0.0, {})
        self._hook_progress()
        self._keep_awake()

    def _keep_awake(self):
        """While Alfred runs, the Mac doesn't fall asleep on its own when it's plugged in (caffeinate -s ends with Alfred).
        Off with "phone_keep_awake": false. A closed lid still sleeps."""
        if not self.cfg.get("phone_keep_awake", True):
            return
        try:
            subprocess.Popen(["caffeinate", "-s", "-w", str(os.getpid())],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:
            print("[phone] keep-awake:", e)

    # ---- logging
    def _log(self, kind, **kw):
        try:
            if self.log:
                self.log.add(kind, **kw)
        except Exception:
            pass

    # ---- brain progress: sentences of a phone turn go to the phone, everything else stays with the Mac voice
    def _hook_progress(self):
        if self.brain is None or getattr(self.brain, "_phone_hooked", False):
            return
        orig = self.brain.on_progress

        def dispatch(text):
            t = self.turn
            if t is not None and t.get("sink"):
                t["sink"](text)
                if t.get("speak_mac") and orig:
                    orig(text)
            elif orig:
                orig(text)

        self.brain.on_progress = dispatch
        self.brain._phone_hooked = True

    # ---- state
    def mac_state(self):
        try:
            import menubar
            return menubar.shown_state()
        except Exception:
            return "idle"

    def state(self):
        t = self.turn
        if t is not None:
            return t["state"]
        s = self.mac_state()
        return s if s in ("idle", "listening", "thinking", "speaking", "paused", "learning", "starting") else "idle"

    def panels(self):
        out = []
        try:
            import panels as pn
            for p in pn.read():
                item = {"id": str(p.get("id", "")), "type": p.get("type", "text"),
                        "title": str(p.get("title", ""))[:120]}
                for k in ("text", "value", "label", "unit", "caption"):
                    if p.get(k) is not None:
                        item[k] = str(p.get(k))[:600]
                if isinstance(p.get("items"), list):
                    item["items"] = [str(x if not isinstance(x, dict) else (x.get("text") or x.get("title") or x))[:160]
                                     for x in p["items"][:12]]
                if isinstance(p.get("rows"), list):
                    item["rows"] = [[str(c)[:40] for c in (r if isinstance(r, list) else [r])][:5] for r in p["rows"][:10]]
                src = p.get("src") or p.get("url")
                if isinstance(src, str) and src.startswith("https://"):
                    item["image"] = src
                out.append(item)
        except Exception:
            pass
        return out

    def hologram(self):
        try:
            d = json.loads((self.home / "data" / f"holo-{USER}.json").read_text(encoding="utf-8"))
            if d.get("hide") or not d.get("title"):
                return None
            return {k: str(d.get(k, ""))[:120] for k in ("title", "subtitle", "kicker", "archetype") if d.get(k)}
        except Exception:
            return None

    def vitals(self):
        """Battery, charging, free disk: cached 30 s (status is polled often)."""
        now = time.time()
        if now - self._vitals[0] < 30:
            return self._vitals[1]
        v = {}
        try:
            out = subprocess.run(["pmset", "-g", "batt"], capture_output=True, text=True, timeout=3).stdout
            m = re.search(r"(\d+)%;\s*([\w ]+);", out)
            if m:
                v["battery"] = int(m.group(1))
                v["charging"] = "AC Power" in out
        except Exception:
            pass
        try:
            st = os.statvfs("/")
            v["disk_free_gb"] = round(st.f_bavail * st.f_frsize / 1e9)
            v["disk_total_gb"] = round(st.f_blocks * st.f_frsize / 1e9)
        except Exception:
            pass
        try:
            out = subprocess.run(["memory_pressure", "-Q"], capture_output=True, text=True, timeout=3).stdout
            m = re.search(r"free percentage:\s*(\d+)%", out)
            if m:
                v["memory_free_pct"] = int(m.group(1))
        except Exception:
            pass
        try:
            v["cpu_load"] = round(os.getloadavg()[0], 1)
        except Exception:
            pass
        v["mac"] = socket.gethostname().split(".")[0]
        self._vitals = (now, v)
        return v

    def vitals_line(self):
        """Live Mac numbers handed to the brain, so "how is my Mac" needs no shell command (and no guard yes)."""
        v = self.vitals()
        parts = []
        if "battery" in v:
            parts.append(f"battery {v['battery']}%{' charging' if v.get('charging') else ''}")
        if "disk_free_gb" in v:
            parts.append(f"free disk {v['disk_free_gb']} GB of {v.get('disk_total_gb', '?')} GB")
        if "memory_free_pct" in v:
            parts.append(f"memory free {v['memory_free_pct']}%")
        if "cpu_load" in v:
            parts.append(f"CPU load {v['cpu_load']}")
        return f"[Mac right now (already measured, no need to run commands for these): {', '.join(parts)}.] " if parts else ""

    def status(self):
        return {"state": self.state(), "mac_state": self.mac_state(), "busy": self.turn is not None,
                "panels": self.panels(), "hologram": self.hologram(), "vitals": self.vitals(),
                "last_heard": self.last_heard, "last_reply": self.last_reply[:2000], "version": VERSION}

    # ---- audio
    def synth(self, text):
        if self.mouth is None:
            return None
        try:
            path = self.mouth._synth(text)
            with open(path, "rb") as f:
                data = f.read()
            try:
                os.remove(path)  # Alfred's own temp file, same as voice.py does after playing
            except OSError:
                pass
            aid = secrets.token_hex(8)
            now = time.time()
            self.audio = {k: v for k, v in self.audio.items() if now - v[0] < 900}
            self.audio[aid] = (now, data)
            return aid
        except Exception as e:
            self._log("error", where="phone_tts", error=str(e)[:300])
            return None

    def transcribe(self, wav_bytes):
        import numpy as np
        with wave.open(io.BytesIO(wav_bytes), "rb") as w:
            ch, sw, sr, n = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
            raw = w.readframes(n)
        if sw != 2:
            raise ValueError("need 16-bit WAV")
        a = np.frombuffer(raw, dtype=np.int16)
        if ch > 1:
            a = a.reshape(-1, ch).mean(axis=1).astype(np.int16)
        if sr != 16000 and len(a):
            x = np.linspace(0, len(a) - 1, int(len(a) * 16000 / sr))
            a = np.interp(x, np.arange(len(a)), a.astype(np.float32)).astype(np.int16)
        if len(a) < 16000 * 0.3:
            return "", None
        if self.stt is None:
            raise RuntimeError("ears not loaded")
        text, lang = self.stt.transcribe(a)
        try:
            import voice
            if voice.is_hallucination(text):
                return "", lang
        except Exception:
            pass
        return (text or "").strip(), lang

    # ---- one phone request = one brain turn
    def run_turn(self, text, speak_mac=False, emit=None):
        """Blocking. Sends text to Alfred's brain, returns reply text + audio chunks."""
        emit = emit or (lambda ev: None)
        if not self.turn_lock.acquire(timeout=180):
            return {"error": "Alfred is busy with another request."}
        tid = secrets.token_hex(6)
        chunks, lock = [], threading.Lock()
        from concurrent.futures import ThreadPoolExecutor
        pool = ThreadPoolExecutor(max_workers=1)  # Kokoro synthesises one sentence at a time anyway
        futs = []

        def add_chunk(sentence):
            sentence = (sentence or "").strip()
            if not sentence:
                return
            with lock:
                seq = len(chunks)
                chunks.append({"seq": seq, "text": sentence, "audio": None})

            def job():
                aid = self.synth(sentence)
                chunks[seq]["audio"] = aid
                if self.turn is not None and self.turn.get("id") == tid:
                    self.turn["state"] = "speaking"
                emit({"type": "say", "turn": tid, "seq": seq, "text": sentence, "audio": aid})
            futs.append(pool.submit(job))

        try:
            # a voice conversation on the Mac goes first; wait for it to finish its current answer
            t_wait = time.time()
            while getattr(self.brain, "lock", None) is not None and self.brain.lock.locked() and time.time() - t_wait < 120:
                time.sleep(0.2)
            self.turn = {"id": tid, "state": "thinking", "sink": add_chunk, "speak_mac": speak_mac}
            emit({"type": "state", "state": "thinking", "turn": tid})
            try:
                import menubar
                menubar.set_state("thinking", "📱 " + text)
            except Exception:
                pass
            if YES_RE.match(text):
                # same as a spoken "yes": guard.py lets the next risky action through for 60 s
                (self.home / "data" / "confirm.json").write_text(json.dumps({"t": time.time()}))
            self._log("phone", text=text[:500])
            t0 = time.time()
            try:
                reply = self.brain.ask(PHONE_PREFIX + self.vitals_line() + text) or ""
            except Exception as e:
                traceback.print_exc()
                self._log("error", where="phone_ask", error=str(e)[:500])
                reply = "Sorry, sir, I hit an internal error. Details are in the log."
            if getattr(self.brain, "cancelled", False):
                reply = reply or ""
            spoken = " ".join(c["text"] for c in chunks)
            if reply and _norm(reply) not in _norm(spoken):
                rest = reply
                for c in chunks:  # the final answer often repeats the sentences already streamed; keep only the new part
                    rest = rest.replace(c["text"], "", 1)
                add_chunk(rest.strip() if chunks else reply)
            for f in list(futs):
                try:
                    f.result(timeout=120)
                except Exception:
                    pass
            full = "\n".join(c["text"] for c in chunks).strip()  # newlines keep markdown tables intact for the app
            self.last_reply = full
            if speak_mac and reply and self.mouth is not None and _norm(reply) not in _norm(spoken):
                threading.Thread(target=self.mouth.say, args=(reply,), daemon=True).start()
            res = {"turn": tid, "heard": text, "reply": full, "chunks": chunks,
                   "seconds": round(time.time() - t0, 1), "cancelled": bool(getattr(self.brain, "cancelled", False))}
            emit({"type": "reply", **res})
            return res
        finally:
            pool.shutdown(wait=False)
            self.turn = None
            try:
                import menubar
                menubar.set_state("idle")
            except Exception:
                pass
            emit({"type": "state", "state": self.state()})
            self.turn_lock.release()

    def stop(self):
        try:
            if self.turn is not None and self.brain is not None:
                self.brain.cancel()
        except Exception:
            pass
        try:
            if self.mouth is not None:
                self.mouth.stream_stop()
        except Exception:
            pass

    # ---- pairing
    def _notify(self, text):
        try:
            subprocess.Popen(["osascript", "-e", f'display notification "{text}" with title "Alfred · iPhone"'])
        except Exception:
            pass

    def new_pairing(self, notify=True):
        priv, pub = x25519_keypair()
        self.pending = {"session": secrets.token_hex(8), "code": f"{secrets.randbelow(10 ** 6):06d}",
                        "priv": priv, "pub": pub, "until": time.time() + 180, "tries": 0}
        print(f"[phone] pairing code: {self.pending['code']} (valid 3 min)")
        if notify:
            self._notify(f"iPhone pairing code: {self.pending['code']}")
        return self.pending

    def pairing_locked(self):
        now = time.time()
        self.fail_log = [t for t in self.fail_log if now - t < 3600]
        return len(self.fail_log) >= 20

    def pair_start(self, ip, device_name):
        now = time.time()
        hist = [t for t in self.start_log.get(ip, []) if now - t < 60]
        if len(hist) >= 5 or self.pairing_locked():
            return None, "Too many pairing attempts. Wait a minute and try again."
        hist.append(now)
        self.start_log[ip] = hist
        p = self.pending
        if not p or p["until"] < now:
            p = self.new_pairing(notify=True)
        self._log("phone_pair", step="start", ip=ip, device=device_name[:60])
        return {"session": p["session"], "mac_pub": p["pub"].hex(), "expires": int(p["until"] - now)}, None

    def pair_finish(self, ip, session, phone_pub_hex, proof, device_name):
        p = self.pending
        if self.pairing_locked():
            return None, "Pairing is locked for an hour after too many wrong codes."
        if not p or p["session"] != session or p["until"] < time.time():
            return None, "That pairing request expired. Start again."
        try:
            phone_pub = bytes.fromhex(phone_pub_hex)
            assert len(phone_pub) == 32
        except Exception:
            return None, "Bad request."
        shared = x25519(p["priv"], phone_pub)
        if shared == bytes(32):
            return None, "Bad key."
        key = hkdf_sha256(shared, p["code"].encode(), PAIR_INFO.encode())
        expect = _mac(key, b"phone:" + phone_pub + p["pub"])
        if not hmac.compare_digest(expect, str(proof)):
            p["tries"] += 1
            self.fail_log.append(time.time())
            self._log("phone_pair", step="wrong_code", ip=ip)
            if p["tries"] >= 5:
                self.pending = None
                return None, "Wrong code too many times. Start pairing again."
            return None, "Wrong code."
        device_id = secrets.token_hex(8)
        self.tokens.add(device_id, key, device_name or "iPhone")
        self.pending = None
        self._log("phone_pair", step="paired", ip=ip, device=device_name[:60])
        self._notify(f"Paired with {device_name or 'iPhone'}")
        return {"device_id": device_id, "proof": _mac(key, b"mac:" + p["pub"] + phone_pub), "name": socket.gethostname()}, None

    # ---- request signing
    def verify(self, request, body: bytes):
        dev = request.headers.get("X-Alfred-Device", "")
        ts = request.headers.get("X-Alfred-Time", "")
        sig = request.headers.get("X-Alfred-Sig", "")
        nonce = request.headers.get("X-Alfred-Nonce", "")[:64]
        if not dev or not ts or not sig:
            return None
        try:
            if abs(time.time() - float(ts)) > 120:
                return None
        except ValueError:
            return None
        key = self.tokens.key(dev)
        if not key:
            return None
        path = request.rel_url.path
        msg = f"{request.method}\n{path}\n{ts}\n{nonce}\n{hashlib.sha256(body).hexdigest()}".encode()
        if not hmac.compare_digest(_mac(key, msg), sig):
            return None
        now = time.time()
        if sig in self.seen_sigs:
            return None
        self.seen_sigs = {s: t for s, t in self.seen_sigs.items() if now - t < 300}
        self.seen_sigs[sig] = now
        self.tokens.touch(dev)
        return dev

    # ---- web server
    def broadcast(self, ev, device=None):
        """Status goes to every phone; a turn's events (heard / say / reply) only to the phone that asked."""
        if not self.loop:
            return
        data = json.dumps(ev, ensure_ascii=False)
        for ws in list(self.ws_clients):
            if device and self.ws_device.get(ws) not in (None, device):
                continue
            try:
                asyncio.run_coroutine_threadsafe(ws.send_str(data), self.loop)
            except Exception:
                pass

    def make_app(self):
        from aiohttp import web

        def ip_of(req):
            return req.remote or "?"

        async def body_of(req, limit=12 * 1024 * 1024):
            # read() waits for the WHOLE body (content.read(n) can return just the first network chunk,
            # which broke the signature check on voice recordings)
            if req.content_length and req.content_length > limit:
                raise web.HTTPRequestEntityTooLarge(max_size=limit, actual_size=req.content_length)
            return await req.read()

        async def authed(req):
            body = await body_of(req)
            dev = self.verify(req, body)
            if not dev:
                raise web.HTTPUnauthorized(text=json.dumps({"error": "not paired"}), content_type="application/json")
            return dev, body

        async def hello(req):
            return web.json_response({"name": "Alfred", "mac": socket.gethostname(), "version": VERSION,
                                      "pairing_locked": self.pairing_locked()})

        async def pair_start(req):
            try:
                j = json.loads(await body_of(req, 4096) or b"{}")
            except Exception:
                j = {}
            res, err = self.pair_start(ip_of(req), str(j.get("device_name", "iPhone")))
            return web.json_response(res) if res else web.json_response({"error": err}, status=429)

        async def pair_finish(req):
            try:
                j = json.loads(await body_of(req, 4096))
            except Exception:
                return web.json_response({"error": "Bad request."}, status=400)
            res, err = self.pair_finish(ip_of(req), str(j.get("session", "")), str(j.get("phone_pub", "")),
                                        str(j.get("proof", "")), str(j.get("device_name", "iPhone")))
            return web.json_response(res) if res else web.json_response({"error": err}, status=403)

        async def pair_page(req):
            # only from this Mac itself: shows the code + QR for the phone to scan
            if ip_of(req) not in ("127.0.0.1", "::1"):
                raise web.HTTPForbidden()
            p = self.pending if self.pending and self.pending["until"] > time.time() + 30 else self.new_pairing(notify=False)
            _, lan, ts = bind_hosts()
            host = (ts or lan or ["127.0.0.1"])[0]  # Tailscale works through any router and away from home
            url = f"alfred://pair?host={host}&port={self.port}&code={p['code']}" + (f"&ts={ts[0]}" if ts else "")
            svg = _qr_svg(url)
            html = PAIR_HTML.replace("{CODE}", f"{p['code'][:3]} {p['code'][3:]}").replace("{QR}", svg) \
                .replace("{HOST}", host).replace("{TS}", ts[0] if ts else "—")
            return web.Response(text=html, content_type="text/html")

        async def text(req):
            dev, body = await authed(req)
            try:
                j = json.loads(body)
                t = str(j.get("text", "")).strip()[:4000]
            except Exception:
                return web.json_response({"error": "Bad request."}, status=400)
            if not t:
                return web.json_response({"error": "Empty message."}, status=400)
            self.last_heard = t
            res = await asyncio.get_running_loop().run_in_executor(
                None, lambda: self.run_turn(t, bool(j.get("speak_mac")), lambda ev: self.broadcast(ev, dev)))
            return web.json_response(res, status=200 if "error" not in res else 409)

        async def voice_in(req):
            dev, body = await authed(req)
            speak_mac = req.query.get("speak_mac") == "1"
            self.broadcast({"type": "state", "state": "listening"}, dev)
            loop = asyncio.get_running_loop()
            try:
                heard, lang = await loop.run_in_executor(None, self.transcribe, body)
            except Exception as e:
                self._log("error", where="phone_stt", error=str(e)[:300])
                return web.json_response({"error": f"Could not understand the audio ({e})."}, status=400)
            self.last_heard = heard
            self.broadcast({"type": "heard", "text": heard, "lang": lang}, dev)
            if not heard:
                self.broadcast({"type": "state", "state": self.state()})
                return web.json_response({"heard": "", "reply": "", "chunks": [], "lang": lang})
            res = await loop.run_in_executor(None, lambda: self.run_turn(heard, speak_mac, lambda ev: self.broadcast(ev, dev)))
            res["lang"] = lang
            return web.json_response(res, status=200 if "error" not in res else 409)

        async def audio(req):
            await authed(req)
            aid = req.match_info["aid"]
            item = self.audio.get(aid)
            if not item:
                raise web.HTTPNotFound()
            return web.Response(body=item[1], content_type="audio/wav")

        async def status(req):
            await authed(req)
            return web.json_response(self.status())

        async def stop(req):
            await authed(req)
            await asyncio.get_running_loop().run_in_executor(None, self.stop)
            return web.json_response({"ok": True})

        async def unpair(req):
            dev, _ = await authed(req)
            self.tokens.revoke(dev)
            self._log("phone_pair", step="unpaired", device=dev)
            return web.json_response({"ok": True})

        async def ws_handler(req):
            dev, _ = await authed(req)
            ws = web.WebSocketResponse(heartbeat=20)
            await ws.prepare(req)
            self.ws_clients.add(ws)
            self.ws_device[ws] = dev
            try:
                await ws.send_str(json.dumps({"type": "status", **self.status()}, ensure_ascii=False))
                async for _ in ws:
                    pass  # the phone only listens
            finally:
                self.ws_clients.discard(ws)
                self.ws_device.pop(ws, None)
            return ws

        app = web.Application(client_max_size=12 * 1024 * 1024)
        app.router.add_get("/api/hello", hello)
        app.router.add_post("/api/pair/start", pair_start)
        app.router.add_post("/api/pair/finish", pair_finish)
        app.router.add_get("/pair", pair_page)
        app.router.add_post("/api/text", text)
        app.router.add_post("/api/voice", voice_in)
        app.router.add_get("/api/audio/{aid}.wav", audio)
        app.router.add_get("/api/status", status)
        app.router.add_post("/api/stop", stop)
        app.router.add_post("/api/unpair", unpair)
        app.router.add_get("/ws", ws_handler)
        return app

    async def _status_pusher(self):
        last = None
        while True:
            await asyncio.sleep(0.4)
            if not self.ws_clients:
                continue
            s = self.status()
            sig = json.dumps([s["state"], s["panels"], s["hologram"]], sort_keys=True)
            if sig != last:
                last = sig
                self.broadcast({"type": "status", **s})

    async def _rebind(self):
        from aiohttp import web
        while True:
            hosts, lan, ts = bind_hosts()
            for h in list(self.sites):
                if h not in hosts:
                    try:
                        await self.sites.pop(h).stop()
                    except Exception:
                        pass
            for h in hosts:
                if h not in self.sites:
                    try:
                        site = web.TCPSite(self.runner, h, self.port, reuse_address=True)
                        await site.start()
                        self.sites[h] = site
                        print(f"[phone] listening on {h}:{self.port}")
                    except OSError as e:
                        print(f"[phone] cannot listen on {h}:{self.port}: {e}")
            self._bonjour(lan)
            await asyncio.sleep(30)

    def _bonjour(self, lan):
        host = lan[0] if lan else ""
        if self.bonjour and self.bonjour[1] == host and self.bonjour[0].poll() is None:
            return
        if self.bonjour:
            try:
                self.bonjour[0].terminate()
                subprocess.run(["pkill", "-f", f"dns-sd -R .*_alfred._tcp local {self.port}"], timeout=3)
            except Exception:
                pass
            self.bonjour = None
        if not host:
            return
        try:
            name = f"Alfred on {socket.gethostname().split('.')[0]}"
            # the announcement ends by itself when Alfred exits (the shell watches our process id)
            script = ('dns-sd -R "$1" _alfred._tcp local "$2" "host=$3" "port=$2" "v=$4" >/dev/null 2>&1 & c=$!; '
                      'while kill -0 "$5" 2>/dev/null && kill -0 $c 2>/dev/null; do sleep 3; done; kill $c 2>/dev/null')
            p = subprocess.Popen(["/bin/sh", "-c", script, "sh", name, str(self.port), host, VERSION, str(os.getpid())],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.bonjour = (p, host)
        except Exception as e:
            print("[phone] bonjour:", e)

    async def _main(self):
        from aiohttp import web
        self.loop = asyncio.get_running_loop()
        self.runner = web.AppRunner(self.make_app(), access_log=None)
        await self.runner.setup()
        asyncio.create_task(self._status_pusher())
        await self._rebind()

    def serve_forever(self):
        try:
            asyncio.run(self._main())
        except Exception as e:
            traceback.print_exc()
            self._log("error", where="phone_bridge", error=str(e)[:300])
        finally:
            if self.bonjour:
                try:
                    self.bonjour[0].terminate()
                except Exception:
                    pass


def _norm(x):
    return " ".join(re.findall(r"\w+", (x or "").lower()))


def _qr_svg(text):
    try:
        import qrcode
        import qrcode.image.svg
        img = qrcode.make(text, image_factory=qrcode.image.svg.SvgPathImage, box_size=12, border=2)
        s = img.to_string().decode() if isinstance(img.to_string(), bytes) else img.to_string()
        return s[s.find("<svg"):]
    except Exception as e:
        return f"<p>(QR unavailable: {e})</p>"


PAIR_HTML = """<!doctype html><html><head><meta charset="utf-8"><title>Pair iPhone · Alfred</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
:root{color-scheme:dark}body{margin:0;background:#050403;color:#ffcf8a;font:16px -apple-system,system-ui,sans-serif;
display:grid;place-items:center;min-height:100vh}
.card{text-align:center;padding:40px 48px;border:1px solid #ff9f1c33;border-radius:28px;background:radial-gradient(circle at 50% 0,#2a1600,#0b0805 70%)}
h1{font-weight:600;letter-spacing:.3em;font-size:14px;color:#ff9f1c;margin:0 0 24px}
.qr{background:#ffe9c7;border-radius:18px;padding:14px;display:inline-block}.qr svg{width:240px;height:240px;display:block}
.code{font:600 56px ui-monospace,Menlo,monospace;letter-spacing:.12em;margin:22px 0 6px;color:#fff1dc}
.s{opacity:.6;font-size:13px;line-height:1.6}
</style></head><body><div class="card"><h1>Alfred · PAIR IPHONE</h1>
<div class="qr">{QR}</div><div class="code">{CODE}</div>
<div class="s">Scan with the Alfred app, or type the code.<br>Valid 3 minutes · Home network {HOST} · Tailscale {TS}</div>
</div></body></html>"""


# ---------------------------------------------------------------- entry points
_BRIDGE = {}


def start(cfg, brain, mouth, ear=None, log=None, home=HOME):
    """Called from alfred.py. Starts the bridge in a background thread and returns at once."""
    if _BRIDGE.get("b"):
        return _BRIDGE["b"]
    b = Bridge(cfg, brain, mouth, ear=ear, log=log, home=home)
    threading.Thread(target=b.serve_forever, daemon=True, name="phone-bridge").start()
    _BRIDGE["b"] = b
    print(f"[phone] bridge started on port {b.port}")
    return b


class _EchoBrain:
    """Test-only brain (no Claude): answers instantly, sentence by sentence."""
    def __init__(self):
        self.lock = threading.Lock()
        self.on_progress = None
        self.cancelled = False

    def ask(self, text):
        with self.lock:
            self.cancelled = False
            said = re.sub(r"^(\[[^\]]*\]\s*)+", "", text)  # drop the bridge's [context] blocks
            for s in ["Test mode, sir.", f"You said: {said}"]:
                time.sleep(0.4)
                if self.on_progress:
                    self.on_progress(s)
            return ""

    def cancel(self):
        self.cancelled = True


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Alfred phone bridge (test mode). Normally runs inside alfred.py.")
    ap.add_argument("--echo", action="store_true", help="test brain that just repeats you (no Claude)")
    ap.add_argument("--ears", action="store_true", help="load Whisper for /api/voice (uses ~0.5 GB RAM)")
    ap.add_argument("--port", type=int, default=None)
    ap.add_argument("--selftest", action="store_true", help="check the crypto against RFC 7748")
    a = ap.parse_args()
    if a.selftest:
        k = bytes.fromhex("a546e36bf0527c9d3b16154b82465edd62144c0ac1fc5a18506a2244ba449ac4")
        u = bytes.fromhex("e6db6867583030db3594c1a424b15f7c726624ec26b3353b10a903a6d0ab1c4c")
        assert x25519(k, u).hex() == "c3da55379de9c6908e94ea4df28d084f32eccf03491c71f754b4075577a28552"
        a1, A1 = x25519_keypair()
        b1, B1 = x25519_keypair()
        assert x25519(a1, B1) == x25519(b1, A1)
        print("crypto ok")
        raise SystemExit(0)
    import sys
    sys.path.insert(0, str(HOME))
    cfg = json.loads((HOME / "config.json").read_text(encoding="utf-8"))
    if a.port:
        cfg["phone_bridge_port"] = a.port
    import voice
    mouth = voice.Mouth(cfg)
    stt = voice.STT(cfg) if a.ears else None
    if not a.echo:
        raise SystemExit("Standalone mode only supports --echo (a real brain runs inside alfred.py).")
    b = Bridge(cfg, _EchoBrain(), mouth, stt=stt)
    b.serve_forever()
