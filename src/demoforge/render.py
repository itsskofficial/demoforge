"""Replay a captured session as a 1920x1080 video.

Every character on screen came out of a real run (see capture.py). What this
controls is *pace*: a command is typed at human speed, output arrives line by
line fast enough to feel live and slow enough to read, and the long silences
where the machine was actually computing are compressed to a beat or two --
with the real elapsed time shown in the title bar so the compression is stated
rather than hidden.

    python -m demo.record.render step4

Frames go straight to ffmpeg over a pipe; nothing touches the disk but the mp4.
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from demoforge.config import FPS, SEGMENTS as OUT, SESSIONS
from demoforge.terminal import Painter, Screen

COLS = 112
ROWS = 30
PROMPT = "\x1b[32m~/livingeval\x1b[0m \x1b[36m$\x1b[0m "


@dataclass
class Event:
    at: float           # video time, seconds
    text: str = ""      # what to feed the screen
    real: float | None = None   # elapsed time in the real run, for the title bar
    cursor: bool = True


@dataclass
class Timeline:
    events: list[Event] = field(default_factory=list)
    t: float = 0.0

    def wait(self, seconds: float) -> None:
        self.t += seconds

    def emit(self, text: str, real: float | None = None, cursor: bool = True) -> None:
        self.events.append(Event(self.t, text, real, cursor))

    def type_command(self, command: str, cps: float = 24.0, think: float = 0.55) -> None:
        """Type a prompt and a command the way a person would, then press enter."""
        self.emit(PROMPT)
        self.wait(think)
        for i, ch in enumerate(command):
            self.emit(ch)
            # Slightly slower over punctuation, which is where real typing hesitates.
            self.wait((1.0 / cps) * (1.9 if ch in "-_\"'/" else 1.0))
        self.wait(0.75)
        self.emit("\r\n", cursor=False)

    def play(self, session: dict, lines_per_sec: float = 15.0, gap_cap: float = 1.1,
             holds: list[dict] | None = None) -> None:
        """Replay captured output, compressing dead air and holding on key lines."""
        holds = list(holds or [])
        fired: set[int] = set()
        prev_real = 0.0
        for real_t, text in session["chunks"]:
            gap = real_t - prev_real
            prev_real = real_t
            self.wait(min(gap, gap_cap))
            # Feed a line at a time so output unrolls instead of appearing in blocks.
            parts = text.splitlines(keepends=True)
            for part in parts:
                self.emit(part, real=real_t, cursor=False)
                self.wait(1.0 / lines_per_sec)
                for i, hold in enumerate(holds):
                    if i not in fired and hold["match"] in part:
                        fired.add(i)
                        self.wait(hold["seconds"])
        for i, hold in enumerate(holds):
            if i not in fired:
                print(f"  !! hold never matched: {hold['match']!r}", file=sys.stderr)

    def duration(self) -> float:
        return self.t


def render(timeline: Timeline, out: Path, title: str, min_seconds: float = 0.0,
           tail_hold: float = 3.0) -> float:
    screen = Screen(COLS, ROWS)
    painter = Painter(screen, title)
    total = max(timeline.duration() + tail_hold, min_seconds)
    n_frames = int(total * FPS)

    out.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen(
        ["ffmpeg", "-y", "-loglevel", "error",
         "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", "1920x1080", "-r", str(FPS),
         "-i", "-",
         "-c:v", "libx264", "-preset", "medium", "-crf", "18",
         "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out)],
        stdin=subprocess.PIPE,
    )

    events = sorted(timeline.events, key=lambda e: e.at)
    idx = 0
    real_elapsed = 0.0
    cursor_on = True
    cache: bytes | None = None
    try:
        for frame in range(n_frames):
            t = frame / FPS
            dirty = False
            while idx < len(events) and events[idx].at <= t:
                event = events[idx]
                if event.text:
                    screen.feed(event.text)
                    dirty = True
                if event.real is not None:
                    real_elapsed = event.real
                cursor_on = event.cursor
                idx += 1
            blink = cursor_on and (int(t * 1.6) % 2 == 0)
            if dirty or cache is None or cursor_on:
                status = f"real elapsed  {int(real_elapsed) // 60}m {int(real_elapsed) % 60:02d}s" \
                    if real_elapsed >= 1 else ""
                cache = painter.paint(status=status, cursor=blink).tobytes()
            proc.stdin.write(cache)
    finally:
        proc.stdin.close()
        proc.wait()
    return total
