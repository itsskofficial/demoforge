"""`film new`: a project folder laid out the way the pitch film was.

    <project>/
      film.json          every decision, documented in docs/film-mode.md
      FOOTAGE.md         what was actually said, one `| NNNN | text |` row per line
      FILM.md            the bible: world, motifs, palette, safe areas, sound
      SCENES.md          one brief per scene, written against timeline.json
      footage/voice/     one wav per line, ...-NNNN.wav
      footage/cam/       the on-camera lines, ...-NNNN.mp4, same NNNN as the voice
      film/              the HyperFrames project
        index.html       the root (written by `film root`)
        lib/kit.css      design tokens and faces; lib/kit.js, seeded helpers
        assets/          fonts, sfx (+ manifest.json), cam, audio, fx
        scenes/sNN/      one sub-composition per scene, each with junctions
                         `assets` and `lib` back to the film's own

Scene folders link to the shared assets and lib rather than copying them,
because `hyperframes snapshot` and preview open a scene on its own and need its
relative paths to resolve. On Windows they are junctions (`mklink /J`), which
need no admin rights. Never `rm -rf` a scene folder: some tools follow them.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from demoforge.config import PROJECTS

KIT = Path(__file__).resolve().parent / "kit"
HYPERFRAMES = "0.8.180"

FILM_JSON = """{
 "_about": "A film-mode project. Every key is documented in docs/film-mode.md; keys starting with _ are comments.",
 "name": "%(name)s",
 "title": "%(name)s",
 "fps": 30, "width": 1920, "height": 1080, "sample_rate": 48000,
 "paths": {
  "film": "film",
  "work": "{out}/{name}",
  "voice": "footage/voice",
  "camera": "footage/cam",
  "music": "{work}/music/tracks"
 },
 "sources": {"voice": "*.wav", "camera": "*.mp4", "seq": "(\\\\d{4})\\\\.[^.]+$"},
 "spine": {
  "gap_after": {"_0001": "a breath after the hook", "0001": 0.55},
  "remove": {},
  "tail_cut": {}
 },
 "lookaways": {"_about": "line -> clip time of the last on-lens frame, approved frame by frame"},
 "captions": {"text": "FOOTAGE.md", "spoken": {}, "srt": "%(name)s.srt"},
 "scenes": [
  {"id": "s01", "kind": "anim", "at": "0001", "title": "cold open"},
  {"id": "s02", "kind": "cam", "at": "0002", "title": "to camera"}
 ],
 "looks": {
  "cam": {"plate": "none", "subject": "none", "ground": "#0b0d12", "plate_scale": 1.0, "push": [1.0, 1.045]},
  "cam-bw": {"plate": "grayscale(1) contrast(1.15)", "subject": "grayscale(1) contrast(1.15)", "ground": "#0b0d12", "plate_scale": null, "push": [1.0, 1.045]}
 },
 "camera": {"nocut": [], "flip_from": {}},
 "joins": {"s01": "glitch"},
 "sfx": {
  "glitch": ["glitch", -0.10, -4],
  "whip": ["whoosh-fast", null, -6],
  "punch": ["impact-punch", 0.0, -9]
 },
 "music": {"sections": [
  {"track": "track.mp3", "pin": "0001", "track_at": 0.0, "start": 0.0, "end": "end", "gain": 0, "fade_in": 0.05, "fade_out": 2.0}
 ]}
}
"""

FILM_MD = """# %(name)s: the film bible

Read this before touching a scene. It is the contract that makes every scene,
built by different hands, feel like one film.

## What we're making
(Who, for whom, how long, where it will be posted. The one feeling it leaves.)

## One world
(The look every frame shares. If a frame could belong to another video, it's wrong.)

## Motifs
(Two or three recurring images or lines that pay off later.)

## Canvas and safe areas
- 1920x1080, 30 fps.
- Caption band y 900-1020 is reserved: captions are burned in by the root.
- Grain, vignette and captions are global (the root adds them). Don't add your own.

## Palette and type
Tokens are in `film/lib/kit.css`.

## Sound
Each scene lists its hits in `scenes/<id>/sfx.json`: `[{"t": 0.5, "sfx": "pop", "gain": -6}]`,
names from `film/assets/sfx/manifest.json`. Joins get their sound from film.json's `sfx`.
"""

SCENES_MD = """# Scene direction

One brief per scene. Timings and exact words are in `film/timeline.json` (each scene's
`words` are scene-local). Read FILM.md first.

## s01 · (title)
The idea, the beats (with the words they land on), and the sound.
"""

FOOTAGE_MD = """# What was said

One row per line, written by listening, not from the script. Numbers as numbers.
Captions are aligned to this text.

| Line | Said |
| --- | --- |
| 0001 | (the first line, as spoken) |
"""

ROOT_STUB = """<!doctype html>
<html lang="en">
<head><meta charset="UTF-8" /><title>%(name)s</title></head>
<body>
  <!-- written by `demoforge film root` -->
  <div id="root" data-composition-id="main" data-start="0" data-duration="1" data-width="1920" data-height="1080"></div>
</body>
</html>
"""


def link_dir(link: Path, target: Path) -> None:
    """A directory link that tools can follow: a junction on Windows, a symlink elsewhere."""
    if link.exists() or link.is_symlink():
        return
    if os.name == "nt":
        subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], check=True,
                       capture_output=True)
    else:
        os.symlink(target, link, target_is_directory=True)


def scene_dir(film: Path, sid: str) -> Path:
    d = film / "scenes" / sid
    d.mkdir(parents=True, exist_ok=True)
    link_dir(d / "assets", film / "assets")
    link_dir(d / "lib", film / "lib")
    return d


def film_skeleton(film: Path, name: str) -> None:
    for sub in ("assets/audio", "assets/cam", "assets/fx", "assets/sfx", "assets/fonts", "lib", "scenes",
                "compositions", "renders"):
        (film / sub).mkdir(parents=True, exist_ok=True)
    for f in ("kit.css", "kit.js"):
        if not (film / "lib" / f).exists():
            shutil.copy(KIT / f, film / "lib" / f)
    for font in (KIT / "fonts").glob("*.woff2"):
        if not (film / "assets" / "fonts" / font.name).exists():
            shutil.copy(font, film / "assets" / "fonts" / font.name)
    manifest = film / "assets" / "sfx" / "manifest.json"
    if not manifest.exists():
        manifest.write_text("[]\n", encoding="utf-8")
    files = {
        "index.html": ROOT_STUB % {"name": name},
        "meta.json": json.dumps({"id": "film", "name": name}),
        "hyperframes.json": json.dumps({
            "$schema": "https://hyperframes.heygen.com/schema/hyperframes.json",
            "registry": "https://raw.githubusercontent.com/heygen-com/hyperframes/main/registry",
            "paths": {"blocks": "compositions", "components": "compositions/components", "assets": "assets"},
            "media": {"autoProxy": True}}, indent=2),
        "package.json": json.dumps({
            "name": "film", "private": True, "type": "module",
            "scripts": {k: f"npx --yes hyperframes@{HYPERFRAMES} {v}" for k, v in
                        (("dev", "preview"), ("check", "check"), ("render", "render"), ("publish", "publish"))}},
            indent=2),
    }
    for rel, text in files.items():
        if not (film / rel).exists():
            (film / rel).write_text(text, encoding="utf-8")


def new(target: str) -> Path:
    p = Path(target)
    d = p if (p.is_absolute() or len(p.parts) > 1) else PROJECTS / target
    d = d.resolve()
    if (d / "film.json").exists():
        raise SystemExit(f"{d / 'film.json'} already exists")
    name = d.name
    d.mkdir(parents=True, exist_ok=True)
    (d / "footage" / "voice").mkdir(parents=True, exist_ok=True)
    (d / "footage" / "cam").mkdir(parents=True, exist_ok=True)
    for rel, text in (("film.json", FILM_JSON), ("FILM.md", FILM_MD), ("SCENES.md", SCENES_MD),
                      ("FOOTAGE.md", FOOTAGE_MD)):
        if not (d / rel).exists():
            (d / rel).write_text(text % {"name": name}, encoding="utf-8")
    film_skeleton(d / "film", name)
    for sid in ("s01", "s02"):
        scene_dir(d / "film", sid)
    print(f"film: new project in {d}\n  next: put the lines in footage/, write FOOTAGE.md, "
          f"then `demoforge film build --project {d}`")
    return d
