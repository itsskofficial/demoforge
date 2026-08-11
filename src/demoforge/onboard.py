"""`demoforge init` — ask for what is needed, check what is missing, set it up.

The first run is where this either works or gets abandoned, and the things it
needs are things only a person can supply: a recording of their voice, a clip
of their face, and a key. So it asks, plainly, once, and then does everything
that does not need a human.

Everything is skippable. A repo with no face clip still produces a narrated
demo; a repo with neither still produces one with a synthetic voice. The point
is to get to *something watchable* on the first run rather than to collect a
complete set of inputs before doing anything.

    demoforge init --repo ../myproject
    demoforge init --repo ../myproject --voice clip.mp3 --face selfie.mp4 --yes
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from demoforge.config import ROOT, VOICE, ensure

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

FACE = ROOT / "assets" / "face"


def ask(prompt: str, default: str = "", quiet: bool = False) -> str:
    if quiet:
        return default
    try:
        answer = input(f"  {prompt}{f' [{default}]' if default else ''}: ").strip()
    except EOFError:
        return default
    return answer or default


def say(text: str = "") -> None:
    print(text)


def check_env(key: str, value: str | None, quiet: bool) -> str:
    """Read a key from .env, or ask for it and write it there."""
    env = ROOT / ".env"
    existing = ""
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith(key):
                existing = line.split("=", 1)[1].strip().strip('"').strip("'")
    if existing:
        return existing
    value = value or ask(f"{key} (blank to skip)", "", quiet)
    if value:
        with env.open("a", encoding="utf-8") as f:
            f.write(f"\n{key}={value}\n")
        say(f"    saved to .env (gitignored)")
    return value


def init(repo: Path, voice: str | None = None, face: str | None = None,
         key: str | None = None, seconds: int = 180, audience: str | None = None,
         quiet: bool = False) -> int:
    ensure()
    say()
    say("  demoforge init")
    say("  " + "-" * 58)

    # --- 1. the toolchain ----------------------------------------------------
    missing = [tool for tool in ("ffmpeg", "ffprobe") if not shutil.which(tool)]
    if missing:
        say(f"  ffmpeg is not on PATH ({', '.join(missing)}). Install it first.")
        return 1
    say("  ffmpeg                    found")

    gpu = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total",
                          "--format=csv,noheader"], capture_output=True, text=True)
    if gpu.returncode == 0 and gpu.stdout.strip():
        say(f"  gpu                       {gpu.stdout.strip().splitlines()[0]}")
    else:
        say("  gpu                       none found — voice and face will be slow")

    # --- 2. the things only you have ----------------------------------------
    say()
    say("  Three things are needed, and all of them are optional.")
    say()

    reference = VOICE / "reference.wav"
    if reference.exists() and not voice:
        say(f"  voice                     already set up ({reference.name})")
    else:
        say("  A recording of your voice. Thirty seconds of talking, any content,")
        say("  no music. Used once to clone it; never uploaded anywhere.")
        src = voice or ask("path to an audio or video file (blank to skip)", "", quiet)
        if src and Path(src).exists():
            from demoforge.voice import prepare
            prepare(Path(src), reference, start=8.0, dur=16.0)
        elif src:
            say(f"    no file at {src} — skipping")
        else:
            say("    skipped: narration will need a voice before it can run")

    say()
    driver = FACE / "driver.mp4"
    if driver.exists() and not face:
        say(f"  face                      already set up ({driver.name})")
    else:
        say("  A clip of you looking at the camera, twenty to forty seconds,")
        say("  even light, plain background, calm delivery. Reused forever.")
        src = face or ask("path to a video file (blank to skip)", "", quiet)
        if src and Path(src).exists():
            from demoforge.face import prepare as prepare_face
            prepare_face(Path(src), driver, 0.0, 24.0)
        elif src:
            say(f"    no file at {src} — skipping")
        else:
            say("    skipped: the demo will have no presenter in the corner")

    say()
    say("  An Anthropic key, to read your codebase and draft the script.")
    api_key = check_env("ANTHROPIC_API_KEY", key, quiet)
    if not api_key:
        say("    skipped: you will need to write the narration by hand")

    # --- 3. the part that needs no human ------------------------------------
    project = ROOT / "projects" / repo.name
    if api_key:
        say()
        say(f"  Reading {repo.name} …")
        from demoforge.understand import main as plan_main

        argv = sys.argv
        sys.argv = ["understand", "--repo", str(repo), "--seconds", str(seconds),
                    "--out", str(project / "plan.json")]
        if audience:
            sys.argv += ["--audience", audience]
        try:
            plan_main()
        finally:
            sys.argv = argv

    # --- 4. what to do next --------------------------------------------------
    say()
    say("  " + "-" * 58)
    say("  Next:")
    say()
    if api_key:
        say(f"    1. read and edit  projects/{repo.name}/plan.json")
        say(f"    2. demoforge voice --script projects/{repo.name}/narration.json")
    else:
        say(f"    1. write projects/{repo.name}/narration.json yourself")
        say(f"    2. demoforge voice --script projects/{repo.name}/narration.json")
    say(f"    3. cp projects/livingeval3/scenes.py projects/{repo.name}/  and edit")
    say(f"    4. demoforge build --project {repo.name}")
    say()
    say("  Read the plan before running anything in it. The commands in it were")
    say("  proposed by a model that has read your repo and never used your tool.")
    say()
    return 0
