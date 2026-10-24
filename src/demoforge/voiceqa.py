"""Measure a narration read, so pacing and expressiveness stop being opinions.

I cannot listen to the audio I generate, and "sounds monotone" is exactly the
kind of judgement that gets made by ear and then argued about. These are the
proxies that actually track it:

* **Pitch variation** -- the standard measure of monotony. Reported in
  semitones so it is comparable across speakers regardless of their base pitch.
  A flat read sits under ~2 semitones of standard deviation; natural narration
  is roughly 2.5-4.
* **Loudness variation** -- expressive speech leans in and backs off. A read
  with a flat energy envelope sounds recited.
* **Pause structure** -- how many silences, how long, and what fraction of the
  clip is speech. Uniform gaps are the giveaway of chunk-based generation.
* **Rate** -- words per minute, and how much it varies between phrases. A human
  speeds up through an aside and slows into a point; TTS often does neither.

The reference clip is the target, not an abstract ideal: it is the person the
clone is imitating, so its own numbers are what "sounds like them" means.

    python -m demoforge.voiceqa out/audio/lab/*.wav --reference assets/voice/reference.wav
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

FMIN, FMAX = 60.0, 400.0     # human speech, generously bounded
SILENCE_DB = -38.0           # below this counts as a pause
MIN_PAUSE = 0.12             # shorter than this is a stop consonant, not a pause


def analyse(path: Path, words: int | None = None) -> dict:
    import librosa
    import numpy as np

    y, sr = librosa.load(str(path), sr=22050, mono=True)
    seconds = len(y) / sr

    # --- pitch: the monotony measure ---------------------------------------
    f0, voiced, _ = librosa.pyin(y, fmin=FMIN, fmax=FMAX, sr=sr,
                                 frame_length=2048, hop_length=256)
    f0v = f0[~np.isnan(f0)]
    if f0v.size > 8:
        semitones = 12 * np.log2(f0v / np.median(f0v))
        f0_std = float(np.std(semitones))
        f0_range = float(np.percentile(semitones, 95) - np.percentile(semitones, 5))
        f0_med = float(np.median(f0v))
    else:
        f0_std = f0_range = f0_med = 0.0

    # --- loudness variation -------------------------------------------------
    rms = librosa.feature.rms(y=y, frame_length=2048, hop_length=256)[0]
    db = librosa.amplitude_to_db(rms, ref=np.max)
    loud = db[db > SILENCE_DB]
    rms_std = float(np.std(loud)) if loud.size else 0.0

    # --- pauses --------------------------------------------------------------
    hop = 256 / sr
    quiet = db <= SILENCE_DB
    pauses, run = [], 0
    for q in quiet:
        if q:
            run += 1
        elif run:
            if run * hop >= MIN_PAUSE:
                pauses.append(run * hop)
            run = 0
    if run and run * hop >= MIN_PAUSE:
        pauses.append(run * hop)
    speech_ratio = float(1 - (sum(pauses) / seconds)) if seconds else 0.0

    return {
        "file": path.name,
        "seconds": round(seconds, 2),
        "wpm": round(words / seconds * 60, 0) if words else None,
        "pitch_semitone_sd": round(f0_std, 2),
        "pitch_range_st": round(f0_range, 2),
        "pitch_median_hz": round(f0_med, 0),
        "loudness_sd_db": round(rms_std, 2),
        "pauses": len(pauses),
        "pause_mean_s": round(sum(pauses) / len(pauses), 2) if pauses else 0.0,
        "pause_sd_s": round(float(__import__("statistics").pstdev(pauses)), 2) if len(pauses) > 1 else 0.0,
        "speech_ratio": round(speech_ratio, 2),
    }


def verdict(row: dict, ref: dict | None) -> str:
    """A short read on the numbers, phrased as what a listener would notice."""
    notes = []
    sd = row["pitch_semitone_sd"]
    if sd < 1.8:
        notes.append("flat")
    elif sd > 4.5:
        notes.append("sing-song")
    if row["loudness_sd_db"] < 4.0:
        notes.append("no dynamics")
    if row["pauses"] and row["pause_sd_s"] < 0.06 and row["pauses"] > 2:
        notes.append("uniform gaps")
    if row["wpm"] and row["wpm"] > 195:
        notes.append("rushed")
    if row["wpm"] and row["wpm"] < 135:
        notes.append("dragging")
    if ref and sd < ref["pitch_semitone_sd"] * 0.7:
        notes.append(f"flatter than you ({sd} vs {ref['pitch_semitone_sd']})")
    return ", ".join(notes) or "ok"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="+")
    ap.add_argument("--reference", default=None, help="the human clip being cloned")
    ap.add_argument("--words", type=int, default=None, help="word count of the script")
    args = ap.parse_args()

    ref = None
    if args.reference:
        ref = analyse(Path(args.reference))
        print(f"\n  REFERENCE (you): pitch sd {ref['pitch_semitone_sd']} st, "
              f"range {ref['pitch_range_st']} st, loudness sd {ref['loudness_sd_db']} dB, "
              f"median {ref['pitch_median_hz']:.0f} Hz\n")

    print(f"  {'file':<34} {'wpm':>4} {'pitchSD':>8} {'range':>6} {'loudSD':>7} "
          f"{'paus':>5} {'pSD':>5}  notes")
    rows = []
    for f in args.files:
        p = Path(f)
        if not p.exists():
            continue
        r = analyse(p, args.words)
        rows.append(r)
        print(f"  {r['file'][:34]:<34} {r['wpm'] or 0:>4.0f} {r['pitch_semitone_sd']:>8.2f} "
              f"{r['pitch_range_st']:>6.2f} {r['loudness_sd_db']:>7.2f} {r['pauses']:>5} "
              f"{r['pause_sd_s']:>5.2f}  {verdict(r, ref)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
