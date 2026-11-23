# Third-party software, models and licences

Alfred's own code is MIT (see `LICENSE`). Alfred downloads or uses the following. **Check each licence yourself before selling or redistributing a product built on Alfred.** This list was compiled from the projects' public pages and has not been legally reviewed.

| Part | Used for | Licence (as published) | Notes |
|---|---|---|---|
| **openWakeWord** (code) | wake-word engine, voice-activity detector | Apache-2.0 | https://github.com/dscripka/openWakeWord |
| ⚠ **`hey_jarvis` model** (openWakeWord pre-trained) | **not shipped, not used by default** | **CC BY-NC-SA 4.0 (non-commercial)** | Only used if you set `wake_model` to it yourself. Alfred's default is **no neural wake model** (name through speech recognition) until you train **"Hey Alfred"**: see `docs/TRAIN-HEY-ALFRED.md` |
| **Kokoro-82M** (voice model) + **kokoro-onnx** | offline text-to-speech (`bm_lewis`, `bf_isabella` …) | Apache-2.0 (model and wrapper) | model files downloaded on first run from the kokoro-onnx GitHub release |
| **MLX Whisper** + `mlx-community/whisper-small-mlx` | offline speech-to-text | MIT (code), MIT (OpenAI Whisper weights) | downloaded from Hugging Face on first run |
| **edge-tts** | optional online voices (en-GB-RyanNeural …) | LGPL-3.0 | ⚠ uses Microsoft's *unofficial* online voice service. Fine for personal use; do not rely on it in a product. Off by default (Kokoro is the default voice) |
| **Piper** + `ru_RU-dmitri` voice | optional Russian voice pack | MIT (Piper); voice licence: check the model card | only if you enable the Russian pack |
| **onnxruntime** | runs the wake/voice models | MIT | |
| **NumPy, SciPy-style stack, soundfile, sounddevice, Pillow, num2words, huggingface_hub** | audio + helpers | BSD / MIT / Apache-2.0 | see `requirements.txt` for exact versions |
| **OpenCV (headless)** | camera features | Apache-2.0 | |
| **MediaPipe** (installed on first use) | hand / face tracking for gestures | Apache-2.0 | optional |
| **rembg** + `u2net` model (installed on first use) | photo → hologram cut-outs | MIT (code); u2net: Apache-2.0 | optional |
| **rumps, PyObjC** | menu-bar helper | BSD-3-Clause / MIT | |
| **three.js**, `GLTFLoader`, `DRACOLoader` | hologram stage | MIT | not copied into the repo; fetched at build/first use. Keep their licence headers if you vendor them |
| **uv** (Astral) | creates the private Python | MIT / Apache-2.0 | downloaded by the app / installer |
| **Claude Code CLI** (Anthropic) | the "Claude subscription" brain | Anthropic's terms (proprietary) | **not bundled.** You install it and sign in with your own account. Alfred never sees your login. Read Anthropic's terms before building a paid product that drives it |
| **Anthropic API** | the "Claude API key" brain | Anthropic's terms | bring your own key |
| OpenAI / Codex CLI, Ollama | experimental brains | their own terms / MIT (Ollama) | not bundled, not verified end to end |
| **Apple frameworks** (SwiftUI, AppKit …) | the Mac app | Apple SDK licence | |

## Names
"Alfred" is a character name from DC Comics (Batman's butler) and also the name of a well-known Mac launcher app (Running with Crayons). This project is unaffiliated with either. Consider this before marketing the project under that name; see `docs/NAMES.md`.

## What is NOT in this repository
No models, no voice samples of real people, no recorded audio, no API keys or tokens, no personal data. `docs/voices/` holds only short demo clips synthesised by the voices above.
