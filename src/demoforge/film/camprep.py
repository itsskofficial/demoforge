"""On-camera media for the film: full-frame plates and cleaned cutouts.

For every decoded camera line NNNN (work/cam/NNNN.mov):

    assets/cam/NNNN.mp4     the plate: H.264, no audio (the sound lives in the mix)
    assets/cam/NNNN_a.webm  the cutout, cleaned: the matte choked a couple of
                            pixels and softened, the wall's green spill taken
                            out, so edges don't glow; VP9 with alpha and a
                            keyframe every 15 frames, because the renderer
                            seeks every frame and sparse keyframes freeze it

The raw matte (work/matte/NNNN.webm) comes from `hyperframes remove-background`;
`--matte` makes any that are missing. Lines in `camera.nocut` stay full-frame
and need no matte. Idempotent: existing outputs are kept.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from demoforge.film.project import Project, ffmpeg


def cutout_filter(choke: int = 2, soften: float = 1.1, despill: str = "green", mix: float = 0.6) -> str:
    erode = ",".join(["erosion"] * choke)
    return ("[0]format=yuva444p,split[c][a];"
            f"[a]alphaextract,{erode + ',' if erode else ''}gblur=sigma={soften}[am];"
            f"[c]format=rgb24,despill=type={despill}:mix={mix}:expand=0.1,format=yuv444p[cc];"
            "[cc][am]alphamerge,format=yuva420p")


def matte(src: Path, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["npx", "--yes", "hyperframes", "remove-background", str(src), "-o", str(out)],
                   check=True, shell=True)


def build(p: Project, make_mattes: bool = False) -> None:
    cfg = p.cfg["camera"]
    src = p.work / "cam"
    dst = p.emit / "assets" / "cam"
    dst.mkdir(parents=True, exist_ok=True)
    movs = sorted(src.glob("*.mov"))
    if not movs:
        raise SystemExit(f"no decoded clips in {src}; run `film decode` first")
    waiting = []
    for mov in movs:
        n = mov.stem
        plate = dst / f"{n}.mp4"
        if not plate.exists():
            gop = ["-g", str(cfg["plate_gop"]), "-keyint_min", str(cfg["plate_gop"])] if cfg["plate_gop"] else []
            ffmpeg("-i", str(mov), "-an", "-c:v", "libx264", "-crf", str(cfg["plate_crf"]), "-preset", "slow",
                   *gop, "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(plate))
            print("  plate", n)
        if n in cfg["nocut"]:
            continue
        raw = p.work / "matte" / f"{n}.webm"
        if not raw.exists() and make_mattes:
            matte(mov, raw)
        cut = dst / f"{n}_a.webm"
        if raw.exists() and not cut.exists():
            g = str(cfg["cutout_gop"])
            ffmpeg("-c:v", "libvpx-vp9", "-i", str(raw), "-filter_complex",
                   cutout_filter(cfg["choke"], cfg["soften"], cfg["despill"], cfg["despill_mix"]),
                   "-c:v", "libvpx-vp9", "-b:v", "0", "-crf", str(cfg["cutout_crf"]), "-row-mt", "1",
                   "-auto-alt-ref", "0", "-g", g, "-keyint_min", g,
                   "-metadata:s:v:0", "alpha_mode=1", str(cut))
            print("  cutout", n)
        elif not cut.exists():
            waiting.append(n)
    if waiting:
        print(f"camprep: no matte yet for {', '.join(waiting)} (run with --matte)")
    print(f"camprep: camera media in {dst}")
