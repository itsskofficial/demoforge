"""The ffprobe and ffmpeg plumbing every mode shares.

Each mode grew its own copy of these -- a duration here, a loudness reading
there, the same voice chain typed out three times with one number different.
They live here now so that a fix to how a file is measured lands in every mode
at once, and so that `short` and `tools` stop reaching into `reel` for a
private helper.

Measurements first (`duration`, `loudness`, `size`, `probe`, `has_video`,
`has_audio`), then the sound steps the voiced modes share (`clean_voice`,
`level_bed`, `master`), then choosing a music bed (`drive`, `local_track`,
`sourced_track`). Everything here takes paths and returns paths or numbers;
nothing knows which mode called it.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# measuring a file
# ---------------------------------------------------------------------------


def duration(path: Path) -> float:
    return float(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True, check=True).stdout.strip())


def loudness(path: Path) -> float | None:
    """Integrated loudness of a file's audio, in LUFS.

    Returns None rather than raising: a missing measurement is a reason to
    fall back to a fixed gain, not a reason to lose the render.
    """
    result = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-map", "0:a",
         "-af", "ebur128=framelog=quiet", "-f", "null", "-"],
        capture_output=True, text=True)
    found = re.findall(r"I:\s*(-?\d+\.\d+)\s*LUFS", result.stderr)
    return float(found[-1]) if found else None


def size(path: Path) -> tuple[int, int]:
    """Width and height of the first video stream."""
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=width,height", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True).stdout.strip()
    width, height = (int(v) for v in out.split(",")[:2])
    return width, height


def probe(video: Path) -> tuple[int, int, float]:
    """Width, height and duration in one call. Zeros for what is not there."""
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=width,height:format=duration", "-of", "json", str(video)],
        capture_output=True, text=True, check=True).stdout
    data = json.loads(out)
    stream = (data.get("streams") or [{}])[0]
    return (int(stream.get("width") or 0), int(stream.get("height") or 0),
            float(data.get("format", {}).get("duration") or 0))


def _has(path: Path, kind: str) -> bool:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", f"{kind}:0",
         "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True).stdout.strip()
    return bool(out)


def has_video(path: Path) -> bool:
    return _has(path, "v")


def has_audio(path: Path) -> bool:
    return _has(path, "a")


# ---------------------------------------------------------------------------
# sound
# ---------------------------------------------------------------------------


def clean_voice(src: Path, out: Path, highpass: int = 90) -> Path:
    """Denoise and shape the voice, picture untouched.

    Done before any music arrives, or the compressor spends its range on hiss.
    PCM out because this is an intermediate that is measured and mixed again.
    """
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(src),
         "-af", f"highpass=f={highpass},afftdn=nr=10:nf=-28,"
                "acompressor=threshold=-20dB:ratio=3:attack=8:release=180,"
                "alimiter=limit=0.95",
         "-c:v", "copy", "-c:a", "pcm_s16le", str(out)],
        check=True)
    return out


def level_bed(track: Path, out: Path, offset: float = 0.0) -> Path:
    """A music track normalised flat before it is placed.

    A sourced cue is mastered to whatever its producer felt like and its own
    loudness wanders across the track, which is heard as music present in one
    gap and absent in the next. `offset` starts a few bars in, so the film
    opens on a track that is already going.
    """
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{offset:.2f}",
         "-i", str(track), "-af", "loudnorm=I=-18:TP=-2:LRA=5", "-ar", "48000",
         "-c:a", "pcm_s16le", str(out)],
        check=True)
    return out


def master(src: Path, out: Path, lufs: float = -14.0, peak: float = -1.2,
           lra: float = 9.0) -> Path:
    """Normalise last, to a streaming loudness, and make it web-playable.

    After the mix, never before it, or the bed changes the number that was
    normalised to.
    """
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(src),
         "-af", f"loudnorm=I={lufs:g}:TP={peak:g}:LRA={lra:g}", "-c:v", "copy",
         "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out)],
        check=True)
    return out


# ---------------------------------------------------------------------------
# choosing a bed
# ---------------------------------------------------------------------------


def drive(path: Path, seconds: float = 60.0) -> tuple[float, float]:
    """How busy a track is, and how much it moves.

    Onset density separates a beat from a pad: a percussive cue throws several
    energy steps a second and a bed of strings throws almost none. Crest
    factor, on top, says whether the track has an arrangement or is simply
    loud all the way through. Ranking on loudness alone picks the most limited
    track in the folder, which is not the same as the most energetic.
    """
    import numpy as np
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-t", f"{seconds:.0f}",
         "-ac", "1", "-ar", "22050", "-f", "f32le", "-"],
        capture_output=True).stdout
    x = np.frombuffer(raw, dtype=np.float32)
    if x.size < 22050:
        return (0.0, 0.0)
    hop = 512
    frames = x[:len(x) // hop * hop].reshape(-1, hop)
    rms = np.sqrt((frames ** 2).mean(axis=1)) + 1e-9
    steps = np.diff(rms)
    onsets = float((steps > steps.std() * 1.2).sum() / (len(steps) / (22050 / hop)))
    return (onsets, float(rms.std() / rms.mean()))


def local_track(profile: Any, need: float) -> Path | None:
    """The best track in the user's own music, if there is one.

    `profile` is anything with `music_file` and `music_dir`: a reel or short
    profile, or the namespace a tool builds. A pinned file wins outright;
    otherwise the folder is ranked on `drive` among tracks long enough.
    """
    if profile.music_file:
        pinned = Path(profile.music_file).expanduser()
        if not pinned.is_absolute() and profile.music_dir:
            pinned = Path(profile.music_dir).expanduser() / profile.music_file
        if pinned.exists():
            print(f"  bed  {pinned.name}  (pinned)")
            return pinned
        print(f"  music_file not found: {pinned}")
    if not profile.music_dir:
        return None
    folder = Path(profile.music_dir).expanduser()
    if not folder.exists():
        print(f"  music_dir not found: {folder}")
        return None

    ranked = []
    for track in sorted(folder.rglob("*.mp3")) + sorted(folder.rglob("*.wav")):
        length = duration(track)
        if length < need:
            continue
        onsets, crest = drive(track)
        ranked.append((onsets, crest, length, track))
    if not ranked:
        print(f"  nothing in {folder} runs {need:.0f}s")
        return None
    ranked.sort(reverse=True)
    onsets, crest, length, best = ranked[0]
    print(f"  bed  {best.name}  {length:.0f}s  "
          f"{onsets:.1f} onsets/s from {len(ranked)} candidates")
    return best


def sourced_track(profile: Any, need: float, work: Path) -> Path:
    """Pixabay, then a synthesised bed. Never silence.

    `profile` needs `music_query` and `music_style`. Synthesising is the last
    resort because a generated bed is worse than a real cue and enormously
    better than none, and it is the one option that cannot fail on somebody
    else's rate limit.
    """
    from demoforge import music_source
    for query in profile.music_query:
        try:
            slugs = music_source.search(query, limit=8)
        except Exception as exc:
            # Pixabay rate-limits per query rather than per session. Giving up
            # on the whole list because the first was throttled is how a cut
            # ships silent.
            print(f"  \"{query}\" failed ({exc.__class__.__name__}); next")
            continue
        for slug in slugs:
            try:
                found = music_source.fetch(slug, work / "candidates")
            except Exception:
                continue
            if found and duration(found) >= need:
                print(f"  bed  {found.name}  {duration(found):.0f}s  \"{query}\"")
                return found
    print("  nothing sourced; synthesising a bed")
    from demoforge.music import bed as synth
    target = work / "bed.wav"
    synth(need, target, style=profile.music_style, seed=11)
    return target
