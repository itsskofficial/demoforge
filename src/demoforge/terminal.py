"""A small terminal emulator and a frame painter for it.

Enough VT to replay what the demo actually prints: SGR colour, bold, dim,
carriage return, newline, tab, and wrapping. No cursor addressing, because
nothing in the demo uses it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FONTS = Path("C:/Windows/Fonts")

BG = (13, 17, 23)
CHROME = (22, 27, 34)
CHROME_LINE = (48, 54, 61)
FG = (201, 209, 217)
MUTED = (110, 118, 129)

# index -> (normal, bright)
PALETTE = {
    0: ((72, 79, 88), (110, 118, 129)),
    1: ((248, 105, 96), (255, 138, 128)),   # red
    2: ((86, 211, 100), (126, 231, 135)),   # green
    3: ((225, 184, 96), (240, 209, 130)),   # yellow
    4: ((88, 166, 255), (121, 192, 255)),   # blue
    5: ((188, 140, 255), (210, 168, 255)),  # magenta
    6: ((57, 197, 187), (86, 220, 210)),    # cyan
    7: (FG, (255, 255, 255)),               # white
}


@dataclass
class Cell:
    ch: str = " "
    fg: tuple[int, int, int] = FG
    bold: bool = False
    dim: bool = False


SGR = re.compile(r"\x1b\[([0-9;]*)m")
OTHER_ESC = re.compile(r"\x1b\[[0-9;]*[A-Za-z]|\x1b\][^\x07]*\x07")


class Screen:
    """A grid that grows downward; the viewport is the last `rows` lines."""

    def __init__(self, cols: int = 100, rows: int = 26) -> None:
        self.cols = cols
        self.rows = rows
        self.lines: list[list[Cell]] = [[]]
        self.row = 0
        self.col = 0
        self._reset_style()

    def _reset_style(self) -> None:
        self.fg = FG
        self.bold = False
        self.dim = False

    def _apply_sgr(self, params: str) -> None:
        codes = [int(p) for p in params.split(";") if p != ""] or [0]
        for code in codes:
            if code == 0:
                self._reset_style()
            elif code == 1:
                self.bold = True
            elif code == 2:
                self.dim = True
            elif code == 22:
                self.bold = self.dim = False
            elif 30 <= code <= 37:
                self.fg = PALETTE[code - 30][0]
            elif 90 <= code <= 97:
                self.fg = PALETTE[code - 90][1]
            elif code == 39:
                self.fg = FG

    def _ensure(self, row: int) -> None:
        while len(self.lines) <= row:
            self.lines.append([])

    def feed(self, text: str) -> None:
        text = OTHER_ESC.sub(lambda m: m.group(0) if SGR.fullmatch(m.group(0)) else "", text)
        pos = 0
        for match in SGR.finditer(text):
            self._write(text[pos : match.start()])
            self._apply_sgr(match.group(1))
            pos = match.end()
        self._write(text[pos:])

    def _write(self, text: str) -> None:
        for ch in text:
            if ch == "\r":
                self.col = 0
            elif ch == "\n":
                self.row += 1
                self.col = 0
                self._ensure(self.row)
            elif ch == "\t":
                self.col = (self.col // 8 + 1) * 8
            elif ch in ("\x07", "\x08", "\x0b", "\x0c"):
                continue
            else:
                if self.col >= self.cols:
                    self.row += 1
                    self.col = 0
                    self._ensure(self.row)
                self._ensure(self.row)
                line = self.lines[self.row]
                while len(line) <= self.col:
                    line.append(Cell())
                line[self.col] = Cell(ch, self.fg, self.bold, self.dim)
                self.col += 1

    def viewport(self) -> tuple[list[list[Cell]], int]:
        """The last `rows` lines, and the cursor's row within them."""
        start = max(0, len(self.lines) - self.rows)
        return self.lines[start:], self.row - start


class Painter:
    """Draws a Screen into a 1920x1080 frame with a window chrome."""

    def __init__(self, screen: Screen, title: str, size: int = 27,
                 width: int = 1920, height: int = 1080) -> None:
        self.screen = screen
        self.title = title
        self.width = width
        self.height = height
        self.regular = self._font("CascadiaMono.ttf", "consola.ttf", size)
        self.bold = self._font("CascadiaMono.ttf", "consolab.ttf", size, bold=True)
        self.ui = self._font("segoeui.ttf", "arial.ttf", 21)
        box = self.regular.getbbox("M")
        self.cw = self.regular.getlength("M")
        self.lh = int((box[3] - box[1]) * 1.72)
        self.pad_x = 42
        self.chrome_h = 58
        self.pad_y = self.chrome_h + 26

    @staticmethod
    def _font(name: str, fallback: str, size: int, bold: bool = False):
        for candidate in (name, fallback):
            path = FONTS / candidate
            if path.exists():
                font = ImageFont.truetype(str(path), size)
                if bold and candidate == name:
                    try:
                        font.set_variation_by_name("Bold")
                    except Exception:
                        # A static face; fall through to the bold fallback file.
                        bold_path = FONTS / fallback
                        if bold_path.exists():
                            return ImageFont.truetype(str(bold_path), size)
                return font
        raise FileNotFoundError(f"no font: {name} / {fallback}")

    def paint(self, status: str = "", cursor: bool = False) -> Image.Image:
        img = Image.new("RGB", (self.width, self.height), BG)
        d = ImageDraw.Draw(img)

        d.rectangle([0, 0, self.width, self.chrome_h], fill=CHROME)
        d.line([0, self.chrome_h, self.width, self.chrome_h], fill=CHROME_LINE)
        for i, colour in enumerate([(255, 95, 87), (255, 189, 46), (39, 201, 63)]):
            cx = 34 + i * 26
            d.ellipse([cx - 8, self.chrome_h // 2 - 8, cx + 8, self.chrome_h // 2 + 8], fill=colour)
        d.text((136, self.chrome_h // 2), self.title, font=self.ui, fill=MUTED, anchor="lm")
        if status:
            d.text((self.width - 42, self.chrome_h // 2), status, font=self.ui,
                   fill=MUTED, anchor="rm")

        lines, cursor_row = self.screen.viewport()
        for r, line in enumerate(lines):
            y = self.pad_y + r * self.lh
            if y > self.height - self.lh:
                break
            # Group adjacent cells sharing a style so we draw runs, not characters.
            c = 0
            while c < len(line):
                cell = line[c]
                if cell.ch == " " and not cell.bold:
                    c += 1
                    continue
                run = [cell.ch]
                style = (cell.fg, cell.bold, cell.dim)
                c2 = c + 1
                while c2 < len(line):
                    nxt = line[c2]
                    if (nxt.fg, nxt.bold, nxt.dim) != style or nxt.ch == "\t":
                        break
                    if (nxt.ch == "█") != (cell.ch == "█"):
                        break
                    run.append(nxt.ch)
                    c2 += 1
                colour = cell.fg
                if cell.dim:
                    colour = tuple(int(a * 0.55 + b * 0.45) for a, b in zip(colour, BG))
                x = self.pad_x + c * self.cw
                if cell.ch == "█":
                    # A full block glyph carries side bearings, so a bar chart drawn
                    # as text comes out striped. Fill the cells instead.
                    d.rectangle([x, y, x + len(run) * self.cw, y + self.lh], fill=colour)
                else:
                    d.text((x, y), "".join(run),
                           font=self.bold if cell.bold else self.regular, fill=colour)
                c = c2

        if cursor:
            y = self.pad_y + cursor_row * self.lh
            if 0 <= y <= self.height - self.lh:
                x = self.pad_x + self.screen.col * self.cw
                d.rectangle([x, y + 2, x + self.cw - 2, y + self.lh - 8], fill=(88, 166, 255))
        return img
