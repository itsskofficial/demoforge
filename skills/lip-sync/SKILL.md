---
name: lip-sync
description: Re-dub existing footage of a person so their mouth matches new narration, producing a talking-head presenter for demo videos. Use when a video needs a presenter without re-filming, or when narration changes and the footage must follow. Covers driver preparation, looping short clips, idle-face artefacts, and Windows/consumer-GPU setup.
---

# Making a presenter say something they never said

The approach that works is **record once, re-dub forever**: film yourself for
twenty or thirty seconds, then reuse that footage for every future version of
the video with new audio. Identity, lighting, head motion and micro-expressions
are all real; only the mouth is generated.

**Do not build photo-to-video for this.** A single still gives you a frozen head
with a moving mouth. It survives a ten-second clip and falls apart over three
minutes. Photo-driven models are for animating *someone else's* portrait, which
is a different product with different consent questions.

## Filming the driver clip

- **Twenty to forty seconds** is plenty. It gets looped.
- Look at the camera. Talk about anything — the words are discarded.
- Even light, plain background, no hard shadows across the mouth.
- Stay roughly still. Big head movement makes the lip-sync region wander.
- **Neutral, low-energy delivery.** This matters more than it sounds: see idle
  faces below.

```bash
python -m demoforge.face prepare --src VID_1234.mp4 --start 1.5 --dur 20
```

`prepare` bakes rotation into the pixels. Phones record portrait video as
landscape plus a rotation flag; ffmpeg honours it, most model code does not, and
the failure mode is a sideways face. It also resamples to 25fps, which is what
these models are trained at.

## Covering a long narration with a short clip

```bash
python -m demoforge.face loop --src driver.mp4 --seconds 180
```

**Never ping-pong a person.** Playing the clip forwards then backwards gives a
mathematically seamless join, which is why it is tempting, and it is wrong.
Reversed human motion is uncanny: blinks un-blink, a jaw closing becomes a jaw
opening on nothing, a head settling becomes a head lurching. Lip-sync replaces
only the mouth, so everything around it is a person running backwards — on a
21s clip under a 3-minute narration that is **47% of the runtime**. Viewers
report it as "weird faces" without being able to say why.

`loop` goes forwards only and crossfades the clip's own tail into its own head,
producing a cycle whose end already matches its start. The cost is a soft
0.5s dissolve every cycle instead of a seamless join — far cheaper than
reversed motion.

The better fix is a longer driver: 60–90 seconds of footage means fewer loops
and fewer seams. Twenty seconds works; it just repeats more.

## The idle-face problem

Lip-sync models regenerate the mouth across the **whole** clip, including
silence. Underneath, your original footage is someone mid-sentence — so during a
pause you get a still-moving jaw attached to eyebrows and eyes that belong to
words nobody is hearing. It reads as "weird faces".

Three fixes, best first:

1. **Only show the presenter while they are speaking.** `demoforge.compose`
   takes speaking windows and cuts the inset out during silence. This removes
   the problem rather than managing it.
2. **Sync per line, not per video.** Each narration line is continuous speech,
   so there is little silence inside it to go wrong.
3. **Film a calmer driver.** Animated source footage produces animated idle.

Check the loop direction before blaming the model. Reversed footage looks like
a lip-sync failure and is not one.

## Running it

```bash
python -m demoforge.face sync --video driver.mp4 --audio line.wav --out head.mp4
```

Knobs worth knowing: `--steps` (20 default; more is slower, marginally cleaner)
and `--guidance` (1.5 default; higher tracks the audio harder and can look
over-articulated).

**Budget the time.** LatentSync runs at roughly **20× realtime on an 8 GB
consumer GPU** — ten seconds of video takes around three and a half minutes, and
a three-minute demo is over an hour. So: lock the script, lock the voice, *then*
run the face pass once. Never iterate through it.

## Anything over about thirty seconds must be chunked

The limit you hit first is **system RAM, not VRAM**. LatentSync decodes the
entire driver into one numpy array before it starts. At 720×1280 that is

    frames × height × width × 3 bytes

so a three-minute clip is 4,450 × 1280 × 720 × 3 ≈ **11.5 GiB**, and a 16 GB
laptop cannot allocate it. The failure is `numpy._core._exceptions.
_ArrayMemoryError`, well before the GPU does any work.

```bash
python -m demoforge.face sync --video driver-long.mp4 --audio timeline.wav \
    --out head.mp4 --chunk 20 --width 512
```

Two things fix it together:

- **`--chunk 20`** bounds the array to one twenty-second window at a time. The
  chunks are independent, so a failure costs one chunk rather than the run, and
  a re-run skips what already succeeded.
- **`--width 512`** is the bigger lever than it looks. The presenter ends up as
  a ~340px inset, so driving at 512 wide is already oversampled — and it costs a
  quarter of the memory and roughly a quarter of the time of 1080p.

Chunk boundaries are inaudible because each chunk is lip-synced against its own
slice of the same continuous audio; the mouth does not reset at the seam.

## Setup traps on Windows and consumer GPUs

- **Triton.** Recent torch routes parts of the UNet through inductor, which
  needs Triton, which does not exist on Windows. Set `TORCHDYNAMO_DISABLE=1`;
  these models predate it and run fine eagerly. `demoforge.face` sets it for you.
- **numpy ABI.** `face-alignment` pulls a `scikit-image` built against numpy 1.x
  and dies against numpy 2.x with "numpy.dtype size changed". Upgrading
  scikit-image alone fixes it.
- **Do not reinstall torch.** These repos pin old torch versions, but the pins
  are conservative. Create the venv with `--system-site-packages` and add only
  what is genuinely missing (usually just torchvision, ~7 MB). A separate venv
  is still needed because lip-sync pins an older `transformers` than voice
  models want — but it can share one torch.
- **512px variants need ~18 GB.** On 8 GB use the 256px config; the face region
  is softer than the surrounding frame, which is invisible in a corner inset and
  visible full-screen.
