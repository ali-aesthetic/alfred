"""OpenAI-compatible API brain (OpenAI, OpenRouter, LM Studio, vLLM, llama.cpp server …). EXPERIMENTAL: chat only."""
import json
import os
import subprocess
import urllib.request

from .base import BrainBase, BrainInfo, BrainNotReady, chat_system_prompt


def _key(cfg, home):
    k = os.environ.get(cfg.get("openai_key_env", "OPENAI_API_KEY"), "").strip()
    if k:
        return k
    r = subprocess.run(["security", "find-generic-password", "-s", "alfred-openai", "-w"], capture_output=True, text=True)
    if r.returncode == 0 and r.stdout.strip():
        return r.stdout.strip()
    p = home / "data" / "openai_key"
    return p.read_text().strip() if p.exists() else ""


class OpenAICompatBrain(BrainBase):
    info = BrainInfo(
        id="openai-compatible", label="OpenAI-compatible API",
        note="Chat only for now. Computer control is not connected for this brain; it is strongest on Claude.",
        computer_control="none", status="experimental",
        setup="Set openai_base_url and openai_model in config.json, and put your key in the OPENAI_API_KEY environment variable or Keychain item 'alfred-openai'.")

    def __init__(self, cfg, home):
        super().__init__(cfg, home)
        self.base = cfg.get("openai_base_url", "https://api.openai.com/v1").rstrip("/")
        self.model = cfg.get("openai_model", "")
        self.history = []

    def check(self):
        if not self.model:
            return False, "Set openai_model in config.json."
        local = self.base.startswith(("http://127.0.0.1", "http://localhost"))
        if not local and not _key(self.cfg, self.home):
            return False, "No API key found (OPENAI_API_KEY or Keychain item 'alfred-openai')."
        return True, "ready"

    def ask(self, text):
        ok, msg = self.check()
        if not ok:
            raise BrainNotReady(msg)
        self.history = (self.history + [{"role": "user", "content": text}])[-20:]
        body = {"model": self.model, "messages": [{"role": "system", "content": chat_system_prompt(self.cfg)}] + self.history,
                "max_tokens": int(self.cfg.get("max_tokens", 300))}
        h = {"Content-Type": "application/json"}
        k = _key(self.cfg, self.home)
        if k:
            h["Authorization"] = "Bearer " + k
        req = urllib.request.Request(self.base + "/chat/completions", data=json.dumps(body).encode(), headers=h)
        with urllib.request.urlopen(req, timeout=int(self.cfg.get("brain_timeout", 90))) as r:
            out = json.loads(r.read())
        reply = (out["choices"][0]["message"]["content"] or "").strip()
        self.history.append({"role": "assistant", "content": reply})
        return reply
