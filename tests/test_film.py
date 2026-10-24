"""Fast tests for film mode. No ffmpeg, no whisper, no GPU, no network.

Film mode's expensive half is ffmpeg, whisper and a headless Chrome, and those
are covered by the acceptance run against the finished pitch film. What is
pinned here is the arithmetic between them, every piece of which shows up only
as a flaw in a four-minute render:

- the spine's envelope trim: a mistake is a clipped word on every line
- caption alignment and retiming: a mistake desynchronises every caption after it
- scene anchoring: a scene that starts a frame late shows the previous line's lips
- SFX placement: a whoosh whose peak misses the cut sounds like a mistake
- dark-frame detection: one black frame is all a viewer needs to see
- config validation: a typo in film.json should fail before a 30-minute render
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from demoforge.film import (
    camscene,
    captions,
    mix,
    project,
    qa,
    root,
    spine,
    thumbs,
    timeline,
)
from demoforge.film.decode import repeated

SR, FPS = 48000, 30


def make(tmp: Path, **over) -> project.Project:
    cfg = project.merge(project.DEFAULTS, {"name": "t", **over})
    return project.Project(dir=tmp, cfg=cfg, work=tmp / "work", film=tmp / "film", emit=tmp / "film")


# -- spine ---------------------------------------------------------------------


def burst(on: float, off: float, dur: float = 2.0, floor: float = 0.001) -> np.ndarray:
    rng = np.random.default_rng(1)
    a = rng.normal(0, floor, int(dur * SR)).astype(np.float32)
    t = np.arange(len(a)) / SR
    a[(t >= on) & (t < off)] += 0.3 * np.sin(2 * np.pi * 220 * t[(t >= on) & (t < off)])
    return np.stack([a, a], 1)


def test_speech_span_finds_the_burst_to_5ms():
    step = SR // 200
    on, off = spine.speech_span(spine.envelope(burst(0.5, 1.3), step), step, SR)
    assert abs(on - 0.5) <= 0.005 and abs(off - 1.3) <= 0.005


def test_speech_span_ignores_room_tone():
    step = SR // 200
    with pytest.raises(ValueError):
        spine.speech_span(spine.envelope(burst(0, 0), step), step, SR)


def test_frames_round_outward():
    assert project.frame(0.401, FPS, up=True) == pytest.approx(13 / 30)
    assert project.frame(0.433, FPS, up=False) == pytest.approx(12 / 30)
    assert project.frame(0.4, FPS, up=True) == pytest.approx(0.4)  # already on a frame
    assert project.snap(1.02, FPS) == pytest.approx(1.0333)


def test_remove_span_cuts_exactly_the_span():
    seg = np.ones((SR, 2), np.float32)
    out = spine.remove_span(seg, 10000, 20000, 576)
    assert len(out) == SR - 10000


# -- captions ------------------------------------------------------------------


HEARD = [{"w": "So", "s": 1.0, "e": 1.2}, {"w": "we", "s": 1.2, "e": 1.4},
         {"w": "raised", "s": 1.5, "e": 1.9}, {"w": "291", "s": 2.0, "e": 2.4},
         {"w": "million.", "s": 2.4, "e": 2.9}]


def test_align_matches_and_interpolates():
    toks = ["So", "we", "raised", "$291", "million."]
    times = captions.align(toks, HEARD, 0.9, 3.0, spoken={"$291": "291"})
    assert times[3] == (2.0, 2.4)
    # without the spoken form, "$291" borrows the gap between its neighbours
    times = captions.align(toks, HEARD, 0.9, 3.0)
    assert times[3] == (1.9, 2.4)


def test_split_breaks_on_punctuation_and_length():
    toks = ["Hi,", "I'm", "Sarthak.", "I'm", "an", "engineer", "and", "an", "operator,", "and", "I", "think"]
    times = [(i * 0.3, i * 0.3 + 0.25) for i in range(len(toks))]
    cues = captions.split("0002", toks, times, max_chars=34, max_words=7)
    assert cues[0]["text"] == "Hi, I'm Sarthak."
    assert all(len(c["text"]) <= 34 for c in cues)
    assert " ".join(c["text"] for c in cues) == " ".join(toks)


def test_hold_never_overlaps_the_next_cue():
    cues = [{"text": "a", "s": 0.0, "e": 1.0}, {"text": "b", "s": 1.2, "e": 2.0}]
    captions.hold(cues, [1.0, 2.0], 0.6, 0.03)
    assert cues[0]["e"] == pytest.approx(1.17) and cues[1]["e"] == pytest.approx(2.6)


def test_clipped_guard():
    assert captions.clipped(["So", "we", "go."], ["we", "go"])
    assert not captions.clipped(["So", "we", "go."], ["so", "we", "go"])


def test_srt_time():
    assert captions.srt_time(3725.4) == "01:02:05,400"


def test_retime_moves_each_word_by_its_lines_shift():
    old = {"clips": [{"seq": "0001", "start": 0.4, "end": 2.0, "src_in": 0.1},
                     {"seq": "0002", "start": 2.3, "end": 4.0, "src_in": 0.2}]}
    new = {"clips": [{"seq": "0001", "start": 0.4, "end": 2.0, "src_in": 0.1},
                     {"seq": "0002", "start": 2.6, "end": 4.3, "src_in": 0.1}]}  # later, and trimmed earlier
    words = [{"seq": "0001", "w": "a", "s": 0.5, "e": 1.0}, {"seq": "0002", "w": "b", "s": 2.5, "e": 3.0}]
    cues = [{"seq": "0001", "text": "a", "s": 0.5, "e": 1.6}, {"seq": "0002", "text": "b", "s": 2.5, "e": 3.6}]
    w, c, notes = captions.retime(old, new, words, cues)
    assert w[0]["s"] == 0.5 and w[1]["s"] == pytest.approx(2.9)  # +0.3 placement, +0.1 trim
    assert c[1]["s"] == pytest.approx(2.9) and c[1]["e"] == pytest.approx(4.0)
    assert words[1]["s"] == 2.5  # inputs untouched
    assert not notes


# -- timeline ------------------------------------------------------------------


SPINE = {"duration": 10.0, "clips": [
    {"seq": "0001", "start": 0.4, "end": 4.0, "src_in": 0, "src_out": 3.6, "cam": None},
    {"seq": "0002", "start": 4.3, "end": 9.0, "src_in": 0, "src_out": 4.7, "cam": "c-0002.mp4"}]}
WORDS = [{"seq": "0001", "w": "One", "s": 0.4, "e": 0.8}, {"seq": "0001", "w": "and", "s": 1.0, "e": 1.1},
         {"seq": "0001", "w": "two,", "s": 2.0, "e": 2.3}, {"seq": "0001", "w": "and", "s": 3.0, "e": 3.1},
         {"seq": "0002", "w": "Three.", "s": 4.3, "e": 4.9}]


def test_anchor_line_word_and_nth():
    clips = {c["seq"]: c for c in SPINE["clips"]}
    assert timeline.anchor("0002", clips, WORDS) == 4.3
    assert timeline.anchor("0001@two", clips, WORDS) == pytest.approx(1.88)
    assert timeline.anchor("0001@and#2", clips, WORDS) == pytest.approx(2.88)
    with pytest.raises(KeyError):
        timeline.anchor("0001@and#3", clips, WORDS)


def test_scenes_tile_the_film_on_frames():
    table = [{"id": "s01", "kind": "anim", "at": "0001"}, {"id": "s02", "kind": "anim", "at": "0001@two"},
             {"id": "s03", "kind": "cam", "at": "0002"}]
    rows = timeline.scenes(table, SPINE, WORDS, FPS)
    assert [r["end"] for r in rows[:-1]] == [r["start"] for r in rows[1:]]
    assert rows[-1]["end"] == 10.0
    for r in rows:
        assert abs(r["start"] * FPS - round(r["start"] * FPS)) < 1e-3
    assert rows[1]["words"][0] == {"w": "two,", "s": round(2.0 - rows[1]["start"], 3), "e": round(2.3 - rows[1]["start"], 3)}
    assert rows[2]["lines"][0]["cam"] == "c-0002.mp4"


# -- root and transitions ------------------------------------------------------


def test_joins_and_root_html(tmp_path):
    p = make(tmp_path, title="T", joins={"s01": "shatter"}, sfx={"whip": ["whoosh-fast", None, -6]})
    scenes = [{"id": "s01", "start": 0.0, "duration": 2.0}, {"id": "s02", "start": 2.0, "duration": 3.0},
              {"id": "s03", "start": 5.0, "duration": 1.0}]
    js = root.joins(p, scenes)
    assert js == [{"t": 2.0, "out": "s01", "in": "s02", "kind": "shatter"},
                  {"t": 5.0, "out": "s02", "in": "s03", "kind": "cut"}]
    page = root.html(p, scenes, 6.0, js, [])
    assert '"s01": {"color": "assets/fx/s01_frozen.png"' in page
    assert "immediateRender: false" in page and "function shatter" in page
    assert 'data-composition-src="scenes/s03/index.html"' in page
    assert "__IMPACT__" not in page
    # the leak's outgoing host only scales: a filter there drops a black frame over video
    leak = page.split('case "leak"')[1].split("break;")[0]
    assert "tl.to(o, { scale: 1.12" in leak and "filter" not in leak.split("tl.to(o,")[1].split(")")[0]


def test_cue_words_fall_back_to_even_spacing():
    cues = [{"s": 1.0, "e": 2.0, "text": "a b"}]
    out = root.cue_words(cues, [{"w": "a", "s": 1.0}])
    assert out[0]["w"] == [["a", 1.0], ["b", 1.5]]


# -- mix -----------------------------------------------------------------------


def test_sfx_placement_peaks_on_the_cut():
    manifest = {"whoosh": {"peak_at": 0.465}, "hit": {"peak_at": 0.0}, "debris": {"peak_at": 0.2}}
    sfx = {"whip": ["whoosh", None, -6], "shatter": [["hit", -0.9, 2], ["debris", 0.0, -10]]}
    joins = [{"t": 10.0, "kind": "whip"}, {"t": 20.0, "kind": "shatter"}, {"t": 30.0, "kind": "cut"}]
    scenes = [{"id": "s01", "start": 5.0}]
    got = mix.placements(scenes, {"s01": [{"t": 1.0, "sfx": "hit"}]}, joins, sfx, manifest)
    assert got[0] == ("hit", 6.0, -6.0)
    assert got[1] == ("whoosh", pytest.approx(10.0 - 0.465), -6)
    assert got[2] == ("hit", pytest.approx(19.1), 2) and got[3] == ("debris", 20.0, -10)
    assert len(got) == 4


def test_lay_clips_at_both_ends():
    bus = np.zeros((100, 2), np.float32)
    mix.lay(bus, np.ones((40, 2), np.float32), -10 / SR, 0.0, SR)
    mix.lay(bus, np.ones((40, 2), np.float32), 80 / SR, 0.0, SR)
    assert bus[:30].sum() == 60 and bus[30:80].sum() == 0 and bus[80:].sum() == 40


# -- qa ------------------------------------------------------------------------


def test_dark_frame_is_found_and_a_fade_is_not():
    y = np.full(60, 120.0)
    y[20] = 15.0                       # a dropped frame
    y[40:46] = [100, 70, 40, 15, 40, 80]  # a dip to black
    y[50] = 8.0                        # and one at the very edge of a cut
    y[51:] = 60.0
    assert qa.dark_frames(y) == [20, 50]


def test_blackout_is_a_one_frame_drop_not_a_dip():
    y = np.array([105, 105, 3, 2, 7, 27, 65, 105] + [105, 80, 50, 25, 10, 5, 3, 20, 60, 105], float)
    assert qa.blackouts(y) == [2]


def test_edge_speech_flags_a_clipped_start():
    a = burst(0.0, 0.6, dur=1.0)
    rows = qa.edge_speech(a, [{"seq": "0001", "start": 0.0, "end": 1.0}], SR)
    assert rows[0]["clipped_head"] and not rows[0]["clipped_tail"]


def test_caption_gaps():
    words = [{"seq": "0001", "w": "a", "s": 1.0}, {"seq": "0001", "w": "b", "s": 3.0}]
    cues = [{"text": "a", "s": 0.9, "e": 1.5}, {"text": "x", "s": 1.4, "e": 2.0}]
    g = qa.caption_gaps(words, cues)
    assert g["uncovered"] == ["0001 b @3.0"] and g["overlapping"] == [("a", "x")]


# -- decode, thumbs ------------------------------------------------------------


def test_repeated_frames_share():
    rng = np.random.default_rng(0)
    frames = [rng.integers(0, 255, (64, 64), np.uint8) for _ in range(10)]
    assert repeated(frames) == 0
    assert repeated([frames[0]] * 5 + frames[1:6]) == pytest.approx(4 / 9)


def test_thumb_pick_keeps_spacing():
    rows = [{"t": 1.0, "total": 0.9}, {"t": 1.5, "total": 0.8}, {"t": 4.0, "total": 0.7}]
    assert [r["t"] for r in thumbs.pick(rows, 3, 2.0)] == [1.0, 4.0]


def test_thumb_score_prefers_open_eyes_closed_mouth():
    good = thumbs.score({"eyes": 0.3, "mouth": 0.0, "yaw": 0.0, "cx": 0.5, "sharp": 1.0})
    blink = thumbs.score({"eyes": 0.05, "mouth": 0.05, "yaw": 0.06, "cx": 0.7, "sharp": 0.2})
    assert good["total"] > 0.95 > blink["total"]


def test_candidates_only_in_camera_scenes():
    scenes = [{"kind": "anim", "start": 0, "end": 5}, {"kind": "cam", "start": 5, "end": 6.8}]
    t = thumbs.candidates(scenes, {"cam"}, step=0.5)
    assert t == [5.4, 5.9]


# -- camera scenes ---------------------------------------------------------------


def test_overlay_slots_survive_regeneration():
    old = ("/* OVERLAY-CSS-BEGIN */\n#s02-x { color: red; }\n      /* OVERLAY-CSS-END */\n"
           "<!-- OVERLAY-FRONT-BEGIN -->\n<div id=\"s02-x\"></div>\n<!-- OVERLAY-FRONT-END -->\n")
    assert camscene.keep(old, "OVERLAY-CSS") == "#s02-x { color: red; }"
    assert camscene.keep(old, "OVERLAY-FRONT") == '<div id="s02-x"></div>'
    assert camscene.keep(old, "OVERLAY-JS") == ""


def test_own_lines():
    sc = {"start": 4.0, "end": 9.0, "lines": [
        {"seq": "0001", "start": 0.4, "cam": "a"}, {"seq": "0002", "start": 4.3, "cam": "b"},
        {"seq": "0003", "start": 5.0, "cam": None}]}
    assert [l["seq"] for l in camscene.own_lines(sc)] == ["0002"]


# -- config --------------------------------------------------------------------


def test_validate_catches_the_usual_typos():
    cfg = project.merge(project.DEFAULTS, {
        "scenes": [{"id": "s01", "kind": "anim", "at": "0001"}, {"id": "s02", "kind": "cam-bw", "at": "1@"}],
        "joins": {"s01": "wipe", "s09": "cut"},
        "spine": {"tail": 0.05},
        "sfx": {"whip": ["whoosh", "x", -6]},
        "music": {"sections": [{"track": "a.mp3", "track_at": 0, "start": "0001+", "end": "end"}]},
    })
    errors, warnings = project.validate(cfg)
    text = "\n".join(errors)
    assert "joins.s01" in text and "joins.s09: no such scene" in text
    assert "s02: at '1@'" in text and "sfx.whip" in text and "music.sections[0].start" in text
    assert any("never every tail" in w for w in warnings)
    assert any("kind 'cam-bw' has no look" in w for w in warnings)


def test_the_pitch_film_config_is_valid():
    path = Path(__file__).resolve().parents[1] / "projects" / "pitch-film" / "film.json"
    if not path.exists():
        pytest.skip("no pitch film in this checkout")
    cfg = project.merge(project.DEFAULTS, project.strip_comments(json.loads(path.read_text(encoding="utf-8"))))
    errors, _ = project.validate(cfg)
    assert errors == []
    assert all(not k.startswith("_") for k in cfg["spine"]["gap_after"])


def test_edges_for_music():
    clips = {"0009": {"start": 58.73, "end": 61.0}}
    assert project.edge("0009+0.6", clips, 100) == pytest.approx(59.33)
    assert project.edge("0009-0.3", clips, 100) == pytest.approx(58.43)
    assert project.edge("0009.end", clips, 100) == 61.0
    assert project.edge("end", clips, 100) == 100 and project.edge(0.0, clips, 100) == 0.0


def test_merge_replaces_film_tables():
    cfg = project.merge(project.DEFAULTS, {"looks": {"cam-x": {"plate": "none"}}, "spine": {"gap": 0.5}})
    assert list(cfg["looks"]) == ["cam-x"]          # not merged with the default "cam" look
    assert cfg["spine"]["gap"] == 0.5 and cfg["spine"]["lead"] == 0.10


def test_new_project_loads(tmp_path):
    from demoforge.film import scaffold
    d = scaffold.new(str(tmp_path / "myfilm"))
    p = project.load(d)
    assert p.name == "myfilm" and (d / "film" / "lib" / "kit.css").exists()
    assert (d / "film" / "scenes" / "s01" / "assets" / "fonts").exists()  # the junction resolves


def test_cli_registers_film():
    import argparse

    from demoforge.film import cli
    ap = argparse.ArgumentParser()
    cli.add_subparser(ap.add_subparsers(dest="cmd"))
    args = ap.parse_args(["film", "retime", "--project", "x", "--from", "spine.v1.json"])
    assert args.action == "retime" and args.baseline == "spine.v1.json" and args.fn is cli.run
