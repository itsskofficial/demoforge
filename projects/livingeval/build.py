"""The segment list: one entry per step in RECORDING.md.

    python -m demo.record.build            # every terminal segment
    python -m demo.record.build s4_measure # just one

Holds are where the picture stops so the voiceover can land. They are matched
against a line of real output rather than a timestamp, so re-capturing the
demo on a faster or slower machine does not desynchronise the pacing.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from demoforge.render import OUT, SESSIONS, Timeline, render  # noqa: E402

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")


def session(name: str) -> dict:
    return json.loads((SESSIONS / f"{name}.json").read_text(encoding="utf-8"))


# --------------------------------------------------------------------------
# step 1 - here is the app, and here is it getting something wrong
# --------------------------------------------------------------------------
def s1_app() -> tuple[Timeline, str, float]:
    tl = Timeline()
    tl.wait(1.0)
    tl.type_command('python -m demo.ask "Where is my order NW-4143?"')
    tl.play(session("step1_ask"), lines_per_sec=13, gap_cap=1.4, holds=[
        {"match": "lookup_order", "seconds": 2.0},
        {"match": "Your order NW-4143", "seconds": 5.0},
        {"match": "database checks flagged", "seconds": 6.0},
    ])
    tl.wait(2.0)
    tl.type_command("python -m demo.ask --failure")
    tl.play(session("step1_failure"), lines_per_sec=12, gap_cap=1.2, holds=[
        {"match": "12 of 480 recorded answers", "seconds": 3.5},
        {"match": "cancel order NW-4030", "seconds": 2.0},
        {"match": "already out for delivery", "seconds": 7.0},
    ])
    return tl, "livingeval — the agent under test", 46.0


# --------------------------------------------------------------------------
# step 4 - the tests are lying to me
# --------------------------------------------------------------------------
def s4_measure() -> tuple[Timeline, str, float]:
    tl = Timeline()
    tl.wait(1.0)
    tl.type_command("python -m demo.run measure")
    tl.play(session("step4_measure"), lines_per_sec=16, gap_cap=1.0, holds=[
        {"match": "50 cases from week 1", "seconds": 2.5},
        {"match": "2. Coverage", "seconds": 2.0},
        {"match": "week 1  n=60", "seconds": 2.0},
        {"match": "week 8  n=60", "seconds": 7.0},
        {"match": "a regression on rentals", "seconds": 8.0},
        {"match": "false alarms", "seconds": 3.0},
        {"match": "coverage of week 8", "seconds": 5.0},
        {"match": "5. The gate", "seconds": 1.5},
        {"match": "-> BLIND", "seconds": 3.0},
        {"match": "simulated detection power 1.2%", "seconds": 8.0},
        {"match": "terms: back, the, on, rental", "seconds": 5.0},
    ])
    return tl, "livingeval — measure", 88.0


# --------------------------------------------------------------------------
# step 5a - it finds the gap and proposes real traces
# --------------------------------------------------------------------------
def s5a_propose() -> tuple[Timeline, str, float]:
    tl = Timeline()
    tl.wait(1.0)
    tl.type_command("python -m demo.loop")
    tl.play(session("step5_propose"), lines_per_sec=12, gap_cap=1.2, holds=[
        {"match": "power on rentals", "seconds": 2.5},
        {"match": "proposals queued for review", "seconds": 4.0},
        {"match": "where's my deposit?", "seconds": 5.0},
        {"match": "day late returning", "seconds": 5.0},
        {"match": "waiting for a human", "seconds": 5.0},
        {"match": "labelled entirely by the judge", "seconds": 5.0},
    ])
    return tl, "livingeval — propose", 40.0


# --------------------------------------------------------------------------
# step 5c - promote, and measure the same traffic again
# --------------------------------------------------------------------------
def s5c_promote() -> tuple[Timeline, str, float]:
    tl = Timeline()
    tl.wait(1.0)
    tl.type_command("python -m demo.loop --auto-confirm --n 40")
    tl.play(session("step5_promote"), lines_per_sec=15, gap_cap=1.1, holds=[
        {"match": "proposals queued", "seconds": 2.5},
        {"match": "labelling with the judge", "seconds": 5.0},
        {"match": "confirmed 3", "seconds": 2.0},
        {"match": "suite is now", "seconds": 4.0},
        # Anchored on the arrow so these fire on the "after" lines in section 5
        # rather than on the "before" lines that carry the same labels.
        {"match": "30.0%  ->", "seconds": 7.0},
        {"match": "1.2%  ->", "seconds": 8.0},
        {"match": "cases affected", "seconds": 5.0},
        {"match": "gate is now", "seconds": 4.0},
        {"match": "simulated detection power", "seconds": 8.0},
    ])
    return tl, "livingeval — promote and re-measure", 70.0


# --------------------------------------------------------------------------
# step 7 - how you would actually use it
# --------------------------------------------------------------------------
def s7_ci() -> tuple[Timeline, str, float]:
    tl = Timeline()
    tl.wait(1.0)
    tl.type_command("livingeval gate --suite suite.json --traces week8.jsonl")
    tl.play(session("step7_gate"), lines_per_sec=12, gap_cap=1.2, holds=[
        {"match": "BLIND", "seconds": 6.0},
    ])
    tl.wait(1.5)
    tl.type_command("echo $?")
    # The exit status the captured run actually returned, not a typed-in number.
    tl.emit(f"{session('step7_gate')['exit_code']}\r\n", cursor=False)
    tl.wait(6.0)
    return tl, "livingeval — in CI", 34.0


SEGMENTS = {
    "s1_app": s1_app,
    "s4_measure": s4_measure,
    "s5a_propose": s5a_propose,
    "s5c_promote": s5c_promote,
    "s7_ci": s7_ci,
}


def main() -> int:
    wanted = sys.argv[1:] or list(SEGMENTS)
    manifest = {}
    for name in wanted:
        if name not in SEGMENTS:
            print(f"unknown segment {name!r}; have {list(SEGMENTS)}")
            return 2
        if not (SESSIONS / f"{name.split('_')[0]}.json").exists():
            pass  # the builder looks up its own session names
        print(f"[build] {name} ...", flush=True)
        started = time.time()
        try:
            tl, title, target = SEGMENTS[name]()
        except FileNotFoundError as exc:
            print(f"  !! missing capture for {name}: {exc}")
            continue
        out = OUT / f"{name}.mp4"
        seconds = render(tl, out, title, min_seconds=target)
        manifest[name] = round(seconds, 2)
        print(f"  {out.name}  {seconds:.1f}s  (rendered in {time.time() - started:.0f}s)")

    path = OUT / "manifest.json"
    existing = json.loads(path.read_text()) if path.exists() else {}
    existing.update(manifest)
    path.write_text(json.dumps(existing, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
