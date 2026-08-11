"""The last three steps, once the lip-sync has landed.

    python projects/livingeval3/finish.py

Kept as a script rather than typed each time because the order matters and two
of the steps are easy to get backwards: the presenter goes on before the music,
and the music is normalised last. Scoring a cut and *then* compositing over it
re-encodes the audio a second time for no reason.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from demoforge.compose import compose, duration  # noqa: E402
from demoforge.music import mix  # noqa: E402

OUT = ROOT / "out"
SILENT = OUT / "livingeval3-silent.mp4"
HEAD = OUT / "livingeval3-head.mp4"
BED = OUT / "audio" / "bed-trap-auto.wav"
WITH_FACE = OUT / "livingeval3-face.mp4"
FINAL = OUT / "livingeval3-final.mp4"


def main() -> int:
    for path in (SILENT, HEAD, BED):
        if not path.exists():
            print(f"  missing: {path}")
            return 1

    print(f"\n  silent {duration(SILENT):.1f}s   head {duration(HEAD):.1f}s")

    print("\n== presenter ==")
    compose(SILENT, HEAD, WITH_FACE, size=340, margin=56, corner="br",
            bias=0.46, zoom=0.62)

    print("\n== music ==")
    mix(WITH_FACE, BED, FINAL, music_db=-23.0, duck_db=-14.0)

    total = duration(FINAL)
    print(f"\n  {FINAL.name}   {int(total) // 60}:{total % 60:05.2f}")

    order = json.loads((OUT / "segments" / "order-livingeval3.json").read_text("utf-8"))
    at = 0.0
    print(f"\n  {'start':>7}  {'len':>6}  scene")
    for entry in order:
        print(f"  {int(at) // 60}:{at % 60:05.2f}  {entry['length']:>6.1f}  {entry['segment']}")
        at += entry["length"]
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
