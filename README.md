# Alfred

**A calm, polite voice assistant that lives on your Mac. "At your service."**
Talk to it, and it opens apps, finds files, writes, searches, clicks and types for you, with the dry wit of a very good butler. Mac only (Apple Silicon, macOS 14+). MIT licence.

> Status: **early release**. Built and checked on the author's Mac; see [What is tested](#what-is-tested) for exactly what.

## Install (pick one)

| | Who | Steps |
|---|---|---|
| **A. Alfred.dmg** | most people | download `Alfred.dmg` from Releases → drag to Applications → [3 steps to open it](#opening-an-unsigned-app) → follow the setup guide |
| **B. One line** | comfortable with Terminal | `curl -fsSL https://raw.githubusercontent.com/<GH_USER>/alfred/main/install.sh \| bash` |
| **C. From source** | developers | `git clone` → `bash install.sh` (or `cd mac-app && bash build.sh`) |

The app is small. On first run it downloads Python and the voice models (about 1.5 GB) with a real progress bar you can pause.

### Opening an unsigned app
Alfred is not signed by Apple yet (the author has no paid Apple account), so macOS blocks the first launch. You do this once:

1. **Open Alfred.** macOS says it can't verify it. Press **Done**.
2. Open **System Settings → Privacy & Security** and scroll to "Alfred was blocked". Press **Open Anyway**.
3. Press **Open Anyway** again and enter your Mac password. Done: Alfred starts its setup guide.

## What you need
- An Apple Silicon Mac (M1 or later), macOS 14 or newer, about 6 GB free.
- A brain (see below). The easiest is a Claude subscription: Alfred uses the Claude Code tool, and you sign in on Anthropic's own web page. **Alfred never sees your login.**

## How it works
```
 your voice ─► ears (Whisper, on your Mac) ─► brain ─► voice (Kokoro, on your Mac)
                                               │
                                               └─► hands: open apps, click, type (alfred-ctl, AppleScript)
```

## Brains: who thinks for Alfred
| Brain | Computer control | Status |
|---|---|---|
| **Claude, your subscription** (Claude Code CLI) | strong | the one the author uses daily |
| **Claude, API key** | strong | code path kept from an earlier version; **not re-tested live in this release** (no key was used) |
| ChatGPT account (Codex CLI) | none yet | **stub, untested** |
| OpenAI-compatible API (OpenAI, LM Studio …) | none yet | chat only; tested against a mock server only |
| Local model (Ollama) | none yet | chat only; tested against a mock server only |

**Computer control is strongest on Claude and weaker on small local models.** The experimental brains can chat but do not drive your Mac yet. Choose in Settings → Brain, then "Restart my brain". The interface is small: see `brains/base.py`.

## Talking to Alfred
- Say **"Alfred, …"** or hold **right ⌥ (Option)**, talk, let go.
- **How he addresses you:** Settings → Sir · Ma'am · My name · Nothing. Or say "call me ma'am", "don't call me sir", "just use my name". He answers "Very good." once. The offline voice follows (Sir → Lewis, Ma'am → Isabella) until you pick a voice yourself.
- Voice samples: `docs/voices/`.
- Wake word: until **"Hey Alfred"** is trained (guide: [docs/TRAIN-HEY-ALFRED.md](docs/TRAIN-HEY-ALFRED.md)), Alfred listens for his name through speech recognition, or use the hold key.

## Permissions (the setup guide shows pictures)
Microphone (hear you) · Accessibility (click and type) · Screen Recording (optional: see the screen) · Input Monitoring (optional: the hold key) · Automation (asked when needed). Re-open the guide any time: **Help → Setup Guide**.

## Folders
Everything lives in one place, set by **`ALFRED_HOME`** (default `~/Library/Application Support/Alfred`): code, `data/` (memory, logs, settings), `models/`, `.venv/`. Alfred never deletes files; leftovers go to a `to delete` folder for you to empty.

## Languages
English is the default. An optional Russian/Uzbek pack: `python apply_language_pack.py ru`. Some code comments and the hologram helpers are still partly in Russian (see Known gaps).

## What is tested
| ✅ Done on the author's Mac, 2026-11-23 | ⚠ Not tested |
|---|---|
| Swift app and `alfred-ctl` compile (`swift build`, release build too) | the full first-run flow (download → sign-in → permissions) in the app, with a brand-new user account |
| Unsigned `Alfred.dmg` builds (2.8 MB) and passes `hdiutil verify` | the DMG opened on a second Mac; the "Open Anyway" steps on a fresh macOS |
| Python syntax of every file; shell scripts parse | a live voice conversation with the renamed build |
| Secrets scan: no keys/tokens/personal paths (gitleaks is not installed, so a pattern scan was used) | the Claude **API key** brain with a real key; the Codex CLI brain |
| Address commands, greeting and voice-follow logic (`tests/test_address.py`) | real OpenAI / Ollama servers (plug-ins checked against a mock server only) |
| Model downloader shows real byte progress (tested into a throwaway home, Kokoro files) | the whole-model download (ears, wake helpers), pause/resume by a human, Reduce Motion |
| Claude brain prompt renders with name and address (checked, not run live) | layout with first-time users (never user-tested) |

## Known gaps
- Wake word model "Hey Alfred" is not trained yet.
- Part of the Russian-language comments and a few helper scripts (holograms, vision) are not translated.
- Ad-hoc signing means macOS may ask again for Accessibility after you rebuild the app.
- The `Claude` brain depends on Anthropic's Claude Code tool and its terms; read them before building a paid product on it.

## Contributing / building
```bash
cd mac-app && swift build            # compile
bash mac-app/build.sh                # Alfred.app (ad-hoc signed)
bash mac-app/make-dmg.sh             # dist/Alfred.dmg (unsigned)
python3 tests/test_brains.py         # brain plug-in checks
```
Licence: MIT, see `LICENSE`. Third-party parts and the non-commercial wake-word warning: `THIRD-PARTY.md`. Signing later with an Apple account: `SIGNING.md`.
