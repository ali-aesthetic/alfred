"""Ollama / local models brain. EXPERIMENTAL: chat only; small local models are weak at controlling a computer."""
import json
import urllib.request

from .base import BrainBase, BrainInfo, BrainNotReady, chat_system_prompt


class OllamaBrain(BrainBase):
    info = BrainInfo(
        id="ollama", label="Local model (Ollama)",
        note="Runs on your Mac, private and free. Chat only for now; computer control is weaker on small local models than on Claude.",
        computer_control="none", status="experimental",
        setup="Install Ollama (ollama.com), run `ollama pull <model>`, then set ollama_model in config.json.")

    def __init__(self, cfg, home):
        super().__init__(cfg, home)
        self.host = cfg.get("ollama_host", "http://127.0.0.1:11434").rstrip("/")
        self.model = cfg.get("ollama_model", "")
        self.history = []

    def _get(self, path):
        with urllib.request.urlopen(self.host + path, timeout=3) as r:
            return json.loads(r.read())

    def check(self):
        try:
            tags = self._get("/api/tags")
        except Exception:
            return False, "Ollama is not running. Open the Ollama app, or run `ollama serve`."
        names = [m.get("name", "") for m in tags.get("models", [])]
        if not self.model:
            return False, "Set ollama_model in config.json. Installed: " + (", ".join(names) or "none yet")
        if not any(n == self.model or n.split(":")[0] == self.model for n in names):
            return False, f"Model '{self.model}' is not installed. Run: ollama pull {self.model}"
        return True, "ready"

    def ask(self, text):
        ok, msg = self.check()
        if not ok:
            raise BrainNotReady(msg)
        self.history = (self.history + [{"role": "user", "content": text}])[-20:]
        body = {"model": self.model, "stream": False,
                "messages": [{"role": "system", "content": chat_system_prompt(self.cfg)}] + self.history}
        req = urllib.request.Request(self.host + "/api/chat", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=int(self.cfg.get("brain_timeout", 120))) as r:
            reply = (json.loads(r.read()).get("message", {}).get("content") or "").strip()
        self.history.append({"role": "assistant", "content": reply})
        return reply
