"""Brain plug-in layer. `make(cfg, ...)` returns the brain chosen in config.json ("brain": id).

| id                   | what                                   | computer control | status       |
|----------------------|----------------------------------------|------------------|--------------|
| claude-subscription  | Claude Code CLI, your own subscription | strong           | ready        |
| claude-api           | Anthropic API key                      | strong           | ready (see README: needs a key) |
| openai-codex         | Codex CLI, ChatGPT login               | none yet         | experimental |
| openai-compatible    | any OpenAI-style API / LM Studio       | none yet         | experimental |
| ollama               | local models                           | none yet         | experimental |
"""
from .base import BrainBase, BrainInfo, BrainNotReady, chat_system_prompt  # noqa: F401

ALIASES = {"subscription": "claude-subscription", "api": "claude-api", "claude": "claude-subscription",
           "codex": "openai-codex", "openai": "openai-compatible", "local": "ollama"}

INFOS = [
    BrainInfo("claude-subscription", "Claude (your subscription)",
              "Best at controlling your Mac. Uses your own Claude plan through the Claude Code tool; Alfred never sees your login.",
              "strong", "ready", "Run `claude` once and sign in (Anthropic's own browser page)."),
    BrainInfo("claude-api", "Claude (API key)",
              "Same strength as above, billed per use on your Anthropic API key.",
              "strong", "ready", "Put your key in Keychain item 'alfred-anthropic' or the ANTHROPIC_API_KEY environment variable."),
]


def infos():
    """All brains, for Settings and docs. Computer control is strongest on Claude, weaker on small local models."""
    from .openai_codex import CodexBrain
    from .openai_compat import OpenAICompatBrain
    from .ollama import OllamaBrain
    return INFOS + [CodexBrain.info, OpenAICompatBrain.info, OllamaBrain.info]


def canonical(name):
    n = str(name or "claude-subscription").strip().lower()
    return ALIASES.get(n, n)


def make_plugin(cfg, home):
    """Build one of the simple (non-Claude) brains."""
    bid = canonical(cfg.get("brain"))
    if bid == "openai-codex":
        from .openai_codex import CodexBrain
        return CodexBrain(cfg, home)
    if bid == "openai-compatible":
        from .openai_compat import OpenAICompatBrain
        return OpenAICompatBrain(cfg, home)
    if bid == "ollama":
        from .ollama import OllamaBrain
        return OllamaBrain(cfg, home)
    raise ValueError(f"Unknown brain: {bid}")


class Adapter:
    """Gives a plug-in brain the few extra methods Alfred's main loop calls, and turns errors into a spoken sentence."""

    def __init__(self, brain, cfg):
        self._b, self.cfg = brain, cfg
        self.on_progress = None
        self.info = brain.info

    def ask(self, text):
        import address as _address
        w = _address.word(self.cfg.get("address", "sir"), self.cfg.get("user_name", ""))
        pre = (w.capitalize() + ", ") if w else ""
        try:
            return self._b.ask(text) or "I have nothing to say to that."
        except BrainNotReady as e:
            return f"{pre}this brain is not ready. {e}"
        except Exception as e:  # network, timeout, bad JSON …
            print("[brain]", self._b.info.id, str(e)[:200])
            return f"{pre}I lost the link to my brain. Please try again."

    def cancel(self):
        self._b.cancel()

    def warm(self):
        self._b.warm()

    def learn(self):
        return self._b.learn()

    def reflect(self, force=False):
        return self._b.reflect(force)

    def _kill(self):
        self._b.close()
