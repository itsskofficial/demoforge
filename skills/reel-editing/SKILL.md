---
name: reel-editing
description: Cut a vertical short-form reel out of one long phone recording — measure where the presenter is actually looking and put them full-frame only there, cover the rest with cards and screen-recording cutaways, burn word-level captions, and score it. Use for Instagram Reels, TikTok, YouTube Shorts, or any 9:16 cut where footage is many times longer than the target and the frame is shared with a platform interface.
---

# Cutting a reel from one long take

`edit` assumes a deck and a folder of takes and makes something people watch on
purpose. This assumes one continuous phone recording and makes something that
has to survive a thumb.

```bash
demoforge reel ingest --project talk    # transcribe, and measure the eye line
demoforge reel plan   --project talk    # settle the cut, check the framing
demoforge reel build  --project talk    # cut, render, caption, score
```

## Let the eye line choose the shots

The clearest tell that a video was assembled rather than performed is a talking
head cut full-frame while its eyes are off reading a script. Viewers rarely
name it. They just stop trusting the person.

So measure it first and build the shot list from the answer: full frame only
where the eyes are on the lens, cards and cutaways everywhere else. That is
backwards from how video is normally made, and correct here, because the
footage already exists and the shots are still free.

**Head pose is not enough.** Someone reading off a phone propped beside the
lens is square to camera and their eyes are not — head yaw alone scores that as
perfect. Combine yaw with iris offset measured against each eye's own corners.

**Treat a blink as still looking.** An eye aspect ratio below threshold is a
blink, not a glance away, and scoring it as a look-away punches holes in every
otherwise usable window.

Expect around half the footage to qualify. That is plenty — a reel wants
roughly a third of its runtime on the face anyway, and the rhythm you get for
free (face → card → face → card) is the rhythm a good reel has.

## The frame is not yours

Three regions belong to the platform: the account row across the top, the
caption and audio strip across the bottom (about a fifth of the height), and
the like/comment/share column down the right.

Layouts must measure their content and shrink to fit inside what is left. A
card whose last bullet sits behind the caption bar looks perfect in a render
preview and broken in the feed — which is the only place it matters.

## Everything is twice the size and twice the speed

Type that reads comfortably on a 16:9 slide is unreadable at phone size.
Roughly double it.

Reveals land in about 140ms with a slight overshoot, not a 340ms fade. At this
pace a fade reads as a video that has not started yet, and the thumb is already
moving. The overshoot is what makes 140ms feel deliberate rather than glitchy.

## Screen recordings get framed, not cropped

Cropping a 16:9 editor into 9:16 throws away two thirds of every line and
magnifies the rest past legibility. Sit the capture whole on the reel's own
background instead, with a hairline along its top edge so it reads as mounted
rather than pasted.

Then crop the capture **to its content** before it gets there. A full editor
window scaled into a vertical panel is a grey smear; the code alone, scaled to
roughly 1:1, is readable.

For synthetic terminal cutaways, render few columns at a large font. A
112-column terminal is built for a slide and is illegible in a panel.

**Time-scale a panel to its section rather than looping it.** A terminal replay
has its payoff at the end — the plan, the list of worktrees. A cutaway that
stops two thirds through shows the setup and never the point.

## Capturing an editor on Windows

GDI (`gdigrab`) cannot see Electron's GPU-rendered surface and returns black
frames — from VS Code, and from anything else Chromium-based. `--disable-gpu`
does not reliably fix it either.

Use the Desktop Duplication API instead:

```bash
ffmpeg -f lavfi -i "ddagrab=output_idx=0:framerate=30" -t 7 \
  -vf "hwdownload,format=bgra,crop=1920:900:0:0,format=yuv420p" out.mp4
```

Record a purpose-built repo in a scratch folder, in a fresh window with
extensions disabled — not the real project. It looks identical on screen and
keeps private code, credentials, notifications and personal files out of
something about to be published.

## Mirroring

Flip the presenter horizontally if they prefer it — most people do, because it
is how they see themselves.

Apply it to the presenter's frames only, inside the lift. A flip on the
finished cut also mirrors every card and every screen recording, and backwards
code is a very fast way to look fake. The cost it cannot avoid is text in the
shot: a printed shirt will read backwards, and the only fix is not flipping.

A card or sign the presenter holds up is the exception worth handling: flip
that stretch back, but only from the moment the card is fully up, and hide the
switch under a short punch-in (about 1.16× easing to 1 over 0.3 s). Flipping the
whole shot mirrors the presenter's face for the seconds before the card
arrives, which viewers notice.

## Fonts

libass resolves a style's font family against installed system fonts. A
downloaded family silently falls back to the default sans — which looks like
the caption style did not apply rather than like a missing font. Point the
`subtitles` filter at a `fontsdir`.

Prefer a static weight for captions. Variable fonts resolve to Regular in
libass regardless of what the style asks for.

## Sizing text boxes behind captions

Measure the box from the font's own ascent and descent, not from the line step.
A box sized to the step clips descenders, so "only coding" renders as "onlv
codina" — invisible to anyone glancing at the frame and obvious to anyone
reading it.

And draw **every box first, then every glyph**. A box tall enough to clear the
descenders necessarily overlaps the line below it, so box-then-text per line
paints the next box over the previous line's tails.

## Sound

Derive the bed level: measure the voice, measure the bed, compute the gain that
puts the bed a stated number of LU below. A fixed decibel figure is wrong the
moment a take is quieter than the last one.

Duck depth matters more than level. 12:1 is near-total — the bed vanishes under
speech and exists only in the gaps, which for continuous narration is most of
the film. Around 4:1 keeps it present underneath.

Pick energetic music that is clearly present; "too calm" is the most common
note on a reel. The voice runs continuously and the music never plays alone in
place of it. Master to −14 LUFS / −1 dB true peak. The audio-mix skill covers
sourcing, sections and effects.

## Before you post

- **Captions follow what was said.** Ad-libs stay in the captions; mishearings
  are fixed by aligning the corrected text to whisper's word timings.
- **Joins on the waveform.** Plot the cut voice against the source at every
  join and listen to each first word; a clipped syllable reads as sloppy.
- **Dropped frames.** Scan the render for isolated frames much darker than
  both neighbours.
- **AV1 phone exports.** ffmpeg's libaom fails on them and CUDA decoding
  repeats frames; decode with libdav1d (PyAV) before ingest.
