"""Where things live.

demoforge records *another* repository's demo, so there are two roots: this
one, which holds the tooling, and the target, which holds the thing being
demonstrated. Since the desktop app arrived there is a third: the user's own
home for projects and output, which is only the checkout by default because
that is where it has always been.

    ROOT       the code, the fonts, the models. Never written to by a build.
    HOME       where projects/ and out/ live. Defaults to ROOT; the app moves
               it to a folder the user picks so an update never touches their
               work.
    TARGET     the repository whose demo is being recorded.

Every one of these is overridable by environment variable, which is also how
the app hands a different home to the subprocess that runs a build.
"""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

HOME = Path(os.environ.get("DEMOFORGE_HOME", ROOT))

# One profile per video, in a folder named after it.
PROJECTS = Path(os.environ.get("DEMOFORGE_PROJECTS", HOME / "projects"))

# Where captures, segments and finished cuts are written.
OUT = Path(os.environ.get("DEMOFORGE_OUT", HOME / "out"))
SESSIONS = OUT / "sessions"
SEGMENTS = OUT / "segments"
AUDIO = OUT / "audio"

# The repository whose demo is being recorded: commands run with this as cwd.
TARGET = Path(os.environ.get("DEMOFORGE_TARGET", Path.cwd()))

# Reference voice clips and other durable inputs.
ASSETS = ROOT / "assets"
VOICE = ASSETS / "voice"

# The local server a project profile brings up for its browser segments.
# Large model weights live outside the repo (tens of GB). DEMOFORGE_MODELS moves them.
MODELS = Path(os.environ.get("DEMOFORGE_MODELS", "E:/Models/demoforge"))

BASE_URL = os.environ.get("DEMOFORGE_BASE_URL", "http://127.0.0.1:8000")

FPS = 30
WIDTH = 1920
HEIGHT = 1080


def ensure() -> None:
    for path in (OUT, SESSIONS, SEGMENTS, AUDIO, VOICE, PROJECTS):
        path.mkdir(parents=True, exist_ok=True)
