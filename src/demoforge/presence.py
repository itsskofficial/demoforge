"""Two post-processes that decide whether the presenter reads as a person.

Neither generates anything. They repair the two places where a locally
generated presenter gives itself away, and they are separate commands because
they fail independently.

**`matte` -- the room behind the head.** Until now the presenter arrived as a
hard circular crop of whatever was actually behind them: in `compose` that is a
green wall and a curtain, sitting on a near-black deck. Nothing about the
lighting matches, so it reads as a webcam bubble pasted on a slide rather than
a person in the film. RobustVideoMatting pulls an alpha with no green screen,
no trimap and no background plate, and it is *recurrent* -- the frames must be
fed in order, because the temporal state is what stops the edge boiling.

**`restore` -- the mouth.** LatentSync generates the mouth inside a 256x256
face crop (`configs/unet/stage2.yaml`), warps it back, and that is fine while
the presenter is a 340px inset. Full frame in a 1080-wide reel the face is
around 600px, so the one generated region in the picture is the one being
upscaled 2.5x. That is the blur, and it is not fixable by driving at a higher
resolution because the crop is resized to 256 either way.

So the mouth is restored rather than re-generated: detect, align to the FFHQ
512 template, run GFPGAN, warp back, and blend through a soft mask that is
only open over the lower face. Restoring the *whole* face would also work and
looks worse -- it repaints eyes and skin that were never generated and were
already real, which is exactly how a re-dub starts to look like a stranger.

    python -m demoforge.presence matte   --video head.mp4 --out head.mov
    python -m demoforge.presence matte   --video head.mp4 --out on-deck.mp4 --over "#0A0B0F"
    python -m demoforge.presence restore --video face.mp4 --out sharp.mp4
    demoforge tool matte   --video head.mp4      the same, as a tool; likewise restore

Both stream frames through ffmpeg pipes rather than decoding to an array.
LatentSync's habit of holding the whole driver in memory is what forced
`face.sync_chunked` to exist; there is no reason to repeat it here.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

import numpy as np

from demoforge.config import OUT
from demoforge.media import has_audio

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

MODELS = Path("E:/Models/demoforge/restore")
RVM = MODELS / "rvm_mobilenetv3_fp32.torchscript"
GFPGAN = MODELS / "GFPGANv1.4.onnx"
YUNET = Path("E:/Models/demoforge/echomimic/yunet.onnx")

# facexlib's FFHQ-512 five-point template, in the order YuNet reports its
# landmarks: right eye, left eye, nose, right mouth corner, left mouth corner.
TEMPLATE = np.array([[192.98138, 239.94708],
                     [318.90277, 240.19366],
                     [256.63416, 314.01935],
                     [201.26117, 371.41043],
                     [313.08905, 371.15118]], dtype=np.float32)


# ---------------------------------------------------------------------------
# frame plumbing
# ---------------------------------------------------------------------------


def probe(video: Path) -> tuple[int, int, float]:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=width,height,r_frame_rate", "-of", "csv=p=0", str(video)],
        capture_output=True, text=True, check=True).stdout.strip().split(",")
    num, _, den = out[2].partition("/")
    return int(out[0]), int(out[1]), float(num) / float(den or 1)


def reader(video: Path, width: int, height: int):
    """Yield rgb24 frames, one at a time, straight out of ffmpeg."""
    proc = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-i", str(video), "-f", "rawvideo",
         "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE)
    size = width * height * 3
    try:
        while True:
            buf = proc.stdout.read(size)
            if len(buf) < size:
                return
            yield np.frombuffer(buf, np.uint8).reshape(height, width, 3)
    finally:
        proc.stdout.close()
        proc.wait()


def writer(out: Path, width: int, height: int, fps: float, alpha: bool = False):
    """An ffmpeg process taking raw frames on stdin.

    Alpha goes out as ProRes 4444 because that is the only common intermediate
    that both carries a real alpha channel and is not a lossless size. h264
    has no alpha at all, and writing one silently drops it.
    """
    out.parent.mkdir(parents=True, exist_ok=True)
    codec = (["-c:v", "prores_ks", "-profile:v", "4444", "-pix_fmt", "yuva444p10le"]
             if alpha else
             ["-c:v", "libx264", "-crf", "16", "-preset", "medium",
              "-pix_fmt", "yuv420p"])
    return subprocess.Popen(
        ["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt",
         "rgba" if alpha else "rgb24", "-s", f"{width}x{height}", "-r", f"{fps}",
         "-i", "-", *codec, str(out)], stdin=subprocess.PIPE)


def revoice(silent: Path, source: Path, out: Path) -> Path:
    """Put the original audio back on a processed picture."""
    if not has_audio(source):
        silent.replace(out)
        return out
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", str(silent), "-i", str(source),
         "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac",
         "-b:a", "192k", "-shortest", str(out)], check=True)
    silent.unlink(missing_ok=True)
    return out


# ---------------------------------------------------------------------------
# matte
# ---------------------------------------------------------------------------


def _backdrop(over: str, width: int, height: int) -> np.ndarray:
    if over.startswith("#"):
        rgb = tuple(int(over[i:i + 2], 16) for i in (1, 3, 5))
        return np.full((height, width, 3), rgb, np.uint8)
    from PIL import Image
    img = Image.open(over).convert("RGB").resize((width, height), Image.LANCZOS)
    return np.asarray(img, np.uint8)


def matte(video: Path, out: Path, over: str | None = None,
          ratio: float | None = None) -> Path:
    """Pull an alpha off the presenter and either keep it or composite it.

    `ratio` is RobustVideoMatting's internal downsample. The model wants the
    *downsampled* frame to land near 512 on its long side -- too high and it
    runs out of memory for no gain, too low and it loses the hair. Derived from
    the frame rather than guessed, which is the difference between this working
    on a 720p driver and a 1080x1920 reel with the same call.
    """
    import torch

    if not RVM.exists():
        raise SystemExit(f"no matting model at {RVM}")
    width, height, fps = probe(video)
    ratio = ratio or max(0.1, min(1.0, 512 / max(width, height)))
    model = torch.jit.load(str(RVM)).cuda().eval()

    silent = out.with_name(f"_{out.stem}.silent{out.suffix}")
    sink = writer(silent, width, height, fps, alpha=over is None)
    ground = _backdrop(over, width, height).astype(np.float32) if over else None

    state = [None] * 4
    count = 0
    with torch.no_grad():
        for frame in reader(video, width, height):
            src = torch.from_numpy(frame.copy()).cuda()
            src = src.permute(2, 0, 1)[None].float() / 255.0
            fgr, pha, *state = model(src, *state, ratio)
            a = pha[0, 0].cpu().numpy()[..., None]
            if ground is None:
                rgba = np.concatenate(
                    [fgr[0].permute(1, 2, 0).cpu().numpy() * 255.0, a * 255.0], 2)
                sink.stdin.write(np.clip(rgba, 0, 255).astype(np.uint8).tobytes())
            else:
                fg = fgr[0].permute(1, 2, 0).cpu().numpy() * 255.0
                sink.stdin.write(
                    np.clip(fg * a + ground * (1 - a), 0, 255).astype(np.uint8).tobytes())
            count += 1

    sink.stdin.close()
    sink.wait()
    revoice(silent, video, out)
    print(f"  matte  {out.name}  {count} frames  ratio {ratio:.2f}"
          f"{'' if over is None else f'  over {over}'}")
    return out


# ---------------------------------------------------------------------------
# restore
# ---------------------------------------------------------------------------


def _session():
    """GFPGAN on the GPU, which takes one line of coaxing on Windows.

    onnxruntime-gpu ships against a CUDA it expects to find on PATH. Torch
    already carries a matching set in its own `lib`, so pointing the loader at
    that is the whole fix -- and without it the provider silently falls back to
    CPU, where this is forty times slower and still produces the right answer,
    so the failure looks like "restore is slow" rather than "restore is
    misconfigured".
    """
    import torch
    import onnxruntime as ort

    lib = Path(torch.__file__).parent / "lib"
    if lib.exists() and hasattr(os, "add_dll_directory"):
        os.add_dll_directory(str(lib))
    providers = (["CUDAExecutionProvider", "CPUExecutionProvider"]
                 if "CUDAExecutionProvider" in ort.get_available_providers()
                 else ["CPUExecutionProvider"])
    session = ort.InferenceSession(str(GFPGAN), providers=providers)
    if "CUDAExecutionProvider" not in session.get_providers():
        print("  restore is on the CPU; expect ~40x the runtime")
    return session


def _mask(region: str, feather: int = 24) -> np.ndarray:
    """The soft window, in the 512 aligned space, that the repair comes through.

    `mouth` is an ellipse over the lower face. It is the default because it is
    the only part LatentSync actually generated -- everything above the nose is
    original footage, and repainting real eyes with a prior is how a re-dub
    stops looking like the person.

    The ellipse used to top out at y=252, which sounds clear of the eyes and is
    not: the 24px feather carried 0.23 of full strength onto the lower-lid line
    at y=235 and 0.09 onto the iris column. Dropped to cy=392, ry=100, which
    leaves 0.002 at the iris column and 0.99 at the mouth.

    How much this was actually costing, measured rather than assumed: against a
    generated take the restored frame differs from the raw one by 3.50 mean
    levels in the mouth, 2.10 at the eyes -- but 1.2-1.6 in the *background*,
    which the mask cannot reach at all. That floor is the warp-and-re-encode
    round trip. So the eyes were getting a little real treatment above the
    noise, not the majority of the mouth's, and this change is a small
    correctness win rather than the large one the raw numbers first suggested.

    The nose loses coverage on the way (0.86 -> 0.39), which is the right
    trade either way: it has no fine structure that restoration recovers.
    """
    import cv2

    mask = np.zeros((512, 512), np.float32)
    if region == "face":
        cv2.ellipse(mask, (256, 280), (170, 210), 0, 0, 360, 1.0, -1)
    else:
        cv2.ellipse(mask, (256, 392), (150, 100), 0, 0, 360, 1.0, -1)
    return cv2.GaussianBlur(mask, (0, 0), feather)[..., None]


def restore(video: Path, out: Path, region: str = "mouth",
            strength: float = 0.85, smooth: float = 0.6) -> Path:
    """Sharpen the generated region of every face, and leave the rest alone.

    `smooth` is an exponential average over the five landmarks before the
    alignment is solved. Per-frame detection jitters by a pixel or two, the
    warp turns that into a wobble, and a wobbling repaint of a still jaw is
    more distracting than the blur it fixes.
    """
    import cv2

    for path in (GFPGAN, YUNET):
        if not path.exists():
            raise SystemExit(f"missing model: {path}")
    width, height, fps = probe(video)
    session = _session()
    name = session.get_inputs()[0].name
    detector = cv2.FaceDetectorYN.create(str(YUNET), "", (width, height),
                                         score_threshold=0.6)
    window = _mask(region)

    silent = out.with_name(f"_{out.stem}.silent{out.suffix}")
    sink = writer(silent, width, height, fps)
    tracked = None
    done = missed = 0

    for frame in reader(video, width, height):
        bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        _, faces = detector.detect(bgr)
        if faces is None or not len(faces):
            sink.stdin.write(frame.tobytes())
            missed += 1
            continue
        # The largest box, not the first: a reflection or a face on a monitor
        # in the background is a real detection and the wrong one.
        face = max(faces, key=lambda f: f[2] * f[3])
        points = face[4:14].reshape(5, 2).astype(np.float32)
        tracked = points if tracked is None else (
            smooth * tracked + (1 - smooth) * points)

        affine, _ = cv2.estimateAffinePartial2D(tracked, TEMPLATE, method=cv2.LMEDS)
        if affine is None:
            sink.stdin.write(frame.tobytes())
            missed += 1
            continue
        crop = cv2.warpAffine(frame, affine, (512, 512), flags=cv2.INTER_LINEAR,
                              borderMode=cv2.BORDER_REFLECT)

        x = crop.astype(np.float32) / 127.5 - 1.0
        y = session.run(None, {name: x.transpose(2, 0, 1)[None]})[0][0]
        fixed = np.clip((y.transpose(1, 2, 0) + 1.0) * 127.5, 0, 255)

        # Blended in the aligned space, then warped back as one image. Warping
        # the repair and the mask separately and blending in frame space drags
        # two different interpolations across the same edge and leaves a seam.
        blended = crop * (1 - window * strength) + fixed * (window * strength)
        back = cv2.invertAffineTransform(affine)
        patch = cv2.warpAffine(blended, back, (width, height),
                               flags=cv2.INTER_LINEAR)
        alpha = cv2.warpAffine(window, back, (width, height),
                               flags=cv2.INTER_LINEAR)[..., None]
        merged = frame * (1 - alpha) + patch * alpha
        sink.stdin.write(np.clip(merged, 0, 255).astype(np.uint8).tobytes())
        done += 1

    sink.stdin.close()
    sink.wait()
    revoice(silent, video, out)
    print(f"  restore  {out.name}  {done} faces, {missed} passed through  "
          f"({region}, strength {strength})")
    return out


# ---------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    m = sub.add_parser("matte", help="cut the presenter out of their room")
    m.add_argument("--video", required=True)
    m.add_argument("--out", default=str(OUT / "matted.mov"))
    m.add_argument("--over", default=None,
                   help="#RRGGBB or an image to composite onto; omit for RGBA")
    m.add_argument("--ratio", type=float, default=None)

    r = sub.add_parser("restore", help="sharpen the generated part of the face")
    r.add_argument("--video", required=True)
    r.add_argument("--out", default=str(OUT / "restored.mp4"))
    r.add_argument("--region", choices=("mouth", "face"), default="mouth")
    r.add_argument("--strength", type=float, default=0.85)
    r.add_argument("--smooth", type=float, default=0.6)

    args = ap.parse_args()
    if args.cmd == "matte":
        matte(Path(args.video), Path(args.out), args.over, args.ratio)
    else:
        restore(Path(args.video), Path(args.out), args.region, args.strength,
                args.smooth)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
