"""The last two steps, once the lip-sync has landed.

    python projects/livingeval3/finish.py

Kept as a script because the order matters and is easy to get backwards: the
presenter goes on before the music, and the music is normalised last. Scoring a
cut and then compositing over it re-encodes the audio a second time for nothing.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from demoforge.compose import compose, duration  # noqa: E402
from demoforge.music import mix  # noqa: E402

OUT = ROOT / "out"
HERE = Path(__file__).parent
SILENT = OUT / "livingeval3-silent.mp4"
HEAD = OUT / "livingeval3-head.mp4"
BED = OUT / "audio" / "bed-trap-auto.wav"
WINDOWS = HERE / "presenter-windows.json"
WITH_FACE = OUT / "livingeval3-face.mp4"
FINAL = OUT / "livingeval3-final.mp4"


def main() -> int:
    for path in (SILENT, HEAD, BED, WINDOWS):
        if not path.exists():
            print(f"  missing: {path}")
            return 1

    print(f"\n  silent {duration(SILENT):.1f}s   head {duration(HEAD):.1f}s")

    # The presenter is hidden across the two real-footage beats. Covering real
    # terminal output with a face wastes the reason for showing it, and cutting
    # to full frame gives the edit a rhythm: talking head for the argument,
    # full frame for the evidence.
    windows = [tuple(w) for w in json.loads(WINDOWS.read_text(encoding="utf-8"))]
    hidden = duration(SILENT) - sum(b - a for a, b in windows)
    print(f"  presenter hidden for {hidden:.1f}s across {len(windows)} visible spans")

    print("\n== presenter ==")
    compose(SILENT, HEAD, WITH_FACE, size=340, margin=56, corner="br",
            show=windows, bias=0.46, zoom=0.62)

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
