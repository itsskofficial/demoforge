"""demoforge — one entry point for the whole pipeline.

    demoforge init     --repo ../myapp    ask for what is needed, set it up
    demoforge doctor                      what is installed and what is missing
    demoforge plan     --repo .           read a codebase, propose a demo
    demoforge voice    --src clip.mp3     clone a voice, then speak the script
    demoforge face     --src selfie.mp4   prepare the presenter footage
    demoforge build    --project myapp    render, narrate, lip-sync, assemble

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
from demoforge.config import AUDIO, OUT, ROOT, SEGMENTS, VOICE, ensure

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
        import playwright  # noqa: F401
        ok("playwright", True)
    except ImportError:
        ok("playwright", False, "pip install playwright && playwright install chromium")
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
    from demoforge.music import bed, mix
    if args.video:
        return mix(Path(args.video), Path(args.music), Path(args.out),
                   args.music_db, args.duck_db) and 0
    bed(args.seconds, Path(args.music), args.style, args.seed)
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
    project = ROOT / "projects" / args.project
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


def main(argv=None) -> int:
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
    mu.add_argument("--music", default=str(AUDIO / "bed.wav"))
    mu.add_argument("--out", default=str(OUT / "final-scored.mp4"))
    mu.add_argument("--seconds", type=float, default=180)
    mu.add_argument("--style", default="lofi")
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

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
