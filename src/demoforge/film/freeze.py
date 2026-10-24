"""Stills of the last frame of every scene that leaves by a shatter, for the glass shards.

The scene is snapshotted on its own, so the still has its overlays and camera
move but none of the root's grain or vignette (those sit above the shards and
stay live). It is taken 0.04 s before the scene's end because the shards
replace the picture 0.02 s before the cut. A black-and-white copy is made
beside it: the shards turn grey as they fall into a black-and-white act.

    assets/fx/<scene>_frozen.png, assets/fx/<scene>_frozen_bw.png
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from demoforge.film.project import Project, ffmpeg, read_json


def snapshot(scene_dir: Path, at: float, out: Path, tmp_root: Path) -> Path:
    tmp_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=tmp_root) as tmp:
        subprocess.run(["npx", "--yes", "hyperframes", "snapshot", str(scene_dir), "--at", str(at),
                        "--no-end", "--keep", "--describe", "false", "-o", tmp], check=True, shell=True)
        png = next(Path(tmp).glob("at-*.png"))
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(png, out)
    return out


def build(p: Project) -> list[str]:
    tl = {s["id"]: s for s in p.timeline()["scenes"]}
    joins = read_json(p.emit / "transitions.json")["joins"]
    fx = p.emit / "assets" / "fx"
    done = []
    for j in joins:
        if j["kind"] != "shatter":
            continue
        sid = j["out"]
        at = round(tl[sid]["duration"] - 0.04, 3)
        scene = p.emit / "scenes" / sid
        scene = scene if (scene / "assets").exists() else p.film / "scenes" / sid
        col = snapshot(scene, at, fx / f"{sid}_frozen.png", p.path("temp"))
        ffmpeg("-i", str(col), "-vf", "hue=s=0,eq=contrast=1.15", str(fx / f"{sid}_frozen_bw.png"))
        print(f"  froze {sid} at {at}s")
        done.append(sid)
    print(f"freeze: {len(done)} still(s) in {fx}")
    return done
