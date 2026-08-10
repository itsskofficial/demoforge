# Quickstart

From nothing to a narrated demo with your face in the corner.

Budget about **two hours** the first time, most of it downloads and one long
render you can leave alone.

---

## 1. Install

```bash
git clone https://github.com/itsskofficial/demoforge
cd demoforge
python -m venv .venv --system-site-packages
.venv/Scripts/pip install -e ".[all]"
```

`--system-site-packages` is not a detail. The model repos pin old torch
versions, and installing each one's pin gives you three copies of a 2.4 GB
library. Reuse the torch you have and add only what is missing.

```bash
demoforge doctor
```

Fix whatever it lists before going on.

### The lip-sync half

Only needed if you want a face on screen.

```bash
git clone --depth 1 https://github.com/sdbds/LatentSync-for-windows vendor/latentsync
python -m venv .venv-lipsync --system-site-packages
.venv-lipsync/Scripts/pip install torchvision --index-url https://download.pytorch.org/whl/cu128 --no-deps
.venv-lipsync/Scripts/pip install diffusers==0.32.2 transformers==4.48.0 huggingface-hub==0.25.2 \
    imageio accelerate einops omegaconf safetensors opencv-python mediapipe av \
    ffmpeg-python face-alignment librosa decord
.venv-lipsync/Scripts/pip install --upgrade scikit-image
hf download ByteDance/LatentSync-1.5 latentsync_unet.pt whisper/tiny.pt \
    --local-dir vendor/latentsync/checkpoints
```

Two lines there exist because of real failures: `torchvision --no-deps` stops
pip dragging in a second torch, and upgrading `scikit-image` fixes a numpy ABI
crash from `face-alignment`. A separate venv is needed because lip-sync pins an
older `transformers` than the voice model — but it shares one torch.

---

## 2. Record two things once

**Your voice** — 30–60 seconds of talking, any content, no music.

**Your face** — 20–40 seconds looking at the camera, talking about anything,
even light, plain background. Stay fairly still and keep your delivery calm;
animated source footage produces an animated idle face later.

You never have to record either again. Every future demo reuses them.

---

## 3. Plan the demo

```bash
export ANTHROPIC_API_KEY=...        # or put it in .env
demoforge plan --repo ../yourproject --seconds 180 \
    --audience "developers who have never seen this"
```

Writes `projects/yourproject/plan.json` and `narration.json`.

**Read the plan and edit it.** It was written by something that read your repo
and has never used your product. Check every command it proposes — nothing runs
them for you, and that gap is deliberate.

---

## 4. Voice

```bash
demoforge voice --src yourvoice.mp3 --start 8 --dur 16
demoforge voice --text "one line, to hear whether it sounds like you"
```

If it sounds rushed, it is: the default reads around 220 words per minute
against a comfortable 145. Lower `--cfg-weight` to 0.24 and set `--pace 0.85`.
See [skills/voice-cloning](../skills/voice-cloning/SKILL.md).

Once it sounds right:

```bash
demoforge voice --script projects/yourproject/narration.json --outdir out/audio
```

This also writes measured durations, which everything downstream sizes itself
against.

---

## 5. Picture

Capture any commands the plan wants to show:

```bash
export DEMOFORGE_TARGET=/path/to/yourproject
python -m demoforge.capture s04.json -- python -m yourapp measure
```

Then render the scenes. Copy `projects/livingeval3/scenes.py` as a starting
point — it is a plain Python file where each scene is a function of time.

```bash
python projects/yourproject/scenes.py
```

---

## 6. Assemble, then the face

```bash
python -m demoforge.assemble --narration out/audio/narration.json
```

You now have a watchable narrated demo. **Look at it before going further** —
the next step takes hours and you do not want to run it on a cut you are going
to change.

```bash
python -m demoforge.face loop --src assets/face/driver.mp4 --seconds 200
python -m demoforge.face sync --video assets/face/driver-long.mp4 \
    --audio out/narration-timeline.wav --out out/head.mp4 --chunk 20 --width 512
python -m demoforge.compose --base out/master.mp4 --head out/head.mp4 \
    --out out/final.mp4
```

`--chunk 20 --width 512` is not optional for anything over about thirty
seconds: LatentSync decodes the whole driver into one array first, and a
three-minute 720p clip is 11.5 GiB of RAM before the GPU does anything.

Lip-sync runs at roughly 20× realtime on an 8 GB GPU — a three-minute demo is
about an hour. Leave it running.

---

## When the product changes

Re-run from step 4. The face and voice stay; only the words and the picture are
rebuilt. That is the whole point.

## Common problems

| Symptom | Cause |
|---|---|
| Narration sounds rushed | Defaults are ~220 wpm. Lower `--cfg-weight`. |
| Sideways face | Phone rotation metadata. `face prepare` bakes it in. |
| `TritonMissing` | Windows has no Triton. `TORCHDYNAMO_DISABLE=1`. |
| `numpy.dtype size changed` | Old scikit-image. Upgrade it. |
| Weird expressions in pauses | Idle-face. Show the head only while speaking. |
| Narration overruns the picture | `assemble` holds the last frame. Re-run it. |
