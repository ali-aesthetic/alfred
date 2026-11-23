# Train your own "Hey Alfred" wake word

**Why:** the pre-trained `hey_jarvis` model that came with openWakeWord is licensed CC BY-NC-SA (non-commercial), and it says the wrong name. Alfred does **not** ship or use it by default. Until you train "Hey Alfred", Alfred uses these fallbacks (all already work):

| Fallback | How |
|---|---|
| Name through speech recognition | just say "Alfred, …" (default; slower and uses the mic continuously) |
| Hold-to-talk key | hold right ⌥ (Option), talk, let go |
| Type | Console window → type a request |

## Train it (free, about 1 hour, mostly waiting)
Not yet done or tested by the author. These are the official steps.

1. Open the openWakeWord training notebook (Google Colab, free GPU):
   https://github.com/dscripka/openWakeWord → "Training New Models" → `automatic_model_training.ipynb`
2. Set the target phrase to `hey alfred` (also try the variant `hey, alfred`).
3. Run all cells. It creates thousands of synthetic voice clips, mixes them with noise and room echoes, and trains a small model. Leave the defaults unless you know why you change them.
4. Download the result: `hey_alfred.onnx`.
5. Put it in your Alfred home folder, e.g. `~/Library/Application Support/Alfred/models/wake/hey_alfred.onnx`.
6. In `config.json` set:
   ```json
   "wake_model": "~/Library/Application Support/Alfred/models/wake/hey_alfred.onnx"
   ```
7. Restart Alfred (Settings → Restart my brain). The log says `Wake word model: hey_alfred.onnx`.
8. Tune `wake_threshold` (default 0.35): raise it if Alfred wakes by mistake, lower it if he misses you.

## Licence of your model
A model you train yourself with synthetic speech is yours to licence (check the licence of the TTS voices the notebook uses). If you want to share it in the repo, add it to `THIRD-PARTY.md` with its licence.

## Checking it works
Say "Hey Alfred" 20 times at different distances, and talk normally for a minute without saying it. Count misses and false wakes. Write the numbers in your release notes; do not claim accuracy you did not measure.
