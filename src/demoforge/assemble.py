"""Fit the picture to the narration, then mux them into one cut.

The pacing of a segment is guessed when it is rendered and only *known* once
the narration has been spoken, so this runs after `voice script`: it reads the
measured length of each line, extends any segment that is shorter than the
words that go over it, and lays the audio underneath.

Extending means freezing the last frame rather than slowing the footage down.
A terminal that is already sitting still on its final output looks identical
held for four more seconds; ramped to 0.7x it looks broken.

    python -m demoforge.assemble --narration out/audio/narration.json
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from demoforge.config import AUDIO, OUT, SEGMENTS

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

# Breathing room after a line ends before the next segment cuts in.
TAIL = 0.9


def duration(path: Path) -> float:
    return float(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True, check=True).stdout.strip())


def pad_to(src: Path, dst: Path, seconds: float) -> None:
    """Hold the final frame until the segment lasts `seconds`."""
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(src),
         "-vf", f"tpad=stop_mode=clone:stop_duration={seconds:.3f}",
         "-c:v", "libx264", "-preset", "medium", "-crf", "18",
         "-pix_fmt", "yuv420p", "-r", "30", str(dst)],
        check=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--narration", default=str(AUDIO / "narration.json"))
    ap.add_argument("--order", default=str(SEGMENTS / "order.json"))
    ap.add_argument("--out", default=str(OUT / "master-narrated.mp4"))
    ap.add_argument("--tail", type=float, default=TAIL)
    args = ap.parse_args()

    narration = {n["id"]: n for n in json.loads(Path(args.narration).read_text("utf-8"))}
    order = json.loads(Path(args.order).read_text("utf-8"))

    fitted = SEGMENTS / "_fitted"
    fitted.mkdir(exist_ok=True)
    audio_dir = Path(args.narration).parent

    plan, video_parts, audio_parts = [], [], []
    for entry in order:
        name = entry["segment"]
        src = SEGMENTS / f"{name}.mp4"
        line = narration.get(name)
        video_len = duration(src)
        if line is None:
            plan.append((name, video_len, None, video_len, "no narration"))
            video_parts.append(src)
            audio_parts.append(None)
            continue

        wanted = line["seconds"] + args.tail
        if wanted > video_len:
            dst = fitted / f"{name}.mp4"
            pad_to(src, dst, wanted - video_len)
            final = duration(dst)
            note = f"held {wanted - video_len:.1f}s longer"
            video_parts.append(dst)
        else:
            final = video_len
            note = f"{video_len - wanted:.1f}s of slack"
            video_parts.append(src)
        plan.append((name, video_len, line["seconds"], final, note))
        audio_parts.append(audio_dir / line["file"])

    print(f"{'segment':<16} {'video':>7} {'voice':>7} {'final':>7}   note")
    for name, v, a, f, note in plan:
        print(f"{name:<16} {v:>7.1f} {a if a else 0:>7.1f} {f:>7.1f}   {note}")

    # One audio track: each line placed at the start of its own segment, padded
    # out to the segment's final length so the two timelines cannot drift.
    silence_specs, concat_audio = [], []
    for (name, _v, _a, final, _n), part in zip(plan, audio_parts):
        piece = fitted / f"{name}.wav"
        if part is None:
            subprocess.run(
                ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
                 "-i", f"anullsrc=r=44100:cl=stereo", "-t", f"{final:.3f}", str(piece)],
                check=True)
        else:
            subprocess.run(
                ["ffmpeg", "-y", "-loglevel", "error", "-i", str(part),
                 "-af", f"aresample=44100,apad=whole_dur={final:.3f}",
                 "-ac", "2", "-t", f"{final:.3f}", str(piece)],
                check=True)
        concat_audio.append(piece)
        silence_specs.append(final)

    vlist = fitted / "_video.txt"
    alist = fitted / "_audio.txt"
    vlist.write_text("".join(f"file '{p.as_posix()}'\n" for p in video_parts), encoding="utf-8")
    alist.write_text("".join(f"file '{p.as_posix()}'\n" for p in concat_audio), encoding="utf-8")

    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error",
         "-f", "concat", "-safe", "0", "-i", str(vlist),
         "-f", "concat", "-safe", "0", "-i", str(alist),
         "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-b:a", "192k", "-shortest",
         "-movflags", "+faststart", args.out],
        check=True)

    total = duration(Path(args.out))
    print(f"\n{Path(args.out).name}  {int(total) // 60}:{total % 60:05.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
