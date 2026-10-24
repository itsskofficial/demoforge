"""The footage base of every on-camera scene, regenerated without losing overlay work.

Each scene whose kind has a look in film.json becomes scenes/<id>/index.html
with this stack, back to front:

    .<id>-world    the ground (empty unless the look asks for a glow)
    plates         the footage, full frame, as shot (a filter only where the
                   look says so: full-frame black and white, nothing stylised)
    .<id>-behind   overlay slot: graphics BEHIND the speaker
    subject        the cutout, pixel for pixel on the same footage, so graphics
                   can pass behind the speaker without anything looking composited
    .<id>-front    overlay slot: graphics in front

Overlays are written by hand between the OVERLAY-*-BEGIN/END markers, and a
re-run carries everything between them forward. Regeneration never wipes a
scene's graphics.

Footage that ends before the next shot (no handle in the export, or a line
that ends on an approved look-away) stops on its last on-lens frame and holds
a still of it, so the look never reaches the screen. A line in `flip_from`
switches to an un-mirrored copy at that clip time, with a punch-in so the
switch reads as an edit.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

from demoforge.film.project import Project, probe_duration


def still(src: Path, t: float, out: Path, alpha: bool) -> None:
    if out.exists():
        return
    out.parent.mkdir(parents=True, exist_ok=True)
    args = ["ffmpeg", "-v", "error", "-y"]
    if alpha:
        args += ["-c:v", "libvpx-vp9"]  # the native decoder drops VP9 alpha
    args += ["-ss", f"{max(0.0, t):.3f}", "-i", str(src), "-frames:v", "1"]
    if alpha:
        args += ["-pix_fmt", "rgba"]
    subprocess.run(args + [str(out)], check=True)


def own_lines(scene: dict) -> list[dict]:
    """Lines with camera footage that start inside this scene."""
    return [ln for ln in scene["lines"]
            if ln["cam"] and scene["start"] - 0.05 <= ln["start"] < scene["end"]]


def media_blocks(p: Project, scene: dict, look: dict) -> tuple[str, list[str], list[float]]:
    """Video and hold-still elements for every line, covering the whole scene.

    Returns (html, notes, switch times for the flip punch-in)."""
    cam = p.film / "assets" / "cam"
    stills = p.emit / "assets" / "cam"
    cfg = p.cfg["camera"]
    sid, dur, fps = scene["id"], scene["duration"], p.fps
    lookaway = p.lookaways
    html, notes, switches = [], [], []
    lines = own_lines(scene)
    for i, ln in enumerate(lines):
        n = ln["seq"]
        local = max(0.0, round(ln["start"] - scene["start"], 4))
        until = (lines[i + 1]["start"] - scene["start"]) if i + 1 < len(lines) else dur
        need = until - local
        plate, cut = cam / f"{n}.mp4", cam / f"{n}_a.webm"
        avail = probe_duration(plate) - ln["src_in"] - 1.0 / fps
        if n in lookaway:  # end the picture on the last on-lens frame; the hold covers the rest
            avail = min(avail, lookaway[n] - ln["src_in"])
        run = round(min(need, avail), 4)
        hold = round(need - run, 4)
        layers = []
        if n in cfg["nocut"]:
            layers.append(("sharp", f"assets/cam/{n}.mp4", plate, False))
        else:
            if look["plate"] is not None:
                layers.append(("plate", f"assets/cam/{n}.mp4", plate, False))
            if look["subject"] is not None:
                layers.append(("subj", f"assets/cam/{n}_a.webm", cut, True))
        for role, rel, path, alpha in layers:
            vid, cls = f"{sid}-{role}-{n}", f"{sid}-{role}"
            flip_at = cfg["flip_from"].get(n)
            if flip_at is not None and ln["src_in"] < flip_at < ln["src_in"] + run:
                a_len = round(flip_at - ln["src_in"], 4)
                html.append(f'      <video id="{vid}" class="{cls} clip" src="{rel}" muted playsinline '
                            f'data-start="{local}" data-duration="{a_len}" data-media-start="{ln["src_in"]}"></video>')
                html.append(f'      <video id="{vid}-b" class="{cls} {sid}-flip clip" src="{rel}" muted playsinline '
                            f'data-start="{round(local + a_len, 4)}" data-duration="{round(run - a_len, 4)}" '
                            f'data-media-start="{flip_at}"></video>')
                switches.append(round(local + a_len, 4))
                cls = f"{cls} {sid}-flip"  # the hold still (if any) is after the switch
            else:
                html.append(f'      <video id="{vid}" class="{cls} clip" src="{rel}" muted playsinline '
                            f'data-start="{local}" data-duration="{run}" data-media-start="{ln["src_in"]}"></video>')
            if hold > 0.001:
                png = stills / f"{n}_{role}_last.png"
                still(path, ln["src_in"] + run - 1.0 / fps, png, alpha)
                html.append(f'      <img id="{vid}-hold" class="{cls} clip" src="assets/cam/{png.name}" '
                            f'data-start="{round(local + run, 4)}" data-duration="{hold}" alt="" />')
        if hold > 0.001:
            notes.append(f"{n}: footage ends {hold:.2f}s early, held on its last frame")
    return "\n".join(html), notes, switches


TEMPLATE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width={W}, height={H}" />
  <script src="{gsap}"></script>
</head>
<body>
  <div id="{sid}" data-composition-id="{sid}" data-start="0" data-duration="{dur}" data-width="{W}" data-height="{H}">
    <link rel="stylesheet" href="lib/kit.css" />
    <script src="lib/kit.js"></script>
    <style>
      #{sid} {{ position: relative; width: 100%; height: 100%; overflow: hidden; background: {ground}; }}
      #{sid} .{sid}-cam, #{sid} .{sid}-world, #{sid} .{sid}-behind, #{sid} .{sid}-front {{ position: absolute; inset: 0; }}
      #{sid} .{sid}-plate {{ position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; filter: {plate_filter}; }}
      #{sid} .{sid}-room {{ position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; transform: scale(1.06); filter: {room_filter}; }}
      #{sid} .{sid}-sharp {{ position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; filter: {sharp_filter}; }}
      #{sid} .{sid}-flip {{ transform: scaleX(-1); }}
      #{sid} .{sid}-sharpwrap {{ position: absolute; inset: 0; transform-origin: 50% 50%; }}
      #{sid} .{sid}-subj {{ position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; filter: {subject_filter}; }}
      #{sid} .{sid}-glow {{ position: absolute; inset: 0;
        background: radial-gradient(ellipse 38% 55% at 50% 42%, rgba(255,181,71,0.16), rgba(255,140,30,0.05) 45%, rgba(0,0,0,0) 72%); }}
      #{sid} .{sid}-key {{ position: absolute; inset: 0; pointer-events: none; mix-blend-mode: soft-light;
        background: radial-gradient(ellipse 34% 48% at 40% 34%, rgba(255,200,140,0.55), rgba(255,170,90,0) 70%),
                    linear-gradient(90deg, rgba(0,0,0,0) 45%, rgba(0,0,0,0.55) 100%); }}
      #{sid} .{sid}-floor {{ position: absolute; inset: 0;
        background: radial-gradient(ellipse 80% 60% at 50% 110%, rgba(255,255,255,0.05), rgba(0,0,0,0) 60%); }}
      /* OVERLAY-CSS-BEGIN */
{overlay_css}
      /* OVERLAY-CSS-END */
    </style>

    <div class="{sid}-cam">
      <div class="{sid}-world">
{world}
      </div>
{plates}
      <div class="{sid}-behind">
<!-- OVERLAY-BEHIND-BEGIN -->
{overlay_behind}
<!-- OVERLAY-BEHIND-END -->
      </div>
{subjects}
{key}
      <div class="{sid}-front">
<!-- OVERLAY-FRONT-BEGIN -->
{overlay_front}
<!-- OVERLAY-FRONT-END -->
      </div>
    </div>

    <script>
      (function () {{
        const tl = gsap.timeline({{ paused: true }});
        // camera: a slow push for the whole scene (generated)
        tl.fromTo("#{sid} .{sid}-cam", {{ scale: {cam0}, transformOrigin: "50% 42%" }},
                  {{ scale: {cam1}, duration: {dur}, ease: "sine.inOut" }}, 0);
{punch}
        // OVERLAY-JS-BEGIN
{overlay_js}
        // OVERLAY-JS-END
        window.__timelines["{sid}"] = tl;
      }})();
    </script>
  </div>
</body>
</html>
"""

SLOTS = ("OVERLAY-CSS", "OVERLAY-BEHIND", "OVERLAY-FRONT", "OVERLAY-JS")


def keep(old: str, tag: str, default: str = "") -> str:
    """What sits between a slot's BEGIN and END marker lines in the old file."""
    m = re.search(rf"{tag}-BEGIN[^\n]*\n(.*?)\n[^\n]*{tag}-END", old, re.DOTALL)
    return m.group(1) if m else default


def render(p: Project, sc: dict, old: str = "") -> tuple[str, list[str]]:
    """The scene's html, with the overlay slots of `old` carried forward."""
    sid, look, cfg = sc["id"], p.cfg["looks"][sc["kind"]], p.cfg["camera"]
    blocks, notes, switches = media_blocks(p, sc, look)
    rows = blocks.splitlines()
    plates = "\n".join(l for l in rows if f"{sid}-plate" in l or f"{sid}-room" in l)
    sharp = "\n".join(l for l in rows if f"{sid}-sharp" in l)
    if sharp:
        plates += f'\n      <div id="{sid}-sharpwrap" class="{sid}-sharpwrap">\n{sharp}\n      </div>'
    punch = "\n".join(
        f'        tl.fromTo("#{sid}-sharpwrap", {{ scale: {cfg["punch_scale"]} }}, {{ scale: 1, '
        f'duration: {cfg["punch_duration"]}, ease: "expo.out", immediateRender: false }}, {t});'
        for t in switches)
    subjects = "\n".join(l for l in rows if f"{sid}-subj" in l)
    world = (f'        <div class="{sid}-grid kit-grid" style="position:absolute;inset:0;opacity:0.35"></div>\n'
             f'        <div class="{sid}-glow"></div>\n        <div class="{sid}-floor"></div>'
             if look.get("glow") else "")
    if look.get("plate_scale") is not None:
        plates = plates.replace(f'class="{sid}-plate',
                                f'style="transform: scale({look["plate_scale"]})" class="{sid}-plate')
    cam0, cam1 = look["push"]
    w, h = p.size
    html = TEMPLATE.format(
        W=w, H=h, gsap=p.cfg["root"]["gsap"], sid=sid, dur=sc["duration"], ground=look["ground"],
        plate_filter=look["plate"] or "none", subject_filter=look["subject"] or "none",
        room_filter="none", sharp_filter=cfg["sharp"], punch=punch,
        world=world, plates=plates, subjects=subjects, cam0=cam0, cam1=cam1,
        key=f'      <div class="{sid}-key"></div>' if look.get("key") else "",
        overlay_css=keep(old, "OVERLAY-CSS"), overlay_behind=keep(old, "OVERLAY-BEHIND"),
        overlay_front=keep(old, "OVERLAY-FRONT"), overlay_js=keep(old, "OVERLAY-JS"))
    return html, notes


def build(p: Project, only: list[str] | None = None) -> list[str]:
    timeline = p.timeline()
    cam = p.film / "assets" / "cam"
    done = []
    for sc in timeline["scenes"]:
        if sc["kind"] not in p.cfg["looks"] or (only and sc["id"] not in only):
            continue
        look = p.cfg["looks"][sc["kind"]]
        mine = own_lines(sc)
        missing = [ln["seq"] for ln in mine
                   if not (cam / f"{ln['seq']}.mp4").exists()
                   or (look["subject"] is not None and ln["seq"] not in p.cfg["camera"]["nocut"]
                       and not (cam / f"{ln['seq']}_a.webm").exists())]
        if missing:
            print(f"  {sc['id']}: waiting for camera media {missing} (run `film camprep`)")
            continue
        out = p.emit / "scenes" / sc["id"] / "index.html"
        old = out.read_text(encoding="utf-8") if out.exists() else ""
        if old and any(f"{t}-BEGIN" in old and f"{t}-END" not in old for t in SLOTS):
            raise SystemExit(f"{out}: an OVERLAY marker has no END; refusing to regenerate over it")
        html, notes = render(p, sc, old)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(html, encoding="utf-8")
        done.append(sc["id"])
        print(f"  {sc['id']} {sc['kind']:9} {sc['duration']:6.2f}s lines {[l['seq'] for l in mine]}"
              + (f"  ({'; '.join(notes)})" if notes else ""))
    print(f"scenes: {len(done)} camera scenes written")
    return done


def scaffold_scene(p: Project, sc: dict[str, Any]) -> Path:
    """An empty animated scene with the right id, size and duration, for a builder to fill."""
    w, h = p.size
    sid = sc["id"]
    out = p.emit / "scenes" / sid / "index.html"
    if out.exists():
        return out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width={w}, height={h}" />
  <script src="{p.cfg['root']['gsap']}"></script>
</head>
<body>
  <div id="{sid}" data-composition-id="{sid}" data-start="0" data-duration="{sc['duration']}" data-width="{w}" data-height="{h}">
    <link rel="stylesheet" href="lib/kit.css" />
    <style>
      #{sid} {{ position: relative; width: 100%; height: 100%; overflow: hidden; background: var(--ink, #0b0d12); }}
    </style>
    <!-- {sc.get('title', '')}: {sc.get('text', '')[:160]} -->
    <script>
      (function () {{
        const tl = gsap.timeline({{ paused: true }});
        window.__timelines["{sid}"] = tl;
      }})();
    </script>
  </div>
</body>
</html>
""", encoding="utf-8")
    return out
