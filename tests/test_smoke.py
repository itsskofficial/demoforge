"""Fast tests for the parts that do not need a model, a GPU or ffmpeg.

Deliberately narrow. The expensive stages are covered by using them; what is
worth pinning here is the quiet logic that would break a render an hour in and
give no clue why: terminal emulation, text chunking, easing bounds, and the
arithmetic that keeps picture and narration on the same timeline.

    python -m pytest tests -q
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from demoforge.motion import ease, ease_out, window, wrap  # noqa: E402
from demoforge.terminal import Screen  # noqa: E402
from demoforge.voice import Voice  # noqa: E402


# ---------------------------------------------------------------------------
# terminal emulation
# ---------------------------------------------------------------------------


def render(screen: Screen) -> list[str]:
    return ["".join(c.ch for c in line).rstrip() for line, _ in [(l, None) for l in screen.lines]]


def test_plain_text_lands_on_one_line():
    s = Screen(40, 10)
    s.feed("hello world")
    assert render(s)[0] == "hello world"


def test_crlf_starts_a_new_line():
    s = Screen(40, 10)
    s.feed("one\r\ntwo")
    assert render(s)[:2] == ["one", "two"]


def test_carriage_return_overwrites_in_place():
    """Progress bars redraw with \\r; the old text must not survive."""
    s = Screen(40, 10)
    s.feed("50%\r99%")
    assert render(s)[0] == "99%"


def test_sgr_sets_colour_and_resets():
    s = Screen(40, 10)
    s.feed("\x1b[31mred\x1b[0mplain")
    line = s.lines[0]
    assert line[0].fg != line[3].fg
    assert not line[3].bold


def test_wrapping_at_the_column_limit():
    s = Screen(10, 10)
    s.feed("a" * 15)
    assert render(s)[0] == "a" * 10
    assert render(s)[1] == "a" * 5


def test_viewport_shows_only_the_last_rows():
    s = Screen(20, 3)
    s.feed("\r\n".join(str(i) for i in range(10)))
    lines, _ = s.viewport()
    assert len(lines) == 3
    assert "".join(c.ch for c in lines[-1]).strip() == "9"


# ---------------------------------------------------------------------------
# narration chunking
# ---------------------------------------------------------------------------


def test_chunking_keeps_sentences_whole():
    text = "One two three. Four five six. Seven eight nine."
    parts = Voice.chunk(text, max_chars=20)
    assert all(p.endswith(".") for p in parts)
    assert " ".join(parts) == text


def test_chunking_groups_up_to_the_limit():
    text = "A a. B b. C c."
    assert Voice.chunk(text, max_chars=100) == [text]


def test_chunking_never_returns_empty_pieces():
    assert Voice.chunk("   ") == []
    assert all(p.strip() for p in Voice.chunk("Hi.  \n\n  There."))


def test_chunking_collapses_whitespace():
    assert Voice.chunk("a\n\n   b")[0] == "a b"


# ---------------------------------------------------------------------------
# motion timing
# ---------------------------------------------------------------------------


def test_easing_is_bounded_and_monotonic():
    for fn in (ease, ease_out):
        values = [fn(i / 20) for i in range(-5, 26)]
        assert all(0.0 <= v <= 1.0 for v in values)
        assert values == sorted(values)
        assert fn(0) == 0.0 and fn(1) == 1.0


def test_window_is_zero_before_and_one_after():
    assert window(0.0, start=1.0, dur=0.5) == 0.0
    assert window(0.9, start=1.0, dur=0.5) == 0.0
    assert window(2.0, start=1.0, dur=0.5) == 1.0
    assert 0.0 < window(1.25, start=1.0, dur=0.5) < 1.0


def test_window_with_zero_duration_is_a_step():
    assert window(0.9, 1.0, 0.0) == 0.0
    assert window(1.0, 1.0, 0.0) == 1.0


# ---------------------------------------------------------------------------
# text layout
# ---------------------------------------------------------------------------


class FakeFont:
    """Every character is ten units wide, so widths are predictable."""

    def getlength(self, text: str) -> float:
        return len(text) * 10.0


def test_wrap_breaks_on_width_and_keeps_every_word():
    words = "the quick brown fox jumps over the lazy dog"
    lines = wrap(words, FakeFont(), 100)
    assert all(len(line) <= 10 for line in lines)
    assert " ".join(lines) == words


def test_wrap_keeps_a_word_longer_than_the_line():
    assert wrap("antidisestablishmentarianism", FakeFont(), 50) == \
        ["antidisestablishmentarianism"]


# ---------------------------------------------------------------------------
# the timeline picture and words share
# ---------------------------------------------------------------------------


def test_speaking_windows_accumulate_along_the_running_order(tmp_path):
    import json

    from demoforge.compose import speaking_windows

    narration = tmp_path / "n.json"
    order = tmp_path / "o.json"
    narration.write_text(json.dumps([
        {"id": "a", "file": "a.wav", "seconds": 4.0},
        {"id": "b", "file": "b.wav", "seconds": 6.0},
    ]), encoding="utf-8")
    order.write_text(json.dumps([
        {"segment": "a", "length": 5.0},
        {"segment": "b", "length": 8.0},
    ]), encoding="utf-8")

    windows = speaking_windows(narration, order, pad=0.0)
    assert windows == [(0.0, 4.0), (5.0, 11.0)]


def test_speaking_windows_skip_segments_with_no_line(tmp_path):
    import json

    from demoforge.compose import speaking_windows

    narration = tmp_path / "n.json"
    order = tmp_path / "o.json"
    narration.write_text(json.dumps([{"id": "b", "file": "b.wav", "seconds": 2.0}]),
                         encoding="utf-8")
    order.write_text(json.dumps([{"segment": "a", "length": 3.0},
                                 {"segment": "b", "length": 4.0}]), encoding="utf-8")

    assert speaking_windows(narration, order, pad=0.0) == [(3.0, 5.0)]
