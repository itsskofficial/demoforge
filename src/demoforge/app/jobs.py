"""Running a step, and watching it.

A build is a subprocess of the same interpreter running `demoforge.cli`, not a
function call in the server. Three reasons, and each has cost a day somewhere:

**A render that crashes must not take the window with it.** ffmpeg, whisper
and mediapipe all abort the process on their worst days. In a subprocess that
is a failed job with a log; in-process it is a blank window and no log.

**A render must be stoppable.** A lip-sync stage runs for an hour. `terminate`
on a subprocess -- and on Windows, `taskkill /T` so the ffmpeg underneath goes
too -- is the only cancel that actually cancels.

**The CLI stays the truth.** The app runs exactly what a person would type, and
prints the command it ran at the top of the log. Anything the app can do can
be repeated from a shell, which is what makes a bug report answerable.

One job runs at a time. The heavy stages are GPU- and CPU-bound, and two of
them at once are slower than one after the other and far harder to read.
"""

from __future__ import annotations

import asyncio
import os
import re
import subprocess
import sys
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

PHASE = re.compile(r"^\s*==\s*(.+?)\s*==\s*$")
KEEP = 4000   # lines held in memory per job; the file has all of them


@dataclass
class Job:
    id: str
    project: str
    mode: str
    step: str
    argv: list[str]
    env: dict[str, str]
    cwd: Path
    log_path: Path
    status: str = "queued"       # queued running done failed cancelled
    phase: str = ""
    created: float = field(default_factory=time.time)
    started: float | None = None
    ended: float | None = None
    returncode: int | None = None
    lines: deque = field(default_factory=lambda: deque(maxlen=KEEP))
    count: int = 0
    process: subprocess.Popen | None = None

    def public(self) -> dict[str, Any]:
        return {
            "id": self.id, "project": self.project, "mode": self.mode,
            "step": self.step, "argv": self.argv, "status": self.status,
            "phase": self.phase, "created": self.created, "started": self.started,
            "ended": self.ended, "returncode": self.returncode,
            "lines": self.count, "log": str(self.log_path),
        }


class Runner:
    """A FIFO of jobs and the thread that drains it."""

    def __init__(self) -> None:
        self.jobs: dict[str, Job] = {}
        self.order: list[str] = []
        self._queue: deque[str] = deque()
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._listeners: list[Callable[[dict[str, Any]], None]] = []
        self._thread = threading.Thread(target=self._loop, name="demoforge-jobs",
                                        daemon=True)
        self._thread.start()

    # -- public --------------------------------------------------------------

    def listen(self, callback: Callable[[dict[str, Any]], None]) -> Callable[[], None]:
        self._listeners.append(callback)

        def stop() -> None:
            if callback in self._listeners:
                self._listeners.remove(callback)
        return stop

    def submit(self, project: str, mode: str, step: str, argv: list[str],
               env: dict[str, str], cwd: Path, log_dir: Path) -> Job:
        log_dir.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        job = Job(id=uuid.uuid4().hex[:10], project=project, mode=mode, step=step,
                  argv=argv, env=env, cwd=cwd,
                  log_path=log_dir / f"{stamp}-{step}.log")
        with self._lock:
            self.jobs[job.id] = job
            self.order.append(job.id)
            self._queue.append(job.id)
        self._emit({"type": "job", "job": job.public()})
        self._wake.set()
        return job

    def cancel(self, job_id: str) -> bool:
        job = self.jobs.get(job_id)
        if not job:
            return False
        with self._lock:
            if job.status == "queued":
                self._queue.remove(job_id)
                job.status = "cancelled"
                job.ended = time.time()
                self._emit({"type": "job", "job": job.public()})
                return True
        if job.status == "running" and job.process:
            # Mark it before killing it. The runner thread sees the exit code
            # first otherwise, and records a cancel as a failure.
            job.status = "cancelled"
            _kill(job.process)
            return True
        return False

    def active(self) -> Job | None:
        return next((self.jobs[i] for i in self.order
                     if self.jobs[i].status == "running"), None)

    def recent(self, limit: int = 50) -> list[dict[str, Any]]:
        return [self.jobs[i].public() for i in reversed(self.order[-limit:])]

    def tail(self, job_id: str, since: int = 0) -> list[str]:
        job = self.jobs.get(job_id)
        if not job:
            return []
        lines = list(job.lines)
        # `since` counts lines from the start of the job; the deque only holds
        # the last KEEP of them.
        first = job.count - len(lines)
        return lines[max(0, since - first):]

    # -- internals -----------------------------------------------------------

    def _emit(self, event: dict[str, Any]) -> None:
        for callback in list(self._listeners):
            try:
                callback(event)
            except Exception:
                pass

    def _loop(self) -> None:
        while True:
            self._wake.wait()
            with self._lock:
                job_id = self._queue.popleft() if self._queue else None
                if job_id is None:
                    self._wake.clear()
            if job_id is None:
                continue
            self._run(self.jobs[job_id])

    def _run(self, job: Job) -> None:
        job.status = "running"
        job.started = time.time()
        self._emit({"type": "job", "job": job.public()})

        env = {**os.environ, **job.env, "PYTHONUNBUFFERED": "1",
               "PYTHONIOENCODING": "utf-8"}
        creation = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        job.log_path.parent.mkdir(parents=True, exist_ok=True)
        with job.log_path.open("w", encoding="utf-8") as log:
            shown = " ".join(_quote(a) for a in job.argv)
            self._line(job, log, f"$ {shown}")
            try:
                job.process = subprocess.Popen(
                    job.argv, cwd=str(job.cwd), env=env,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    creationflags=creation,
                    start_new_session=(os.name != "nt"))
            except OSError as exc:
                self._line(job, log, f"could not start: {exc}")
                job.status = "failed"
                job.ended = time.time()
                self._emit({"type": "job", "job": job.public()})
                return
            assert job.process.stdout is not None
            for raw in iter(job.process.stdout.readline, b""):
                text = raw.decode("utf-8", errors="replace").rstrip("\r\n")
                # A progress bar redraws itself with carriage returns and
                # sends no newline until it finishes, so it arrives here as
                # one line holding every frame it ever drew. Keep the last,
                # which is what the terminal would be showing.
                if "\r" in text:
                    text = text.split("\r")[-1]
                self._line(job, log, text)
            job.returncode = job.process.wait()
            if job.status == "cancelled":
                self._line(job, log, "stopped")
        job.ended = time.time()
        if job.status != "cancelled":
            job.status = "done" if job.returncode == 0 else "failed"
        self._emit({"type": "job", "job": job.public()})

    def _line(self, job: Job, log, text: str) -> None:
        log.write(text + "\n")
        log.flush()
        job.lines.append(text)
        job.count += 1
        found = PHASE.match(text)
        if found:
            job.phase = found.group(1)
        self._emit({"type": "line", "id": job.id, "n": job.count, "text": text,
                    **({"phase": job.phase} if found else {})})


def _quote(arg: str) -> str:
    return f'"{arg}"' if " " in arg else arg


def _kill(process: subprocess.Popen) -> None:
    """Stop a job and everything it started.

    ffmpeg is a grandchild by the time a build is running. Terminating only
    the Python process leaves it encoding into a file nobody will read, at
    full CPU, until it finishes on its own.
    """
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(process.pid)],
                       capture_output=True)
    else:
        import signal
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        except ProcessLookupError:
            pass
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()


def cli_argv(args: list[str]) -> list[str]:
    """The interpreter running this app, running the CLI."""
    return [sys.executable, "-m", "demoforge.cli", *args]


class Bridge:
    """Hands runner events to asyncio websockets without blocking the runner."""

    def __init__(self, runner: Runner) -> None:
        self.runner = runner
        self.loop: asyncio.AbstractEventLoop | None = None
        self.queues: set[asyncio.Queue] = set()
        runner.listen(self._on_event)

    def attach(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=5000)
        self.queues.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self.queues.discard(queue)

    def _on_event(self, event: dict[str, Any]) -> None:
        if not self.loop:
            return
        for queue in list(self.queues):
            def put(q=queue, e=event):
                if q.full():
                    try:
                        q.get_nowait()
                    except asyncio.QueueEmpty:
                        pass
                q.put_nowait(e)
            try:
                self.loop.call_soon_threadsafe(put)
            except RuntimeError:
                pass
