"""Check a film the way it gets sent back: dark flashes, clipped words, missing captions.

    dark       every frame of the render, at a small size: a frame much darker
               than both its neighbours is a dropped frame, and a lit frame
               followed by a black one is a blackout (Chrome's capture does
               this when a filter switches on over video: the pitch film's v3
               went from 105 to 3 in one frame mid-leak). One frame is all a
               viewer needs to see it.
    joins      every line's edges on the voice waveform: speech energy in the
               first or last 5 ms of a clip means a trim cut into a word; and
               every line's loudness against the others
    captions   every word inside a cue, and no two cues on screen at once
    sheets     labelled contact sheets of every scene boundary (two frames
               before the cut, the cut, two after), for the eye

Writes qa.json and the sheets to work/qa/ and prints what needs a look.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np

from demoforge.film.project import Project, load_audio, read_json, write_json
from demoforge.film.spine import envelope

# -- dark frames --------------------------------------------------------------


def dark_frames(luma: np.ndarray, ratio: float = 0.6, drop: float = 12.0) -> list[int]:
    """Indices of isolated dark frames: darker than `ratio` x the dimmer neighbour,
    at least `drop` levels below it, and a dip far deeper than the picture is
    changing anyway. A fade or a dip to black moves its neighbours too, so it
    never qualifies; a single dropped frame in steady picture does."""
    y = np.asarray(luma, float)
    if len(y) < 3:
        return []
    pad = np.concatenate([y[:1], y, y[-1:]])
    mid, prev, nxt = pad[2:-2], pad[1:-3], pad[3:-1]
    outer_prev, outer_next = pad[:-4], pad[4:]
    near = np.minimum(prev, nxt)
    depth = near - mid
    moving = np.maximum(np.abs(prev - outer_prev), np.abs(nxt - outer_next))
    hit = (mid < near * ratio) & (depth > drop) & (depth > 2 * moving)
    return [int(i) + 1 for i in np.nonzero(hit)[0]]


def blackouts(luma: np.ndarray, black: float = 8.0, lit: float = 40.0) -> list[int]:
    """Frames that are black right after a lit one. Designed darkness ramps (a dip
    takes nine frames); a capture fault arrives in one."""
    y = np.asarray(luma, float)
    return [int(i) + 1 for i in np.nonzero((y[1:] < black) & (y[:-1] > lit))[0]]


def lumas(video: Path, width: int = 160, height: int = 90) -> np.ndarray:
    proc = subprocess.Popen(["ffmpeg", "-v", "error", "-i", str(video), "-vf", f"scale={width}:{height}",
                             "-f", "rawvideo", "-pix_fmt", "gray", "-"], stdout=subprocess.PIPE)
    size, out = width * height, []
    while True:
        raw = proc.stdout.read(size)
        if len(raw) < size:
            break
        out.append(np.frombuffer(raw, np.uint8).mean())
    proc.wait()
    return np.array(out)


# -- joins --------------------------------------------------------------------


def edge_speech(voice: np.ndarray, clips: list[dict], sr: int, over: float = 14.0,
                edge: float = 0.005) -> list[dict]:
    """Lines whose first or last `edge` seconds carry speech, and each line's level."""
    step = int(round(sr * 0.005))
    rows = []
    for c in clips:
        seg = voice[int(round(c["start"] * sr)): int(round(c["end"] * sr))]
        db = envelope(seg, step)
        if not len(db):
            continue
        floor = np.percentile(db, 10)
        k = max(1, int(round(edge / 0.005)))
        # the 4 ms edge fades sit inside the first and last window; look one in
        head, tail = db[k: 2 * k].max(), db[-2 * k: -k].max() if len(db) > 2 * k else db[-1]
        speech = db[db > floor + over]
        rows.append({"seq": c["seq"], "head_db": round(float(head - floor), 1),
                     "tail_db": round(float(tail - floor), 1),
                     "level_db": round(float(np.median(speech)) if len(speech) else -99.0, 1),
                     "clipped_head": bool(head > floor + over), "clipped_tail": bool(tail > floor + over)})
    if rows:
        med = float(np.median([r["level_db"] for r in rows]))
        for r in rows:
            r["level_off"] = round(r["level_db"] - med, 1)
    return rows


def caption_gaps(words: list[dict], cues: list[dict]) -> dict[str, list]:
    uncovered = [w for w in words if not any(c["s"] - 0.02 <= w["s"] < c["e"] for c in cues)]
    overlap = [(a["text"], b["text"]) for a, b in zip(cues, cues[1:]) if a["e"] > b["s"]]
    return {"uncovered": [f"{w['seq']} {w['w']} @{w['s']}" for w in uncovered], "overlapping": overlap}


# -- contact sheets -----------------------------------------------------------


def grab(video: Path, t: float, width: int) -> np.ndarray:
    h = width * 9 // 16
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{max(0.0, t):.4f}", "-i", str(video),
                          "-frames:v", "1", "-vf", f"scale={width}:{h}", "-f", "rawvideo", "-pix_fmt", "bgr24", "-"],
                         capture_output=True).stdout
    if len(raw) < width * h * 3:
        return np.zeros((h, width, 3), np.uint8)
    return np.frombuffer(raw, np.uint8).reshape(h, width, 3).copy()


def sheet(cells: list[tuple[np.ndarray, str]], cols: int, out: Path) -> Path:
    import cv2
    h, w = cells[0][0].shape[:2]
    rows = (len(cells) + cols - 1) // cols
    board = np.full((rows * (h + 24), cols * w, 3), 16, np.uint8)
    for i, (img, label) in enumerate(cells):
        r, c = divmod(i, cols)
        y, x = r * (h + 24), c * w
        board[y + 24: y + 24 + h, x: x + w] = img
        cv2.putText(board, label, (x + 4, y + 17), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (230, 230, 230), 1, cv2.LINE_AA)
    out.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out), board)
    return out


def boundary_sheets(video: Path, joins: list[dict], fps: int, out: Path, per: int = 6,
                    width: int = 320) -> list[Path]:
    offsets = [-2, -1, 0, 1, 2]
    paths = []
    for k in range(0, len(joins), per):
        cells = []
        for j in joins[k: k + per]:
            for o in offsets:
                t = j["t"] + o / fps
                cells.append((grab(video, t, width), f"{j['out']}>{j['in']} {j['kind']} {o:+d}f {t:.2f}s"))
        paths.append(sheet(cells, len(offsets), out / f"joins_{k // per + 1:02d}.png"))
    return paths


def scene_at(scenes: list[dict], t: float) -> str:
    return next((s["id"] for s in scenes if s["start"] <= t < s["end"]), "?")


def run(p: Project, video: Path | None = None, sheets: bool = True) -> dict:
    out = p.work / "qa"
    report: dict = {}
    clips = p.spine()["clips"]
    voice = load_audio(p.spine_dir / "voice.wav", p.sr)
    report["joins"] = edge_speech(voice, clips, p.sr)
    for r in report["joins"]:
        if r["clipped_head"] or r["clipped_tail"]:
            print(f"  ! {r['seq']}: speech at the {'start' if r['clipped_head'] else 'end'} of the clip "
                  f"({max(r['head_db'], r['tail_db']):.0f} dB over the room): a clipped word?")
        if abs(r.get("level_off", 0)) > 4:
            print(f"  ! {r['seq']}: {r['level_off']:+.1f} dB against the median line")
    words = read_json(p.spine_dir / "words.json")
    cues = read_json(p.spine_dir / "cues.json")
    report["captions"] = caption_gaps(words, cues)
    for w in report["captions"]["uncovered"]:
        print(f"  ! no caption for {w}")
    for a, b in report["captions"]["overlapping"]:
        print(f"  ! cues overlap: {a!r} / {b!r}")
    if video:
        tl = p.timeline()
        cache = out / f"luma_{video.stem}.npy"
        if cache.exists() and cache.stat().st_mtime > video.stat().st_mtime:
            y = np.load(cache)
        else:
            y = lumas(video)
            out.mkdir(parents=True, exist_ok=True)
            np.save(cache, y)
        dark = sorted(set(dark_frames(y)) | set(blackouts(y)))
        report["frames"] = len(y)
        report["dark"] = [{"frame": i, "t": round(i / p.fps, 3), "scene": scene_at(tl["scenes"], i / p.fps),
                           "luma": round(float(y[i]), 1),
                           "neighbours": [round(float(y[i - 1]), 1), round(float(y[i + 1]), 1)]} for i in dark]
        print(f"  {len(y)} frames, {len(y) / p.fps:.2f}s; {len(dark)} dark frame(s) or blackout(s)")
        for d in report["dark"]:
            print(f"  ! dark frame {d['frame']} at {d['t']}s in {d['scene']}: {d['luma']} vs {d['neighbours']}")
        if sheets:
            joins = read_json(p.emit / "transitions.json")["joins"]
            report["sheets"] = [str(s) for s in boundary_sheets(video, joins, p.fps, out)]
            print(f"  {len(report['sheets'])} contact sheet(s) in {out}")
    write_json(out / "qa.json", report)
    print(f"qa -> {out / 'qa.json'}")
    return report
