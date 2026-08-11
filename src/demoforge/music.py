"""A background bed, and the ducking that keeps it out of the way.

Two jobs. The first is getting a track: either yours, or one synthesised here
from scratch. Synthesised is the default because a demo you publish should not
carry someone else's copyright, and "royalty-free lofi" downloads are a licence
audit waiting to happen. What is generated here is a few sine waves, filtered
noise and an envelope -- nobody owns it.

The second job matters more than the track does: **ducking**. Music at a fixed
level either buries the narration or is inaudible. A sidechain compressor makes
the bed step back whenever the voice is present and swell in the gaps, which is
what makes a demo feel scored rather than soundtracked.

    python -m demoforge.music bed --seconds 180 --style lofi
    python -m demoforge.music mix --video cut.mp4 --music bed.wav --out final.mp4
"""

from __future__ import annotations

import argparse
import math
import subprocess
import sys
import wave
from pathlib import Path

from demoforge.config import AUDIO, OUT

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

RATE = 44100

# Seventh chords in a low register: they sit under speech without competing for
# the same frequencies a voice occupies.
PROGRESSIONS = {
    # Fmaj7 - Em7 - Dm7 - Cmaj7, the four chords every lofi tape is built on
    "lofi": [(174.61, 220.00, 261.63, 329.63),
             (164.81, 196.00, 246.94, 293.66),
             (146.83, 174.61, 220.00, 261.63),
             (130.81, 164.81, 196.00, 246.94)],
    # Minor and sparser, for something with more edge under it
    "trap": [(146.83, 174.61, 220.00, 293.66),
             (130.81, 155.56, 196.00, 261.63),
             (174.61, 207.65, 261.63, 349.23),
             (155.56, 185.00, 233.08, 311.13)],
}

STYLES = {
    "lofi": dict(bpm=74, swing=0.14, hats=2, sub=False, air=0.020, wobble=0.5),
    "trap": dict(bpm=140, swing=0.0, hats=4, sub=True, air=0.008, wobble=0.2),
}


def _write(path: Path, samples, rate: int = RATE) -> Path:
    import numpy as np

    peak = float(np.max(np.abs(samples))) or 1.0
    pcm = np.clip(samples / peak * 0.87, -1, 1)
    stereo = np.stack([pcm, np.roll(pcm, 90)], axis=1)   # a hair of width
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as f:
        f.setnchannels(2)
        f.setsampwidth(2)
        f.setframerate(rate)
        f.writeframes((stereo * 32767).astype("<i2").tobytes())
    return path


def _env(n: int, attack: float, decay: float, rate: int = RATE):
    import numpy as np

    t = np.arange(n) / rate
    rise = np.clip(t / max(attack, 1e-4), 0, 1)
    fall = np.exp(-t / max(decay, 1e-4))
    return rise * fall


def bed(seconds: float, out: Path, style: str = "lofi", seed: int = 0) -> Path:
    """Synthesise a loopable backing bed.

    Deliberately dull: soft attacks, a low-pass on everything, no melody on top.
    A bed with a tune in it competes with the narration for attention, and the
    narration has to win.
    """
    import numpy as np

    cfg = STYLES.get(style, STYLES["lofi"])
    rng = np.random.default_rng(seed)
    n = int(seconds * RATE)
    mix = np.zeros(n)

    beat = 60.0 / cfg["bpm"]
    bar = beat * 4
    chords = PROGRESSIONS.get(style, PROGRESSIONS["lofi"])

    # --- pads: one chord per bar, slow attack, detuned a touch for warmth ----
    bars = int(seconds / bar) + 1
    for b in range(bars):
        start = int(b * bar * RATE)
        length = min(int(bar * RATE * 1.05), n - start)
        if length <= 0:
            break
        t = np.arange(length) / RATE
        chord = chords[b % len(chords)]
        voice = np.zeros(length)
        for i, freq in enumerate(chord):
            detune = 1 + (rng.random() - 0.5) * 0.0022
            # A slow tremolo stands in for tape wow, which is most of what makes
            # this sound like a cassette rather than a synth patch.
            wobble = 1 + cfg["wobble"] * 0.012 * np.sin(2 * math.pi * 0.7 * t + i)
            voice += np.sin(2 * math.pi * freq * detune * t * wobble) / (i + 2.0)
        mix[start:start + length] += voice * _env(length, 0.35, bar * 0.9) * 0.55

    # --- drums ---------------------------------------------------------------
    steps = int(seconds / (beat / 2)) + 1
    for step in range(steps):
        swing = cfg["swing"] * (beat / 2) if step % 2 else 0.0
        at = int((step * beat / 2 + swing) * RATE)
        if at >= n:
            break
        eighth = step % 8

        if eighth in (0, 6):                       # kick, on 1 and the "and" of 4
            length = min(int(0.30 * RATE), n - at)
            t = np.arange(length) / RATE
            sweep = 118 * np.exp(-t * 26) + 44
            mix[at:at + length] += np.sin(2 * math.pi * sweep * t) * _env(length, 0.002, 0.10) * 1.5
            if cfg["sub"]:
                mix[at:at + length] += np.sin(2 * math.pi * 41 * t) * _env(length, 0.004, 0.55) * 1.1

        if eighth == 4:                            # snare / rim on 3
            length = min(int(0.19 * RATE), n - at)
            noise = rng.normal(0, 1, length)
            body = np.sin(2 * math.pi * 188 * np.arange(length) / RATE)
            mix[at:at + length] += (noise * 0.55 + body * 0.45) * _env(length, 0.001, 0.055) * 0.75

        for h in range(cfg["hats"]):               # hats, subdivided per style
            hat_at = at + int(h * (beat / 2 / cfg["hats"]) * RATE)
            length = min(int(0.05 * RATE), n - hat_at)
            if length <= 0 or hat_at >= n:
                continue
            amp = 0.16 if h == 0 else 0.085
            mix[hat_at:hat_at + length] += rng.normal(0, 1, length) * _env(length, 0.0005, 0.017) * amp

    # --- vinyl air -----------------------------------------------------------
    mix += rng.normal(0, cfg["air"], n)

    # --- one-pole low pass: takes the fizz off everything above ~2kHz ---------
    alpha = 0.16
    smoothed = np.empty(n)
    acc = 0.0
    for i in range(n):
        acc += alpha * (mix[i] - acc)
        smoothed[i] = acc

    # Fade in and out so a loop can be cut anywhere without a click.
    fade = int(2.2 * RATE)
    smoothed[:fade] *= np.linspace(0, 1, fade)
    smoothed[-fade:] *= np.linspace(1, 0, fade)

    _write(out, smoothed)
    print(f"  bed  {out.name}  {seconds:.0f}s  {style}  {cfg['bpm']}bpm")
    return out


def mix(video: Path, music: Path, out: Path, music_db: float = -23.0,
        duck_db: float = -14.0) -> Path:
    """Lay `music` under `video`, ducking it whenever the narration speaks.

    `music_db` is the resting level of the bed; `duck_db` is how far it drops
    under speech. The narration itself is never touched -- compressing the voice
    to make room for the music is backwards.
    """
    has_audio = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries",
         "stream=index", "-of", "csv=p=0", str(video)],
        capture_output=True, text=True).stdout.strip()
    if not has_audio:
        raise SystemExit(f"{video.name} has no narration track to duck against")

    out.parent.mkdir(parents=True, exist_ok=True)
    # sidechaincompress listens to the voice and pulls the music down; the
    # release is long so the bed rises back gradually between sentences rather
    # than pumping on every pause for breath.
    graph = (
        f"[1:a]aloop=loop=-1:size=2e9,volume={music_db}dB[bed];"
        f"[0:a]asplit=2[voice][key];"
        f"[bed][key]sidechaincompress=threshold=0.02:ratio=12:attack=8:"
        f"release=650:makeup=1:level_sc=1[ducked];"
        f"[ducked]volume={duck_db}dB[quiet];"
        f"[voice][quiet]amix=inputs=2:duration=first:dropout_transition=0,"
        f"loudnorm=I=-16:TP=-1.5:LRA=11[a]"
    )
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(video), "-i", str(music),
         "-filter_complex", graph, "-map", "0:v", "-map", "[a]",
         "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
         "-movflags", "+faststart", str(out)],
        check=True)
    print(f"  {out.name}  music under narration ({music_db:+.0f}dB, ducking {duck_db:+.0f}dB)")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("bed", help="synthesise a backing track")
    b.add_argument("--seconds", type=float, required=True)
    b.add_argument("--style", default="lofi", choices=sorted(STYLES))
    b.add_argument("--seed", type=int, default=0)
    b.add_argument("--out", default=str(AUDIO / "bed.wav"))

    m = sub.add_parser("mix", help="lay a bed under a narrated cut")
    m.add_argument("--video", required=True)
    m.add_argument("--music", default=str(AUDIO / "bed.wav"))
    m.add_argument("--out", default=str(OUT / "final-scored.mp4"))
    m.add_argument("--music-db", type=float, default=-23.0)
    m.add_argument("--duck-db", type=float, default=-14.0)

    args = ap.parse_args()
    if args.cmd == "bed":
        bed(args.seconds, Path(args.out), args.style, args.seed)
    else:
        mix(Path(args.video), Path(args.music), Path(args.out),
            args.music_db, args.duck_db)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
