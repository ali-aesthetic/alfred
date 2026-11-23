"""Checks for the address setting, greeting and spoken commands. Run: python tests/test_address.py"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import address as a

S = {"address": "sir", "name": "Sam", "voice": "bm_lewis"}
def get(k): return S.get(k)
def setk(k, v): S[k] = v

cases = [("don't call me sir", "name"), ("call me ma'am", "ma'am"), ("Alfred, call me madam", "ma'am"),
         ("just use my name", "name"), ("stop addressing me", "none"), ("call me sir", "sir"), ("what time is it", None)]
for text, want in cases:
    assert a.parse(text, "sir", "Sam") == want, (text, a.parse(text, "sir", "Sam"), want)
assert a.parse("just use my name", "sir", "") is None            # no name known: brain asks
assert a.greeting("sir") == "At your service, sir."
assert a.greeting("ma'am") == "At your service, ma'am."
assert a.greeting("none") == "At your service."
assert a.greeting("name", "Sam") == "At your service, Sam."
assert a.default_voice("sir") == "bm_lewis" and a.default_voice("ma'am") == "bf_isabella" and a.default_voice("name") is None

seen = []
a.on_change = lambda new, voice: seen.append((new, voice))
assert a.apply_spoken("call me ma'am", get, setk) == "Very good."
assert S["address"] == "ma'am" and S["voice"] == "bf_isabella" and seen == [("ma'am", "bf_isabella")]
S["voice_follows_address"] = False                               # user picked a voice themselves
assert a.apply_spoken("call me sir", get, setk) == "Very good." and S["voice"] == "bf_isabella"
assert a.apply_spoken("open Notes", get, setk) is None
print("address tests passed")
