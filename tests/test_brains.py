"""Plumbing tests for the brain plug-ins against a local mock server (NOT against real OpenAI/Ollama).
Run:  python tests/test_brains.py"""
import json, os, sys, threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import brains


class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _send(self, o):
        b = json.dumps(o).encode(); self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(b)
    def do_GET(self): self._send({"models": [{"name": "tiny:latest"}]})
    def do_POST(self):
        n = int(self.headers["Content-Length"]); body = json.loads(self.rfile.read(n))
        assert body["messages"][0]["role"] == "system" and "Alfred" in body["messages"][0]["content"]
        if self.path.endswith("/chat/completions"): self._send({"choices": [{"message": {"content": "Very good."}}]})
        else: self._send({"message": {"content": "Indeed."}})

srv = HTTPServer(("127.0.0.1", 0), H); port = srv.server_port
threading.Thread(target=srv.serve_forever, daemon=True).start()
home = Path(os.environ.get("ALFRED_HOME") or "/tmp/alfred-test"); (home / "data").mkdir(parents=True, exist_ok=True)

b = brains.Adapter(brains.make_plugin({"brain": "openai-compatible", "openai_base_url": f"http://127.0.0.1:{port}/v1", "openai_model": "m", "address": "ma'am"}, home), {"address": "ma'am"})
assert b.ask("hi") == "Very good.", "openai-compatible"
b = brains.Adapter(brains.make_plugin({"brain": "ollama", "ollama_host": f"http://127.0.0.1:{port}", "ollama_model": "tiny"}, home), {"address": "sir"})
assert b.ask("hi") == "Indeed.", "ollama"
b = brains.Adapter(brains.make_plugin({"brain": "ollama", "ollama_host": f"http://127.0.0.1:{port}", "ollama_model": "missing"}, home), {"address": "sir"})
assert "not ready" in b.ask("hi") and "ollama pull" in b.ask("hi"), "ollama missing model"
b = brains.Adapter(brains.make_plugin({"brain": "ollama", "ollama_host": "http://127.0.0.1:9", "ollama_model": "x"}, home), {"address": "none"})
assert "not running" in b.ask("hi"), "ollama down"
assert brains.canonical("subscription") == "claude-subscription" and brains.canonical("api") == "claude-api"
assert len(brains.infos()) == 5
print("brain plug-in tests passed (mock server)")
