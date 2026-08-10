# livingeval — the three-minute cut

The demo this repository was built to make, and the worked example for anyone
copying the pattern.

**Audience:** developers who have never written an eval, and non-technical
people who need to understand why the thing matters. So the words on screen are
"tests", "questions" and "blind" — never coverage, detection power, judges or
regressions. Terminals appear rarely; the argument is carried by drawn scenes,
because a stranger watching once reads a picture and skims a wall of output.

**Length:** 2:57. Twelve scenes, each exactly its narration plus a short tail.

## Files

| File | What it is |
|---|---|
| `narration.json` | The script. Edit this first; everything downstream sizes itself to it. |
| `scenes.py` | Twelve scenes, each a pure function of time. |
| `cards.py` | The two cards from the older six-minute cut. |
| `build.py` | Terminal replays for the older cut. |
| `HANDOFF.md` | Notes for the earlier, longer, terminal-heavy version. |

## Rebuilding it

```bash
cd demoforge
PYTHONPATH=src .venv/Scripts/python.exe -m demoforge.voice script \
    --script projects/livingeval3/narration.json --outdir out/audio/live3 \
    --cfg-weight 0.24 --gap 0.7 --pace 0.85 --max-chars 120
python projects/livingeval3/scenes.py
PYTHONPATH=src python -m demoforge.assemble \
    --narration out/audio/live3/narration.json \
    --order out/segments/order-live3.json \
    --out out/livingeval3-silent.mp4 --tail 0.6
```

That is the watchable demo, narrated, no face. Everything above takes minutes.

For the presenter:

```bash
ffmpeg -i out/livingeval3-silent.mp4 -vn -ac 1 -ar 16000 out/audio/live3/timeline.wav
PYTHONPATH=src python -m demoforge.face loop --src assets/face/driver.mp4 \
    --out assets/face/driver-long.mp4 --seconds 178
PYTHONPATH=src .venv-lipsync/Scripts/python.exe -m demoforge.face sync \
    --video assets/face/driver-long.mp4 --audio out/audio/live3/timeline.wav \
    --out out/livingeval3-head.mp4
PYTHONPATH=src python -m demoforge.compose --base out/livingeval3-silent.mp4 \
    --head out/livingeval3-head.mp4 --out out/livingeval3-final.mp4
```

The lip-sync step runs about an hour. Do it last, once.

## Two things about the numbers

The figures on screen are from real runs of livingeval, not illustrations:
coverage 77% in week one falling to 30% by week eight, detection power of 1.2%
against a rentals regression, and 30→60 / 1→43 after the loop closes.

They are rounded for speech — "one percent" for 1.2%, "forty three" for 43.2%.
If the underlying demo is re-run and the numbers move, **the narration has to
move with them.** They did once already: an earlier cut of the longer demo
quoted 71.7% and 58% from a previous run, and the recording showed 60% and
43.2%. Re-narrate rather than letting a voiceover describe a different run.
