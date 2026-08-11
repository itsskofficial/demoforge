"""IndexTTS-2 as an alternative narrator, behind the same interface as voice.py.

Worth a separate module because its architecture differs in the way that
matters: **timbre and emotion come from different inputs.** The speaker clip
says who you sound like; a separate emotion clip, an eight-value vector, or a
plain-English description says how energetic you are. In Chatterbox those are
entangled -- turning up `exaggeration` for energy also speeds and reshapes the
delivery -- which is why tuning one there costs you the other.

    python -m demoforge.indextts say --text "..." --emotion "energetic, confident"
    python -m demoforge.indextts script --script narration.json

No speed control is applied by default. This release has no `duration_factor`
(that is IndexTTS-2.5), so `--pace` is the same post-hoc stretch voice.py uses,
and it is left at 1.0 so the model's natural pacing can be measured before
anything is done about it.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

from demoforge.config import AUDIO, ROOT, VOICE

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

VENDOR = ROOT / "vendor" / "indextts"
PYTHON = ROOT / ".venv-indextts" / "Scripts" / "python.exe"
CHECKPOINTS = VENDOR / "checkpoints_2"
REFERENCE = VOICE / "reference.wav"

# The order the model expects. Documented here because a mis-ordered vector
# produces a confident, wrong emotion rather than an error.
EMOTIONS = ("happy", "angry", "sad", "afraid",
            "disgusted", "melancholic", "surprised", "calm")


def duration(path: Path) -> float:
    return float(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True, check=True).stdout.strip())


def _use_soundfile_for_saving() -> None:
    """Write wavs with soundfile instead of torchaudio's new backend.

    torchaudio 2.11 routes `save` through TorchCodec, whose native library
    wants FFmpeg's *shared* libraries -- having `ffmpeg.exe` on PATH is not
    enough, and on Windows it fails to load its own DLL. IndexTTS was written
    against torchaudio 2.8, where `save` still had a working backend of its own.

    This is the cost of reusing the machine's torch instead of the pinned one,
    and it is a cheap cost: soundfile is already present and writes the same
    PCM. Patched before IndexTTS imports so its module-level `torchaudio.save`
    reference picks up the replacement.
    """
    import soundfile as sf
    import torchaudio

    def save(uri, src, sample_rate, **_kwargs):
        data = src.detach().cpu()
        if data.ndim == 2:
            data = data.T                      # torchaudio is (channels, samples)
        sf.write(str(uri), data.numpy(), int(sample_rate))

    torchaudio.save = save


class Voice:
    """A loaded IndexTTS-2, with the same `say` shape as demoforge.voice.Voice."""

    def __init__(self, reference: Path = REFERENCE, device: str | None = None) -> None:
        sys.path.insert(0, str(VENDOR))
        _use_soundfile_for_saving()
        from indextts.infer_v2 import IndexTTS2

        if not reference.exists():
            raise FileNotFoundError(f"no reference clip at {reference}")
        if not (CHECKPOINTS / "config.yaml").exists():
            raise SystemExit(f"no checkpoints at {CHECKPOINTS}")
        self.reference = reference
        started = time.time()
        self.model = IndexTTS2(
            cfg_path=str(CHECKPOINTS / "config.yaml"),
            model_dir=str(CHECKPOINTS),
            use_fp16=True,          # half the VRAM, negligible quality cost
            use_deepspeed=False,    # awkward to install on Windows, optional anyway
            use_cuda_kernel=False,
        )
        print(f"  indextts-2  (loaded in {time.time() - started:.0f}s)")

    def say(self, text: str, out: Path, emotion: str | None = None,
            emo_vector: list[float] | None = None, emo_alpha: float = 1.0,
            pace: float = 1.0, interval_silence: int = 200) -> float:
        """Speak `text` into `out`. Returns seconds.

        `emotion` is a plain-English description handed to the model, which is
        the cheapest way to ask for energy without touching the voice itself.
        """
        out.parent.mkdir(parents=True, exist_ok=True)
        kwargs: dict = {"interval_silence": interval_silence}
        if emo_vector:
            kwargs["emo_vector"] = emo_vector
            kwargs["emo_alpha"] = emo_alpha
        elif emotion:
            kwargs["use_emo_text"] = True
            kwargs["emo_text"] = emotion
            kwargs["emo_alpha"] = emo_alpha

        self.model.infer(spk_audio_prompt=str(self.reference), text=text,
                         output_path=str(out), **kwargs)

        if abs(pace - 1.0) > 0.001:
            tmp = out.with_suffix(".s.wav")
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(out),
                            "-filter:a", f"atempo={pace:.4f}", str(tmp)], check=True)
            tmp.replace(out)
        seconds = duration(out)
        print(f"  {out.name}  {seconds:.1f}s  ({len(text.split()) / seconds * 60:.0f} wpm)")
        return seconds


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("say", "script"):
        sp = sub.add_parser(name)
        sp.add_argument("--reference", default=str(REFERENCE))
        sp.add_argument("--emotion", default=None,
                        help='plain English, e.g. "energetic and confident"')
        sp.add_argument("--emo-alpha", type=float, default=1.0)
        sp.add_argument("--pace", type=float, default=1.0,
                        help="post-hoc stretch; 1.0 leaves the model's own pacing alone")
        sp.add_argument("--outdir", default=str(AUDIO / "indextts"))
        if name == "say":
            sp.add_argument("--text", required=True)
            sp.add_argument("--out", default=None)
        else:
            sp.add_argument("--script", required=True)

    args = ap.parse_args()
    outdir = Path(args.outdir)
    voice = Voice(Path(args.reference))

    if args.cmd == "say":
        out = Path(args.out) if args.out else outdir / "sample.wav"
        voice.say(args.text, out, emotion=args.emotion, emo_alpha=args.emo_alpha,
                  pace=args.pace)
        return 0

    lines = json.loads(Path(args.script).read_text(encoding="utf-8"))
    manifest = []
    for line in lines:
        out = outdir / f"{line['id']}.wav"
        seconds = voice.say(line["text"], out, emotion=args.emotion,
                            emo_alpha=args.emo_alpha, pace=args.pace)
        manifest.append({"id": line["id"], "file": out.name,
                         "seconds": round(seconds, 2), "segment": line["id"]})
    (outdir / "narration.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
