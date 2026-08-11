"""Find a real music bed, rank it on structure, and record its licence.

A mastered, human-arranged cue beats anything synthesised: it grooves, and the
difference is audible under narration. `demoforge.music bed` stays as a
fallback for when a licence dependency is unacceptable, but this is the default
path.

Pixabay is the source because its Content License is genuinely free for
commercial use with no attribution required. The licence is written down at
download time, including what it *forbids* -- most stock licences bar handing
over the audio as a standalone file, which is fine for a bed inside a video and
matters the moment someone asks for "the music on its own".

    python -m demoforge.music_source find --query "chill trap beat" --runtime 180
    python -m demoforge.music_source rank --dir out/audio/candidates

Two things this does that a naive picker does not:

* **Ranks on arrangement, not loudness.** Stock music is limited hard, so RMS is
  nearly a straight line and tells you almost nothing. A breakdown is the bass
  and percussion leaving, which barely moves total level but is unmistakable in
  the low and high bands separately.

* **Shortlists on length.** Aligning a track to an edit is done by sliding it,
  never by splicing, so the source has to be meaningfully longer than the film
  or there is no offset to spend.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from demoforge.config import AUDIO

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
BASE = "https://pixabay.com"
CANDIDATES = AUDIO / "candidates"
THROTTLE = 2.5      # seconds between requests


_LAST = [0.0]


def _get(url: str, tries: int = 4) -> str:
    """Fetch a page, politely.

    Pixabay starts returning 403 after a handful of rapid requests, so this
    paces itself and backs off rather than hammering. Sourcing a bed is a
    once-per-video operation; there is no reason for it to be fast.
    """
    headers = {
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-GB,en;q=0.9",
        "Referer": f"{BASE}/music/",
    }
    for attempt in range(tries):
        wait = max(0.0, THROTTLE - (time.time() - _LAST[0]))
        if wait:
            time.sleep(wait)
        _LAST[0] = time.time()
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=60) as resp:
                return resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            if exc.code not in (403, 429) or attempt == tries - 1:
                raise
            time.sleep(4 * (attempt + 1))
    return ""


def search(query: str, limit: int = 12) -> list[str]:
    """Track slugs for a query. The search page has no audio URLs; the track page does."""
    html = _get(f"{BASE}/music/search/{urllib.parse.quote(query)}/")
    slugs = re.findall(r'href="(/music/[a-z0-9-]+-[0-9]+/)"', html)
    seen, out = set(), []
    for slug in slugs:
        if slug not in seen:
            seen.add(slug)
            out.append(slug)
    return out[:limit]


def cdn_url(slug: str) -> tuple[str, str] | None:
    """The direct download for a track page, plus the filename it suggests."""
    html = _get(f"{BASE}{slug}")
    match = re.search(r'https://cdn\.pixabay\.com/download/audio/[^"\']+\.mp3[^"\']*', html)
    if not match:
        return None
    url = match.group(0)
    name = re.search(r"filename=([^&\"']+)", url)
    return url, (name.group(1) if name else slug.strip("/").split("/")[-1] + ".mp3")


def duration(path: Path) -> float:
    return float(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True, check=True).stdout.strip())


def fetch(slug: str, into: Path = CANDIDATES) -> Path | None:
    into.mkdir(parents=True, exist_ok=True)
    found = cdn_url(slug)
    if not found:
        return None
    url, name = found
    dest = into / name
    if dest.exists():
        return dest
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=180) as resp, dest.open("wb") as f:
        f.write(resp.read())
    (into / f"{dest.stem}.source.json").write_text(json.dumps(
        {"slug": slug, "page": f"{BASE}{slug}", "url": url, "file": dest.name},
        indent=1), encoding="utf-8")
    return dest


def analyse(path: Path) -> dict:
    """Tempo, brightness, drive, and how much the arrangement actually moves.

    The two band envelopes are the point. A breakdown drops the low band (kick
    and bass leaving) and the high band (hats leaving) together while the
    overall level barely moves, because the master is limited.
    """
    import librosa
    import numpy as np

    y, sr = librosa.load(str(path), sr=22050, mono=True)
    S = np.abs(librosa.stft(y, n_fft=2048, hop_length=512))
    freq = librosa.fft_frequencies(sr=sr, n_fft=2048)
    times = librosa.times_like(S[0], sr=sr, hop_length=512)

    low = S[freq < 130].mean(axis=0)
    high = S[freq > 4000].mean(axis=0)

    def per_second(env):
        seconds = int(times[-1])
        return np.array([env[(times >= i) & (times < i + 1)].mean() or 0.0
                         for i in range(max(1, seconds))])

    low_s, high_s = per_second(low), per_second(high)
    lown = low_s / (low_s.max() or 1)
    highn = high_s / (high_s.max() or 1)

    # A section counts as thin when both bands sit well under their own median.
    thin = (lown < np.median(lown) * 0.55) & (highn < np.median(highn) * 0.6)
    runs, run = [], 0
    for flag in thin:
        run = run + 1 if flag else 0
        if not flag and run:
            runs.append(run)
        elif flag:
            pass
    if run:
        runs.append(run)
    breakdown = max(runs) if runs else 0

    tempo, beats = librosa.beat.beat_track(y=y, sr=sr, units="time")
    centroid = float(librosa.feature.spectral_centroid(y=y, sr=sr).mean())
    percussive = librosa.effects.percussive(y)
    drive = float(np.sqrt((percussive ** 2).mean()) / (np.sqrt((y ** 2).mean()) or 1))

    return {
        "file": path.name,
        "seconds": round(len(y) / sr, 1),
        "bpm": round(float(np.atleast_1d(tempo)[0]), 1),
        "brightness": round(centroid, 0),
        "drive": round(drive, 3),
        "breakdown_s": int(breakdown),
        "low": lown.round(2).tolist(),
        "high": highn.round(2).tolist(),
        "beats": [round(b, 3) for b in beats.tolist()],
    }


def licence_md(path: Path, meta: dict, out: Path) -> Path:
    """Write down the licence at download time, including what it forbids."""
    stem = path.stem
    pretty = re.sub(r"-\d+$", "", stem).replace("-", " ").strip().title()
    out.write_text(f"""# Music licence

| | |
|---|---|
| **Title** | {pretty} |
| **Source** | {meta.get('page', 'Pixabay')} |
| **File** | `{path.name}` ({meta.get('seconds', '?')} s, {meta.get('bpm', '?')} bpm) |
| **Licence** | Pixabay Content License |

## What it permits

Free for commercial use. **No attribution required.** Safe as a bed in a
distributed demo video, on YouTube, LinkedIn and X.

## What it forbids

- Redistributing the audio **as a standalone file**. The bed may ship inside the
  video; the mp3 must not be handed over as music on its own.
- Reselling or sublicensing the track, or claiming ownership of it.
- Any use implying the artist endorses this product.
""", encoding="utf-8")
    return out


def align(analysis: dict, runtime: float, payoff: float) -> float:
    """Offset that puts the track's arrangement return on the film's payoff.

    Slide, never splice: a splice costs a click, a phase discontinuity or a
    broken bar, while an offset costs nothing but requiring the source to be
    longer than the film.
    """
    import numpy as np

    low = np.array(analysis["low"])
    high = np.array(analysis["high"])
    combined = low + high
    thin = combined < np.median(combined) * 0.75

    # The return is the first strong rise after the longest thin stretch.
    best_end, best_len, run, start = None, 0, 0, 0
    for i, flag in enumerate(thin):
        if flag:
            if run == 0:
                start = i
            run += 1
        else:
            if run > best_len:
                best_len, best_end = run, i
            run = 0
    if best_end is None:
        return 0.0

    beats = np.array(analysis["beats"])
    snapped = float(beats[np.argmin(np.abs(beats - best_end))]) if len(beats) else float(best_end)
    offset = max(0.0, snapped - payoff)
    if offset + runtime > analysis["seconds"]:
        offset = max(0.0, analysis["seconds"] - runtime)
    return round(offset, 3)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    f = sub.add_parser("find", help="search, download candidates, rank them")
    f.add_argument("--query", action="append", required=True,
                   help="repeatable; spread queries, result sets barely overlap")
    f.add_argument("--runtime", type=float, required=True)
    f.add_argument("--limit", type=int, default=8, help="candidates per query")
    f.add_argument("--dir", default=str(CANDIDATES))

    r = sub.add_parser("rank", help="analyse already-downloaded candidates")
    r.add_argument("--dir", default=str(CANDIDATES))
    r.add_argument("--runtime", type=float, default=0.0)

    args = ap.parse_args()
    into = Path(args.dir)

    if args.cmd == "find":
        slugs = []
        for query in args.query:
            try:
                found = search(query, args.limit)
            except Exception as exc:                       # noqa: BLE001
                print(f"  {query:<32} {type(exc).__name__} - skipped")
                continue
            print(f"  {query:<32} {len(found)} results")
            slugs.extend(found)
        slugs = list(dict.fromkeys(slugs))
        print(f"\n  {len(slugs)} unique candidates; downloading …")
        for slug in slugs:
            try:
                path = fetch(slug, into)
                if path:
                    print(f"    {path.name}  ({duration(path):.0f}s)")
            except Exception as exc:                       # noqa: BLE001
                print(f"    {slug}: {type(exc).__name__}")

    files = sorted(p for p in into.glob("*.mp3"))
    runtime = args.runtime
    print(f"\n  {'file':<52} {'len':>6} {'bpm':>6} {'thin':>5} {'bright':>7} {'drive':>6}")
    rows = []
    for path in files:
        try:
            a = analyse(path)
        except Exception as exc:                           # noqa: BLE001
            print(f"  {path.name:<52} {type(exc).__name__}")
            continue
        rows.append(a)
        fits = "" if not runtime else ("" if a["seconds"] > runtime * 1.15 else "  (too short)")
        print(f"  {a['file'][:52]:<52} {a['seconds']:>6.0f} {a['bpm']:>6.0f} "
              f"{a['breakdown_s']:>5} {a['brightness']:>7.0f} {a['drive']:>6.3f}{fits}")
    (into / "analysis.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")
    print(f"\n  analysis -> {into / 'analysis.json'}")
    print("  shortlist on length first, then on a real breakdown (thin >= 8s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
