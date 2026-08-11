"""Put the talking head in the corner of the screen recording.

The presenter is a circular inset with a soft ring, bottom-right by default.
Two details matter more than they sound:

* **The inset frames the head, not the frame.** A phone video is portrait, and
  a square crop of it is only as wide as the video -- so a head filmed at arm's
  length fills the square and a circle inscribed in it slices the jaw off. The
  head is scaled to fit the circle's height instead, and the gap at the sides is
  filled with a blurred copy of the same frame.

* **The head only appears while it is speaking.** Lip-sync models regenerate
  the mouth over silence too, and the original footage underneath is someone
  mid-sentence -- so a face left on screen through a pause pulls expressions
  that belong to words nobody is hearing. Cutting the inset out during
  silence removes the problem rather than trying to animate around it.

    python -m demoforge.compose --base master.mp4 --head face.mp4 --out final.mp4
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from demoforge.config import HEIGHT, OUT, WIDTH

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

SIZE = 340          # diameter of the inset
MARGIN = 56
# Centre of the square crop, as a fraction down the source frame. A head filmed
# at arm's length on a phone sits around 40% down; 0.30 crops to the forehead.
FACE_BIAS = 0.46


def duration(path: Path) -> float:
    return float(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True, check=True).stdout.strip())


def circle_mask(size: int) -> Path:
    """A greyscale circle, generated once and reused by ffmpeg.

    Greyscale on purpose: ffmpeg's `alphamerge` takes the **luma** of its second
    input as the alpha channel, not that input's own alpha. Handing it a white
    RGBA image with a circular alpha channel produces a fully opaque square,
    which is exactly what it looks like.
    """
    from PIL import Image, ImageDraw, ImageFilter

    path = OUT / f"_mask{size}.png"
    if path.exists():
        return path
    scale = 4
    big = Image.new("L", (size * scale, size * scale), 0)
    ImageDraw.Draw(big).ellipse([0, 0, size * scale - 1, size * scale - 1], fill=255)
    mask = big.resize((size, size), Image.LANCZOS).filter(ImageFilter.GaussianBlur(1.1))
    path.parent.mkdir(parents=True, exist_ok=True)
    mask.convert("L").save(path)
    return path


def head_clip(head: Path, out: Path, size: int = SIZE, bias: float = FACE_BIAS,
              zoom: float = 0.66) -> Path:
    """Fit the presenter's head into a circle, blurred fill at the sides.

    `zoom` is how much of the circle's height the head should occupy: lower
    shows more around it. 0.66 keeps hair and chin inside the circle for a
    typical arm's-length selfie.
    """
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0", str(head)],
        capture_output=True, text=True, check=True).stdout.strip().split(",")
    w, h = int(probe[0]), int(probe[1])

    # Foreground: a region taller than the frame is wide, so the whole head fits
    # with air above the hair and below the chin. Scaled to the circle's height,
    # it is narrower than the circle.
    tall = min(h, int(w / max(0.4, min(1.0, zoom)))) // 2 * 2
    y_fg = max(0, min(h - tall, int(h * bias - tall / 2)))

    # Background: the same frame, cropped square and blurred, filling the gap at
    # the sides. A flat colour cannot match a wall with a gradient on it and
    # leaves two vertical seams; a blurred copy of the wall always matches.
    square = min(w, h)
    y_bg = max(0, min(h - square, int(h * bias - square / 2)))

    mask = circle_mask(size)
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(head), "-i", str(mask),
         "-filter_complex",
         f"[0:v]split=2[a][b];"
         f"[a]crop={square}:{square}:{(w - square) // 2}:{y_bg},"
         f"scale={size}:{size},boxblur=22:2[bg];"
         f"[b]crop={w}:{tall}:0:{y_fg},scale=-2:{size}[fg];"
         f"[bg][fg]overlay=(W-w)/2:0,format=rgba[c];"
         f"[c][1:v]alphamerge[out]",
         "-map", "[out]", "-c:v", "qtrle", "-an", str(out)],
        check=True)
    return out


def compose(base: Path, head: Path, out: Path, size: int = SIZE, margin: int = MARGIN,
            corner: str = "br", show: list[tuple[float, float]] | None = None,
            bias: float = FACE_BIAS, zoom: float = 0.66) -> Path:
    """Overlay `head` on `base`. `show` is a list of (start, end) to appear in."""
    rounded = out.with_suffix(".head.mov")
    head_clip(head, rounded, size, bias, zoom)

    x = margin if corner in ("bl", "tl") else WIDTH - size - margin
    y = margin if corner in ("tl", "tr") else HEIGHT - size - margin

    enable = ""
    if show:
        clauses = "+".join(f"between(t,{a:.2f},{b:.2f})" for a, b in show)
        enable = f":enable='{clauses}'"

    # The overlay follows whichever input runs longest, so a head video even
    # slightly longer than the cut leaves a frozen tail on the end. Pin the
    # output to the base's own duration.
    ring = size + 10
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error",
         "-i", str(base), "-i", str(rounded),
         "-filter_complex",
         f"[0:v]drawbox=x={x - 5}:y={y - 5}:w={ring}:h={ring}:"
         f"color=0x0b0f14@0.0:t=fill[bg];"
         f"[bg][1:v]overlay={x}:{y}{enable}[v]",
         "-map", "[v]", "-map", "0:a?", "-c:v", "libx264", "-preset", "medium",
         "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
         # -t as an OUTPUT option. Before an input it only limits that input's
         # read, which does not stop overlay running on to the longer one.
         "-t", f"{duration(base):.3f}",
         "-movflags", "+faststart", str(out)],
        check=True)
    rounded.unlink(missing_ok=True)
    print(f"  {out.name}  {duration(out):.1f}s")
    return out


def speaking_windows(narration: Path, order: Path, pad: float = 0.25) -> list[tuple[float, float]]:
    """When is someone actually talking, on the master timeline?

    Built from the narration manifest and the running order rather than by
    analysing the audio, because the manifest already knows exactly which line
    sits on which segment and how long it ran.
    """
    lines = {n["id"]: n for n in json.loads(narration.read_text(encoding="utf-8"))}
    windows, at = [], 0.0
    for entry in json.loads(order.read_text(encoding="utf-8")):
        name = entry["segment"]
        length = entry.get("length") or 0.0
        line = lines.get(name)
        if line:
            start = at
            windows.append((max(0.0, start - pad), start + line["seconds"] + pad))
        at += length
    return windows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--head", required=True)
    ap.add_argument("--out", default=str(OUT / "final.mp4"))
    ap.add_argument("--size", type=int, default=SIZE)
    ap.add_argument("--margin", type=int, default=MARGIN)
    ap.add_argument("--corner", default="br", choices=["br", "bl", "tr", "tl"])
    ap.add_argument("--bias", type=float, default=FACE_BIAS)
    ap.add_argument("--zoom", type=float, default=0.66,
                    help="lower shows more around the head")
    ap.add_argument("--windows", default=None,
                    help="JSON list of [start,end] pairs the head appears in")
    args = ap.parse_args()

    show = json.loads(Path(args.windows).read_text(encoding="utf-8")) if args.windows else None
    compose(Path(args.base), Path(args.head), Path(args.out), args.size,
            args.margin, args.corner, show, args.bias, args.zoom)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
