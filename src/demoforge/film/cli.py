"""`demoforge film ...`: the film mode's commands, one per step.

    demoforge film new <dir>                       scaffold a project
    demoforge film check    --project X            validate film.json
    demoforge film decode   --project X [lines]    AV1 camera clips -> work/cam
    demoforge film spine    --project X            the voice spine
    demoforge film captions --project X [lines]    whisper + the caption table
    demoforge film retime   --project X --from spine.v1.json
    demoforge film timeline --project X
    demoforge film camprep  --project X [--matte]  plates and cutouts
    demoforge film scenes   --project X [ids]      camera scene bases + skeletons
    demoforge film root     --project X
    demoforge film freeze   --project X
    demoforge film score    --project X
    demoforge film mix      --project X
    demoforge film build    --project X [--retime B] [--skip a,b]
    demoforge film render   --project X [--out F] [--wait]
    demoforge film qa       --project X [--video F]
    demoforge film thumbs   --project X [--video F] [--at 3.2,250]

Every step takes `--work DIR` (intermediates) and `--into DIR` (generated film
files) to run somewhere other than the project's own folders.
"""

from __future__ import annotations

import argparse
from pathlib import Path

BUILD = ["decode", "spine", "captions", "timeline", "camprep", "scenes", "root", "freeze", "score", "mix"]
ACTIONS = ["new", "check", *BUILD, "retime", "build", "render", "qa", "thumbs"]


def add_subparser(subparsers) -> argparse.ArgumentParser:
    f = subparsers.add_parser("film", help="film mode: a voiced film of scenes on a voice spine",
                              description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    f.add_argument("action", choices=ACTIONS)
    f.add_argument("only", nargs="*", help="new: the folder; decode/captions: lines; scenes: scene ids")
    f.add_argument("--project", default=None, help="a film.json, its folder, or a project name")
    f.add_argument("--work", default=None, help="intermediates folder (default: paths.work)")
    f.add_argument("--into", default=None, help="write generated film files here instead of film/")
    f.add_argument("--from", dest="baseline", default=None, help="retime: the spine the words were made on")
    f.add_argument("--retime", default=None, help="build: retime from this spine instead of running whisper")
    f.add_argument("--skip", default="", help="build: comma list of steps to leave out")
    f.add_argument("--force", action="store_true", help="decode: redo existing; render: start anyway")
    f.add_argument("--matte", action="store_true", help="camprep: make missing mattes")
    f.add_argument("--out", default=None, help="render: output file")
    f.add_argument("--wait", action="store_true", help="render: wait out an orphaned render")
    f.add_argument("--video", default=None, help="qa/thumbs: the render to check (default: render.output)")
    f.add_argument("--no-sheets", action="store_true", help="qa: skip the contact sheets")
    f.add_argument("--count", type=int, default=None, help="thumbs: how many")
    f.add_argument("--at", default=None, help="thumbs: headline frame times, comma list")
    f.set_defaults(fn=run)
    return f


def _step(p, name: str, args) -> None:
    only = args.only or None
    if name == "decode":
        from demoforge.film import decode
        decode.build(p, only, args.force)
    elif name == "spine":
        from demoforge.film import spine
        spine.build(p)
    elif name == "captions":
        from demoforge.film import captions
        problems = captions.transcribe(p, only)
        if problems:
            raise SystemExit("CLIPPED SPEECH:\n  " + "\n  ".join(problems))
    elif name == "retime":
        from demoforge.film import captions
        if not args.baseline:
            raise SystemExit("retime needs --from <the spine the words were transcribed on>")
        captions.retime_project(p, Path(args.baseline).resolve())
    elif name == "timeline":
        from demoforge.film import timeline
        timeline.build(p)
    elif name == "camprep":
        from demoforge.film import camprep
        camprep.build(p, args.matte)
    elif name == "scenes":
        from demoforge.film import camscene, scaffold
        tl = p.timeline()
        for sc in tl["scenes"]:
            if only and sc["id"] not in only:
                continue
            if p.emit == p.film:
                scaffold.scene_dir(p.film, sc["id"])
            if sc["kind"] not in p.cfg["looks"]:
                camscene.scaffold_scene(p, sc)
        camscene.build(p, only)
    elif name == "root":
        from demoforge.film import root
        root.build(p)
    elif name == "freeze":
        from demoforge.film import freeze
        freeze.build(p)
    elif name == "score":
        from demoforge.film import score
        score.build(p)
    elif name == "mix":
        from demoforge.film import mix
        mix.build(p)


def run(args) -> int:
    from demoforge.film import project

    if args.action == "new":
        from demoforge.film import scaffold
        if not args.only:
            raise SystemExit("film new <dir>")
        scaffold.new(args.only[0])
        return 0
    if not args.project:
        raise SystemExit(f"film {args.action} needs --project")
    if args.action == "check":
        path = project.find(args.project)
        import json
        raw = project.strip_comments(json.loads(path.read_text(encoding="utf-8")))
        errors, warnings = project.validate(project.merge(project.DEFAULTS, raw))
        for w in warnings:
            print("  warning:", w)
        for e in errors:
            print("  error:", e)
        print(f"{path}: {len(errors)} error(s), {len(warnings)} warning(s)")
        return 1 if errors else 0
    p = project.load(args.project, work=args.work, into=args.into)
    if args.action == "build":
        skip = {s.strip() for s in args.skip.split(",") if s.strip()}
        for name in BUILD:
            if name in skip:
                continue
            if name == "captions" and args.retime:
                args.baseline = args.retime
                name = "retime"
            print(f"== film {name}", flush=True)
            _step(p, name, args)
        return 0
    if args.action == "render":
        from demoforge.film import render
        render.render(p, Path(args.out).resolve() if args.out else None, wait=args.wait, force=args.force)
        return 0
    if args.action in ("qa", "thumbs"):
        video = Path(args.video).resolve() if args.video else p._resolve(p.cfg["render"]["output"])
        if args.action == "qa":
            from demoforge.film import qa
            qa.run(p, video if video.exists() else None, sheets=not args.no_sheets)
        else:
            from demoforge.film import thumbs
            if not video.exists():
                raise SystemExit(f"no render at {video}")
            at = [float(x) for x in args.at.split(",")] if args.at else None
            thumbs.run(p, video, args.count, at)
        return 0
    _step(p, args.action, args)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="demoforge")
    add_subparser(ap.add_subparsers(dest="cmd", required=True))
    args = ap.parse_args(argv)
    return args.fn(args)


def film_mode():
    """The app's catalog entry for film mode, built from the catalog's own types."""
    from demoforge.app.catalog import Artifact, Field, Mode, Step

    def step(key, label, help, heavy=False, needs=(), makes=(), extra=()):
        return Step(key, label, help, ["film", key, "--project", "{project}", *extra],
                    needs=list(needs), makes=list(makes), heavy=heavy)

    return Mode(
        key="film", name="Film", aspect="16:9", accent="blue",
        tagline="A narrated film of scenes, cut on the voice.",
        blurb="You recorded the story line by line, some of it to camera. This builds the "
              "voice spine every cut is timed on, captions what you actually said, pins "
              "every scene to its words, generates the camera scenes and the root with "
              "its transitions, scores it and mixes it. The animated scenes are yours.",
        needs=["One voice file per line, numbered in film order",
               "The on-camera lines as video, same numbers", "A film.json (`film new` writes one)"],
        profile="film.json",
        requires=["ffmpeg", "whisper", "mediapipe", "node"],
        fields=[
            Field("title", "Title", "text", required=True),
            Field("paths", "Footage and folders", "json", default={},
                  help="voice and camera folders; work and music folders. See docs/film-mode.md."),
            Field("scenes", "Scenes", "json", default=[], help="id, kind, the line (or line@word) it starts on"),
            Field("joins", "Transitions", "json", group="look", default={}, help="scene id -> transition kind"),
            Field("lookaways", "Look-aways", "json", group="speech", default={},
                  help="line -> clip time of the last on-lens frame"),
            Field("music", "Music", "json", group="sound", default={}),
        ],
        steps=[
            step("decode", "Decode", "AV1 phone clips through libdav1d, checked for repeated frames.",
                 heavy=True, makes=["cam"]),
            step("spine", "Spine", "Trim every line on its waveform and lay them on the frame clock.",
                 makes=["spine", "voice"]),
            step("captions", "Captions", "Whisper each line and align what was said to it.", heavy=True,
                 needs=["spine"], makes=["words"]),
            step("timeline", "Timeline", "Pin every scene to its line or word.", needs=["words"],
                 makes=["timeline"]),
            step("camprep", "Camera media", "Plates and cleaned cutouts.", heavy=True, needs=["cam"]),
            step("scenes", "Scenes", "Camera scene bases; skeletons for the animated ones.",
                 needs=["timeline"]),
            step("root", "Root", "Hosts, transitions, karaoke captions.", needs=["timeline"],
                 makes=["root", "transitions"]),
            step("freeze", "Freeze", "Stills for shatter joins.", needs=["transitions"]),
            step("score", "Score", "The music bed, pinned to lines.", needs=["spine"], makes=["bed"]),
            step("mix", "Mix", "Voice, ducked music, every SFX, mastered.", needs=["bed", "transitions"],
                 makes=["mix"]),
            step("render", "Render", "hyperframes render, with a big temp and a long timeout.", heavy=True,
                 needs=["mix", "root"], makes=["film"]),
            step("qa", "QA", "Dark frames, clipped words, captions, contact sheets.", needs=["film"],
                 makes=["qa"]),
            step("thumbs", "Thumbnails", "Score camera frames on the face; export the best.", needs=["film"],
                 makes=["thumbs"]),
        ],
        artifacts=[
            Artifact("cam", "Decoded camera clips", "out", "{name}/cam/*.mov", "video"),
            Artifact("spine", "Spine", "out", "{name}/spine/spine.json", "json"),
            Artifact("voice", "Voice", "out", "{name}/spine/voice.wav", "file"),
            Artifact("words", "Words", "out", "{name}/spine/words.json", "json"),
            Artifact("timeline", "Timeline", "project", "film/timeline.json", "json"),
            Artifact("root", "Root composition", "project", "film/index.html", "file"),
            Artifact("transitions", "Transitions", "project", "film/transitions.json", "json"),
            Artifact("bed", "Music bed", "out", "{name}/music/bed.wav", "file"),
            Artifact("mix", "Mix", "project", "film/assets/audio/mix.wav", "file"),
            Artifact("film", "The film", "project", "film/renders/{name}.mp4", "video"),
            Artifact("qa", "QA report", "out", "{name}/qa/qa.json", "json"),
            Artifact("thumbs", "Thumbnails", "out", "{name}/thumbs/thumbs_sheet.png", "image"),
        ],
        output="film",
    )


if __name__ == "__main__":
    raise SystemExit(main())
