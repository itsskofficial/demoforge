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

**Why sampling is also split in two.** The shot is generated at half size,
the latent upsampler doubles it, and four more steps refine the result. That
is cheaper than generating large, because attention cost grows with the square
of the token count and tokens grow with area -- and it is *better*, because the
upsampler is a trained 2x in latent space rather than a resize. Measured here,
one 4s vertical shot:

    base only     352x608     35s   3.8 GB
    + upsample    704x1216    36s   3.8 GB   sharp, but no new detail
    + refine x4   704x1216   240s   8.6 GB   detail in the texture

    python -m demoforge.broll encode --shots shots.json
    python -m demoforge.broll sample
    python -m demoforge.broll sample --no-refine     # preview, ~6x faster
    python -m demoforge.broll reel ltx-desk ltx-datagraph

`shots.json` is a list of `{"id", "prompt", "aspect", "seconds"}`. `aspect` is
one of `vertical`, `wide`, `square` and defaults to `wide`; `seconds` defaults
to 4 and is rounded to what the temporal VAE accepts. LTX wants long, prose,
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

from demoforge.config import MODELS as _MODELS, OUT

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

VIDEO = OUT / "video"
MODELS = _MODELS / "ltx"
CHECKPOINT = MODELS / "ltxv-2b-0.9.8-distilled.safetensors"
UPSCALER = _MODELS / "ltx-upscaler"
ENCODER_GGUF = "t5-v1_1-xxl-encoder-Q5_K_M.gguf"
EMBEDDINGS = MODELS / "prompts.pt"

# LTX's tokenizer comes from the base diffusers repo. The VAE and the scheduler
# deliberately do not -- see `load_pipeline`.
BASE_REPO = "Lightricks/LTX-Video"

# Base sizes, which the latent upsampler doubles. Every dimension here is
# divisible by 32 both before and after doubling, which the VAE requires.
#
# `vertical` is the one that matters. Generating wide and letterboxing it into
# a 9:16 frame -- which is what this did until the panel treatment in `reel`
# was the only option -- spends 60% of a reel on background. Asking for the
# shape the film actually wants costs the same tokens and fills the frame.
SIZES = {
    "vertical": (352, 608),     # -> 704 x 1216
    "wide": (704, 480),         # -> 1408 x 960
    "square": (480, 480),       # -> 960 x 960
}
FPS_OUT = 24
MAX_LEN = 128

# The sigma schedule the distilled checkpoint was trained to land on. A
# distilled model lands on a specific short list of timesteps; the scheduler's
# own linear-quadratic spacing is not that list, and puts the sampler
# somewhere the model has never been. It fails softly -- slightly mushy
# output, no error -- which is why it went unnoticed.
SIGMAS = [1.0000, 0.9937, 0.9875, 0.9812, 0.9750, 0.9094, 0.7250, 0.4219]

# Pass 2 re-noises the upscaled latent to REFINE[6] and walks it down from
# there. The first six entries are never sampled; they exist so that
# `denoise_strength` slices the list at the right index.
REFINE = [1.0, 0.95, 0.9, 0.8, 0.7, 0.6, 0.45, 0.33, 0.22, 0.11]
REFINE_STRENGTH = 0.4

NEGATIVE = ("worst quality, inconsistent motion, blurry, jittery, distorted, "
            "watermark, text, static image, deformed")

EXAMPLES = [
    {"id": "ltx-desk", "aspect": "vertical", "seconds": 4.0,
     "prompt": "A developer's desk at night lit only by a monitor. Steam rises "
               "gently from a ceramic coffee mug beside a mechanical keyboard. The "
               "camera drifts slowly to the right, revealing the warm glow across "
               "the desk surface. Shallow depth of field, cinematic lighting, high "
               "detail, film grain."},
    {"id": "ltx-datagraph", "aspect": "vertical", "seconds": 4.0,
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


def frames_for(seconds: float) -> int:
    """Frames for a duration, rounded to what the temporal VAE accepts.

    LTX compresses time 8:1, so a clip has to be `8k + 1` frames. Generating
    the section's own length matters more than it sounds: the old fixed 97
    frames meant `reel` retimed every cutaway to fit, and a 6.5s section over
    a 4s clip plays at 0.62x -- which is the entire reason generated B-roll
    reads as floaty.
    """
    want = max(1, round(seconds * FPS_OUT))
    # Rounded up, never down. A cutaway one frame longer than its section gets
    # trimmed; one frame shorter has to be retimed or held, and both of those
    # are the thing this exists to stop.
    return max(9, -(-(want - 1) // 8) * 8 + 1)


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
    # The whole shot dict is kept, not just the id: `sample` needs the aspect
    # and the duration, and requiring --shots on both phases is a good way to
    # sample a vertical shot at the wide size and not notice until the cut.
    torch.save({"shots": shots, "store": store}, out)
    print(f"  wrote {out}")
    return out


# ---------------------------------------------------------------------------
# phase 2: embeddings -> video
# ---------------------------------------------------------------------------


def load_pipeline():
    """Build the sampler and the latent upsampler over one set of weights.

    Three things here are load-bearing and each fails softly:

    **The VAE.** LTX changed its latent space after 0.9.0 and the diffusers
    `BASE_REPO` is still the 0.9.0 layout, so pairing that VAE with a 0.9.8
    transformer decodes noise -- silently, since nothing about the shapes
    disagrees. The Lightricks single-file checkpoints carry their own VAE (229
    `vae.*` tensors next to the `model.*` ones), so both are read from the one
    file and cannot drift apart.

    **The scheduler.** `BASE_REPO`'s has `use_dynamic_shifting`, under which an
    explicit sigma list is rejected outright. The distilled checkpoint wants
    exactly the list in `SIGMAS`, so the scheduler is constructed rather than
    inherited.

    **VAE tiling.** The refine pass decodes 97 frames at 704x1216 through a
    conv3d, which is around 6 GB of activations on its own and OOMs an 8 GB
    card before the transformer has asked for anything.

    The upsampler shares the sampler's VAE object, so the second model on the
    GPU costs 505 MB of weights and nothing else.
    """
    import torch
    from diffusers import (AutoencoderKLLTXVideo, FlowMatchEulerDiscreteScheduler,
                           LTXConditionPipeline, LTXLatentUpsamplePipeline,
                           LTXVideoTransformer3DModel)
    from diffusers.pipelines.ltx.modeling_latent_upsampler import (
        LTXLatentUpsamplerModel)

    dtype = torch.bfloat16
    transformer = LTXVideoTransformer3DModel.from_single_file(str(CHECKPOINT),
                                                              torch_dtype=dtype)
    vae = AutoencoderKLLTXVideo.from_single_file(str(CHECKPOINT), torch_dtype=dtype)
    scheduler = FlowMatchEulerDiscreteScheduler(use_dynamic_shifting=False, shift=1.0)
    pipe = LTXConditionPipeline.from_pretrained(
        BASE_REPO, transformer=transformer, vae=vae, scheduler=scheduler,
        text_encoder=None, tokenizer=None, torch_dtype=dtype)

    upsampler = None
    if UPSCALER.exists():
        upsampler = LTXLatentUpsamplePipeline(
            vae=vae,
            latent_upsampler=LTXLatentUpsamplerModel.from_pretrained(
                str(UPSCALER), subfolder="latent_upsampler", torch_dtype=dtype))
        upsampler.enable_model_cpu_offload()

    pipe.enable_model_cpu_offload()
    vae.enable_tiling()
    vae.enable_slicing()
    return pipe, upsampler


def sample(embeddings: Path = EMBEDDINGS, outdir: Path = VIDEO,
           shots: list[dict] | None = None, refine: bool = True) -> list[Path]:
    """Embeddings in, video out, in two passes.

    Pass 1 samples the base size in eight distilled steps. The latent
    upsampler then doubles both spatial dimensions *in latent space* -- a
    trained 2x, not a resize -- and pass 2 re-noises that to a middling sigma
    and walks it back down in four steps.

    The point of doing it this way rather than generating large directly is
    that attention cost is quadratic in token count, and tokens scale with
    area. Sampling at 352x608 and refining at 704x1216 costs roughly a third
    of what sampling at 704x1216 costs, and the refine pass only runs four
    steps instead of eight.
    """
    import torch
    from diffusers.utils import export_to_video

    blob = torch.load(embeddings)
    store = blob["store"]
    # Older embedding files hold bare ids; newer ones hold the shot dicts.
    saved = [s if isinstance(s, dict) else {"id": s} for s in blob["shots"]]
    spec = {s["id"]: s for s in saved}
    spec.update({s["id"]: s for s in (shots or [])})
    order = [s["id"] for s in saved]
    pipe, upsampler = load_pipeline()
    if refine and upsampler is None:
        print(f"  no upsampler at {UPSCALER}; sampling base size only")
        refine = False
    device, dtype = pipe._execution_device, torch.bfloat16
    print(f"  pipeline ready on {device} (no text encoder resident)")

    outdir.mkdir(parents=True, exist_ok=True)
    negative, negative_mask = store["neg"]
    written = []
    for name in order:
        shot = spec.get(name, {})
        width, height = SIZES.get(shot.get("aspect", "wide"), SIZES["wide"])
        count = frames_for(shot.get("seconds", 4.0))
        embedding, mask = store[name]
        common = dict(prompt_embeds=embedding.to(device, dtype),
                      prompt_attention_mask=mask.to(device),
                      negative_prompt_embeds=negative.to(device, dtype),
                      negative_prompt_attention_mask=negative_mask.to(device),
                      guidance_scale=1.0, num_frames=count)
        started = time.time()

        result = pipe(width=width, height=height,
                      timesteps=[s * 1000 for s in SIGMAS],
                      num_inference_steps=len(SIGMAS),
                      output_type="latent" if refine else "pil", **common)
        if refine:
            latents = upsampler(latents=result.frames, output_type="latent").frames
            frames = pipe(width=width * 2, height=height * 2, latents=latents,
                          timesteps=[s * 1000 for s in REFINE],
                          num_inference_steps=len(REFINE),
                          denoise_strength=REFINE_STRENGTH,
                          image_cond_noise_scale=0.025,
                          output_type="pil", **common).frames[0]
        else:
            frames = result.frames[0]

        path = outdir / f"{name}.mp4"
        export_to_video(frames, str(path), fps=FPS_OUT)
        peak = torch.cuda.max_memory_allocated() / 1024 ** 3
        print(f"  {name:<18} {frames[0].size[0]}x{frames[0].size[1]}  "
              f"{len(frames)} frames  {time.time() - started:5.0f}s  peak {peak:.1f} GB")
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
    sp.add_argument("--shots", type=Path, default=None,
                    help="same json as `encode`; only needed for an old "
                         "embeddings file that predates shot metadata")
    sp.add_argument("--no-refine", action="store_true",
                    help="skip the 2x upsample and refine pass -- roughly six "
                         "times faster, and a preview rather than a shot")

    sp = sub.add_parser("reel", help="cross-dissolve shots into one clip")
    sp.add_argument("names", nargs="+")
    sp.add_argument("--fade", type=float, default=0.7)

    args = ap.parse_args()
    if args.cmd == "encode":
        encode(load_shots(args.shots))
    elif args.cmd == "sample":
        if not EMBEDDINGS.exists():
            raise SystemExit("no embeddings; run `encode` first")
        sample(shots=load_shots(args.shots) if args.shots else None,
               refine=not args.no_refine)
    else:
        reel(args.names, fade=args.fade)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
