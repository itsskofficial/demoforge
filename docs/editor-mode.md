# Editor mode

The third path through this repository, and the one that assumes the least
about you.

`build` writes a script, clones your voice and speaks it. `present` asks you to
record one clean take per section against a script it wrote first. Both assume
the words come before the recording.

Editor mode assumes the opposite, because that is what people actually have on
the evening they decide to make a video: a deck written last week, and a folder
of long recordings in which the same paragraph was attempted four times.

```bash
demoforge edit new    --project talk --deck deck.pptx --footage "~/Videos/2026-08-27*"
demoforge edit ingest --project talk    # transcribe, find the attempts
demoforge edit plan   --project talk    # choose the keepers, design the slides
demoforge edit build  --project talk    # cut, render, caption, score
```

`demoforge edit all --project talk` runs the three in order. Nothing here
replaces `build` or `present`; all three stay installed.

## The one structural difference

    build     knows the picture, discovers the words
    present   knows the words, builds the picture to fit
    edit      is handed both, and has to work out which words you meant

That last part is the whole job. Thirteen minutes of footage contain about six
minutes of talk and one minute of somebody saying "sorry, again". Finding the
difference is what `ingest` and `plan` are for.

## The transcript is the edit

Nothing downstream of `ingest` opens the audio again. Which take survived,
where a cut lands, what the caption says at 1:14 — all of it is a decision
about a list of words with timestamps.

That is what keeps the cut coherent. Captions come from the same word list the
video was cut from, so they cannot drift: a word removed from the film was
never in the caption list. The usual way this goes wrong is captioning the
master *after* cutting it, and discovering at minute four that everything is
300ms early.

Word-level timestamps, not segment-level. Removing an "um" needs to know where
that word starts to within about 40ms.

Transcription is cached against each source's size and mtime, so re-running
`ingest` after a profile change costs seconds.

## What the model decides, and what it does not

    the model chooses which span, and what the slide says
    arithmetic chooses where exactly the cuts land

A model reading a transcript is genuinely good at *"the third attempt is the
one where he doesn't trail off"*. It is unreliable at *"and it starts at 41.72
seconds"* — that number will be close, and close is a span that opens
mid-consonant.

So `plan` asks for spans and slide content and then snaps every boundary to a
whole word. Filler removal and pause tightening are never asked for at all;
`tighten()` computes them from word timings, which means they are identical on
every re-run and work with no API key at all.

With no key, `plan` falls back to one section per recording, its longest
surviving attempt, in deck order. That is not a good cut. It is a *complete*
one, which is the difference between a rough video and no video.

### The pauses it keeps

`tighten()` shortens any pause over 0.72s down to 0.30s and leaves everything
shorter completely alone. A talk with every pause closed up does not sound
tight, it sounds like a machine reading — the short pauses are the delivery.
The long ones are somebody deciding what to say next.

Filler words come out with the hesitation either side of them. Lifting the "um"
and leaving its two-tenths of silence behind is worse than leaving both.

## The profile

`projects/<name>/edit.json`:

```json
{
  "title": "Vibe coding — do this instead",
  "deck": "C:/Users/me/Downloads/short-3min-horizontal.pptx",
  "footage": ["C:/Users/me/Videos/2026-08-27 16-2*.mkv"],
  "aspect": "16:9",
  "accent": "blue",
  "target_seconds": 195,
  "whisper_model": "medium.en",
  "corrections": { "wipecoding": "vibe coding", "agents .md": "AGENTS.md" },
  "captions": true,
  "music": true,
  "music_db": -27.0
}
```

| field | meaning |
|---|---|
| `deck` | the `.pptx`. Read for structure, never rendered into the film |
| `footage` | files, folders or globs. Order is recording order |
| `aspect` | `16:9`, `9:16` or `1:1` |
| `accent` | one colour for the whole film |
| `target_seconds` | what the planner aims at. `0` means "as tight as it goes" |
| `corrections` | what the recogniser mis-hears, and what it should say |
| `music_db` | the bed's level before ducking |

### `corrections` is not optional in practice

Every recording has three or four words the recogniser cannot get: a product
name, a library, the thing the whole video is about. "Vibe coding" came back as
*wipecoding*, *white coding* and *Wipe Coding* in a single afternoon. A caption
that misspells the title of the video is worse than no caption.

Replacements are matched longest-first over n-grams, so a two-word mishearing
is caught before either of its halves, and a multi-word replacement divides the
original span between its words. The timings never move.

## Slides

There is no `slides.py` here. Presenter mode asks each project to draw its own,
which is right when the visuals *are* the argument. Editor mode's premise is
that you already made the deck and should not have to write it a second time in
Python — so `slidekit` offers eight layouts that will lay out whatever content
they are given:

`title` · `statement` · `stats` · `steps` · `bullets` · `flow` · `equation` ·
`closer`

Every one takes a `kicker`, a `headline`, an optional `sub`, an optional
`footnote` and a list of `items`. Wrap a word in `*asterisks*` to colour it.

Elements arrive on beats that are **fractions of the section**, and the section
is however long the take turned out to be. Pin a reveal to an absolute second
and a 20-second delivery and a 30-second one get the same first 14 seconds of
motion followed by a long stare.

**The slide follows the recording, not the deck.** The deck was the plan; the
recording is the talk. Where they disagree the talk wins, and a point that got
dropped in delivery loses its slide.

### Two regions no layout may draw into

- **The bottom 15.5%** is the caption band, reserved on every section including
  ones with nothing under them. Captions that move whenever a slide is busy are
  captions the eye has to re-find every few seconds.
- **The bottom-right corner** is the presenter inset. Content columns narrow on
  any section framed `corner`.

## Framing

`full` puts the presenter on the whole canvas, dressed with the same accent
hairline and progress rail the slides carry, so the cut to a talking head does
not read as a cut to different software. `corner` puts them in a 330px circle
over the slide.

Open on `full`, close on `full`, and keep it under about a third of the
sections in between. A talking head with nothing beside it is the least
interesting thing you can put on screen — and it is also the only thing that
makes an argument land, which is why the hook and the close get it.

### The push-in

Tightening a static webcam shot leaves visible jump cuts: a shoulder teleports
with nothing to explain it. `lift()` alternates a ~5% push-in across
consecutive segments, so each cut arrives with a change of framing and reads as
deliberate.

It is one line and it does more for the finish than anything else in the
module. It is applied only to `full` sections — inside a 330px circle the jumps
were never visible and the re-encode buys nothing.

## Captions

Two or three words at a time, the current one lit. A full line of subtitle is
read in about 400ms and then the eye has nothing to do for the remaining two
seconds, so it wanders off the frame.

Generated as ASS, one dialogue event per word. A sidecar `.srt` with longer
cards is written next to the video for platforms that would rather render their
own.

## The mix

    denoise and compress the voice  →  lay the bed under it  →  normalise

Denoise before the music arrives, or the compressor spends its range on hiss.
Normalise after the bed, or the number you normalised to is not the number
coming out. It lands at -14 LUFS, which is what the platforms expect and what
stops the video being the quiet one in the feed.

## `plan.json` is the deliverable of `plan`

The whole edit in one document, in seconds and words. Disagree with it by
editing a number:

```bash
demoforge edit build --project talk --only 04_spec   # one section
demoforge edit build --project talk --steps music    # leave the picture alone
```

Every stage writes files the next one reads, so a re-plan never re-transcribes
and a re-render never re-plans.

## Known limits

- **Silence and filler are lexical, not acoustic.** A word mis-heard as "um" is
  cut; a real "um" transcribed as "some" is kept.
- **A section may not span two recordings.** A sentence straddling the moment
  you stopped and restarted the capture cannot be used whole.
- **Sections cut, they do not dissolve.** There is a short dip at the end of
  each slide so two slides in the same layout do not read as one slide whose
  text changed by itself. That is all.
- **Reference PNGs need `comtypes` and PowerPoint.** They are only ever for a
  human comparing the rebuild against the original; the film does not use them.
- **One accent per film.** `slidekit` will take a different accent per section.
  A film that does is not one film.
- **`plan` asks for one long answer and sometimes does not get one.** A
  fourteen-section plan is several thousand tokens of JSON; the call is
  streamed and given fifteen minutes, and it has still come back empty. When it
  does, `plan --from cut.json` settles a hand-written cut through exactly the
  same pass, and `INTAKE.md` is what you write it from.
