"""Slides drawn from content, not from a template file.

Presenter mode asks each project for a `slides.py` and lets it draw whatever it
likes. That is right when the visuals *are* the argument — probeit's slides
carry numbers that have to be laid out a particular way. It is wrong here,
because the editor mode's whole premise is that you already made the deck and
should not have to write it a second time in Python.

So this is the other half of that trade: a fixed set of eight layouts, each of
which will take any content it is given and lay it out legibly. You lose
per-slide art direction. You gain a deck that renders itself.

Three rules hold across every layout, and they are the reason the output looks
like one film rather than eight:

**Nothing is on screen before it is spoken about.** Every element has a beat,
beats are fractions of the section's length, and the section's length is
whatever the presenter actually took to say it. A slide that arrives fully
drawn has given away its own ending.

**The bottom-right corner belongs to the presenter.** When a section is framed
`corner`, the content column narrows. Discovering the collision after the
composite means re-rendering the slide, and the slide is the expensive part.

**Size is a parameter, never a constant.** The same spec renders 16:9 and 9:16.
Everything is measured against the canvas it was handed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFilter

from demoforge import motion
from demoforge.motion import (BG, FG, MUTED, PANEL, Scene, blend, ease, ease_out,
                              window, wrap)

ACCENTS = {
    "blue": (88, 166, 255),
    "red": (248, 105, 96),
    "green": (72, 207, 115),
    "gold": (240, 190, 90),
    "violet": (167, 139, 250),
    "cyan": (56, 205, 214),
}
DEFAULT_ACCENT = "blue"

LAYOUTS = ("title", "statement", "stats", "steps", "bullets",
           "flow", "equation", "closer")

# `*emphasis*` in any text field. Written this way in the spec because the spec
# is authored by a model, and asking for a parallel list of character offsets
# is asking for off-by-ones nobody can debug from a rendered frame.
EMPHASIS = re.compile(r"\*(.+?)\*")


def strip_emphasis(text: str) -> str:
    return EMPHASIS.sub(r"\1", text)


def split_emphasis(text: str) -> list[tuple[str, bool]]:
    """`"a *b* c"` → `[("a ", False), ("b", True), (" c", False)]`."""
    parts: list[tuple[str, bool]] = []
    cursor = 0
    for match in EMPHASIS.finditer(text):
        if match.start() > cursor:
            parts.append((text[cursor:match.start()], False))
        parts.append((match.group(1), True))
        cursor = match.end()
    if cursor < len(text):
        parts.append((text[cursor:], False))
    return parts or [(text, False)]


# ---------------------------------------------------------------------------
# the spec
# ---------------------------------------------------------------------------


@dataclass
class Item:
    label: str = ""
    value: str = ""
    note: str = ""


@dataclass
class Spec:
    layout: str = "statement"
    kicker: str = ""
    headline: str = ""
    sub: str = ""
    footnote: str = ""
    accent: str = DEFAULT_ACCENT
    items: list[Item] = field(default_factory=list)
    presenter: str = "corner"

    @classmethod
    def parse(cls, raw: dict[str, Any]) -> "Spec":
        items = [Item(**{k: str(v) for k, v in i.items() if k in ("label", "value", "note")})
                 if isinstance(i, dict) else Item(label=str(i))
                 for i in raw.get("items", [])]
        layout = raw.get("layout", "statement")
        return cls(
            layout=layout if layout in LAYOUTS else "statement",
            kicker=str(raw.get("kicker", "")),
            headline=str(raw.get("headline", "")),
            sub=str(raw.get("sub", "")),
            footnote=str(raw.get("footnote", "")),
            accent=raw.get("accent", DEFAULT_ACCENT),
            items=items,
            presenter=raw.get("presenter", "corner"),
        )

    @property
    def colour(self) -> tuple[int, int, int]:
        return ACCENTS.get(self.accent, ACCENTS[DEFAULT_ACCENT])


# ---------------------------------------------------------------------------
# type
# ---------------------------------------------------------------------------


def fit(text: str, width: int, lines: int, ceiling: int, floor: int,
        weight=motion.bold) -> tuple[Any, list[str]]:
    """The largest size at which `text` wraps into at most `lines` lines.

    Stepping down by 4pt rather than binary-searching: the search space is
    ~40 sizes, PIL's metrics are cheap, and a linear walk always returns the
    true maximum where a bisection on a non-monotonic wrap can miss it.
    """
    size = ceiling
    while size > floor:
        fnt = weight(size)
        wrapped = wrap(text, fnt, width)
        if len(wrapped) <= lines:
            return fnt, wrapped
        size -= 4
    fnt = weight(floor)
    return fnt, wrap(text, fnt, width)[:lines]


def rich_text(d, xy, parts: list[tuple[str, bool]], fnt, base, accent, alpha,
              rise=0.0):
    """One line, with the emphasised runs in the accent colour."""
    x, y = xy
    y += rise
    for chunk, hot in parts:
        d.text((x, y), chunk, font=fnt, fill=blend(accent if hot else base, alpha))
        x += fnt.getlength(chunk)


def tokens(text: str) -> list[tuple[str, bool, bool]]:
    """`(word, emphasised, had a space before it)`.

    The space has to be tracked rather than reinserted between every word,
    because `*cheap*.` puts the full stop in a different run from the word it
    belongs to. Rejoining on spaces renders it as "cheap ." — which survives
    every test that checks the text and is the first thing anyone notices in
    the frame.
    """
    out: list[tuple[str, bool, bool]] = []
    space = False
    for chunk, hot in split_emphasis(text):
        for part in re.split(r"(\s+)", chunk):
            if not part:
                continue
            if part.isspace():
                space = True
                continue
            out.append((part, hot, space and bool(out)))
            space = False
    return out


def wrap_rich(text: str, fnt, width: int) -> list[list[tuple[str, bool]]]:
    """Wrap while keeping track of which words were emphasised."""
    lines: list[list[tuple[str, bool, bool]]] = []
    line: list[tuple[str, bool, bool]] = []
    for word, hot, space in tokens(text):
        trial = _flatten(line + [(word, hot, space)])
        if fnt.getlength(trial) <= width or not line:
            line.append((word, hot, space))
        else:
            lines.append(line)
            line = [(word, hot, False)]
    if line:
        lines.append(line)
    return [_join(l) for l in lines]


def _flatten(line: list[tuple[str, bool, bool]]) -> str:
    return "".join((" " if space else "") + word for word, _, space in line)


def _join(line: list[tuple[str, bool, bool]]) -> list[tuple[str, bool]]:
    """Merge adjacent runs of the same emphasis into one drawable piece."""
    out: list[tuple[str, bool]] = []
    for word, hot, space in line:
        piece = (" " if space and out else "") + word
        if out and out[-1][1] == hot:
            out[-1] = (out[-1][0] + piece, hot)
        else:
            out.append((piece, hot))
    return out


def fit_rich(text: str, width: int, lines: int, ceiling: int, floor: int):
    plain = strip_emphasis(text)
    fnt, _ = fit(plain, width, lines, ceiling, floor)
    return fnt, wrap_rich(text, fnt, width)


# ---------------------------------------------------------------------------
# backdrop
# ---------------------------------------------------------------------------


_BACKDROPS: dict[tuple[int, int, str], Image.Image] = {}


def backdrop(size: tuple[int, int], accent: str) -> Image.Image:
    """A dark ground with one soft bloom in it, drawn once and reused.

    Per-frame it would cost a gaussian blur on a 1080p canvas thirty times a
    second, which is most of the render. It never animates, so it never needs
    to be drawn twice.
    """
    key = (size[0], size[1], accent)
    if key in _BACKDROPS:
        return _BACKDROPS[key]

    width, height = size
    colour = ACCENTS.get(accent, ACCENTS[DEFAULT_ACCENT])
    img = Image.new("RGB", size, BG)

    bloom = Image.new("RGB", (width // 4, height // 4), (0, 0, 0))
    ImageDraw.Draw(bloom).ellipse(
        [-width // 16, -height // 10, width // 5, height // 5],
        # Screen-blended, so this number is how far the whole frame lifts
        # towards the accent. Past about 0.2 a warm accent stops reading as a
        # light source and starts reading as a colour cast on the slide.
        fill=tuple(int(c * 0.17) for c in colour))
    ImageDraw.Draw(bloom).ellipse(
        [int(width * 0.19), int(height * 0.17), int(width * 0.28), int(height * 0.27)],
        fill=tuple(int(c * 0.06) for c in colour))
    bloom = bloom.filter(ImageFilter.GaussianBlur(26)).resize(size, Image.BILINEAR)

    import numpy as np
    base = np.asarray(img, dtype=np.uint16)
    glow = np.asarray(bloom, dtype=np.uint16)
    img = Image.fromarray((255 - ((255 - base) * (255 - glow) // 255)).astype("uint8"))

    # A hairline of accent along the top edge. It is the only thing on screen
    # that is the same on every slide, which is what makes a set of slides read
    # as one deck.
    ImageDraw.Draw(img).rectangle(
        [0, 0, width, max(2, height // 360)], fill=tuple(int(c * 0.55) for c in colour))

    _BACKDROPS[key] = img
    return img


# ---------------------------------------------------------------------------
# chrome
# ---------------------------------------------------------------------------


def chrome(d, spec: Spec, size: tuple[int, int], t: float, seconds: float,
           progress: tuple[int, int] | None = None) -> None:
    """Kicker, footnote and the deck rail. Everything a slide has in common."""
    width, height = size
    unit = height / 1080
    margin = int(96 * unit)

    if spec.kicker:
        fnt = motion.bold(int(30 * unit))
        text = spec.kicker.upper()
        d.text((margin, int(margin * 0.62)), text, font=fnt,
               fill=blend(spec.colour, window(t, 0.0, 0.3)))
        # A short rule under the kicker, drawn to the kicker's own width so it
        # never looks arbitrary.
        run = fnt.getlength(text)
        grown = run * ease_out(window(t, 0.12, 0.45))
        d.rectangle([margin, int(margin * 0.62 + 44 * unit),
                     margin + grown, int(margin * 0.62 + 47 * unit)],
                    fill=blend(spec.colour, 0.55))

    if spec.footnote:
        fnt = motion.regular(int(30 * unit))
        limit = int(width - margin * 2 - (420 * unit if spec.presenter == "corner" else 0))
        lines = wrap(strip_emphasis(spec.footnote), fnt, limit)[:2]
        # Late, and never before two thirds through: the footnote is the aside
        # you land on, and putting it up with the headline spends it early.
        start = max(seconds * 0.62, seconds - 4.5)
        a = window(t, start, 0.5)
        # Nothing at all before the beat. `blend(colour, 0)` returns the
        # background colour, which is opaque — and against a backdrop that has
        # a bloom lifting it, drawing in the background colour is *visible*.
        # The footnote reads as a ghost of itself for the first two thirds of
        # every slide, which looks like a bug in the fade and is not.
        if a > 0.001:
            y = caption_top(size) - int(len(lines) * 40 * unit) - int(18 * unit)
            d.rectangle([margin, y + int(6 * unit), margin + int(4 * unit),
                         y + int(len(lines) * 40 * unit)],
                        fill=blend(spec.colour, a * 0.8))
            for i, line in enumerate(lines):
                d.text((margin + int(22 * unit), y + i * int(40 * unit)), line,
                       font=fnt, fill=blend(MUTED, a))

    if progress:
        current, total = progress
        rail = int(width * 0.999)
        seg = rail / max(1, total)
        y = height - max(3, int(5 * unit))
        d.rectangle([0, y, rail, height], fill=blend(PANEL, 0.9))
        done = seg * (current - 1) + seg * min(1.0, t / max(0.1, seconds))
        d.rectangle([0, y, done, height], fill=blend(spec.colour, 0.85))


# The bottom of the frame is spoken for: burned-in captions sit in a band
# there on every section, so no layout may draw into it. Reserving the band
# unconditionally — even on a section that turns out to have no words under it
# — is the only way the eye reads one caption position through the whole film
# rather than one that moves whenever a slide is busy.
CAPTION_BAND = 0.155


def caption_top(size: tuple[int, int]) -> int:
    return int(size[1] * (1 - CAPTION_BAND))


def content_box(spec: Spec, size: tuple[int, int]) -> tuple[int, int, int, int]:
    """Where a layout is allowed to draw."""
    width, height = size
    unit = height / 1080
    margin = int(96 * unit)
    right = width - margin
    if spec.presenter == "corner":
        right -= int(400 * unit)
    top = margin + int(90 * unit if spec.kicker else 0)
    bottom = caption_top(size) - int(110 * unit if spec.footnote else 24 * unit)
    return margin, top, right, bottom


def beats(count: int, seconds: float, first: float = 0.55,
          span: float = 0.55) -> list[float]:
    """When each of `count` elements arrives.

    Spread across the first `span` of the section rather than the whole of it,
    because the last element wants to be up and readable while the presenter is
    still talking about it. An element that lands on the final word is an
    element nobody read.
    """
    if count <= 0:
        return []
    if count == 1:
        return [first]
    room = max(0.9, seconds * span - first)
    step = min(1.15, room / (count - 1))
    return [first + i * step for i in range(count)]


# ---------------------------------------------------------------------------
# layouts
# ---------------------------------------------------------------------------


def _headline(d, spec: Spec, box, size, t, at: float = 0.32, ceiling=132,
              floor=54, lines=3, centre_y: float | None = None):
    left, top, right, bottom = box
    unit = size[1] / 1080
    fnt, wrapped = fit_rich(spec.headline, right - left, lines,
                            int(ceiling * unit), int(floor * unit))
    line_h = int(fnt.size * 1.16)
    y = top if centre_y is None else int(centre_y - len(wrapped) * line_h / 2)
    for i, line in enumerate(wrapped):
        a = window(t, at + i * 0.13, 0.42)
        if a > 0.001:
            rich_text(d, (left, y + i * line_h), line, fnt, FG, spec.colour, a,
                      rise=26 * unit * (1 - a))
    return y + len(wrapped) * line_h


def layout_title(d, img, spec, size, t, seconds):
    left, top, right, bottom = content_box(spec, size)
    unit = size[1] / 1080
    end = _headline(d, spec, (left, top, right, bottom), size, t, at=0.35,
                    ceiling=150, floor=64, lines=3,
                    centre_y=(top + bottom) * 0.46)
    if spec.sub:
        fnt = motion.regular(int(42 * unit))
        for i, line in enumerate(wrap(strip_emphasis(spec.sub), fnt, right - left)[:2]):
            a = window(t, 0.95 + i * 0.12, 0.45)
            d.text((left, end + int(30 * unit) + i * int(52 * unit)), line,
                   font=fnt, fill=blend(MUTED, a))


def layout_statement(d, img, spec, size, t, seconds):
    left, top, right, bottom = content_box(spec, size)
    unit = size[1] / 1080
    end = _headline(d, spec, (left, top, right, bottom), size, t, at=0.28,
                    ceiling=124, floor=52, lines=3,
                    centre_y=(top + bottom) * 0.47)
    if spec.sub:
        fnt = motion.regular(int(40 * unit))
        for i, line in enumerate(wrap(strip_emphasis(spec.sub), fnt, right - left)[:3]):
            a = window(t, 0.9 + i * 0.14, 0.45)
            d.text((left, end + int(34 * unit) + i * int(50 * unit)), line,
                   font=fnt, fill=blend(MUTED, a))


def layout_stats(d, img, spec, size, t, seconds):
    left, top, right, bottom = content_box(spec, size)
    unit = size[1] / 1080
    end = _headline(d, spec, (left, top, right, bottom), size, t, at=0.28,
                    ceiling=86, floor=44, lines=2)
    items = spec.items[:3] or [Item(value="—", label="")]
    when = beats(len(items), seconds, first=max(0.9, end and 0.9), span=0.42)

    gap = int(56 * unit)
    cell = (right - left - gap * (len(items) - 1)) // len(items)
    y = int(end + (bottom - end) * 0.16)
    box_h = int(min((bottom - y) * 0.86, 300 * unit))

    for i, item in enumerate(items):
        x = left + i * (cell + gap)
        a = window(t, when[i], 0.42)
        if a <= 0.001:
            continue
        lift = int(24 * unit * (1 - a))
        d.rounded_rectangle([x, y + lift, x + cell, y + box_h + lift],
                            radius=int(26 * unit), fill=blend(PANEL, a))
        d.rectangle([x, y + lift, x + int(6 * unit), y + box_h + lift],
                    fill=blend(spec.colour, a))

        value = item.value or item.label
        vfnt, _ = fit(value, cell - int(56 * unit), 1, int(132 * unit), int(48 * unit))
        d.text((x + cell // 2, y + int(box_h * 0.42) + lift), value, font=vfnt,
               fill=blend(spec.colour if i else FG, a), anchor="mm")
        if item.value and item.label:
            lfnt = motion.regular(int(34 * unit))
            d.text((x + cell // 2, y + int(box_h * 0.74) + lift), item.label,
                   font=lfnt, fill=blend(MUTED, a), anchor="mm")

    if spec.sub:
        fnt = motion.bold(int(44 * unit))
        a = window(t, when[-1] + 0.5, 0.45)
        for i, line in enumerate(wrap(strip_emphasis(spec.sub), fnt, right - left)[:2]):
            d.text((left, y + box_h + int(44 * unit) + i * int(54 * unit)), line,
                   font=fnt, fill=blend(FG, a))


def layout_steps(d, img, spec, size, t, seconds):
    left, top, right, bottom = content_box(spec, size)
    unit = size[1] / 1080
    end = _headline(d, spec, (left, top, right, bottom), size, t, at=0.25,
                    ceiling=78, floor=40, lines=2)
    items = spec.items or [Item(label="—")]
    when = beats(len(items), seconds, first=0.75, span=0.6)

    columns = 3 if len(items) > 4 else min(len(items), 2) or 1
    rows = (len(items) + columns - 1) // columns
    gap = int(28 * unit)
    cell_w = (right - left - gap * (columns - 1)) // columns
    room = bottom - end
    cell_h = min(int((room - gap * (rows + 1)) / rows), int(150 * unit))
    # Centred in what is left, like `bullets`. A four-item grid top-anchored
    # under a one-line headline leaves a third of the frame empty and the
    # slide reads as unfinished — nine items fill it and four do not, and the
    # layout should not look different depending on how many there are.
    y0 = int(end + (room - (cell_h * rows + gap * (rows - 1))) / 2)

    for i, item in enumerate(items):
        cx, cy = i % columns, i // columns
        x = left + cx * (cell_w + gap)
        y = y0 + cy * (cell_h + gap)
        a = window(t, when[i], 0.34)
        if a <= 0.001:
            continue
        lift = int(18 * unit * (1 - a))
        d.rounded_rectangle([x, y + lift, x + cell_w, y + cell_h + lift],
                            radius=int(18 * unit), fill=blend(PANEL, a))
        badge = int(cell_h * 0.42)
        bx, by = x + int(24 * unit), y + (cell_h - badge) // 2 + lift
        d.rounded_rectangle([bx, by, bx + badge, by + badge], radius=int(10 * unit),
                            fill=blend(spec.colour, a * 0.9))
        d.text((bx + badge / 2, by + badge / 2), item.value or str(i + 1),
               font=motion.bold(int(badge * 0.58)), fill=blend(BG, a), anchor="mm")
        lfnt, lines = fit(item.label, cell_w - badge - int(64 * unit), 2,
                          int(40 * unit), int(22 * unit))
        ty = y + cell_h / 2 + lift - (len(lines) - 1) * lfnt.size * 0.6
        for j, line in enumerate(lines):
            d.text((bx + badge + int(22 * unit), ty + j * lfnt.size * 1.2), line,
                   font=lfnt, fill=blend(FG, a), anchor="lm")

    if spec.sub:
        fnt = motion.regular(int(36 * unit))
        a = window(t, when[-1] + 0.45, 0.45)
        d.text((left, y0 + rows * (cell_h + gap) + int(10 * unit)),
               strip_emphasis(spec.sub)[:120], font=fnt, fill=blend(MUTED, a))


def layout_bullets(d, img, spec, size, t, seconds):
    left, top, right, bottom = content_box(spec, size)
    unit = size[1] / 1080
    end = _headline(d, spec, (left, top, right, bottom), size, t, at=0.25,
                    ceiling=92, floor=44, lines=2)
    items = spec.items or [Item(label="—")]
    when = beats(len(items), seconds, first=0.8, span=0.62)

    room = bottom - end
    step = min(int(room / max(1, len(items))), int(124 * unit))
    # Centred in the space left over, not hung from the headline. Three bullets
    # top-anchored under a one-line headline leave a third of the frame empty
    # and the slide reads as unfinished.
    y = int(end + (room - step * len(items)) / 2)
    fnt = motion.bold(int(min(step * 0.42, 50 * unit)))

    for i, item in enumerate(items):
        a = window(t, when[i], 0.38)
        if a <= 0.001:
            continue
        cy = y + i * step + step * 0.4
        dot = int(14 * unit)
        d.ellipse([left, cy - dot, left + dot * 2, cy + dot],
                  fill=blend(spec.colour, a))
        text = strip_emphasis(item.label)
        lfnt = fnt
        avail = right - left - int(64 * unit)
        while lfnt.getlength(text) > avail and lfnt.size > 22 * unit:
            lfnt = motion.bold(int(lfnt.size - 3))
        d.text((left + int(52 * unit), cy), text, font=lfnt,
               fill=blend(FG, a), anchor="lm")
        if item.note:
            nfnt = motion.regular(int(lfnt.size * 0.62))
            d.text((left + int(52 * unit), cy + lfnt.size * 0.82), item.note,
                   font=nfnt, fill=blend(MUTED, window(t, when[i] + 0.25, 0.4)))


def layout_flow(d, img, spec, size, t, seconds):
    left, top, right, bottom = content_box(spec, size)
    unit = size[1] / 1080
    end = _headline(d, spec, (left, top, right, bottom), size, t, at=0.25,
                    ceiling=86, floor=42, lines=2)
    items = spec.items[:4] or [Item(label="—")]
    when = beats(len(items), seconds, first=0.85, span=0.5)

    arrow = int(64 * unit)
    cell = (right - left - arrow * (len(items) - 1)) // len(items)
    y = int(end + (bottom - end) * 0.2)
    box_h = int(min((bottom - y) * 0.7, 230 * unit))

    for i, item in enumerate(items):
        x = left + i * (cell + arrow)
        a = window(t, when[i], 0.4)
        if a > 0.001:
            lift = int(20 * unit * (1 - a))
            d.rounded_rectangle([x, y + lift, x + cell, y + box_h + lift],
                                radius=int(22 * unit), fill=blend(PANEL, a))
            lfnt, lines = fit(strip_emphasis(item.label), cell - int(48 * unit), 3,
                              int(46 * unit), int(24 * unit))
            ty = y + box_h / 2 + lift - (len(lines) - 1) * lfnt.size * 0.62
            for j, line in enumerate(lines):
                d.text((x + cell / 2, ty + j * lfnt.size * 1.24), line, font=lfnt,
                       fill=blend(FG, a), anchor="mm")
        if i < len(items) - 1:
            # The arrow belongs to the *arrival* of the next box, so the chain
            # reads as one motion travelling left to right.
            b = ease_out(window(t, when[i + 1] - 0.16, 0.32))
            if b > 0.001:
                ax = x + cell + arrow * 0.2
                ay = y + box_h / 2
                d.line([(ax, ay), (ax + arrow * 0.6 * b, ay)],
                       fill=blend(spec.colour, b), width=max(3, int(5 * unit)))
                if b > 0.6:
                    tip = ax + arrow * 0.6 * b
                    h = int(11 * unit)
                    d.polygon([(tip + h, ay), (tip - h * 0.4, ay - h),
                               (tip - h * 0.4, ay + h)], fill=blend(spec.colour, b))


def layout_equation(d, img, spec, size, t, seconds):
    left, top, right, bottom = content_box(spec, size)
    unit = size[1] / 1080
    end = _headline(d, spec, (left, top, right, bottom), size, t, at=0.25,
                    ceiling=96, floor=46, lines=2)
    items = (spec.items + [Item(label=""), Item(label=""), Item(label="")])[:3]
    when = beats(3, seconds, first=0.85, span=0.5)

    sign = int(72 * unit)
    cell = (right - left - sign * 2) // 3
    y = int(end + (bottom - end) * 0.2)
    box_h = int(min((bottom - y) * 0.72, 250 * unit))

    for i, item in enumerate(items):
        x = left + i * (cell + sign)
        a = window(t, when[i], 0.4)
        if a > 0.001:
            lift = int(20 * unit * (1 - a))
            hot = i == 2
            d.rounded_rectangle([x, y + lift, x + cell, y + box_h + lift],
                                radius=int(22 * unit),
                                fill=blend(spec.colour if hot else PANEL,
                                           a * (0.22 if hot else 1.0)))
            if hot:
                d.rounded_rectangle([x, y + lift, x + cell, y + box_h + lift],
                                    radius=int(22 * unit), outline=blend(spec.colour, a),
                                    width=max(2, int(3 * unit)))
            lfnt, lines = fit(strip_emphasis(item.label), cell - int(48 * unit), 3,
                              int(48 * unit), int(24 * unit))
            ty = y + box_h / 2 + lift - (len(lines) - 1) * lfnt.size * 0.62
            for j, line in enumerate(lines):
                d.text((x + cell / 2, ty + j * lfnt.size * 1.24), line, font=lfnt,
                       fill=blend(spec.colour if hot else FG, a), anchor="mm")
        if i < 2:
            b = window(t, when[i + 1] - 0.14, 0.3)
            d.text((x + cell + sign / 2, y + box_h / 2), "+" if i == 0 else "=",
                   font=motion.bold(int(58 * unit)), fill=blend(MUTED, b), anchor="mm")


def layout_closer(d, img, spec, size, t, seconds):
    left, top, right, bottom = content_box(spec, size)
    unit = size[1] / 1080
    mid = (top + bottom) * 0.44
    hfnt, hlines = fit_rich(spec.headline, right - left, 2, int(112 * unit),
                            int(52 * unit))
    line_h = int(hfnt.size * 1.14)
    y = int(mid - len(hlines) * line_h)
    for i, line in enumerate(hlines):
        a = window(t, 0.3 + i * 0.14, 0.45)
        if a > 0.001:
            rich_text(d, (left, y + i * line_h), line, hfnt, FG, spec.colour, a,
                      rise=24 * unit * (1 - a))
    y += len(hlines) * line_h + int(18 * unit)

    if spec.sub:
        sfnt, slines = fit_rich(spec.sub, right - left, 2, int(112 * unit),
                                int(52 * unit))
        for i, line in enumerate(slines):
            a = window(t, 0.95 + i * 0.14, 0.5)
            if a > 0.001:
                rich_text(d, (left, y + i * int(sfnt.size * 1.14)), line, sfnt,
                          spec.colour, spec.colour, a, rise=24 * unit * (1 - a))
        y += len(slines) * int(sfnt.size * 1.14)

    for item in spec.items[:1]:
        a = window(t, seconds * 0.55, 0.5)
        if a <= 0.001:
            continue
        fnt = motion.bold(int(40 * unit))
        pad = int(30 * unit)
        w = fnt.getlength(item.label) + pad * 2
        h = int(fnt.size * 2.0)
        by = y + int(48 * unit)
        d.rounded_rectangle([left, by, left + w, by + h], radius=h // 2,
                            fill=blend(spec.colour, a))
        d.text((left + w / 2, by + h / 2), item.label, font=fnt,
               fill=blend(BG, a), anchor="mm")


RENDERERS = {
    "title": layout_title,
    "statement": layout_statement,
    "stats": layout_stats,
    "steps": layout_steps,
    "bullets": layout_bullets,
    "flow": layout_flow,
    "equation": layout_equation,
    "closer": layout_closer,
}


# ---------------------------------------------------------------------------
# render
# ---------------------------------------------------------------------------


def scene(spec: Spec, seconds: float, size: tuple[int, int],
          progress: tuple[int, int] | None = None, name: str = "slide") -> Scene:
    ground = backdrop(size, spec.accent)
    draw_layout = RENDERERS[spec.layout]

    def draw(d, img, t):
        img.paste(ground)
        d = ImageDraw.Draw(img)
        chrome(d, spec, size, t, seconds, progress)
        draw_layout(d, img, spec, size, t, seconds)
        # A half-second dip to black at the very end of a section. Sections
        # otherwise butt straight together and two slides in the same layout
        # read as one slide whose text changed by itself.
        tail = seconds - t
        if tail < 0.28:
            fade = 1 - max(0.0, tail / 0.28)
            return Image.blend(img, Image.new("RGB", size, BG), fade * 0.85)
        return img

    return Scene(name=name, seconds=seconds, draw=draw)


def render(spec: dict[str, Any] | Spec, seconds: float, out: Path,
           size: tuple[int, int], progress: tuple[int, int] | None = None) -> Path:
    parsed = spec if isinstance(spec, Spec) else Spec.parse(spec)
    return motion.render(scene(parsed, seconds, size, progress, out.stem),
                         out=out, size=size)
