"""Reel mode: one long vertical take in, a short vertical film out.

The fourth path. `edit` assumes a deck and a folder of takes and produces
something you watch on purpose. This assumes one continuous recording, made on
a phone, and produces something that has to survive a thumb.

Three things make it a different mode rather than a 9:16 flag on `edit`:

**The shot list is derived from the footage, not chosen.** `gaze` measures
where the presenter is looking, and a section only goes full frame where the
eyes are actually on the lens. Everywhere else gets a card or a cutaway. That
is backwards from how video is normally made and it is the right way round
here, because the footage already exists and the shots do not.

**Pacing is a parameter of the film, not of the delivery.** A reel runs
slightly fast. Not enough to hear, enough to feel.

**The frame is shared with an interface.** A fifth of the bottom, a strip
across the top and a column down the right belong to the platform. Everything
here is laid out around that, which is why `reelkit` exists instead of
`slidekit`.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from demoforge import captions as caps
from demoforge import gaze as gazemod
from demoforge import reelkit
from demoforge.config import OUT, PROJECTS
from demoforge.edit import lift, subtract, tighten
from demoforge.media import (clean_voice, drive, duration, level_bed,  # noqa: F401
                             local_track, loudness, master, size, sourced_track)
from demoforge.transcribe import (Transcript, Word, correct, destutter,
                                  repair, transcribe)

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

SIZE = (1080, 1920)

# Where the eye line sits in the finished frame. The upper third, which is
# the convention for a reason: it leaves headroom without leaving a gap.
EYE_LINE = 0.38


@dataclass
class Profile:
    name: str
    directory: Path
    title: str = ""
    source: str = ""
    speed: float = 1.1
    whisper_model: str = "medium.en"
    corrections: dict[str, str] = field(default_factory=dict)
    captions: bool = True
    caption_words: int = 3
    music: bool = True
    music_query: list[str] = field(default_factory=lambda: ["upbeat energetic tech"])
    # A folder of tracks you already own, searched before anything is fetched.
    # Local beats stock: it is instant, it cannot be rate-limited, and it is
    # music somebody already decided they liked.
    music_dir: str = ""
    music_file: str = ""
    music_offset: float = 0.0
    music_under: float = -13.0
    music_ratio: float = 4.0
    accent: str = "lime"
    music_style: str = "lofi"
    presenter_zoom: float = 1.14
    mirror: bool = False
    # A reel breathes far less than a film. These are the film's numbers
    # roughly halved: a pause you would keep in a two-minute explainer is dead
    # air in a fifteen-second one.
    pause_cut: float = 0.42
    pause_keep: float = 0.14
    head_pad: float = 0.07
    tail_pad: float = 0.13
    # A look-away longer than this inside a full-frame shot cuts away to the
    # section's visual instead. Below it, the glance is shorter than the cut
    # would be and cutting looks worse than the glance.
    look_away: float = 0.7
    min_shot: float = 0.9
    # How much of a detected pause survives. Not zero: speech butted straight
    # together clips the consonant at each side of the join and sounds glued.
    breath: float = 0.07
    loudness: float = -12.0
    # Windows the recogniser got wrong that no heuristic flags.
    repairs: list[list[float]] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def size(self) -> tuple[int, int]:
        return SIZE

    @property
    def video(self) -> Path:
        path = Path(self.source).expanduser()
        return path if path.is_absolute() else (self.directory / path)

    @property
    def stem(self) -> str:
        return self.video.stem

    @property
    def transcripts(self) -> Path:
        return self.directory / "transcripts"

    @property
    def gaze_path(self) -> Path:
        return self.directory / "gaze.json"

    @property
    def plan_path(self) -> Path:
        return self.directory / "plan.json"

    @property
    def home(self) -> Path:
        """Everything this reel produces, under one folder named after it."""
        return OUT / self.name

    @property
    def work(self) -> Path:
        return self.home / "work"

    @property
    def broll(self) -> Path:
        return self.directory / "broll"

    @property
    def accent_hex(self) -> str:
        return "#%02X%02X%02X" % reelkit.Spec(accent=self.accent).colour


def load(project: str) -> Profile:
    directory = PROJECTS / project
    path = directory / "reel.json"
    if not path.exists():
        raise SystemExit(f"no reel profile at {path}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    known = {f for f in Profile.__dataclass_fields__
             if f not in ("name", "directory", "raw")}
    return Profile(name=project, directory=directory, raw=raw,
                   **{k: v for k, v in raw.items() if k in known})


def _repaired(profile: Profile, rebuild: bool = False) -> Transcript:
    """The transcript with the profile's named windows re-heard.

    Written to its own file and always derived from the pristine one. Saving a
    repair back over the original makes it permanent and unreviewable: a window
    chosen a shade too wide swallows a neighbouring word, and the corrected
    window cannot put it back because the word is no longer there to keep.
    That happened to "changes," and cost a full re-transcription to undo.
    """
    pristine = profile.transcripts / f"{profile.stem}.json"
    out = profile.transcripts / f"{profile.stem}.repaired.json"
    spans = [(float(a), float(b)) for a, b in profile.repairs]
    stamp = json.dumps(spans)

    if not spans:
        return Transcript.load(pristine)
    if not rebuild and out.exists():
        saved = json.loads(out.read_text(encoding="utf-8"))
        if saved.get("fingerprint") == stamp:
            return Transcript.load(out)

    script = Transcript.load(pristine)
    script.words = repair(script.words, profile.video, spans,
                          profile.whisper_model, scratch=pristine.parent)
    script.text = " ".join(w.text.strip() for w in script.words).strip()
    script.save(out, stamp)
    return script


def words_of(profile: Profile, clean: bool = True) -> list[Word]:
    words = correct(_repaired(profile).words, profile.corrections)
    return destutter(words)[0] if clean else words


# ---------------------------------------------------------------------------
# 1. ingest
# ---------------------------------------------------------------------------


def ingest(profile: Profile, cache: bool = True) -> None:
    profile.transcripts.mkdir(parents=True, exist_ok=True)
    print("\n== transcribe ==")
    path = profile.transcripts / f"{profile.stem}.json"
    transcribe(profile.video, path, profile.whisper_model, cache=cache)
    _repaired(profile, rebuild=True)

    print("\n== gaze ==")
    if cache and profile.gaze_path.exists():
        samples = gazemod.load(profile.gaze_path)
        print("  cached")
    else:
        samples = gazemod.scan(profile.video, 5.0, profile.gaze_path)
    gazemod.report(samples, gazemod.windows(samples), duration(profile.video))


# ---------------------------------------------------------------------------
# 2. plan
# ---------------------------------------------------------------------------


def settle(profile: Profile, cut: dict[str, Any]) -> dict[str, Any]:
    """Snap the hand-written cut to words, tighten it, and check the eye line.

    The gaze check is advisory and loud rather than fatal. A section asking for
    a full-frame shot over footage where the eyes are elsewhere is a mistake
    worth being told about, but the person writing the cut can see the frame
    and this cannot, so it does not get a veto.
    """
    words = words_of(profile)
    samples = gazemod.load(profile.gaze_path) if profile.gaze_path.exists() else []
    spans = gazemod.windows(samples)
    # Silence to remove: what the waveform says is quiet, minus what the
    # transcript says is a word.
    #
    # Both halves are needed. Without the detector the padded word timings hide
    # every pause; without the protection the detector eats word onsets, because
    # the recogniser starts a word a little before the sound does and cutting
    # to the energy takes the front off it. "This is the only…" became "is the
    # only…" — correct by every measure except listening to it.
    # Protect the front of each word for as long as saying it plausibly takes,
    # and expose the rest. The recogniser pads a word's end into the pause that
    # follows it, so protecting the whole span protects the pause too — which
    # is how a cut measures tight against the transcript and still breathes.
    # The detector decides whether that exposed tail is actually quiet; where
    # the word really does run long, it is not, and nothing is cut.
    protected = []
    for w in words:
        spoken = 0.075 * len(w.key) + 0.10
        # Never past the midpoint. Word membership downstream is decided by
        # midpoint, so cutting through one does not shorten the word -- it
        # deletes it, from the audio and the captions both. That is how "Put
        # an AGENTS.md" lost its "Put".
        middle = (w.start + w.end) / 2
        protected.append((w.start - 0.03,
                          min(w.end + 0.03,
                              max(w.start + spoken, middle + 0.06))))
    quiet = subtract(
        [(a + profile.breath, b - profile.breath)
         for a, b in silences(profile) if b - a > profile.breath * 2],
        protected, floor=0.08)
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    # A word belongs to exactly one section, and which one is decided for all
    # sections before any of them is built.
    #
    # Spans are widened before being snapped to words, so two sections meeting
    # inside that window both want the word on the boundary. Left alone that is
    # heard as a stutter ("Real | Real engineers") while looking correct in
    # each section on its own. Resolved first-come, the *second* section loses
    # its opening word instead, which is worse and quieter.
    #
    # So: containment first, and only then the strays. A boundary authored
    # between two words — which is how they are authored — never reaches the
    # second pass at all.
    sections = list(cut.get("sections", []))
    owner: dict[int, int] = {}
    for pass_slack in (0.0, 0.25):
        for number, section in enumerate(sections):
            start, end = float(section["start"]), float(section["end"])
            for i, w in enumerate(words):
                if i in owner:
                    continue
                middle = (w.start + w.end) / 2
                if start - pass_slack <= middle <= end + pass_slack:
                    owner[i] = number

    for order, section in enumerate(sections, start=1):
        number = order - 1
        drops = [(float(a), float(b)) for a, b in section.get("drops", [])]
        start, end = float(section["start"]), float(section["end"])
        inside = [w for i, w in enumerate(words)
                  if owner.get(i) == number
                  and not any(a <= (w.start + w.end) / 2 <= b for a, b in drops)]
        if not inside:
            print(f"  ! {section.get('id')} has no words in {start}-{end}")
            continue
        keeps = subtract(
            tighten(inside, pause_cut=profile.pause_cut,
                    pause_keep=profile.pause_keep, head_pad=profile.head_pad,
                    tail_pad=profile.tail_pad), drops)
        # Then the pauses the transcript could not see. A low floor here: the
        # fragments between two detected pauses are words, not slivers.
        keeps = subtract(keeps, quiet, floor=0.06)
        if not keeps:
            continue

        identifier = section.get("id") or f"{order:02d}"
        while identifier in seen:
            identifier += "_b"
        seen.add(identifier)

        shot = section.get("shot", "card")
        card = dict(section.get("card") or {})
        banner = section.get("banner", "")
        broll = section.get("broll", "")

        # A face shot is only a face shot while the eyes are on the lens. The
        # rest of it becomes whatever the section was going to show anyway.
        runs = [(keeps, True)]
        if shot in ("full", "auto"):
            pieces = split_on_gaze(keeps, spans, profile.look_away,
                                   profile.min_shot)
            if len(pieces) > 1:
                runs = [([(a, b)], on) for a, b, on in pieces]

        for order2, (run_keeps, on_camera) in enumerate(runs):
            seconds = sum(b - a for a, b in run_keeps)
            if seconds < 0.35:
                continue
            name = identifier if len(runs) == 1 else                 f"{identifier}{chr(ord('a') + order2)}"
            if shot in ("full", "auto"):
                piece_shot = "full" if on_camera else (
                    "broll" if broll else "card")
            else:
                piece_shot = shot
            piece_card = card
            if piece_shot == "card" and not piece_card:
                # Nothing was authored for the look-away, so the line that
                # would have been a banner becomes the card instead. It is the
                # same words either way; this just puts them where there is
                # room for them.
                piece_card = {"layout": "punch",
                              "headline": banner or section.get("say", "")}
            out.append({
                "id": name,
                "start": round(run_keeps[0][0], 3),
                "end": round(run_keeps[-1][1], 3),
                "keeps": [[round(a, 3), round(b, 3)] for a, b in run_keeps],
                "drops": [[round(a, 3), round(b, 3)] for a, b in drops],
                "seconds": round(seconds / profile.speed, 3),
                "shot": piece_shot,
                "eyes": round(_coverage(spans, run_keeps), 3),
                # Banners are gone from face shots: the burned captions already
                # carry the words, and two sets of bold text on one frame is
                # one set too many.
                "banner": "" if piece_shot == "full" else banner,
                "zoom": section.get("zoom", ""),
                # Where the presenter was during this run, so the shot can be
                # framed on them rather than on a constant.
                "face": [round(v, 4) for v in gazemod.framing(
                    samples, run_keeps[0][0], run_keeps[-1][1],
                    mirror=profile.mirror)],
                "card": piece_card,
                "broll": broll,
                "fit": section.get("fit", "panel"),
                "say": " ".join(
                    w.text.strip() for w in inside
                    if any(a <= (w.start + w.end) / 2 <= b for a, b in run_keeps)
                ).strip(),
            })

    if not out:
        raise SystemExit("the cut has no usable sections")
    return {"title": profile.title or profile.name, "sections": out}


def silences(profile: "Profile", threshold: str = "-30dB",
             shortest: float = 0.18, cache: bool = True) -> list[tuple[float, float]]:
    """Every stretch of the source with no speech in it, in source time.

    Word timings cannot find these. The recogniser pads a word's end into the
    pause that follows it, so a real six-hundred-millisecond gap reads as a
    tenth of a second between two words — which is why a cut can measure
    perfectly tight against the transcript and still sound full of holes.

    So the transcript decides *what* to keep and the waveform decides *exactly
    where the speech is*. Measured on the source rather than on the finished
    cut, because caption times are derived from source-time ranges: take the
    silence out afterwards and every caption after the first pause is late.

    -30dB rather than the -38 a silence detector would normally use. A room
    with any tone in it never reaches -38 between words, and the pauses a
    viewer hears as dead air sit well above it.
    """
    out = profile.directory / "silence.json"
    if cache and out.exists():
        return [(a, b) for a, b in json.loads(out.read_text(encoding="utf-8"))]

    log = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(profile.video),
         "-af", f"silencedetect=noise={threshold}:d={shortest}", "-f", "null", "-"],
        capture_output=True, text=True).stderr
    spans: list[tuple[float, float]] = []
    for end, span in re.findall(
            r"silence_end: ([\d.]+) \| silence_duration: ([\d.]+)", log):
        end, span = float(end), float(span)
        spans.append((round(end - span, 3), round(end, 3)))
    out.write_text(json.dumps(spans), encoding="utf-8")
    print(f"  {len(spans)} silences, {sum(b - a for a, b in spans):.0f}s of "
          f"{duration(profile.video):.0f}s")
    return spans


def split_on_gaze(keeps, spans, look_away: float, min_shot: float):
    """Break a span into runs of on-camera and off-camera.

    The rule the presenter actually asked for: the moment the eyes leave the
    lens, cut away. Implemented as a partition rather than a score, because a
    section that is 80% on camera can still contain three seconds in the middle
    of someone reading, and a single verdict for the whole section either shows
    that or throws away the good 80% around it.

    Two guards stop it turning into a strobe. A look-away shorter than
    `look_away` is ignored, because the cut would last longer than the glance.
    And any run shorter than `min_shot` is folded into its neighbour, because a
    half-second shot reads as a mistake however well motivated it is.
    """
    marks: list[tuple[float, float, bool]] = []
    for start, end in keeps:
        edges = {start, end}
        for a, b in spans:
            if b > start and a < end:
                edges.add(max(a, start))
                edges.add(min(b, end))
        ordered = sorted(edges)
        for a, b in zip(ordered, ordered[1:]):
            if b - a <= 0.001:
                continue
            middle = (a + b) / 2
            on = any(x <= middle <= y for x, y in spans)
            marks.append((a, b, on))

    # Ignore the short glances, then merge neighbours that now agree.
    kept: list[list] = []
    for a, b, on in marks:
        if not on and b - a < look_away and kept:
            on = kept[-1][2]
        if kept and kept[-1][2] == on and abs(kept[-1][1] - a) < 0.001:
            kept[-1][1] = b
        else:
            kept.append([a, b, on])

    # Fold away anything too short to be a shot.
    folded: list[list] = []
    for run in kept:
        if folded and run[1] - run[0] < min_shot:
            folded[-1][1] = run[1]
        else:
            folded.append(run)
    if len(folded) > 1 and folded[0][1] - folded[0][0] < min_shot:
        folded[1][0] = folded[0][0]
        folded.pop(0)
    return [(a, b, on) for a, b, on in folded]


def _coverage(spans, keeps) -> float:
    total = sum(b - a for a, b in keeps)
    if not total or not spans:
        return 0.0
    inside = sum(max(0.0, min(b, y) - max(a, x))
                 for a, b in keeps for x, y in spans)
    return min(1.0, inside / total)


def plan(profile: Profile, source: Path | None = None) -> dict[str, Any]:
    source = source or profile.directory / "cut.json"
    result = settle(profile, json.loads(source.read_text(encoding="utf-8")))
    profile.plan_path.write_text(json.dumps(result, indent=1), encoding="utf-8")
    total = sum(s["seconds"] for s in result["sections"])
    print(f"\n  {len(result['sections'])} sections, {total:.0f}s "
          f"({total // 60:.0f}:{total % 60:04.1f}) at {profile.speed}x")
    at = 0.0
    for s in result["sections"]:
        label = s["card"].get("headline", "") or s["banner"] or s["say"][:38]
        print(f"    {int(at) // 60}:{int(at) % 60:02d}  {s['id']:<16} "
              f"{s['seconds']:5.1f}s  {s['shot']:<6} eyes {s['eyes']:4.0%}  "
              f"{reelkit.strip(label)[:44]}")
        at += s["seconds"]
    print(f"\n  {profile.plan_path}")
    return result


# ---------------------------------------------------------------------------
# 3. build
# ---------------------------------------------------------------------------


def banner(profile: Profile, text: str, seconds: float, out: Path) -> Path:
    """A caption-sized headline laid over the presenter, not a card.

    Full-frame sections still need something on screen for the thumb to read
    in the first second. A band across the upper third does that without
    hiding the face, which is the thing that earns the second second.
    """
    from PIL import Image, ImageDraw
    width, height = profile.size
    unit = height / 1920
    spec = reelkit.Spec(accent=profile.accent)
    fnt, lines = reelkit.fit(text, int(width * 0.86), 3, int(96 * unit),
                            int(54 * unit))
    step = int(fnt.size * 1.1)

    layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    top = int(height * 0.135)
    # The box is measured from the font's own ascent and descent, not from the
    # line step. A box sized to the step cuts the tails off g, y and p — which
    # turns "only coding" into "onlv codina" and is invisible until somebody
    # reads the frame rather than looking at it.
    ascent, descent = fnt.getmetrics()
    placed = []
    for i, line in enumerate(lines):
        run = sum(fnt.getlength(c) for c, _ in line)
        placed.append(((width - run) / 2, top + i * step, run, line))

    # Every box first, then every glyph. A box tall enough to clear the
    # descenders necessarily overlaps the line below it, so drawing each
    # box-then-text pair in turn paints the next box straight over the tails
    # of the previous line -- which is how "only coding" ends up reading
    # "onlv codina" in the finished frame.
    for x, y, run, _ in placed:
        d.rounded_rectangle([x - int(26 * unit), y - int(14 * unit),
                             x + run + int(26 * unit),
                             y + ascent + descent + int(8 * unit)],
                            radius=int(16 * unit), fill=(8, 9, 12, 205))
    for x, y, _, line in placed:
        for chunk, hot in line:
            d.text((x, y), chunk, font=fnt,
                   fill=(*spec.colour, 255) if hot else (255, 255, 255, 255))
            x += fnt.getlength(chunk)
    out.parent.mkdir(parents=True, exist_ok=True)
    layer.save(out)
    return out


def entry(size: tuple[int, int], seconds: float, zoom: str = "",
          settle_frames: int = 6, from_scale: float = 1.07) -> str:
    """A snap-in on every cut, and optionally a drift across the whole shot.

    Two separate jobs sharing one filter. The snap is 6 frames of scale
    settling to 1.0 and it exists to punctuate the cut -- at reel pace a hard
    cut with no movement reads as a still frame, and the thumb reads a still
    frame as the end. The drift is per section and is direction, not
    punctuation: `in` tightens on a line as it lands, `out` opens up.

    Expressed against `on` (the frame counter) rather than `t`, because
    zoompan's `t` is not reliable when it is fed a filtered stream.
    """
    width, height = size
    frames = max(1, int(seconds * 30))
    snap = (f"if(lt(on,{settle_frames}),"
            f"{from_scale}-{from_scale - 1:.4f}*on/{settle_frames},1)")
    if zoom == "in":
        drift = f"+0.10*on/{frames}"
    elif zoom == "out":
        drift = f"+0.10*(1-on/{frames})"
    elif zoom == "punch":
        # Held wide, then a single step in a third of the way through. For a
        # line that turns on one word.
        drift = f"+if(gt(on,{int(frames * 0.34)}),0.09,0)"
    else:
        drift = ""
    return (f"zoompan=z='({snap}){drift}':d=1:"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
            f"s={width}x{height}:fps=30")


def shot_full(profile: Profile, clip: Path, out: Path, text: str,
              work: Path, zoom: str = "",
              face: tuple[float, float] = (0.5, 0.4)) -> Path:
    """The presenter, filling the frame, with an optional headline over them."""
    width, height = profile.size
    # A reel wants the face bigger than a phone frames it, and in the middle.
    #
    # `face` is where the presenter actually was during this span, measured
    # rather than assumed -- the previous fixed bias framed whoever happened to
    # be sitting where the constant said. The crop is placed so the face centre
    # lands on the middle of the frame horizontally and the eye line lands on
    # `EYE_LINE` vertically, then clamped so it never runs off the source.
    zoom = profile.presenter_zoom
    inner_w, inner_h = int(width * zoom) // 2 * 2, int(height * zoom) // 2 * 2
    fx, ey = face
    x_off = max(0, min(inner_w - width, int(fx * inner_w - width / 2)))
    y_off = max(0, min(inner_h - height, int(ey * inner_h - height * EYE_LINE)))
    chain = (f"[0:v]scale={inner_w}:{inner_h}:force_original_aspect_ratio="
             f"increase:flags=lanczos,crop={inner_w}:{inner_h},"
             f"crop={width}:{height}:{x_off}:{y_off},"
             f"eq=contrast=1.07:saturation=1.08,"
             f"{entry(profile.size, duration(clip), zoom)},setsar=1[v]")
    inputs = ["-i", str(clip)]
    if text:
        overlay = banner(profile, text, duration(clip),
                         work / f"{out.stem}.banner.png")
        inputs += ["-i", str(overlay)]
        chain = chain.replace("[v]", "[s];[s][1:v]overlay=0:0[v]")
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", *inputs,
         "-filter_complex", chain, "-map", "[v]", "-map", "0:a",
         "-c:v", "libx264", "-preset", "medium", "-crf", "18",
         "-pix_fmt", "yuv420p", "-c:a", "pcm_s16le",
         "-t", f"{duration(clip):.3f}", str(out)],
        check=True)
    return out


def shot_card(profile: Profile, clip: Path, out: Path, card: dict[str, Any],
              work: Path) -> Path:
    """A rendered card carrying the picture, the take carrying the sound."""
    seconds = duration(clip)
    card_video = work / f"{out.stem}.card.mp4"
    spec = reelkit.Spec.parse({**card, "accent": card.get("accent",
                                                          profile.accent)})
    reelkit.render(spec, seconds, card_video, profile.size)
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(card_video),
         "-i", str(clip), "-filter_complex",
         f"[0:v]{entry(profile.size, seconds)},setsar=1[v]",
         "-map", "[v]", "-map", "1:a",
         "-c:v", "libx264", "-preset", "medium", "-crf", "18",
         "-pix_fmt", "yuv420p", "-c:a", "pcm_s16le",
         "-t", f"{seconds:.3f}", str(out)],
        check=True)
    return out


def ground_png(profile: Profile, work: Path) -> Path:
    path = work / "_ground.png"
    if not path.exists():
        work.mkdir(parents=True, exist_ok=True)
        reelkit.ground(profile.size, profile.accent).save(path)
    return path


def _is_tall(source: Path, canvas_aspect: float) -> bool:
    src_w, src_h = size(source)
    return src_w / src_h <= canvas_aspect * 1.05


def shot_broll(profile: Profile, clip: Path, out: Path, source: Path,
               text: str, work: Path, fit: str = "panel") -> Path:
    """A cutaway under the take's audio.

    Two ways to place it, and the choice is about what the footage *is*.

    `cover` fills the frame and is right for anything shot vertically or
    anything where the edges do not matter.

    `panel` is for a screen recording, which is landscape and full of small
    text. Cropping a 16:9 editor to 9:16 throws away two thirds of the line
    and magnifies what is left past the point of legibility. Sitting it whole
    in the middle of the reel's own background keeps every line readable and
    reads as a deliberate device rather than a mistake.

    Either way it moves. A still cutaway inside a fast cut reads as a freeze;
    almost any drift reads as footage.
    """
    width, height = profile.size
    seconds = duration(clip)
    frames = max(1, int(seconds * 30))
    inputs = ["-i", str(source), "-i", str(clip)]

    if fit == "panel" and _is_tall(source, width / height):
        # A cutaway that is already at least as tall as the canvas has nothing
        # to gain from the panel treatment -- panelling it letterboxes footage
        # that would have filled the frame. `broll` generates vertical now, so
        # this is the common case rather than the exception, and inferring it
        # from the file beats making every profile say so.
        fit = "cover"

    if fit == "panel":
        inputs = ["-loop", "1", "-i", str(ground_png(profile, work))] + inputs
        # Measured, not assumed. A screen grab is cropped to its content
        # before it gets here, so it is whatever shape the content was --
        # forcing it back to 16:9 re-introduces exactly the crop the panel
        # treatment exists to avoid.
        src_w, src_h = size(source)
        # Time-scaled to the section rather than looped or truncated. A
        # terminal replay has a payoff at the end -- the plan, the list of
        # worktrees -- and a cutaway that stops two thirds of the way through
        # shows the setup and never the point.
        src_seconds = duration(source)
        rate = max(0.2, min(5.0, src_seconds / max(0.1, seconds)))
        panel_w = int(width * 0.94) // 2 * 2
        panel_h = int(panel_w * src_h / src_w) // 2 * 2
        lift_y = int(height * 0.03)
        accent = "%02X%02X%02X" % reelkit.Spec(accent=profile.accent).colour
        chain = (
            f"[0:v]scale={width}:{height},fps=30,setsar=1[bg];"
            f"[1:v]setpts=PTS/{rate:.4f},fps=30,"
            f"scale={panel_w}:{panel_h}:flags=lanczos,"
            f"eq=contrast=1.04:saturation=1.03,"
            f"zoompan=z='min(1.05,1+0.05*on/{frames})':d=1:"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
            f"s={panel_w}x{panel_h},setsar=1[cap];"
            f"[bg][cap]overlay=(W-w)/2:(H-h)/2-{lift_y}[o];"
            # A hairline in the accent along the top of the panel. It is what
            # makes the capture look mounted rather than pasted.
            f"[o]drawbox=x=(iw-{panel_w})/2:y=(ih-{panel_h})/2-{lift_y}-5:"
            f"w={panel_w}:h=5:color=0x{accent}@0.95:t=fill,"
            f"{entry(profile.size, seconds)}")
        take_index = 2
    else:
        inputs = ["-stream_loop", "-1"] + inputs
        chain = (f"[1:v]scale={width}:{height}:force_original_aspect_ratio="
                 f"increase:flags=lanczos,crop={width}:{height},fps=30,"
                 f"zoompan=z='min(1.04,1+0.04*on/{frames})':d=1:"
                 f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={width}x{height},"
                 f"eq=contrast=1.05:saturation=1.02,setsar=1")
        take_index = 1

    if text:
        overlay = banner(profile, text, seconds, work / f"{out.stem}.banner.png")
        inputs += ["-i", str(overlay)]
        chain += f"[s];[s][{take_index + 1}:v]overlay=0:0[v]"
    else:
        chain += "[v]"

    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", *inputs,
         # The take is the input the voice comes from, and its index moves
         # depending on whether a background was prepended. Getting this wrong
         # scores the section with the b-roll's own audio, which is silence.
         "-filter_complex", chain, "-map", "[v]", "-map", f"{take_index}:a",
         "-c:v", "libx264", "-preset", "medium", "-crf", "18",
         "-pix_fmt", "yuv420p", "-c:a", "pcm_s16le",
         "-t", f"{seconds:.3f}", str(out)],
        check=True)
    return out


def cover(profile: Profile, at: float, lines: list[str], out: Path,
          source: Path | None = None, size: tuple[int, int] | None = None) -> Path:
    """A cover frame: one still from the film, with the hook set across it.

    Pulled from the finished cut rather than the raw recording, so the crop,
    the mirror and the grade are the ones the viewer will see a second later.
    A cover that does not match its own first frame reads as a different video.

    The text sits in the caption band, which is where the eye already goes on
    this platform -- and where the film's own captions will appear, so the
    cover teaches the viewer where to look before the video starts.
    """
    from PIL import Image, ImageDraw

    width, height = size or profile.size
    # The master, not the delivered file: that one already has captions burned
    # into exactly the band this text goes in, and they show through the scrim.
    master = profile.work / "master.mp4"
    source = source or (master if master.exists()
                        else profile.home / f"{profile.name}-reel.mp4")
    still = out.with_suffix(".frame.png")
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{at:.2f}",
         "-i", str(source), "-frames:v", "1", str(still)],
        check=True)

    img = Image.open(still).convert("RGB").resize((width, height), Image.LANCZOS)
    unit = height / 1920
    spec = reelkit.Spec(accent=profile.accent)

    # A scrim under the text rather than a box around it. On a still there is
    # room to do it properly, and a gradient keeps the face lit while giving
    # the words something solid to sit on.
    band_top = int(height * (1 - reelkit.SAFE_BOTTOM) - 120 * unit)
    scrim = Image.new("L", (1, height), 0)
    for y in range(height):
        if y < band_top:
            value = 0
        else:
            value = int(235 * min(1.0, (y - band_top) / (height * 0.14)))
        scrim.putpixel((0, y), value)
    scrim = scrim.resize((width, height))
    img = Image.composite(Image.new("RGB", (width, height), reelkit.BG), img, scrim)

    d = ImageDraw.Draw(img)
    # The accent hairline the whole film carries.
    d.rectangle([0, 0, width, max(3, int(height // 360))],
                fill=tuple(int(c * 0.9) for c in spec.colour))

    laid = []
    limit = int(width * 0.88)
    for text in lines:
        # One line per line given. A cover is read at thumbnail size in a
        # grid; four short stacked lines read as a paragraph and a paragraph
        # reads as nothing.
        fnt, wrapped = reelkit.fit(text, limit, 1, int(118 * unit), int(44 * unit))
        laid.append((fnt, wrapped))
    total = sum(len(w) * int(f.size * 1.06) for f, w in laid)

    # Centred on the caption band, growing upward.
    caption_mid = int(height * (1 - 0.205) - 50 * unit)
    y = caption_mid - total // 2
    for fnt, wrapped in laid:
        step = int(fnt.size * 1.06)
        for line in wrapped:
            run = sum(fnt.getlength(c) for c, _ in line)
            x = (width - run) / 2
            for chunk, hot in line:
                d.text((x + 3, y + 4), chunk, font=fnt, fill=(0, 0, 0))
                d.text((x, y), chunk, font=fnt,
                       fill=spec.colour if hot else reelkit.FG)
                x += fnt.getlength(chunk)
            y += step

    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, quality=95)
    still.unlink(missing_ok=True)
    print(f"  {out}  {width}x{height}")
    return out


def section_words(profile: Profile, section: dict[str, Any]) -> list[Word]:
    """The section's words on the finished clip's clock, speed included."""
    source = words_of(profile)
    out: list[Word] = []
    elapsed = 0.0
    for start, end in section["keeps"]:
        for word in source:
            middle = (word.start + word.end) / 2
            if start <= middle <= end:
                out.append(Word(
                    text=word.text,
                    start=round((word.start - start + elapsed) / profile.speed, 3),
                    end=round((min(word.end, end) - start + elapsed) / profile.speed, 3),
                    probability=word.probability))
        elapsed += end - start
    return out


def build(profile: Profile, out: Path | None = None,
          only: list[str] | None = None,
          steps: list[str] | None = None) -> Path:
    plan_data = json.loads(profile.plan_path.read_text(encoding="utf-8"))
    sections = plan_data["sections"]
    steps = steps or ["sections", "concat", "captions", "music"]
    work = profile.work
    work.mkdir(parents=True, exist_ok=True)
    out = out or profile.home / f"{profile.name}-reel.mp4"
    width, height = profile.size

    pieces: list[Path] = []
    words: list[Word] = []
    at = 0.0

    for index, section in enumerate(sections, start=1):
        piece = work / f"{section['id']}.mp4"
        keeps = [(float(a), float(b)) for a, b in section["keeps"]]
        wanted = "sections" in steps and (not only or section["id"] in only)

        if wanted or not piece.exists():
            print(f"  {index:2d}/{len(sections)}  {section['id']:<16} "
                  f"{section['seconds']:5.1f}s  {section['shot']}")
            clip = work / f"{section['id']}.take.mp4"
            lift(profile.video, keeps, clip, size=profile.size,
                 punch=section["shot"] == "full", speed=profile.speed,
                 mirror=profile.mirror)

            shot = section["shot"]
            if shot == "full":
                shot_full(profile, clip, piece, "", work,
                          zoom=section.get("zoom", ""),
                          face=tuple(section.get("face", (0.5, 0.4))))
            elif shot == "broll":
                source = profile.broll / str(section["broll"])
                if not source.exists():
                    print(f"      no b-roll at {source}; falling back to a card")
                    shot_card(profile, clip, piece, section["card"], work)
                else:
                    shot_broll(profile, clip, piece, source,
                               section.get("banner", ""), work,
                               fit=section.get("fit", "panel"))
            else:
                shot_card(profile, clip, piece, section["card"], work)
            clip.unlink(missing_ok=True)

        for word in section_words(profile, section):
            words.append(Word(text=word.text, start=word.start + at,
                              end=word.end + at, probability=word.probability))
        pieces.append(piece)
        at += duration(piece)

    master = work / "master.mp4"
    if "concat" in steps or not master.exists():
        print("\n== concat ==")
        _concat(pieces, work, master)

    result = master
    captioned = work / "captioned.mp4"
    if profile.captions and "captions" not in steps and captioned.exists():
        print("  reusing the burned captions")
        result = captioned
    if profile.captions and "captions" in steps:
        print("\n== captions ==")
        ass = work / "captions.ass"
        caps.write(words, ass, width, height, profile.accent_hex,
                   max_words=profile.caption_words, font="Archivo Black",
                   size_frac=0.052, margin_v_frac=0.205, margin_h_frac=0.10)
        caps.srt(words, out.with_suffix(".srt"))
        caps.burn(result, ass, captioned, fontsdir=reelkit.FONTS)
        result = captioned

    print("\n== sound ==")
    result = _sound(profile, result, work, out)

    timeline = [{"id": s["id"], "shot": s["shot"], "say": s["say"]}
                for s in sections]
    out.with_suffix(".timeline.json").write_text(
        json.dumps(timeline, indent=2), encoding="utf-8")
    print(f"\n  {out}  {duration(out):.1f}s")
    return out


def _concat(pieces: list[Path], work: Path, out: Path) -> None:
    listing = work / "concat.txt"
    listing.write_text("".join(f"file '{p.resolve().as_posix()}'\n" for p in pieces),
                       encoding="utf-8")
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
         "-i", str(listing), "-c:v", "libx264", "-preset", "medium", "-crf", "18",
         "-pix_fmt", "yuv420p", "-c:a", "pcm_s16le", str(out)],
        check=True)


def _sound(profile: Profile, video: Path, work: Path, out: Path) -> Path:
    voiced = clean_voice(video, work / "voice.mp4")

    track = next((work / f"bed{ext}" for ext in (".mp3", ".wav")
                  if (work / f"bed{ext}").exists()), work / "bed.mp3")
    if profile.music and not track.exists():
        track = _bed(profile, work) or track

    if not profile.music or not track.exists():
        master(voiced, out, lufs=profile.loudness)
        voiced.unlink(missing_ok=True)
        return out

    from demoforge.music import mix

    # Level the bed before placing it -- no amount of tuning the placement
    # fixes a cue whose own loudness wanders. Slid, not spliced: the offset
    # skips the intro and costs nothing but the length requirement.
    flat = work / "bed-level.wav"
    if not flat.exists():
        level_bed(track, flat, profile.music_offset)
    track = flat

    voice_lufs, bed_lufs = loudness(voiced), loudness(track)
    gain = (-20.0 if None in (voice_lufs, bed_lufs)
            else (voice_lufs + profile.music_under) - bed_lufs)
    print(f"  bed {gain:+.1f}dB for {profile.music_under:+.0f} LU under")
    scored = work / "scored.mp4"
    mix(voiced, track, scored, music_db=gain, duck_db=0.0,
        ratio=profile.music_ratio, release=240)
    master(scored, out, lufs=profile.loudness)
    voiced.unlink(missing_ok=True)
    return out


# Kept under its old name: `short` and `tools` reached in for it before it
# moved to `media`, and a project script may still.
_local = local_track


def _bed(profile: Profile, work: Path) -> Path:
    """A cue long enough to cover the cut: yours first, then Pixabay, then
    a synthesised one. Copied into the work folder so a rebuild reuses it."""
    need = duration(work / "master.mp4") + 3 + profile.music_offset
    track = local_track(profile, need) or sourced_track(profile, need, work)
    if track.parent != work:
        target = work / f"bed{track.suffix}"
        target.write_bytes(track.read_bytes())
        track = target
    return track


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="demoforge reel", description=__doc__)
    sub = ap.add_subparsers(dest="action", required=True)
    cv = sub.add_parser("cover", help="a cover frame with the hook set across it")
    cv.add_argument("--project", required=True)
    cv.add_argument("--at", type=float, default=0.0, help="seconds into the cut")
    cv.add_argument("--line", action="append", default=None,
                    help="a line of the banner; repeat for more. *word* is accented")
    cv.add_argument("--out", default=None)

    for action in ("ingest", "plan", "build", "all"):
        p = sub.add_parser(action)
        p.add_argument("--project", required=True)
        if action == "plan":
            p.add_argument("--from", dest="source", default=None)
        if action in ("build", "all"):
            p.add_argument("--out", default=None)
        if action == "build":
            p.add_argument("--only", nargs="*", default=None)
            p.add_argument("--steps", default=None)
    args = ap.parse_args(argv)
    profile = load(args.project)

    if args.action == "cover":
        cover(profile, args.at,
              args.line or ["Stop *vibe coding*.", "*Do this instead.*"],
              Path(args.out) if args.out
              else profile.home / f"{profile.name}-cover.jpg")
    elif args.action == "ingest":
        ingest(profile)
    elif args.action == "plan":
        plan(profile, Path(args.source) if args.source else None)
    elif args.action == "build":
        build(profile, Path(args.out) if args.out else None, args.only,
              args.steps.split(",") if args.steps else None)
    else:
        ingest(profile)
        plan(profile)
        build(profile, Path(args.out) if args.out else None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
