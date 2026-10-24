"""Editor mode: a deck and a pile of raw recordings in, a finished cut out.

The third path through this repository, and the one that assumes the least.
`build` generates the whole video. `present` takes clean per-section takes and
fits pictures to them. This one takes what people actually have after an
afternoon in front of a webcam: a folder of long files, most of which contain
the same paragraph attempted four times, and a deck that was written before any
of it was said.

The shape of the thing:

    ingest   read the deck, transcribe every source, find the attempts
    plan     choose the keeper of each attempt, and design the slide for it
    build    cut, render, composite, caption, score

`plan` writes `plan.json` and stops. That file is the edit — every decision the
pipeline made, in one document, in seconds and words. Disagreeing with it means
editing a number, not arguing with a model, and `build --only 04_spec`
re-renders the one section you changed.

The division of labour between the model and the code is the load-bearing
choice here, and it is not the obvious one:

    the model decides *which* span, and what the slide says
    the code decides *where exactly* the cuts land

Models are good at "the third attempt is the one where he doesn't trail off"
and unreliable at "and it starts at 41.72 seconds". Filler removal, pause
tightening and cut placement are arithmetic over word timings, so they are
arithmetic over word timings — deterministic, re-runnable, and identical
whether or not there is an API key in the environment.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from demoforge import captions as caps
from demoforge import deck as deckmod
from demoforge import slidekit
from demoforge.config import OUT, PROJECTS, ROOT
from demoforge.transcribe import (ABANDON, Transcript, Word, correct,
                                  destutter, implausible, transcribe)

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

ASPECTS = {"16:9": (1920, 1080), "9:16": (1080, 1920), "1:1": (1080, 1080)}

MODEL = "claude-opus-5"

# Cut placement. All of it is taste expressed as numbers, and all of it is
# overridable per project.
PAUSE_KEEP = 0.30      # a pause longer than PAUSE_CUT is shortened to this
PAUSE_CUT = 0.72       # below this, a pause is part of the delivery
HEAD_PAD = 0.14        # air before the first word of a segment
TAIL_PAD = 0.22        # air after the last — a clipped consonant is very audible
MIN_SEGMENT = 0.45     # a fragment shorter than this is not worth a cut
XFADE = 0.030          # audio fade at each junction, to kill the click


# ---------------------------------------------------------------------------
# profile
# ---------------------------------------------------------------------------


@dataclass
class Profile:
    name: str
    directory: Path
    title: str = ""
    deck: str = ""
    footage: list[str] = field(default_factory=list)
    aspect: str = "16:9"
    accent: str = "blue"
    target_seconds: float = 0.0
    captions: bool = True
    whisper_model: str = "large-v3"
    corrections: dict[str, str] = field(default_factory=dict)
    music: bool = True
    music_under: float = -16.0
    music_ratio: float = 5.0
    music_release: int = 260
    music_style: str = "lofi"
    inset: int = 330
    inset_margin: int = 54
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def size(self) -> tuple[int, int]:
        return ASPECTS.get(self.aspect, ASPECTS["16:9"])

    @property
    def transcripts(self) -> Path:
        return self.directory / "transcripts"

    @property
    def home(self) -> Path:
        """Everything this project produces, under one folder named after it.

        `out/` accumulates: a dozen projects, their intermediates, and the
        scratch of every experiment ever run beside them. Deliverables named
        `<project>-edited.mp4` sort next to each other alphabetically and
        nowhere near the working files that made them, which is the worst of
        both -- so each project gets a folder and keeps its own mess inside it.
        """
        return OUT / self.name

    @property
    def work(self) -> Path:
        return self.home / "work"

    @property
    def plan_path(self) -> Path:
        return self.directory / "plan.json"

    @property
    def deck_path(self) -> Path:
        path = Path(self.deck).expanduser()
        return path if path.is_absolute() else (self.directory / path)

    def sources(self) -> list[Path]:
        """Every recording, in the order they were made.

        Order matters more than it looks: people record a talk front to back,
        so file order is very nearly section order, and it is the fallback the
        planner leans on when nothing else disambiguates.
        """
        found: list[Path] = []
        for entry in self.footage:
            path = Path(entry).expanduser()
            if not path.is_absolute():
                path = self.directory / path
            if path.is_dir():
                found += sorted(p for p in path.iterdir()
                                if p.suffix.lower() in (".mkv", ".mp4", ".mov", ".webm"))
            elif any(ch in entry for ch in "*?["):
                base = path.parent
                found += sorted(base.glob(path.name))
            elif path.exists():
                found.append(path)
            else:
                raise SystemExit(f"footage not found: {path}")
        seen, unique = set(), []
        for path in found:
            if path.resolve() not in seen:
                seen.add(path.resolve())
                unique.append(path)
        return unique


def load(project: str) -> Profile:
    directory = PROJECTS / project
    path = directory / "edit.json"
    if not path.exists():
        raise SystemExit(
            f"no editor profile at {path}\n"
            f"Write one — see docs/editor-mode.md — or run "
            f"`demoforge edit new --project {project} --deck <file.pptx> "
            f"--footage <folder>`.")
    raw = json.loads(path.read_text(encoding="utf-8"))
    known = {f for f in Profile.__dataclass_fields__ if f not in
             ("name", "directory", "raw")}
    return Profile(name=project, directory=directory, raw=raw,
                   **{k: v for k, v in raw.items() if k in known})


def scaffold(project: str, deck: str, footage: list[str], aspect: str,
             seconds: float) -> Path:
    directory = PROJECTS / project
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "edit.json"
    if path.exists():
        raise SystemExit(f"{path} already exists")
    path.write_text(json.dumps({
        "title": project,
        "deck": deck,
        "footage": footage,
        "aspect": aspect,
        "accent": "blue",
        "target_seconds": seconds,
        "captions": True,
        "music": True,
    }, indent=2), encoding="utf-8")
    print(f"  {path}")
    return path


# ---------------------------------------------------------------------------
# 1. ingest
# ---------------------------------------------------------------------------


def words_of(profile: Profile, stem: str, clean: bool = True) -> list[Word]:
    """A recording's words: spelled as the project says, said only once.

    `clean=False` gets the raw list. `INTAKE.md` wants that, because the point
    of the intake report is to show what is actually on the disk — a report
    that has already tidied the false starts away cannot be used to check that
    the tidying was right.
    """
    transcript = Transcript.load(profile.transcripts / f"{stem}.json")
    words = correct(transcript.words, profile.corrections)
    return destutter(words)[0] if clean else words


def sentences(words: list[Word], gap: float = 0.55) -> list[dict[str, Any]]:
    """The transcript as timed sentences, which is the unit a person edits in.

    Split on terminal punctuation *or* a long pause. Whisper's punctuation is
    good and its pauses are better: a restart almost never comes with a full
    stop, and almost always comes with three quarters of a second of nothing.
    """
    out: list[dict[str, Any]] = []
    current: list[Word] = []
    for word in words:
        if current and word.start - current[-1].end > gap:
            out.append(_sentence(current))
            current = []
        current.append(word)
        if re.search(r"[.!?]$", word.text.strip()) and len(current) >= 3:
            out.append(_sentence(current))
            current = []
    if current:
        out.append(_sentence(current))
    return out


def _sentence(words: list[Word]) -> dict[str, Any]:
    return {"start": round(words[0].start, 2), "end": round(words[-1].end, 2),
            "text": " ".join(w.text.strip() for w in words).strip()}


def attempts(words: list[Word], gap: float = 1.6) -> list[dict[str, Any]]:
    """Split one recording into the separate goes at saying the same thing.

    Two signals, and they disagree often enough that both are needed. A long
    silence is where somebody stopped, thought, and started over. A phrase from
    `ABANDON` — "sorry", "let me do that again" — is where they said so out
    loud, usually without pausing first.

    This is advisory. It is shown to the planner as structure and used by the
    keyless fallback as the answer; neither treats it as certain, because a
    presenter who pauses for effect looks exactly like one who lost their place.
    """
    lines = sentences(words)
    if not lines:
        return []
    groups: list[list[dict[str, Any]]] = [[lines[0]]]
    for previous, line in zip(lines, lines[1:]):
        if (line["start"] - previous["end"] > gap
                or ABANDON.search(line["text"])):
            groups.append([])
        groups[-1].append(line)
    return [{
        "index": i,
        "start": round(g[0]["start"], 2),
        "end": round(g[-1]["end"], 2),
        "seconds": round(g[-1]["end"] - g[0]["start"], 2),
        "words": sum(len(s["text"].split()) for s in g),
        "text": " ".join(s["text"] for s in g),
        "abandoned": bool(ABANDON.search(" ".join(s["text"] for s in g))),
    } for i, g in enumerate(groups) if g]


def ingest(profile: Profile, model: str | None = None,
           cache: bool = True) -> dict[str, Any]:
    """Read the deck, transcribe the footage, write the report."""
    profile.transcripts.mkdir(parents=True, exist_ok=True)

    print("\n== deck ==")
    deck = deckmod.read(profile.deck_path)
    (profile.directory / "deck.json").write_text(
        json.dumps(deck, indent=1), encoding="utf-8")
    print(f"  {len(deck['slides'])} slides  {profile.deck_path.name}")
    deckmod.export_png(profile.deck_path, profile.directory / "reference")

    print("\n== transcribe ==")
    sources = profile.sources()
    corpus: list[dict[str, Any]] = []
    for source in sources:
        out = profile.transcripts / f"{source.stem}.json"
        transcript = transcribe(source, out, model or profile.whisper_model,
                                cache=cache)
        corpus.append({
            "source": source.name,
            "stem": source.stem,
            "path": str(source),
            "seconds": round(transcript.duration, 2),
            "attempts": attempts(words_of(profile, source.stem)),
            "unresolved": [
                {"start": round(w.start, 2), "end": round(w.end, 2),
                 "text": w.text}
                for w in transcript.words if implausible(w)],
            "stutters": [
                {"start": round(run[0].start, 2), "end": round(run[-1].end, 2),
                 "text": " ".join(w.text.strip() for w in run)}
                for run in destutter(
                    correct(transcript.words, profile.corrections))[1]],
        })

    report = {"deck": deck, "footage": corpus}
    (profile.directory / "ingest.json").write_text(
        json.dumps(report, indent=1), encoding="utf-8")
    _ingest_report(profile, report)
    return report


def _ingest_report(profile: Profile, report: dict[str, Any]) -> None:
    lines = [f"# {profile.title or profile.name} — intake", ""]
    total = sum(f["seconds"] for f in report["footage"])
    lines += [f"{len(report['footage'])} recordings, {total / 60:.1f} minutes raw, "
              f"{len(report['deck']['slides'])} slides.", ""]
    for item in report["footage"]:
        lines.append(f"## {item['source']}  ({item['seconds']:.0f}s)")
        for attempt in item["attempts"]:
            flag = "  ✗ abandoned" if attempt["abandoned"] else ""
            opening = " ".join(attempt["text"].split()[:14])
            lines.append(f"- `{attempt['start']:6.1f}–{attempt['end']:6.1f}` "
                         f"({attempt['seconds']:4.1f}s, {attempt['words']:3d}w)"
                         f"{flag}  {opening}…")
        if item.get("stutters"):
            # Listed even though they are removed automatically. A false start
            # is the one edit nobody can verify from the finished film — it
            # sounds correct whether or not it worked — so the only way to
            # check it is to be told where they were.
            lines.append("")
            lines.append("  false starts removed:")
            for run in item["stutters"]:
                lines.append(f"  - `{run['start']:6.1f}–{run['end']:6.1f}`  "
                             f"{run['text']}")
        if item.get("unresolved"):
            # Flagged as over-long, re-transcribed, and still over-long. The
            # audio in there is something — a false start, a stall, a word
            # said twice — and the recogniser will not say what. It is the
            # one thing in this report that needs a human with headphones.
            lines.append("  still unexplained, check by ear:")
            for w in item["unresolved"]:
                lines.append(f"  - `{w['start']:6.1f}–{w['end']:6.1f}`  "
                             f"{w['end'] - w['start']:.1f}s on \"{w['text']}\"")
            lines.append("")
        lines.append("")
    path = profile.directory / "INTAKE.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n  {path}")
    print(f"  {total / 60:.1f} min raw across {len(report['footage'])} files, "
          f"{sum(len(f['attempts']) for f in report['footage'])} attempts")


# ---------------------------------------------------------------------------
# 2. plan
# ---------------------------------------------------------------------------


BRIEF = """You are cutting a talking-head explainer from raw webcam footage and \
the slide deck the presenter wrote beforehand.

You get every recording transcribed with timestamps, split into attempts. The \
presenter recorded a section, fluffed it, and said it again — often several \
times, in the same file. You get the deck as structured text.

Return one JSON object. No prose, no markdown fence.

{"sections":[{
  "id": "02_cost",                     snake_case, two-digit prefix, in order
  "source": "<the `stem` of the recording>",
  "start": 41.9,                       seconds into THAT recording
  "end":   68.4,
  "presenter": "full" | "corner",
  "slide": {
     "layout": "title|statement|stats|steps|bullets|flow|equation|closer",
     "kicker": "STEP 3",               optional, <= 3 words, shown upper case
     "headline": "One page. That is it.",
     "sub": "",                        optional supporting line
     "footnote": "",                   optional aside, lands late in the section
     "accent": "blue|red|green|gold|violet|cyan",
     "items": [{"value":"+180%","label":"code"}]
  }}]}

## Choosing spans

- Pick the ONE best attempt for each part of the talk. Reject every attempt \
that trails off, restarts, corrects itself, or is audibly worse than another \
attempt at the same content. Most recordings contain exactly one keeper.
- `start` on the first word of the keeper, `end` on its last. Do not include \
the run-up ("okay so, um, right") or the trailing "yeah, that's it".
- A single recording may hold two consecutive sections; split it. A section may \
not span two recordings.
- Order the sections as the finished video plays. That is usually recording \
order, because people record front to back.
- Total the spans. The target runtime is <target>. Getting there is mostly a \
matter of choosing tighter `start`/`end` *within* the keeper: people restate \
the point twice and add a caveat nobody needed, and cutting that is free. Take \
the crispest statement of each idea and leave the rest on the floor.
- Where the talk has a numbered spine — "step one … step nine" — every number \
in it has to survive, or the video promises something it does not deliver. \
Compress those; do not drop them. Anything outside the spine is fair game to \
cut entirely, and dropping one whole digression beats shaving five seconds off \
everything.
- Being over the target is not a failure. Landing a minute over with every \
point made cleanly beats hitting it exactly with three of them rushed.
- Do not attempt to remove filler words or pauses. That happens downstream from \
word timings, and is more precise than you can be.

## Designing slides

- Every section gets a slide, even the ones framed `full` — a full-frame \
section shows the presenter and the slide is not rendered, but the fields are \
kept so re-framing later costs nothing.
- **Follow what was actually said, not what the deck said.** The deck is the \
plan; the recording is the talk. Where they disagree, the recording wins. If a \
point was cut in delivery, cut its slide. If something was added, give it one.
- The headline is the sentence the viewer should leave with. Short. Six words \
beats fourteen. Wrap the one word that carries it in *asterisks* to colour it.
- `items` is what the layout draws: `stats` wants `value` + `label`, `steps` \
and `flow` and `bullets` and `equation` want `label` (and `steps` may set \
`value` to force the badge number). Four items per slide is a lot; nine is only \
acceptable on `steps`.
- `footnote` is the aside — the line that arrives after the point has landed. \
Use it for the "nobody does this and it is the one that saves you" remarks.
- `presenter`: `full` when the argument is the person — the hook, the close, a \
direct claim with nothing to show. `corner` when the slide carries it. Open on \
`full` and end on `full`. Do not use `full` for more than about a third of the \
sections; a talking head with nothing beside it is the least interesting thing \
you can put on screen.
- Keep `accent` constant across the film except where a section is genuinely \
about a problem — those may use `red`. One accent change is a signal; five is a \
colour scheme.

## The deck

<deck>

## The footage

<footage>
"""


def _key() -> str:
    value = os.environ.get("ANTHROPIC_API_KEY", "")
    env = ROOT / ".env"
    if not value and env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("ANTHROPIC_API_KEY"):
                value = line.split("=", 1)[1].strip().strip('"').strip("'")
    return value


def _footage_brief(report: dict[str, Any]) -> str:
    blocks: list[str] = []
    for item in report["footage"]:
        lines = [f"### {item['stem']}  ({item['seconds']:.0f}s)"]
        for attempt in item["attempts"]:
            mark = " [says it went wrong]" if attempt["abandoned"] else ""
            lines.append(f"[{attempt['start']:.1f}–{attempt['end']:.1f}]{mark} "
                         f"{attempt['text']}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def plan(profile: Profile, report: dict[str, Any] | None = None,
         source: Path | None = None) -> dict[str, Any]:
    report = report or json.loads(
        (profile.directory / "ingest.json").read_text(encoding="utf-8"))
    if source:
        # A cut written by hand, or one exported from somewhere else. It goes
        # through exactly the same settling pass as a generated one — spans
        # snapped to whole words, pauses tightened, ids deduplicated — because
        # the alternative is two code paths that agree until they do not.
        print(f"  settling the cut in {source}")
        result = json.loads(source.read_text(encoding="utf-8"))
    elif not (key := _key()):
        print("  no ANTHROPIC_API_KEY — falling back to the mechanical plan")
        result = _fallback_plan(profile, report)
    else:
        result = _model_plan(profile, report, key)

    result = _settle(profile, report, result)
    profile.plan_path.write_text(json.dumps(result, indent=1), encoding="utf-8")
    _plan_report(profile, result)
    return result


def _model_plan(profile: Profile, report: dict[str, Any], key: str) -> dict[str, Any]:
    import anthropic

    target = (f"{profile.target_seconds:.0f} seconds"
              if profile.target_seconds else "as tight as the material allows")
    # `replace`, not `format`: the brief contains a JSON example, and every
    # brace in it would have to be doubled for `format` — which is a footgun
    # that fires the next time someone edits the schema.
    prompt = (BRIEF.replace("<target>", target)
                   .replace("<deck>", deckmod.outline(report["deck"]))
                   .replace("<footage>", _footage_brief(report)))
    print(f"  asking {MODEL} for the cut ({len(prompt)} chars) …")
    client = anthropic.Anthropic(api_key=key, timeout=900.0)
    # Streamed, because a plan for a dozen sections is a long answer and a
    # long non-streaming request is the one that comes back empty after four
    # minutes with nothing to show for it.
    text = ""
    with client.messages.stream(
            model=MODEL, max_tokens=24000,
            messages=[{"role": "user", "content": prompt}]) as stream:
        for chunk in stream.text_stream:
            text += chunk
            if len(text) % 4096 < len(chunk):
                print(f"    {len(text)} chars …", flush=True)
    text = text.strip()
    if not text:
        raise SystemExit(f"{MODEL} returned nothing. Re-run, or write "
                         f"{profile.plan_path} by hand.")
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        broken = profile.directory / "plan.broken.json"
        broken.write_text(text, encoding="utf-8")
        raise SystemExit(
            f"the planner did not return JSON ({exc}). Its answer is in "
            f"{broken}; fix it and save it as plan.json, or re-run.")


def _fallback_plan(profile: Profile, report: dict[str, Any]) -> dict[str, Any]:
    """One section per recording, its longest surviving attempt, deck order.

    Not a good cut. It is a *complete* one, which means the rest of the
    pipeline can be exercised, tested and debugged without a network call — and
    when the key is missing at 2am that is the difference between a rough video
    and no video.
    """
    slides = report["deck"]["slides"]
    sections: list[dict[str, Any]] = []
    for i, item in enumerate(report["footage"]):
        alive = [a for a in item["attempts"] if not a["abandoned"]] or item["attempts"]
        if not alive:
            continue
        best = max(alive, key=lambda a: a["words"])
        slide = slides[i] if i < len(slides) else None
        blocks = slide["blocks"] if slide else []
        head = next((b["text"] for b in blocks if b["role"] == "headline"), "")
        kick = next((b["text"] for b in blocks if b["role"] == "kicker"), "")
        note = next((b["text"] for b in blocks if b["role"] == "footnote"), "")
        items = [{"label": b["text"]} for b in blocks
                 if b["role"] in ("item", "body")][:6]
        slug = re.sub(r"[^a-z0-9]+", "_", (head or item["stem"]).lower())
        sections.append({
            "id": f"{i + 1:02d}_{slug[:16].strip('_')}",
            "source": item["stem"], "start": best["start"], "end": best["end"],
            "presenter": "full" if i in (0, len(report["footage"]) - 1) else "corner",
            "slide": {"layout": "bullets" if items else "statement",
                      "kicker": kick, "headline": head or "", "footnote": note,
                      "accent": profile.accent, "items": items},
        })
    return {"sections": sections}


def _settle(profile: Profile, report: dict[str, Any],
            result: dict[str, Any]) -> dict[str, Any]:
    """Make the plan true: snap spans to words, tighten them, record the text.

    A plan straight from the model has times that are close and ids that may
    collide. Everything downstream indexes on both, so both are made exact here
    rather than defended against in four later places.
    """
    by_stem = {item["stem"]: item for item in report["footage"]}
    seen: set[str] = set()
    settled: list[dict[str, Any]] = []

    for order, section in enumerate(result.get("sections", []), start=1):
        stem = section.get("source", "")
        if stem not in by_stem:
            match = [s for s in by_stem if stem and stem in s]
            if not match:
                print(f"  ! section {section.get('id')} names unknown source "
                      f"{stem!r} — dropped")
                continue
            stem = match[0]

        # Snap to whole words. A span that starts 200ms into "verify" plays as
        # "-erify", and the model's times are only ever close.
        words = [w for w in words_of(profile, stem)
                 if w.end > float(section["start"]) - 0.25
                 and w.start < float(section["end"]) + 0.25]
        if not words:
            print(f"  ! section {section.get('id')} has no words in "
                  f"{section['start']}–{section['end']} — dropped")
            continue

        drops = [(float(a), float(b)) for a, b in section.get("drops", [])]
        if drops:
            words = [w for w in words
                     if not any(a <= (w.start + w.end) / 2 <= b for a, b in drops)]
            if not words:
                print(f"  ! section {section.get('id')} is entirely dropped")
                continue
        keeps = subtract(tighten(words), drops)
        identifier = section.get("id") or f"{order:02d}_section"
        while identifier in seen:
            identifier += "_b"
        seen.add(identifier)

        slide = dict(section.get("slide") or {})
        slide.setdefault("accent", profile.accent)
        slide["presenter"] = section.get("presenter", "corner")

        settled.append({
            "id": identifier,
            "source": stem,
            "path": by_stem[stem]["path"],
            "start": round(keeps[0][0], 3),
            "end": round(keeps[-1][1], 3),
            "keeps": [[round(a, 3), round(b, 3)] for a, b in keeps],
            "drops": [[round(a, 3), round(b, 3)] for a, b in drops],
            "seconds": round(sum(b - a for a, b in keeps), 3),
            "presenter": section.get("presenter", "corner"),
            "slide": slide,
            "say": " ".join(w.text.strip() for w in words).strip(),
        })

    if not settled:
        raise SystemExit("the plan has no usable sections")
    return {"title": profile.title or profile.name, "aspect": profile.aspect,
            "sections": settled}


def tighten(words: list[Word], pause_cut: float = PAUSE_CUT,
            pause_keep: float = PAUSE_KEEP, head_pad: float = HEAD_PAD,
            tail_pad: float = TAIL_PAD,
            min_segment: float = MIN_SEGMENT) -> list[tuple[float, float]]:
    """Turn a span of words into the ranges of it worth keeping.

    Three removals, in this order:

    **Filler.** "Um" and its relatives, with the hesitation either side of them,
    because removing the word and leaving the gap is worse than leaving both.

    **Long pauses.** Anything over `PAUSE_CUT` is shortened to `PAUSE_KEEP`
    rather than closed up. A talk with every pause removed does not sound
    tight, it sounds like a machine reading — the pauses under the threshold
    are the delivery and are left exactly alone.

    **The ends.** Leading and trailing silence, replaced by a fixed pad.

    Returns ranges in source time. Concatenating them in order is the cut.
    """
    kept = [w for w in words if not w.filler]
    if not kept:
        return [(words[0].start, words[-1].end)]

    ranges: list[list[float]] = [[kept[0].start - head_pad, kept[0].end]]
    for previous, word in zip(kept, kept[1:]):
        gap = word.start - previous.end
        if gap > pause_cut:
            # Close the run, keeping a little of the pause on each side so the
            # join has the breath the ear expects.
            ranges[-1][1] = previous.end + pause_keep / 2
            ranges.append([word.start - pause_keep / 2, word.end])
        else:
            ranges[-1][1] = word.end
    ranges[-1][1] += tail_pad
    ranges[0][0] = max(0.0, ranges[0][0])

    # A sliver left behind by two cuts close together is not worth the jump it
    # costs; fold it into its neighbour.
    merged: list[list[float]] = []
    for span in ranges:
        if merged and (span[1] - span[0] < min_segment
                       or span[0] - merged[-1][1] < min_segment):
            merged[-1][1] = span[1]
        else:
            merged.append(span)
    return [(a, b) for a, b in merged if b > a]


def subtract(ranges: list[tuple[float, float]],
             drops: list[tuple[float, float]],
             floor: float = MIN_SEGMENT) -> list[tuple[float, float]]:
    """Remove hand-written cuts from computed ones.

    `drops` is the escape hatch for everything the arithmetic cannot see: a
    tool name fumbled four ways, an example that went on too long, a sentence
    started twice without a pause between the goes. Written in the plan as
    source-time ranges, so they mean the same thing after a re-plan.

    Applied *after* `tighten` and by interval subtraction rather than by
    filtering words, because tighten pads each range with a fraction of the
    pause on either side and that padding is exactly wide enough to catch the
    first syllable of the thing being dropped.

    `floor` discards the slivers left behind. It is a parameter because the
    default suits hand-written cuts, where a fragment under half a second is
    not worth the jump -- and is completely wrong for subtracting detected
    silence, where the fragments between two pauses are the words.
    """
    if not drops:
        return ranges
    out: list[tuple[float, float]] = []
    for start, end in ranges:
        pieces = [(start, end)]
        for a, b in sorted(drops):
            nxt: list[tuple[float, float]] = []
            for x, y in pieces:
                if b <= x or a >= y:
                    nxt.append((x, y))
                    continue
                if x < a:
                    nxt.append((x, a))
                if b < y:
                    nxt.append((b, y))
            pieces = nxt
        out += [(x, y) for x, y in pieces if y - x >= floor]
    return out


def _plan_report(profile: Profile, result: dict[str, Any]) -> None:
    total = sum(s["seconds"] for s in result["sections"])
    print(f"\n  {len(result['sections'])} sections, {total:.0f}s "
          f"({total / 60:.1f} min)")
    at = 0.0
    for section in result["sections"]:
        saved = (section["end"] - section["start"]) - section["seconds"]
        cuts = len(section["keeps"]) - 1
        minutes, seconds = divmod(int(at), 60)
        print(f"    {minutes}:{seconds:02d}  {section['id']:<22} "
              f"{section['seconds']:5.1f}s  {section['presenter']:<6} "
              f"{section['slide'].get('layout', '?'):<9} "
              f"{cuts} cut{'s' if cuts != 1 else ' '}  -{saved:.1f}s")
        at += section["seconds"]
    print(f"\n  {profile.plan_path}")


# ---------------------------------------------------------------------------
# 3. build
# ---------------------------------------------------------------------------


def loudness(path: Path) -> float | None:
    """Integrated loudness of a file's audio, in LUFS.

    Returns None rather than raising: a missing measurement is a reason to
    fall back to a fixed gain, not a reason to lose the render.
    """
    result = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-map", "0:a",
         "-af", "ebur128=framelog=quiet", "-f", "null", "-"],
        capture_output=True, text=True)
    found = re.findall(r"I:\s*(-?\d+\.\d+)\s*LUFS", result.stderr)
    return float(found[-1]) if found else None


def duration(path: Path) -> float:
    return float(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True, check=True).stdout.strip())


def lift(source: Path, keeps: list[tuple[float, float]], out: Path,
         size: tuple[int, int] | None = None, punch: bool = False,
         speed: float = 1.0, mirror: bool = False) -> Path:
    """Cut the kept ranges out of a recording and join them into one clip.

    Done as a single filtergraph rather than N extractions and a concat
    demuxer. Trimming with `-ss` snaps to the nearest keyframe — on a 30fps
    screen recording that is up to two seconds of slack, which is a whole
    sentence — and `trim` is frame-accurate.

    `punch` alternates a small push-in across the segments. On a static webcam
    a jump cut is visible as a shoulder teleporting; the same cut under a
    change of framing reads as a deliberate edit. It is the cheapest trick in
    this file and the one that does the most.
    """
    parts: list[str] = []
    labels: list[str] = []
    for i, (start, end) in enumerate(keeps):
        span = end - start
        zoom = 1.0 + (0.055 if punch and i % 2 else 0.0)
        chain = f"[0:v]trim=start={start:.3f}:end={end:.3f},setpts=PTS-STARTPTS"
        if size:
            width, height = size
            chain += (f",scale={width}:{height}:force_original_aspect_ratio="
                      f"increase:flags=lanczos,crop={width}:{height}")
        if zoom > 1.0:
            # Crop in, then scale back out to the size we started at. Zooming
            # by scaling *up* and cropping leaves each segment at a slightly
            # different sample aspect ratio, and `concat` rejects a mismatched
            # SAR with nothing more helpful than "Invalid argument".
            chain += (f",crop=iw/{zoom:.4f}:ih/{zoom:.4f},"
                      f"scale={'%d:%d' % size if size else 'iw*%.4f:ih*%.4f' % (zoom, zoom)}"
                      f":flags=lanczos")
        # Pinned explicitly rather than inherited: every segment must reach
        # `concat` with the same rate and the same SAR or it refuses the lot.
        if mirror:
            # Selfie footage, flipped back to the way the presenter sees
            # themselves. Applied here rather than at the end so it lands on
            # the presenter's own frames only -- a flip on the finished cut
            # would also mirror every card and every screen recording, and
            # mirrored code is a very fast way to look like a fake.
            chain += ",hflip"
        chain += ",setsar=1,fps=30,format=yuv420p"
        if speed != 1.0:
            # Applied per segment rather than to the concatenated result: the
            # segments are what the caption times are derived from, and one
            # rate change at the end would leave every word late by a growing
            # amount. `atempo` holds pitch, which is the whole point -- a
            # chipmunk voice is what a naive rate change sounds like.
            chain += f",setpts=PTS/{speed:.4f}"
        parts.append(f"{chain}[v{i}]")
        fade = min(XFADE, span / 3)
        parts.append(
            f"[0:a]atrim=start={start:.3f}:end={end:.3f},asetpts=PTS-STARTPTS,"
            f"aresample=48000,aformat=sample_fmts=s16:channel_layouts=stereo,"
            f"afade=t=in:st=0:d={fade:.3f},"
            f"afade=t=out:st={max(0.0, span - fade):.3f}:d={fade:.3f}"
            + (f",atempo={speed:.4f}" if speed != 1.0 else "")
            + f"[a{i}]")
        labels += [f"[v{i}]", f"[a{i}]"]

    graph = ";".join(parts) + ";" + "".join(labels) + \
        f"concat=n={len(keeps)}:v=1:a=1[v][a]"
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(source),
         "-filter_complex", graph, "-map", "[v]", "-map", "[a]",
         "-c:v", "libx264", "-preset", "medium", "-crf", "17",
         "-pix_fmt", "yuv420p", "-c:a", "pcm_s16le", str(out)],
        check=True)
    return out


def section_words(profile: Profile, section: dict[str, Any]) -> list[Word]:
    """The section's words, retimed onto the cut clip's own clock.

    This is why captions cannot drift. Every removed range shifts everything
    after it earlier by exactly its own length, and that shift is applied here
    once, from the same list of ranges the video was cut with.
    """
    source = words_of(profile, section["source"])
    out: list[Word] = []
    elapsed = 0.0
    for start, end in section["keeps"]:
        for word in source:
            middle = (word.start + word.end) / 2
            if start <= middle <= end:
                out.append(Word(text=word.text,
                                start=round(word.start - start + elapsed, 3),
                                end=round(min(word.end, end) - start + elapsed, 3),
                                probability=word.probability))
        elapsed += end - start
    return out


def _overlay(profile: Profile) -> Path:
    """The frame furniture that a full-frame presenter section shares with the
    slides: the accent hairline and a vignette. Without it the cut to a
    talking head reads as a cut to different software."""
    width, height = profile.size
    path = profile.work / "_frame.png"
    if path.exists():
        return path
    from PIL import Image, ImageDraw, ImageFilter

    layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    accent = slidekit.ACCENTS.get(profile.accent, slidekit.ACCENTS["blue"])
    d.rectangle([0, 0, width, max(2, height // 360)], fill=(*accent, 190))

    shade = Image.new("L", (width, height), 150)
    ImageDraw.Draw(shade).ellipse(
        [-width // 5, -height // 4, width + width // 5, height + height // 4], fill=0)
    shade = shade.filter(ImageFilter.GaussianBlur(90))
    layer = Image.alpha_composite(
        layer, Image.merge("RGBA", (Image.new("L", (width, height), 6),) * 3
                           + (shade,)))
    path.parent.mkdir(parents=True, exist_ok=True)
    layer.save(path)
    return path


def frame_full(clip: Path, out: Path, profile: Profile,
               progress: tuple[int, int]) -> Path:
    """The presenter filling the canvas, dressed to match the slides."""
    width, height = profile.size
    rail = max(3, int(height * 0.0046))
    current, total = progress
    seconds = duration(clip)
    done_from = width * (current - 1) / total
    done_to = width * current / total
    accent = "0x%02X%02X%02X" % slidekit.ACCENTS.get(
        profile.accent, slidekit.ACCENTS["blue"])
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(clip),
         "-i", str(_overlay(profile)),
         "-filter_complex",
         # A slide is a dark frame with saturated accents; a webcam pointed at
         # a cream wall is neither. Cutting between the two ungraded reads as
         # cutting between two different videos, so the presenter is pulled
         # down and firmed up to meet the slides halfway.
         f"[0:v]scale={width}:{height}:force_original_aspect_ratio=increase:"
         f"flags=lanczos,crop={width}:{height},"
         f"eq=contrast=1.09:brightness=-0.035:saturation=1.06,fps=30[s];"
         f"[s][1:v]overlay=0:0[o];"
         f"[o]drawbox=x=0:y={height - rail}:w={width}:h={rail}:"
         f"color=0x161B22@1.0:t=fill,"
         f"drawbox=x=0:y={height - rail}:"
         f"w='{done_from:.1f}+({done_to - done_from:.1f})*t/{max(0.1, seconds):.3f}':"
         f"h={rail}:color={accent}@0.85:t=fill[v]",
         "-map", "[v]", "-map", "0:a", "-c:v", "libx264", "-preset", "medium",
         "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "pcm_s16le", str(out)],
        check=True)
    return out


def frame_corner(slide: Path, clip: Path, out: Path, profile: Profile) -> Path:
    """The slide, with the presenter in a circle in the corner."""
    from demoforge.compose import head_clip

    width, height = profile.size
    size = profile.inset
    margin = profile.inset_margin
    inset = out.with_suffix(".inset.mov")
    head_clip(clip, inset, size, bias=0.42, zoom=0.72)

    x, y = width - size - margin, height - size - margin
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(slide), "-i", str(inset),
         "-i", str(clip),
         "-filter_complex",
         # Audio is mapped from the untouched take rather than from either
         # composited stream: the slide is silent, and the inset has been
         # through a colour-space conversion that ffmpeg would happily re-encode
         # the audio alongside for no reason.
         f"[0:v][1:v]overlay={x}:{y}:shortest=0[v]",
         "-map", "[v]", "-map", "2:a", "-c:v", "libx264", "-preset", "medium",
         "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "pcm_s16le",
         "-t", f"{duration(slide):.3f}", str(out)],
        check=True)
    inset.unlink(missing_ok=True)
    return out


def build(profile: Profile, out: Path | None = None,
          only: list[str] | None = None, steps: list[str] | None = None) -> Path:
    plan_data = json.loads(profile.plan_path.read_text(encoding="utf-8"))
    sections = plan_data["sections"]
    steps = steps or ["sections", "concat", "captions", "music"]
    work = profile.work
    work.mkdir(parents=True, exist_ok=True)
    out = out or profile.home / f"{profile.name}-edited.mp4"
    width, height = profile.size

    pieces: list[Path] = []
    words: list[Word] = []
    timeline: list[dict[str, Any]] = []
    at = 0.0

    for index, section in enumerate(sections, start=1):
        piece = work / f"{section['id']}.mp4"
        keeps = [(float(a), float(b)) for a, b in section["keeps"]]
        seconds = sum(b - a for a, b in keeps)
        wanted = "sections" in steps and (not only or section["id"] in only)

        if wanted or not piece.exists():
            print(f"  {index:2d}/{len(sections)}  {section['id']:<24} "
                  f"{seconds:5.1f}s  {section['presenter']}")
            source = Path(section["path"])
            clip = work / f"{section['id']}.take.mp4"
            lift(source, keeps, clip,
                 size=(width, height) if section["presenter"] == "full" else None,
                 punch=section["presenter"] == "full")

            if section["presenter"] == "full":
                frame_full(clip, piece, profile, (index, len(sections)))
            else:
                spec = slidekit.Spec.parse(
                    {**section["slide"], "presenter": "corner"})
                slide = work / f"{section['id']}.slide.mp4"
                slidekit.render(spec, duration(clip), slide, (width, height),
                                progress=(index, len(sections)))
                frame_corner(slide, clip, piece, profile)
            clip.unlink(missing_ok=True)

        actual = duration(piece)
        for word in section_words(profile, section):
            words.append(Word(text=word.text, start=word.start + at,
                              end=word.end + at, probability=word.probability))
        pieces.append(piece)
        timeline.append({"id": section["id"], "start": round(at, 2),
                         "seconds": round(actual, 2),
                         "presenter": section["presenter"],
                         "headline": section["slide"].get("headline", ""),
                         "say": section["say"]})
        at += actual

    master = work / "master.mp4"
    if "concat" in steps or not master.exists():
        print("\n== concat ==")
        _concat(pieces, work, master)

    result = master
    captioned = work / "captioned.mp4"
    if profile.captions and "captions" not in steps and captioned.exists():
        # Skipping the caption step must mean "reuse the captions", not "ship
        # without them". `--steps music` is the most common re-run there is and
        # it silently produced a bare cut.
        print("  reusing the burned captions")
        result = captioned
    if profile.captions and "captions" in steps:
        print("\n== captions ==")
        accent = "#%02X%02X%02X" % slidekit.ACCENTS.get(
            profile.accent, slidekit.ACCENTS["blue"])
        ass = work / "captions.ass"
        caps.write(words, ass, width, height, accent)
        caps.srt(words, out.with_suffix(".srt"))
        caps.burn(result, ass, captioned)
        result = captioned

    print("\n== sound ==")
    result = _sound(profile, result, work, out)

    manifest = out.with_suffix(".timeline.json")
    manifest.write_text(json.dumps(timeline, indent=2), encoding="utf-8")
    print(f"\n  {out}  {duration(out):.1f}s")
    print(f"  {manifest}")
    _timecodes(timeline)
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
    """Clean the voice, put a bed under it, and land on a broadcast loudness.

    Order matters. Denoise and shape *before* the music arrives, or the
    compressor spends its range on hiss. Normalise *after*, or the bed changes
    the number you normalised to.
    """
    voiced = work / "voice.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(video),
         "-af", "highpass=f=85,afftdn=nr=10:nf=-28,"
                "acompressor=threshold=-20dB:ratio=3:attack=8:release=180,"
                "alimiter=limit=0.95",
         "-c:v", "copy", "-c:a", "pcm_s16le", str(voiced)],
        check=True)

    if not profile.music:
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", str(voiced),
             "-af", "loudnorm=I=-14:TP=-1.5:LRA=11", "-c:v", "copy",
             "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out)],
            check=True)
        voiced.unlink(missing_ok=True)
        return out

    from demoforge.music import bed, mix

    length = duration(voiced)
    track = work / "bed.wav"
    if not track.exists():
        bed(length + 4, track, style=profile.music_style, seed=7)

    # How loud the bed should be is a question about the voice, not a number
    # of decibels. Both are measured and the gain is derived, so a quiet take
    # and a loud one get a bed that sits the same distance underneath.
    #
    # `duck_db` is passed as zero deliberately. `music.mix` applies it on top
    # of `music_db` rather than as the depth of the duck, so setting both
    # stacks them — which is how a bed ends up 36dB down and the film ships
    # with no music anybody can hear. The ducking itself is the sidechain's
    # job and happens regardless.
    voice_lufs = loudness(voiced)
    bed_lufs = loudness(track)
    if voice_lufs is None or bed_lufs is None:
        gain = -20.0
        print("  could not measure loudness; bed at a fixed -20dB")
    else:
        gain = (voice_lufs + profile.music_under) - bed_lufs
        print(f"  voice {voice_lufs:.1f} LUFS, bed {bed_lufs:.1f} LUFS "
              f"→ {gain:+.1f}dB for {profile.music_under:+.0f} LU under")
    scored = work / "scored.mp4"
    mix(voiced, track, scored, music_db=gain, duck_db=0.0,
        ratio=profile.music_ratio, release=profile.music_release)
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(scored),
         "-af", "loudnorm=I=-14:TP=-1.5:LRA=11", "-c:v", "copy",
         "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out)],
        check=True)
    voiced.unlink(missing_ok=True)
    return out


def _timecodes(timeline: list[dict[str, Any]]) -> None:
    print("\n  timecodes")
    for entry in timeline:
        minutes, seconds = divmod(int(entry["start"]), 60)
        # The stored headline keeps its `*emphasis*` markers, because that is
        # what the renderer needs. A description box does not.
        label = (slidekit.strip_emphasis(entry["headline"])
                 or " ".join(entry["say"].split()[:8]))
        print(f"    {minutes}:{seconds:02d}  {label}")


# ---------------------------------------------------------------------------
# cli
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="demoforge edit", description=__doc__)
    sub = ap.add_subparsers(dest="action", required=True)

    new = sub.add_parser("new", help="write an editor profile")
    new.add_argument("--project", required=True)
    new.add_argument("--deck", required=True)
    new.add_argument("--footage", nargs="+", required=True)
    new.add_argument("--aspect", default="16:9", choices=sorted(ASPECTS))
    new.add_argument("--seconds", type=float, default=0.0)

    ing = sub.add_parser("ingest", help="read the deck and transcribe the footage")
    ing.add_argument("--project", required=True)
    ing.add_argument("--model", default=None)
    ing.add_argument("--no-cache", action="store_true")

    pl = sub.add_parser("plan", help="choose the cut and design the slides")
    pl.add_argument("--project", required=True)
    pl.add_argument("--from", dest="source", default=None,
                    help="settle a cut written by hand instead of asking a model")

    bd = sub.add_parser("build", help="render the cut")
    bd.add_argument("--project", required=True)
    bd.add_argument("--out", default=None)
    bd.add_argument("--only", nargs="*", default=None)
    bd.add_argument("--steps", default=None,
                    help="sections,concat,captions,music")

    al = sub.add_parser("all", help="ingest, plan and build in one go")
    al.add_argument("--project", required=True)
    al.add_argument("--out", default=None)

    args = ap.parse_args(argv)

    if args.action == "new":
        scaffold(args.project, args.deck, args.footage, args.aspect, args.seconds)
        return 0

    profile = load(args.project)

    if args.action == "ingest":
        ingest(profile, args.model, cache=not args.no_cache)
    elif args.action == "plan":
        plan(profile, source=Path(args.source) if args.source else None)
    elif args.action == "build":
        build(profile, Path(args.out) if args.out else None, args.only,
              args.steps.split(",") if args.steps else None)
    else:
        report = ingest(profile)
        plan(profile, report)
        build(profile, Path(args.out) if args.out else None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
