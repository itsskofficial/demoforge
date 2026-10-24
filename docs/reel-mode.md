# Reel mode

The fourth path, and the one that assumes least of all. No deck, no script, no
per-section takes — one long vertical recording made on a phone, and a short
vertical film at the end.

```bash
demoforge reel ingest --project talk    # transcribe, and measure the eye line
demoforge reel plan   --project talk    # settle the cut, check the framing
demoforge reel build  --project talk    # cut, render, caption, score
```

## Why it is a mode and not a flag on `edit`

    build     knows the picture, discovers the words
    present   knows the words, builds the picture to fit
    edit      is handed a deck and takes, and works out which words you meant
    reel      is handed one take, and works out where you were looking

Three things differ, and each of them changes the output rather than the
options.

**The shot list is derived from the footage.** `gaze` measures where the
presenter's eyes are, per frame, and a section only goes full frame where they
are on the lens. Everywhere else gets a card or a cutaway. That is backwards
from how video is usually made — and it is the right way round here, because
the footage already exists and the shots do not.

**Pacing is a property of the film.** A reel runs slightly fast. `speed: 1.1`
is applied per segment inside `lift`, so caption times are derived from it
rather than corrected for it afterwards.

**The frame is shared with an interface.** The platform draws the account row
across the top, the caption and audio strip across the bottom, and the
like/comment/share column down the right. `reelkit` lays out around all three.
That is the whole reason it exists instead of `slidekit`.

## Gaze

```bash
python -m demoforge.gaze --video take.mp4 --out gaze.json
```

Two signals, and both are needed:

- **Head yaw**, from the nose against the midpoint of the eyes, normalised by
  face width. Catches someone turned towards a second monitor.
- **Iris offset**, from each iris against its own eye corners. Catches someone
  square to camera whose *eyes* are not — which is what reading off a phone
  propped beside the lens looks like, and what head pose alone scores as
  perfect.

A blink counts as still looking; an eye aspect ratio under the threshold is
skipped rather than treated as a glance away. Windows shorter than 1.2s are
dropped and gaps under 0.6s are bridged, because nobody holds a lens perfectly
and a shot list that demands it comes back empty.

`plan` reports the eye-line coverage of every section and warns — loudly, but
without vetoing — when a section asks for `full` and the footage does not
support it. On a real seven-minute take, 48% of the footage was usable full
frame, which was ample: the hook and the close both scored 100%.

## Shots

| `shot` | what it does |
|---|---|
| `full` | the presenter on the whole frame, punched in, with an optional banner |
| `card` | a `reelkit` layout carrying the picture, the take carrying the sound |
| `broll` | a cutaway under the take's audio |

`broll` has two fits. `cover` fills the frame and loops, and is right for
anything shot vertically. `panel` sits the clip whole on the reel's own
background and is right for a screen recording: cropping a 16:9 editor to 9:16
throws away two thirds of every line and magnifies what is left past the point
of legibility.

**A panel is time-scaled to its section, not looped.** A terminal replay has
its payoff at the end — the plan, the list of worktrees — and a cutaway that
stops two thirds of the way through shows the setup and never the point.

## Layouts

`step` · `punch` · `code` · `chain` · `versus` · `stat`

Every one takes a `headline`, an optional `kicker`, `index`, `sub` and a list
of `items`. Wrap a word in `*asterisks*` to colour it.

Elements arrive over 140ms with a slight overshoot rather than fading over
340ms the way the 16:9 deck does. At reel pace a fade reads as a video that has
not started yet, and the thumb is already moving.

Layouts measure before they draw and shrink to fit. The alternative is a card
whose last bullet sits behind the platform's caption bar — invisible in a
render preview and obvious in the feed.

## Mirror

`"mirror": true` flips the presenter horizontally, which is how most people
prefer to see themselves.

It is applied inside `lift`, on the presenter's own frames only. A flip on the
finished cut would also mirror every card and every screen recording, and
backwards code is a very fast way to look fake. The one cost it cannot avoid is
text in the shot — a printed shirt reads backwards, and there is no fixing that
short of not flipping.

## Sound

The bed is sourced from Pixabay through `music_source`, whose CDN path needs no
API key. Level is derived rather than guessed: measure the voice, measure the
bed, and compute the gain that puts the bed `music_under` LU below it.

`music_ratio` is the depth of the duck and matters more than the level. The
default in `music.mix` is 12:1, which is near-total — right for a demo where
narration is the whole point, wrong for a reel that should feel scored. Four
keeps the bed present underneath.

## Known limits

- **Gaze is measured at 5fps.** A glance shorter than about 200ms is invisible
  to it, in both directions.
- **A section may not span a cut in the source.**
- **`type_command` draws its prompt from a module constant.** Overriding it for
  a synthetic terminal cutaway does not always take, so the prompt may read
  `~ $` rather than the project directory.
- **Captions need `fontsdir`.** The style names a downloaded family, and
  without pointing libass at `assets/fonts` it silently falls back to the
  default sans — which looks like the caption style simply did not apply.
