"""Put the talking head in the corner of the screen recording.

The presenter is a circular inset with a soft ring, bottom-right by default.
Two details matter more than they sound:

* **The inset is cropped to the face, not the frame.** A phone video is
  portrait; dropping it whole into a corner wastes most of the circle on
  chest and ceiling. The crop is centred on the upper third, where a head
  filmed at arm's length actually sits.

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
FACE_BIAS = 0.30    # centre of the crop, as a fraction down the source frame


def duration(path: Path) -> float:
    return float(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True, check=True).stdout.strip())


def circle_mask(size: int, ring: int = 6) -> Path:
    """A PNG mask with a soft edge, generated once and reused by ffmpeg."""
    from PIL import Image, ImageDraw, ImageFilter

    path = OUT / f"_mask{size}.png"
    if path.exists():
        return path
    scale = 4
    big = Image.new("L", (size * scale, size * scale), 0)
    ImageDraw.Draw(big).ellipse([0, 0, size * scale - 1, size * scale - 1], fill=255)
    mask = big.resize((size, size), Image.LANCZOS).filter(ImageFilter.GaussianBlur(1.2))
    rgba = Image.new("RGBA", (size, size), (255, 255, 255, 0))
    rgba.putalpha(mask)
    path.parent.mkdir(parents=True, exist_ok=True)
    rgba.save(path)
    return path


def head_clip(head: Path, out: Path, size: int = SIZE, bias: float = FACE_BIAS) -> Path:
    """Crop the presenter to a square centred on the face, then round it off."""
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0", str(head)],
        capture_output=True, text=True, check=True).stdout.strip().split(",")
    w, h = int(probe[0]), int(probe[1])
    side = min(w, h)
    x = (w - side) // 2
    y = max(0, min(h - side, int(h * bias - side / 2)))

    mask = circle_mask(size)
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(head), "-i", str(mask),
         "-filter_complex",
         f"[0:v]crop={side}:{side}:{x}:{y},scale={size}:{size},format=rgba[c];"
         f"[c][1:v]alphamerge[out]",
         "-map", "[out]", "-c:v", "qtrle", "-an", str(out)],
        check=True)
    return out


def compose(base: Path, head: Path, out: Path, size: int = SIZE, margin: int = MARGIN,
            corner: str = "br", show: list[tuple[float, float]] | None = None,
            bias: float = FACE_BIAS) -> Path:
    """Overlay `head` on `base`. `show` is a list of (start, end) to appear in."""
    rounded = out.with_suffix(".head.mov")
    head_clip(head, rounded, size, bias)

    x = margin if corner in ("bl", "tl") else WIDTH - size - margin
    y = margin if corner in ("tl", "tr") else HEIGHT - size - margin

    enable = ""
    if show:
        clauses = "+".join(f"between(t,{a:.2f},{b:.2f})" for a, b in show)
        enable = f":enable='{clauses}'"

    # A ring drawn under the inset separates it from whatever is behind it.
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
    ap.add_argument("--windows", default=None,
                    help="JSON list of [start,end] pairs the head appears in")
    args = ap.parse_args()

    show = json.loads(Path(args.windows).read_text(encoding="utf-8")) if args.windows else None
    compose(Path(args.base), Path(args.head), Path(args.out), args.size,
            args.margin, args.corner, show, args.bias)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
