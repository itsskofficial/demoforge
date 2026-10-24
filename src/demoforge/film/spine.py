"""The voice spine: every line in order, trimmed to its speech, with designed gaps.

The spine is the film's master clock. Every scene, caption, cut and music
entry is timed against it, so it is built first and written as audio and as a
table (`spine.json`: each line's source in/out and where it sits in the film).

How a line is trimmed is the result of having trimmed them badly first:

- From a 5 ms full-band envelope, never from transcript times. Whisper's word
  times drift by tenths after silence, and a band-limited envelope hides the
  /s/ and /f/ that a clipped word is made of.
- Speech is anything 14 dB over the clip's own room tone (its 10th percentile).
- Every in and out point is a whole frame, so a line's picture and sound can
  never drift apart, and every clip is a whole number of frames long.
- The silence between lines is designed, speech end to speech start, with a
  per-line `gap_after` for the breaths. Tails are generous by default and only
  tightened line by line: on an approved look-away, or with `tail_cut` where a
  take carries the start of the next word.
- Spans inside a line are removed with a short crossfade, not a hard cut.
"""

from __future__ import annotations

import subprocess
from dataclasses import asdict, dataclass

import numpy as np

from demoforge.film.project import Project, frame, load_audio, write_json

STEP_SECONDS = 0.005


@dataclass
class Clip:
    seq: str
    voice: str
    cam: str | None
    src_in: float
    src_out: float
    removed: list
    start: float = 0.0
    end: float = 0.0


def envelope(a: np.ndarray, step: int) -> np.ndarray:
    """dB RMS of every `step` samples, full band, both channels summed to mono."""
    mono = a.mean(axis=1) if a.ndim == 2 else a
    n = len(mono) // step
    frames = mono[: n * step].reshape(n, step)
    return 20 * np.log10(np.sqrt((frames ** 2).mean(axis=1)) + 1e-7)


def speech_span(db: np.ndarray, step: int, sr: int, percentile: float = 10,
                over: float = 14.0) -> tuple[float, float]:
    """First and last window that is clearly speech: `over` dB above the room tone."""
    floor = np.percentile(db, percentile)
    loud = np.nonzero(db > floor + over)[0]
    if not len(loud):
        raise ValueError("no speech found")
    return loud[0] * step / sr, (loud[-1] + 1) * step / sr


def remove_span(seg: np.ndarray, i0: int, i1: int, x: int) -> np.ndarray:
    """Cut samples [i0, i1) out, crossfading the x samples before each edge."""
    ramp = np.linspace(0, 1, x, dtype=np.float32)[:, None]
    joined = seg[i0 - x: i0] * (1 - ramp) + seg[i1 - x: i1] * ramp
    return np.concatenate([seg[: i0 - x], joined, seg[i1:]])


def build(p: Project) -> dict:
    sp, fps, sr = p.cfg["spine"], p.fps, p.sr
    step = int(round(sr * STEP_SECONDS))
    look = p.lookaways
    cams = {s: f.name for s, f in p.sources("camera").items()} if p.path("camera").exists() else {}
    voices = p.sources("voice")
    if not voices:
        raise SystemExit(f"no voice lines in {p.path('voice')} matching {p.cfg['sources']['voice']}")

    clips: list[Clip] = []
    pieces: list[np.ndarray] = []
    t = frame(sp["lead_in"], fps, up=True)
    pieces.append(np.zeros((int(round(t * sr)), 2), np.float32))
    prev_speech_end = prev_seq = None

    for seq, path in voices.items():
        a = load_audio(path, sr)
        dur = len(a) / sr
        on, off = speech_span(envelope(a, step), step, sr, sp["floor_percentile"], sp["speech_db"])
        src_in = max(0.0, frame(on - sp["lead"], fps, up=False))
        limit = dur - sp["tail_cut"].get(seq, 0.0)
        tail = sp["lookaway_tail"] if seq in look else sp["tail"]
        src_out = min(frame(limit, fps, up=False), frame(off + tail, fps, up=True))

        # place it: the gap is speech to speech, then out to a frame
        if prev_speech_end is not None:
            gap = (sp["lookaway_gap_after"].get(prev_seq, sp["lookaway_gap"]) if prev_seq in look
                   else sp["gap_after"].get(prev_seq, sp["gap"]))
            want = prev_speech_end + gap - (on - src_in)
            t = max(t, frame(want, fps, up=True))
            silence = int(round(t * sr)) - sum(len(x) for x in pieces)
            pieces.append(np.zeros((max(0, silence), 2), np.float32))

        seg = a[int(round(src_in * sr)): int(round(src_out * sr))].copy()
        removed = []
        for r0, r1 in sp["remove"].get(seq, []):
            i0, i1 = int(round((r0 - src_in) * sr)), int(round((r1 - src_in) * sr))
            seg = remove_span(seg, i0, i1, int(sp["remove_xfade"] * sr))
            removed.append([r0, r1])
        # whole frames, then short fades so no join can click
        keep = int(round(len(seg) / sr * fps)) * sr // fps
        seg = seg[:keep]
        f = int(sp["edge_fade"] * sr)
        seg[:f] *= np.linspace(0, 1, f, dtype=np.float32)[:, None]
        seg[-f:] *= np.linspace(1, 0, f, dtype=np.float32)[:, None]

        c = Clip(seq, path.name, cams.get(seq), round(src_in, 4), round(src_out, 4), removed,
                 start=round(t, 4), end=round(t + len(seg) / sr, 4))
        clips.append(c)
        pieces.append(seg)
        t = c.end
        prev_speech_end = c.start + (off - src_in) - sum(r1 - r0 for r0, r1 in removed)
        prev_seq = seq

    audio = np.concatenate(pieces + [np.zeros((int(round(sp["end_hold"] * sr)), 2), np.float32)])
    out = p.spine_dir
    out.mkdir(parents=True, exist_ok=True)
    raw = out / "voice_raw.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "f32le", "-ar", str(sr), "-ac", "2", "-i", "-",
                    "-c:a", "pcm_s24le", str(raw)], input=audio.tobytes(), check=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(raw), "-af", sp["chain"],
                    "-ar", str(sr), "-c:a", "pcm_s24le", str(out / "voice.wav")], check=True)
    meta = {"fps": fps, "sample_rate": sr, "duration": round(len(audio) / sr, 4),
            "clips": [asdict(c) for c in clips]}
    write_json(out / "spine.json", meta)
    print(f"spine: {len(clips)} lines, {len(audio) / sr:.2f}s -> {out}")
    for c in clips:
        print(f"  {c.seq} {'CAM' if c.cam else '   '} {c.start:7.3f}-{c.end:7.3f}"
              f"  src {c.src_in:6.3f}-{c.src_out:6.3f}")
    return meta
