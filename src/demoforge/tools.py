"""One feature, one file.

The modes are pipelines: a project folder, a profile, three or four steps in
order. Most of what they do is a single operation that somebody wants on its
own -- put music under this, caption this, cut the dead air out of this --
and none of it should need a project to exist first.

So every feature the modes are built from is also a command here:

    demoforge tool score     --video talk.mp4 --music-dir ~/Music
    demoforge tool caption   --video talk.mp4
    demoforge tool tighten   --video take.mp4 --speed 1.05
    demoforge tool gaze      --video take.mp4
    demoforge tool cover     --video reel.mp4 --line "Stop *vibe coding*."
    demoforge tool punch     --video take.mp4 --zoom 1.2 --mirror
    demoforge tool voice     --text "..." --reference me.mp3
    demoforge tool lipsync   --video face.mp4 --audio narration.wav
    demoforge tool matte     --video head.mp4 --over "#0A0B0F"
    demoforge tool restore   --video synced.mp4
    demoforge tool voice-check --audio read.wav --reference me.wav
    demoforge tool broll-generate --prompt "A developer's desk at night..."
    demoforge tool broll-search   --query "cafe laptop typing"

Each one writes into a fresh folder under `out/tools/<name>/` unless `--out`
says otherwise, and prints every file it made on a line starting with
`  -> `. Nothing here is new machinery: each function is the same code the
modes call, with the profile taken out of the way.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from demoforge.config import OUT, ROOT
from demoforge.media import (clean_voice, duration, level_bed, local_track,
                             loudness, master, probe, sourced_track)

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

TOOLS_OUT = OUT / "tools"

# The accent names the two kits know, so a tool accepts either vocabulary.
_ACCENTS = {
    "lime": (200, 255, 46), "cyan": (56, 205, 214), "coral": (255, 107, 92),
    "gold": (240, 190, 90), "violet": (167, 139, 250), "white": (244, 244, 244),
    "blue": (88, 166, 255), "red": (248, 105, 96), "green": (72, 207, 115),
}


def made(path: Path) -> Path:
    print(f"  -> {path}")
    return path


def run_dir(name: str, stem: str, out: str | None) -> Path:
    if out:
        path = Path(out).expanduser()
    else:
        path = TOOLS_OUT / name / f"{time.strftime('%Y%m%d-%H%M%S')}-{stem[:40]}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def accent_hex(name: str) -> str:
    if name.startswith("#"):
        return name
    r, g, b = _ACCENTS.get(name, _ACCENTS["lime"])
    return "#%02X%02X%02X" % (r, g, b)


def _words(video: Path, work: Path, model: str, corrections: dict[str, str]):
    from demoforge.transcribe import correct, transcribe
    print("\n== transcribe ==")
    script = transcribe(video, work / "transcript.json", model)
    return correct(script.words, corrections)


def _corrections(raw: str | None) -> dict[str, str]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        raise SystemExit("--corrections wants JSON: {\"heard\": \"meant\"}")
    return {str(k): str(v) for k, v in data.items()}


# ---------------------------------------------------------------------------
# score
# ---------------------------------------------------------------------------


def score(video: Path, out: Path, music_dir: str = "", music_file: str = "",
          music_offset: float = 0.0, music_under: float = -9.0,
          music_ratio: float = 4.0, music_query: list[str] | None = None,
          music_style: str = "lofi", loudness_target: float = -14.0) -> Path:
    """A bed under the voice. The reel's music step, without the reel."""
    from demoforge.music import mix

    work = out / "work"
    work.mkdir(exist_ok=True)
    seconds = duration(video)
    need = seconds + 3 + music_offset
    profile = SimpleNamespace(music_dir=music_dir, music_file=music_file,
                              music_query=music_query or ["upbeat energetic tech"],
                              music_offset=music_offset, music_style=music_style)

    print("\n== bed ==")
    track = local_track(profile, need) or sourced_track(profile, need, work)

    print("\n== voice ==")
    voiced = clean_voice(video, work / "voice.mp4")
    flat = level_bed(track, work / "bed-level.wav", music_offset)

    print("\n== mix ==")
    voice_lufs, bed_lufs = loudness(voiced), loudness(flat)
    gain = (-20.0 if None in (voice_lufs, bed_lufs)
            else (voice_lufs + music_under) - bed_lufs)
    print(f"  bed {gain:+.1f}dB for {music_under:+.0f} LU under the voice")
    scored = work / "scored.mp4"
    mix(voiced, flat, scored, music_db=gain, duck_db=0.0, ratio=music_ratio,
        release=240)
    result = master(scored, out / f"{video.stem}-scored.mp4", lufs=loudness_target)
    voiced.unlink(missing_ok=True)
    scored.unlink(missing_ok=True)
    return made(result)


# ---------------------------------------------------------------------------
# caption
# ---------------------------------------------------------------------------


def caption(video: Path, out: Path, model: str = "medium.en", words_per: int = 3,
            accent: str = "lime", corrections: dict[str, str] | None = None) -> Path:
    from demoforge import captions as caps
    from demoforge import reelkit

    width, height, _ = probe(video)
    words = _words(video, out, model, corrections or {})
    print("\n== captions ==")
    vertical = height > width
    ass = out / "captions.ass"
    caps.write(words, ass, width, height, accent_hex(accent), max_words=words_per,
               font="Archivo Black",
               size_frac=0.052 if vertical else 0.058,
               margin_v_frac=0.205 if vertical else 0.052,
               margin_h_frac=0.10 if vertical else 0.215)
    made(caps.srt(words, out / f"{video.stem}.srt"))
    result = out / f"{video.stem}-captioned.mp4"
    caps.burn(video, ass, result, fontsdir=reelkit.FONTS)
    made(out / "transcript.json")
    return made(result)


# ---------------------------------------------------------------------------
# tighten
# ---------------------------------------------------------------------------


def tighten_video(video: Path, out: Path, model: str = "medium.en",
                  pause_cut: float = 0.72, pause_keep: float = 0.30,
                  speed: float = 1.0, mirror: bool = False,
                  corrections: dict[str, str] | None = None) -> Path:
    from demoforge.edit import lift, tighten
    from demoforge.transcribe import destutter

    words = _words(video, out, model, corrections or {})
    clean, dropped = destutter(words)
    print("\n== cut ==")
    keeps = tighten(clean, pause_cut=pause_cut, pause_keep=pause_keep)
    kept = sum(b - a for a, b in keeps)
    total = duration(video)
    print(f"  {len(keeps)} segments, {kept:.1f}s of {total:.1f}s kept "
          f"({total - kept:.1f}s of silence and retakes out)"
          + (f", {len(dropped)} false starts dropped" if dropped else ""))
    (out / "cut.json").write_text(json.dumps(
        {"source": str(video), "keeps": [[round(a, 3), round(b, 3)] for a, b in keeps],
         "speed": speed, "mirror": mirror}, indent=1), encoding="utf-8")
    result = out / f"{video.stem}-tight.mp4"
    lift(video, keeps, result, speed=speed, mirror=mirror)
    made(out / "transcript.json")
    made(out / "cut.json")
    return made(result)


# ---------------------------------------------------------------------------
# gaze
# ---------------------------------------------------------------------------


def gaze_report(video: Path, out: Path, fps: float = 5.0) -> Path:
    from demoforge import gaze as gz
    _, _, total = probe(video)
    print("\n== gaze ==")
    samples = gz.scan(video, fps, out / "gaze.json")
    spans = gz.windows(samples)
    gz.report(samples, spans, total)
    on = sum(b - a for a, b in spans)
    lines = [f"{video.name}: {on:.1f}s of {total:.1f}s on the lens "
             f"({100 * on / max(total, 0.01):.0f}%)", ""]
    lines += [f"  {a:7.2f}  {b:7.2f}   {b - a:5.1f}s" for a, b in spans]
    (out / "report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    made(out / "gaze.json")
    return made(out / "report.txt")


# ---------------------------------------------------------------------------
# cover
# ---------------------------------------------------------------------------


def cover_frame(video: Path, out: Path, at: float = 0.5, lines: list[str] | None = None,
                accent: str = "lime") -> Path:
    from demoforge.reel import cover as reel_cover
    width, height, _ = probe(video)
    stub = SimpleNamespace(accent=accent if accent in _ACCENTS else "lime",
                           size=(width, height), work=out, home=out, name=video.stem)
    return made(reel_cover(stub, at, lines or ["Stop *scrolling*."],
                           out / f"{video.stem}-cover.jpg", source=video,
                           size=(width, height)))


# ---------------------------------------------------------------------------
# punch
# ---------------------------------------------------------------------------


def punch(video: Path, out: Path, zoom: float = 1.2, mirror: bool = True,
          speed: float = 1.0, face: bool = True) -> Path:
    """Mirror, a zoom centred on the face, and a little speed.

    The zoom is a crop followed by a scale back to the source size, centred on
    the median face position measured by `gaze` -- or on the frame if the
    landmarker is not installed or finds nobody.
    """
    width, height, seconds = probe(video)
    fx, fy = 0.5, 0.45
    if face and zoom > 1.0:
        try:
            from demoforge import gaze as gz
            print("\n== face ==")
            samples = gz.scan(video, 2.0, out / "gaze.json")
            fx, fy = gz.framing(samples, 0, seconds, mirror=False)
            print(f"  centre ({fx:.2f}, {fy:.2f})")
        except Exception as exc:
            print(f"  no face measurement ({exc.__class__.__name__}); centring")

    print("\n== render ==")
    cw, ch = int(width / zoom) // 2 * 2, int(height / zoom) // 2 * 2
    x = min(max(int(fx * width - cw / 2), 0), width - cw)
    y = min(max(int(fy * height - ch / 2), 0), height - ch)
    chain = []
    if zoom > 1.0:
        chain.append(f"crop={cw}:{ch}:{x}:{y},scale={width}:{height}:flags=lanczos")
    if mirror:
        chain.append("hflip")
    if speed != 1.0:
        chain.append(f"setpts=PTS/{speed:.4f}")
    chain.append("setsar=1")
    audio = [f"atempo={speed:.4f}"] if speed != 1.0 else []
    result = out / f"{video.stem}-punched.mp4"
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(video),
           "-vf", ",".join(chain)]
    if audio:
        cmd += ["-af", ",".join(audio)]
    cmd += ["-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(result)]
    subprocess.run(cmd, check=True)
    return made(result)


# ---------------------------------------------------------------------------
# voice, lipsync, presence, b-roll: thin, because the heavy lifting has its own module
# ---------------------------------------------------------------------------


def voice(text: str, reference: Path, out: Path, pace: float = 0.85) -> Path:
    from demoforge import voice as vc
    print("\n== reference ==")
    ref = vc.prepare(reference, out / "reference.wav", start=0.0, dur=20.0)
    print("\n== say ==")
    argv = ["voice", "say", "--text", text, "--reference", str(ref),
            "--pace", str(pace), "--out", str(out / "spoken.wav")]
    old = sys.argv
    sys.argv = argv
    try:
        vc.main()
    finally:
        sys.argv = old
    return made(out / "spoken.wav")


def lipsync(video: Path, audio: Path, out: Path, chunk: float = 20.0) -> Path:
    result = out / f"{video.stem}-synced.mp4"
    argv = [sys.executable, "-m", "demoforge.face", "sync", "--video", str(video),
            "--audio", str(audio), "--out", str(result), "--chunk", str(chunk)]
    print("  " + " ".join(argv[2:]))
    subprocess.run(argv, check=True, cwd=str(ROOT))
    return made(result)


def matte(video: Path, out: Path, over: str | None = None,
          ratio: float | None = None) -> Path:
    """The presenter cut out of their room: RGBA ProRes, or flattened onto
    `over` (a #RRGGBB or an image) as h264."""
    from demoforge import presence
    suffix = ".mov" if over is None else ".mp4"
    return made(presence.matte(video, out / f"{video.stem}-matte{suffix}", over, ratio))


def restore(video: Path, out: Path, region: str = "mouth",
            strength: float = 0.85, smooth: float = 0.6) -> Path:
    """Sharpen the lip-synced mouth, for a presenter shown larger than an inset."""
    from demoforge import presence
    return made(presence.restore(video, out / f"{video.stem}-restored.mp4", region,
                                 strength, smooth))


def voice_check(audio: list[Path], out: Path, reference: Path | None = None,
                words: int | None = None) -> Path:
    """Pitch, dynamics, pauses and rate of a read, against the voice it clones."""
    from demoforge import voiceqa
    ref = voiceqa.analyse(reference) if reference else None
    rows = []
    for path in audio:
        row = voiceqa.analyse(path, words)
        row["notes"] = voiceqa.verdict(row, ref)
        rows.append(row)
        print(f"  {row['file']}  pitch sd {row['pitch_semitone_sd']} st  "
              f"loudness sd {row['loudness_sd_db']} dB  {row['pauses']} pauses  "
              f"{row['wpm'] or '-'} wpm  -- {row['notes']}")
    report = out / "voice-check.json"
    report.write_text(json.dumps({"reference": ref, "reads": rows}, indent=1),
                      encoding="utf-8")
    return made(report)


def free_ram_gb() -> float | None:
    """Free physical memory, or None where it cannot be read."""
    try:
        if sys.platform == "win32":
            import ctypes

            class Status(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong),
                            ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong),
                            ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong),
                            ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            status = Status()
            status.dwLength = ctypes.sizeof(Status)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
            return status.ullAvailPhys / 1e9
        import os
        return os.sysconf("SC_AVPHYS_PAGES") * os.sysconf("SC_PAGE_SIZE") / 1e9
    except Exception:
        return None


ENCODER_RAM_GB = 10.0


def broll_generate(prompt: str, out: Path, aspect: str = "vertical",
                   seconds: float = 4.0, refine: bool = True) -> Path:
    """Two processes on purpose: the text encoder and the transformer do not
    fit in RAM together on the machines this targets. See `broll.py`."""
    from demoforge import broll

    # The T5 encoder is de-quantised into about 9.5 GB of system RAM before
    # it says a word. On a 16 GB laptop with a browser open that is a two
    # minute crunch followed by an allocation failure, so say so up front.
    free = free_ram_gb()
    if free is not None and free < ENCODER_RAM_GB:
        raise SystemExit(
            f"  {free:.1f} GB of RAM is free and the text encoder needs about "
            f"{ENCODER_RAM_GB:.0f} GB. Close the browser and anything else large, "
            f"then run this again.")
    shot_id = f"shot-{time.strftime('%H%M%S')}"
    shots = out / "shots.json"
    shots.write_text(json.dumps([{"id": shot_id, "prompt": prompt, "aspect": aspect,
                                  "seconds": seconds}], indent=1), encoding="utf-8")
    for phase, extra in (("encode", []), ("sample", [] if refine else ["--no-refine"])):
        print(f"\n== {phase} ==")
        subprocess.run([sys.executable, "-m", "demoforge.broll", phase,
                        "--shots", str(shots), *extra], check=True, cwd=str(ROOT))
    produced = broll.VIDEO / f"{shot_id}.mp4"
    if not produced.exists():
        raise SystemExit(f"the sampler wrote nothing at {produced}")
    result = out / f"{shot_id}.mp4"
    shutil.move(str(produced), str(result))
    return made(result)


PIXABAY = "https://pixabay.com/api/videos/"
PIXABAY_LICENCE = "Pixabay Content License — free for commercial use, no attribution"


def broll_search(query: str, out: Path, count: int = 4, orientation: str = "vertical",
                 min_seconds: float = 5.0, key: str = "") -> list[Path]:
    """Stock clips, with the licence recorded next to each.

    The record matters more than it looks. Pixabay's licence is fine for a
    cutaway inside a video and forbids redistributing the clip on its own; the
    first time somebody asks "can we ship the b-roll separately?" the answer
    is in the folder rather than in somebody's memory.
    """
    key = key or _pixabay_key()
    if not key:
        raise SystemExit("no PIXABAY_API_KEY: add it in Settings, or to .env")
    params = {"key": key, "q": query, "per_page": max(3, min(200, count * 4)),
              "safesearch": "true", "order": "popular"}
    if orientation == "vertical":
        params["orientation"] = "vertical"
    elif orientation == "horizontal":
        params["orientation"] = "horizontal"
    url = PIXABAY + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "demoforge/0.3"})
    with urllib.request.urlopen(req, timeout=60) as res:
        hits = json.loads(res.read().decode("utf-8")).get("hits", [])
    hits = [h for h in hits if float(h.get("duration", 0)) >= min_seconds]
    # Pixabay's video search ignores `orientation`, and nearly all stock
    # footage is wide. So the orientation asked for is a preference: matching
    # clips first, the rest after, and a note on each one that will be
    # cropped to cover a vertical frame rather than filling it.
    wanted = [h for h in hits if _oriented(h, orientation)]
    others = [h for h in hits if not _oriented(h, orientation)]
    print(f"  {len(hits)} candidates for \"{query}\""
          + (f", {len(wanted)} {orientation}" if orientation != "any" else ""))
    got: list[Path] = []
    for hit in wanted + others:
        if len(got) >= count:
            break
        rendition = pick_rendition(hit.get("videos", {}))
        if not rendition:
            continue
        fits = _oriented(hit, orientation)
        slug = _slug(hit.get("tags", ""), hit.get("id"))
        dest = out / f"{slug}.mp4"
        try:
            req = urllib.request.Request(rendition["url"],
                                         headers={"User-Agent": "demoforge/0.3"})
            with urllib.request.urlopen(req, timeout=300) as res, dest.open("wb") as f:
                shutil.copyfileobj(res, f)
        except Exception as exc:
            print(f"  {slug}: download failed ({exc.__class__.__name__})")
            dest.unlink(missing_ok=True)
            continue
        (out / f"{slug}.source.json").write_text(json.dumps({
            "id": hit.get("id"), "page": hit.get("pageURL"), "tags": hit.get("tags"),
            "seconds": hit.get("duration"), "width": rendition.get("width"),
            "height": rendition.get("height"), "user": hit.get("user"),
            "licence": PIXABAY_LICENCE,
            "note": "Fine inside a video. Not for redistribution as a standalone clip."},
            indent=1, ensure_ascii=False), encoding="utf-8")
        print(f"  {slug}.mp4  {rendition.get('width')}x{rendition.get('height')}  "
              f"{hit.get('duration')}s"
              + ("" if fits or orientation == "any" else "  (will be cropped to cover)"))
        got.append(made(dest))
    if not got:
        print("  nothing downloaded")
    return got


def _oriented(hit: dict[str, Any], orientation: str) -> bool:
    item = (hit.get("videos") or {}).get("large") or (hit.get("videos") or {}).get("medium") or {}
    w, h = int(item.get("width") or 0), int(item.get("height") or 0)
    if orientation == "vertical":
        return h > w
    if orientation == "horizontal":
        return w >= h
    return True


def pick_rendition(videos: dict[str, Any]) -> dict[str, Any] | None:
    """The largest rendition that is still 1080p, in either orientation.

    `large` is often 4K, which is four times the download for a cutaway that
    will be scaled to 1080 anyway. "1080p" is judged on the short edge, so a
    1080x1920 vertical clip counts, the same as a 1920x1080 wide one.
    """
    ranked = []
    for name in ("large", "medium", "small", "tiny"):
        item = videos.get(name) or {}
        w, h = int(item.get("width") or 0), int(item.get("height") or 0)
        if not item.get("url") or not w or not h:
            continue
        long_edge = max(w, h)
        ranked.append((min(w, h) <= 1080, long_edge, item))
    if not ranked:
        return None
    # Prefer the largest that is still at most 1080, else the smallest above.
    within = sorted((r for r in ranked if r[0]), key=lambda r: -r[1])
    above = sorted((r for r in ranked if not r[0]), key=lambda r: r[1])
    return (within or above)[0][2]


def _slug(tags: str, ident: Any) -> str:
    words = [w.strip().replace(" ", "-") for w in tags.split(",") if w.strip()][:3]
    base = "-".join(words) or "clip"
    return f"{base}-{ident}"[:60]


def _pixabay_key() -> str:
    import os
    value = os.environ.get("PIXABAY_API_KEY", "")
    env = ROOT / ".env"
    if not value and env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("PIXABAY_API_KEY"):
                value = line.split("=", 1)[1].strip().strip('"').strip("'")
    return value


# ---------------------------------------------------------------------------
# cli
# ---------------------------------------------------------------------------


def _bool(value: str) -> bool:
    return str(value).lower() in ("1", "true", "yes", "on")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="demoforge tool", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="name", required=True)

    def add(name: str, *, video: bool = True) -> argparse.ArgumentParser:
        p = sub.add_parser(name)
        if video:
            p.add_argument("--video", required=True)
        p.add_argument("--out", default=None, help="a folder; default out/tools/<name>/…")
        return p

    p = add("score")
    p.add_argument("--music-dir", default="")
    p.add_argument("--music-file", default="")
    p.add_argument("--music-offset", type=float, default=0.0)
    p.add_argument("--music-under", type=float, default=-9.0)
    p.add_argument("--music-ratio", type=float, default=4.0)
    p.add_argument("--music-query", action="append", default=None)
    p.add_argument("--music-style", default="lofi", choices=["lofi", "trap"])
    p.add_argument("--loudness", type=float, default=-14.0)

    p = add("caption")
    p.add_argument("--whisper-model", default="medium.en")
    p.add_argument("--caption-words", type=int, default=3)
    p.add_argument("--accent", default="lime")
    p.add_argument("--corrections", default=None, help='JSON: {"heard": "meant"}')

    p = add("tighten")
    p.add_argument("--whisper-model", default="medium.en")
    p.add_argument("--pause-cut", type=float, default=0.72)
    p.add_argument("--pause-keep", type=float, default=0.30)
    p.add_argument("--speed", type=float, default=1.0)
    p.add_argument("--mirror", action="store_true")
    p.add_argument("--corrections", default=None)

    p = add("gaze")
    p.add_argument("--fps", type=float, default=5.0)

    p = add("cover")
    p.add_argument("--at", type=float, default=0.5)
    p.add_argument("--line", action="append", default=None)
    p.add_argument("--accent", default="lime")

    p = add("punch")
    p.add_argument("--zoom", type=float, default=1.2)
    p.add_argument("--mirror", action="store_true")
    p.add_argument("--speed", type=float, default=1.0)
    p.add_argument("--face", action="store_true")

    p = add("voice", video=False)
    p.add_argument("--text", required=True)
    p.add_argument("--reference", required=True)
    p.add_argument("--pace", type=float, default=0.85)

    p = add("lipsync")
    p.add_argument("--audio", required=True)
    p.add_argument("--chunk", type=float, default=20.0)

    p = add("matte")
    p.add_argument("--over", default=None,
                   help="#RRGGBB or an image to composite onto; omit for RGBA")
    p.add_argument("--ratio", type=float, default=None)

    p = add("restore")
    p.add_argument("--region", default="mouth", choices=["mouth", "face"])
    p.add_argument("--strength", type=float, default=0.85)
    p.add_argument("--smooth", type=float, default=0.6)

    p = add("voice-check", video=False)
    p.add_argument("--audio", action="append", required=True,
                   help="a read to measure; repeat for more")
    p.add_argument("--reference", default=None, help="the clip being cloned")
    p.add_argument("--words", type=lambda v: int(float(v)), default=None,
                   help="word count of the script")

    p = add("broll-generate", video=False)
    p.add_argument("--prompt", required=True)
    p.add_argument("--aspect", default="vertical", choices=["vertical", "wide", "square"])
    p.add_argument("--seconds", type=float, default=4.0)
    p.add_argument("--refine", action="store_true")

    p = add("broll-search", video=False)
    p.add_argument("--query", required=True)
    p.add_argument("--count", type=int, default=4)
    p.add_argument("--orientation", default="vertical",
                   choices=["vertical", "horizontal", "any"])
    p.add_argument("--min-seconds", type=float, default=5.0)

    args = ap.parse_args(argv)
    name = args.name
    video = Path(args.video).expanduser() if getattr(args, "video", None) else None
    if video is not None and not video.is_file():
        raise SystemExit(f"no such video: {video}")
    stem = (video.stem if video else
            Path(args.audio[0]).stem if name == "voice-check" else
            getattr(args, "query", None) or getattr(args, "prompt", "")[:24] or name)
    out = run_dir(name, "".join(c if c.isalnum() else "-" for c in stem), args.out)
    print(f"  {name}  ->  {out}")

    if name == "score":
        score(video, out, args.music_dir, args.music_file, args.music_offset,
              args.music_under, args.music_ratio, args.music_query, args.music_style,
              args.loudness)
    elif name == "caption":
        caption(video, out, args.whisper_model, args.caption_words, args.accent,
                _corrections(args.corrections))
    elif name == "tighten":
        tighten_video(video, out, args.whisper_model, args.pause_cut, args.pause_keep,
                      args.speed, args.mirror, _corrections(args.corrections))
    elif name == "gaze":
        gaze_report(video, out, args.fps)
    elif name == "cover":
        cover_frame(video, out, args.at, args.line, args.accent)
    elif name == "punch":
        punch(video, out, args.zoom, args.mirror, args.speed, args.face)
    elif name == "voice":
        voice(args.text, Path(args.reference).expanduser(), out, args.pace)
    elif name == "lipsync":
        lipsync(video, Path(args.audio).expanduser(), out, args.chunk)
    elif name == "matte":
        matte(video, out, args.over, args.ratio)
    elif name == "restore":
        restore(video, out, args.region, args.strength, args.smooth)
    elif name == "voice-check":
        voice_check([Path(a).expanduser() for a in args.audio], out,
                    Path(args.reference).expanduser() if args.reference else None,
                    args.words)
    elif name == "broll-generate":
        broll_generate(args.prompt, out, args.aspect, args.seconds, args.refine)
    elif name == "broll-search":
        broll_search(args.query, out, args.count, args.orientation, args.min_seconds)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
