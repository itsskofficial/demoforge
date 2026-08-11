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

## Getting a bed: source one, don't synthesise one

A real, mastered, human-arranged cue beats anything generated. It grooves, and
the difference is audible the moment a voice sits on top of it.

```bash
python -m demoforge.music_source find --query "chill trap beat"     --query "hip hop instrumental background" --runtime 180
```

Downloads candidates from Pixabay, whose Content License is genuinely free for
commercial use with no attribution, and writes down the licence at download
time — including what it **forbids**. Most stock licences bar redistributing the
audio as a standalone file: fine for a bed inside a video, and it matters the
first time someone asks for "the music on its own".

### Shortlist on length, then on structure

**Length first.** Alignment is done by *sliding* the track, so the source must
be meaningfully longer than the film. A 180-second track under a 178-second cut
gives you no offset to spend.

**Then structure — and measure the right thing.** Stock music is limited hard,
so RMS is nearly a straight line and ranking on "dynamic range" picks whichever
track has the longest outro. A breakdown is the bass and percussion *leaving*,
which barely moves total level but is unmistakable in the bands separately:

```python
low  = S[freq < 130].mean(axis=0)     # kick / bass  — is the floor still there?
high = S[freq > 4000].mean(axis=0)    # hats / perc  — is the groove still there?
```

`music_source find` prints this as `thin` (longest stretch in seconds where both
bands collapse). Look for **8s or more**, mid-track.

**Download 8–12 candidates, not 2**, across several query framings — result sets
barely overlap, and you cannot tell a track's structure from its title. Pixabay
starts returning 403 after a handful of rapid requests, so the fetcher paces
itself; sourcing is a once-per-video operation and has no reason to be fast.

### Align by sliding, never splicing

```bash
python -m demoforge.music shape --src track.mp3 --seconds 178 --offset 30.3
```

Choose the offset that puts the track's arrangement *return* on your film's
payoff. A splice costs a click, a phase discontinuity or a broken bar; an offset
costs nothing but the length requirement above. Normalise to −16 LUFS here,
before ducking, so the duck targets mean the same thing on every track.

### When the track has no breakdown to align to

Most stock cues are one texture end to end — shortlisting on length often
leaves you with nothing that has a real arrangement. Impose one:

```bash
python -m demoforge.music automate --src bed.wav --out bed-auto.wav     --points act-map.json
```

`points` is `[seconds, gain_db]` pairs taken from your running order: a cold
open, a dip across whichever scene must read as the quietest, a lift on the
payoff, a tail. Smoothed into a curve, so it is an arrangement rather than a
set of steps.

Two things worth knowing:

- **Level alone reads as "quieter"; level plus a closing filter reads as
  "underwater".** The cold open sweeps a lowpass as well as the gain, because a
  track sliced at any offset starts at full energy on frame one.
- **Smooth with `scipy.signal.fftconvolve`, never `np.convolve`.** At 177s and
  a 1.5s kernel the latter is ~10¹⁰ operations and looks exactly like a hang.

Verify with the meter, not intent — measure the bed alone at each act break and
check the shape matches what you drew. Automation is *relative* gain over
whatever the track is already doing, so a lift can still land quieter than a
neutral section if the source dips there.

## The synthesised fallback

```bash
python -m demoforge.music bed --seconds 180 --style lofi
```

Sine waves, filtered noise and envelopes — nobody owns it. Legitimate when the
video cannot take a licence dependency, or when you need an act break at an
exact second no real track will give you.

**It is also worse.** It does not groove. Treat it as a placeholder that
unblocks the edit, and swap in a real cue before delivery.

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
