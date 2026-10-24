"""Captions that keep up with the sentence, from the words we already timed.

Most of a video's audience has the sound off for the first few seconds, and a
good number never turn it on. Captions are not an accessibility afterthought
here; they are the copy that decides whether the video gets watched.

Two or three words at a time, the current one lit. It is a short-form
convention and it earns its keep for a boring mechanical reason: a full line of
subtitle is read in about 400ms and then the eye has nothing to do for the
remaining two seconds, so it wanders off the frame. A card that changes on the
beat of the speech never gives it the chance.

Everything here is generated from `transcribe.Word` timings. Nothing re-listens
to the audio, so captions cannot drift out of sync with a cut — a word removed
from the film is a word that was never in the caption list.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from demoforge.transcribe import Word

# Held to three because the card is read as a unit and a four-word card at this
# size starts wrapping on a 1080p frame.
MAX_WORDS = 3
MAX_CHARS = 26
MAX_SECONDS = 1.9
# A gap this long is a breath or a cut, and a card should not straddle one.
SPLIT_GAP = 0.42

# Sentence-final punctuation ends a card even mid-count: the pause after a full
# stop is where the viewer catches up.
ENDS = re.compile(r"[.!?…]$")
COMMA = re.compile(r"[,;:—]$")


def _ass_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    hours, rest = divmod(seconds, 3600)
    minutes, rest = divmod(rest, 60)
    return f"{int(hours)}:{int(minutes):02d}:{rest:05.2f}"


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "(").replace("}", ")")


@dataclass
class Card:
    words: list[Word]

    @property
    def start(self) -> float:
        return self.words[0].start

    @property
    def end(self) -> float:
        return self.words[-1].end

    def text(self) -> str:
        return " ".join(w.text.strip() for w in self.words)


def cards(words: list[Word], max_words: int = MAX_WORDS,
          max_chars: int = MAX_CHARS, max_seconds: float = MAX_SECONDS,
          split_gap: float = SPLIT_GAP) -> list[Card]:
    """Group timed words into cards that break where the speech breaks.

    Every limit is a parameter because the two consumers want opposite things.
    Burned-in captions want two or three words held for under two seconds. A
    sidecar `.srt` is rendered by somebody else's player at their size, and
    three-word subtitles there look like a stutter — it wants a line's worth.
    Raising only `max_words` and leaving the character and duration caps at
    their burn-in values gets you the short cards anyway.
    """
    out: list[Card] = []
    current: list[Word] = []

    def flush():
        if current:
            out.append(Card(list(current)))
            current.clear()

    for word in words:
        if current:
            gap = word.start - current[-1].end
            span = word.end - current[0].start
            chars = len(" ".join(w.text for w in current)) + len(word.text) + 1
            if (gap > split_gap or span > max_seconds
                    or len(current) >= max_words or chars > max_chars):
                flush()
        current.append(word)
        stripped = word.text.strip()
        if ENDS.search(stripped):
            flush()
        elif COMMA.search(stripped) and len(current) >= 2:
            flush()
    flush()
    return out


def header(width: int, height: int, accent: str = "#58A6FF",
           font: str = "Segoe UI Black", size_frac: float = 0.058,
           margin_v_frac: float = 0.052, margin_h_frac: float = 0.215) -> str:
    """An ASS preamble sized to the frame it will be burned into.

    `PlayResX/Y` matching the real frame is what makes every measurement below
    a real pixel measurement, so the same file burns correctly at 1080p and at
    a vertical crop without a second set of numbers.
    """
    size = int(height * size_frac)
    outline = max(3, int(height * 0.0045))
    # ASS colours are &HBBGGRR. Getting this backwards yields a blue that is
    # orange, which is the sort of thing that survives three review passes.
    r, g, b = accent.lstrip("#")[0:2], accent.lstrip("#")[2:4], accent.lstrip("#")[4:6]
    hot = f"&H00{b}{g}{r}"
    # Captions live in a band the slide layouts keep clear and the presenter
    # inset sits beside, not on top of.
    # Fractions, because the same file has to burn onto a 16:9 frame whose only
    # obstruction is a corner inset, and onto a 9:16 one where the platform
    # covers the bottom fifth with its own interface.
    margin_v = int(height * margin_v_frac)
    margin_h = int(width * margin_h_frac)
    return "\n".join([
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {width}",
        f"PlayResY: {height}",
        "WrapStyle: 2",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, "
        "ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, "
        "MarginL, MarginR, MarginV, Encoding",
        f"Style: pop,{font},{size},&H00FFFFFF,{hot},&H00101418,&H88000000,"
        f"-1,0,0,0,100,100,1,0,1,{outline},2,2,"
        f"{margin_h},{margin_h},{margin_v},1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, "
        "MarginV, Effect, Text",
    ])


def events(cards_: list[Card], accent: str = "#58A6FF") -> list[str]:
    """One dialogue line per word, each showing its whole card.

    Highlighting by re-emitting the card is not the elegant way to do it — ASS
    can animate a single line with `\\k` karaoke tags — but karaoke timing is
    expressed as centiseconds *since the line started* and accumulates rounding
    across a long card. Word timings are absolute and stay absolute this way.
    """
    hexed = accent.lstrip("#")
    hot = f"&H00{hexed[4:6]}{hexed[2:4]}{hexed[0:2]}&"
    lines: list[str] = []

    for index, card in enumerate(cards_):
        # The last word of a card is held a little past its own end so the card
        # does not vanish on the closing consonant — but never past the moment
        # the next card arrives. ASS stacks simultaneous lines at the same
        # alignment rather than replacing them, so an overlap of two frames is
        # not a subtle timing error: it is the caption jumping up a line and
        # back down again, once per card, for the length of the film.
        ceiling = cards_[index + 1].start if index + 1 < len(cards_) else None
        tail = card.end + 0.06
        if ceiling is not None:
            tail = min(tail, ceiling)
        for i, word in enumerate(card.words):
            start = word.start
            end = card.words[i + 1].start if i + 1 < len(card.words) else tail
            if end <= start:
                continue
            pieces = []
            for j, w in enumerate(card.words):
                text = _escape(w.text.strip())
                if j == i:
                    pieces.append(f"{{\\c{hot}}}{text}{{\\c&H00FFFFFF&}}")
                else:
                    pieces.append(text)
            body = " ".join(pieces)
            # Only the card's first word fades in; fading every word would
            # strobe the whole card three times a second.
            if i == 0:
                body = "{\\fad(90,0)}" + body
            lines.append(
                f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},pop,,0,0,0,,{body}")
    return lines


def write(words: list[Word], out: Path, width: int, height: int,
          accent: str = "#58A6FF", max_words: int = MAX_WORDS,
          font: str = "Segoe UI Black", size_frac: float = 0.058,
          margin_v_frac: float = 0.052, margin_h_frac: float = 0.215) -> Path:
    grouped = cards(words, max_words)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        header(width, height, accent, font, size_frac, margin_v_frac,
               margin_h_frac)
        + "\n" + "\n".join(events(grouped, accent)) + "\n",
        encoding="utf-8")
    print(f"  {out.name}  {len(grouped)} cards, {len(words)} words")
    return out


def srt(words: list[Word], out: Path, max_words: int = 12) -> Path:
    """A sidecar file for the platforms that want to do their own rendering."""
    grouped = cards(words, max_words, max_chars=84, max_seconds=5.5,
                    split_gap=0.9)
    lines: list[str] = []
    for i, card in enumerate(grouped, start=1):
        def stamp(value: float) -> str:
            hours, rest = divmod(max(0.0, value), 3600)
            minutes, rest = divmod(rest, 60)
            return f"{int(hours):02d}:{int(minutes):02d}:{rest:06.3f}".replace(".", ",")
        lines += [str(i), f"{stamp(card.start)} --> {stamp(card.end)}",
                  card.text(), ""]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    return out


def filter_path(path: Path) -> str:
    """A path ffmpeg's `subtitles` filter will actually accept on Windows.

    The filter argument is parsed twice — once by the filtergraph, once by
    libass — so a drive letter's colon reads as an option separator and a
    backslash reads as an escape. Forward slashes plus an escaped colon is the
    one form that survives both passes.
    """
    text = path.resolve().as_posix()
    return text.replace(":", r"\:").replace("'", r"\'")


def burn(video: Path, ass: Path, out: Path, crf: int = 18,
         fontsdir: Path | None = None) -> Path:
    """Burn the subtitles in.

    `fontsdir` points libass at fonts that are not installed on the machine.
    Without it a style naming a downloaded family silently falls back to the
    default sans, which looks like the caption style simply did not apply.
    """
    style = f"subtitles='{filter_path(ass)}'"
    if fontsdir:
        style += f":fontsdir='{filter_path(fontsdir)}'"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(video),
         "-vf", style,
         "-c:v", "libx264", "-preset", "medium", "-crf", str(crf),
         "-pix_fmt", "yuv420p", "-c:a", "copy",
         "-movflags", "+faststart", str(out)],
        check=True)
    return out
