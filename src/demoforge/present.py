"""Presenter mode: you record the words, demoforge builds everything else.

The rest of this repository clones a voice, speaks a script and lip-syncs a
face. That path is intact and is still the default. This is the other one, and
it exists because a cloned voice is convincing right up until someone who knows
you watches it, and a re-dubbed face is convincing right up until it is on a
big screen. For anything you put your own name on, your real voice reading your
real script is better than any model, and it costs one afternoon.

So the division of labour inverts. **You record yourself. Nothing else.** The
slides, the terminal captures, the timing, the framing and the cut are built
here.

The one structural difference from the generated path is worth stating clearly,
because everything else follows from it:

    the generated path knows the picture and discovers the words
    presenter mode knows the words and builds the picture to fit

In the generated path a segment is rendered first and then padded to whatever
length the speech turned out to be, which is why `assemble` holds final frames.
Here the take already exists before anything is drawn, so a slide is rendered
at *exactly* its take's duration and there is nothing to pad. A re-recorded
take re-renders one slide and leaves the rest alone.

    demoforge present script  --project probeit      # what to say, and when
    demoforge present intake  --project probeit      # what you have recorded
    demoforge present build   --project probeit      # the cut

Framing is per section. ``full`` puts you on screen alone, ``corner`` puts the
slide up with you inset, ``off`` is slide-only with your voice over it. Use
``full`` where you are making an argument and ``corner`` where the screen is
carrying it -- a talking head over a table of numbers competes with the numbers.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from demoforge.config import FPS, HEIGHT, OUT, PROJECTS, WIDTH
from demoforge.media import duration, has_video

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

# Kept as a name so a profile can still be given as a bare folder path.
FRAMINGS = ("full", "corner", "off")
VISUALS = ("slide", "screen", "none")

# Words per second for the duration estimate in the script. Deliberately slow:
# people read a teleprompter faster than they talk, then wonder why the slide
# is still up. Measured over the livingeval narration at a comfortable pace.
WORDS_PER_SECOND = 2.5

VIDEO_SUFFIXES = (".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v")
AUDIO_SUFFIXES = (".wav", ".m4a", ".mp3", ".aac", ".flac")

ASPECTS = {
    "16:9": (1920, 1080),
    "9:16": (1080, 1920),
    "1:1": (1080, 1080),
}


# ---------------------------------------------------------------------------
# the profile
# ---------------------------------------------------------------------------


@dataclass
class Section:
    """One stretch of speech, and what is on screen behind it."""

    id: str
    say: str
    note: str = ""
    presenter: str = "corner"
    visual_kind: str = "slide"
    visual_name: str = ""
    screen: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def words(self) -> int:
        return len(re.findall(r"[\w']+", self.say))

    @property
    def estimate(self) -> float:
        """Roughly how long this will take to say."""
        return round(self.words / WORDS_PER_SECOND, 1)

    def validate(self) -> None:
        if self.presenter not in FRAMINGS:
            raise ValueError(
                f"section {self.id!r}: presenter={self.presenter!r}, "
                f"expected one of {FRAMINGS}"
            )
        if self.visual_kind not in VISUALS:
            raise ValueError(
                f"section {self.id!r}: visual kind={self.visual_kind!r}, "
                f"expected one of {VISUALS}"
            )
        if self.presenter == "off" and self.visual_kind == "none":
            raise ValueError(
                f"section {self.id!r} has no presenter and no visual, so it is "
                "a black screen with a voice over it. Pick one."
            )


@dataclass
class Profile:
    name: str
    title: str
    sections: list[Section]
    aspect: str = "16:9"
    directory: Path = field(default_factory=Path)

    @property
    def size(self) -> tuple[int, int]:
        return ASPECTS.get(self.aspect, (WIDTH, HEIGHT))

    @property
    def takes(self) -> Path:
        return self.directory / "takes"

    @property
    def estimate(self) -> float:
        return sum(section.estimate for section in self.sections)


def load(project: str) -> Profile:
    """Read ``projects/<project>/presentation.json``."""
    directory = Path(project) if Path(project).is_dir() else PROJECTS / project
    path = directory / "presentation.json"
    if not path.exists():
        raise SystemExit(
            f"no presentation profile at {path}.\n"
            f"Presenter mode needs one; see projects/probeit/presentation.json "
            f"for the shape."
        )
    payload = json.loads(path.read_text(encoding="utf-8"))

    sections = []
    for raw in payload["sections"]:
        visual = raw.get("visual") or {}
        section = Section(
            id=raw["id"],
            say=raw["say"],
            note=raw.get("note", ""),
            presenter=raw.get("presenter", "corner"),
            visual_kind=visual.get("kind", "slide"),
            visual_name=visual.get("name", raw["id"]),
            screen=visual.get("path"),
            meta=raw.get("meta", {}),
        )
        section.validate()
        sections.append(section)

    seen = [s.id for s in sections]
    if len(set(seen)) != len(seen):
        duplicates = {i for i in seen if seen.count(i) > 1}
        raise SystemExit(f"duplicate section ids: {sorted(duplicates)}")

    return Profile(
        name=directory.name,
        title=payload.get("title", directory.name),
        sections=sections,
        aspect=payload.get("aspect", "16:9"),
        directory=directory,
    )


# ---------------------------------------------------------------------------
# ffmpeg helpers
# ---------------------------------------------------------------------------


def speech_window(path: Path, threshold: str = "-38dB", minimum: float = 0.35
                  ) -> tuple[float, float]:
    """First and last moment of sound, from ffmpeg's own silence detector.

    Used to trim the dead air at the top and tail of a take -- the seconds
    between pressing record and starting to talk. Trimming is done from the
    *detected* window rather than by a fixed offset because the gap is
    different on every take and a fixed offset eventually eats a word.
    """
    total = duration(path)
    result = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(path),
         "-af", f"silencedetect=noise={threshold}:d={minimum}", "-f", "null", "-"],
        capture_output=True, text=True)
    log = result.stderr

    starts = [float(m) for m in re.findall(r"silence_start: (-?[\d.]+)", log)]
    ends = [float(m) for m in re.findall(r"silence_end: (-?[\d.]+)", log)]

    # Leading silence only counts if it starts at the very top of the file.
    begin = 0.0
    if starts and starts[0] <= 0.05 and ends:
        begin = ends[0]
    # Trailing silence only counts if nothing follows it.
    finish = total
    if starts and (not ends or starts[-1] > ends[-1]):
        finish = starts[-1]

    if finish - begin < 0.5:  # detector confused; keep the whole thing
        return 0.0, total
    return begin, finish


# ---------------------------------------------------------------------------
# 1. the script
# ---------------------------------------------------------------------------


def write_script(profile: Profile, out: Path | None = None) -> Path:
    """The document you read from while recording.

    One block per take, in recording order, with the words to say, the
    direction, the framing, and what will be on screen behind you. The target
    duration is an estimate and is there to catch a section that has quietly
    become ninety seconds long -- it is not a constraint, because the slide is
    built to your take rather than the other way round.
    """
    out = out or profile.directory / "RECORDING-SCRIPT.md"

    lines = [
        f"# {profile.title} — recording script",
        "",
        f"**{len(profile.sections)} takes · about {_clock(profile.estimate)} of "
        f"finished video · {profile.aspect}**",
        "",
        "Record one file per take and name it after the take id "
        "(`01_hook.mp4`, `02_problem.mp4`, …). Drop them all in:",
        "",
        f"    {profile.takes}",
        "",
        "Then run `demoforge present build --project "
        f"{profile.name}`.",
        "",
        "## Before you start",
        "",
        "- **Record every take at the same distance, framing and lighting.** "
        "Sections cut straight into each other; a take shot half a metre closer "
        "reads as a different video.",
        "- **Leave two seconds of silence at both ends of every take.** They are "
        "trimmed automatically, and they give the trimmer something unambiguous "
        "to find.",
        "- **A fluffed line costs one take, not the video.** Stop, breathe, and "
        "say the whole section again. Only the last clean attempt in the file "
        "is used if you re-record the file.",
        "- **Do not rush to hit the target time.** The slide is drawn to the "
        "length of your take. Saying it well at 20 seconds beats saying it "
        "badly at 14.",
        "",
        "---",
        "",
    ]

    for index, section in enumerate(profile.sections, start=1):
        framing = {
            "full": "**YOU, FULL FRAME** — look down the lens",
            "corner": "**SLIDE, you inset bottom-right** — the screen is doing the work",
            "off": "**SLIDE ONLY** — voice over, you are not on screen",
        }[section.presenter]

        visual = {
            "slide": f"slide `{section.visual_name}`",
            "screen": f"screen recording `{section.screen}`",
            "none": "nothing",
        }[section.visual_kind]

        lines += [
            f"## {index}. `{section.id}`",
            "",
            f"- {framing}",
            f"- On screen: {visual}",
            f"- Target: **~{_clock(section.estimate)}** ({section.words} words)",
        ]
        if section.note:
            lines += [f"- Direction: *{section.note}*"]
        lines += ["", "> " + section.say.replace("\n", "\n> "), "", "---", ""]

    lines += [
        "## When you are done",
        "",
        "```bash",
        f"demoforge present intake --project {profile.name}",
        f"demoforge present build  --project {profile.name}",
        "```",
        "",
        "`intake` tells you which takes are missing, which are much longer than "
        "planned, and how much silence it will trim. `build` renders the slides "
        "to your timings and produces the cut.",
        "",
    ]

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"  {out}")
    print(f"  {len(profile.sections)} takes, about {_clock(profile.estimate)} of video")
    return out


def _clock(seconds: float) -> str:
    minutes, rest = divmod(int(round(seconds)), 60)
    return f"{minutes}:{rest:02d}" if minutes else f"{rest}s"


# ---------------------------------------------------------------------------
# 2. intake
# ---------------------------------------------------------------------------


def find_take(profile: Profile, section: Section) -> Path | None:
    """The recorded file for a section, whatever container it arrived in."""
    for suffix in (*VIDEO_SUFFIXES, *AUDIO_SUFFIXES):
        candidate = profile.takes / f"{section.id}{suffix}"
        if candidate.exists():
            return candidate
    # Tolerate a camera's own prefix, so long as the id is in the name.
    matches = sorted(
        path
        for path in profile.takes.glob("*")
        if path.suffix.lower() in (*VIDEO_SUFFIXES, *AUDIO_SUFFIXES)
        and section.id in path.stem
    )
    return matches[-1] if matches else None


def intake(profile: Profile, trim: bool = True) -> list[dict[str, Any]]:
    """Report what has been recorded, and what each take will contribute."""
    profile.takes.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []

    for section in profile.sections:
        path = find_take(profile, section)
        row: dict[str, Any] = {
            "id": section.id,
            "presenter": section.presenter,
            "estimate": section.estimate,
            "path": str(path) if path else None,
        }
        if path is None:
            row["status"] = "missing"
            rows.append(row)
            continue

        raw = duration(path)
        begin, finish = speech_window(path) if trim else (0.0, raw)
        row.update(
            raw=round(raw, 2),
            start=round(begin, 2),
            end=round(finish, 2),
            seconds=round(finish - begin, 2),
            video=has_video(path),
            status="ok",
        )
        if section.presenter in ("full", "corner") and not row["video"]:
            row["status"] = "audio-only"
        rows.append(row)

    return rows


def report(profile: Profile, rows: list[dict[str, Any]]) -> None:
    missing = [r for r in rows if r["status"] == "missing"]
    present = [r for r in rows if r["status"] != "missing"]

    print(f"\n  {profile.title} — {len(present)}/{len(rows)} takes recorded\n")
    print(f"  {'take':<22}{'framing':<9}{'target':>8}{'actual':>9}{'trim':>8}  note")
    print(f"  {'-' * 68}")
    for row in rows:
        if row["status"] == "missing":
            print(f"  {row['id']:<22}{row['presenter']:<9}"
                  f"{_clock(row['estimate']):>8}{'—':>9}{'—':>8}  not recorded")
            continue
        trimmed = row["raw"] - row["seconds"]
        note = ""
        if row["status"] == "audio-only":
            note = f"audio only, but framing is '{row['presenter']}'"
        elif row["seconds"] > row["estimate"] * 1.8:
            note = "much longer than planned — worth another take"
        elif row["seconds"] < row["estimate"] * 0.5:
            note = "much shorter than planned — did it record fully?"
        print(f"  {row['id']:<22}{row['presenter']:<9}"
              f"{_clock(row['estimate']):>8}{_clock(row['seconds']):>9}"
              f"{trimmed:>7.1f}s  {note}")

    total = sum(r.get("seconds", 0.0) for r in present)
    print(f"  {'-' * 68}")
    print(f"  {'recorded':<22}{'':<9}{_clock(profile.estimate):>8}{_clock(total):>9}")

    if missing:
        print(f"\n  still to record: {', '.join(r['id'] for r in missing)}")
    else:
        print(f"\n  everything is here. "
              f"demoforge present build --project {profile.name}")


# ---------------------------------------------------------------------------
# 3. build
# ---------------------------------------------------------------------------


def slide_module(profile: Profile) -> Any:
    """Import the project's ``slides.py``, if it has one.

    A profile that only cuts between camera and screen recordings does not need
    slides at all, so this is allowed to come back empty rather than failing.
    """
    path = profile.directory / "slides.py"
    if not path.exists():
        return None
    import importlib.util

    spec = importlib.util.spec_from_file_location(f"_slides_{profile.name}", path)
    module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def render_visual(profile: Profile, section: Section, seconds: float, out: Path,
                  slides: Any) -> Path | None:
    """The picture behind a section, rendered to exactly ``seconds``."""
    width, height = profile.size

    if section.visual_kind == "none":
        return None

    if section.visual_kind == "screen":
        source = Path(section.screen or "")
        if not source.is_absolute():
            source = profile.directory / source
        if not source.exists():
            raise SystemExit(
                f"section {section.id!r} wants screen recording {source}, "
                "which does not exist. Capture it first, or change the profile."
            )
        return fit_clip(source, out, seconds, width, height)

    # The slide is told where the presenter is going to sit. Without this a
    # full-width layout draws its right-hand column underneath the inset, and
    # the collision only shows up after the composite -- by which point the
    # slide has already been rendered at its take's length.
    meta = {**section.meta, "presenter": section.presenter}

    if slides is None or not hasattr(slides, "render"):
        # No slides.py. A project written in the app describes each slide as
        # a `slidekit` spec on the section instead of as Python, which is
        # enough for a title, a list, a number or a step and is what most
        # sections are. Anything more particular still gets a slides.py.
        spec = section.meta.get("slide")
        if isinstance(spec, dict):
            from demoforge import slidekit
            return slidekit.render({**spec, "presenter": section.presenter},
                                   seconds, out, (width, height))
        raise SystemExit(
            f"section {section.id!r} wants slide {section.visual_name!r}, but "
            f"{profile.directory / 'slides.py'} has no render(name, seconds, out, size) "
            f"and the section has no `meta.slide` spec."
        )
    return slides.render(section.visual_name, seconds, out, (width, height), meta)


def fit_clip(source: Path, out: Path, seconds: float, width: int, height: int) -> Path:
    """Scale a clip into the canvas and make it last exactly ``seconds``.

    Short clips hold their final frame rather than slowing down; long ones are
    cut. Both are stated in the build log, because a screen recording silently
    truncated at 40% is the kind of thing nobody notices until it is published.
    """
    have = duration(source)
    pad = max(0.0, seconds - have)
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(source),
         "-vf",
         f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
         f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=0x0b0f14,"
         f"tpad=stop_mode=clone:stop_duration={pad:.3f},fps={FPS}",
         "-an", "-t", f"{seconds:.3f}",
         "-c:v", "libx264", "-preset", "medium", "-crf", "18",
         "-pix_fmt", "yuv420p", str(out)],
        check=True)
    if have > seconds + 0.25:
        print(f"      note: {source.name} is {have:.1f}s, cut to {seconds:.1f}s")
    return out


def presenter_full(take: Path, out: Path, start: float, seconds: float,
                   width: int, height: int) -> Path:
    """The take, cropped to fill the canvas. Silent -- audio is muxed later."""
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{start:.3f}",
         "-i", str(take), "-t", f"{seconds:.3f}",
         "-vf",
         f"scale={width}:{height}:force_original_aspect_ratio=increase,"
         f"crop={width}:{height},fps={FPS}",
         "-an", "-c:v", "libx264", "-preset", "medium", "-crf", "18",
         "-pix_fmt", "yuv420p", str(out)],
        check=True)
    return out


def presenter_corner(base: Path, take: Path, out: Path, start: float, seconds: float,
                     width: int, height: int, size: int | None = None,
                     margin: int = 56, bias: float = 0.46, zoom: float = 0.66) -> Path:
    """The slide with the presenter inset, reusing the generated path's circle.

    ``compose.head_clip`` already solves the hard part -- fitting a portrait
    phone frame into a circle without slicing the jaw off -- so this trims the
    take to its speech window and hands it over rather than reimplementing it.
    """
    from demoforge.compose import head_clip

    size = size or int(min(width, height) * 0.31)
    window = out.with_suffix(".window.mp4")
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{start:.3f}",
         "-i", str(take), "-t", f"{seconds:.3f}",
         "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
         "-pix_fmt", "yuv420p", str(window)],
        check=True)

    inset = out.with_suffix(".inset.mov")
    head_clip(window, inset, size, bias, zoom)

    x, y = width - size - margin, height - size - margin
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(base), "-i", str(inset),
         "-filter_complex", f"[0:v][1:v]overlay={x}:{y}:shortest=0[v]",
         "-map", "[v]", "-an", "-t", f"{seconds:.3f}",
         "-c:v", "libx264", "-preset", "medium", "-crf", "18",
         "-pix_fmt", "yuv420p", str(out)],
        check=True)
    window.unlink(missing_ok=True)
    inset.unlink(missing_ok=True)
    return out


def build(profile: Profile, out: Path | None = None, trim: bool = True,
          only: list[str] | None = None) -> Path:
    """Render every section to its take's length and concatenate."""
    width, height = profile.size
    work = OUT / f"present-{profile.name}"
    work.mkdir(parents=True, exist_ok=True)
    out = out or OUT / f"{profile.name}-presented.mp4"

    rows = {row["id"]: row for row in intake(profile, trim=trim)}
    missing = [i for i, row in rows.items() if row["status"] == "missing"]
    if missing and not only:
        raise SystemExit(
            f"{len(missing)} take(s) not recorded: {', '.join(missing)}\n"
            f"Run `demoforge present intake --project {profile.name}` for the full list."
        )

    slides = slide_module(profile)
    pieces: list[Path] = []
    timeline: list[dict[str, Any]] = []
    at = 0.0

    for section in profile.sections:
        row = rows[section.id]
        if row["status"] == "missing":
            continue
        if only and section.id not in only:
            # Still needs to exist for the concat, so reuse the previous render.
            existing = work / f"{section.id}.mp4"
            if existing.exists():
                pieces.append(existing)
                at += duration(existing)
                continue

        take = Path(row["path"])
        seconds = float(row["seconds"])
        start = float(row["start"])
        piece = work / f"{section.id}.mp4"
        print(f"  {section.id}  {seconds:5.1f}s  {section.presenter}")

        if section.presenter == "full":
            if not row["video"]:
                raise SystemExit(
                    f"section {section.id!r} is framed 'full' but {take.name} has "
                    "no video track."
                )
            presenter_full(take, piece, start, seconds, width, height)
        else:
            base = render_visual(
                profile, section, seconds, work / f"{section.id}.slide.mp4", slides)
            if base is None:
                raise SystemExit(f"section {section.id!r} produced no picture")
            if section.presenter == "corner" and row["video"]:
                presenter_corner(base, take, piece, start, seconds, width, height)
            else:
                shutil.copyfile(base, piece)

        # The take's own audio, cut to exactly the length of the picture that was
        # actually rendered -- padded with silence if it is short, trimmed if long.
        #
        # Not `seconds`. The picture is quantised to whole frames and the sound is
        # not, so each section can carry up to a frame more of one than the other,
        # and the two concats below then drift apart one section at a time. On a
        # fourteen-section cut the voice was running 0.4s ahead of the face by the
        # closer, and every slide change landed late against the words it belongs
        # to. Matching each section's sound to its own picture stops the drift
        # accumulating, whatever the takes were cut with.
        #
        # Counted in samples, not seconds. A time limit (`-t`) is measured from
        # the audio stream's first timestamp, and a take whose audio starts a
        # frame after its picture then comes out a frame short no matter how
        # much padding is asked for -- which is what the first version of this
        # fix did. Rebasing the sound to zero and trimming to a sample count
        # makes the length exact whatever the take looks like inside.
        audio = work / f"{section.id}.wav"
        picture = duration(piece)
        samples = round(picture * 48000)
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{start:.3f}",
             "-i", str(take), "-vn", "-ac", "2",
             "-af", f"aresample=48000,asetpts=PTS-STARTPTS,apad,atrim=end_sample={samples}",
             "-c:a", "pcm_s16le", str(audio)],
            check=True)

        pieces.append(piece)
        timeline.append({
            "id": section.id, "start": round(at, 2), "seconds": round(seconds, 2),
            "presenter": section.presenter, "say": section.say,
        })
        at += seconds

    _concat(profile, pieces, work, out)

    manifest = out.with_suffix(".timeline.json")
    manifest.write_text(json.dumps(timeline, indent=2), encoding="utf-8")
    print(f"\n  {out}  {duration(out):.1f}s")
    print(f"  {manifest}")
    _print_timecodes(timeline)
    return out


def _concat(profile: Profile, pieces: list[Path], work: Path, out: Path) -> None:
    """Join the sections, video and audio together.

    Re-encoding rather than stream-copying: the pieces come from three
    different filter chains and a concat demuxer on mismatched streams produces
    a file that plays for four seconds and then stops, which is a bad way to
    find out.
    """
    listing = work / "concat.txt"
    listing.write_text(
        "".join(f"file '{p.resolve().as_posix()}'\n" for p in pieces), encoding="utf-8")

    audio_listing = work / "concat-audio.txt"
    audio_listing.write_text(
        "".join(f"file '{(work / (p.stem + '.wav')).resolve().as_posix()}'\n"
                for p in pieces),
        encoding="utf-8")

    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error",
         "-f", "concat", "-safe", "0", "-i", str(listing),
         "-f", "concat", "-safe", "0", "-i", str(audio_listing),
         "-map", "0:v", "-map", "1:a",
         "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-b:a", "192k", "-shortest",
         "-movflags", "+faststart", str(out)],
        check=True)


def _print_timecodes(timeline: list[dict[str, Any]]) -> None:
    print("\n  timecodes")
    for entry in timeline:
        minutes, seconds = divmod(int(entry["start"]), 60)
        words = entry["say"].split()
        opening = " ".join(words[:9]) + ("…" if len(words) > 9 else "")
        print(f"    {minutes}:{seconds:02d}  {entry['id']:<20} {opening}")


# ---------------------------------------------------------------------------
# cli
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="demoforge present", description=__doc__)
    sub = ap.add_subparsers(dest="action", required=True)

    for action in ("script", "intake", "build"):
        p = sub.add_parser(action)
        p.add_argument("--project", required=True)
        p.add_argument("--no-trim", action="store_true",
                       help="keep the silence at the ends of every take")
        if action == "build":
            p.add_argument("--out", default=None)
            p.add_argument("--only", nargs="*", default=None,
                           help="re-render only these sections, reusing the rest")

    args = ap.parse_args(argv)
    profile = load(args.project)

    if args.action == "script":
        write_script(profile)
    elif args.action == "intake":
        report(profile, intake(profile, trim=not args.no_trim))
    else:
        build(profile,
              Path(args.out) if args.out else None,
              trim=not args.no_trim,
              only=args.only)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
