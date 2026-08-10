---
name: screen-capture
description: Record terminal sessions and browser interactions for a demo video without capturing the physical screen. Use when a demo needs real command output or real UI, and must be reproducible, notification-free, and independent of whether anyone is at the machine. Covers capture-then-replay, pacing holds, and headless browser recording.
---

# Recording a terminal and a browser, without a screen

Screen-capturing a real desktop is the obvious approach and the wrong one for
anything you will re-render. It breaks if the machine locks, it catches
notifications, it depends on fonts and window size, and re-recording means
performing the whole thing again without fumbling.

Instead: **run the real command, keep its output and timing, replay it as
video.**

## Terminals

```bash
python -m demoforge.capture step4.json -- python -m yourapp measure
python projects/<name>/build.py
```

`capture` runs the real command and stores `(seconds, bytes)` pairs. Nothing is
edited, shortened or reordered — the replay shows exactly what the program
printed. What you control is *pace*:

- **Dead air is compressed** to about a second. A twenty-minute computation
  becomes a beat.
- **The real elapsed time stays on screen** in the title bar throughout, so the
  compression is stated rather than hidden. Do not remove this; it is the
  difference between editing and misleading.
- **Output unrolls line by line** at a readable rate rather than appearing in
  blocks.

### Holds: pacing anchored to output, not timestamps

A hold pauses the picture on a line the narration talks about:

```python
tl.play(session("step4"), holds=[
    {"match": "week 8  n=60", "seconds": 7.0},
    {"match": "-> BLIND",     "seconds": 3.0},
])
```

Matching on *text* rather than a timestamp means re-capturing on a faster
machine does not desynchronise the edit. Match on something unique — anchor on a
distinctive substring (`"1.2%  ->"`) when a label appears twice in one run.

### Gotchas

- **Encoding.** A recorder that tees UTF-8 output to a cp1252 console dies
  mid-render on a box-drawing character. Reconfigure stdout to UTF-8 in *both*
  the program and the recorder.
- **Capture at byte granularity**, not `readline()`, or progress bars that use
  carriage returns stall the timeline.
- **Exit codes are worth showing.** Render `echo $?` from the recorded status
  rather than re-running the command.

## Browsers

```bash
python -m demoforge.browser review
```

Playwright drives a real Chromium and records it. Headless, so it works whether
or not anyone is looking at the screen, and the viewport is fixed at 1920×1080
regardless of the monitor.

- **Draw the cursor.** A browser's own pointer is not in the capture. demoforge
  injects an SVG cursor and a click pulse; without it, clicks are invisible.
- **Move like a hand.** Ease in and out between targets and pause before
  clicking. Instant teleporting reads as a robot.
- **Let the page breathe.** Hold a few seconds on arrival so a viewer can read
  before anything moves.
- The clicks are real and hit a real server, so state changes. Reset between
  takes.

## What is honest

Every frame is real output or a real page. Two things are constructed, and both
should be stated in a handoff note: dead air is compressed (with the real
elapsed time on screen), and title cards are drawn rather than captured. Cards
are never styled to look like terminal output — a card that impersonates a
program implies a run that never happened.
