"""Read and write wavs with soundfile instead of torchaudio's TorchCodec backend.

torchaudio 2.11 routes both `load` and `save` through TorchCodec, whose native
library wants FFmpeg's *shared* libraries -- having `ffmpeg.exe` on PATH is not
enough, and on Windows it fails to load its own DLL. Every speech model here
was written against an older torchaudio where both had working backends of
their own, so they all hit this the moment they share one modern torch.

This is the standing cost of one torch for the whole machine rather than a
pinned copy per model, and it is a cheap one: soundfile is already a dependency
of every voice stack here and handles the same PCM.

Call before importing any model code, so its module-level `torchaudio.load` and
`torchaudio.save` references pick up the replacements.
"""

from __future__ import annotations

_PATCHED = False


def use_soundfile_for_saving() -> None:
    """Patch torchaudio's file I/O. Idempotent."""
    global _PATCHED
    if _PATCHED:
        return
    import soundfile as sf
    import torch
    import torchaudio

    def save(uri, src, sample_rate, **_kwargs):
        data = src.detach().cpu()
        if data.ndim == 2:
            data = data.T                     # torchaudio is (channels, samples)
        sf.write(str(uri), data.numpy(), int(sample_rate))

    def load(uri, frame_offset: int = 0, num_frames: int = -1,
             normalize: bool = True, channels_first: bool = True, **_kwargs):
        data, rate = sf.read(
            str(uri), dtype="float32", always_2d=True,
            start=frame_offset, frames=num_frames if num_frames > 0 else -1)
        tensor = torch.from_numpy(data.T.copy() if channels_first else data.copy())
        return tensor, rate

    torchaudio.save = save
    torchaudio.load = load
    _PATCHED = True
