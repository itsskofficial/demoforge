"""Vertical layouts for a reel. Different medium, different rules.

`slidekit` draws for a 16:9 frame somebody watches deliberately, on a laptop,
with the sound on. This draws for a 1080x1920 frame that arrives unannounced
between two other videos, is watched at arm's length, and gets about one second
to earn the next one.

What changes, concretely:

**Type is roughly twice the size** relative to the frame. A headline that reads
comfortably on a 16:9 slide is unreadable at phone size in a feed.

**Nothing is subtle.** The 16:9 deck fades elements up over 340ms. Here they
snap in over 140ms with a slight overshoot, because a fade reads as a video
that has not started yet and the thumb is already moving.

**Three safe zones, not one.** The platform draws its own interface over the
frame: the account row across the top, the caption and audio strip across the
bottom, and the like/comment/share column down the right. Anything important
inside those is anything important the viewer never sees.

**One accent, and it is loud.** Electric lime on near-black survives a dim
phone screen in daylight, which is where this is actually watched.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from demoforge import motion
from demoforge.config import ROOT
from demoforge.motion import Scene

FONTS = ROOT / "assets/fonts"

BG = (8, 9, 12)
FG = (255, 255, 255)
MUTED = (138, 147, 163)
PANEL = (22, 25, 32)
ACCENT = (200, 255, 46)      # electric lime
WARN = (255, 92, 92)
DIM = (58, 64, 76)

# Fractions of the 1920-tall frame that the platform covers with its own UI.
SAFE_TOP = 0.085
# Deep enough for the platform's own strip *and* the burned captions that sit
# above it. Reserving only the platform's share leaves the last bullet of a
# card sitting underneath the caption -- which looks correct in every still of
# the card on its own, and only shows up once the two are composited.
SAFE_BOTTOM = 0.285
SAFE_RIGHT = 0.115

EMPHASIS = re.compile(r"\*(.+?)\*")

_CACHE: dict[tuple[str, int, str], ImageFont.FreeTypeFont] = {}


def font(name: str, size: int, weight: str = "") -> ImageFont.FreeTypeFont:
    """A named weight of a variable font, cached.

    The Google static instances have been withdrawn in favour of variable
    files, so the weight is selected at load time rather than by filename.
    """
    key = (name, size, weight)
    if key in _CACHE:
        return _CACHE[key]
    loaded = ImageFont.truetype(str(FONTS / name), size)
    if weight:
        try:
            loaded.set_variation_by_name(weight)
        except (OSError, ValueError):
            pass
    _CACHE[key] = loaded
    return loaded


def black(size: int):
    return font("Montserrat.ttf", size, "Black")


def bold(size: int):
    return font("Montserrat.ttf", size, "ExtraBold")


def semi(size: int):
    return font("Montserrat.ttf", size, "SemiBold")


def hand(size: int):
    """The headline face for anything that should not look designed."""
    return font("Kalam-Bold.ttf", size)


def script(size: int):
    """Looser and more cursive, for asides."""
    return font("Caveat.ttf", size, "Bold")


def mono(size: int, weight: str = "Bold"):
    return font("JetBrainsMono.ttf", size, weight)


# ---------------------------------------------------------------------------
# timing
# ---------------------------------------------------------------------------


def pop(t: float, start: float, dur: float = 0.14) -> float:
    """0 to 1 with a small overshoot. The reel equivalent of a fade.

    Overshoot rather than ease-out because at this speed a linear arrival
    reads as a jump and an eased one reads as slow. The bounce is what makes
    140ms feel deliberate instead of glitchy.
    """
    if t < start:
        return 0.0
    x = min(1.0, (t - start) / dur)
    return 1 + 2.2 * (x - 1) ** 3 + 1.2 * (x - 1) ** 2


def alpha(t: float, start: float, dur: float = 0.12) -> float:
    if dur <= 0:
        return 1.0 if t >= start else 0.0
    return max(0.0, min(1.0, (t - start) / dur))


def blend(colour, amount: float, onto=BG):
    amount = max(0.0, min(1.0, amount))
    return tuple(int(o + (c - o) * amount) for c, o in zip(colour, onto))


def beats(count: int, seconds: float, first: float = 0.25,
          span: float = 0.62) -> list[float]:
    if count <= 0:
        return []
    if count == 1:
        return [first]
    room = max(0.5, seconds * span - first)
    return [first + i * min(0.75, room / (count - 1)) for i in range(count)]


# ---------------------------------------------------------------------------
# text
# ---------------------------------------------------------------------------


def strip(text: str) -> str:
    return EMPHASIS.sub(r"\1", text)


def pieces(text: str) -> list[tuple[str, bool, bool]]:
    out: list[tuple[str, bool, bool]] = []
    space = False
    cursor = 0
    chunks: list[tuple[str, bool]] = []
    for match in EMPHASIS.finditer(text):
        if match.start() > cursor:
            chunks.append((text[cursor:match.start()], False))
        chunks.append((match.group(1), True))
        cursor = match.end()
    if cursor < len(text):
        chunks.append((text[cursor:], False))
    for chunk, hot in chunks or [(text, False)]:
        for part in re.split(r"(\s+)", chunk):
            if not part:
                continue
            if part.isspace():
                space = True
                continue
            out.append((part, hot, space and bool(out)))
            space = False
    return out


def wrap(text: str, fnt, width: int) -> list[list[tuple[str, bool]]]:
    lines: list[list[tuple[str, bool, bool]]] = []
    line: list[tuple[str, bool, bool]] = []
    for word, hot, sp in pieces(text):
        trial = "".join((" " if s else "") + w for w, _, s in line + [(word, hot, sp)])
        if fnt.getlength(trial) <= width or not line:
            line.append((word, hot, sp))
        else:
            lines.append(line)
            line = [(word, hot, False)]
    if line:
        lines.append(line)
    return [_merge(l) for l in lines]


def _merge(line):
    out: list[list[Any]] = []
    for word, hot, sp in line:
        piece = (" " if sp and out else "") + word
        if out and out[-1][1] == hot:
            out[-1][0] += piece
        else:
            out.append([piece, hot])
    return [(a, b) for a, b in out]


def fit(text: str, width: int, lines: int, ceiling: int, floor: int,
        weight=black):
    size = ceiling
    plain = strip(text)
    while size > floor:
        fnt = weight(size)
        if len(wrap(plain, fnt, width)) <= lines:
            return fnt, wrap(text, fnt, width)
        size -= 4
    fnt = weight(floor)
    return fnt, wrap(text, fnt, width)[:lines]


def draw_line(d, xy, chunks, fnt, base, accent, a, centre=False, width=0):
    x, y = xy
    if centre:
        total = sum(fnt.getlength(c) for c, _ in chunks)
        x = x + (width - total) / 2
    for chunk, hot in chunks:
        d.text((x, y), chunk, font=fnt, fill=blend(accent if hot else base, a))
        x += fnt.getlength(chunk)


# ---------------------------------------------------------------------------
# spec
# ---------------------------------------------------------------------------


@dataclass
class Item:
    label: str = ""
    value: str = ""
    note: str = ""


@dataclass
class Spec:
    layout: str = "punch"
    index: str = ""
    kicker: str = ""
    headline: str = ""
    sub: str = ""
    items: list[Item] = field(default_factory=list)
    accent: str = "lime"

    @classmethod
    def parse(cls, raw: dict[str, Any]) -> "Spec":
        items = [Item(**{k: str(v) for k, v in i.items()
                         if k in ("label", "value", "note")})
                 if isinstance(i, dict) else Item(label=str(i))
                 for i in raw.get("items", [])]
        return cls(layout=raw.get("layout", "punch"),
                   index=str(raw.get("index", "")),
                   kicker=str(raw.get("kicker", "")),
                   headline=str(raw.get("headline", "")),
                   sub=str(raw.get("sub", "")),
                   items=items, accent=raw.get("accent", "lime"))

    @property
    def colour(self):
        return {"lime": ACCENT, "red": WARN, "white": FG}.get(self.accent, ACCENT)


# ---------------------------------------------------------------------------
# backdrop
# ---------------------------------------------------------------------------


_GROUND: dict[tuple[int, int, str], Image.Image] = {}


def ground(size: tuple[int, int], accent: str) -> Image.Image:
    key = (size[0], size[1], accent)
    if key in _GROUND:
        return _GROUND[key]
    width, height = size
    colour = {"lime": ACCENT, "red": WARN, "white": FG}.get(accent, ACCENT)
    img = Image.new("RGB", size, BG)

    bloom = Image.new("RGB", (width // 4, height // 4), (0, 0, 0))
    d = ImageDraw.Draw(bloom)
    d.ellipse([-width // 12, height // 20, width // 4, height // 6],
              fill=tuple(int(c * 0.16) for c in colour))
    d.ellipse([width // 6, height // 5, width // 4, height // 4],
              fill=tuple(int(c * 0.05) for c in colour))
    bloom = bloom.filter(ImageFilter.GaussianBlur(24)).resize(size, Image.BILINEAR)

    import numpy as np
    a = np.asarray(img, dtype=np.uint16)
    b = np.asarray(bloom, dtype=np.uint16)
    img = Image.fromarray((255 - ((255 - a) * (255 - b) // 255)).astype("uint8"))
    _GROUND[key] = img
    return img


def box(size: tuple[int, int]) -> tuple[int, int, int, int]:
    """The rectangle the platform does not cover."""
    width, height = size
    margin = int(width * 0.075)
    return (margin,
            int(height * SAFE_TOP) + margin,
            width - margin - int(width * SAFE_RIGHT * 0.35),
            int(height * (1 - SAFE_BOTTOM)))


# ---------------------------------------------------------------------------
# layouts
# ---------------------------------------------------------------------------


def _index_badge(d, spec, size, t, left, top):
    """The big step number. The one element that makes a series feel like one."""
    if not spec.index:
        return top
    unit = size[1] / 1920
    a = pop(t, 0.0, 0.18)
    if a <= 0.01:
        return top
    fnt = black(int(150 * unit))
    text = spec.index
    d.text((left, top), text, font=fnt, fill=blend(spec.colour, min(1.0, a)))
    rule = fnt.getlength(text)
    d.rectangle([left, top + int(170 * unit), left + rule * a, top + int(184 * unit)],
                fill=blend(spec.colour, 0.9))
    return top + int(230 * unit)


def layout_step(d, img, spec, size, t, seconds):
    left, top, right, bottom = box(size)
    unit = size[1] / 1920
    y = _index_badge(d, spec, size, t, left, top)

    if spec.kicker:
        a = alpha(t, 0.1)
        d.text((left, y), spec.kicker.upper(), font=bold(int(42 * unit)),
               fill=blend(MUTED, a))
        y += int(70 * unit)

    fnt, lines = fit(spec.headline, right - left, 4, int(128 * unit),
                     int(64 * unit))
    step = int(fnt.size * 1.1)
    for i, line in enumerate(lines):
        a = pop(t, 0.22 + i * 0.09, 0.16)
        if a > 0.01:
            draw_line(d, (left, y + i * step), line, fnt, FG, spec.colour,
                      min(1.0, a))
    y += len(lines) * step + int(40 * unit)

    items = spec.items[:4]
    if not items:
        return
    when = beats(len(items), seconds, first=0.55, span=0.5)
    gap = int(22 * unit)

    # Measured before anything is drawn, and shrunk to fit. The alternative is
    # a card whose last bullet is behind the platform's caption bar, which is
    # invisible in a render preview and obvious in the feed.
    room = bottom - y - gap * (len(items) - 1)
    ceiling = int(62 * unit)
    while ceiling > int(30 * unit):
        laid = []
        for item in items:
            ifnt, ilines = fit(item.label, right - left - int(90 * unit), 2,
                               ceiling, int(30 * unit), weight=bold)
            laid.append((ifnt, ilines,
                         len(ilines) * int(ifnt.size * 1.16) + int(46 * unit)))
        if sum(h for _, _, h in laid) <= room:
            break
        ceiling -= 4

    for i, (ifnt, ilines, block) in enumerate(laid):
        a = pop(t, when[i], 0.16)
        if a <= 0.01:
            y += block + gap
            continue
        shift = int(60 * unit * (1 - min(1.0, a)))
        d.rounded_rectangle([left - shift, y, right - shift, y + block],
                            radius=int(26 * unit), fill=blend(PANEL, min(1.0, a)))
        d.rectangle([left - shift, y, left + int(9 * unit) - shift, y + block],
                    fill=blend(spec.colour, min(1.0, a)))
        for j, line in enumerate(ilines):
            draw_line(d, (left + int(46 * unit) - shift,
                          y + int(22 * unit) + j * int(ifnt.size * 1.16)),
                      line, ifnt, FG, spec.colour, min(1.0, a))
        y += block + gap


def layout_punch(d, img, spec, size, t, seconds):
    """One statement, as large as it will go, centred. The whole layout."""
    left, top, right, bottom = box(size)
    unit = size[1] / 1920
    fnt, lines = fit(spec.headline, right - left, 5, int(160 * unit),
                     int(76 * unit))
    step = int(fnt.size * 1.08)
    y = int((top + bottom) / 2 - len(lines) * step / 2)
    for i, line in enumerate(lines):
        a = pop(t, 0.12 + i * 0.1, 0.16)
        if a > 0.01:
            lift = int(50 * unit * (1 - min(1.0, a)))
            draw_line(d, (left, y + i * step + lift), line, fnt, FG,
                      spec.colour, min(1.0, a))
    if spec.sub:
        a = alpha(t, 0.12 + len(lines) * 0.1 + 0.2, 0.2)
        sfnt = semi(int(52 * unit))
        for j, line in enumerate(wrap(strip(spec.sub), sfnt, right - left)[:2]):
            draw_line(d, (left, y + len(lines) * step + int(36 * unit)
                          + j * int(64 * unit)), line, sfnt, MUTED, spec.colour, a)


def layout_code(d, img, spec, size, t, seconds):
    """A file, typed on. Reads as a real artefact rather than a bullet list."""
    left, top, right, bottom = box(size)
    unit = size[1] / 1920
    y = top

    if spec.headline:
        fnt, lines = fit(spec.headline, right - left, 2, int(104 * unit),
                         int(60 * unit))
        for i, line in enumerate(lines):
            a = pop(t, 0.1 + i * 0.08, 0.16)
            if a > 0.01:
                draw_line(d, (left, y + i * int(fnt.size * 1.1)), line, fnt, FG,
                          spec.colour, min(1.0, a))
        y += len(lines) * int(fnt.size * 1.1) + int(46 * unit)

    a = pop(t, 0.3, 0.2)
    if a <= 0.01:
        return
    lines = [i.label for i in spec.items][:9]
    mfnt = mono(int(42 * unit))
    pad = int(38 * unit)
    line_h = int(58 * unit)
    height = pad * 2 + line_h * max(1, len(lines)) + int(52 * unit)
    y += max(0, (bottom - y - height) // 2)
    d.rounded_rectangle([left, y, right, y + height], radius=int(24 * unit),
                        fill=blend((16, 18, 24), min(1.0, a)))
    # A title bar with the filename, which is what tells the viewer this is a
    # file and not a quote card.
    d.rounded_rectangle([left, y, right, y + int(52 * unit)],
                        radius=int(24 * unit), fill=blend((30, 34, 43), min(1.0, a)))
    d.rectangle([left, y + int(30 * unit), right, y + int(52 * unit)],
                fill=blend((30, 34, 43), min(1.0, a)))
    for k in range(3):
        d.ellipse([left + pad + k * int(34 * unit), y + int(18 * unit),
                   left + pad + k * int(34 * unit) + int(18 * unit),
                   y + int(36 * unit)],
                  fill=blend((70, 78, 92), min(1.0, a)))
    if spec.kicker:
        d.text((left + pad + int(130 * unit), y + int(14 * unit)),
               spec.kicker, font=mono(int(30 * unit), "Regular"),
               fill=blend(MUTED, min(1.0, a)))

    # Typed on line by line, not revealed as a block: a file appearing whole
    # is a screenshot, and a file being written is somebody working.
    when = beats(len(lines), seconds, first=0.42, span=0.55)
    for i, line in enumerate(lines):
        reveal = alpha(t, when[i], 0.18)
        if reveal <= 0.01:
            continue
        shown = line[:max(1, int(len(line) * reveal))]
        hot = line.startswith("#") or line.startswith("##")
        d.text((left + pad, y + int(76 * unit) + i * line_h), shown, font=mfnt,
               fill=blend(spec.colour if hot else (206, 214, 226), 1.0))


def layout_chain(d, img, spec, size, t, seconds):
    """A sequence, stacked downwards, with the arrows drawn between."""
    left, top, right, bottom = box(size)
    unit = size[1] / 1920
    y = _index_badge(d, spec, size, t, left, top)

    if spec.headline:
        fnt, lines = fit(spec.headline, right - left, 2, int(108 * unit),
                         int(60 * unit))
        for i, line in enumerate(lines):
            a = pop(t, 0.12 + i * 0.08, 0.16)
            if a > 0.01:
                draw_line(d, (left, y + i * int(fnt.size * 1.1)), line, fnt, FG,
                          spec.colour, min(1.0, a))
        y += len(lines) * int(fnt.size * 1.1) + int(50 * unit)

    items = spec.items[:5]
    when = beats(len(items), seconds, first=0.5, span=0.55)
    gap = int(56 * unit)
    room = bottom - y
    block = min(int((room - gap * (len(items) - 1)) / max(1, len(items))),
                int(150 * unit))
    for i, item in enumerate(items):
        a = pop(t, when[i], 0.16)
        if a > 0.01:
            slide = int(70 * unit * (1 - min(1.0, a)))
            d.rounded_rectangle([left + slide, y, right + slide, y + block],
                                radius=int(24 * unit),
                                fill=blend(PANEL, min(1.0, a)))
            ifnt, ilines = fit(item.label, right - left - int(70 * unit), 2,
                               int(58 * unit), int(34 * unit), weight=bold)
            ty = y + block / 2 - (len(ilines) - 1) * ifnt.size * 0.58
            for j, line in enumerate(ilines):
                draw_line(d, (left + int(40 * unit) + slide,
                              ty + j * int(ifnt.size * 1.16) - ifnt.size * 0.5),
                          line, ifnt, FG, spec.colour, min(1.0, a))
        if i < len(items) - 1:
            b = alpha(t, when[i + 1] - 0.08, 0.14)
            if b > 0.01:
                cx = left + int(52 * unit)
                cy = y + block + gap / 2
                arm = int(16 * unit)
                d.line([(cx, cy - arm), (cx, cy + arm)],
                       fill=blend(spec.colour, b), width=max(3, int(6 * unit)))
                d.polygon([(cx, cy + arm + int(10 * unit)),
                           (cx - arm * 0.7, cy + arm - int(2 * unit)),
                           (cx + arm * 0.7, cy + arm - int(2 * unit))],
                          fill=blend(spec.colour, b))
        y += block + gap


def layout_versus(d, img, spec, size, t, seconds):
    """Two claims, one crossed out. The shape of every 'do this not that'."""
    left, top, right, bottom = box(size)
    unit = size[1] / 1920
    items = (spec.items + [Item(label=""), Item(label="")])[:2]
    mid = (top + bottom) / 2
    height = int(340 * unit)

    for i, item in enumerate(items):
        a = pop(t, 0.15 + i * 0.28, 0.18)
        if a <= 0.01:
            continue
        y = int(mid - height - int(40 * unit)) if i == 0 else int(mid + int(40 * unit))
        wrong = i == 0
        colour = WARN if wrong else spec.colour
        d.rounded_rectangle([left, y, right, y + height], radius=int(30 * unit),
                            fill=blend(PANEL, min(1.0, a)))
        d.rectangle([left, y, left + int(10 * unit), y + height],
                    fill=blend(colour, min(1.0, a)))
        tag = "VIBE CODING" if wrong else "ENGINEERING"
        d.text((left + int(48 * unit), y + int(34 * unit)),
               item.note.upper() or tag, font=bold(int(38 * unit)),
               fill=blend(colour, min(1.0, a)))
        ifnt, ilines = fit(item.label, right - left - int(96 * unit), 2,
                           int(96 * unit), int(56 * unit))
        for j, line in enumerate(ilines):
            draw_line(d, (left + int(48 * unit),
                          y + int(110 * unit) + j * int(ifnt.size * 1.12)),
                      line, ifnt, FG, colour, min(1.0, a))
        if wrong:
            b = alpha(t, 0.15 + 0.5, 0.18)
            if b > 0.01:
                # Struck through the middle of the text block it crosses, and
                # only as wide as the longest line. A rule at a fixed height
                # lands on whichever line happens to be there.
                # One rule per line, each only as wide as its own text. A
                # single rule across a two-line claim crosses out the first
                # line and underlines the second.
                x0 = left + int(48 * unit)
                for j, line in enumerate(ilines):
                    run = sum(ifnt.getlength(c) for c, _ in line)
                    sy = (y + int(110 * unit) + j * int(ifnt.size * 1.12)
                          + ifnt.size * 0.42)
                    d.line([(x0, sy), (x0 + run * b, sy)],
                           fill=blend(WARN, 1.0), width=max(4, int(9 * unit)))


def layout_stat(d, img, spec, size, t, seconds):
    left, top, right, bottom = box(size)
    unit = size[1] / 1920
    a = pop(t, 0.1, 0.2)
    value = spec.items[0].value if spec.items else spec.headline
    fnt, _ = fit(value, right - left, 1, int(360 * unit), int(140 * unit))
    mid = (top + bottom) / 2
    if a > 0.01:
        d.text(((left + right) / 2, mid - int(60 * unit)), value, font=fnt,
               fill=blend(spec.colour, min(1.0, a)), anchor="mm")
    if spec.headline and spec.items:
        b = alpha(t, 0.35, 0.2)
        hfnt, lines = fit(spec.headline, right - left, 3, int(84 * unit),
                          int(48 * unit), weight=bold)
        for i, line in enumerate(lines):
            draw_line(d, (left, mid + int(80 * unit) + i * int(hfnt.size * 1.14)),
                      line, hfnt, FG, spec.colour, b, centre=True,
                      width=right - left)


RENDERERS = {
    "step": layout_step,
    "punch": layout_punch,
    "code": layout_code,
    "chain": layout_chain,
    "versus": layout_versus,
    "stat": layout_stat,
}
LAYOUTS = tuple(RENDERERS)


# ---------------------------------------------------------------------------
# render
# ---------------------------------------------------------------------------


def scene(spec: Spec, seconds: float, size: tuple[int, int],
          name: str = "card") -> Scene:
    base = ground(size, spec.accent)
    render = RENDERERS.get(spec.layout, layout_punch)

    def draw(d, img, t):
        img.paste(base)
        d = ImageDraw.Draw(img)
        render(d, img, spec, size, t, seconds)
        return img

    return Scene(name=name, seconds=seconds, draw=draw)


def render(spec: dict[str, Any] | Spec, seconds: float, out: Path,
           size: tuple[int, int] = (1080, 1920)) -> Path:
    parsed = spec if isinstance(spec, Spec) else Spec.parse(spec)
    return motion.render(scene(parsed, seconds, size, out.stem), out=out, size=size)
