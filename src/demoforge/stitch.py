"""Concatenate the segments in RECORDING.md order and write the timecodes.

Hard cuts, no crossfades: the boundaries are where the voiceover changes
subject, and a clean cut is easier to slide around in an editor than a
dissolve.

    python -m demo.record.stitch
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from demoforge.config import OUT as OUTDIR, SEGMENTS as SEG

# The running order is the project's, not demoforge's: a profile writes
# `order.json` as a list of {segment, step, voiceover} and this reads it.
ORDER_FILE = SEG / "order.json"


def duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True, check=True).stdout.strip()
    return float(out)


def tc(seconds: float) -> str:
    return f"{int(seconds) // 60}:{seconds % 60:05.2f}"


def main() -> int:
    order_file = Path(sys.argv[1]) if len(sys.argv) > 1 else ORDER_FILE
    if not order_file.exists():
        print(f"no running order at {order_file}. A project profile writes it.")
        return 1
    order = json.loads(order_file.read_text(encoding="utf-8"))
    name_of = [(o["segment"], o.get("step", ""), o.get("voiceover", "")) for o in order]
    out = OUTDIR / f"{order_file.stem.replace('order', 'master')}.mp4"

    missing = [n for n, _, _ in name_of if not (SEG / f"{n}.mp4").exists()]
    if missing:
        print(f"missing segments: {missing}")
        return 1

    listing = SEG / "_concat.txt"
    listing.write_text("".join(f"file '{(SEG / f'{n}.mp4').as_posix()}'\n"
                               for n, _, _ in name_of), encoding="utf-8")
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
         "-i", str(listing), "-c:v", "libx264", "-preset", "medium", "-crf", "18",
         "-pix_fmt", "yuv420p", "-r", "30", "-movflags", "+faststart", str(out)],
        check=True)

    rows, at = [], 0.0
    for name, step, what in name_of:
        d = duration(SEG / f"{name}.mp4")
        rows.append({"start": round(at, 2), "start_tc": tc(at), "length": round(d, 2),
                     "segment": name, "step": step, "voiceover": what})
        at += d
    (SEG / "timecodes.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")

    print(f"\n{out.name}  {tc(at)} total\n")
    print(f"{'start':>8}  {'len':>6}  {'step':<16}  segment")
    for r in rows:
        print(f"{r['start_tc']:>8}  {r['length']:>6.1f}  {r['step']:<16}  {r['segment']}")
    print(f"\nmeasured total {tc(duration(out))}")
    return 0


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):
        if hasattr(_s, "reconfigure"):
            _s.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
