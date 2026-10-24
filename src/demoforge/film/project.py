"""film.json: load it, fill in the defaults, check it, and say where things live.

Everything particular to one film lives in its `film.json`: which lines have a
breath after them, which spans of a take are cut out, which scenes start on
which word, which join is a whip and which shatters, where each piece of music
comes in. The engine reads nothing else, so a second film is a second file.

Keys that start with `_` are comments, at any depth, and are dropped on load.
Paths may use `{out}` (demoforge's out folder), `{root}` (the checkout),
`{project}` (the folder holding film.json), `{name}`, `{work}` and `{film}`.
Relative paths are relative to the project folder.

Three folders matter:

    project   film.json, the briefs, and `film/`: the HyperFrames project
    work      intermediates nobody edits: spine, music, mix, decoded footage
    emit      where generated film files go. It is the film folder unless a
              run is redirected (`--into`), which is how a build is checked
              against a finished film without touching it.
"""

from __future__ import annotations

import copy
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from demoforge.config import OUT, PROJECTS, ROOT

# The HyperFrames release every film step runs (the pitch film rendered on it).
# Pinned so a project re-renders identically; bump deliberately.
HYPERFRAMES = "0.8.181"
HF = f"hyperframes@{HYPERFRAMES}"

CONFIG = "film.json"

# The transitions the root composition knows how to draw. A join names one.
TRANSITIONS = ("glitch", "leak", "match", "flash", "whip", "cut", "dip", "drop",
               "punch", "zoom", "act", "shatter")

# Defaults are the pitch film's numbers: they were tuned by ear and eye on a
# real film, which is a better starting point than round numbers.
DEFAULTS: dict[str, Any] = {
    "name": "",
    "title": "",
    "fps": 30,
    "width": 1920,
    "height": 1080,
    "sample_rate": 48000,
    "paths": {
        "film": "film",
        "work": "{out}/{name}",
        "voice": "footage/voice",
        "camera": "footage/cam",
        "music": "{work}/music/tracks",
        "temp": "{work}/tmp",
    },
    "sources": {
        "voice": "*.wav",
        "camera": "*.mp4",
        # the line number is the last run of digits before the extension:
        # voiceover00000539_A1-0001.wav and camera_looking00001094_V1-0002.mp4
        "seq": r"(\d{4})\.[^.]+$",
    },
    "decode": {"max_repeat": 0.05, "crf": 12},
    "spine": {
        "lead": 0.10,           # air before speech, then out to a whole frame
        "tail": 0.16,           # air after; never tightened across the board
        "gap": 0.30,            # speech-to-speech silence between lines
        "gap_after": {},        # per line: the film's breaths
        "lead_in": 0.40,        # room before the first word
        "end_hold": 3.5,        # silence after the last line: the end card holds
        "floor_percentile": 10,
        "speech_db": 14.0,      # speech is this far over the room tone
        "remove": {},           # per line: [[start, end], ...] in clip seconds
        "remove_xfade": 0.012,
        "tail_cut": {},         # per line: hard limit, seconds before the clip's end
        "edge_fade": 0.004,
        "lookaway_tail": 0.09,
        "lookaway_gap": 0.18,
        "lookaway_gap_after": {},
        "chain": ("adeclip,highpass=f=75,afftdn=nr=12:nf=-44:tn=1,"
                  "agate=threshold=0.015:ratio=2:range=0.2:attack=5:release=200,"
                  "equalizer=f=250:t=q:w=1.0:g=-2,equalizer=f=3500:t=q:w=1.2:g=2,"
                  "acompressor=threshold=-20dB:ratio=2.5:attack=8:release=120:makeup=2,"
                  "loudnorm=I=-16:TP=-1.5:LRA=9"),
    },
    # line -> clip time of the last on-lens frame, approved frame by frame
    "lookaways": {},
    "captions": {
        "text": "FOOTAGE.md",   # a `| NNNN | text |` table, or {seq: text}
        "spoken": {},           # caption token -> how whisper writes it
        "source_words": None,   # untrimmed transcripts, for the clipped-word guard
        "model": "large-v3",
        "language": "en",
        "max_chars": 34,
        "max_words": 7,
        "soft_after": 14,       # a comma breaks a cue once it is this long
        "hold": 0.6,            # a cue stays this long past its last word
        "gap": 0.03,            # and leaves before the next cue by this much
        "srt": "captions.srt",
    },
    "anchor_lead": 0.12,        # a `line@word` scene cuts this far ahead of the word
    "scenes": [],
    # kinds that are on camera, and how their footage looks
    "looks": {
        "cam": {"plate": "none", "subject": "none", "ground": "#0b0d12",
                "plate_scale": 1.0, "push": [1.0, 1.045], "glow": False, "key": False},
    },
    "camera": {
        "nocut": [],            # lines that stay full-frame, no cutout
        "flip_from": {},        # line -> clip time to un-mirror from, with a punch-in
        "punch_scale": 1.16,
        "punch_duration": 0.32,
        "sharp": "none",
        "plate_crf": 14,
        "plate_gop": 30,        # sparse keyframes make the renderer freeze on seek
        "cutout_gop": 15,
        "cutout_crf": 18,
        "choke": 2,             # erosion passes on the matte
        "soften": 1.1,
        "despill": "green",
        "despill_mix": 0.6,
    },
    "joins": {},                # outgoing scene id -> transition kind
    "default_join": "cut",
    # transition kind -> [sfx, offset from the cut or null (peak on the cut), gain dB]
    # or a list of those
    "sfx": {},
    "root": {
        "grain_seed": 99,
        "grain_opacity": 0.075,
        "glitch_seed": 7,
        "shatter_seed": 1337,
        "shatter_point": [1260, 360],
        "shatter_impact": 0.72,
        "caption_top": 920,
        "caption_size": 54,
        "gsap": "https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js",
    },
    "music": {
        "target_lufs": -16.0,
        "limit": 0.9,
        "sections": [],
        "preview": True,
    },
    "mix": {
        "music_db": -8,
        "sfx_default_db": -6,
        "sfx_headroom": 0.5,
        "loudnorm": "I=-14:TP=-1:LRA=11",
    },
    "render": {
        "workers": 2,
        "quality": "delivery",
        "timeout_ms": 1800000,
        "output": "{film}/renders/{name}.mp4",
    },
    "thumbs": {
        "count": 6,
        "step": 0.25,
        "spacing": 2.0,
        "headlines": [],
    },
}


def strip_comments(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: strip_comments(v) for k, v in value.items() if not str(k).startswith("_")}
    if isinstance(value, list):
        return [strip_comments(v) for v in value]
    return value


def merge(base: dict, over: dict) -> dict:
    """Defaults under the file. Tables keyed by line or scene replace whole."""
    out = copy.deepcopy(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict) and k not in WHOLE:
            out[k] = merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


# Tables whose keys are the film's own (line numbers, scene ids, kinds), so a
# default entry would be a stray, not a default.
WHOLE = {"gap_after", "remove", "tail_cut", "lookaway_gap_after", "lookaways", "spoken",
         "looks", "flip_from", "joins", "sfx", "text"}


@dataclass
class Project:
    dir: Path
    cfg: dict[str, Any]
    work: Path
    film: Path
    emit: Path

    # -- the numbers everything shares -------------------------------------
    @property
    def name(self) -> str:
        return self.cfg["name"]

    @property
    def fps(self) -> int:
        return int(self.cfg["fps"])

    @property
    def sr(self) -> int:
        return int(self.cfg["sample_rate"])

    @property
    def size(self) -> tuple[int, int]:
        return int(self.cfg["width"]), int(self.cfg["height"])

    @property
    def lookaways(self) -> dict[str, float]:
        return {k: float(v) for k, v in self.cfg["lookaways"].items()}

    def path(self, key: str) -> Path:
        return self._resolve(self.cfg["paths"][key])

    def _resolve(self, value: str) -> Path:
        return resolve(value, self.dir, self.name, work=self.work, film=self.film)

    # -- where each step reads and writes ----------------------------------
    @property
    def spine_dir(self) -> Path:
        return self.work / "spine"

    def spine(self) -> dict[str, Any]:
        return read_json(self.spine_dir / "spine.json")

    def clips(self) -> dict[str, dict[str, Any]]:
        return {c["seq"]: c for c in self.spine()["clips"]}

    def timeline(self) -> dict[str, Any]:
        return read_json(self.emit / "timeline.json")

    def camera_kinds(self) -> set[str]:
        return set(self.cfg["looks"])

    def seq_of(self, path: Path) -> str | None:
        m = re.search(self.cfg["sources"]["seq"], path.name)
        return m.group(1) if m else None

    def sources(self, key: str) -> dict[str, Path]:
        """seq -> file, for the voice or camera folder."""
        folder = self.path(key)
        found = {}
        for p in sorted(folder.glob(self.cfg["sources"][key])):
            s = self.seq_of(p)
            if s:
                found[s] = p
        return dict(sorted(found.items()))


def resolve(value: str, project: Path, name: str, work: Path | None = None,
            film: Path | None = None) -> Path:
    s = str(value).format(out=OUT, root=ROOT, project=project, name=name,
                          work=work if work is not None else "{work}",
                          film=film if film is not None else "{film}")
    p = Path(s)
    return (p if p.is_absolute() else project / p).resolve()


def find(target: str | Path) -> Path:
    """A film.json, a folder holding one, or a project name under projects/."""
    p = Path(target)
    for cand in (p, p / CONFIG, PROJECTS / str(target) / CONFIG):
        if cand.is_file() and cand.name.endswith(".json"):
            return cand.resolve()
    raise SystemExit(f"no {CONFIG} for {target!r} (looked in {p}, {PROJECTS / str(target)})")


def load(target: str | Path, work: str | Path | None = None,
         into: str | Path | None = None) -> Project:
    path = find(target)
    raw = strip_comments(json.loads(path.read_text(encoding="utf-8")))
    cfg = merge(DEFAULTS, raw)
    if not cfg["name"]:
        cfg["name"] = path.parent.name
    problems, _ = validate(cfg)
    if problems:
        raise SystemExit(f"{path}:\n  " + "\n  ".join(problems))
    d = path.parent
    w = Path(work).resolve() if work else resolve(cfg["paths"]["work"], d, cfg["name"])
    f = resolve(cfg["paths"]["film"], d, cfg["name"], work=w)
    e = Path(into).resolve() if into else f
    return Project(dir=d, cfg=cfg, work=w, film=f, emit=e)


ANCHOR = re.compile(r"^(\d+)(?:@([^#]+)(?:#(\d+))?)?$")
EDGE = re.compile(r"^(?:(end)|(\d+)(?:\.(start|end))?)?([+-]\d+(?:\.\d+)?)?$")


def validate(cfg: dict[str, Any]) -> tuple[list[str], list[str]]:
    """(errors, warnings). Errors stop a load; warnings are printed by `check`."""
    err, warn = [], []
    for k in ("fps", "width", "height", "sample_rate"):
        if not isinstance(cfg.get(k), (int, float)) or cfg[k] <= 0:
            err.append(f"{k} must be a positive number")
    try:
        re.compile(cfg["sources"]["seq"])
    except re.error as e:
        err.append(f"sources.seq is not a regex: {e}")
    sp = cfg["spine"]
    for k in ("lead", "tail", "gap", "lookaway_tail", "lookaway_gap"):
        if not isinstance(sp.get(k), (int, float)) or sp[k] < 0:
            err.append(f"spine.{k} must be a number >= 0")
    if isinstance(sp.get("tail"), (int, float)) and sp["tail"] < 0.12:
        warn.append(f"spine.tail {sp['tail']} clips consonants; tighten single lines "
                    "with lookaways or tail_cut, never every tail")
    for seq, spans in sp["remove"].items():
        for span in spans:
            if len(span) != 2 or span[0] >= span[1]:
                err.append(f"spine.remove.{seq}: {span} is not [start, end]")
    for seq, t in cfg["lookaways"].items():
        if not isinstance(t, (int, float)):
            err.append(f"lookaways.{seq} must be a clip time in seconds")
    looks = cfg["looks"]
    for kind, look in looks.items():
        for k in ("plate", "subject", "ground", "push"):
            if k not in look:
                err.append(f"looks.{kind} needs {k!r}")
    ids = [s.get("id") for s in cfg["scenes"]]
    if len(set(ids)) != len(ids):
        err.append("scene ids must be unique")
    for s in cfg["scenes"]:
        for k in ("id", "kind", "at"):
            if k not in s:
                err.append(f"scene {s} needs {k!r}")
        if "at" in s and not ANCHOR.match(str(s["at"])):
            err.append(f"scene {s.get('id')}: at {s['at']!r} is not 'NNNN', 'NNNN@word' or 'NNNN@word#n'")
        if str(s.get("kind", "")).startswith("cam") and s.get("kind") not in looks:
            warn.append(f"scene {s.get('id')}: kind {s['kind']!r} has no look, so it is not on camera")
    for sid, kind in cfg["joins"].items():
        if sid not in ids:
            err.append(f"joins.{sid}: no such scene")
        if kind not in TRANSITIONS:
            err.append(f"joins.{sid}: {kind!r} is not one of {', '.join(TRANSITIONS)}")
    if cfg["default_join"] not in TRANSITIONS:
        err.append(f"default_join {cfg['default_join']!r} is unknown")
    for kind, spec in cfg["sfx"].items():
        if kind not in TRANSITIONS:
            err.append(f"sfx.{kind}: not a transition kind")
        for one in (spec if spec and isinstance(spec[0], list) else [spec]):
            if (len(one) != 3 or not isinstance(one[0], str)
                    or not (one[1] is None or isinstance(one[1], (int, float)))):
                err.append(f"sfx.{kind}: {one} is not [name, offset|null, gain]")
    for i, m in enumerate(cfg["music"]["sections"]):
        for k in ("track", "track_at", "start", "end"):
            if k not in m:
                err.append(f"music.sections[{i}] needs {k!r}")
        for k in ("pin", "start", "end"):
            if k in m and not isinstance(m[k], (int, float)) and not EDGE.match(str(m[k])):
                err.append(f"music.sections[{i}].{k}: {m[k]!r} is not a time, 'NNNN[.end][+-s]' or 'end'")
    if cfg["scenes"] and cfg["scenes"][0].get("at") and "@" in str(cfg["scenes"][0]["at"]):
        warn.append("the first scene starts on a word, so the film opens mid-line")
    return err, warn


# ---------------------------------------------------------------------------
# small shared helpers
# ---------------------------------------------------------------------------


def frame(t: float, fps: int, up: bool) -> float:
    """A time on a whole frame, rounding out (up) or in."""
    f = np.ceil(t * fps - 1e-9) if up else np.floor(t * fps + 1e-9)
    return float(f) / fps


def snap(t: float, fps: int) -> float:
    return round(round(t * fps) / fps, 4)


def edge(value: Any, clips: dict[str, dict], total: float) -> float:
    """A music edge: seconds, 'end', or a line ('0009', '0009.end') plus an offset."""
    if isinstance(value, (int, float)):
        return float(value)
    m = EDGE.match(str(value))
    if not m:
        raise ValueError(f"bad time {value!r}")
    end, seq, which, off = m.groups()
    t = total if end else clips[seq][which or "start"] if seq else 0.0
    return t + float(off) if off else t


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any, indent: int | None = 1) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=indent, ensure_ascii=False), encoding="utf-8")
    return path


def ffmpeg(*args: str, quiet: bool = True) -> None:
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args] if quiet else ["ffmpeg", "-y", *args],
                   check=True)


def load_audio(path: Path, sr: int) -> np.ndarray:
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-ac", "2", "-ar", str(sr), "-f", "f32le", "-"],
        capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.float32).reshape(-1, 2).copy()


def save_audio(path: Path, a: np.ndarray, sr: int) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "f32le", "-ar", str(sr), "-ac", "2", "-i", "-",
                    "-c:a", "pcm_s24le", str(path)], input=a.astype(np.float32).tobytes(), check=True)
    return path


def probe_duration(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                          str(path)], capture_output=True, text=True).stdout
    return float(out.strip())
