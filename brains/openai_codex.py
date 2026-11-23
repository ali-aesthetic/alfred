"""OpenAI Codex CLI brain (sign in with your ChatGPT account). EXPERIMENTAL / UNTESTED stub: chat via `codex exec`."""
import shutil
import subprocess

from .base import BrainBase, BrainInfo, BrainNotReady, chat_system_prompt


class CodexBrain(BrainBase):
    info = BrainInfo(
        id="openai-codex", label="ChatGPT account (Codex CLI)",
        note="Stub: not tested end to end. Chat only; computer control is not connected.",
        computer_control="none", status="experimental",
        setup="Install the Codex CLI, run `codex` once and sign in with ChatGPT (opens OpenAI's own browser page).")

    def _bin(self):
        return shutil.which("codex") or shutil.which("codex", path="/opt/homebrew/bin:/usr/local/bin")

    def check(self):
        return (True, "ready") if self._bin() else (False, "Codex CLI not found. Install it, then run `codex` once to sign in.")

    def ask(self, text):
        ok, msg = self.check()
        if not ok:
            raise BrainNotReady(msg)
        prompt = chat_system_prompt(self.cfg) + "\n\nUser: " + text
        r = subprocess.run([self._bin(), "exec", "--skip-git-repo-check", prompt], capture_output=True, text=True,
                           timeout=int(self.cfg.get("brain_timeout", 120)), cwd=str(self.home / "data"))
        if r.returncode != 0:
            raise BrainNotReady((r.stderr or "codex failed").strip()[-300:])
        return r.stdout.strip()
