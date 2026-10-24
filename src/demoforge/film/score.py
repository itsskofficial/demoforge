"""The music bed, cut to the voice spine.

Every section is pinned to a line: `pin` says which film moment `track_at` (a
time inside the track) lands on, usually a drop on a line's first word. Its
`start` and `end` are film times written the same way (`"0009+0.6"`, `"end"`),
so when the spine moves the music follows it.

Each stretch is measured on its own (EBU R128 over exactly the part that
plays) and levelled to the same loudness before its own `gain`, so `gain` is
pure intent: +3 for the quiet track that has to carry a scene, -3 for the one
under a dense paragraph. A section may stop dead on an impact (a 60 ms fade)
and the next can drop in on the break. The bed is always under voice: a
section that ends in a stretch with no voice is a gap in the film, and `check`
says so.

Also writes a voice + ducked bed preview, which is the quickest honest listen.
"""

from __future__ import annotations

import subprocess

from demoforge.film.project import Project, edge


def lufs(path, start: float, dur: float) -> float:
    """Integrated loudness of one stretch of a track."""
    err = subprocess.run(["ffmpeg", "-hide_banner", "-ss", f"{max(0.0, start):.3f}", "-t", f"{dur:.3f}",
                          "-i", str(path), "-af", "ebur128", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    return float(err.rsplit("I:", 1)[1].split("LUFS")[0])


def sections(p: Project, clips: dict, total: float) -> list[dict]:
    out = []
    for s in p.cfg["music"]["sections"]:
        start = edge(s["start"], clips, total)
        out.append(dict(track=s["track"], pin=edge(s.get("pin", s["start"]), clips, total),
                        track_at=float(s["track_at"]), start=start, end=edge(s["end"], clips, total),
                        gain=float(s.get("gain", 0)), fade_in=float(s.get("fade_in", 0.05)),
                        fade_out=float(s.get("fade_out", 0.5))))
    return out


def voice_gaps(clips: dict, longest: float = 2.0) -> list[tuple[float, float]]:
    """Stretches between lines longer than `longest`: there the music plays alone,
    which the film should only do on purpose."""
    lines = sorted((c["start"], c["end"]) for c in clips.values())
    return [(round(a[1], 2), round(b[0], 2)) for a, b in zip(lines, lines[1:]) if b[0] - a[1] > longest]


def build(p: Project) -> None:
    spine = p.spine()
    clips = {c["seq"]: c for c in spine["clips"]}
    total, sr = spine["duration"], p.sr
    mc = p.cfg["music"]
    tracks = p.path("music")
    secs = sections(p, clips, total)
    if not secs:
        raise SystemExit("film.json has no music.sections")
    parts, inputs = [], []
    for i, s in enumerate(secs):
        src = tracks / s["track"]
        if not src.exists():
            raise SystemExit(f"no track {src}")
        src_start = s["track_at"] - (s["pin"] - s["start"])
        dur = s["end"] - s["start"]
        level = mc["target_lufs"] - lufs(src, src_start, dur)
        inputs += ["-ss", f"{max(0.0, src_start):.4f}", "-t", f"{dur:.4f}", "-i", str(src)]
        pad = max(0.0, -src_start)  # the pin falls before the track begins: start late, in silence
        parts.append(
            f"[{i}:a]aresample={sr},aformat=channel_layouts=stereo,volume={level + s['gain']:.2f}dB,"
            f"afade=t=in:d={s['fade_in']},afade=t=out:st={max(0.0, dur - s['fade_out']):.4f}:d={s['fade_out']},"
            f"adelay={int(round((s['start'] + pad) * 1000))}:all=1[m{i}]")
        print(f"  {s['track']:>10} film {s['start']:7.2f}-{s['end']:7.2f}  from {src_start:6.2f}s"
              f"  level {level:+.1f} gain {s['gain']:+.0f}")
    mix = "".join(f"[m{i}]" for i in range(len(parts)))
    graph = (";".join(parts) + f";{mix}amix=inputs={len(parts)}:normalize=0,atrim=0:{total},"
             f"alimiter=limit={mc['limit']}[bed]")
    out = p.work / "music"
    out.mkdir(parents=True, exist_ok=True)
    bed = out / "bed.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex", graph, "-map", "[bed]",
                    "-ar", str(sr), "-c:a", "pcm_s24le", str(bed)], check=True)
    if mc.get("preview"):
        md = p.cfg["mix"]["music_db"]
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-i", str(p.spine_dir / "voice.wav"), "-i", str(bed),
             "-filter_complex",
             (f"[0:a]asplit=2[v][sc];[1:a]volume={md}dB[b];"
              "[b][sc]sidechaincompress=threshold=0.05:ratio=2.5:attack=15:release=350:makeup=1[duck];"
              "[v][duck]amix=inputs=2:normalize=0,alimiter=limit=0.89[out]"),
             "-map", "[out]", "-ar", str(sr), "-c:a", "pcm_s24le", str(out / "preview_mix.wav")], check=True)
    for a, b in voice_gaps(clips):
        print(f"  ! music plays alone for {b - a:.1f}s at {a:.2f}s")
    print(f"score: {len(secs)} sections -> {bed}")
