"""Decode the camera clips reliably, into H.264 + PCM intermediates.

Phone exports are often AV1, and both obvious decoders fail on them quietly:
ffmpeg's libaom could not read these files at all, and the CUDA AV1 path
*plays* them while dropping and repeating frames, so most consecutive frames
come out identical and everything downstream stutters. PyAV ships libdav1d,
which decodes them cleanly. Every frame is piped into ffmpeg for encoding, the
audio is copied across as PCM, and then the frames are checked: if more than a
few percent are exact repeats, the decode is wrong and the step fails rather
than handing a stutter to the edit.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np


class Repeats:
    """Counts frames identical to the one before, on a coarse grid: sensor noise
    makes real consecutive frames differ somewhere, so an exact repeat is a
    decoder repeating itself."""

    def __init__(self) -> None:
        self.prev, self.same, self.n = None, 0, 0

    def add(self, img: np.ndarray) -> None:
        small = img[::16, ::16]
        if self.prev is not None and np.array_equal(small, self.prev):
            self.same += 1
        self.prev = small.copy()
        self.n += 1

    @property
    def share(self) -> float:
        return self.same / max(1, self.n - 1)


def repeated(frames) -> float:
    r = Repeats()
    for img in frames:
        r.add(img)
    return r.share


def decode(src: Path, dst: Path, fps: int = 30, crf: int = 12, sr: int = 48000) -> tuple[int, float]:
    import av

    dst.parent.mkdir(parents=True, exist_ok=True)
    with av.open(str(src)) as c:
        vs = c.streams.video[0]
        vs.thread_type = "AUTO"
        av1 = vs.codec_context.name in ("av1", "libdav1d", "libaom-av1")
        ctx = None
        if av1:
            ctx = av.codec.CodecContext.create("libdav1d", "r")
            ctx.extradata = vs.codec_context.extradata
        w, h = vs.codec_context.width, vs.codec_context.height
        has_audio = bool(c.streams.audio)
        cmd = ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "yuv420p", "-s", f"{w}x{h}",
               "-r", str(fps), "-i", "-"]
        if has_audio:
            cmd += ["-i", str(src), "-map", "0:v", "-map", "1:a"]
        cmd += ["-c:v", "libx264", "-crf", str(crf), "-preset", "medium", "-pix_fmt", "yuv420p"]
        if has_audio:
            cmd += ["-c:a", "pcm_s24le", "-ar", str(sr), "-shortest"]
        enc = subprocess.Popen(cmd + [str(dst)], stdin=subprocess.PIPE)
        seen = Repeats()

        def frames():
            for packet in c.demux(vs):
                for frame in (ctx.decode(packet) if ctx else packet.decode()):
                    yield frame
            if ctx:
                try:
                    yield from ctx.decode(None)
                except av.error.EOFError:
                    pass

        for frame in frames():
            img = frame.to_ndarray(format="yuv420p")
            seen.add(img)
            enc.stdin.write(img.tobytes())
        enc.stdin.close()
        enc.wait()
        if enc.returncode:
            raise SystemExit(f"encoding {dst.name} failed")
    return seen.n, seen.share


def build(p, only: list[str] | None = None, force: bool = False) -> list[str]:
    """Every camera clip -> work/cam/NNNN.mov. Fails if any decode repeats frames."""
    out = p.work / "cam"
    limit = p.cfg["decode"]["max_repeat"]
    bad = []
    for seq, src in p.sources("camera").items():
        if only and seq not in only:
            continue
        dst = out / f"{seq}.mov"
        if dst.exists() and not force:
            continue
        frames, dup = decode(src, dst, p.fps, p.cfg["decode"]["crf"], p.sr)
        flag = "  REPEATED FRAMES" if dup > limit else ""
        print(f"  {seq}: {frames} frames, {dup:.1%} repeated{flag}", flush=True)
        if dup > limit:
            bad.append(seq)
    if bad:
        raise SystemExit(f"decode: {', '.join(bad)} repeat more than {limit:.0%} of frames; "
                         "the decoder is dropping frames (CUDA AV1 does this). Use libdav1d.")
    print(f"decode: camera clips in {out}")
    return bad
