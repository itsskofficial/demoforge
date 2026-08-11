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


def loop(src: Path, out: Path, seconds: float, fps: int = FPS,
         blend: float = 0.5) -> Path:
    """Extend a short clip to `seconds` by looping it forwards.

    **Never ping-pong a person.** Playing a clip forwards then backwards makes
    a seamless join, which is why it is tempting, and it is wrong: reversed
    human motion is uncanny. Blinks un-blink, a jaw closing becomes a jaw
    opening on nothing, a head settling becomes a head lurching. Lip-sync only
    replaces the mouth, so everything around it is a person running backwards
    for half the runtime, and viewers read it as "weird faces" without being
    able to say why.

    Forward-only has a seam instead. That is dealt with by crossfading the
    clip's own tail into its own head, producing a cycle whose end already
    matches its start, so repeating it has nothing to snap.
    """
    d = duration(src)
    x = min(blend, d / 4)
    body = d - x

    cycle = out.with_suffix(".cycle.mp4")
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(src),
         "-filter_complex",
         # xfade refuses a variable frame rate, and `trim` leaves the rate
         # unset, so each branch is re-rated before it reaches the crossfade.
         f"[0:v]fps={fps},split=3[b][t][h];"
         f"[b]trim=0:{body:.3f},setpts=PTS-STARTPTS,fps={fps}[bb];"
         f"[t]trim={body:.3f}:{d:.3f},setpts=PTS-STARTPTS,fps={fps}[tt];"
         f"[h]trim=0:{x:.3f},setpts=PTS-STARTPTS,fps={fps}[hh];"
         f"[tt][hh]xfade=transition=fade:duration={x:.3f}:offset=0[xx];"
         f"[bb][xx]concat=n=2:v=1[v]",
         "-map", "[v]", "-an", "-c:v", "libx264", "-crf", "18", "-preset", "medium",
         "-pix_fmt", "yuv420p", "-r", str(fps), str(cycle)],
        check=True)

    repeats = max(1, int(seconds / duration(cycle)) + 1)
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-stream_loop", str(repeats),
         "-i", str(cycle), "-t", f"{seconds:.3f}", "-c:v", "libx264", "-crf", "18",
         "-preset", "medium", "-pix_fmt", "yuv420p", "-r", str(fps), str(out)],
        check=True)
    cycle.unlink(missing_ok=True)
    print(f"  driver  {out.name}  {duration(out):.1f}s  "
          f"({repeats} forward loops, {x:.1f}s blend)")
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


def sync_chunked(video: Path, audio: Path, out: Path, chunk: float = 20.0,
                 steps: int = 20, guidance: float = 1.5, width: int = 512,
                 workdir: Path | None = None) -> Path:
    """Lip-sync a long track in pieces, then join them.

    LatentSync decodes the whole driver into one numpy array before it starts:
    at 720x1280 a three-minute clip is 11.5 GiB, which a 16 GB laptop cannot
    allocate. Chunking bounds that, and the pieces are independent so a failure
    halfway costs one chunk rather than the run.

    Resolution matters more than it looks: the presenter ends up as a ~340px
    inset, so driving at 512 wide is already oversampled and costs a quarter of
    the memory of 1080p.
    """
    workdir = workdir or out.parent / f"_{out.stem}_chunks"
    workdir.mkdir(parents=True, exist_ok=True)
    total = duration(audio)
    pieces, at, index = [], 0.0, 0

    while at < total - 0.05:
        span = min(chunk, total - at)
        a_part = workdir / f"a{index:03d}.wav"
        v_part = workdir / f"v{index:03d}.mp4"
        o_part = workdir / f"o{index:03d}.mp4"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{at:.3f}",
                        "-t", f"{span:.3f}", "-i", str(audio), "-ac", "1",
                        "-ar", "16000", str(a_part)], check=True)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{at:.3f}",
                        "-t", f"{span:.3f}", "-i", str(video),
                        "-vf", f"scale={width}:-2,fps={FPS}", "-an",
                        "-c:v", "libx264", "-crf", "18", "-preset", "medium",
                        "-pix_fmt", "yuv420p", str(v_part)], check=True)
        if not o_part.exists():
            print(f"  chunk {index}  {at:.0f}s -> {at + span:.0f}s")
            sync(v_part, a_part, o_part, steps, guidance)
        pieces.append(o_part)
        at += span
        index += 1

    # LatentSync emits whole 16-frame windows, so it returns slightly LESS video
    # than the audio it was given: 20s at 25fps is 500 frames, which truncates to
    # 496 -- 160ms short, every chunk. Concatenated raw, that accumulates into
    # visible lip drift (1.4s over a three-minute cut). Each piece is retimed
    # back to its own audio length before joining, which spreads ~0.8% across the
    # chunk rather than leaving a hole at each seam.
    fixed = []
    for index, piece in enumerate(pieces):
        want = duration(workdir / f"a{index:03d}.wav")
        got = duration(piece)
        if abs(want - got) < 0.005:
            fixed.append(piece)
            continue
        stretched = piece.with_name(f"{piece.stem}-fit.mp4")
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", str(piece),
             "-vf", f"setpts=PTS*{want / got:.9f},fps={FPS}",
             "-c:v", "libx264", "-crf", "18", "-preset", "medium",
             "-pix_fmt", "yuv420p", "-an", str(stretched)],
            check=True)
        fixed.append(stretched)
    pieces = fixed

    listing = workdir / "parts.txt"
    listing.write_text("".join(f"file '{p.resolve().as_posix()}'\n" for p in pieces),
                       encoding="utf-8")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
                    "-i", str(listing), "-c:v", "libx264", "-crf", "18",
                    "-preset", "medium", "-pix_fmt", "yuv420p", "-r", str(FPS),
                    "-an", str(out)], check=True)
    print(f"  lipsync  {out.name}  {duration(out):.1f}s  ({len(pieces)} chunks)")
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
    s.add_argument("--chunk", type=float, default=0.0,
                   help="seconds per chunk; required for anything over ~30s")
    s.add_argument("--width", type=int, default=512, help="driver width when chunking")

    args = ap.parse_args()
    if args.cmd == "prepare":
        prepare(Path(args.src), Path(args.out), args.start, args.dur, args.width)
    elif args.cmd == "loop":
        loop(Path(args.src), Path(args.out), args.seconds)
    elif args.chunk:
        sync_chunked(Path(args.video), Path(args.audio), Path(args.out),
                     args.chunk, args.steps, args.guidance, args.width)
    else:
        sync(Path(args.video), Path(args.audio), Path(args.out), args.steps,
             args.guidance, config=Path(args.config) if args.config else None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
