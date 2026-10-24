"""demoforge — one entry point for the whole pipeline.

    demoforge init     --repo ../myapp    ask for what is needed, set it up
    demoforge doctor                      what is installed and what is missing
    demoforge plan     --repo .           read a codebase, propose a demo
    demoforge voice    --src clip.mp3     clone a voice, then speak the script
    demoforge face     --src selfie.mp4   prepare the presenter footage
    demoforge build    --project myapp    render, narrate, lip-sync, assemble
    demoforge present  --project myapp    you record the words, this builds the picture
    demoforge edit     --project myapp    a deck and raw takes, cut into a film
    demoforge reel     --project myapp    one vertical take, cut into a reel
    demoforge short    --project myapp    points over ambient footage, nothing filmed
    demoforge film     build --project x  a narrated film, scene by scene (HyperFrames)
    demoforge music    --video cut.mp4    score a finished cut, ducked under the voice
    demoforge tool     score --video x.mp4   one feature on one file; see `tool --help`
    demoforge app                         the window over all of the above
    demoforge shortcut                    put the app in the Start Menu

Each stage writes files the next one reads, so any of them can be re-run alone
and the rest of the work is kept. That matters here because the lip-sync stage
is measured in tens of minutes: nothing about changing one line of narration
should mean redoing the face.
"""

from __future__ import annotations

import argparse
import importlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

from demoforge import __version__
from demoforge.config import AUDIO, OUT, PROJECTS, ROOT, SEGMENTS, VOICE, ensure

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

VENV = ROOT / ".venv" / "Scripts" / "python.exe"
LIPSYNC_VENV = ROOT / ".venv-lipsync" / "Scripts" / "python.exe"


def ok(label, good, detail=""):
    print(f"  {'OK ' if good else '-- '} {label:<26} {detail}")
    return good


def cmd_doctor(args) -> int:
    print("demoforge", __version__, "\n")
    ok("ffmpeg", shutil.which("ffmpeg") is not None)
    ok("ffprobe", shutil.which("ffprobe") is not None)
    ok("voice venv", VENV.exists(), str(VENV) if VENV.exists() else "python -m venv .venv")
    ok("lipsync venv", LIPSYNC_VENV.exists())
    ok("lipsync weights", (ROOT / "vendor/latentsync/checkpoints/latentsync_unet.pt").exists(),
       "vendor/latentsync/checkpoints")
    ok("voice reference", (VOICE / "reference.wav").exists(),
       "demoforge voice --src yourclip.mp3")
    ok("presenter footage", any((ROOT / "assets/face").glob("*.mp4"))
       if (ROOT / "assets/face").exists() else False)
    ok("anthropic key", bool(_key("ANTHROPIC_API_KEY")), "for `plan`")
    try:
        import whisper  # noqa: F401
        ok("whisper", True, "for `edit ingest`")
    except ImportError:
        ok("whisper", False, "pip install openai-whisper")
    try:
        import pptx  # noqa: F401
        ok("python-pptx", True, "for `edit`")
    except ImportError:
        ok("python-pptx", False, "pip install python-pptx")
    try:
        import playwright  # noqa: F401
        ok("playwright", True)
    except ImportError:
        ok("playwright", False, "pip install playwright && playwright install chromium")
    for mod, why, fix in (("mediapipe", "for gaze and `film thumbs`", "pip install mediapipe"),
                          ("av", "for `film decode` (AV1 via libdav1d)", "pip install av")):
        try:
            importlib.import_module(mod)
            ok(mod, True, why)
        except ImportError:
            ok(mod, False, fix)
    ok("node + npx", shutil.which("npx") is not None, "for `film` (HyperFrames); install Node.js 20+")
    return 0


def _key(name: str) -> str:
    import os
    value = os.environ.get(name, "")
    env = ROOT / ".env"
    if not value and env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith(name):
                value = line.split("=", 1)[1].strip().strip('"').strip("'")
    return value


def cmd_init(args) -> int:
    from demoforge.onboard import init
    return init(Path(args.repo).resolve(), args.voice, args.face, args.key,
                args.seconds, args.audience, args.yes)


def cmd_music(args) -> int:
    from demoforge.music import bed, mix, score
    music = Path(args.music)
    if args.video and args.style:
        # A style asked for alongside a cut means a fresh bed sized to that
        # cut, not whatever bed.wav was left over from the last one.
        score(Path(args.video), music, Path(args.out), args.style, args.seed,
              args.music_db, args.duck_db)
    elif args.video:
        mix(Path(args.video), music, Path(args.out), args.music_db, args.duck_db)
    else:
        bed(args.seconds, music, args.style or "lofi", args.seed)
    return 0


def cmd_plan(args) -> int:
    understand = importlib.import_module("demoforge.understand")
    sys.argv = ["understand", "--repo", args.repo, "--seconds", str(args.seconds),
                "--audience", args.audience]
    if args.out:
        sys.argv += ["--out", args.out]
    return understand.main()


def cmd_voice(args) -> int:
    voice = importlib.import_module("demoforge.voice")
    if args.src:
        voice.prepare(Path(args.src), start=args.start, dur=args.dur)
    if args.script:
        sys.argv = ["voice", "script", "--script", args.script, "--outdir", args.outdir,
                    "--pace", str(args.pace)]
        return voice.main()
    if args.text:
        sys.argv = ["voice", "say", "--text", args.text, "--pace", str(args.pace)]
        return voice.main()
    return 0


def cmd_face(args) -> int:
    face = importlib.import_module("demoforge.face")
    if args.src:
        face.prepare(Path(args.src), Path(args.out), args.start, args.dur)
    return 0


def cmd_build(args) -> int:
    """Render scenes, fit them to the narration, lip-sync, and composite."""
    ensure()
    project = PROJECTS / args.project
    if not project.exists():
        print(f"no project at {project}")
        return 1

    steps = args.only.split(",") if args.only else ["scenes", "assemble", "face", "compose"]

    if "scenes" in steps and (project / "scenes.py").exists():
        print("\n== scenes ==")
        subprocess.run([sys.executable, str(project / "scenes.py")], check=True)

    order = SEGMENTS / f"order-{args.project}.json"
    if not order.exists():
        order = SEGMENTS / "order.json"
    narration = Path(args.narration) if args.narration else AUDIO / "narration.json"

    if "assemble" in steps:
        print("\n== assemble ==")
        subprocess.run([sys.executable, "-m", "demoforge.assemble",
                        "--narration", str(narration), "--order", str(order),
                        "--out", str(OUT / f"{args.project}-silent.mp4")], check=True)

    head = OUT / f"{args.project}-head.mp4"
    if "face" in steps:
        print("\n== face ==")
        subprocess.run([sys.executable, "-m", "demoforge.face", "sync",
                        "--video", args.driver, "--audio", str(args.head_audio),
                        "--out", str(head)], check=True)

    if "compose" in steps and head.exists():
        print("\n== compose ==")
        subprocess.run([sys.executable, "-m", "demoforge.compose",
                        "--base", str(OUT / f"{args.project}-silent.mp4"),
                        "--head", str(head),
                        "--out", str(OUT / f"{args.project}-final.mp4")], check=True)
    return 0


def cmd_present(args) -> int:
    """Presenter mode: the user records the words, demoforge builds the rest.

    A separate path from `build`, not a replacement for it. `build` clones a
    voice and lip-syncs a face; this one takes real recordings and fits the
    picture to them. Both remain available because they fail in different
    places: a generated demo is free to iterate and unconvincing to anyone who
    knows the presenter, and a recorded one is the opposite.
    """
    from demoforge import present

    argv = [args.action, "--project", args.project]
    if args.no_trim:
        argv.append("--no-trim")
    if args.action == "build":
        if args.out:
            argv += ["--out", args.out]
        if args.only:
            argv += ["--only", *args.only.split(",")]
    return present.main(argv)


def cmd_edit(args) -> int:
    """Editor mode: a deck and a folder of raw takes, cut into a film.

    The third path, and the one that starts furthest back. `build` needs a
    script, `present` needs one clean take per section; this one needs neither,
    because it reads the words out of the recordings themselves and decides
    which of the four attempts at a paragraph was the good one.
    """
    from demoforge import edit

    argv = [args.action, "--project", args.project]
    if args.action == "new":
        argv += ["--deck", args.deck, "--footage", *args.footage,
                 "--aspect", args.aspect, "--seconds", str(args.seconds)]
    if args.action in ("build", "all") and args.out:
        argv += ["--out", args.out]
    if args.action == "build":
        if args.only:
            argv += ["--only", *args.only.split(",")]
        if args.steps:
            argv += ["--steps", args.steps]
    if args.action == "ingest" and args.model:
        argv += ["--model", args.model]
    if args.action == "plan" and args.source:
        argv += ["--from", args.source]
    return edit.main(argv)


def cmd_reel(args) -> int:
    """Reel mode: one long vertical take, cut into a short vertical film.

    The fourth path, and the one that assumes least of all: no deck, no script,
    no per-section takes. It reads the words out of a single recording, asks
    `gaze` where the eyes were, and only puts the presenter on the whole frame
    where they were actually looking at the lens.
    """
    from demoforge import reel

    argv = [args.action, "--project", args.project]
    if args.action == "plan" and args.source:
        argv += ["--from", args.source]
    if args.action in ("build", "all", "cover") and args.out:
        argv += ["--out", args.out]
    if args.action == "build":
        if args.only:
            argv += ["--only", *args.only.split(",")]
        if args.steps:
            argv += ["--steps", args.steps]
    if args.action == "cover":
        argv += ["--at", str(args.at)]
        for line in args.line or []:
            argv += ["--line", line]
    return reel.main(argv)


def cmd_short(args) -> int:
    """Short mode: a list of points over ambient footage, nothing filmed.

    The fifth path, and the only one the presenter never appears in. Timing
    is authored rather than derived, because there is no speech to derive it
    from.
    """
    from demoforge import short

    argv = [args.action, "--project", args.project]
    if args.out:
        argv += ["--out", args.out]
    if args.action == "build" and args.steps:
        argv += ["--steps", args.steps]
    return short.main(argv)


def cmd_tool(args) -> int:
    """One feature, one file. Score, caption, tighten, gaze, cover, punch,
    voice, lipsync, the two b-roll tools, matte, restore and voice-check, each
    as a single command."""
    from demoforge import tools
    return tools.main([args.name, *args.rest])


def cmd_app(args) -> int:
    """The window. A local server and a native view on it; the browser if
    there is no webview on this machine."""
    from demoforge.app.window import launch
    return launch(port=args.port, browser=args.browser, serve_only=args.serve,
                  host=args.host, log_file=OUT / "_app" / "app.log")


def cmd_shortcut(args) -> int:
    from demoforge.app import shortcuts
    return shortcuts.main()


def build_parser() -> argparse.ArgumentParser:
    """The whole command line, unparsed. Separate from `main` so the app's
    catalog can be checked against it without running anything."""
    from demoforge.music import STYLES

    ap = argparse.ArgumentParser(prog="demoforge", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", action="version", version=f"demoforge {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    i = sub.add_parser("init", help="ask for what is needed and set it up")
    i.add_argument("--repo", required=True)
    i.add_argument("--voice", default=None, help="a recording to clone from")
    i.add_argument("--face", default=None, help="a clip of the presenter")
    i.add_argument("--key", default=None, help="ANTHROPIC_API_KEY")
    i.add_argument("--seconds", type=int, default=180)
    i.add_argument("--audience", default=None)
    i.add_argument("--yes", action="store_true", help="take defaults, ask nothing")
    i.set_defaults(fn=cmd_init)

    sub.add_parser("doctor", help="check the toolchain").set_defaults(fn=cmd_doctor)

    mu = sub.add_parser("music", help="synthesise a bed, or score a cut with one")
    mu.add_argument("--video", default=None, help="score this cut; omit to only make a bed")
    mu.add_argument("--music", default=str(AUDIO / "bed.wav"),
                    help="the bed: read when scoring, written when a --style is given")
    mu.add_argument("--out", default=str(OUT / "final-scored.mp4"))
    mu.add_argument("--seconds", type=float, default=180,
                    help="bed length without --video; with it, the cut's length")
    mu.add_argument("--style", default=None, choices=sorted(STYLES),
                    help="synthesise a bed in this style (default lofi); with "
                         "--video, make one to fit the cut instead of reusing --music")
    mu.add_argument("--seed", type=int, default=0)
    mu.add_argument("--music-db", type=float, default=-23.0)
    mu.add_argument("--duck-db", type=float, default=-14.0)
    mu.set_defaults(fn=cmd_music)

    p = sub.add_parser("plan", help="read a codebase and propose a demo")
    p.add_argument("--repo", default=".")
    p.add_argument("--seconds", type=int, default=180)
    p.add_argument("--audience", default="developers new to this project")
    p.add_argument("--out", default=None)
    p.set_defaults(fn=cmd_plan)

    v = sub.add_parser("voice", help="clone a voice and read the script")
    v.add_argument("--src", default=None, help="a recording to clone from")
    v.add_argument("--start", type=float, default=8.0)
    v.add_argument("--dur", type=float, default=16.0)
    v.add_argument("--script", default=None)
    v.add_argument("--text", default=None)
    v.add_argument("--outdir", default=str(AUDIO))
    v.add_argument("--pace", type=float, default=0.85)
    v.set_defaults(fn=cmd_voice)

    f = sub.add_parser("face", help="prepare presenter footage")
    f.add_argument("--src", required=True)
    f.add_argument("--out", default=str(ROOT / "assets/face/driver.mp4"))
    f.add_argument("--start", type=float, default=0.0)
    f.add_argument("--dur", type=float, default=None)
    f.set_defaults(fn=cmd_face)

    b = sub.add_parser("build", help="render and assemble a project")
    b.add_argument("--project", required=True)
    b.add_argument("--narration", default=None)
    b.add_argument("--driver", default=str(ROOT / "assets/face/driver.mp4"))
    b.add_argument("--head-audio", default=str(AUDIO / "narration-all.wav"))
    b.add_argument("--only", default=None, help="comma list: scenes,assemble,face,compose")
    b.set_defaults(fn=cmd_build)

    pr = sub.add_parser(
        "present",
        help="presenter mode: you record the words, demoforge builds the picture")
    pr.add_argument("action", choices=["script", "intake", "build"])
    pr.add_argument("--project", required=True)
    pr.add_argument("--out", default=None)
    pr.add_argument("--only", default=None, help="comma list of section ids to re-render")
    pr.add_argument("--no-trim", action="store_true",
                    help="keep the silence at the ends of every take")
    pr.set_defaults(fn=cmd_present)

    ed = sub.add_parser(
        "edit",
        help="editor mode: a deck and raw recordings, cut into a finished video")
    ed.add_argument("action", choices=["new", "ingest", "plan", "build", "all"])
    ed.add_argument("--project", required=True)
    ed.add_argument("--deck", default=None, help="the .pptx (with `new`)")
    ed.add_argument("--footage", nargs="+", default=[],
                    help="files, folders or globs (with `new`)")
    ed.add_argument("--aspect", default="16:9", choices=["16:9", "9:16", "1:1"])
    ed.add_argument("--seconds", type=float, default=0.0, help="target runtime")
    ed.add_argument("--model", default=None, help="whisper model for `ingest`")
    ed.add_argument("--from", dest="source", default=None,
                    help="with `plan`: settle a cut written by hand")
    ed.add_argument("--out", default=None)
    ed.add_argument("--only", default=None, help="comma list of section ids")
    ed.add_argument("--steps", default=None,
                    help="comma list: sections,concat,captions,music")
    ed.set_defaults(fn=cmd_edit)

    rl = sub.add_parser(
        "reel",
        help="reel mode: one vertical take, cut into a short vertical film")
    rl.add_argument("action", choices=["ingest", "plan", "build", "all", "cover"])
    rl.add_argument("--project", required=True)
    rl.add_argument("--from", dest="source", default=None,
                    help="with `plan`: settle a cut written by hand")
    rl.add_argument("--at", type=float, default=0.0,
                    help="with `cover`: seconds into the cut")
    rl.add_argument("--line", action="append", default=None,
                    help="with `cover`: a banner line; repeat for more. *word* is accented")
    rl.add_argument("--out", default=None)
    rl.add_argument("--only", default=None, help="comma list of section ids")
    rl.add_argument("--steps", default=None,
                    help="comma list: sections,concat,captions,music")
    rl.set_defaults(fn=cmd_reel)

    sh = sub.add_parser(
        "short",
        help="short mode: a list of points over ambient footage, nothing filmed")
    sh.add_argument("action", choices=["build", "cover"])
    sh.add_argument("--project", required=True)
    sh.add_argument("--out", default=None)
    sh.add_argument("--steps", default=None,
                    help="comma list: overlay,background,compose,music")
    sh.set_defaults(fn=cmd_short)

    t = sub.add_parser("tool", help="one feature on one file: score, caption, tighten, "
                       "gaze, cover, punch, voice, lipsync, broll-generate, broll-search, "
                       "matte, restore, voice-check (`demoforge tool <name> --help`)")
    t.add_argument("name")
    t.add_argument("rest", nargs=argparse.REMAINDER)
    t.set_defaults(fn=cmd_tool)

    a = sub.add_parser("app", help="open the app: every mode, in a window")
    a.add_argument("--port", type=int, default=None, help="default: any free port")
    a.add_argument("--host", default="127.0.0.1")
    a.add_argument("--browser", action="store_true",
                   help="open in the default browser instead of a native window")
    a.add_argument("--serve", action="store_true",
                   help="only run the server (port 8765 unless --port)")
    a.set_defaults(fn=cmd_app)

    sub.add_parser("shortcut", help="put the app in the Start Menu and on the desktop"
                   ).set_defaults(fn=cmd_shortcut)

    from demoforge.film import cli as film_cli
    film_cli.add_subparser(sub)
    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
