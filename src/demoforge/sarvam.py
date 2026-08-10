"""Sarvam Bulbul as an alternative narrator, behind the same interface as voice.py.

Deliberately the same shape as `demoforge.voice`: `say` writes a wav and
returns its length, `script` writes `narration.json`. That means
`demoforge.assemble` does not know or care which engine spoke the lines, and
switching is a one-word change rather than a rewrite.

Bulbul is a hosted API, so unlike Chatterbox the text and the resulting audio
leave the machine. It is also a *curated* voice rather than yours, unless a
voice has been cloned in Sarvam's dashboard first -- which is a browser flow
with a consent step, and is not something this file can or should do for you.

    python -m demoforge.sarvam voices
    python -m demoforge.sarvam say --text "..." --speaker anand --pace 0.9
    python -m demoforge.sarvam script --script projects/livingeval/narration.json

The key is read from SARVAM_API_KEY, or from a .env beside the repo root. It is
never logged, and it is not a command-line argument on purpose: arguments end
up in shell history.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

from demoforge.config import AUDIO, ROOT

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

ENDPOINT = "https://api.sarvam.ai/text-to-speech"
MODEL = "bulbul:v3"
LANGUAGE = "en-IN"
MAX_CHARS = 1400          # v3 allows 2500; shorter keeps prosody per sentence group
PACE = 0.85               # Bulbul reads briskly by default, like most TTS

# A starting set to audition. Sarvam lists 30+; these are the ones worth
# hearing first for a male technical narration in Indian English.
SPEAKERS = ["shubh", "aditya", "anand", "rahul", "rohan", "amit", "dev", "karun", "vijay"]


def api_key() -> str:
    key = os.environ.get("SARVAM_API_KEY", "").strip()
    if not key:
        env = ROOT / ".env"
        if env.exists():
            for line in env.read_text(encoding="utf-8").splitlines():
                if line.strip().startswith("SARVAM_API_KEY"):
                    key = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break
    if not key:
        raise SystemExit(
            "no SARVAM_API_KEY.\n"
            f"  put it in {ROOT / '.env'} as   SARVAM_API_KEY=...\n"
            "  (that file is gitignored; do not paste the key into a shell command)")
    return key


def chunk(text: str, max_chars: int = MAX_CHARS) -> list[str]:
    text = " ".join(text.split())
    sentences = re.split(r"(?<=[.!?])\s+", text)
    groups: list[str] = []
    for sentence in sentences:
        if groups and len(groups[-1]) + len(sentence) + 1 <= max_chars:
            groups[-1] = f"{groups[-1]} {sentence}"
        else:
            groups.append(sentence)
    return [g for g in groups if g.strip()]


def _request(text: str, speaker: str, pace: float, model: str, language: str,
             sample_rate: int, key: str) -> bytes:
    body = json.dumps({
        "text": text,
        "target_language_code": language,
        "language_code": language,
        "model": model,
        "speaker": speaker,
        "pace": pace,
        "speech_sample_rate": sample_rate,
    }).encode("utf-8")
    req = urllib.request.Request(
        ENDPOINT, data=body,
        headers={"api-subscription-key": key, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            payload = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:400]
        raise SystemExit(f"sarvam {exc.code}: {detail}") from exc
    audios = payload.get("audios") or payload.get("audio")
    if not audios:
        raise SystemExit(f"unexpected response: {str(payload)[:300]}")
    return base64.b64decode(audios[0] if isinstance(audios, list) else audios)


def say(text: str, out: Path, speaker: str = "anand", pace: float = PACE,
        model: str = MODEL, language: str = LANGUAGE, sample_rate: int = 24000,
        gap: float = 0.45) -> float:
    """Speak `text` into `out`, one request per sentence group. Returns seconds."""
    key = api_key()
    out.parent.mkdir(parents=True, exist_ok=True)
    parts = chunk(text)
    pieces = []
    for i, part in enumerate(parts):
        raw = _request(part, speaker, pace, model, language, sample_rate, key)
        piece = out.with_suffix(f".part{i}.wav")
        piece.write_bytes(raw)
        pieces.append(piece)

    if len(pieces) == 1:
        pieces[0].replace(out)
    else:
        # Concatenate with a real pause between groups, the same way the local
        # engine does, so the two sound like the same edit.
        listing = out.with_suffix(".parts.txt")
        silence = out.with_suffix(".silence.wav")
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
             "-i", f"anullsrc=r={sample_rate}:cl=mono", "-t", f"{gap}", str(silence)],
            check=True)
        entries = []
        for piece in pieces:
            entries.append(f"file '{piece.as_posix()}'")
            entries.append(f"file '{silence.as_posix()}'")
        listing.write_text("\n".join(entries[:-1]) + "\n", encoding="utf-8")
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
             "-i", str(listing), "-ar", str(sample_rate), "-ac", "1", str(out)],
            check=True)
        for path in pieces + [listing, silence]:
            path.unlink(missing_ok=True)

    seconds = float(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(out)],
        capture_output=True, text=True, check=True).stdout.strip())
    words = len(text.split())
    print(f"  {out.name}  {seconds:.1f}s  ({words / seconds * 60:.0f} wpm)")
    return seconds


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("voices", help="list the speakers worth auditioning")

    for name in ("say", "script", "audition"):
        sp = sub.add_parser(name)
        sp.add_argument("--speaker", default="anand")
        sp.add_argument("--pace", type=float, default=PACE)
        sp.add_argument("--model", default=MODEL)
        sp.add_argument("--language", default=LANGUAGE)
        sp.add_argument("--sample-rate", type=int, default=24000)
        sp.add_argument("--outdir", default=str(AUDIO))
        if name == "script":
            sp.add_argument("--script", required=True)
        else:
            sp.add_argument("--text", required=True)

    args = ap.parse_args()

    if args.cmd == "voices":
        print("  " + "  ".join(SPEAKERS))
        print("\n  audition them all with:  python -m demoforge.sarvam audition --text '...'")
        return 0

    outdir = Path(args.outdir)

    common = dict(pace=args.pace, model=args.model, language=args.language,
                  sample_rate=args.sample_rate)

    if args.cmd == "audition":
        for speaker in SPEAKERS:
            try:
                say(args.text, outdir / f"sarvam-{speaker}.wav", speaker=speaker, **common)
            except SystemExit as exc:
                print(f"  {speaker}: {exc}")
        return 0

    if args.cmd == "say":
        say(args.text, outdir / f"sarvam-{args.speaker}.wav", speaker=args.speaker, **common)
        return 0

    lines = json.loads(Path(args.script).read_text(encoding="utf-8"))
    manifest = []
    for line in lines:
        out = outdir / f"{line['id']}.wav"
        seconds = say(line["text"], out, speaker=args.speaker, **common)
        manifest.append({"id": line["id"], "file": out.name, "seconds": round(seconds, 2),
                         "segment": line.get("segment"), "budget": line.get("budget")})
    (outdir / "narration.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
