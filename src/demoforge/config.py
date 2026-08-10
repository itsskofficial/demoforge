"""Where things live.

demoforge records *another* repository's demo, so there are two roots: this
one, which holds the tooling and the output, and the target, which holds the
thing being demonstrated. Both are overridable by environment variable so a
project profile can point at whatever it is recording.
"""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# Where captures, segments and finished cuts are written.
OUT = Path(os.environ.get("DEMOFORGE_OUT", ROOT / "out"))
SESSIONS = OUT / "sessions"
SEGMENTS = OUT / "segments"
AUDIO = OUT / "audio"

# The repository whose demo is being recorded: commands run with this as cwd.
TARGET = Path(os.environ.get("DEMOFORGE_TARGET", Path.cwd()))

# Reference voice clips and other durable inputs.
ASSETS = ROOT / "assets"
VOICE = ASSETS / "voice"

# The local server a project profile brings up for its browser segments.
BASE_URL = os.environ.get("DEMOFORGE_BASE_URL", "http://127.0.0.1:8000")

FPS = 30
WIDTH = 1920
HEIGHT = 1080


def ensure() -> None:
    for path in (OUT, SESSIONS, SEGMENTS, AUDIO, VOICE):
        path.mkdir(parents=True, exist_ok=True)
