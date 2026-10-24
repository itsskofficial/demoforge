# Presenter mode

The other path through this repository. You record yourself; everything else is
built.

The generated path clones your voice, speaks a script and lip-syncs your face.
It is free to iterate, it re-renders overnight when the product changes, and it
is the right choice for a demo that has to stay current. It is also, to anyone
who knows you, faintly wrong — the voice is close and the mouth is close, and
close is worse than absent.

Presenter mode exists for the videos with your name on them. Your real voice
reading your real script beats any model, and it costs one afternoon.

```bash
demoforge present script  --project probeit   # what to say, and when
demoforge present intake  --project probeit   # what you have recorded
demoforge present build   --project probeit   # the cut
```

Both paths stay installed. Nothing here replaces `demoforge build`.

## The one structural difference

    the generated path knows the picture and discovers the words
    presenter mode knows the words and builds the picture to fit

In the generated path a segment is rendered before the narration exists, so
`assemble` pads it by freezing the last frame once the speech turns out longer.
Here the take already exists before anything is drawn, so a slide is rendered
at **exactly** its take's duration. There is nothing to pad, and a re-recorded
take re-renders one slide and leaves the rest alone.

That is also why slides in a presenter-mode project schedule their reveals as
*fractions of the take* rather than at fixed seconds. Pin an animation to
absolute times and a 20-second delivery and a 30-second delivery get the same
first 14 seconds of motion followed by a long stare. See `Beats` in
[`projects/probeit/slides.py`](../projects/probeit/slides.py).

## The profile

`projects/<name>/presentation.json`:

```json
{
  "title": "probeit",
  "aspect": "16:9",
  "sections": [
    {
      "id": "01_hook",
      "presenter": "full",
      "visual": { "kind": "none" },
      "note": "Straight down the lens.",
      "say": "the words you will actually say"
    },
    {
      "id": "02_leak",
      "presenter": "corner",
      "visual": { "kind": "slide", "name": "leak" },
      "say": "..."
    },
    {
      "id": "04_probeit",
      "presenter": "corner",
      "visual": { "kind": "screen", "path": "captures/quickstart.mp4" },
      "say": "..."
    }
  ]
}
```

| field | meaning |
|---|---|
| `id` | names the take file: `takes/01_hook.mp4` |
| `say` | the words. Also drives the duration estimate in the script |
| `note` | delivery direction, printed in the script and nowhere else |
| `presenter` | `full`, `corner` or `off` |
| `visual.kind` | `slide`, `screen` or `none` |
| `aspect` | `16:9`, `9:16` or `1:1` |

**Framing is per section, and it is a real choice.** Use `full` where you are
making an argument and the viewer should be looking at a person. Use `corner`
where the screen is carrying it — a talking head over a table of numbers
competes with the numbers. Use `off` for a beat where the slide should have the
frame to itself.

## Slides

A project supplies `slides.py` with one function:

```python
def render(name: str, seconds: float, out: Path,
           size: tuple[int, int], meta: dict) -> Path:
```

It is called once per section, after the take is measured, with `seconds` set
to that take's speech length. `meta` carries the section's own `meta` block plus
`presenter`, so a slide can lay out around the inset instead of drawing its
right-hand column underneath it.

[`projects/probeit/slides.py`](../projects/probeit/slides.py) is the worked
example: eight slides built on `demoforge.motion`, sized from the image they are
handed so the same code renders the 16:9 cut and the 9:16 one.

## Recording

`present script` writes `RECORDING-SCRIPT.md` — one block per take, in order,
with the words, the direction, the framing and a target duration.

Four things matter, and they are all in that document because they are all
learned the hard way:

- **Same distance, framing and lighting for every take.** Sections cut straight
  into each other. A take shot half a metre closer reads as a different video.
- **Two seconds of silence at both ends.** They are trimmed automatically, and
  they give the trimmer something unambiguous to find.
- **A fluffed line costs one take, not the video.** Stop and say the section
  again from the top.
- **Do not chase the target time.** The slide is drawn to your take. Saying it
  well at 20 seconds beats saying it badly at 14.

Name each file after its section id and drop it in `projects/<name>/takes/`.
Any common container works, and audio-only files are fine for sections framed
`off`.

## Intake

```
  take                  framing    target   actual    trim  note
  --------------------------------------------------------------------
  01_hook               full          22s      21s    1.5s
  02_leak               corner        26s      27s    1.5s
  09_result             corner        38s      52s    1.5s  much longer than planned
  12_close              full          16s       —       —   not recorded
```

`intake` measures every take, finds its speech window with ffmpeg's silence
detector, and flags the two failures worth another take: much longer than
planned, and much shorter than planned. Trimming is taken from the *detected*
window rather than a fixed offset, because the gap between pressing record and
starting to talk is different every time and a fixed offset eventually eats a
word.

## Build

`build` renders each section to its take's length, composites the presenter,
and concatenates. Audio comes from your takes throughout.

It writes a `.timeline.json` next to the video and prints timecodes, which is
what you want for a description box or a blog post.

Re-recorded one section?

```bash
demoforge present build --project probeit --only 09_result
```

Everything else is reused.

## Both cuts from one deck

A vertical short is a second profile pointing at the same `slides.py`:

```python
# projects/probeit-short/slides.py
_MAIN = Path(__file__).resolve().parents[1] / "probeit" / "slides.py"
```

Two decks would drift apart the first time a number changed, and in a demo
about measurement the numbers are the argument. The slides read their size from
the image they are given, so 9:16 needs a different canvas rather than
different code — see the `stacked` branch in `slide_always_works`, where two
side-by-side panels become two stacked ones because there is no width for the
comparison otherwise.

## Known limitations

- **The circular inset is tuned for an arm's-length phone selfie.** It reuses
  `compose.head_clip`, whose `bias` and `zoom` defaults assume a head about 46%
  down the frame. A tripod shot from further back needs those adjusted, and
  they are not yet exposed on the profile.
- **Silence detection is a threshold, not a voice detector.** A noisy room
  raises the floor and the trimmer keeps everything; `--no-trim` and manual
  trimming are the fallback.
- **There is no per-section corner choice.** The inset is bottom-right
  everywhere. `compose` supports the other three and presenter mode does not
  pass it through yet.
- **Sections cut, they do not dissolve.** Fine for a technical demo, wrong for
  something that wants to feel produced.
