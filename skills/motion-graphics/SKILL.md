---
name: motion-graphics
description: Draw animated scenes for a video — title cards, counters, charts, chat bubbles, overlays behind a speaker, transitions. Use when a video needs to explain something no screen recording can show, when a cut needs less terminal and more picture, or when building HyperFrames (HTML + GSAP) scenes for Film mode. Covers the scene-as-function-of-time model, timing to spoken words, and the browser-render traps that drop frames.
---

# Drawing the parts you cannot record

A demo made only of screen recordings explains *what the tool prints*. It rarely
explains *why anyone should care*. The parts that carry the argument — the
problem, the shape of the data, the before and after — usually have to be drawn.

This matters most for a mixed audience. Developers will read a terminal; nobody
else will.

## A scene is a function of time

```python
def draw(d, img, t):
    heading(d, "Then the business changed.", t)
    grow_bar(d, (300, 400), 900, 44, t, start=1.2, dur=0.6, colour=WARN)
    return img

Scene("s05_change", seconds=18.1, draw)
```

Every animated value is computed from `t` alone. No state carries between
frames. That buys three things: any frame can be drawn independently, a render
is deterministic, and re-rendering one scene never disturbs another.

## The vocabulary, deliberately small

| Helper | Use |
|---|---|
| `rise_text` | Text fades up into place. The staple; nearly every label. |
| `count_text` | A number travelling from one value to another. Reads as measurement. |
| `grow_bar` | A bar growing left to right. |
| `bubble` / `wrap` | Chat bubbles for conversation. |
| `tick` / `cross` | Drawn along their own stroke, not stamped. |
| `panel` | A card that scales up slightly as it fades in. |
| `glow` | A screen-blended halo. For the one thing that matters. |

`ease` (smoothstep) for most things, `ease_out` for anything arriving.

A demo watched once should be legible, not clever. Resist a fourth kind of
transition.

## Timing to the narration

**Speak the script first, then size the scenes.** The narration manifest records
measured durations, and a scene should be exactly its line plus a short tail:

```python
seconds = measured[name] + 1.0
```

Guessing scene lengths and discovering later that the narration overruns means
rendering twice. If a scene is already rendered and the line grows,
`demoforge.assemble` holds the final frame rather than re-rendering — but
getting it right up front is cheaper.

Stagger reveals inside a scene against the words: if the line says "week one,
seventy seven percent" four seconds in, the counter should land at four seconds.
Take those offsets from the transcript's word times, not a stopwatch, and keep
them as named constants (`W.dead`, `W.company`) so a re-cut moves the beat with
the word.

## Legibility

- **Type is bigger than feels right.** 60px headings, 30px+ body at 1080p.
  People watch demos in a small embedded player.
- **One idea per scene.** If two things need saying, that is two scenes.
- **Colour carries meaning consistently.** Pick one accent, one warning, one
  success and never reuse them decoratively.
- **Contrast against the panel, not the page**, once anything sits on a card.
- **Never style a card as terminal output.** It implies a run that did not happen.

## HyperFrames scenes (Film mode)

Film mode draws in the browser instead: each scene is an HTML composition with
one paused GSAP timeline, rendered by `npx hyperframes render`. The same rule
holds (every value a function of the timeline's time), and the browser adds
traps of its own:

- **`fromTo` overlays need `immediateRender: false`.** Otherwise the start
  state paints at build time and the first overlay shows from frame 0.
- **No CSS `filter` on an element hosting video during a transition.** Chrome
  capture drops a black frame when a filter switches on over a video. Move,
  scale and fade the video host; blur and grade only overlays and stills.
- **Scrims behind graphics on real footage.** A busy room eats thin type; a
  soft dark panel or backing card keeps it legible without grading the shot.
- **Leave the caption band (y 900–1020 at 1080p) empty** on every scene.
- **Never `rm -rf` a scene folder.** `assets` and `lib` inside it are directory
  junctions to the shared folders, and deleting through them deletes the
  originals.
- **Verify with snapshots** (`npx hyperframes snapshot <dir> --at t1,t2,...`)
  before rendering: a contact sheet of the moments that matter costs seconds; a
  full render costs half an hour.
- **Render with temp on a big disk** and `FFMPEG_PROCESS_TIMEOUT_MS=1800000`;
  a four-minute 1080p render needs ~10 GB of scratch and its audio pass outlives
  the default timeout. `demoforge film render` sets both.
- **Scan every render for dropped frames** (`demoforge film qa`) before anyone
  watches it.

## Cost (Pillow scenes)

Frames are drawn with Pillow and piped straight to ffmpeg as raw video —
nothing touches disk. A three-minute 1080p30 sequence renders in a couple of
minutes on a laptop CPU, so iterating on visuals is cheap. This is the opposite
of the lip-sync stage, and the reason to get the picture right before the face.
