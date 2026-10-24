"""Render the film with `hyperframes render`, set up the way a 4-minute render survives.

    npx hyperframes render <film> -o <out> --workers 2 -q delivery

What the wrapper adds, each from a render that went wrong:

- TEMP and TMP point at a big disk (paths.temp). Chrome's frame cache for a
  four-minute 1080p film is tens of gigabytes and a nearly full C: kills the
  render half way, sometimes silently.
- FFMPEG_PROCESS_TIMEOUT_MS is 30 minutes. The default kills the final encode
  of a long film while it is still working.
- Two workers. More starve Chrome's media pipeline (ERR_INSUFFICIENT_RESOURCES
  on the cutout webms) and the renderer falls back to one worker anyway.
- The orphaned render. If the npx process is killed (a closed terminal, a
  timed-out tool), node keeps rendering with nobody watching and the log just
  stops. Before starting, any hyperframes render already running is reported
  and the new one refuses to start over it. After it exits, the output is
  checked: present, with video and audio, as long as the timeline. Anything
  less is reported as partial, never as done.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

from demoforge.film.project import Project


def running_renders() -> list[tuple[int, str]]:
    """(pid, command line) of every hyperframes render process on this machine."""
    if os.name == "nt":
        ps = ("Get-CimInstance Win32_Process -Filter \"Name='node.exe'\" | "
              "Select-Object ProcessId,CommandLine | ConvertTo-Json -Compress")
        out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True).stdout
        rows = json.loads(out) if out.strip() else []
        rows = rows if isinstance(rows, list) else [rows]
        found = [(r["ProcessId"], r.get("CommandLine") or "") for r in rows]
    else:
        out = subprocess.run(["ps", "-eo", "pid=,args="], capture_output=True, text=True).stdout
        found = [(int(l.split(None, 1)[0]), l.split(None, 1)[1]) for l in out.splitlines() if l.strip()]
    return [(pid, cmd) for pid, cmd in found if "hyperframes" in cmd and " render" in cmd]


def verify(out: Path, want: float, tolerance: float = 0.2) -> list[str]:
    """Why a render is not finished, or [] if it is."""
    if not out.exists() or out.stat().st_size == 0:
        return [f"{out} does not exist"]
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type:format=duration",
                            "-of", "json", str(out)], capture_output=True, text=True)
    if probe.returncode:
        return [f"{out} is unreadable (still being written, or cut off): {probe.stderr.strip()[:200]}"]
    info = json.loads(probe.stdout)
    kinds = {s["codec_type"] for s in info.get("streams", [])}
    problems = [f"no {k} stream" for k in ("video", "audio") if k not in kinds]
    got = float(info.get("format", {}).get("duration", 0))
    if abs(got - want) > tolerance:
        problems.append(f"{got:.2f}s long, the timeline is {want:.2f}s")
    return problems


def render(p: Project, out: Path | None = None, workers: int | None = None,
           quality: str | None = None, wait: bool = False, force: bool = False) -> Path:
    rc = p.cfg["render"]
    out = out or p._resolve(rc["output"])
    temp = p.path("temp")
    temp.mkdir(parents=True, exist_ok=True)
    out.parent.mkdir(parents=True, exist_ok=True)
    busy = running_renders()
    if busy and not force:
        lines = "\n  ".join(f"{pid}: {cmd[:160]}" for pid, cmd in busy)
        raise SystemExit(f"a hyperframes render is already running (orphaned?):\n  {lines}\n"
                         "wait for it, or stop it, or pass --force")
    env = dict(os.environ, TEMP=str(temp), TMP=str(temp),
               FFMPEG_PROCESS_TIMEOUT_MS=str(rc["timeout_ms"]))
    log = p.work / f"render_{out.stem}.log"
    cmd = ["npx", "--yes", "hyperframes", "render", str(p.emit), "-o", str(out),
           "--workers", str(workers or rc["workers"]), "-q", quality or rc["quality"]]
    print("render:", " ".join(cmd), f"\n  TEMP={temp}\n  log {log}")
    started = time.time()
    with log.open("w", encoding="utf-8") as fh:
        code = subprocess.run(cmd, env=env, stdout=fh, stderr=subprocess.STDOUT, shell=os.name == "nt").returncode
    want = p.timeline()["duration"]
    left = running_renders()
    if left and wait:
        print(f"  npx exited ({code}) but {len(left)} render process(es) carry on; waiting")
        while running_renders():
            time.sleep(15)
        left = []
    problems = verify(out, want)
    if left:
        problems.insert(0, f"npx exited ({code}) but render processes are still running "
                           f"(pids {', '.join(str(x) for x, _ in left)}): orphaned render; "
                           "rerun with --wait, or wait and run `film qa`")
    elif code:
        problems.insert(0, f"hyperframes exited with {code}; see {log}")
    if problems:
        raise SystemExit("render is partial:\n  " + "\n  ".join(problems))
    print(f"render: {out} ({(time.time() - started) / 60:.1f} min)")
    return out
