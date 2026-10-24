"""Short mode: a list of points and a background clip, with nothing filmed.

The fifth path, and the only one where the presenter never appears.

`reel` derives everything from a recording — cuts land on word boundaries,
captions come from the transcript, shots are chosen by where the eyes are. That
is the right machine when somebody has spoken for seven minutes and the film is
hiding in there somewhere.

This is for the other case: you know the five things you want to say, you are
not going to film yourself saying them, and the video needs to exist today.
There is no speech, so there is nothing to derive timing *from* — timing is
authored instead, from how long a card takes to read.

The background is deliberately unrelated to the content. It is ambient
footage — hands on a keyboard, a server aisle — running underneath at reduced
contrast, and its only job is to stop the frame being a static graphic. Swap it
for any other clip and the video still works. That is the whole trick of the
format, and the reason it costs an afternoon instead of a weekend:

    the background carries the motion
    the overlay carries the meaning
    neither one has to know about the other

Which also means the overlay is rendered once, with alpha, and composited. No
part of this pipeline needs the background to exist until the last step.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFilter

from demoforge import reelkit as rk
from demoforge.config import OUT, PROJECTS, ROOT
from demoforge.edit import duration, loudness

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

SIZE = (1080, 1920)
FPS = 30


@dataclass
class Card:
    kind: str = "point"          # title | point | cta
    index: str = ""
    kicker: str = ""
    headline: str = ""
    note: str = ""
    tile_header: str = ""
    tile_stat: str = ""
    tile_caption: str = ""
    tile_tone: str = "bad"
    icon: str = ""
    seconds: float = 2.4


@dataclass
class Profile:
    name: str
    directory: Path
    title: str = ""
    background: str = ""
    accent: str = "lime"
    cards: list[Card] = field(default_factory=list)
    music: bool = True
    music_dir: str = ""
    music_file: str = ""
    music_offset: float = 0.0
    music_target: float = -14.0
    scrim: float = 0.62
    trim_bottom: float = 0.0
    face: str = "hand"
    push: float = 1.10
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def home(self) -> Path:
        return OUT / self.name

    @property
    def work(self) -> Path:
        return self.home / "work"

    @property
    def clip(self) -> Path:
        path = Path(self.background).expanduser()
        return path if path.is_absolute() else (self.directory / path)

    @property
    def seconds(self) -> float:
        return sum(c.seconds for c in self.cards)


def load(project: str) -> Profile:
    directory = PROJECTS / project
    path = directory / "short.json"
    if not path.exists():
        raise SystemExit(f"no short profile at {path}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    cards = [Card(**c) for c in raw.get("cards", [])]
    known = {f for f in Profile.__dataclass_fields__
             if f not in ("name", "directory", "raw", "cards")}
    return Profile(name=project, directory=directory, raw=raw, cards=cards,
                   **{k: v for k, v in raw.items() if k in known})


# ---------------------------------------------------------------------------
# the overlay
# ---------------------------------------------------------------------------


YELLOW = (244, 236, 74)
STRIKE = (232, 62, 58)

# Named type pairings. The look of this format lives almost entirely in the
# face, so it is a switch rather than a code change -- one line in the profile
# re-renders the whole film in a different voice.
FACES = {
    "hand":      ("Kalam-Bold.ttf", "",            "Caveat.ttf", "Bold",  1.00, 1.00),
    "marker":    ("PermanentMarker.ttf", "",       "Caveat.ttf", "Bold",  0.92, 1.00),
    "editorial": ("PlayfairDisplay-Italic.ttf", "Black Italic",
                                                   "PlayfairDisplay-Italic.ttf",
                                                                 "Italic", 1.02, 0.92),
    "bold":      ("ArchivoBlack-Regular.ttf", "",  "Inter.ttf",  "SemiBold", 0.88, 0.80),
    "casual":    ("ArchitectsDaughter.ttf", "",    "PatrickHand.ttf", "", 0.92, 0.94),
}


def faces(name: str):
    """(headline, subheadline) font factories for a named variant."""
    head_file, head_w, sub_file, sub_w, head_k, sub_k = FACES.get(
        name, FACES["hand"])

    def headline(size: int):
        return rk.font(head_file, max(12, int(size * head_k)), head_w)

    def sub(size: int):
        return rk.font(sub_file, max(10, int(size * sub_k)), sub_w)

    return headline, sub


_CODEPOINTS: dict[str, str] = {}


def codepoint(name: str) -> str:
    """Look an icon name up in the font's own codepoint table.

    Shipping a 4,000-icon font and hard-coding three glyph values would mean
    every new card needs a hex lookup by hand. The table ships beside the
    font; read it.
    """
    if not _CODEPOINTS:
        table = rk.FONTS / "MaterialSymbols.codepoints"
        for line in table.read_text(encoding="utf-8").splitlines():
            if " " in line:
                key, value = line.split(" ", 1)
                _CODEPOINTS[key] = value.strip()
    return chr(int(_CODEPOINTS[name], 16)) if name in _CODEPOINTS else ""


def icon_font(size: int):
    fnt = rk.font("MaterialSymbols.ttf", size)
    try:
        fnt.set_variation_by_axes([0.0, 0.0, 48.0, 600.0])   # FILL GRAD opsz wght
    except Exception:
        pass
    return fnt


def outlined(img, xy, text, fnt, fill, weight=6, angle=0.0, anchor=None):
    """Type with its own contrast, so the footage underneath stays ungraded."""
    x, y = xy
    pad = int(fnt.size * 0.55) + weight * 2
    w = int(fnt.getlength(text)) + pad * 2
    h = int(fnt.size * 2.2) + pad
    tile = Image.new("RGBA", (max(w, 1), max(h, 1)), (0, 0, 0, 0))
    d = ImageDraw.Draw(tile)
    d.text((pad, pad), text, font=fnt, fill=(12, 12, 14, 240),
           stroke_width=weight, stroke_fill=(12, 12, 14, 240))
    d.text((pad, pad), text, font=fnt, fill=fill)
    if angle:
        tile = tile.rotate(angle, resample=Image.BICUBIC, expand=True)
    img.alpha_composite(tile, (int(x - pad), int(y - pad)))


def lean(i: int, spread: float = 1.4) -> float:
    return ((i * 37) % 100 / 100 - 0.5) * 2 * spread


def centred(img, text, fnt, y, size, fill, weight=6, angle=0.0):
    run = fnt.getlength(text)
    outlined(img, ((size[0] - run) / 2, y), text, fnt, fill, weight, angle)


def _fit_hand(text, start, width, most, floor, head=None):
    head = head or rk.hand
    fnt = head(int(start))
    lines = rk.wrap(text, fnt, width)
    while len(lines) > most and fnt.size > floor:
        fnt = head(int(fnt.size - 5))
        lines = rk.wrap(text, fnt, width)
    return fnt, lines


def draw_icon(img, name, size, t, cy, start=0.28, tone="bad"):
    """One big glyph, struck through when the point is about an absence."""
    unit = size[1] / 1920
    glyph = codepoint(name)
    if not glyph:
        return
    a = rk.pop(t, start, 0.2)
    if a <= 0.01:
        return
    fnt = icon_font(int(300 * unit))
    run = fnt.getlength(glyph)
    x = (size[0] - run) / 2
    outlined(img, (x, cy), glyph, fnt,
             (255, 255, 255, int(255 * min(1.0, a))), weight=7)
    if tone == "bad":
        b = rk.alpha(t, start + 0.22, 0.18)
        if b > 0.01:
            layer = Image.new("RGBA", size, (0, 0, 0, 0))
            d = ImageDraw.Draw(layer)
            x0, y0 = x - int(20 * unit), cy + int(300 * unit)
            x1, y1 = x + run + int(20 * unit), cy + int(30 * unit)
            d.line([(x0, y0), (x0 + (x1 - x0) * b, y0 + (y1 - y0) * b)],
                   fill=(12, 12, 14, 235), width=int(28 * unit))
            d.line([(x0, y0), (x0 + (x1 - x0) * b, y0 + (y1 - y0) * b)],
                   fill=(*STRIKE, 245), width=int(16 * unit))
            img.alpha_composite(layer)


def draw_title(img, card, spec, size, t, face="hand"):
    head, sub = faces(face)
    unit = size[1] / 1920
    width = int(size[0] * 0.86)
    fnt, lines = _fit_hand(card.headline, 128 * unit, width, 3, 74 * unit, head)
    step = int(fnt.size * 1.12)
    y = int(size[1] * 0.30)
    for i, line in enumerate(lines):
        a = rk.pop(t, 0.05 + i * 0.09, 0.18)
        if a <= 0.01:
            continue
        text = "".join(c for c, _ in line)
        centred(img, text, fnt, y + i * step + int(30 * (1 - min(1.0, a))),
                size, (*YELLOW, int(255 * min(1.0, a))), angle=lean(i))
    y += len(lines) * step
    if card.note:
        a = rk.pop(t, min(0.42, 0.42 * card.seconds / 3.2), 0.2)
        if a > 0.01:
            nfnt = sub(int(78 * unit))
            for j, line in enumerate(rk.wrap(rk.strip(card.note), nfnt,
                                             width)[:2]):
                text = "".join(c for c, _ in line)
                centred(img, text, nfnt, y + int(34 * unit) + j * int(74 * unit),
                        size, (250, 250, 250, int(250 * min(1.0, a))),
                        weight=5, angle=lean(j + 2, 1.0))


def draw_point(img, card, spec, size, t, position, total,
               face="hand"):
    head, sub = faces(face)
    unit = size[1] / 1920
    width = int(size[0] * 0.86)
    heading = f"{position}. {rk.strip(card.headline)}"
    fnt, lines = _fit_hand(heading, 112 * unit, width, 2, 70 * unit, head)
    step = int(fnt.size * 1.12)

    y = int(size[1] * 0.20)
    for i, line in enumerate(lines):
        a = rk.pop(t, 0.04 + i * 0.09, 0.16)
        if a <= 0.01:
            continue
        text = "".join(c for c, _ in line)
        centred(img, text, fnt, y + i * step, size,
                (*YELLOW, int(255 * min(1.0, a))), angle=lean(i))
    y += len(lines) * step

    quick = card.seconds / 2.9        # 2.9s was the pace these were tuned at
    draw_icon(img, card.icon, size, t, y + int(60 * unit),
              start=min(0.26, 0.26 * quick), tone=card.tile_tone)

    if card.note:
        a = rk.pop(t, min(0.6, 0.6 * quick), 0.2)
        if a > 0.01:
            nfnt = sub(int(74 * unit))
            base = y + int(470 * unit)
            for j, line in enumerate(rk.wrap(rk.strip(card.note), nfnt,
                                             width)[:2]):
                text = "".join(c for c, _ in line)
                centred(img, text, nfnt, base + j * int(70 * unit), size,
                        (250, 250, 250, int(250 * min(1.0, a))), weight=5,
                        angle=lean(j + 4, 1.0))


def draw_cta(img, card, spec, size, t, face="hand"):
    head, sub = faces(face)
    unit = size[1] / 1920
    width = int(size[0] * 0.86)
    fnt, lines = _fit_hand(card.headline, 124 * unit, width, 3, 74 * unit, head)
    step = int(fnt.size * 1.12)
    y = int(size[1] * 0.33)
    for i, line in enumerate(lines):
        a = rk.pop(t, 0.06 + i * 0.09, 0.18)
        if a <= 0.01:
            continue
        text = "".join(c for c, _ in line)
        centred(img, text, fnt, y + i * step, size,
                (*YELLOW, int(255 * min(1.0, a))), angle=lean(i))
    y += len(lines) * step
    if card.note:
        a = rk.pop(t, min(0.45, 0.45 * card.seconds / 2.9), 0.2)
        if a > 0.01:
            nfnt = sub(int(80 * unit))
            centred(img, rk.strip(card.note), nfnt, y + int(36 * unit), size,
                    (250, 250, 250, int(250 * min(1.0, a))), weight=5,
                    angle=-1.0)


def overlay(profile: Profile, out: Path) -> Path:
    """The whole graphic track, once, with alpha.

    Rendered independently of the background and composited at the end. It
    means the expensive half (drawing) never has to be redone when the cheap
    half (which clip is underneath) changes.
    """
    size = SIZE
    spec = rk.Spec(accent=profile.accent)
    points = [c for c in profile.cards if c.kind == "point"]
    out.parent.mkdir(parents=True, exist_ok=True)

    proc = subprocess.Popen(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo",
         "-pix_fmt", "rgba", "-s", f"{size[0]}x{size[1]}", "-r", str(FPS),
         "-i", "-", "-c:v", "qtrle", str(out)],
        stdin=subprocess.PIPE)
    try:
        seen = 0
        for card in profile.cards:
            if card.kind == "point":
                seen += 1
            for frame in range(int(card.seconds * FPS)):
                t = frame / FPS
                img = Image.new("RGBA", size, (0, 0, 0, 0))
                if card.kind == "title":
                    draw_title(img, card, spec, size, t, profile.face)
                elif card.kind == "cta":
                    draw_cta(img, card, spec, size, t, profile.face)
                else:
                    draw_point(img, card, spec, size, t, seen, len(points),
                               profile.face)
                proc.stdin.write(img.tobytes())
    finally:
        proc.stdin.close()
        proc.wait()
    print(f"  overlay  {duration(out):.1f}s  {len(profile.cards)} cards")
    return out


# ---------------------------------------------------------------------------
# the background
# ---------------------------------------------------------------------------


def scrim(size: tuple[int, int], strength: float, out: Path) -> Path:
    """A darkening wash, heaviest where the type goes.

    Not a flat overlay. Ambient footage is busiest in the middle and the type
    sits top and bottom, so a uniform scrim either leaves the headline fighting
    a highlight or drains the one part of the picture that is doing any work.
    """
    if out.exists():
        return out
    width, height = size
    layer = Image.new("L", (width, height), 0)
    d = ImageDraw.Draw(layer)
    for y in range(height):
        # Flat across the middle, heavier at the top and bottom. The first
        # version of this lightened towards the centre, on the theory that the
        # type lives at the edges -- which was exactly wrong for a clip whose
        # brightest object (a lit keyboard) is dead centre and whose type is
        # centred over it.
        edge = max(0.0, 1 - min(y / (height * 0.22),
                                (height - y) / (height * 0.24), 1.0))
        d.line([(0, y), (width, y)],
               fill=int(255 * min(1.0, strength * (1 + 0.28 * edge))))
    layer = layer.filter(ImageFilter.GaussianBlur(28))
    out.parent.mkdir(parents=True, exist_ok=True)
    Image.merge("RGBA", (Image.new("L", (width, height), 6),
                         Image.new("L", (width, height), 7),
                         Image.new("L", (width, height), 10), layer)).save(out)
    return out


def background(profile: Profile, out: Path) -> Path:
    """The ambient clip, cropped, graded and slowly pushed in."""
    width, height = SIZE
    seconds = profile.seconds
    have = duration(profile.clip)
    frames = max(1, int(seconds * FPS))
    loop = ["-stream_loop", "-1"] if have < seconds + 0.5 else []
    push = profile.push
    # The footage is left exactly as shot. An earlier version desaturated it and
    # laid a wash over the top so the type would read; the type carries its own
    # outline now, and the grade was only ever making somebody's real video
    # look like stock. A scrim is available but off unless asked for.
    chain = (f"[0:v]crop=iw:ih*{1 - profile.trim_bottom:.4f}:0:0,"
             f"scale={width}:{height}:force_original_aspect_ratio=increase:"
             f"flags=lanczos,crop={width}:{height},fps={FPS},"
             f"zoompan=z='1+{push - 1:.4f}*on/{frames}':d=1:"
             f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={width}x{height},"
             f"setsar=1")
    inputs = [*loop, "-i", str(profile.clip)]
    if profile.scrim > 0.01:
        inputs += ["-i", str(scrim(SIZE, profile.scrim,
                                   profile.work / "_scrim.png"))]
        chain += "[b];[b][1:v]overlay=0:0[v]"
    else:
        chain += "[v]"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", *inputs,
         "-filter_complex", chain,
         "-map", "[v]", "-an", "-t", f"{seconds:.3f}",
         "-c:v", "libx264", "-preset", "medium", "-crf", "17",
         "-pix_fmt", "yuv420p", str(out)],
        check=True)
    return out


# ---------------------------------------------------------------------------
# build
# ---------------------------------------------------------------------------


def build(profile: Profile, out: Path | None = None,
          steps: list[str] | None = None) -> Path:
    steps = steps or ["overlay", "background", "compose", "music"]
    work = profile.work
    work.mkdir(parents=True, exist_ok=True)
    out = out or profile.home / f"{profile.name}-short.mp4"

    graphic = work / "overlay.mov"
    if "overlay" in steps or not graphic.exists():
        print("\n== overlay ==")
        overlay(profile, graphic)

    plate = work / "background.mp4"
    if "background" in steps or not plate.exists():
        print("\n== background ==")
        background(profile, plate)

    silent = work / "silent.mp4"
    if "compose" in steps or not silent.exists():
        print("\n== compose ==")
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", str(plate),
             "-i", str(graphic), "-filter_complex", "[0:v][1:v]overlay=0:0[v]",
             "-map", "[v]", "-an", "-c:v", "libx264", "-preset", "medium",
             "-crf", "17", "-pix_fmt", "yuv420p", str(silent)],
            check=True)

    print("\n== music ==")
    _score(profile, silent, work, out)
    print(f"\n  {out}  {duration(out):.1f}s")
    return out


def _score(profile: Profile, video: Path, work: Path, out: Path) -> Path:
    """Music only. There is no voice here, so nothing has to duck."""
    track = None
    if profile.music:
        from demoforge.reel import _local
        track = _local(profile, profile.seconds + profile.music_offset + 1)
    if not track:
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", str(video),
             "-c:v", "copy", "-an", "-movflags", "+faststart", str(out)],
            check=True)
        print("  no music; silent cut")
        return out

    level = loudness(track) or -14.0
    gain = profile.music_target - level
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(video),
         "-ss", f"{profile.music_offset:.2f}", "-i", str(track),
         "-filter_complex",
         f"[1:a]volume={gain:.2f}dB,afade=t=in:st=0:d=0.4,"
         f"afade=t=out:st={max(0.0, profile.seconds - 0.8):.2f}:d=0.8,"
         f"loudnorm=I={profile.music_target}:TP=-1.2:LRA=9[a]",
         "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac",
         "-b:a", "192k", "-shortest", "-movflags", "+faststart", str(out)],
        check=True)
    print(f"  bed {gain:+.1f}dB to {profile.music_target:.0f} LUFS")
    return out


def cover(profile: Profile, out: Path | None = None, at: float = 0.6) -> Path:
    """A still for the feed, taken from the title card."""
    out = out or profile.home / f"{profile.name}-cover.jpg"
    source = profile.work / "silent.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{at:.2f}",
         "-i", str(source), "-frames:v", "1", "-q:v", "2", str(out)],
        check=True)
    print(f"  {out}")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="demoforge short", description=__doc__)
    sub = ap.add_subparsers(dest="action", required=True)
    for action in ("build", "cover"):
        p = sub.add_parser(action)
        p.add_argument("--project", required=True)
        p.add_argument("--out", default=None)
        if action == "build":
            p.add_argument("--steps", default=None,
                           help="overlay,background,compose,music")
    args = ap.parse_args(argv)
    profile = load(args.project)
    if args.action == "cover":
        cover(profile, Path(args.out) if args.out else None)
    else:
        build(profile, Path(args.out) if args.out else None,
              args.steps.split(",") if args.steps else None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
