"""Title cards, for the beats that have no command to run.

Deliberately not styled to look like terminal output: a card is something the
presenter talks over, and a card that impersonates a program implies a run that
never happened.

A project profile builds a list of `(image, seconds)` and calls `write`.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from demoforge.config import FPS, HEIGHT, SEGMENTS, WIDTH

FONTS = Path("C:/Windows/Fonts")

BG = (13, 17, 23)
FG = (230, 237, 243)
MUTED = (139, 148, 158)
ACCENT = (88, 166, 255)
WARN = (248, 105, 96)
OK = (86, 211, 100)

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")


def font(name: str, size: int):
    return ImageFont.truetype(str(FONTS / name), size)


def base(title: str, subtitle: str) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    """A titled card with a rule under the heading. Returns it mid-draw."""
    img = Image.new("RGB", (WIDTH, HEIGHT), BG)
    d = ImageDraw.Draw(img)
    d.text((150, 130), title, font=font("segoeuib.ttf", 62), fill=FG)
    d.text((150, 218), subtitle, font=font("segoeui.ttf", 30), fill=MUTED)
    d.line([150, 288, WIDTH - 150, 288], fill=(48, 54, 61), width=2)
    return img, d


def bullet(d: ImageDraw.ImageDraw, y: int, text: str, mono: bool = True) -> None:
    """A quoted line in a slab, for showing real content from the project."""
    d.rectangle([150, y - 14, WIDTH - 150, y + 58], fill=(22, 27, 34))
    d.rectangle([150, y - 14, 156, y + 58], fill=ACCENT)
    d.text((190, y + 8), text[:78],
           font=font("consola.ttf" if mono else "segoeui.ttf", 27), fill=FG, anchor="lm")


def write(name: str, frames: list[tuple[Image.Image, float]]) -> float:
    SEGMENTS.mkdir(parents=True, exist_ok=True)
    out = SEGMENTS / f"{name}.mp4"
    proc = subprocess.Popen(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
         "-s", f"{WIDTH}x{HEIGHT}", "-r", str(FPS), "-i", "-",
         "-c:v", "libx264", "-preset", "medium", "-crf", "18",
         "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out)],
        stdin=subprocess.PIPE,
    )
    total = 0.0
    for img, seconds in frames:
        raw = img.tobytes()
        for _ in range(int(seconds * FPS)):
            proc.stdin.write(raw)
        total += seconds
    proc.stdin.close()
    proc.wait()
    print(f"  {out.name}  {total:.1f}s")
    return total
