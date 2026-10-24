"""Fast tests for presenter mode. No ffmpeg, no takes, no render.

The expensive half of `present` is ffmpeg calls, and those are covered by using
them. What is worth pinning here is the quiet logic that decides what gets
built: profile validation, how a take file is matched to a section, and the
layout arithmetic that keeps a slide clear of the presenter inset.

That last one is the reason this file exists. A slide drawing its right-hand
column underneath the circular inset is invisible until after the composite --
by which point the slide has already been rendered at its take's length, and
the mistake looks like a rendering bug rather than a layout one.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from demoforge.present import (  # noqa: E402
    ASPECTS,
    Profile,
    Section,
    find_take,
    load,
    write_script,
)


def make_section(**kwargs) -> Section:
    base = {"id": "01_x", "say": "one two three four five"}
    base.update(kwargs)
    return Section(**base)


def make_profile(tmp_path: Path, sections: list[dict], **top) -> Path:
    payload = {"title": "t", "sections": sections}
    payload.update(top)
    (tmp_path / "presentation.json").write_text(json.dumps(payload), encoding="utf-8")
    return tmp_path


# ---------------------------------------------------------------------------
# the profile
# ---------------------------------------------------------------------------


def test_word_count_ignores_punctuation():
    assert make_section(say="one, two -- three!").words == 3


def test_estimate_scales_with_length():
    short = make_section(say=" ".join(["w"] * 25)).estimate
    long = make_section(say=" ".join(["w"] * 50)).estimate
    assert long == pytest.approx(short * 2)


def test_unknown_framing_is_rejected():
    with pytest.raises(ValueError, match="presenter="):
        make_section(presenter="hologram").validate()


def test_unknown_visual_kind_is_rejected():
    with pytest.raises(ValueError, match="expected one of"):
        make_section(visual_kind="interpretive dance").validate()


def test_a_section_with_neither_presenter_nor_visual_is_refused():
    """Otherwise it renders as a black screen with a voice over it."""
    with pytest.raises(ValueError, match="black screen"):
        make_section(presenter="off", visual_kind="none").validate()


def test_duplicate_ids_are_caught_before_anything_renders(tmp_path):
    directory = make_profile(tmp_path, [
        {"id": "a", "say": "one"},
        {"id": "a", "say": "two"},
    ])
    with pytest.raises(SystemExit, match="duplicate section ids"):
        load(str(directory))


def test_a_missing_profile_says_where_it_looked(tmp_path):
    with pytest.raises(SystemExit, match="presentation.json"):
        load(str(tmp_path))


def test_defaults_are_applied(tmp_path):
    profile = load(str(make_profile(tmp_path, [{"id": "a", "say": "one two"}])))
    section = profile.sections[0]
    assert section.presenter == "corner"
    assert section.visual_kind == "slide"
    assert section.visual_name == "a"       # defaults to the section id
    assert profile.aspect == "16:9"


def test_every_aspect_has_even_dimensions():
    """h264 refuses odd dimensions, and the failure is a wall of ffmpeg output."""
    for name, (w, h) in ASPECTS.items():
        assert w % 2 == 0 and h % 2 == 0, name


def test_profile_estimate_is_the_sum_of_its_sections(tmp_path):
    profile = load(str(make_profile(tmp_path, [
        {"id": "a", "say": " ".join(["w"] * 25)},
        {"id": "b", "say": " ".join(["w"] * 50)},
    ])))
    assert profile.estimate == pytest.approx(sum(s.estimate for s in profile.sections))


# ---------------------------------------------------------------------------
# finding takes
# ---------------------------------------------------------------------------


def test_a_take_is_found_by_exact_name(tmp_path):
    profile = Profile("p", "t", [make_section()], directory=tmp_path)
    profile.takes.mkdir()
    (profile.takes / "01_x.mp4").write_bytes(b"")
    assert find_take(profile, profile.sections[0]).name == "01_x.mp4"


def test_any_container_is_accepted(tmp_path):
    profile = Profile("p", "t", [make_section()], directory=tmp_path)
    profile.takes.mkdir()
    (profile.takes / "01_x.mov").write_bytes(b"")
    assert find_take(profile, profile.sections[0]).suffix == ".mov"


def test_a_cameras_own_prefix_is_tolerated(tmp_path):
    """Phones and cameras name files themselves; renaming twelve of them is a
    step people skip, and skipping it should not read as a missing take."""
    profile = Profile("p", "t", [make_section()], directory=tmp_path)
    profile.takes.mkdir()
    (profile.takes / "IMG_4821_01_x.mp4").write_bytes(b"")
    assert find_take(profile, profile.sections[0]).name == "IMG_4821_01_x.mp4"


def test_a_missing_take_is_none_not_an_error(tmp_path):
    profile = Profile("p", "t", [make_section()], directory=tmp_path)
    profile.takes.mkdir()
    assert find_take(profile, profile.sections[0]) is None


def test_unrelated_files_are_not_matched(tmp_path):
    profile = Profile("p", "t", [make_section()], directory=tmp_path)
    profile.takes.mkdir()
    (profile.takes / "notes.txt").write_text("x", encoding="utf-8")
    (profile.takes / "02_y.mp4").write_bytes(b"")
    assert find_take(profile, profile.sections[0]) is None


# ---------------------------------------------------------------------------
# the script
# ---------------------------------------------------------------------------


def test_the_script_carries_the_words_and_the_direction(tmp_path):
    directory = make_profile(tmp_path, [
        {"id": "01_hook", "say": "the words to say", "note": "down the lens",
         "presenter": "full", "visual": {"kind": "none"}},
    ])
    text = write_script(load(str(directory))).read_text(encoding="utf-8")
    assert "the words to say" in text
    assert "down the lens" in text
    assert "01_hook" in text
    assert "FULL FRAME" in text


def test_the_script_names_the_takes_directory(tmp_path):
    directory = make_profile(tmp_path, [{"id": "a", "say": "one two"}])
    profile = load(str(directory))
    assert str(profile.takes) in write_script(profile).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# staying clear of the presenter inset
# ---------------------------------------------------------------------------


def deck():
    """The bundled probeit deck, which is where the layout helpers live."""
    import importlib.util

    path = Path(__file__).resolve().parents[1] / "projects" / "probeit" / "slides.py"
    spec = importlib.util.spec_from_file_location("probeit_slides", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_reserved_corner_matches_where_compose_puts_the_inset():
    """`pip_box` duplicates a constant from `present.presenter_corner`.

    If they drift, slides reserve the wrong rectangle and the collision is only
    visible after the composite -- so the duplication is pinned here rather
    than trusted.
    """
    w, h = 1920, 1080
    size = int(min(w, h) * 0.31)
    assert deck().pip_box(w, h) == (w - size - 56, h - size - 56)


def test_a_band_above_the_inset_keeps_the_full_width():
    module = deck()
    edge = module.right_edge(1920, 1080, {"presenter": "corner"}, 200, 400)
    assert edge == 1920 - int(1920 * 0.07)


def test_a_band_overlapping_the_inset_stops_short_of_it():
    module = deck()
    pip_x, _ = module.pip_box(1920, 1080)
    edge = module.right_edge(1920, 1080, {"presenter": "corner"}, 700, 900)
    assert edge < pip_x


def test_no_inset_means_no_reservation():
    module = deck()
    for framing in ({"presenter": "off"}, {"presenter": "full"}, {}):
        assert module.right_edge(1920, 1080, framing, 700, 900) == 1920 - int(1920 * 0.07)


def test_row_pitch_is_bounded_at_both_ends():
    """Floored so rows never overlap, capped so a tall frame does not give
    four thin bands of text floating in four large empty rectangles."""
    module = deck()
    assert module.pitch(1080, 200, 20) == 80          # floor
    assert module.pitch(1920, 200, 4) == 230          # cap
    assert 80 < module.pitch(1080, 200, 4) < 230      # neither


def test_every_named_slide_is_dispatchable():
    module = deck()
    assert set(module.SLIDES) == {
        "leak", "control", "ladder", "always_works",
        "matched", "result", "bug", "power",
    }


def test_an_unknown_slide_lists_what_is_available(tmp_path):
    module = deck()
    with pytest.raises(SystemExit, match="Available:"):
        module.render("nope", 1.0, tmp_path / "x.mp4", (1920, 1080), {})
