"""Thumbnail candidates from a render: the frames where the face reads best.

A thumbnail of a talking film is a frame of the person, and most frames of a
person talking are bad ones: half-blinks, a mouth mid-vowel, a glance at the
script, motion blur on a turn. So candidates are taken only inside camera
scenes (away from their edges, where transitions sit), every `step` seconds,
and each is scored with mediapipe's face landmarker:

    eyes      both eyes open (lid gap over eye width)
    mouth     closed (lip gap over face width)
    frontal   the nose centred between the eyes (no turn)
    centred   the face near the middle of the frame
    sharp     Laplacian variance of the face crop (no motion blur)

The best N, at least `spacing` seconds apart, are exported as full-resolution
PNGs with a labelled contact sheet. `headlines` are plain frames at given
times (a title card, the end card) exported alongside, unscored.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np

from demoforge.film.project import Project

# 478-point face mesh indices
L_OUT, L_IN, L_TOP, L_BOT = 33, 133, 159, 145
R_IN, R_OUT, R_TOP, R_BOT = 362, 263, 386, 374
LIP_TOP, LIP_BOT, NOSE, FACE_L, FACE_R = 13, 14, 1, 234, 454

WEIGHTS = {"eyes": 2.0, "mouth": 1.5, "frontal": 1.5, "centred": 1.0, "sharp": 1.0}


def spans(scenes: list[dict], kinds: set[str], margin: float = 0.4) -> list[tuple[float, float]]:
    """The inside of every camera scene, clear of the transitions at its edges."""
    return [(s["start"] + margin, s["end"] - margin) for s in scenes
            if s["kind"] in kinds and s["end"] - s["start"] > 2 * margin]


def candidates(scenes: list[dict], kinds: set[str], step: float = 0.25, margin: float = 0.4) -> list[float]:
    times = []
    for a, b in spans(scenes, kinds, margin):
        times += [round(a + k * step, 3) for k in range(int((b - a) / step) + 1) if a + k * step < b]
    return times


def span_frames(video: Path, a: float, b: float, step: float, width: int = 640):
    """(time, rgb) every `step` seconds across [a, b), from one decode."""
    probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                            "stream=width,height", "-of", "csv=p=0", str(video)],
                           capture_output=True, text=True, check=True).stdout.strip().split(",")
    sw, sh = int(probe[0]), int(probe[1])
    h = (int(round(sh * width / sw)) // 2) * 2
    proc = subprocess.Popen(["ffmpeg", "-v", "error", "-ss", f"{a:.3f}", "-t", f"{b - a:.3f}", "-i", str(video),
                             "-vf", f"fps=1/{step},scale={width}:{h}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                            stdout=subprocess.PIPE)
    size, k = width * h * 3, 0
    while True:
        raw = proc.stdout.read(size)
        if len(raw) < size:
            break
        yield round(a + k * step, 3), np.frombuffer(raw, np.uint8).reshape(h, width, 3).copy()
        k += 1
    proc.wait()


def measure(pts, gray: np.ndarray | None = None) -> dict[str, float]:
    """Raw face measures from landmarks (normalised x, y)."""
    x = lambda i: pts[i].x
    y = lambda i: pts[i].y
    fw = abs(x(FACE_R) - x(FACE_L)) or 1e-6
    eye = lambda top, bot, a, b: abs(y(top) - y(bot)) / (abs(x(a) - x(b)) or 1e-6)
    m = {
        "eyes": min(eye(L_TOP, L_BOT, L_OUT, L_IN), eye(R_TOP, R_BOT, R_IN, R_OUT)),
        "mouth": abs(y(LIP_BOT) - y(LIP_TOP)) / fw,
        "yaw": (x(NOSE) - (x(L_OUT) + x(R_OUT)) / 2) / fw,
        "cx": (x(FACE_L) + x(FACE_R)) / 2,
        "fw": fw,
    }
    if gray is not None:
        import cv2
        h, w = gray.shape
        x0, x1 = int(max(0, x(FACE_L) * w)), int(min(w, x(FACE_R) * w))
        y0, y1 = int(max(0, y(10) * h)), int(min(h, y(152) * h))
        crop = gray[y0:y1, x0:x1]
        m["sharp"] = float(cv2.Laplacian(crop, cv2.CV_64F).var()) if crop.size else 0.0
    return m


def score(m: dict[str, float], sharp_ref: float = 1.0) -> dict[str, float]:
    """Each measure to 0..1, and a weighted total."""
    parts = {
        "eyes": float(np.clip((m["eyes"] - 0.12) / 0.18, 0, 1)),
        "mouth": float(np.clip(1 - m["mouth"] / 0.06, 0, 1)),
        "frontal": float(np.clip(1 - abs(m["yaw"]) / 0.08, 0, 1)),
        "centred": float(np.clip(1 - abs(m["cx"] - 0.5) / 0.25, 0, 1)),
        "sharp": float(np.clip(m.get("sharp", 0) / (sharp_ref or 1), 0, 1)),
    }
    parts["total"] = sum(WEIGHTS[k] * v for k, v in parts.items()) / sum(WEIGHTS.values())
    return parts


def pick(rows: list[dict], count: int, spacing: float) -> list[dict]:
    """Best first, never two within `spacing` seconds of each other."""
    chosen = []
    for r in sorted(rows, key=lambda r: -r["total"]):
        if all(abs(r["t"] - c["t"]) >= spacing for c in chosen):
            chosen.append(r)
        if len(chosen) >= count:
            break
    return chosen


def frame_at(video: Path, t: float, width: int | None = None) -> np.ndarray:
    vf = ["-vf", f"scale={width}:-2"] if width else []
    probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                            "stream=width,height", "-of", "csv=p=0", str(video)],
                           capture_output=True, text=True, check=True).stdout.strip().split(",")
    sw, sh = int(probe[0]), int(probe[1])
    w = width or sw
    h = (int(round(sh * w / sw)) // 2) * 2 if width else sh
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-i", str(video), "-frames:v", "1",
                          *vf, "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
    return np.frombuffer(raw[: w * h * 3], np.uint8).reshape(h, w, 3).copy()


def run(p: Project, video: Path, count: int | None = None, headlines: list[float] | None = None) -> list[Path]:
    import cv2
    import mediapipe as mp
    from mediapipe.tasks.python import BaseOptions, vision

    from demoforge.gaze import ensure_model

    cfg = p.cfg["thumbs"]
    count = count or cfg["count"]
    out = p.work / "thumbs"
    out.mkdir(parents=True, exist_ok=True)
    tl = p.timeline()
    todo = spans(tl["scenes"], p.camera_kinds())
    landmarker = vision.FaceLandmarker.create_from_options(vision.FaceLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=str(ensure_model())),
        running_mode=vision.RunningMode.IMAGE, num_faces=1))
    rows = []
    print(f"thumbs: scoring {len(candidates(tl['scenes'], p.camera_kinds(), cfg['step']))} candidate frames"
          f" in {len(todo)} camera scenes")
    for a, b in todo:
        for t, rgb in span_frames(video, a, b, cfg["step"]):
            res = landmarker.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb))
            if res.face_landmarks:
                m = measure(res.face_landmarks[0], cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY))
                rows.append({"t": t, **m})
    if not rows:
        raise SystemExit("thumbs: no face found in any camera scene")
    ref = float(np.percentile([r["sharp"] for r in rows], 90))
    for r in rows:
        r["score"] = score(r, ref)
        r["total"] = r["score"]["total"]
    best = pick(rows, count, cfg["spacing"])
    paths, cells = [], []
    for k, r in enumerate(best, 1):
        img = frame_at(video, r["t"])
        path = out / f"thumb_{k:02d}_{r['t']:.2f}s.png"
        cv2.imwrite(str(path), cv2.cvtColor(img, cv2.COLOR_RGB2BGR))
        paths.append(path)
        small = cv2.resize(cv2.cvtColor(img, cv2.COLOR_RGB2BGR), (480, 270))
        label = (f"#{k} {r['t']:.2f}s  score {r['total']:.2f}  eyes {r['score']['eyes']:.2f} "
                 f"mouth {r['score']['mouth']:.2f} frontal {r['score']['frontal']:.2f}")
        cells.append((small, label))
    for t in (headlines if headlines is not None else cfg["headlines"]):
        img = frame_at(video, float(t))
        path = out / f"headline_{float(t):.2f}s.png"
        cv2.imwrite(str(path), cv2.cvtColor(img, cv2.COLOR_RGB2BGR))
        paths.append(path)
        cells.append((cv2.resize(cv2.cvtColor(img, cv2.COLOR_RGB2BGR), (480, 270)), f"headline {float(t):.2f}s"))
    from demoforge.film.qa import sheet
    sheet(cells, 3, out / "thumbs_sheet.png")
    import json
    (out / "thumbs.json").write_text(json.dumps(sorted(rows, key=lambda r: -r["total"])[:50], indent=1),
                                     encoding="utf-8")
    for r in best:
        print(f"  {r['t']:7.2f}s  {r['total']:.2f}")
    print(f"thumbs: {len(paths)} frames and a sheet in {out}")
    return paths
