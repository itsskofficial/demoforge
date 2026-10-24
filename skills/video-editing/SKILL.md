---
name: video-editing
description: Cut a finished explainer out of a slide deck and a folder of raw webcam recordings — transcribe, throw away the fluffed takes, rebuild the deck as motion slides timed to the delivery, burn word-level captions and score it. Use when someone has recorded themselves talking over a presentation and wants a video, when raw footage is many times longer than the target runtime, or when a cut needs bloopers, filler and dead air removed.
---

# Editing footage you did not plan

The other two paths in this repository start from a script. `build` writes one
and speaks it; `present` asks you to record one section at a time against it.
Editor mode starts from what people actually produce: a deck written last week,
and twelve files of somebody saying roughly the right thing four times each.

```bash
demoforge edit new    --project talk --deck deck.pptx --footage ~/Videos/2026-08-27*
demoforge edit ingest --project talk    # transcribe, find the attempts
demoforge edit plan   --project talk    # choose the keepers, design the slides
demoforge edit build  --project talk    # cut, render, caption, score
```

## The transcript is the edit

Nothing downstream of `ingest` opens the audio. Every decision — which take
survived, where a cut lands, what the caption says at 1:14 — is a decision
about a list of words with timestamps on them.

This is not a convenience. It is what makes the cut *consistent*. Captions
generated from the same word list the video was cut from cannot drift, because
a word removed from the film was never in the caption list. The usual failure
here is captioning the master after cutting it and discovering at minute four
that everything is 300ms early.

Word-level timestamps, not segment-level. Segment timings are enough to caption
a video and useless for cutting one: removing an "um" needs to know where that
word starts to within about 40ms, and a cut placed on a segment boundary lands
in the middle of the next breath.

## Split the decisions by what each side is good at

    the model chooses which span, and what the slide says
    arithmetic chooses where exactly the cuts land

A language model reading a transcript is genuinely good at *"the third attempt
is the one where he doesn't trail off"*. It is unreliable at *"and it starts at
41.72 seconds"* — the number will be close, and close means a span that opens
mid-consonant.

So `plan` asks for spans and slide content, and then snaps every boundary to a
whole word before writing `plan.json`. Filler removal and pause tightening are
never asked for at all; they are computed from word timings in `tighten()`,
which means they are identical on every re-run and work with no API key at all.

### Do not remove every pause

`tighten()` shortens pauses over 0.72s down to 0.30s and leaves everything
shorter completely alone. A talk with all its pauses closed up does not sound
tight, it sounds like a machine reading — the short pauses *are* the delivery.
The long ones are somebody deciding what to say next, and those are the ones
nobody wants to watch.

Similarly: filler words come out with the hesitation on either side of them.
Lifting "um" and leaving its two-tenths of silence behind is worse than leaving
the "um" in.

## Hide the jump cuts you just made

Tightening a static webcam shot leaves visible jumps — a shoulder teleports
across the frame with nothing to explain it. Alternating a ~5% push-in across
consecutive segments turns each of them into an apparent change of framing,
which reads as a deliberate edit rather than a mistake.

It is one line in `lift()` and it does more for the finish than anything else
in this file.

On `corner` sections the presenter is a 330px circle and the jumps are
invisible, so the push-in is applied only to `full` sections. Applying it
everywhere costs a re-encode and buys nothing.

## Rebuild the deck; do not photograph it

Exporting the .pptx to PNGs gives a picture of a deck, and a still on screen
for twenty seconds is where attention goes to die. `deck.py` reads the file for
*structure* — every text run with its geometry and a guess at its role — and
`slidekit.py` draws it again with each element arriving on its own beat.

Beats are fractions of the section, and the section is however long the take
turned out to be. Pin a reveal to an absolute second and a 20-second delivery
and a 30-second one get the same first 14 seconds of motion followed by a long
stare.

**Follow the recording, not the deck.** The deck is the plan and the recording
is the talk; where they disagree, the talk wins. If a point got dropped in
delivery, its slide goes with it.

## Two regions are spoken for, on every frame

Layouts may not draw into either, and the reason is the same both times: the
viewer should never have to find out where a thing lives twice.

- **The bottom 15.5%** is the caption band, reserved on every section including
  the ones with nothing under them. Captions that move whenever a slide gets
  busy are captions the eye has to re-locate every few seconds.
- **The bottom-right corner** is the presenter inset. Content columns narrow on
  any section framed `corner`. Finding the collision after the composite means
  re-rendering the slide, and the slide is the expensive part.

## Captions: two or three words, the current one lit

A full line of subtitle is read in about 400ms and then the eye has nothing to
do for the remaining two seconds, so it wanders off the frame. A card that
changes on the beat of the speech never gives it the chance.

Generated as ASS, one dialogue event per word, each showing its whole card with
the live word coloured. ASS *does* have karaoke tags that would do this in one
event — but karaoke timing is centiseconds relative to the line's own start and
accumulates rounding across a long card. Word timings are absolute; keep them
absolute.

`PlayResX/Y` must match the real frame. It is what makes every margin in the
style block a true pixel measurement, so one caption file burns correctly at
1080p and at a vertical crop with no second set of numbers.

## The order of operations in the mix

    denoise and compress the voice  →  lay the bed under it  →  normalise

Denoise before the music arrives or the compressor spends its range on hiss.
Normalise after the bed or the number you normalised to is no longer the number
coming out. Land at -14 LUFS, which is what every social platform is expecting
and what stops your video being the quiet one in the feed.

## `plan.json` is the actual deliverable of `plan`

It is the whole edit in one document, in seconds and words. Disagreeing with
the cut means changing a number in a file, not re-prompting a model:

```bash
# nudge a span, then re-render only what changed
demoforge edit build --project talk --only 04_spec

# leave the picture alone and re-do the sound
demoforge edit build --project talk --steps music
```

Every stage writes files the next one reads, so `ingest` is never repeated for
a re-plan and `plan` is never repeated for a re-render. Transcription is cached
against each source's size and mtime.

## Known limits

- **Silence and filler are lexical, not acoustic.** A word whisper mis-hears as
  "um" is cut; a genuine "um" it transcribes as "some" is kept.
- **A section may not span two recordings.** If a sentence straddles the moment
  you stopped and restarted the capture, it cannot be used whole.
- **Sections cut, they do not dissolve.** There is a short dip at the end of
  each slide so two slides in the same layout do not read as one slide whose
  text changed by itself, but that is all.
- **One accent per film.** `slidekit` will happily take a different accent per
  section; a film that does is not one film.
