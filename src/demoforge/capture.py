"""Run a real command and record its output with timestamps.

The point is that the video shows output that actually happened. Nothing here
edits, shortens or invents a line: it runs the command, reads the pipe at byte
granularity, and stores `(seconds_since_start, bytes)` so the renderer can
replay the session at whatever pace the voiceover needs while keeping every
character the program actually printed.

    python -m demo.record.capture out.json -- python -m demo.run measure
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

from demoforge import config

# This script tees the child's output to its own stdout, and the child prints `█`
# and `—`. A Windows console defaults to cp1252, so without this the *recorder*
# dies on a bar chart halfway through a twenty-minute capture — the same trap
# demo/run.py documents at the top of the file.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")


def capture(command: list[str], out: Path, cwd: Path | None = None) -> int:
    cwd = cwd or config.TARGET
    env = dict(os.environ)
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    # Several libraries drop colour when stdout is a pipe. The demo writes its own
    # escape codes, but anything using click/rich needs telling.
    env["FORCE_COLOR"] = "1"
    env["TERM"] = "xterm-256color"
    env["COLUMNS"] = "100"

    started = time.time()
    proc = subprocess.Popen(
        command,
        cwd=str(cwd),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=0,
    )
    chunks: list[tuple[float, str]] = []
    fd = proc.stdout.fileno()
    pending = b""
    while True:
        try:
            data = os.read(fd, 65536)
        except OSError:
            break
        if not data:
            break
        pending += data
        # Decode only up to the last complete UTF-8 sequence so a multi-byte
        # character split across two reads does not become a replacement char.
        try:
            text = pending.decode("utf-8")
            pending = b""
        except UnicodeDecodeError as exc:
            text = pending[: exc.start].decode("utf-8", errors="replace")
            pending = pending[exc.start :]
        if text:
            chunks.append((round(time.time() - started, 4), text))
            sys.stdout.write(text)
            sys.stdout.flush()
    proc.wait()
    if pending:
        chunks.append((round(time.time() - started, 4), pending.decode("utf-8", "replace")))

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            {
                "command": command,
                "display": " ".join(command),
                "cwd": str(cwd),
                "started": started,
                "duration": round(time.time() - started, 3),
                "exit_code": proc.returncode,
                "chunks": chunks,
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    print(f"\n[capture] {out.name}  {proc.returncode=}  {time.time() - started:.1f}s  "
          f"{sum(len(c[1]) for c in chunks)} chars")
    return proc.returncode


def main() -> int:
    if "--" not in sys.argv:
        print(__doc__)
        return 2
    split = sys.argv.index("--")
    out = Path(sys.argv[1])
    command = sys.argv[split + 1 :]
    if not out.is_absolute():
        out = config.SESSIONS / out
    return capture(command, out)


if __name__ == "__main__":
    raise SystemExit(main())
