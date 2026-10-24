"""The app, minus the window and minus ffmpeg.

What is worth testing here is the table that drives the whole UI: every
mode's steps point at artifacts that exist, every substitution in an argv can
be filled from a profile, and a project folder is recognised as the mode it
is. Those are the things that would otherwise fail only when somebody clicks
the button.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from demoforge.app import catalog


def test_every_step_refers_to_declared_artifacts():
    for mode in catalog.MODES.values():
        keys = {a.key for a in mode.artifacts}
        for step in mode.steps:
            for k in step.needs + step.makes:
                assert k in keys, f"{mode.key}.{step.key} refers to unknown artifact {k}"
        assert mode.output in keys, f"{mode.key} has no deliverable artifact"


def test_every_argv_placeholder_is_a_field_or_builtin():
    import re
    for mode in catalog.MODES.values():
        fields = {f.key for f in mode.fields} | {"project", "project_dir", "out_dir"}
        for step in mode.steps:
            for token in step.argv + [t for group in step.optional for t in group]:
                for name in re.findall(r"\{(\w+)\}", token):
                    assert name in fields, f"{mode.key}.{step.key} uses {{{name}}}"


def test_field_kinds_are_ones_the_form_can_draw():
    known = {"text", "textarea", "number", "bool", "select", "path", "paths", "folder",
             "color", "list", "corrections", "cards", "sections", "repairs", "json"}
    for mode in catalog.MODES.values():
        for f in mode.fields:
            assert f.kind in known, f"{mode.key}.{f.key}: {f.kind}"
            if f.kind in ("select", "color"):
                assert f.options, f"{mode.key}.{f.key} has no options"
                if f.default is not None:
                    assert f.default in f.options


def test_public_catalog_is_json():
    json.dumps(catalog.public())


def test_detect_by_profile_file(tmp_path: Path):
    (tmp_path / "reel.json").write_text("{}")
    assert catalog.detect(tmp_path) is catalog.REEL
    (tmp_path / "short.json").write_text("{}")
    assert catalog.detect(tmp_path) is catalog.SHORT     # newest mode wins
    empty = tmp_path / "empty"
    empty.mkdir()
    assert catalog.detect(empty) is None
    (empty / "scenes.py").write_text("")
    assert catalog.detect(empty) is catalog.DEMO


def test_defaults_skip_unset():
    d = catalog.defaults(catalog.SHORT)
    assert d["face"] == "bold" and "title" not in d


@pytest.fixture
def server(tmp_path: Path, monkeypatch):
    from demoforge.app import server as srv
    monkeypatch.setattr(srv, "SETTINGS", tmp_path / "settings.json")
    srv.save_settings({"projects_dir": str(tmp_path / "projects"),
                       "out_dir": str(tmp_path / "out")})
    return srv


def test_slug():
    from demoforge.app.server import slug
    assert slug("5 Signs Your AI Agent Isn't Ready!") == "5-signs-your-ai-agent-isn-t-ready"
    assert slug("") == "video"


def test_create_project_and_argv(server):
    directory = server.create_project(
        catalog.SHORT, "smoke", {"title": "Smoke", "background": "clip.mp4"})
    profile = json.loads((directory / "short.json").read_text())
    assert profile["face"] == "bold" and profile["background"] == "clip.mp4"

    argv = server.build_argv(catalog.SHORT, catalog.SHORT.step("build"), "smoke",
                             directory, profile, {})
    assert argv[-4:] == ["short", "build", "--project", "smoke"]

    argv = server.build_argv(catalog.REEL, catalog.REEL.step("plan"), "smoke",
                             directory, {}, {"from_cut": True})
    assert argv[-2] == "--from" and argv[-1].endswith("cut.json")

    argv = server.build_argv(catalog.REEL, catalog.REEL.step("cover"), "smoke",
                             directory, {}, {"line": ["Stop.", "*Go.*"], "at": 1.5})
    assert argv.count("--line") == 2 and "--at" in argv


def test_create_project_refuses_duplicates(server):
    server.create_project(catalog.SHORT, "twice", {"title": "x", "background": "b"})
    with pytest.raises(Exception):
        server.create_project(catalog.SHORT, "twice", {"title": "x", "background": "b"})


def test_missing_placeholder_is_a_client_error(server, tmp_path):
    from fastapi import HTTPException
    with pytest.raises(HTTPException):
        server.build_argv(catalog.DEMO, catalog.DEMO.step("plan"), "d", tmp_path, {}, {})


def test_an_optional_flag_drops_out_when_its_field_is_blank(server, tmp_path):
    voice = catalog.DEMO.step("voice")
    argv = server.build_argv(catalog.DEMO, voice, "d", tmp_path,
                             {"pace": 0.85, "voice_clip": ""}, {})
    assert "--src" not in argv
    argv = server.build_argv(catalog.DEMO, voice, "d", tmp_path,
                             {"pace": 0.85, "voice_clip": "me.mp3"}, {})
    assert argv[argv.index("--src") + 1] == "me.mp3"


def test_a_blank_required_field_is_a_client_error(server, tmp_path):
    """`face` needs --src; a blank clip must stop here, not as an argparse
    usage dump in the job log."""
    from fastapi import HTTPException
    with pytest.raises(HTTPException, match="face_clip"):
        server.build_argv(catalog.DEMO, catalog.DEMO.step("face"), "d", tmp_path,
                          {"face_clip": ""}, {})


# ---------------------------------------------------------------------------
# every button is a command the CLI accepts
# ---------------------------------------------------------------------------


class _Parsed(Exception):
    """Raised in place of running a command, once its parser has accepted it."""


def _plausible(f: catalog.Field) -> object:
    """A value a person might have typed, for fields whose default is blank."""
    if f.default not in (None, "", [], {}):
        return f.default
    return {"path": "clip.mp4", "paths": ["a.mp4"], "folder": "repo",
            "list": ["One *two*"], "bool": True, "number": 1.5,
            "corrections": {"wipe": "vibe"}}.get(f.kind, "words")


# Commands whose `cmd_*` only rebuilds argv for a module's own parser before
# anything runs. The rest (voice, face, build, music) do work before or
# instead of a second parse, so they are checked against the top level only.
_DISPATCH = {"edit", "reel", "short", "present", "tool", "plan"}


def _accepts(argv: list[str], monkeypatch) -> None:
    """Parse `argv` the way `demoforge` would, without running it: the top
    level, then the mode's own parser that `cmd_*` hands it on to."""
    import argparse
    import sys

    from demoforge import cli

    shown = " ".join(argv)
    try:
        args = cli.build_parser().parse_args(argv)
    except SystemExit:
        pytest.fail(f"demoforge refuses: {shown}")
    if args.cmd not in _DISPATCH:
        return

    real = argparse.ArgumentParser.parse_args

    def parse_then_stop(self, *a, **k):
        real(self, *a, **k)
        raise _Parsed

    with monkeypatch.context() as m:
        m.setattr(argparse.ArgumentParser, "parse_args", parse_then_stop)
        m.setattr(sys, "argv", list(sys.argv))     # `plan` rewrites it
        try:
            args.fn(args)
        except _Parsed:
            return
        except SystemExit:
            pytest.fail(f"demoforge {args.cmd} refuses what the CLI passed it: {shown}")
    pytest.fail(f"{shown} ran without reaching a parser")


def test_every_step_and_tool_argv_is_accepted_by_the_cli(server, tmp_path, monkeypatch):
    """The catalog and the CLI are written separately; this is where they meet.

    Every step is rendered with plausible values, once with its options at
    their defaults and once with every option set, and handed to the real
    parsers. A button whose command the CLI does not know is otherwise found
    by clicking it."""
    for mode in catalog.MODES.values():
        profile = {f.key: _plausible(f) for f in mode.fields}
        for step in mode.steps:
            for options in ({}, {o.key: _plausible(o) for o in step.options}):
                argv = server.build_argv(mode, step, "p", tmp_path, profile, options)
                _accepts(argv[argv.index("demoforge.cli") + 1:], monkeypatch)

    (tmp_path / "clip.mp4").write_bytes(b"")
    for tool in catalog.TOOLS.values():
        options = {f.key: _plausible(f) for f in tool.fields}
        options = {k: str(tmp_path / v) if v == "clip.mp4" else v
                   for k, v in options.items()}       # tools check the file exists
        argv = server.tool_argv(tool, options, tmp_path / "run")
        _accepts(argv[argv.index("demoforge.cli") + 1:], monkeypatch)


def test_allowed_paths(server, tmp_path):
    from fastapi import HTTPException
    inside = tmp_path / "projects" / "p" / "plan.json"
    inside.parent.mkdir(parents=True)
    inside.write_text("{}")
    assert server.allowed(inside) == inside.resolve()
    with pytest.raises(HTTPException):
        server.allowed(tmp_path / "elsewhere.txt")
    with pytest.raises(HTTPException):
        server.allowed(tmp_path / "out" / "x.mp4", write=True)   # out is read-only


def test_artifact_status(server, tmp_path):
    directory = server.create_project(
        catalog.REEL, "r", {"title": "r", "source": "take.mp4"})
    arts = server.artifacts(catalog.REEL, "r", directory)
    assert not arts["plan"]["exists"]
    (directory / "plan.json").write_text("{}")
    arts = server.artifacts(catalog.REEL, "r", directory)
    assert arts["plan"]["exists"]
    status = {s["key"]: s for s in server.step_status(catalog.REEL, arts)}
    assert status["plan"]["done"] and not status["plan"]["ready"]   # no transcript yet
    assert status["build"]["ready"] and not status["build"]["done"]


def test_plan_summary_reads_sections(server, tmp_path):
    directory = server.create_project(catalog.REEL, "s", {"title": "s", "source": "t"})
    (directory / "plan.json").write_text(json.dumps({"sections": [
        {"id": "01", "start": 1.0, "end": 3.5, "shot": "full", "banner": "Hi"},
        {"id": "02", "start": 4.0, "end": 6.0, "shot": "card",
         "card": {"layout": "punch", "headline": "Then"}}]}))
    summary = server.plan_summary(catalog.REEL, directory)
    assert summary["kind"] == "sections" and summary["seconds"] == 4.5
    assert [r["headline"] for r in summary["rows"]] == ["Hi", "Then"]


def test_runner_streams_and_finishes(tmp_path):
    import sys
    import time
    from demoforge.app.jobs import Runner
    runner = Runner()
    seen = []
    runner.listen(seen.append)
    job = runner.submit("p", "short", "echo",
                        [sys.executable, "-c", "print('== hello ==')\nprint('line two')"],
                        {}, tmp_path, tmp_path / "logs")
    for _ in range(100):
        if job.status in ("done", "failed"):
            break
        time.sleep(0.1)
    assert job.status == "done" and job.phase == "hello"
    assert runner.tail(job.id)[-1] == "line two"
    assert job.log_path.read_text().splitlines()[0].startswith("$ ")
    assert any(e["type"] == "line" for e in seen)


def test_runner_cancels_a_running_job(tmp_path):
    import sys
    import time
    from demoforge.app.jobs import Runner
    runner = Runner()
    job = runner.submit("p", "short", "sleep",
                        [sys.executable, "-c", "import time; time.sleep(30)"],
                        {}, tmp_path, tmp_path / "logs")
    for _ in range(50):
        if job.status == "running":
            break
        time.sleep(0.1)
    assert runner.cancel(job.id)
    for _ in range(100):
        if job.ended:
            break
        time.sleep(0.1)
    assert job.status == "cancelled"


# ---------------------------------------------------------------------------
# tools
# ---------------------------------------------------------------------------


def test_every_tool_has_a_parser_matching_its_fields(capsys):
    """The window sends `--field value` for every field; the parser must take it."""
    import re
    from demoforge import tools
    for key, tool in catalog.TOOLS.items():
        with pytest.raises(SystemExit) as stop:
            tools.main([key.replace("_", "-"), "--help"])
        assert stop.value.code == 0
        usage = capsys.readouterr().out
        flags = set(re.findall(r"--[a-z][a-z-]*", usage))
        for f in tool.fields:
            assert "--" + f.key.replace("_", "-") in flags, f"{key} lacks --{f.key}"
        assert "--out" in flags


def test_tool_argv_shapes(tmp_path):
    from demoforge.app.server import tool_argv
    tool = catalog.TOOLS["tighten"]
    argv = tool_argv(tool, {"video": "a.mp4", "mirror": True, "speed": 1.05,
                            "corrections": {"wipe": "vibe"}}, tmp_path)
    tail = argv[argv.index("tool"):]
    assert tail[:2] == ["tool", "tighten"]
    assert "--mirror" in tail and "--speed" in tail and tail[tail.index("--speed") + 1] == "1.05"
    assert tail[tail.index("--corrections") + 1] == '{"wipe": "vibe"}'
    assert "--out" in tail

    cover = tool_argv(catalog.TOOLS["cover"], {"video": "a.mp4", "line": ["One", "Two"],
                                               "mirror": False}, tmp_path)
    assert cover.count("--line") == 2 and "--mirror" not in cover


def test_pick_rendition_prefers_1080():
    from demoforge.tools import _oriented, pick_rendition
    videos = {"large": {"url": "L", "width": 2160, "height": 3840},
              "medium": {"url": "M", "width": 1080, "height": 1920},
              "small": {"url": "S", "width": 540, "height": 960}}
    assert pick_rendition(videos)["url"] == "M"
    only_4k = {"large": {"url": "L", "width": 3840, "height": 2160}}
    assert pick_rendition(only_4k)["url"] == "L"
    assert pick_rendition({}) is None
    assert _oriented({"videos": videos}, "vertical")
    assert not _oriented({"videos": videos}, "horizontal")
    assert _oriented({"videos": only_4k}, "horizontal") and _oriented({}, "any")


def test_slug_and_accent():
    from demoforge.tools import _slug, accent_hex
    assert _slug("cafe, laptop typing, work", 123) == "cafe-laptop-typing-work-123"
    assert _slug("", 9) == "clip-9"
    assert accent_hex("lime") == "#C8FF2E" and accent_hex("#123456") == "#123456"
    assert accent_hex("nonsense") == accent_hex("lime")


def test_tool_runs_lists_newest_first(server, tmp_path):
    base = server.out_dir() / "tools" / "cover"
    for name in ("20260101-000000-a", "20260102-000000-b"):
        (base / name).mkdir(parents=True)
        (base / name / "x-cover.jpg").write_bytes(b"\xff\xd8")
        (base / name / "notes.txt").write_text("hi")
    import os, time
    os.utime(base / "20260102-000000-b", (time.time() + 5, time.time() + 5))
    runs = server.tool_runs("cover")
    assert [r["name"] for r in runs][0] == "20260102-000000-b"
    kinds = {f["name"]: f["kind"] for f in runs[0]["files"]}
    assert kinds == {"x-cover.jpg": "image", "notes.txt": "text"}
    jpg = next(f for f in runs[0]["files"] if f["kind"] == "image")
    assert jpg["url"].startswith("/api/media")
