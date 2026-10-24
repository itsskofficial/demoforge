"""Words, with the time each one was said.

Every decision the editor makes is a decision about *words* — which take was
the clean one, where the sentence restarted, which "um" to lift out, when a
caption should change. So the transcript is not a convenience here, it is the
edit medium. Nothing downstream reads the audio again.

Two things matter about the output and neither is the text:

**Word-level timestamps.** Segment-level ones are enough to caption a video and
useless for cutting one. Removing a filler word needs to know where that word
starts to within about 40ms, and a cut placed on a segment boundary lands
somewhere in the middle of the next breath.

**Stability under re-runs.** Transcription is the slowest stage that isn't a
render, so the result is cached against the source's size and mtime. Re-running
`ingest` after fixing one thing in the profile should cost seconds.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

MODEL = "large-v3"

# Bumped when anything changes the words a recording produces, so cached
# transcripts from before the change are re-made rather than trusted.
REVISION = 4

# Words that carry no meaning and are worth lifting out of a cut. Kept
# deliberately short: aggressive filler removal makes speech sound like a
# ransom note. "like" and "so" are absent on purpose — both are load-bearing
# often enough that removing every instance is worse than keeping them all.
FILLER = {
    "um", "uh", "umm", "uhh", "erm", "er", "ah", "hmm", "mm",
    "haan", "arre",
}

# Said out loud when a take has gone wrong. A line containing one of these is a
# strong signal that everything before it in that attempt is rubbish.
ABANDON = re.compile(
    r"\b(sorry|scratch that|let me (start|do|say|try) (that|it|this)? ?again|"
    r"one more time|from the top|take (two|three|four|five)|"
    r"cut that|again again|wait wait|no no no)\b",
    re.I,
)


def normalise(word: str) -> str:
    return re.sub(r"[^\w']", "", word).lower()


@dataclass
class Word:
    text: str
    start: float
    end: float
    probability: float = 1.0

    @property
    def key(self) -> str:
        return normalise(self.text)

    @property
    def filler(self) -> bool:
        return self.key in FILLER


@dataclass
class Transcript:
    source: str
    duration: float
    language: str
    text: str
    words: list[Word] = field(default_factory=list)

    @classmethod
    def load(cls, path: Path) -> "Transcript":
        raw = json.loads(path.read_text(encoding="utf-8"))
        raw["words"] = [Word(**w) for w in raw["words"]]
        return cls(**{k: v for k, v in raw.items() if k != "fingerprint"})

    def save(self, path: Path, fingerprint: str = "") -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = asdict(self)
        payload["fingerprint"] = fingerprint
        path.write_text(json.dumps(payload, indent=1), encoding="utf-8")
        return path

    def between(self, start: float, end: float) -> list[Word]:
        """Words whose midpoint falls inside the window.

        Midpoint rather than containment: a word straddling the boundary
        belongs to whichever side has more of it, and containment would drop it
        from both.
        """
        return [w for w in self.words
                if start <= (w.start + w.end) / 2 <= end]

    def say(self, start: float, end: float) -> str:
        return " ".join(w.text.strip() for w in self.between(start, end)).strip()


def implausible(word: Word) -> bool:
    """A word held far longer than it takes to say.

    This is the signature of the failure that nothing else in the pipeline can
    see. When somebody stumbles and restarts — "okay you, okay you need to
    stop" — the recogniser often transcribes the sentence once and hangs the
    whole false start off the duration of a single word. The text is clean, the
    timings are clean, and there is no *gap*, so pause-tightening walks straight
    past two seconds of audio that says the thing twice.

    A syllable takes something like 75ms and a word carries a little overhead.
    Three times that, and at least 0.9s, is loose enough to ignore a drawn-out
    word for emphasis and tight enough to catch a collapsed restart.
    """
    expected = 0.075 * len(normalise(word.text)) + 0.06
    span = word.end - word.start
    return span > 0.9 and span > 3 * expected


def windows(words: list[Word], pad: float = 1.6, join: float = 1.0,
            shortest: float = 4.5) -> list[tuple[float, float]]:
    """The stretches worth listening to again, merged where they touch.

    Generously padded, and never shorter than `shortest`. A three-second clip
    handed to the model on its own comes back worse than the pass it is meant
    to correct — "okay you need to stop" was returned as "okay, U, make the
    stop" from a 2.9s window and correctly from a 6s one. The model is doing
    language modelling as much as transcription and a window with no run-up
    gives it nothing to model.
    """
    spans: list[list[float]] = []
    for w in words:
        if not implausible(w):
            continue
        start, end = w.start - pad, w.end + pad
        if end - start < shortest:
            middle = (start + end) / 2
            start, end = middle - shortest / 2, middle + shortest / 2
        spans.append([max(0.0, start), end])

    merged: list[list[float]] = []
    for start, end in spans:
        if merged and start - merged[-1][1] < join:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [(a, b) for a, b in merged]


def _overlap(original: list[Word], refined: list[Word]) -> float:
    """How much of the original survives, in order, in the refined pass.

    Plain longest-common-subsequence over normalised words. The refinement is
    only supposed to *reveal* audio the first pass folded away, so it should
    contain what was already there. When it does not, the model has re-heard
    the clip as something else and its answer is worse than the question.
    """
    a = [w.key for w in original if w.key]
    b = [w.key for w in refined if w.key]
    if not a:
        return 1.0
    table = [0] * (len(b) + 1)
    for x in a:
        previous, table = table[:], [0] * (len(b) + 1)
        for j, y in enumerate(b, start=1):
            table[j] = previous[j - 1] + 1 if x == y else max(previous[j],
                                                              table[j - 1])
    return table[-1] / len(a)


def refine(words: list[Word], video: Path, model: str = MODEL,
           scratch: Path | None = None) -> list[Word]:
    """Re-transcribe the stretches that look collapsed, and splice them back.

    A long file is transcribed in 30-second mel windows and the aligner has to
    place every word in one pass; a six-second clip of the same audio gets the
    model's whole attention and reliably comes back with the words that were
    folded away. Nothing else changes — only the words inside a suspect window
    are replaced, and their times stay absolute — so this is safe to run over
    every recording rather than only the ones somebody noticed.
    """
    suspects = windows(words)
    if not suspects:
        return words

    import torch
    device = "cuda" if torch.cuda.is_available() else "cpu"
    loaded = _model(model, device)
    scratch = scratch or video.parent
    clip = scratch / f"_refine-{video.stem}.wav"

    out = list(words)
    for start, end in reversed(suspects):  # from the back, so indices hold
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{start:.3f}",
             "-t", f"{end - start:.3f}", "-i", str(video),
             "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(clip)],
            check=True)
        result = loaded.transcribe(
            str(clip), word_timestamps=True, language="en",
            fp16=(device == "cuda"), temperature=0.0,
            condition_on_previous_text=False)
        found: list[Word] = []
        for segment in result.get("segments", []):
            for w in segment.get("words", []):
                text = w["word"].strip()
                if text:
                    found.append(Word(text=text,
                                      start=round(start + float(w["start"]), 3),
                                      end=round(start + float(w["end"]), 3),
                                      probability=round(
                                          float(w.get("probability", 1.0)), 3)))
        if not found:
            continue
        head = [w for w in out if (w.start + w.end) / 2 < start]
        tail = [w for w in out if (w.start + w.end) / 2 > end]
        inside = [w for w in out if w not in head and w not in tail]

        # Never accept a refinement that lost something. A second pass that
        # comes back shorter, or that no longer contains what the first pass
        # heard, has re-interpreted the clip rather than resolved it — and
        # splicing that in replaces a transcription problem with a wrong one.
        keep = _overlap(inside, found)
        if len(found) < len(inside) or keep < 0.75:
            print(f"    refinement of {start:.1f}–{end:.1f}s rejected "
                  f"({keep:.0%} of the original survived)")
            continue
        out = head + found + tail

    # A second, tighter pass over anything still unexplained.
    #
    # The wide window is right for most collapses: the model needs run-up to
    # decode well. But a restart buried inside a long word is a case the wide
    # window reads straight past -- it produces a confident, fluent sentence
    # with the same hole in it. Cropped to the hole itself the model has
    # nothing else to attend to and reports what is actually there. "Put an
    # AGENTS.md at" turned out to be in there twice, and no amount of context
    # was going to reveal it.
    for word in [w for w in out if implausible(w)]:
        start = max(0.0, word.start - 0.25)
        end = word.end + 0.25
        if end - start < 1.4:
            middle = (start + end) / 2
            start, end = max(0.0, middle - 0.7), middle + 0.7
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{start:.3f}",
             "-t", f"{end - start:.3f}", "-i", str(video),
             "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(clip)],
            check=True)
        result = loaded.transcribe(
            str(clip), word_timestamps=True, language="en",
            fp16=(device == "cuda"), temperature=0.0,
            condition_on_previous_text=False)
        found = []
        for segment in result.get("segments", []):
            for w in segment.get("words", []):
                text = w["word"].strip()
                if text:
                    found.append(Word(text=text,
                                      start=round(start + float(w["start"]), 3),
                                      end=round(start + float(w["end"]), 3),
                                      probability=round(
                                          float(w.get("probability", 1.0)), 3)))
        inside = [w for w in out if start <= (w.start + w.end) / 2 <= end]
        # Accept only if it found more than was there. This pass exists to
        # reveal words, so anything that does not reveal any is noise.
        if len(found) <= len(inside) or _overlap(inside, found) < 0.4:
            continue
        print(f"    {start:.1f}-{end:.1f}s resolved into {len(found)} words: "
              f"{' '.join(w.text for w in found)}")
        out = ([w for w in out if (w.start + w.end) / 2 < start] + found
               + [w for w in out if (w.start + w.end) / 2 > end])

    clip.unlink(missing_ok=True)
    return out


def repair(words: list[Word], video: Path, spans: list[tuple[float, float]],
           model: str = MODEL, scratch: Path | None = None) -> list[Word]:
    """Re-transcribe named windows and splice the result in.

    `refine` finds its own suspects from word duration, which catches a restart
    buried inside one long word and misses one the recogniser smeared across
    several. When a person can hear a repeat that no heuristic flags, this is
    the way to say so: name the window, and the words in it are replaced by a
    dedicated pass over that audio alone.

    No overlap guard here, unlike `refine`. The point of naming a window is
    that the first pass was wrong about it, so requiring the new words to agree
    with the old ones would reject exactly the corrections being asked for.
    """
    if not spans:
        return words
    import torch
    device = "cuda" if torch.cuda.is_available() else "cpu"
    loaded = _model(model, device)
    scratch = scratch or video.parent
    clip = scratch / f"_repair-{video.stem}.wav"

    out = list(words)
    for start, end in sorted(spans, reverse=True):
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{start:.3f}",
             "-t", f"{end - start:.3f}", "-i", str(video),
             "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(clip)],
            check=True)
        result = loaded.transcribe(
            str(clip), word_timestamps=True, language="en",
            fp16=(device == "cuda"), temperature=0.0,
            condition_on_previous_text=False)
        found = []
        for segment in result.get("segments", []):
            for w in segment.get("words", []):
                text = w["word"].strip()
                if text:
                    found.append(Word(text=text,
                                      start=round(start + float(w["start"]), 3),
                                      end=round(start + float(w["end"]), 3),
                                      probability=round(
                                          float(w.get("probability", 1.0)), 3)))
        if not found:
            print(f"    repair {start:.1f}-{end:.1f}s heard nothing; left alone")
            continue
        print(f"    repair {start:.1f}-{end:.1f}s -> "
              f"{' '.join(w.text for w in found)}")
        out = ([w for w in out if (w.start + w.end) / 2 < start] + found
               + [w for w in out if (w.start + w.end) / 2 > end])
    clip.unlink(missing_ok=True)
    return out


def destutter(words: list[Word], longest: int = 6, gap: float = 1.6
              ) -> tuple[list[Word], list[list[Word]]]:
    """Drop a run of words immediately said again, keeping the second go.

    A false start is a prefix of the sentence that follows it: "okay you" then
    "okay you need to stop". So the test is whether the next `k` words repeat
    the previous `k` — and the copy to keep is the later one, because that is
    the one that carries on into the rest of the sentence.

    Longest match first. "the the coding workflow the coding workflow" should
    lose three words, not one, and a one-word test would fire on "the" and
    leave the real repeat standing.
    """
    out: list[Word] = []
    removed: list[list[Word]] = []
    i = 0
    while i < len(words):
        cut = 0
        for size in range(min(longest, (len(words) - i) // 2), 0, -1):
            first = words[i:i + size]
            second = words[i + size:i + size * 2]
            if [w.key for w in first] != [w.key for w in second]:
                continue
            if not any(w.key for w in first):  # punctuation only
                continue
            if second[0].start - first[-1].end > gap:
                continue
            cut = size
            break
        if cut:
            removed.append(words[i:i + cut])
            i += cut
            continue
        out.append(words[i])
        i += 1
    return out, removed


def correct(words: list[Word], mapping: dict[str, str]) -> list[Word]:
    """Fix what the recogniser mis-hears, without touching the timings.

    Every recording has three or four of these: a product name, a library, the
    thing the whole video is about. "Vibe coding" comes back as "wipecoding",
    "white coding" and "Wipe Coding" in the same afternoon, and a caption that
    misspells the title is worse than no caption.

    Matching runs over n-grams longest-first so a two-word mishearing is caught
    before either of its halves. A replacement spanning several words divides
    the original span between them by length, which is wrong in the way that
    nobody can see and right in the way that matters: the words stay inside the
    time their sound occupies, so no caption arrives before it is said.
    """
    if not mapping:
        return words
    lookup = {tuple(normalise(w) for w in k.split()): v for k, v in mapping.items()}
    longest = max((len(k) for k in lookup), default=1)

    out: list[Word] = []
    i = 0
    while i < len(words):
        for size in range(min(longest, len(words) - i), 0, -1):
            key = tuple(words[i + j].key for j in range(size))
            if key in lookup:
                span = words[i:i + size]
                out += _respan(lookup[key], span[0].start, span[-1].end,
                               min(w.probability for w in span))
                i += size
                break
        else:
            out.append(words[i])
            i += 1
    return out


def _respan(text: str, start: float, end: float, probability: float) -> list[Word]:
    pieces = text.split()
    if len(pieces) == 1:
        return [Word(text=pieces[0], start=start, end=end, probability=probability)]
    total = sum(len(p) for p in pieces)
    out, at = [], start
    for piece in pieces:
        share = (end - start) * len(piece) / total
        out.append(Word(text=piece, start=round(at, 3), end=round(at + share, 3),
                        probability=probability))
        at += share
    return out


def fingerprint(path: Path) -> str:
    stat = path.stat()
    return f"{MODEL}:r{REVISION}:{stat.st_size}:{int(stat.st_mtime)}"


def audio_of(video: Path, out: Path) -> Path:
    """16k mono, which is what whisper resamples to anyway.

    Doing it here rather than letting whisper shell out means one predictable
    ffmpeg invocation instead of one that depends on what is on PATH inside
    whatever venv is running.
    """
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(video),
         "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(out)],
        check=True)
    return out


def transcribe(video: Path, out: Path, model: str = MODEL,
               cache: bool = True) -> Transcript:
    """One source video in, one transcript out."""
    stamp = fingerprint(video)
    if cache and out.exists():
        try:
            existing = json.loads(out.read_text(encoding="utf-8"))
            if existing.get("fingerprint") == stamp:
                print(f"  {video.name:<32} cached")
                return Transcript.load(out)
        except (json.JSONDecodeError, KeyError, TypeError):
            pass

    import torch
    import whisper

    device = "cuda" if torch.cuda.is_available() else "cpu"
    loaded = _model(model, device)

    wav = out.with_suffix(".wav")
    audio_of(video, wav)
    result = loaded.transcribe(
        str(wav), word_timestamps=True, language="en", fp16=(device == "cuda"),
        # A low temperature with fallbacks: greedy decoding is both faster and
        # less inclined to invent a sentence over a pause, and a recording with
        # long thinking gaps gives it plenty of chances to.
        temperature=(0.0, 0.2, 0.4),
        condition_on_previous_text=False,
    )
    wav.unlink(missing_ok=True)

    words: list[Word] = []
    for segment in result.get("segments", []):
        for w in segment.get("words", []):
            text = w["word"].strip()
            if not text:
                continue
            words.append(Word(text=text, start=round(float(w["start"]), 3),
                              end=round(float(w["end"]), 3),
                              probability=round(float(w.get("probability", 1.0)), 3)))

    before = len(words)
    words = refine(words, video, model, scratch=out.parent)
    if len(words) != before:
        print(f"  {video.name:<32} refined {len(words) - before:+d} words "
              "from collapsed stretches")

    transcript = Transcript(
        source=str(video), duration=_duration(video),
        language=result.get("language", "en"),
        text=" ".join(w.text.strip() for w in words).strip(), words=words)
    transcript.save(out, stamp)
    print(f"  {video.name:<32} {len(words):4d} words  {transcript.duration:6.1f}s")
    return transcript


_LOADED: dict[tuple[str, str], object] = {}


def _model(name: str, device: str):
    key = (name, device)
    if key in _LOADED:
        return _LOADED[key]
    import whisper
    print(f"  loading whisper {name} on {device} …")
    try:
        loaded = whisper.load_model(name, device=device)
    except (RuntimeError, MemoryError) as exc:  # not enough VRAM for large-v3
        if device != "cuda" or name == "medium.en":
            raise
        print(f"  {name} would not load ({exc.__class__.__name__}); falling back "
              "to medium.en")
        loaded = whisper.load_model("medium.en", device=device)
    _LOADED[key] = loaded
    return loaded


def _duration(path: Path) -> float:
    return float(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True, check=True).stdout.strip())


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="demoforge.transcribe", description=__doc__)
    ap.add_argument("--video", nargs="+", required=True)
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--model", default=MODEL)
    ap.add_argument("--no-cache", action="store_true")
    args = ap.parse_args(argv)

    outdir = Path(args.outdir)
    for path in args.video:
        source = Path(path)
        transcribe(source, outdir / f"{source.stem}.json", args.model,
                   cache=not args.no_cache)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
