# Film mode

A narrated film of scenes. The narration is recorded line by line, some lines to camera; every
other line plays under an animated HyperFrames scene; music is cut to the story and every join
has a sound. This is the pipeline that made the pitch film (`projects/pitch-film`), with
everything particular to that film moved into one file, `film.json`.

The other modes cut footage that already says what it needs to. Film mode is for a film that is
*made*: the engine builds the clock, the captions, the camera scenes, the root composition, the
score and the mix. The animated scenes are written by hand (or by an agent) against the
timeline it produces.

```
demoforge film new projects/myfilm      # scaffold
# put the lines in footage/, write FOOTAGE.md, fill in film.json
demoforge film build  --project myfilm  # decode → spine → captions → timeline → camprep
                                        #   → scenes → root → freeze → score → mix
# write the animated scenes in film/scenes/sNN/, overlays in the camera scenes
demoforge film render --project myfilm
demoforge film qa     --project myfilm
demoforge film thumbs --project myfilm
```

## The folder

```
projects/myfilm/
  film.json          every decision (below)
  FOOTAGE.md         what was actually said: one `| NNNN | text |` row per line
  FILM.md            the bible: world, motifs, palette, safe areas, sound
  SCENES.md          one brief per scene, written against film/timeline.json
  footage/voice/     one wav per line, ...-NNNN.wav (NNNN = order in the film)
  footage/cam/       the on-camera lines, ...-NNNN.mp4, same NNNN as their voice
  film/              the HyperFrames project
    index.html       the root composition            (film root)
    timeline.json    the scene table                 (film timeline)
    transitions.json every join and its sound        (film root)
    lib/kit.css      design tokens and faces; lib/kit.js, seeded helpers
    assets/cam/      plates, cutouts, hold stills    (film camprep, film scenes)
    assets/audio/    voice.wav, mix.wav              (film mix)
    assets/fx/       freeze-frame stills             (film freeze)
    assets/sfx/      the SFX library + manifest.json (name, file, duration, peak_at)
    scenes/sNN/      index.html, sfx.json, and junctions `assets` and `lib`
out/myfilm/          (paths.work) spine/, music/, mix/, cam/, matte/, qa/, thumbs/, tmp/
```

Each scene folder links back to the film's `assets` and `lib` (a junction on Windows, made with
`mklink /J`; a symlink elsewhere) so a scene can be previewed and snapshotted on its own. Never
`rm -rf` a scene folder.

## The commands

| Step | Reads | Writes |
| --- | --- | --- |
| `decode [NNNN...]` | footage/cam | work/cam/NNNN.mov (H.264 + PCM) |
| `spine` | footage/voice | work/spine/voice.wav, voice_raw.wav, spine.json |
| `captions [NNNN...]` | spine, FOOTAGE.md | work/spine/words.json, cues.json, &lt;srt&gt; |
| `retime --from spine.v1.json` | the old spine + words.v1/cues.v1 beside it | the same three, on the new spine |
| `timeline` | spine, words, cues | film/timeline.json |
| `camprep [--matte]` | work/cam, work/matte | film/assets/cam/NNNN.mp4, NNNN_a.webm |
| `scenes [sNN...]` | timeline | scene folders; camera scenes regenerated; stubs for the rest |
| `root` | timeline, words | film/index.html, film/transitions.json |
| `freeze` | transitions, the outgoing scene | film/assets/fx/sNN_frozen.png, _bw.png |
| `score` | spine, music tracks | work/music/bed.wav, preview_mix.wav |
| `mix` | voice, bed, scene sfx.json, transitions | film/assets/audio/mix.wav, work/mix/sfx.wav |
| `build [--retime B] [--skip a,b]` | | the ten steps above, in that order |
| `render [--out F] [--wait]` | the film folder | render.output |
| `qa [--video F]` | the render, spine, captions | work/qa/qa.json, joins_NN.png |
| `thumbs [--video F] [--at 3,250]` | the render | work/thumbs/*.png, thumbs_sheet.png |
| `check` | film.json | errors and warnings |

Every step takes `--project` (a film.json, its folder, or a name under projects/), and
`--work DIR` / `--into DIR` to write intermediates and generated film files somewhere else. That
is how a build is checked against a finished film without touching it.

When only *where* lines sit changes (a gap, a tail), keep a copy of the old spine, words and cues
as `spine.v1.json` / `words.v1.json` / `cues.v1.json` and run `retime` instead of `captions`:
each word belongs to one line and moves by exactly that line's shift, so it is exact and needs
no GPU.

## film.json

Keys starting with `_` are comments, at any depth. Paths may use `{out}` (demoforge's out
folder), `{root}`, `{project}`, `{name}`, `{work}` and `{film}`; relative paths are relative to
the project folder. Anything left out takes the default in `src/demoforge/film/project.py`
(the pitch film's tuned values).

| Key | Meaning |
| --- | --- |
| `name`, `title` | folder name in out/; the root's `<title>` |
| `fps`, `width`, `height`, `sample_rate` | 30, 1920, 1080, 48000 |
| `paths.film` | the HyperFrames project (`film`) |
| `paths.work` | intermediates (`{out}/{name}`) |
| `paths.voice`, `paths.camera` | the line folders |
| `paths.music` | where the tracks named in `music.sections` live |
| `paths.temp` | a big-disk temp folder for render and snapshot (`{work}/tmp`) |
| `sources.voice`, `sources.camera` | globs inside those folders |
| `sources.seq` | regex whose group 1 is the line number (`(\d{4})\.[^.]+$`) |
| `decode.max_repeat` | fail a decode with more repeated frames than this (0.05) |
| `spine.lead`, `spine.tail` | air kept before / after speech, then out to a frame (0.10, 0.16) |
| `spine.gap`, `spine.gap_after` | speech-to-speech silence; per line overrides: the breaths |
| `spine.lead_in`, `spine.end_hold` | room before the first word; silence after the last (end card) |
| `spine.speech_db`, `spine.floor_percentile` | speech = floor + 14 dB, floor = 10th percentile |
| `spine.remove` | per line: `[[start, end], ...]` clip seconds cut out with a 12 ms crossfade |
| `spine.tail_cut` | per line: never keep the last N seconds (a take that carries the next word) |
| `spine.lookaway_tail`, `lookaway_gap`, `lookaway_gap_after` | tighter tail and gap after look-away lines |
| `spine.chain` | the ffmpeg voice clean-up chain |
| `lookaways` | line → clip time of the last on-lens frame (approved frame by frame) |
| `captions.text` | `FOOTAGE.md` (a `\| NNNN \| text \|` table) or `{seq: text}` |
| `captions.spoken` | caption token → how whisper writes it (`"$291": "291"`), for alignment only |
| `captions.source_words` | untrimmed transcripts `[{seq, words:[{w}]}]`, for the clipped-word guard |
| `captions.model`, `max_chars`, `max_words`, `soft_after`, `hold`, `gap`, `srt` | whisper model; cue shape; hold past the last word; gap before the next cue; srt file name |
| `scenes` | `[{id, kind, at, title}]`; `at` is `NNNN`, `NNNN@word` or `NNNN@word#n` |
| `anchor_lead` | a word-anchored scene cuts this far ahead of the word (0.12) |
| `looks` | kind → `{plate, subject, ground, plate_scale, push: [from, to], glow, key}`. A kind with a look is on camera. `plate`/`subject` are CSS filters (`"none"`, or `"grayscale(1) contrast(1.15)"`); `null` drops the layer. `plate_scale: null` writes no inline scale |
| `camera.nocut` | lines that stay full-frame with no cutout |
| `camera.flip_from` | line → clip time to switch to an un-mirrored copy, with a punch-in |
| `camera.punch_scale`, `punch_duration`, `plate_crf`, `plate_gop`, `cutout_crf`, `cutout_gop`, `choke`, `soften`, `despill`, `despill_mix` | camera media details |
| `joins` | outgoing scene id → transition; others get `default_join` (`cut`) |
| `sfx` | transition → `[name, offset, gain]` or a list of them; offset `null` = peak on the cut |
| `root` | `grain_seed`, `grain_opacity`, `glitch_seed`, `shatter_seed`, `shatter_point`, `shatter_impact`, `caption_top`, `caption_size`, `gsap` |
| `music.sections` | `[{track, pin, track_at, start, end, gain, fade_in, fade_out}]`; `pin`/`start`/`end` are seconds, `"end"`, or `"NNNN[.end][+/-s]"` |
| `music.target_lufs`, `music.limit`, `music.preview` | per-stretch level (-16); bed limiter; write the preview |
| `mix.music_db`, `sfx_default_db`, `sfx_headroom`, `loudnorm` | -8, -6, 0.5, `I=-14:TP=-1:LRA=11` |
| `render.workers`, `quality`, `timeout_ms`, `output` | 2, delivery, 1800000, `{film}/renders/{name}.mp4` |
| `thumbs.count`, `step`, `spacing`, `headlines` | 6 frames, sampled every 0.25 s, 2 s apart; plain frames at these times |

Transitions: `cut`, `match` (nothing; the scenes line up), `glitch`, `leak`, `flash`, `drop`,
`act`, `whip`, `dip`, `zoom`, `punch`, `shatter`.

## The rules

These are what the pitch film taught. The engine enforces what it can; the rest is on you.

**Footage**

- Phone AV1 clips: ffmpeg's libaom can't decode them and CUDA AV1 decoding silently repeats
  frames. `decode` uses PyAV's libdav1d and fails if more than 5% of frames are repeats.
- Footage stays as shot. No stylised grade, no blurred room, no clean plate, no swapped
  background: cutouts on artificial grounds look composited. Full-frame black and white only
  where a look says so. The cutout is only a depth layer on the identical footage, so graphics
  can sit behind the speaker.
- Cutouts: matte choked ~2 px and softened, green spill removed, VP9 alpha with a keyframe every
  15 frames (the renderer seeks every frame; sparse keyframes freeze it).
- A look-away is cut frame-exact from the approved list: the picture stops on the last on-lens
  frame and holds a still of it. Footage that runs out before the next shot holds its last frame.
- Overlays live between the `OVERLAY-*-BEGIN/END` markers and survive every regeneration. A
  scene whose markers are broken is refused, not overwritten.

**Voice**

- Trim from a 5 ms full-band envelope, never from transcript times. Speech is floor + 14 dB.
- Every in/out is a whole frame, every clip a whole number of frames, joined on the sample clock.
- Gaps are designed speech to speech; `gap_after` gives the breaths.
- Never tighten tails across the board (`check` warns below 0.12 s). Tighten single lines: a
  look-away gets a tighter tail and gap, a take that carries the next word gets a `tail_cut`.
- Cut a stray word inside a line with `remove` (12 ms crossfade), not by re-recording around it.

**Captions**

- Captions follow what was said, not the script. Write FOOTAGE.md by listening; align it to
  whisper's word times; fix mishearings in the table, not in the timing.
- Cues break on . ? ! : always, on , ; once over 14 characters, and before 34 characters or 7
  words. A cue holds 0.6 s past its last word and leaves 0.03 s before the next.
- The clipped-word guard compares the first and last word whisper hears in each trimmed line
  with the untrimmed take, and the run fails on any mismatch.

**Timeline and root**

- Scenes are anchored to a line or a word in it; a scene ends where the next starts. The voice
  never stops between scenes.
- Every transition tween is `ft()` (fromTo, immediateRender false).
- No CSS filter on an outgoing host that carries video: Chrome's capture drops a black frame
  when it switches on. Incoming hosts may blur in.
- Grain and glitch are seeded. Captions are karaoke, one cue at a time.
- A shatter needs `film freeze` (a snapshot of the outgoing scene 0.04 s before its end, plus a
  black-and-white copy) before rendering.

**Music and mix**

- Each section is pinned to a line, measured on exactly the stretch that plays, levelled to
  -16 LUFS, then given its intent gain.
- Music may stop dead on an impact and the next track drop in on the break.
- Music never plays alone where the voice should be; `score` reports any stretch with no line
  for more than 2 s.
- Voice + music at -8 dB, sidechain-ducked + SFX compressed and ducked → limiter → loudnorm
  -14 LUFS, true peak -1. Whooshes peak on the cut (`offset: null`).

**Render and QA**

- Render with TEMP/TMP on a big disk and FFMPEG_PROCESS_TIMEOUT_MS=1800000, two workers. A
  render whose npx parent died keeps going unwatched: `render` refuses to start over one,
  reports one left running, and calls anything short of a full-length file partial.
- After every render, `qa`: isolated dark frames, speech at clip edges (clipped words), line
  loudness against the median, words with no caption, overlapping cues, and contact sheets of
  every boundary. Look at the sheets.
- `thumbs` scores camera-scene frames on the face (eyes open, mouth closed, frontal, centred,
  sharp) and exports the best full-resolution PNGs with a sheet; `--at` adds plain frames.
