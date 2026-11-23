"""The Brain interface — the one small contract every "brain" follows.

A brain takes what you said (text) and returns what Alfred should say back. Some brains can also drive your Mac
(open apps, click, type). How well that works depends on the model, so each brain declares what it can do honestly.

Required:
    ask(text) -> str          answer one request (blocking)
Optional (defaults do nothing):
    cancel()                  stop the current answer (barge-in)
    warm()                    pre-load so the first answer is fast
    close()
    on_progress               callable(str) set by Alfred; call it with short "doing X" sentences while working
Class attributes (shown in Settings and the README):
    id, label, note, computer_control ("strong" | "limited" | "none"), status ("ready" | "experimental")
"""
from dataclasses import dataclass


class BrainNotReady(Exception):
    """Raised by check()/ask() when a brain is not set up (missing login, key, or server). Message is user-readable."""


@dataclass(frozen=True)
class BrainInfo:
    id: str
    label: str
    note: str
    computer_control: str   # "strong" | "limited" | "none"
    status: str             # "ready" = used daily by the author | "experimental" = not verified end to end
    setup: str              # one-line how to set it up


class BrainBase:
    info: BrainInfo
    on_progress = None

    def __init__(self, cfg, home):
        self.cfg = cfg
        self.home = home

    def check(self):
        """Return (ok: bool, message: str). Must be fast and never raise."""
        return True, "ready"

    def ask(self, text: str) -> str:  # pragma: no cover - interface
        raise NotImplementedError

    def cancel(self):
        pass

    def warm(self):
        pass

    def close(self):
        pass

    # the daily self-review hooks Alfred calls; brains without memory skip them
    def learn(self):
        return {}

    def reflect(self, force=False):
        return ""


def chat_system_prompt(cfg, note=""):
    """Persona for chat-only brains (no computer control)."""
    import address as _address
    name = cfg.get("user_name") or "the user"
    w = _address.word(cfg.get("address", "sir"), cfg.get("user_name", ""))
    call = f'Address them as "{w}" once, at the end.' if w else "Do not address them by title or name."
    return (f"You are Alfred, the personal voice assistant of {name}, like Alfred the Batman butler: calm, polite, dry British wit, loyal. "
            f"{call} You are spoken aloud: answer in one to three short sentences, plain words, no markdown, no lists, no emoji. "
            "You can chat and answer questions. " + (note or "You cannot control the computer in this mode; if asked to, say so briefly and offer what you can do."))
