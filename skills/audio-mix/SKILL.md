---
name: audio-mix
description: Score a demo video with background music that stays out of the way — synthesising a licence-free bed, ducking it under narration with a sidechain compressor, and normalising the final loudness. Use when a demo feels dry or clinical, when music buries the voice, or when a published video needs a soundtrack nobody owns.
---

# Music under a demo, without burying it

A demo with no music feels like a screen recording. A demo with music at a
fixed level is worse: the bed either sits on top of the narration or is so
quiet it may as well not be there.

The fix is not a level. It is **ducking** — the bed steps back whenever the
voice is present and swells in the gaps between sentences. That is the whole
difference between a video that sounds scored and one that sounds like a track
was pasted underneath it.

## Getting a bed

```bash
python -m demoforge.music bed --seconds 180 --style lofi
```

Synthesised from sine waves, filtered noise and envelopes. **Nobody owns it**,
which matters for anything you publish: "royalty-free lofi" downloads carry
terms that differ per track, per platform, and per whether your video is
monetised, and that is a licence audit nobody wants attached to a demo.

Two styles: `lofi` (74bpm, seventh chords, swung hats, tape wobble) and `trap`
(140bpm, minor, 808 sub, faster hats).

Bring your own instead with `mix --music yourtrack.mp3`. Check its licence
covers your use before you publish.

### Why the generated bed is deliberately boring

- **Seventh chords in a low register.** They sit under speech instead of
  competing for the frequencies a voice occupies.
- **No melody on top.** A tune pulls attention, and the narration has to win.
- **Slow attacks and a low-pass on everything.** Transients poke through
  ducking; soft ones do not.
- **A slow tremolo** stands in for tape wow. It is most of what makes a
  synthesised loop read as a cassette rather than a synth patch.
- **Fades at both ends**, so a loop cut anywhere does not click.

## Ducking

```bash
python -m demoforge.music mix --video cut.mp4 --music bed.wav --out final.mp4
```

The narration feeds a sidechain compressor that pulls the music down:

| Setting | Value | Why |
|---|---|---|
| `--music-db` | −23 | Resting level of the bed. |
| `--duck-db` | −14 | How far it drops under speech. |
| `--release` | 380ms | How fast the bed recovers. Must be **shorter than your gaps** or it never does. |
| attack | 8ms | Fast, so the first syllable is never buried. |

**Never compress the narration to make room for the music.** It is backwards,
and it is audible — the voice starts to sound squashed and distant. Only the
bed moves.

## Final loudness

The mix is normalised to **−16 LUFS** with a −1.5 dB true peak, which is where
web video sits. Skip this and your demo is either noticeably quieter than
everything around it or clipped on playback.

Normalise **once**, at the end, on the finished mix. Normalising the narration
and then again after the music undoes the level relationship you just built.

## Order of operations

Music goes on **last**, after the picture is locked and the presenter is
composited:

1. Narration → 2. Picture → 3. Assemble → 4. Lip-sync → 5. **Music**

Because it is last and cheap (seconds), it is the one stage worth trying
several versions of. Render three beds with different seeds and listen to each
under the real narration — a bed that sounds good alone often disappears or
clashes once a voice is over it.

## What to listen for

- **The first word of each scene.** If it is buried, the attack is too slow.
- **The gaps.** If the bed does not come up, check the gap length before touching
  the release. Measured on a cut with 0.4s scene tails, 380ms and 650ms releases
  produce *identical* levels — the gap is simply too short for either to matter.
  Swell is an editing decision (longer tails), not a compressor setting.
- **Pumping.** Bed audibly breathing on every pause means the release is too
  short or the ratio too high.
- **The close.** The last few seconds usually have no narration, so the bed is
  fully exposed. It should end on a fade, not a cut.
