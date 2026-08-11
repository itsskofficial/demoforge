"""Clone a voice with Chatterbox and read a script in it.

Chatterbox is zero-shot: it wants one clean reference clip, roughly ten to
twenty seconds, and nothing else. Everything below is about giving it a good
one and then keeping long narration stable -- the model drifts if you hand it
a whole paragraph, so a script is spoken sentence-group by sentence-group and
reassembled with real pauses between them.

    python -m demoforge.voice prepare  --src "clip.mp3" --start 4 --dur 16
    python -m demoforge.voice say      --text "one line to hear it"
    python -m demoforge.voice script   --script script.json

The reference clip never leaves this machine, which is one of the reasons to
prefer a local model for a voice that belongs to a person.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

from demoforge.config import AUDIO, VOICE

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

REFERENCE = VOICE / "reference.wav"
SAMPLE_RATE = 24000

# Narration defaults, which are not the model's defaults. Chatterbox ships
# 0.5/0.5, which reads like an advert: fast, clipped, and pitched at someone
# who is about to scroll away. Three things fix that, and they work together:
#
#   cfg_weight   lower makes the model take its time. This is the real speed
#                control -- the model paces itself rather than being stretched.
#   exaggeration slightly higher carries more intent, but *speeds speech up*,
#                which is why it has to move opposite cfg_weight.
#   gap          silence between sentence groups. A person reading over a
#                screen recording pauses; a TTS model does not unless told.
#
# MAX_CHARS is deliberately short: chunk boundaries are where pauses land, so
# smaller groups mean more breathing without touching the audio itself.
MAX_CHARS = 180
EXAGGERATION = 0.5
CFG_WEIGHT = 0.3
GAP = 0.5
PACE = 0.94              # final pitch-preserving stretch; 1.0 leaves it alone


# ---------------------------------------------------------------------------
# reference preparation
# ---------------------------------------------------------------------------


def prepare(src: Path, out: Path = REFERENCE, start: float = 0.0,
            dur: float = 16.0, normalise: bool = True) -> Path:
    """Cut a clean mono reference out of whatever the phone recorded.

    Loudness is normalised because a quiet reference makes the clone breathy,
    and it is downmixed to mono at 24k because that is what the model works in.
    """
    out.parent.mkdir(parents=True, exist_ok=True)
    filters = ["highpass=f=60"]
    if normalise:
        filters.append("loudnorm=I=-20:TP=-2:LRA=7")
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-ss", str(start), "-t", str(dur),
         "-i", str(src), "-ac", "1", "-ar", str(SAMPLE_RATE),
         "-af", ",".join(filters), str(out)],
        check=True)
    print(f"  reference  {out}  ({dur:.0f}s from {start:.0f}s)")
    return out


def _stretch(path: Path, pace: float) -> float:
    """Slow a rendered clip without moving its pitch.

    This is the last resort of the three speed controls, not the first: it is
    applied after the model has already been asked to take its time, so the
    factor stays mild enough to be inaudible. Pushed hard it smears consonants.
    """
    tmp = path.with_suffix(".stretch.wav")
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(path),
         "-filter:a", f"atempo={pace:.4f}", str(tmp)],
        check=True)
    tmp.replace(path)
    return float(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True, check=True).stdout.strip())


def slow_reference(src: Path, dst: Path, pace: float = 0.9) -> Path:
    """Make a calmer reference clip.

    Chatterbox copies the *delivery* of the reference, speaking rate included,
    and a phone voice note is usually rushed. Slowing the reference asks the
    model for a calmer read rather than correcting a fast one afterwards.
    """
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(src),
         "-filter:a", f"atempo={pace:.4f}", "-ar", str(SAMPLE_RATE), "-ac", "1", str(dst)],
        check=True)
    return dst


# ---------------------------------------------------------------------------
# the model
# ---------------------------------------------------------------------------


# Chatterbox ships three models under one package. Which one you load matters
# more than any parameter on it:
#
#   english       the default. Trained predominantly on Western English, and it
#                 can flatten a non-Western accent while keeping the timbre.
#   multilingual  23 languages including Hindi, so Indian phonetics are in its
#                 representation space. The one to try when a clone sounds
#                 like the right person with the wrong accent.
#   turbo         faster, and the variant Resemble benchmarked against
#                 ElevenLabs.
MODELS = ("english", "multilingual", "turbo")


class Voice:
    """A loaded Chatterbox, plus the chunking that keeps long reads stable."""

    def __init__(self, reference: Path = REFERENCE, device: str | None = None,
                 model: str = "english", language: str = "en") -> None:
        import torch

        if not reference.exists():
            raise FileNotFoundError(f"no reference clip at {reference}; run `prepare` first")
        self.reference = reference
        self.kind = model
        self.language = language
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        started = time.time()
        if model == "multilingual":
            from chatterbox import ChatterboxMultilingualTTS as Model
        elif model == "turbo":
            from chatterbox.tts_turbo import ChatterboxTurboTTS as Model
        else:
            from chatterbox.tts import ChatterboxTTS as Model
        self.model = Model.from_pretrained(device=self.device)
        print(f"  chatterbox/{model} on {self.device}  "
              f"(loaded in {time.time() - started:.0f}s)")

    @staticmethod
    def chunk(text: str, max_chars: int = MAX_CHARS) -> list[str]:
        """Split on sentence ends, then regroup up to the length the model holds."""
        text = " ".join(text.split())
        sentences = re.split(r"(?<=[.!?])\s+", text)
        groups: list[str] = []
        for sentence in sentences:
            if groups and len(groups[-1]) + len(sentence) + 1 <= max_chars:
                groups[-1] = f"{groups[-1]} {sentence}"
            else:
                groups.append(sentence)
        return [g for g in groups if g.strip()]

    def say(self, text: str, out: Path, exaggeration: float = EXAGGERATION,
            cfg_weight: float = CFG_WEIGHT, gap: float = GAP,
            pace: float = PACE, max_chars: int = MAX_CHARS) -> float:
        """Speak `text` into `out`. Returns the duration in seconds."""
        import torch
        import torchaudio

        parts = self.chunk(text, max_chars)
        pieces = []
        silence = torch.zeros(1, int(gap * self.model.sr))
        for i, part in enumerate(parts):
            kwargs = dict(audio_prompt_path=str(self.reference),
                          exaggeration=exaggeration, cfg_weight=cfg_weight)
            if self.kind == "multilingual":
                kwargs["language_id"] = self.language
            wav = self.model.generate(part, **kwargs)
            pieces.append(wav.cpu())
            if i < len(parts) - 1:
                pieces.append(silence)
        audio = torch.cat(pieces, dim=1)
        out.parent.mkdir(parents=True, exist_ok=True)
        torchaudio.save(str(out), audio, self.model.sr)
        seconds = audio.shape[1] / self.model.sr
        if abs(pace - 1.0) > 0.001:
            seconds = _stretch(out, pace)
        print(f"  {out.name}  {seconds:.1f}s")
        return seconds


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("prepare", help="cut a reference clip from a recording")
    p.add_argument("--src", required=True)
    p.add_argument("--start", type=float, default=0.0)
    p.add_argument("--dur", type=float, default=16.0)
    p.add_argument("--out", default=str(REFERENCE))

    for name, helptext in (("say", "speak one piece of text"),
                           ("script", "speak a JSON script of {id, text} lines")):
        sp = sub.add_parser(name, help=helptext)
        sp.add_argument("--reference", default=str(REFERENCE))
        sp.add_argument("--exaggeration", type=float, default=EXAGGERATION,
                        help="emotional intensity; higher also speaks faster")
        sp.add_argument("--cfg-weight", type=float, default=CFG_WEIGHT,
                        help="lower makes the model take its time")
        sp.add_argument("--gap", type=float, default=GAP,
                        help="silence between sentence groups")
        sp.add_argument("--pace", type=float, default=PACE,
                        help="final pitch-preserving stretch; 1.0 leaves it alone")
        sp.add_argument("--max-chars", type=int, default=MAX_CHARS,
                        help="chunk size; smaller means more pauses")
        sp.add_argument("--model", default="english", choices=MODELS,
                        help="multilingual holds a non-Western accent better")
        sp.add_argument("--language", default="en", help="multilingual only")
        if name == "say":
            sp.add_argument("--text", required=True)
            sp.add_argument("--out", default=str(AUDIO / "sample.wav"))
        else:
            sp.add_argument("--script", required=True)
            sp.add_argument("--outdir", default=str(AUDIO))

    c = sub.add_parser("compare", help="same line through every model, to choose one")
    c.add_argument("--text", required=True)
    c.add_argument("--reference", default=str(REFERENCE))
    c.add_argument("--models", default=",".join(MODELS))
    c.add_argument("--outdir", default=str(AUDIO / "compare"))
    c.add_argument("--exaggeration", type=float, default=EXAGGERATION)
    c.add_argument("--cfg-weight", type=float, default=CFG_WEIGHT)
    c.add_argument("--pace", type=float, default=PACE)

    r = sub.add_parser("slow-ref", help="make a calmer reference clip")
    r.add_argument("--src", default=str(REFERENCE))
    r.add_argument("--out", required=True)
    r.add_argument("--pace", type=float, default=0.9)

    args = ap.parse_args()

    if args.cmd == "prepare":
        prepare(Path(args.src), Path(args.out), args.start, args.dur)
        return 0

    if args.cmd == "compare":
        # One sentence, every model, identical settings. Comparing across
        # different sentences is how you convince yourself of a difference that
        # is not there -- accent judgements need the same words.
        outdir = Path(args.outdir)
        outdir.mkdir(parents=True, exist_ok=True)
        words = len(args.text.split())
        for name in args.models.split(","):
            try:
                voice = Voice(Path(args.reference), model=name.strip())
            except Exception as exc:                       # noqa: BLE001
                print(f"  {name}: {type(exc).__name__}: {str(exc)[:80]}")
                continue
            seconds = voice.say(args.text, outdir / f"{name.strip()}.wav",
                                exaggeration=args.exaggeration,
                                cfg_weight=args.cfg_weight, pace=args.pace)
            print(f"    -> {words / seconds * 60:.0f} wpm")
        print(f"\n  {outdir}  - listen for accent first, pace second")
        return 0

    if args.cmd == "slow-ref":
        out = slow_reference(Path(args.src), Path(args.out), args.pace)
        print(f"  reference  {out}  (paced {args.pace})")
        return 0

    voice = Voice(Path(args.reference), model=args.model, language=args.language)
    knobs = dict(exaggeration=args.exaggeration, cfg_weight=args.cfg_weight,
                 gap=args.gap, pace=args.pace, max_chars=args.max_chars)

    if args.cmd == "say":
        voice.say(args.text, Path(args.out), **knobs)
        return 0

    lines = json.loads(Path(args.script).read_text(encoding="utf-8"))
    outdir = Path(args.outdir)
    manifest = []
    for line in lines:
        out = outdir / f"{line['id']}.wav"
        seconds = voice.say(line["text"], out, **knobs)
        manifest.append({"id": line["id"], "file": out.name, "seconds": round(seconds, 2),
                         "segment": line.get("segment"), "budget": line.get("budget")})
    (outdir / "narration.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    over = [m for m in manifest if m.get("budget") and m["seconds"] > m["budget"]]
    for m in over:
        print(f"  !! {m['id']} runs {m['seconds']:.1f}s against a {m['budget']}s segment")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
