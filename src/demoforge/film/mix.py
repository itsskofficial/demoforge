"""The final sound: voice, ducked music, every scene's SFX and a sound on every join.

Writes assets/audio/mix.wav, the root composition's only audio, plus the SFX
bus as a stem in the work folder for checking. The levels are how the film's
mixes were judged: the voice always wins; the music is clearly present (about
8 dB under the voice in the gaps, never a timid bed) and ducks under speech;
the SFX hit hard but are compressed and ducked under the words.

SFX come from two places:

    scenes/<id>/sfx.json   [{"t": scene seconds, "sfx": name, "gain": dB}]
    transitions.json       a spec per join kind: [name, offset, gain], or a
                           list of them. An offset of null lines the sound's
                           loudest moment (`peak_at` in assets/sfx/manifest.json)
                           up with the cut, which is where a whoosh belongs.

Chain: voice + music (-8 dB, sidechain-ducked) + SFX (compressed, ducked)
-> limiter -> loudnorm -14 LUFS, true peak -1.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import numpy as np

from demoforge.film.project import Project, load_audio, read_json, save_audio


def specs(spec) -> list:
    """A transition's sound: one [name, offset, gain] or a list of them."""
    return spec if spec and isinstance(spec[0], list) else [spec]


def placements(scenes: list[dict], scene_cues: dict[str, list[dict]], joins: list[dict],
               sfx: dict, manifest: dict, default_gain: float = -6) -> list[tuple[str, float, float]]:
    """(name, film time, gain dB) for every sound, in the order they are laid."""
    out = []
    for sc in scenes:
        for c in scene_cues.get(sc["id"], []):
            out.append((c["sfx"], sc["start"] + float(c["t"]), float(c.get("gain", default_gain))))
    for j in joins:
        if j["kind"] not in sfx:
            continue
        for name, offset, gain in specs(sfx[j["kind"]]):
            if name not in manifest:
                continue
            t = j["t"] + (offset if offset is not None else -manifest[name]["peak_at"])
            out.append((name, t, gain))
    return out


def lay(bus: np.ndarray, sound: np.ndarray, t: float, gain_db: float, sr: int) -> None:
    """Add a sound into the bus at t; anything before 0 or after the end is cut off."""
    s = sound * (10 ** (gain_db / 20))
    i = int(round(t * sr))
    if i < 0:
        s, i = s[-i:], 0
    j = min(len(bus), i + len(s))
    if j > i:
        bus[i:j] += s[: j - i]


def build(p: Project) -> Path:
    tl = p.timeline()
    total, sr = tl["duration"], p.sr
    sfx_dir = p.film / "assets" / "sfx"
    manifest = {m["name"]: m for m in read_json(sfx_dir / "manifest.json")}
    scene_cues = {}
    for sc in tl["scenes"]:
        f = p.film / "scenes" / sc["id"] / "sfx.json"
        if f.exists():
            scene_cues[sc["id"]] = read_json(f)
    tr = read_json(p.emit / "transitions.json")
    mc = p.cfg["mix"]
    bus = np.zeros((int(round(total * sr)), 2), np.float32)
    cache: dict[str, np.ndarray] = {}
    laid = 0
    for name, t, gain in placements(tl["scenes"], scene_cues, tr["joins"], tr["sfx"], manifest,
                                    mc["sfx_default_db"]):
        if name not in manifest:
            print(f"  ! unknown sfx {name!r} at {t:.2f}s")
            continue
        if name not in cache:
            cache[name] = load_audio(sfx_dir / manifest[name]["file"], sr)
        lay(bus, cache[name], t, gain, sr)
        laid += 1
    print(f"  {laid} sfx cues placed")
    stems = p.work / "mix"
    save_audio(stems / "sfx.wav", bus * mc["sfx_headroom"], sr)

    audio = p.emit / "assets" / "audio"
    audio.mkdir(parents=True, exist_ok=True)
    voice = audio / "voice.wav"
    shutil.copyfile(p.spine_dir / "voice.wav", voice)
    out = audio / "mix.wav"
    graph = (
        "[0:a]asplit=3[v][sc1][sc2];"
        f"[1:a]volume={mc['music_db']}dB[m];[m][sc1]sidechaincompress=threshold=0.05:ratio=2.5:attack=15:release=350[md];"
        "[2:a]acompressor=threshold=-18dB:ratio=3:attack=2:release=80[sx];"
        "[sx][sc2]sidechaincompress=threshold=0.06:ratio=2:attack=5:release=200[sd];"
        "[v][md][sd]amix=inputs=3:normalize=0[sum];"
        f"[sum]alimiter=limit=0.89:attack=3:release=60,loudnorm={mc['loudnorm']}[out]"
    )
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(voice), "-i", str(p.work / "music" / "bed.wav"),
                    "-i", str(stems / "sfx.wav"), "-filter_complex", graph, "-map", "[out]", "-ar", str(sr),
                    "-t", f"{total:.4f}", "-c:a", "pcm_s24le", str(out)], check=True)
    print(f"mix -> {out}")
    return out
