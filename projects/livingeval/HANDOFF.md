# Screen recordings — ready for your voiceover

**`out/master.mp4` — 5:58, 1920×1080, 30fps, no audio.**

Every segment in RECORDING.md order, hard-cut, one file. Individual segments are in
`out/segments/` if you want to re-time anything in an editor.

> This tooling used to live in `livingeval/demo/record/`. It is now its own project,
> **demoforge**, and livingeval is just the first thing it records. Paths below are
> relative to the demoforge repo, and commands need `DEMOFORGE_TARGET` pointing at
> your livingeval checkout.

## Read this first: three numbers in your script changed

Step 5's payoff was re-run for real today and came out **lower** than the numbers written
in RECORDING.md. What is on screen is what the code produced; the script is what needs
editing, not the video.

| RECORDING.md says | the recording shows |
|---|---|
| coverage `30.0% -> 71.7%` | **`30.0% -> 60.0%`** |
| power on rentals `1.2% -> 58.0%` | **`1.2% -> 43.2%`** `[38.5%, 48.1%]` |
| cases affected `0 -> 26 of 101` | **`0 -> 20 of 87`** |

The cause is `--n 40` being a *total* proposal count, not "40 more": with 12 already
queued it added 25, so the suite grew to 87 rather than 101. Fewer added cases, less
coverage bought.

**Step 6 needs a bigger edit.** Your line is *"still blind — but for one reason now
instead of three."* The gate is still blind for **two** reasons, coverage (60% < 70%) and
power (43.2% < 80%). Suggested replacement:

> Still blind — but for two reasons now instead of three, and both of them are just
> "not enough yet" rather than "can't see it at all." Coverage went from 30 to 60. The
> rentals bug went from 1 percent caught to 43. It's telling me to keep going, and it's
> telling me exactly how far.

If you would rather have the bigger numbers, re-run `python -m demo.loop --reset` then
`python -m demo.loop --auto-confirm --n 70` and re-render — about four minutes total
(commands at the bottom).

## Timecodes

| start | length | step | what you're saying over it |
|---|---|---|---|
| 0:00.00 | 46.0s | Step 1 | Here's the app — and here's it getting one wrong |
| 0:46.00 | 9.0s | Step 2 | So I wrote tests |
| 0:55.00 | 12.2s | Step 3 | Then my users changed |
| 1:07.23 | 88.0s | Step 4 | The tests are lying to me |
| 2:35.23 | 40.0s | Step 5a | Mine the traffic the suite cannot see |
| 3:15.23 | 36.9s | Step 5b | A human confirms every case (browser) |
| 3:52.17 | 70.0s | Step 5c + 6 | Promote, re-measure, still not done |
| 5:02.17 | 22.1s | Step 7a | The dashboard (browser) |
| 5:24.30 | 34.0s | Step 7b | In CI: it exits non-zero |

Also in `out/segments/timecodes.json`.

The picture **stops on every number you have a line about** — the coverage bars, the
power table, the gate, the before/after. Those holds are 5–8 seconds, so you have room
to talk without pausing playback. Total runs 6 minutes against your 4-minute target
because of that; trimming holds is the easiest place to get time back.

## One nice thing that happened

Step 1's live question was a real call to the model, and it produced a **fresh**
contradiction on camera — the agent said NW-4143 was *"still in transit"* when the row
says `packed`, and the mechanical check caught it:

```
database checks flagged: contradicts_tool
  contradicts_tool: [{"claimed": "in_transit", "actual": "packed", "order": "NW-4143"}]
```

That is the same failure DEMO.md §6 uses to show the local judge waving something
through. Nothing was staged to get it; worth a sentence.

## What is real, and what I did to it

Everything on a terminal screen is real output from a real run — captured to
`demo/record/sessions/*.json` with timestamps, then replayed. No line was written,
shortened or reordered. What I controlled is pace:

- **Dead air is compressed** to at most ~1.1s. The title bar shows the *real* elapsed
  time of the actual run throughout, so the compression is visible rather than hidden.
- **Commands are typed** at human speed; the output that follows is the recorded output.
- **`echo $?` in step 7b** prints the exit status the captured run actually returned (2),
  rendered rather than re-run — WSL's `bash` shadows Git bash here and broke the shell
  capture.
- **Step 7b's command reads `livingeval gate ...`** but was executed as
  `python -m livingeval.cli gate ...` — same entry point, because installing the package
  globally would have shadowed the `src/` checkout you work in.
- **Steps 2 and 3 are graphics, not terminal output**, deliberately: they are things you
  say over a picture, and I did not want a card that looks like a program that ran. The
  week table in step 3 is counted from the 480 traces in the database at render time, so
  it cannot drift from the data. The example questions in step 2 are real cases from
  `demo/results/suite.json`.
- **Browser segments are a real Chromium** driven by Playwright against the real server
  on `:8000` — real clicks, real confirmations written to the database. The cursor is
  drawn in, because a browser's own pointer is not in the capture.

Nothing was captured off your physical screen, so nothing depends on the machine having
stayed unlocked, and no notification or stray window can appear in the footage.

## State I left behind

- **The suite is now 87 cases**, not the frozen 50 — steps 5b and 5c promoted into it.
  Put it back with `python -m demo.loop --reset` before any further recording.
- **The review queue is empty** (all confirmed and promoted).
- **The server is still running** on `:8000` from `projects/livingeval/serve_fast.py`. Kill it
  when you're done. It is `dev.py serve` with the startup refit disabled — the refit
  embeds all 480 traces before binding the port, which left the socket dead for over ten
  minutes; nothing on screen reads the fitted scorer.
- Three proposals were confirmed through the UI during the step 5b recording, under the
  reviewer name the form was left with.

## Re-rendering

Pacing lives in `projects/livingeval/build.py` as *holds* matched against a line of real
output, so re-capturing on a different machine will not desynchronise them.

```bash
export DEMOFORGE_TARGET=D:/Career/Technology/Projects/livingeval
python projects/livingeval/build.py s4_measure   # one segment, ~30s
python projects/livingeval/build.py              # all terminal segments
python projects/livingeval/cards.py              # steps 2 and 3
python -m demoforge.browser review               # needs pending proposals
python -m demoforge.stitch                       # master + timecodes
```

To re-capture a command's output for real:

```bash
python -m demoforge.capture step4_measure.json -- python -m demo.run measure
```
