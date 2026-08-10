---
name: video-assembly
description: Fit rendered segments to measured narration, lay the audio underneath, overlay a talking head, and cut a final video with timecodes. Use at the end of a demo pipeline, or when narration length and picture length disagree. Covers frame-holding, picture-in-picture placement, and speaking windows.
---

# Cutting it together

The last stage: many segments, one narration track per line, a presenter clip,
and a single file at the end.

```bash
python -m demoforge.assemble --narration out/audio/narration.json
python -m demoforge.compose --base master.mp4 --head face.mp4 --out final.mp4
```

## Fit the picture to the words, not the other way round

Segment length is guessed when it is rendered and only *known* once the line has
been spoken. `assemble` reads the measured durations and extends any segment
shorter than its narration.

**It extends by holding the final frame, not by slowing the footage.** A
terminal already sitting still on its last output looks identical held for four
more seconds; ramped to 0.7× it looks broken. Motion graphics are worse — eased
animation replayed slowly reads as a stutter.

If a segment is *longer* than its line, leave the slack. Silence over a held
picture is fine; clipped narration is not.

## One audio timeline, built from the same manifest

Each line is placed at the start of its own segment and padded to that segment's
final length. Both timelines are derived from one source, so they cannot drift —
which is the failure that shows up ninety seconds in and costs a full re-render
to find.

## Picture-in-picture

```bash
python -m demoforge.compose --base master.mp4 --head head.mp4 --corner br --size 340
```

- **Crop to the face, not the frame.** Phone video is portrait; dropping it
  whole into a circle wastes most of the inset on chest and ceiling. Centre the
  crop about a third down.
- **Bottom-right by default**, but check what it covers. Terminal output grows
  downward and browser UI lives top-left, so bottom-right is usually the quiet
  corner. Move it per project if not.
- **340px on a 1920 frame** is large enough to read expression and small enough
  not to compete. Below ~260 the face stops carrying anything.

### Show the head only while it is speaking

```python
windows = speaking_windows(narration, order)
```

Lip-sync models regenerate the mouth over silence, and the footage underneath is
someone mid-sentence — so a face left on screen through a pause makes
expressions belonging to words nobody is hearing. Cutting the inset during
silence removes the artefact instead of animating around it. It also gives the
edit rhythm: presenter for narration, full screen for the thing being shown.

## Timecodes

`stitch` writes a table of every segment's start and length. Hand it over with
the video. Anyone re-cutting it — including you in a month — needs to know where
the boundaries are without scrubbing.

Keep cuts hard. A dissolve is harder to slide around in an editor than a cut,
and boundaries are exactly where a voiceover changes subject.

## Order of operations

Cheap to expensive, so nothing expensive is done twice:

1. Script → 2. Narration (minutes) → 3. Scenes (minutes) → 4. Assemble (seconds)
→ 5. **Lip-sync (hours)** → 6. Compose (seconds)

Never iterate through step 5. Lock the script and the voice first.
