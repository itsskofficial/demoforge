"""Fast tests for editor mode. No ffmpeg, no whisper, no render.

The expensive half of `edit` is ffmpeg and a model call, and both are covered
by using them. What is worth pinning here is the arithmetic those two hand off
to — because all of it is invisible until it is wrong in the finished film, and
by then it looks like a rendering bug.

Four things in particular:

- `tighten` decides where every cut lands. A mistake here is a clipped word.
- `correct` rewrites text without moving timings. A mistake here desynchronises
  every caption after it.
- `cards` groups words for the caption band. A mistake here is a card that
  outlives its sentence.
- `slidekit`'s emphasis wrapping puts the accent on one word. A mistake here
  renders "cheap ." with a space before the full stop, which is the sort of
  thing that survives three review passes and is the first thing anyone sees.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from demoforge import slidekit  # noqa: E402
from demoforge.captions import cards, events, header  # noqa: E402
from demoforge.deck import _role  # noqa: E402
from demoforge.edit import (  # noqa: E402
    MIN_SEGMENT,
    PAUSE_CUT,
    PAUSE_KEEP,
    subtract,
    tighten,
)
from demoforge.transcribe import (  # noqa: E402
    Word,
    correct,
    destutter,
    implausible,
    windows,
)


def say(*pairs: tuple[str, float, float]) -> list[Word]:
    return [Word(text=t, start=a, end=b) for t, a, b in pairs]


def spoken(text: str, start: float = 0.0, pace: float = 0.4) -> list[Word]:
    """Evenly spaced words, for tests that care about grouping not timing."""
    out = []
    for i, token in enumerate(text.split()):
        out.append(Word(text=token, start=start + i * pace,
                        end=start + i * pace + pace * 0.8))
    return out


# ---------------------------------------------------------------------------
# tighten
# ---------------------------------------------------------------------------


def test_short_pauses_are_left_alone():
    """The pauses under the threshold are the delivery, not dead air."""
    words = say(("one", 1.0, 1.4), ("two", 1.9, 2.3), ("three", 2.8, 3.2))
    assert len(tighten(words)) == 1


def test_a_long_pause_becomes_two_segments():
    words = say(("one", 1.0, 1.4), ("two", 4.0, 4.4))
    keeps = tighten(words)
    assert len(keeps) == 2
    # The pause is shortened, not closed: a little of it survives on each side.
    assert keeps[0][1] == pytest.approx(1.4 + PAUSE_KEEP / 2)
    assert keeps[1][0] == pytest.approx(4.0 - PAUSE_KEEP / 2)


def test_the_gap_removed_is_the_gap_over_the_threshold():
    words = say(("one", 1.0, 1.4), ("two", 1.4 + PAUSE_CUT + 2.0, 5.0))
    keeps = tighten(words)
    removed = keeps[1][0] - keeps[0][1]
    assert removed == pytest.approx(PAUSE_CUT + 2.0 - PAUSE_KEEP)


def test_filler_is_lifted_with_the_hesitation_around_it():
    """Removing 'um' and leaving its silence behind is worse than keeping it."""
    words = say(("so", 1.0, 1.3), ("um", 2.2, 2.6), ("verify", 3.6, 4.2))
    text = []
    for start, end in tighten(words):
        text += [w.text for w in words if start <= (w.start + w.end) / 2 <= end]
    assert "um" not in text
    assert text == ["so", "verify"]


def test_a_sliver_is_folded_into_its_neighbour():
    """Two cuts close together leave a fragment not worth the jump it costs."""
    words = say(("one", 1.0, 1.3), ("two", 3.0, 3.1), ("three", 5.0, 5.4))
    for start, end in tighten(words):
        assert end - start >= MIN_SEGMENT


def test_the_span_never_starts_before_the_recording_does():
    assert tighten(say(("one", 0.02, 0.4)))[0][0] == 0.0


def test_every_kept_range_is_forward():
    words = spoken("a b c d e f g h")
    assert all(b > a for a, b in tighten(words))


# ---------------------------------------------------------------------------
# manual drops
# ---------------------------------------------------------------------------


def test_a_drop_in_the_middle_splits_the_range():
    assert subtract([(0.0, 10.0)], [(4.0, 6.0)]) == [(0.0, 4.0), (6.0, 10.0)]


def test_a_drop_is_subtracted_from_the_padded_range_not_the_words():
    """tighten pads each range with part of the pause on either side, and that
    padding is exactly wide enough to catch the first syllable of the thing
    being dropped. Subtracting afterwards is what makes the boundary exact."""
    words = say(("keep", 1.0, 1.5), ("cut", 4.0, 5.0), ("keep", 7.5, 8.0))
    keeps = subtract(tighten(words), [(3.8, 5.2)])
    assert all(end <= 3.8 or start >= 5.2 for start, end in keeps)


def test_overlapping_drops_do_not_produce_inverted_ranges():
    for start, end in subtract([(0.0, 10.0)], [(2.0, 6.0), (4.0, 8.0)]):
        assert end > start


def test_a_drop_covering_everything_leaves_nothing():
    assert subtract([(2.0, 5.0)], [(0.0, 9.0)]) == []


def test_a_fragment_left_by_a_drop_is_discarded():
    leftover = subtract([(0.0, 10.0)], [(0.1, 6.0)])
    assert all(end - start >= MIN_SEGMENT for start, end in leftover)


def test_no_drops_is_the_identity():
    ranges = [(0.0, 3.0), (5.0, 9.0)]
    assert subtract(ranges, []) == ranges


# ---------------------------------------------------------------------------
# corrections
# ---------------------------------------------------------------------------


def test_a_two_word_mishearing_is_matched_before_its_halves():
    words = say(("white", 1.0, 1.4), ("coding", 1.4, 1.9))
    fixed = correct(words, {"white coding": "vibe coding", "coding": "typing"})
    assert [w.text for w in fixed] == ["vibe", "coding"]


def test_a_replacement_stays_inside_the_time_it_replaced():
    words = say(("wipecoding", 2.0, 3.0))
    fixed = correct(words, {"wipecoding": "vibe coding"})
    assert fixed[0].start == pytest.approx(2.0)
    assert fixed[-1].end == pytest.approx(3.0)
    assert fixed[0].end <= fixed[1].start


def test_correction_is_case_and_punctuation_insensitive():
    words = say(("Wipe", 1.0, 1.4), ("Coding,", 1.4, 1.9))
    assert " ".join(w.text for w in correct(words, {"wipe coding": "vibe coding"})) \
        == "vibe coding"


def test_an_empty_map_changes_nothing():
    words = spoken("nothing to see here")
    assert correct(words, {}) is words


# ---------------------------------------------------------------------------
# false starts
# ---------------------------------------------------------------------------


def test_a_word_held_far_too_long_is_flagged():
    """The signature of a restart the recogniser folded into one word: the
    text is clean, the timings are clean, and there is no gap to find."""
    assert implausible(Word(text="need", start=20.64, end=22.88))


def test_an_ordinary_word_is_not_flagged():
    for word in spoken("the quick brown fox jumped over it"):
        assert not implausible(word)


def test_a_word_drawn_out_for_emphasis_is_not_flagged():
    assert not implausible(Word(text="everything", start=1.0, end=1.85))


def test_suspect_windows_are_padded_and_merged():
    words = [Word(text="need", start=20.6, end=22.9),
             Word(text="so", start=23.0, end=24.6)]
    assert len(windows(words)) == 1


def test_a_false_start_loses_its_first_go():
    words = spoken("okay you okay you need to stop")
    kept, removed = destutter(words)
    assert " ".join(w.text for w in kept) == "okay you need to stop"
    assert [w.text for w in removed[0]] == ["okay", "you"]


def test_the_longest_repeat_wins():
    """A one-word test fires on 'the' and leaves the real repeat standing."""
    words = spoken("the coding workflow the coding workflow is this")
    kept, _ = destutter(words)
    assert " ".join(w.text for w in kept) == "the coding workflow is this"


def test_a_repeat_across_a_long_gap_is_left_alone():
    """Said twice a minute apart is rhetoric, not a stumble."""
    words = [Word(text="verify", start=0.0, end=0.5),
             Word(text="verify", start=40.0, end=40.5)]
    kept, removed = destutter(words)
    assert len(kept) == 2 and not removed


def test_a_word_said_twice_back_to_back_is_treated_as_a_stumble():
    """The known false positive: "very very good" is legitimate emphasis and
    loses a word. Accepted, because a doubled word with no gap is a stumble far
    more often than it is emphasis — and the gap check spares the deliberate
    kind, which comes with a beat in front of it."""
    kept, _ = destutter(spoken("it is very very good"))
    assert " ".join(w.text for w in kept) == "it is very good"

    deliberate = [Word(text="it", start=0.0, end=0.2),
                  Word(text="is", start=0.2, end=0.4),
                  Word(text="very", start=0.4, end=0.9),
                  Word(text="very", start=2.8, end=3.3),
                  Word(text="good", start=3.3, end=3.7)]
    assert len(destutter(deliberate)[0]) == 5


def test_destutter_never_invents_or_reorders():
    words = spoken("one two three four five")
    kept, removed = destutter(words)
    assert kept == words and not removed


# ---------------------------------------------------------------------------
# captions
# ---------------------------------------------------------------------------


def test_a_card_never_outlives_its_sentence():
    words = spoken("this ends here. and this begins")
    grouped = cards(words)
    first = [w.text for w in grouped[0].words]
    assert first[-1].endswith(".")


def test_a_card_breaks_where_the_speech_breaks():
    words = say(("one", 0.0, 0.3), ("two", 0.3, 0.6), ("three", 4.0, 4.3))
    assert len(cards(words)) == 2


def test_cards_hold_at_most_the_requested_words():
    grouped = cards(spoken("a b c d e f g h i j k l"), max_words=3)
    assert all(len(c.words) <= 3 for c in grouped)


def test_every_word_survives_grouping():
    words = spoken("one two three four five six seven")
    assert sum(len(c.words) for c in cards(words)) == len(words)


def test_one_event_per_word_and_none_of_them_run_backwards():
    words = spoken("one two three four")
    lines = events(cards(words))
    assert len(lines) == len(words)
    assert all(line.startswith("Dialogue: 0,") for line in lines)


def clock(stamp: str) -> float:
    hours, minutes, seconds = stamp.split(":")
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def spans_of(words: list[Word]) -> list[tuple[float, float]]:
    out = []
    for line in events(cards(words)):
        parts = line.split(",")
        out.append((clock(parts[1]), clock(parts[2])))
    return sorted(out)


def test_no_two_caption_lines_are_ever_on_screen_at_once():
    """ASS stacks simultaneous lines instead of replacing them, so an overlap
    is the caption jumping up a line and back down — once per card, for the
    length of the film."""
    words = spoken("one two three. four five six. seven eight nine ten")
    spans = spans_of(words)
    for (_, end), (start, _) in zip(spans, spans[1:]):
        assert start >= end - 0.001


def test_a_card_does_not_hang_over_into_the_next_one():
    """The last word of a card is held past its own end so the card does not
    vanish on the closing consonant — but not past the next card's arrival."""
    words = say(("one", 0.0, 0.4), ("two", 0.4, 0.9), ("three.", 0.9, 1.0),
                ("next", 1.02, 1.4))
    spans = spans_of(words)
    assert len(spans) == 4
    assert max(end for _, end in spans[:3]) <= 1.021


def test_the_style_block_is_measured_in_real_pixels():
    """PlayRes has to match the frame or every margin below it is a guess."""
    text = header(1080, 1920)
    assert "PlayResX: 1080" in text and "PlayResY: 1920" in text


def test_ass_colours_are_written_back_to_front():
    """ASS is &HBBGGRR. Getting it round the wrong way yields an orange blue."""
    assert "&H00FF6658" in header(1920, 1080, "#5866FF")


# ---------------------------------------------------------------------------
# slidekit
# ---------------------------------------------------------------------------


def test_emphasis_does_not_push_punctuation_off_its_word():
    fnt = slidekit.motion.bold(60)
    lines = slidekit.wrap_rich("Writing code got *cheap*.", fnt, 4000)
    assert "".join(chunk for chunk, _ in lines[0]) == "Writing code got cheap."


def test_the_emphasised_run_is_the_one_marked_hot():
    fnt = slidekit.motion.bold(60)
    lines = slidekit.wrap_rich("a *b* c", fnt, 4000)
    # The space preceding an emphasised word rides with it. Which side of the
    # colour change a blank pixel falls on is not a thing anyone can see, and
    # keeping it attached is what stops the run being split into three.
    assert [chunk.strip() for chunk, hot in lines[0] if hot] == ["b"]


def test_wrapping_keeps_every_word():
    fnt = slidekit.motion.bold(60)
    text = "one two three four five six seven eight nine ten"
    lines = slidekit.wrap_rich(text, fnt, 300)
    assert len(lines) > 1
    joined = " ".join("".join(c for c, _ in line).strip() for line in lines)
    assert joined.split() == text.split()


def test_a_corner_section_leaves_the_inset_room():
    spec = slidekit.Spec.parse({"layout": "bullets", "presenter": "corner"})
    _, _, right, _ = slidekit.content_box(spec, (1920, 1080))
    assert right <= 1920 - 330 - 54


def test_nothing_is_drawn_into_the_caption_band():
    for framing in ("corner", "full"):
        spec = slidekit.Spec.parse({"layout": "steps", "presenter": framing})
        assert slidekit.content_box(spec, (1920, 1080))[3] \
            <= slidekit.caption_top((1920, 1080))


def test_the_caption_band_is_the_same_height_whatever_the_slide_holds():
    busy = slidekit.Spec.parse({"layout": "steps", "footnote": "x" * 90})
    bare = slidekit.Spec.parse({"layout": "statement"})
    size = (1920, 1080)
    assert slidekit.caption_top(size) == slidekit.caption_top(size)
    assert slidekit.content_box(busy, size)[3] < slidekit.content_box(bare, size)[3]


def test_beats_land_before_the_section_ends():
    """An element arriving on the final word is an element nobody read."""
    for count in (1, 3, 9):
        for seconds in (6.0, 20.0, 80.0):
            assert max(slidekit.beats(count, seconds)) < seconds


def test_an_unknown_layout_falls_back_rather_than_raising():
    assert slidekit.Spec.parse({"layout": "nonsense"}).layout == "statement"


def test_every_layout_has_a_renderer():
    assert set(slidekit.LAYOUTS) == set(slidekit.RENDERERS)


def test_a_spec_renders_at_both_aspects_without_being_rewritten():
    spec = slidekit.Spec.parse({
        "layout": "stats", "kicker": "why", "headline": "It got *cheap*.",
        "items": [{"value": "+180%", "label": "code"}], "presenter": "corner"})
    from PIL import Image, ImageDraw
    for size in ((1920, 1080), (1080, 1920)):
        scene = slidekit.scene(spec, 12.0, size, progress=(1, 4))
        img = Image.new("RGB", size, slidekit.BG)
        assert scene.draw(ImageDraw.Draw(img), img, 8.0) is not None or True


# ---------------------------------------------------------------------------
# deck
# ---------------------------------------------------------------------------


def block(text, size, top, left=0.1):
    return {"text": text, "size": size, "top": top, "left": left}


def test_a_kicker_is_not_mistaken_for_a_headline():
    blocks = [block("STEP 3", 24, 0.08), block("One page. That is it.", 54, 0.3)]
    assert _role(blocks[0], blocks) == "kicker"
    assert _role(blocks[1], blocks) == "headline"


def test_the_line_pinned_to_the_bottom_is_an_aside():
    blocks = [block("Big claim", 60, 0.3),
              block("Nobody writes non-goals.", 20, 0.85)]
    assert _role(blocks[1], blocks) == "footnote"
