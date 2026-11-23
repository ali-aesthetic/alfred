"""How Alfred addresses you: Sir / Ma'am / your name / nothing — and the spoken commands that change it.

Setting `address` (settings.json + config.json): "sir" | "ma'am" | "name" | "none".
Legacy values still work: "boss", "madam", "ma'am", or any other word = used as is.
The default voice follows the address (Sir -> bm_lewis, Ma'am -> bf_isabella) until you pick a voice yourself.
"""
import re

OPTIONS = ("sir", "ma'am", "name", "none")
VOICE_FOR = {"sir": "bm_lewis", "ma'am": "bf_isabella"}
GREETING = "At your service."
CONFIRM = "Very good."

# set by alfred.py: called with (address, voice_or_None) after a spoken change so live settings update
on_change = None


def norm(a):
    a = str(a or "sir").strip().lower().replace("’", "'")
    if a in ("madam", "mam", "maam", "ma am", "ma'am"):
        return "ma'am"
    if a in ("sir", "name", "none"):
        return a
    if a in ("", "nothing", "no"):
        return "none"
    return a  # legacy custom word ("boss")


def word(address, user_name=""):
    """The word to say. "" means: do not address the user at all."""
    a = norm(address)
    if a == "name":
        return (user_name or "").strip()
    if a == "none":
        return ""
    return a


def with_address(text, address, user_name=""):
    """'Done.' + sir -> 'Done, sir.'  (no address -> text unchanged)"""
    w = word(address, user_name)
    if not w:
        return text
    t = text.rstrip()
    end = t[-1] if t and t[-1] in ".!?" else ""
    core = t[:-1] if end else t
    return f"{core}, {w}{end or '.'}"


def greeting(address, user_name=""):
    """'At your service.' — with the address added when one is set ('At your service, sir.')."""
    return with_address(GREETING, address, user_name)


def default_voice(address):
    return VOICE_FOR.get(norm(address))


_SIR = r"(?:sir|mister|mr)"
_MAAM = r"(?:ma'?am|madam|mam|miss|lady)"
_PAT = [
    (r"\b(?:don'?t|do not|stop|quit|never) (?:call|calling|address|addressing) me (?:sir|ma'?am|madam|anything|that)\b", "dont"),
    (r"\b(?:just |only )?(?:use|call me by|say) my name\b|\bcall me by (?:my )?name\b", "name"),
    (r"\bcall me " + _MAAM + r"\b|\baddress me as " + _MAAM + r"\b", "ma'am"),
    (r"\bcall me " + _SIR + r"\b|\baddress me as " + _SIR + r"\b", "sir"),
    (r"\b(?:stop|quit) (?:addressing|calling) me$", "none"),
    (r"\b(?:don'?t|stop|no need to) (?:call|address) me (?:anything|by anything)\b|\bno (?:title|titles)\b|\bdon'?t (?:address|call) me at all\b", "none"),
]


def parse(text, current="sir", user_name=""):
    """Spoken command -> new address ("sir"/"ma'am"/"name"/"none") or None when it is not an address command."""
    t = re.sub(r"\s+", " ", str(text or "").lower().replace("’", "'")).strip(" .!?,")
    t = re.sub(r"^(hey |ok )?alfred[,\s]+", "", t)
    for pat, val in _PAT:
        if re.search(pat, t):
            if val == "dont":
                # "don't call me sir" -> use the name if we know it, else nothing
                return "name" if (user_name or "").strip() else "none"
            if val == "name" and not (user_name or "").strip():
                return None  # nothing to use; let the brain ask for the name
            return val
    return None


def apply_spoken(text, get_setting, set_setting):
    """Handle an address command. Returns the one confirmation line ('Very good.') or None."""
    cur = get_setting("address") or "sir"
    new = parse(text, cur, get_setting("name") or "")
    if new is None:
        return None
    set_setting("address", new)
    voice = None
    if get_setting("voice_follows_address") is not False and default_voice(new):
        voice = default_voice(new)
        set_setting("voice", voice)
    if on_change:
        try:
            on_change(new, voice)
        except Exception as e:  # never break a turn
            print("[address]", str(e)[:120])
    return CONFIRM
