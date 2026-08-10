"""Re-dub a base recording so the mouth matches new narration.

This is the "record once, re-dub forever" half. You film yourself once, and
every future version of the demo reuses that footage with new audio: identity,
lighting, head motion and micro-expressions are all real, and only the mouth
is generated. It is the reason this looks like you and a photo-to-video model
does not.

LatentSync runs in its own virtualenv because it pins an older transformers
than the voice model does. It still shares the machine's global torch, so
there is exactly one copy of that on disk.

    python -m demoforge.face prepare --src clip.mp4 --start 1.5 --dur 11
    python -m demoforge.face loop    --src driver.mp4 --seconds 90
    python -m demoforge.face sync    --video driver.mp4 --audio line.wav
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from demoforge.config import ASSETS, OUT, ROOT

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

VENDOR = ROOT / "vendor" / "latentsync"
PYTHON = ROOT / ".venv-lipsync" / "Scripts" / "python.exe"
CHECKPOINT = VENDOR / "checkpoints" / "latentsync_unet.pt"
# stage2 is the 1.5 inference config: 256px face region, 16-frame window. The
# 512px variant is LatentSync 1.6 and wants ~18GB, which this machine has not got.
CONFIG = VENDOR / "configs" / "unet" / "stage2.yaml"
FACE = ASSETS / "face"

FPS = 25          # what the model was trained at; feeding it 30 costs quality
WIDTH = 720


def duration(path: Path) -> float:
    return float(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True, check=True).stdout.strip())


def prepare(src: Path, out: Path, start: float = 0.0, dur: float | None = None,
            width: int = WIDTH, fps: int = FPS) -> Path:
    """Normalise a phone recording into something the model can chew on.

    Phones write portrait video as landscape plus a rotation flag. ffmpeg
    honours it, most model code does not, so the rotation is baked into the
    pixels here rather than left as metadata for something else to ignore.
    """
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-y", "-loglevel", "error"]
    if start:
        cmd += ["-ss", str(start)]
    if dur:
        cmd += ["-t", str(dur)]
    cmd += ["-i", str(src), "-vf", f"scale={width}:-2,fps={fps}", "-an",
            "-metadata:s:v", "rotate=0", "-c:v", "libx264", "-crf", "18",
            "-preset", "medium", "-pix_fmt", "yuv420p", str(out)]
    subprocess.run(cmd, check=True)
    print(f"  driver  {out.name}  {duration(out):.1f}s")
    return out


def loop(src: Path, out: Path, seconds: float, fps: int = FPS) -> Path:
    """Extend a short clip to `seconds` by ping-ponging it.

    A plain loop snaps back to frame one every cycle, which reads as a glitch.
    Playing it forwards then backwards means the join is always between two
    adjacent frames, so the seam is a change of direction rather than a cut.
    The head drifts back and forth, which over a long narration looks like
    someone shifting in their seat.
    """
    reversed_clip = out.with_suffix(".rev.mp4")
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(src),
         "-vf", "reverse", "-an", "-c:v", "libx264", "-crf", "18",
         "-pix_fmt", "yuv420p", str(reversed_clip)],
        check=True)

    cycle = out.with_suffix(".cycle.mp4")
    listing = out.with_suffix(".txt")
    # Absolute: the concat demuxer resolves relative entries against the
    # listing file's own directory, not the working directory.
    listing.write_text(
        f"file '{src.resolve().as_posix()}'\nfile '{reversed_clip.resolve().as_posix()}'\n",
        encoding="utf-8")
    # Re-encoded rather than stream-copied: the reversed clip comes back with a
    # different timebase, and concat -c copy refuses to join the two.
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
         "-i", str(listing), "-c:v", "libx264", "-crf", "18", "-preset", "medium",
         "-pix_fmt", "yuv420p", "-r", str(fps), str(cycle)],
        check=True)

    repeats = max(1, int(seconds / duration(cycle)) + 1)
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-stream_loop", str(repeats),
         "-i", str(cycle), "-t", f"{seconds:.3f}", "-c:v", "libx264", "-crf", "18",
         "-preset", "medium", "-pix_fmt", "yuv420p", "-r", str(fps), str(out)],
        check=True)
    for path in (reversed_clip, cycle, listing):
        path.unlink(missing_ok=True)
    print(f"  driver  {out.name}  {duration(out):.1f}s  ({repeats} ping-pong cycles)")
    return out


def sync(video: Path, audio: Path, out: Path, steps: int = 20,
         guidance: float = 1.5, seed: int = 1247, config: Path | None = None) -> Path:
    """Run LatentSync. The mouth is generated; everything else is the original."""
    if not PYTHON.exists():
        raise SystemExit(f"no lipsync venv at {PYTHON}")
    if not CHECKPOINT.exists():
        raise SystemExit(f"no checkpoint at {CHECKPOINT}")
    config = config or CONFIG
    out.parent.mkdir(parents=True, exist_ok=True)

    # The driver has to be at least as long as the audio or the model runs out
    # of frames partway through the line.
    if duration(video) < duration(audio):
        raise SystemExit(
            f"driver is {duration(video):.1f}s but the audio is {duration(audio):.1f}s; "
            f"run `face loop --seconds {duration(audio):.0f}` first")

    # Torch 2.11 routes parts of the UNet through inductor, which wants Triton,
    # which does not exist on Windows. The model runs fine eagerly -- it was
    # written against torch 2.4, before any of this was on by default.
    env = dict(os.environ, TORCHDYNAMO_DISABLE="1")

    subprocess.run(
        [str(PYTHON), "-m", "scripts.inference",
         "--unet_config_path", str(config),
         "--inference_ckpt_path", str(CHECKPOINT),
         "--video_path", str(video.resolve()),
         "--audio_path", str(audio.resolve()),
         "--video_out_path", str(out.resolve()),
         "--inference_steps", str(steps),
         "--guidance_scale", str(guidance),
         "--seed", str(seed)],
        cwd=str(VENDOR), env=env, check=True)
    print(f"  lipsync  {out.name}  {duration(out):.1f}s")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("prepare", help="normalise a phone recording")
    p.add_argument("--src", required=True)
    p.add_argument("--out", default=str(FACE / "driver.mp4"))
    p.add_argument("--start", type=float, default=0.0)
    p.add_argument("--dur", type=float, default=None)
    p.add_argument("--width", type=int, default=WIDTH)

    lp = sub.add_parser("loop", help="ping-pong a clip out to a length")
    lp.add_argument("--src", default=str(FACE / "driver.mp4"))
    lp.add_argument("--out", default=str(FACE / "driver-long.mp4"))
    lp.add_argument("--seconds", type=float, required=True)

    s = sub.add_parser("sync", help="re-dub a clip against an audio track")
    s.add_argument("--video", default=str(FACE / "driver.mp4"))
    s.add_argument("--audio", required=True)
    s.add_argument("--out", default=str(OUT / "face-sample.mp4"))
    s.add_argument("--steps", type=int, default=20)
    s.add_argument("--guidance", type=float, default=1.5)
    s.add_argument("--config", default=None)

    args = ap.parse_args()
    if args.cmd == "prepare":
        prepare(Path(args.src), Path(args.out), args.start, args.dur, args.width)
    elif args.cmd == "loop":
        loop(Path(args.src), Path(args.out), args.seconds)
    else:
        sync(Path(args.video), Path(args.audio), Path(args.out), args.steps,
             args.guidance, config=Path(args.config) if args.config else None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
