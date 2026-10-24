---
name: audio-mix
description: Score a video with music and sound effects that sit under the voice: source a real track, align it by sliding, pin music sections to narration lines, duck the bed and an SFX bus under the voice, and master to −14 LUFS. Use when a cut feels dry, when music buries or loses to the voice, when a longer film needs different music per act, or when transitions need hits that land on the cut.
---

# Music and effects under a voice

A cut with no music feels like a screen recording. A cut with music at a fixed
level is worse: the bed either sits on top of the narration or is so quiet it
may as well not be there.

The fix is **ducking**: the bed steps back whenever the voice is present and
swells in the gaps between sentences. That is the difference between a video
that sounds scored and one that sounds like a track was pasted underneath it.

## What the listener holds you to

- **The voice is continuous; the music is never alone.** Narration runs from
  the first second to the last. Music fills the gaps between sentences and
  carries the energy, but no stretch of the film is music on its own while the
  story waits.
- **Upbeat and clearly present.** The note that comes back most often on a cut
  is "the music is too calm". Default to an energetic track that sits roughly
  8 dB under speech in the gaps, not a barely audible bed.
- **Every join is clean.** A clipped first syllable under a music swell reads as
  sloppy editing. Check joins on the waveform (see *What to listen for*).

## Getting a bed: source one

A real, mastered, human-arranged cue beats anything generated. It grooves, and
the difference is audible the moment a voice sits on top of it.

```bash
python -m demoforge.music_source find --query "upbeat electronic" --query "hip hop instrumental" --runtime 180
```

Downloads candidates from Pixabay (Content License: free for commercial use, no
attribution) and records the licence at download time, including what it
**forbids**: most stock licences bar redistributing the audio as a standalone
file. Mixkit tracks (Mixkit Stock Music Free License) are a good second source.

Pixabay starts returning 403 after rapid requests, and some networks are
blocked outright. When `find` skips every query, reuse what is already on disk
in `out/audio/candidates/` (each file has a `.source.json` licence record).

### Shortlist on length, then on structure

**Length first.** Alignment is done by *sliding* the track, so the source must
be meaningfully longer than the stretch it scores.

**Then structure, measured in bands.** Stock music is limited hard, so RMS is
nearly flat and ranking on dynamic range picks whichever track has the longest
outro. A breakdown is the bass and percussion *leaving*:

```python
low  = S[freq < 130].mean(axis=0)     # kick / bass: is the floor still there?
high = S[freq > 4000].mean(axis=0)    # hats / perc: is the groove still there?
```

`music_source find` prints this as `thin` (longest stretch where both bands
collapse). Look for **8 s or more**, mid-track. Download 8–12 candidates across
several query framings; you cannot tell a track's structure from its title.

### Align by sliding, never splicing

```bash
python -m demoforge.music shape --src track.mp3 --seconds 178 --offset 30.3
```

Choose the offset that puts the track's drop or arrangement *return* on your
film's payoff. A splice costs a click or a broken bar; an offset costs nothing
but the length requirement.

### When the track has no arrangement to align to

```bash
python -m demoforge.music automate --src bed.wav --out bed-auto.wav --points act-map.json
```

`points` is `[seconds, gain_db]` pairs from your running order: a cold open, a
dip for the quietest scene, a lift on the payoff, a tail. Level plus a closing
lowpass reads as "underwater"; level alone reads as "quieter". Smooth with
`scipy.signal.fftconvolve`; `np.convolve` at this length looks like a hang.
Verify with the meter at each act break: automation is relative to whatever
the track already does there.

## Sections: different music per act

A film longer than a couple of minutes changes mood: a confident open, a dark
middle, a lift into the call to action. Score it as **sections**, each a track
pinned to a narration line rather than to a stopwatch time, so the music
follows when the voice is re-cut:

- `pin`: the line (or word) where the track must be at `track_at` seconds.
- `start` / `end` / fades: where the section plays, in film time.
- Each stretch is EBU-measured and levelled to −16 LUFS first, *then* given its
  intent gain, so "+3 dB" means the same thing on every track.

A section can **stop dead** on an impact (a 0.06 s fade) and the next can drop
in on the cut: silence for a beat before a reveal is a choice, as long as the
voice or an effect carries it. Film mode implements this as `demoforge film score`
(see `docs/film-mode.md`).

## Sound effects

Transitions and graphic hits land harder with a sound, and they need their own
bus:

- **Align on the peak, not the file start.** Record each effect's `peak_at`
  in its manifest and place it so the loudest moment lands on the cut. A whoosh
  whose peak is 0.6 s into the file, started on the cut, arrives late.
- **Read the envelope before cueing.** A file described as "thud, then glass"
  may have an inaudible thud; measure RMS in 50 ms windows and cue what is
  actually there.
- **Compress the SFX bus and duck it under the voice** like the music. An
  effect never covers a word.

## Ducking and the final master

```bash
python -m demoforge.music mix --video cut.mp4 --music bed.wav --out final.mp4
```

The narration feeds a sidechain compressor that pulls the music (and the SFX
bus) down:

| Setting | Value | Why |
|---|---|---|
| bed under voice | about −8 dB | Clearly present in the gaps, out of the way under speech. |
| attack | 8–15 ms | Fast, so the first syllable is never buried. |
| release | 350–380 ms | Must be **shorter than your gaps** or the bed never recovers. |

Only the bed and effects move; the narration is never compressed to make room.

**Master to −14 LUFS integrated, −1 dB true peak**, the level social feeds
normalise to. Normalise **once**, on the finished mix: normalising the
narration and again after the music undoes the relationship you just built.

## Order of operations

Music goes on **last**, after the picture is locked: it is cheap (seconds) and
the one stage worth trying several versions of. Listen to each candidate under
the real narration; a bed that sounds good alone often disappears or clashes
once a voice is over it.

## What to listen for

- **The first word of every line and scene.** Buried means the attack is too
  slow or the cut clipped it. Confirm on the waveform: plot the finished voice
  against the source at every join.
- **The gaps.** If the bed does not come up, check the gap length before the
  release: with 0.4 s gaps, 380 ms and 650 ms releases measure identically.
  Swell is an editing decision (longer gaps), not a compressor setting.
- **Pumping.** A bed that breathes on every pause means the release is too
  short or the ratio too high.
- **Effect timing.** Step through each transition: the hit lands on the cut,
  the music stop lands on the impact.
- **The close.** The last seconds usually have no narration, so the bed is
  exposed. End on a fade, not a cut.

## The synthesised fallback

```bash
python -m demoforge.music bed --seconds 180 --style lofi
```

Sine waves, filtered noise and envelopes: nobody owns it, and it can put an act
break at an exact second. It does not groove. Treat it as a placeholder that
unblocks the edit, and swap in a real cue before delivery.
