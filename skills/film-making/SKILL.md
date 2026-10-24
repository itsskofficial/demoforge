---
name: film-making
description: Make a narrated film with demoforge Film mode — talking-head lines and animated HyperFrames scenes on one voice spine, recorded line by line, captioned, scored, mixed, rendered and checked. Use for a voiced personal, brand or launch film; when working in a project with a film.json; or when a film cut comes back with notes.
---

# Making a narrated film

Film mode is for a film that is *made*, not cut out of footage that already
says what it needs to. The story is recorded one line at a time, some lines to
camera; every other line plays under an animated scene. The engine builds the
clock and everything mechanical on it. The animated scenes, and every judgement
about the person's face and words, are yours and theirs.

The schema, every command and the rules the engine enforces are in
[docs/film-mode.md](../../docs/film-mode.md). Read it before step 3; this skill
is the order of work and what the person holds the cut to.

## When it fits

A voiced film of 1–6 minutes where the narration is the spine: a self-pitch, a
founder story, a launch film. The person can record each line as its own file
and say which lines are on camera.

If the material is one long take, use Reel mode; a deck and rambling takes,
Editor mode; a repository with no one on camera, Demo mode.

## The workflow

Each step ends on its **done** line. A step is done when that line is true, not
when the command exits.

1. **The narration text, approved.** Write or tighten the spoken text with the
   person, line by line, numbered in film order. Every text change goes to the
   person before any shot work. **Done:** the person has said yes to this exact
   text.

2. **Record the lines.** The person records one voice file per line and video
   for the on-camera ones, sharing the line number (`...-NNNN.wav`,
   `...-NNNN.mp4`). Footage is theirs to shoot; the numbers are the order in the
   film. **Done:** every approved line has a voice file and every camera line a
   clip.

3. **Scaffold.** `demoforge film new projects/X`, lines into `footage/voice/`
   and `footage/cam/`. Write `FOOTAGE.md` by *listening* to every line: what
   was actually said, ad-libs included, not the script. Fill in `film.json`:
   scenes (anchored to `NNNN` or `NNNN@word`), looks, joins, music sections.
   **Done:** `demoforge film check --project X` reports 0 errors.

4. **Decode.** `film decode`. Phone AV1 goes through libdav1d and fails on
   repeated frames. **Done:** every camera line has a `work/cam/NNNN.mov` and
   no decode failed.

5. **Spine, then look-aways with the person.** `film spine` builds the master
   clock. For every on-camera line, find the last frame the eyes are on the lens
   (`demoforge tool gaze --video work/cam/NNNN.mov` gives candidates), show the
   person those frames, and write only the ones they approve, frame by frame,
   into `lookaways`. Rebuild the spine after. **Done:** every look-away in
   `film.json` is one the person picked, and the spine is built on them.

6. **Captions.** `film captions` aligns `FOOTAGE.md` to whisper's word times and
   runs the clipped-word guard. A mishearing is fixed in `FOOTAGE.md` or
   `captions.spoken`, never by moving times. If only *where* lines sit changed,
   `film retime --from spine.v1.json` instead. **Done:** the run passes the
   guard and every spoken word is in a cue.

7. **Timeline.** `film timeline` pins every scene to its line or word.
   **Done:** `film/timeline.json` has every scene in `film.json`, each on its
   anchor.

8. **Camera media and scenes.** `film camprep --matte`, then `film scenes`:
   camera scenes are generated, animated scenes get skeletons. Write each
   animated scene in `film/scenes/sNN/` against its brief in `SCENES.md` and
   its length in the timeline (motion-graphics skill). Overlays in a camera
   scene go between the `OVERLAY-*` markers. Snapshot each scene
   (`npx hyperframes snapshot` on its folder) and look at the frames before any
   full render.
   **Done:** every scene has its own snapshot and you have looked at each one.

9. **Root and transitions.** `film root` writes the root composition and
   `transitions.json`; `film freeze` makes the stills a shatter needs.
   **Done:** every join in `film.json` is in `transitions.json` with its sound.

10. **Score and mix.** `film score`, listen to `work/music/preview_mix.wav`,
    then `film mix` (audio-mix skill for the bed, the ducking and SFX).
    **Done:** `score` reports no stretch without a line, you have listened
    to the preview, and `film/assets/audio/mix.wav` is written.

11. **Render.** `film render`. One render at a time; `render` reports an
    orphan rather than racing it. **Done:** the output is full length.

12. **QA.** `film qa`, then open every `joins_NN.png` contact sheet. Steps 4–10
    each re-run alone (`film build --skip ...` for a rebuild); fix at the step
    that made the problem. **Done:** `qa.json` has no dark frames, no clipped
    edges, no uncaptioned words, and you have looked at every sheet.

13. **Thumbnails, and send for review.** `film thumbs`. Send the person a
    review copy (an H.264 re-encode; the delivery master is large), the `.srt`,
    the thumbnails and the list of what changed since their last note.
    **Done:** the person has the review copy and the change list.

## What the person holds the cut to

These are the notes that came back on the films this was built on. Check each
one before step 13, every time.

- **Footage as shot.** Their face stays as filmed: colour, room, light. The
  cutout is only an invisible depth layer on the identical footage, so graphics
  can sit behind them. Keep graphics legible on the real room with scrims and
  backing panels.
- **Black and white only where they asked**, as a look on those scenes.
- **The voice is continuous; music is never alone.** Narration runs first
  second to last, with designed gaps between lines.
- **Energetic music, clearly present.** "Too calm" is the most common note.
- **Captions follow what was said**, burned in, with an `.srt` beside the film.
- **Check every join on the waveform.** A clipped first or last syllable reads
  as sloppy editing. Tighten single lines (`tail_cut`, `remove`); keep tails
  generous everywhere else.
- **Scan for dropped frames.** One dark frame is enough for a viewer to see:
  `qa` finds them, the contact sheets confirm them.
- **The person approves before anything blanket.** A look-away, a grade, a
  change applied to every line: show the frames or the before-and-after first.
  Text changes go to them before shot work.

## Where else to look

- [docs/film-mode.md](../../docs/film-mode.md): the folder, every `film.json`
  key, the engine's rules
- [audio-mix](../audio-mix/SKILL.md): sourcing and pinning music, ducking, SFX
  on the cut
- [motion-graphics](../motion-graphics/SKILL.md): writing the HyperFrames scenes
- [video-editing](../video-editing/SKILL.md): why cuts follow words, and the
  transcript as the edit
