"""Generated B-roll: text prompts in, short cinematic shots out.

Screen recordings carry the argument of a demo; B-roll carries its mood, and
stock footage is both expensive and instantly recognisable. These shots are
generated locally instead.

**Why LTX and not the obvious names.** Measured on an RTX 4060 Laptop (8 GB
VRAM, 15.3 GB system RAM), same prompts, same machine:

    CogVideoX-2B         3.1s clip   ~600s   3.8 GB   soft, mushy motion
    Wan2.1-1.3B (gguf)   3.1s clip   ~500s   5.5 GB   good hands, very dark
    LTX 2B-distilled     4.0s clip    ~65s   5.4 GB   photographic

LTX is distilled to land in 8 denoising steps rather than 25-30, so it is
roughly eight times cheaper *and* looks better. Mochi never enters the running:
20 GB VRAM at fp8, with a 12 GB floor.

**Why generation is split in two.** Every guide for low-VRAM video says to
offload the text encoder to CPU. On this class of machine that is exactly
backwards -- the binding constraint is system RAM, not the GPU, and t5-xxl is
~9.5 GB of it. Quantisation does not help either: transformers dequantises a
GGUF encoder back to the compute dtype on load, so the 3 GB file still costs
9.5 GB resident.

What does help is noticing the encoder is not needed *at the same time* as the
transformer. Prompts are known up front, so `encode` embeds them all and exits,
and `sample` loads into a machine where that memory has been returned. Peak
usage becomes the larger phase instead of the sum.

    python -m demoforge.broll encode --shots shots.json
    python -m demoforge.broll sample
    python -m demoforge.broll reel ltx-desk ltx-datagraph

`shots.json` is a list of `{"id": ..., "prompt": ...}`. LTX wants long, prose,
chronological prompts describing action and camera; terse ones underperform
badly, so the bundled examples are verbose on purpose.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

from demoforge.config import OUT

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

VIDEO = OUT / "video"
MODELS = Path("E:/ai-models/ltx")
CHECKPOINT = MODELS / "ltxv-2b-0.9.8-distilled.safetensors"
ENCODER_GGUF = "t5-v1_1-xxl-encoder-Q5_K_M.gguf"
EMBEDDINGS = MODELS / "prompts.pt"

# LTX's tokenizer and scheduler config come from the base diffusers repo. The
# VAE deliberately does not -- see `load_pipeline`.
BASE_REPO = "Lightricks/LTX-Video"

WIDTH, HEIGHT, FRAMES, FPS_OUT = 704, 480, 97, 24
STEPS = 8
MAX_LEN = 128

NEGATIVE = ("worst quality, inconsistent motion, blurry, jittery, distorted, "
            "watermark, text, static image, deformed")

EXAMPLES = [
    {"id": "ltx-desk",
     "prompt": "A developer's desk at night lit only by a monitor. Steam rises "
               "gently from a ceramic coffee mug beside a mechanical keyboard. The "
               "camera drifts slowly to the right, revealing the warm glow across "
               "the desk surface. Shallow depth of field, cinematic lighting, high "
               "detail, film grain."},
    {"id": "ltx-datagraph",
     "prompt": "A glowing line chart climbs steadily across a dark computer monitor "
               "in a dim room. The line is bright cyan against deep blue grid lines. "
               "The camera pushes in slowly and smoothly toward the screen. Soft "
               "bloom around the bright pixels, shallow depth of field, cinematic "
               "lighting, high detail, film grain."},
]


def load_shots(path: Path | None) -> list[dict]:
    if path is None:
        return EXAMPLES
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# phase 1: prompts -> embeddings
# ---------------------------------------------------------------------------


def encode(shots: list[dict], out: Path = EMBEDDINGS) -> Path:
    """Embed every prompt, write the tensors, and let the process exit."""
    import torch
    from transformers import AutoTokenizer, T5EncoderModel

    tokenizer = AutoTokenizer.from_pretrained(BASE_REPO, subfolder="tokenizer")
    encoder = T5EncoderModel.from_pretrained(
        str(MODELS), gguf_file=ENCODER_GGUF, torch_dtype=torch.bfloat16).eval()
    print("  t5 encoder loaded")

    def embed(text: str):
        """LTX keeps the padding and hands the mask to the DiT, unlike Wan."""
        batch = tokenizer([text], padding="max_length", max_length=MAX_LEN,
                          truncation=True, add_special_tokens=True,
                          return_attention_mask=True, return_tensors="pt")
        with torch.no_grad():
            hidden = encoder(batch.input_ids, attention_mask=batch.attention_mask
                             ).last_hidden_state.to(torch.bfloat16)
        return hidden, batch.attention_mask

    store = {"neg": embed(NEGATIVE)}
    for shot in shots:
        store[shot["id"]] = embed(shot["prompt"])
        print(f"  embedded {shot['id']}")
    out.parent.mkdir(parents=True, exist_ok=True)
    torch.save({"shots": [s["id"] for s in shots], "store": store}, out)
    print(f"  wrote {out}")
    return out


# ---------------------------------------------------------------------------
# phase 2: embeddings -> video
# ---------------------------------------------------------------------------


def load_pipeline():
    """Build the pipeline with a VAE that matches the transformer.

    LTX changed its latent space after 0.9.0 and the diffusers `BASE_REPO` is
    still the 0.9.0 layout, so pairing that VAE with a 0.9.8 transformer decodes
    noise -- silently, since nothing about the shapes disagrees. The Lightricks
    single-file checkpoints carry their own VAE (229 `vae.*` tensors next to the
    `model.*` ones), so both are read from the one file and cannot drift apart.
    """
    import torch
    from diffusers import AutoencoderKLLTXVideo, LTXPipeline, LTXVideoTransformer3DModel

    dtype = torch.bfloat16
    transformer = LTXVideoTransformer3DModel.from_single_file(str(CHECKPOINT),
                                                              torch_dtype=dtype)
    vae = AutoencoderKLLTXVideo.from_single_file(str(CHECKPOINT), torch_dtype=dtype)
    pipe = LTXPipeline.from_pretrained(BASE_REPO, transformer=transformer, vae=vae,
                                       text_encoder=None, tokenizer=None,
                                       torch_dtype=dtype)
    pipe.enable_model_cpu_offload()
    return pipe


def sample(embeddings: Path = EMBEDDINGS, outdir: Path = VIDEO,
           steps: int = STEPS) -> list[Path]:
    import torch
    from diffusers.utils import export_to_video

    blob = torch.load(embeddings)
    store, shots = blob["store"], blob["shots"]
    pipe = load_pipeline()
    device, dtype = pipe._execution_device, torch.bfloat16
    print(f"  pipeline ready on {device} (no text encoder resident)")

    outdir.mkdir(parents=True, exist_ok=True)
    negative, negative_mask = store["neg"]
    written = []
    for name in shots:
        embedding, mask = store[name]
        started = time.time()
        frames = pipe(prompt_embeds=embedding.to(device, dtype),
                      prompt_attention_mask=mask.to(device),
                      negative_prompt_embeds=negative.to(device, dtype),
                      negative_prompt_attention_mask=negative_mask.to(device),
                      width=WIDTH, height=HEIGHT, num_frames=FRAMES,
                      num_inference_steps=steps, guidance_scale=1.0).frames[0]
        path = outdir / f"{name}.mp4"
        export_to_video(frames, str(path), fps=FPS_OUT)
        peak = torch.cuda.max_memory_allocated() / 1024 ** 3
        print(f"  {name:<18} {len(frames)} frames  {time.time() - started:5.0f}s  "
              f"peak {peak:.1f} GB")
        torch.cuda.reset_peak_memory_stats()
        written.append(path)
    return written


# ---------------------------------------------------------------------------
# assembly
# ---------------------------------------------------------------------------


def duration(path: Path) -> float:
    return float(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True, check=True).stdout.strip())


def reel(names: list[str], outdir: Path = VIDEO, fade: float = 0.7,
         out: Path | None = None) -> Path:
    """Cross-dissolve shots into one clip at the project canvas size.

    Shots come from different generators at different sizes and frame rates, so
    each is normalised first -- concat and xfade both refuse mismatched streams.
    Normalisation crops to fill rather than padding: these generators emit square
    and 3:2 frames, and pillarbox bars between shots read as a mistake, whereas a
    tighter crop on atmospheric footage costs nothing anyone will notice.
    """
    from demoforge.config import HEIGHT as CANVAS_H, WIDTH as CANVAS_W

    shots = [outdir / f"{n}.mp4" for n in names]
    missing = [s.name for s in shots if not s.exists()]
    if missing:
        raise SystemExit(f"no such shots: {', '.join(missing)}")
    out = out or outdir / "broll-reel.mp4"

    scratch = []
    for i, shot in enumerate(shots):
        norm = outdir / f"_norm{i}.mp4"
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", str(shot), "-vf",
             f"scale={CANVAS_W}:{CANVAS_H}:force_original_aspect_ratio=increase,"
             f"crop={CANVAS_W}:{CANVAS_H},fps={FPS_OUT},format=yuv420p",
             "-c:v", "libx264", "-crf", "18", "-preset", "medium", str(norm)],
            check=True)
        scratch.append(norm)

    # xfade joins two inputs at a time, and each link needs the running length
    # of everything already joined -- not the length of the incoming shot.
    current, total = scratch[0], duration(scratch[0])
    for i, nxt in enumerate(scratch[1:], start=1):
        step = outdir / f"_xfade{i}.mp4"
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", str(current), "-i", str(nxt),
             "-filter_complex",
             f"[0][1]xfade=transition=fade:duration={fade}:"
             f"offset={max(0.0, total - fade)}",
             "-c:v", "libx264", "-crf", "18", "-preset", "medium", str(step)],
            check=True)
        scratch.append(step)
        current, total = step, duration(step)

    out.write_bytes(current.read_bytes())
    for path in scratch:
        path.unlink(missing_ok=True)
    print(f"  {out.name}  {total:.1f}s  {len(shots)} shots")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("encode", help="prompts -> embeddings, then exit")
    sp.add_argument("--shots", type=Path, default=None,
                    help="json list of {id, prompt}; omit for the bundled examples")

    sp = sub.add_parser("sample", help="embeddings -> video")
    sp.add_argument("--steps", type=int, default=STEPS)

    sp = sub.add_parser("reel", help="cross-dissolve shots into one clip")
    sp.add_argument("names", nargs="+")
    sp.add_argument("--fade", type=float, default=0.7)

    args = ap.parse_args()
    if args.cmd == "encode":
        encode(load_shots(args.shots))
    elif args.cmd == "sample":
        if not EMBEDDINGS.exists():
            raise SystemExit("no embeddings; run `encode` first")
        sample(steps=args.steps)
    else:
        reel(args.names, fade=args.fade)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
