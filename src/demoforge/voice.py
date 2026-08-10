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
MAX_CHARS = 280          # past this Chatterbox starts losing the thread


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


# ---------------------------------------------------------------------------
# the model
# ---------------------------------------------------------------------------


class Voice:
    """A loaded Chatterbox, plus the chunking that keeps long reads stable."""

    def __init__(self, reference: Path = REFERENCE, device: str | None = None) -> None:
        import torch
        from chatterbox.tts import ChatterboxTTS

        if not reference.exists():
            raise FileNotFoundError(f"no reference clip at {reference}; run `prepare` first")
        self.reference = reference
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        started = time.time()
        self.model = ChatterboxTTS.from_pretrained(device=self.device)
        print(f"  chatterbox on {self.device}  (loaded in {time.time() - started:.0f}s)")

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

    def say(self, text: str, out: Path, exaggeration: float = 0.4,
            cfg_weight: float = 0.4, gap: float = 0.32) -> float:
        """Speak `text` into `out`. Returns the duration in seconds.

        The defaults are set for narration rather than performance: Chatterbox's
        stock 0.5/0.5 reads like an advert, which is wrong over a screen
        recording of a terminal.
        """
        import torch
        import torchaudio

        parts = self.chunk(text)
        pieces = []
        silence = torch.zeros(1, int(gap * self.model.sr))
        for i, part in enumerate(parts):
            wav = self.model.generate(
                part,
                audio_prompt_path=str(self.reference),
                exaggeration=exaggeration,
                cfg_weight=cfg_weight,
            )
            pieces.append(wav.cpu())
            if i < len(parts) - 1:
                pieces.append(silence)
        audio = torch.cat(pieces, dim=1)
        out.parent.mkdir(parents=True, exist_ok=True)
        torchaudio.save(str(out), audio, self.model.sr)
        seconds = audio.shape[1] / self.model.sr
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

    s = sub.add_parser("say", help="speak one piece of text")
    s.add_argument("--text", required=True)
    s.add_argument("--out", default=str(AUDIO / "sample.wav"))
    s.add_argument("--reference", default=str(REFERENCE))
    s.add_argument("--exaggeration", type=float, default=0.4)
    s.add_argument("--cfg-weight", type=float, default=0.4)

    c = sub.add_parser("script", help="speak a JSON script of {id, text} lines")
    c.add_argument("--script", required=True)
    c.add_argument("--outdir", default=str(AUDIO))
    c.add_argument("--reference", default=str(REFERENCE))
    c.add_argument("--exaggeration", type=float, default=0.4)
    c.add_argument("--cfg-weight", type=float, default=0.4)

    args = ap.parse_args()

    if args.cmd == "prepare":
        prepare(Path(args.src), Path(args.out), args.start, args.dur)
        return 0

    voice = Voice(Path(args.reference))

    if args.cmd == "say":
        voice.say(args.text, Path(args.out), args.exaggeration, args.cfg_weight)
        return 0

    lines = json.loads(Path(args.script).read_text(encoding="utf-8"))
    outdir = Path(args.outdir)
    manifest = []
    for line in lines:
        out = outdir / f"{line['id']}.wav"
        seconds = voice.say(line["text"], out, args.exaggeration, args.cfg_weight)
        manifest.append({"id": line["id"], "file": out.name, "seconds": round(seconds, 2),
                         "segment": line.get("segment"), "budget": line.get("budget")})
    (outdir / "narration.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    over = [m for m in manifest if m.get("budget") and m["seconds"] > m["budget"]]
    for m in over:
        print(f"  !! {m['id']} runs {m['seconds']:.1f}s against a {m['budget']}s segment")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
