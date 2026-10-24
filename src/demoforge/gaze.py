"""Where the presenter is looking, second by second.

A talking head cut full-frame while its eyes are off reading a script is the
single clearest tell that a video was assembled rather than performed. The
viewer cannot always say what is wrong, but they stop trusting the person.

So this measures it, and the shot plan is built around the answer: full frame
only where the eyes are on the lens, and a slide or a cutaway everywhere else.
That inverts the usual order — normally you decide the shots and hope the
footage cooperates — and it is the right way round, because the footage is
already shot and the shots are still free.

Two signals, both needed:

**Head yaw**, from the horizontal offset of the nose against the midpoint of
the eyes, normalised by face width. Catches someone turned towards a second
monitor.

**Iris offset**, from each iris centre against its own eye corners. Catches
someone whose head is square to camera and whose eyes are not — which is what
reading off a phone propped beside the lens actually looks like, and what head
pose alone scores as perfect.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from demoforge.config import ROOT

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

MODEL = ROOT / "assets/models/face_landmarker.task"
MODEL_URL = ("https://storage.googleapis.com/mediapipe-models/face_landmarker/"
             "face_landmarker/float16/1/face_landmarker.task")

# Landmark indices in mediapipe's 478-point face mesh.
NOSE = 1
LEFT_EYE_OUTER, LEFT_EYE_INNER = 33, 133
RIGHT_EYE_INNER, RIGHT_EYE_OUTER = 362, 263
LEFT_IRIS = (468, 469, 470, 471, 472)
RIGHT_IRIS = (473, 474, 475, 476, 477)
FACE_LEFT, FACE_RIGHT = 234, 454
LEFT_LID_TOP, LEFT_LID_BOTTOM = 159, 145

# Tuned against a phone propped just beside the lens, which is the normal
# setup and the hardest case: the head barely moves and the eyes move a lot.
YAW_LIMIT = 0.085       # nose offset as a fraction of face width
IRIS_LIMIT = 0.115      # iris offset from the centre of its own eye
BLINK_LIMIT = 0.12      # eye aspect below this is a blink, not a look away


@dataclass
class Sample:
    t: float
    face: bool = False
    yaw: float = 0.0
    iris: float = 0.0
    open_eyes: float = 0.0
    # Where the face is, as fractions of the frame. Stored because framing a
    # shot on a fixed offset assumes the presenter never moves, and over seven
    # minutes in a chair they always do.
    fx: float = 0.5
    ey: float = 0.4
    fw: float = 0.0

    @property
    def on_camera(self) -> bool:
        """Looking down the lens. A blink counts as still looking."""
        if not self.face:
            return False
        if self.open_eyes < BLINK_LIMIT:
            return True
        return abs(self.yaw) < YAW_LIMIT and abs(self.iris) < IRIS_LIMIT


def ensure_model() -> Path:
    if MODEL.exists():
        return MODEL
    import urllib.request
    MODEL.parent.mkdir(parents=True, exist_ok=True)
    print(f"  fetching {MODEL.name} …")
    urllib.request.urlretrieve(MODEL_URL, MODEL)
    return MODEL


def _landmarker():
    from mediapipe.tasks.python import BaseOptions, vision
    return vision.FaceLandmarker.create_from_options(
        vision.FaceLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(ensure_model())),
            running_mode=vision.RunningMode.VIDEO, num_faces=1))


def _measure(points) -> tuple[float, float, float, float, float, float]:
    """yaw, iris offset, eye openness, and where the face sits in frame."""
    def x(i):
        return points[i].x

    def y(i):
        return points[i].y

    width = abs(x(FACE_RIGHT) - x(FACE_LEFT)) or 1e-6
    eye_mid = (x(LEFT_EYE_OUTER) + x(RIGHT_EYE_OUTER)) / 2
    yaw = (x(NOSE) - eye_mid) / width

    def offset(iris, outer, inner):
        centre = sum(x(i) for i in iris) / len(iris)
        span = abs(x(inner) - x(outer)) or 1e-6
        return (centre - (x(outer) + x(inner)) / 2) / span

    iris = (offset(LEFT_IRIS, LEFT_EYE_OUTER, LEFT_EYE_INNER)
            + offset(RIGHT_IRIS, RIGHT_EYE_OUTER, RIGHT_EYE_INNER)) / 2

    lid = abs(y(LEFT_LID_TOP) - y(LEFT_LID_BOTTOM))
    eye_span = abs(x(LEFT_EYE_INNER) - x(LEFT_EYE_OUTER)) or 1e-6

    centre = (x(FACE_LEFT) + x(FACE_RIGHT)) / 2
    # The eye line, not the nose or the centroid. Framing convention puts the
    # eyes on the upper third, and every other reference point drifts when the
    # chin moves.
    eyes = (y(LEFT_EYE_OUTER) + y(RIGHT_EYE_OUTER)) / 2
    return yaw, iris, lid / eye_span, centre, eyes, width


def scan(video: Path, fps: float = 5.0, out: Path | None = None,
         width: int = 480) -> list[Sample]:
    """Sample the video and measure the gaze at each sample.

    Decoded through ffmpeg at a reduced size and rate rather than with
    OpenCV's own reader: the source is a phone recording with a rotation flag
    on it, and ffmpeg is the only thing in this stack that reliably applies it.
    A frame scanned upside down produces a confident, meaningless answer.
    """
    import numpy as np
    import mediapipe as mp

    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=width,height", "-show_entries", "stream_side_data=rotation",
         "-of", "default=nw=1", str(video)],
        capture_output=True, text=True, check=True).stdout
    values = dict(line.split("=") for line in probe.strip().splitlines()
                  if "=" in line)
    source_w, source_h = int(values["width"]), int(values["height"])
    if abs(int(values.get("rotation", 0))) == 90:
        source_w, source_h = source_h, source_w
    height = int(width * source_h / source_w) // 2 * 2

    proc = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-i", str(video), "-vf",
         f"fps={fps},scale={width}:{height}", "-f", "rawvideo",
         "-pix_fmt", "rgb24", "-"],
        stdout=subprocess.PIPE)

    landmarker = _landmarker()
    frame_bytes = width * height * 3
    samples: list[Sample] = []
    index = 0
    try:
        while True:
            raw = proc.stdout.read(frame_bytes)
            if len(raw) < frame_bytes:
                break
            frame = np.frombuffer(raw, dtype=np.uint8).reshape(height, width, 3)
            image = mp.Image(image_format=mp.ImageFormat.SRGB,
                             data=np.ascontiguousarray(frame))
            at = index / fps
            result = landmarker.detect_for_video(image, int(at * 1000))
            sample = Sample(t=round(at, 3))
            if result.face_landmarks:
                yaw, iris, open_eyes, fx, ey, fw = _measure(result.face_landmarks[0])
                sample = Sample(t=round(at, 3), face=True, yaw=round(yaw, 4),
                                iris=round(iris, 4), open_eyes=round(open_eyes, 4),
                                fx=round(fx, 4), ey=round(ey, 4), fw=round(fw, 4))
            samples.append(sample)
            index += 1
    finally:
        proc.stdout.close()
        proc.wait()

    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps([asdict(s) for s in samples], indent=1),
                       encoding="utf-8")
    return samples


def load(path: Path) -> list[Sample]:
    return [Sample(**s) for s in json.loads(path.read_text(encoding="utf-8"))]


def windows(samples: list[Sample], shortest: float = 1.2,
            forgive: float = 0.6) -> list[tuple[float, float]]:
    """Stretches where the eyes are on the lens for long enough to cut to.

    `forgive` bridges a brief glance away. Nobody holds a lens perfectly for
    twenty seconds, and a shot list that demands it comes back empty — while
    a third of a second looking down mid-sentence is invisible at speed.
    """
    if not samples:
        return []
    step = samples[1].t - samples[0].t if len(samples) > 1 else 0.2
    runs: list[list[float]] = []
    for sample in samples:
        if sample.on_camera:
            if runs and sample.t - runs[-1][1] <= forgive + step / 2:
                runs[-1][1] = sample.t + step
            else:
                runs.append([sample.t, sample.t + step])
    return [(round(a, 2), round(b, 2)) for a, b in runs if b - a >= shortest]


def framing(samples: list[Sample], start: float, end: float,
             mirror: bool = False) -> tuple[float, float]:
    """Median face centre and eye line across a span, as frame fractions.

    Median rather than mean: a couple of frames where the landmarker latched
    onto a shadow would drag an average across the frame, and the resulting
    crop would slide for no visible reason.

    `mirror` flips the horizontal, because the presenter's frames are flipped
    before this offset is applied and a centre measured on the original lands
    on the wrong side of a mirrored face.
    """
    inside = [s for s in samples if s.face and start <= s.t <= end]
    if not inside:
        return (0.5, 0.4)
    xs = sorted(s.fx for s in inside)
    ys = sorted(s.ey for s in inside)
    fx = xs[len(xs) // 2]
    ey = ys[len(ys) // 2]
    return (1 - fx if mirror else fx, ey)


def covers(spans: list[tuple[float, float]], start: float, end: float,
           needed: float = 0.8) -> bool:
    """Is enough of `start`–`end` eyes-on-camera to use it full frame?"""
    if end <= start:
        return False
    inside = sum(max(0.0, min(end, b) - max(start, a)) for a, b in spans)
    return inside / (end - start) >= needed


def report(samples: list[Sample], spans: list[tuple[float, float]],
           total: float) -> None:
    seen = sum(1 for s in samples if s.face)
    good = sum(1 for s in samples if s.on_camera)
    usable = sum(b - a for a, b in spans)
    print(f"  {len(samples)} samples, face in {seen / max(1, len(samples)):.0%}, "
          f"on camera in {good / max(1, len(samples)):.0%}")
    print(f"  {len(spans)} usable windows, {usable:.0f}s of {total:.0f}s "
          f"({usable / max(1.0, total):.0%})")
    for a, b in spans[:12]:
        print(f"    {a:7.1f}–{b:7.1f}  ({b - a:4.1f}s)")
    if len(spans) > 12:
        print(f"    … and {len(spans) - 12} more")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="demoforge.gaze", description=__doc__)
    ap.add_argument("--video", required=True)
    ap.add_argument("--out", default=None)
    ap.add_argument("--fps", type=float, default=5.0)
    args = ap.parse_args(argv)

    video = Path(args.video)
    out = Path(args.out) if args.out else None
    samples = scan(video, args.fps, out)
    total = float(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(video)],
        capture_output=True, text=True, check=True).stdout.strip())
    report(samples, windows(samples), total)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
