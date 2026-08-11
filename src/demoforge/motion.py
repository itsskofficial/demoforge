"""A small motion-graphics kit: scenes as a function of time.

A scene is `draw(d, img, t)` plus a duration. Everything animated is a pure
function of `t`, so any frame can be drawn independently and a render is
deterministic and resumable -- no state carried between frames, no ordering
bugs, and re-rendering one scene never disturbs another.

The vocabulary is deliberately small: things fade and rise into place, numbers
count, bars grow. A demo that people watch once should be legible, not clever.
"""

from __future__ import annotations

import math
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from demoforge.config import FPS, HEIGHT, SEGMENTS, WIDTH

FONTS = Path("C:/Windows/Fonts")

BG = (11, 15, 20)
PANEL = (22, 27, 34)
FG = (237, 242, 247)
MUTED = (138, 149, 163)
DIM = (70, 79, 90)
ACCENT = (88, 166, 255)
WARN = (248, 105, 96)
OK = (72, 207, 115)
GOLD = (240, 190, 90)

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

_FONT_CACHE: dict[tuple[str, int], ImageFont.FreeTypeFont] = {}


def font(name: str, size: int) -> ImageFont.FreeTypeFont:
    key = (name, size)
    if key not in _FONT_CACHE:
        _FONT_CACHE[key] = ImageFont.truetype(str(FONTS / name), size)
    return _FONT_CACHE[key]


def bold(size: int):
    return font("segoeuib.ttf", size)


def regular(size: int):
    return font("segoeui.ttf", size)


def mono(size: int, heavy: bool = False):
    return font("consolab.ttf" if heavy else "consola.ttf", size)


# ---------------------------------------------------------------------------
# timing
# ---------------------------------------------------------------------------


def ease(x: float) -> float:
    """Smoothstep. Slow at both ends, which is what reads as deliberate.

    Note the defaults around it are short (~0.34s). A demo reads as slow long
    before the narration does: half-second fades on every element add up to
    dead time the viewer feels but cannot point at.
    """
    x = max(0.0, min(1.0, x))
    return x * x * (3 - 2 * x)


def ease_out(x: float) -> float:
    x = max(0.0, min(1.0, x))
    return 1 - (1 - x) ** 3


def window(t: float, start: float, dur: float = 0.32) -> float:
    """0 before `start`, 1 after `start + dur`, eased between."""
    if dur <= 0:
        return 1.0 if t >= start else 0.0
    return ease((t - start) / dur)


def blend(colour, amount: float, onto=BG):
    amount = max(0.0, min(1.0, amount))
    return tuple(int(o + (c - o) * amount) for c, o in zip(colour, onto))


# ---------------------------------------------------------------------------
# primitives
# ---------------------------------------------------------------------------


def rise_text(d, xy, text, fnt, colour, t, start, dur=0.34, rise=22, anchor="la"):
    """Fade up into place. The staple move; used for nearly every label."""
    a = window(t, start, dur)
    if a <= 0.001:
        return
    x, y = xy
    d.text((x, y + rise * (1 - a)), text, font=fnt, fill=blend(colour, a), anchor=anchor)


def count_text(d, xy, t, start, dur, lo, hi, fnt, colour, suffix="", anchor="la",
               decimals=0):
    """A number travelling from lo to hi. Reads as a measurement being taken."""
    a = window(t, start, dur)
    if a <= 0.001:
        return
    value = lo + (hi - lo) * ease_out(min(1.0, (t - start) / dur)) if dur > 0 else hi
    text = f"{value:.{decimals}f}{suffix}"
    d.text(xy, text, font=fnt, fill=blend(colour, min(1.0, a * 2)), anchor=anchor)


def grow_bar(d, xy, width, height, t, start, dur, colour, radius=8, track=True):
    """A bar that grows left to right."""
    x, y = xy
    if track:
        d.rounded_rectangle([x, y, x + width, y + height], radius=radius, fill=PANEL)
    a = ease_out(window(t, start, dur))
    w = width * a
    if w > radius:
        d.rounded_rectangle([x, y, x + w, y + height], radius=radius, fill=colour)


def bubble(d, xy, width, lines, fnt, t, start, colour=PANEL, text_colour=FG,
           tail="left", pad=28, line_h=44):
    """A chat bubble that fades up. `lines` is already wrapped."""
    a = window(t, start, 0.5)
    if a <= 0.001:
        return 0
    x, y = xy
    y += 22 * (1 - a)
    height = pad * 2 + line_h * len(lines)
    d.rounded_rectangle([x, y, x + width, y + height], radius=22,
                        fill=blend(colour, a))
    for i, line in enumerate(lines):
        d.text((x + pad, y + pad + i * line_h), line, font=fnt,
               fill=blend(text_colour, a))
    return height


def wrap(text: str, fnt, width: int) -> list[str]:
    words, lines, line = text.split(), [], ""
    for word in words:
        trial = f"{line} {word}".strip()
        if fnt.getlength(trial) <= width:
            line = trial
        else:
            if line:
                lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


def tick(d, xy, size, t, start, colour=OK):
    """A drawn checkmark, revealed along its own stroke."""
    a = ease_out(window(t, start, 0.35))
    if a <= 0.001:
        return
    x, y = xy
    pts = [(x, y + size * 0.5), (x + size * 0.38, y + size * 0.88), (x + size, y + size * 0.1)]
    if a < 0.5:
        p = a / 0.5
        end = (pts[0][0] + (pts[1][0] - pts[0][0]) * p, pts[0][1] + (pts[1][1] - pts[0][1]) * p)
        d.line([pts[0], end], fill=colour, width=max(3, size // 6))
    else:
        p = (a - 0.5) / 0.5
        end = (pts[1][0] + (pts[2][0] - pts[1][0]) * p, pts[1][1] + (pts[2][1] - pts[1][1]) * p)
        d.line([pts[0], pts[1]], fill=colour, width=max(3, size // 6))
        d.line([pts[1], end], fill=colour, width=max(3, size // 6))


def cross(d, xy, size, t, start, colour=WARN):
    a = ease_out(window(t, start, 0.3))
    if a <= 0.001:
        return
    x, y = xy
    w = max(3, size // 6)
    d.line([(x, y), (x + size * a, y + size * a)], fill=colour, width=w)
    d.line([(x + size, y), (x + size * (1 - a), y + size * a)], fill=colour, width=w)


def panel(d, box, t, start, radius=24, fill=PANEL, dur=0.34):
    a = window(t, start, dur)
    if a <= 0.001:
        return False
    x0, y0, x1, y1 = box
    shrink = 16 * (1 - a)
    d.rounded_rectangle([x0 + shrink, y0 + shrink, x1 - shrink, y1 - shrink],
                        radius=radius, fill=blend(fill, a))
    return True


def glow(img: Image.Image, box, colour, strength: float) -> Image.Image:
    """A soft halo behind the one thing on screen that matters.

    Screen-blended rather than alpha-composited so it only ever lightens --
    a halo that darkens the background reads as a smudge.
    """
    if strength <= 0.01:
        return img
    import numpy as np

    layer = Image.new("RGB", img.size, (0, 0, 0))
    ImageDraw.Draw(layer).rounded_rectangle(
        box, radius=28, fill=tuple(int(c * strength) for c in colour))
    layer = layer.filter(ImageFilter.GaussianBlur(38))
    a = np.asarray(img, dtype=np.uint16)
    b = np.asarray(layer, dtype=np.uint16)
    return Image.fromarray((255 - ((255 - a) * (255 - b) // 255)).astype("uint8"))


# ---------------------------------------------------------------------------
# scenes
# ---------------------------------------------------------------------------


@dataclass
class Scene:
    name: str
    seconds: float
    draw: Callable[[ImageDraw.ImageDraw, Image.Image, float], Image.Image | None]


def render(scene: Scene, out: Path | None = None, fps: int = FPS) -> Path:
    out = out or SEGMENTS / f"{scene.name}.mp4"
    out.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
         "-s", f"{WIDTH}x{HEIGHT}", "-r", str(fps), "-i", "-",
         "-c:v", "libx264", "-preset", "medium", "-crf", "18",
         "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out)],
        stdin=subprocess.PIPE)
    try:
        for frame in range(int(scene.seconds * fps)):
            img = Image.new("RGB", (WIDTH, HEIGHT), BG)
            d = ImageDraw.Draw(img)
            result = scene.draw(d, img, frame / fps)
            proc.stdin.write((result or img).tobytes())
    finally:
        proc.stdin.close()
        proc.wait()
    print(f"  {out.name}  {scene.seconds:.1f}s")
    return out


def render_all(scenes: list[Scene]) -> dict[str, float]:
    return {s.name: render(s).stat().st_size and s.seconds for s in scenes}
