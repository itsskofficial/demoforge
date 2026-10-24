"""Word times and burned-in caption cues, on the spine's clock.

Captions follow what was actually said, not the script: people ad-lib. The
caption text is a table written by hand from listening (mishearings fixed,
numbers written as numbers), and it is *aligned* to whisper's word times
rather than replaced by them. Whisper is good at when and bad at what; the
table is the other way round.

    transcribe  each spine line's window on its own (word timestamps), the
                table aligned to it (difflib, gaps interpolated), split into
                cues, plus a guard that fails if a trim clipped a first or
                last word
    retime      words and cues moved onto a rebuilt spine with no whisper:
                each word belongs to one line and moves by that line's shift

Cues break after sentence punctuation, after a comma once they have some
length, or before they get too long for one line at caption size. A cue holds
a little past its last word but always leaves before the next one starts.
"""

from __future__ import annotations

import difflib
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from demoforge.film.project import Project, read_json, write_json


def key(w: str) -> str:
    return re.sub(r"[^\w$]", "", w.lower().replace("-", ""))


def caption_text(p: Project) -> dict[str, str]:
    """seq -> what was said. A dict in film.json, or a `| NNNN | text |` markdown table."""
    src = p.cfg["captions"]["text"]
    if isinstance(src, dict):
        return dict(src)
    rows = {}
    for line in (p.dir / src).read_text(encoding="utf-8").splitlines():
        m = re.match(r"\| (\d{4}) \| (.*) \|$", line)
        if m:
            rows[m.group(1)] = re.sub(r"\*\(.*?\)\*", "", m.group(2)).replace("⚠", "").strip()
    return rows


def align(tokens: list[str], heard: list[dict], start: float, end: float,
          spoken: dict[str, str] | None = None) -> list[tuple[float, float]]:
    """Give every caption token a time from the words whisper heard.

    Matched tokens take their word's time. Unmatched ones (a name whisper
    spelled its own way) sit between their matched neighbours, or against the
    line's edges.
    """
    spoken = spoken or {}
    sm = difflib.SequenceMatcher(a=[key(spoken.get(t, t)) for t in tokens],
                                 b=[key(w["w"]) for w in heard], autojunk=False)
    times: list[tuple[float, float] | None] = [None] * len(tokens)
    for blk in sm.get_matching_blocks():
        for k in range(blk.size):
            h = heard[blk.b + k]
            times[blk.a + k] = (h["s"], h["e"])
    for i in range(len(tokens)):
        if times[i] is None:
            prev = next((times[j] for j in range(i - 1, -1, -1) if times[j]), (start, start))
            nxt = next((times[j] for j in range(i + 1, len(tokens)) if times[j]), (end, end))
            times[i] = (prev[1], max(prev[1], nxt[0]))
    return times  # type: ignore[return-value]


def split(seq: str, tokens: list[str], times: list[tuple[float, float]], max_chars: int = 34,
          max_words: int = 7, soft_after: int = 14) -> list[dict[str, Any]]:
    """One line's tokens as cues: hard breaks on . ? ! :, soft on , ; once long enough."""
    cues, cue = [], []
    for i, tok in enumerate(tokens):
        cue.append(i)
        text = " ".join(tokens[j] for j in cue)
        hard = tok.endswith((".", "?", "!", ":"))
        soft = tok.endswith((",", ";")) and len(text) > soft_after
        nxt_len = len(text) + 1 + len(tokens[i + 1]) if i + 1 < len(tokens) else 0
        if hard or soft or nxt_len > max_chars or len(cue) >= max_words or i == len(tokens) - 1:
            cues.append({"seq": seq, "text": text,
                         "s": round(times[cue[0]][0], 3), "e": round(times[cue[-1]][1], 3)})
            cue = []
    return cues


def hold(cues: list[dict], last_end: list[float], hold_for: float = 0.6, gap: float = 0.03) -> None:
    """Hold each cue past its last word, but leave `gap` before the next one."""
    for a, b, le in zip(cues, cues[1:], last_end):
        a["e"] = round(min(b["s"] - gap, le + hold_for), 3)
    if cues:
        cues[-1]["e"] = round(last_end[-1] + hold_for, 3)


def clipped(source: list[str], got: list[str]) -> bool:
    """A trim clipped speech if the first or last word heard differs from the untrimmed take."""
    src, got = [key(w) for w in source], [key(w) for w in got]
    return src[:1] != got[:1] or src[-1:] != got[-1:]


def srt_time(t: float) -> str:
    return (f"{int(t // 3600):02d}:{int(t % 3600 // 60):02d}:{int(t % 60):02d},"
            f"{int(round(t % 1 * 1000)) % 1000:03d}")


def srt(cues: list[dict]) -> str:
    return "\n".join(f"{i}\n{srt_time(q['s'])} --> {srt_time(q['e'])}\n{q['text']}\n"
                     for i, q in enumerate(cues, 1))


def write(p: Project, words: list[dict], cues: list[dict]) -> None:
    out = p.spine_dir
    write_json(out / "words.json", words, indent=0)
    write_json(out / "cues.json", cues, indent=1)
    (out / p.cfg["captions"]["srt"]).write_text(srt(cues), encoding="utf-8")


def transcribe(p: Project, only: list[str] | None = None) -> list[str]:
    """Whisper every line's spine window, align the caption table, write words/cues/srt.

    Returns the clipped-word problems; the CLI fails on any.
    """
    import whisper

    cfg = p.cfg["captions"]
    spine = p.spine()
    source = {}
    if cfg.get("source_words"):
        source = {r["seq"]: r for r in read_json(p.dir / cfg["source_words"])}
    texts = caption_text(p)
    model = whisper.load_model(cfg["model"])
    words_out, cues, last, problems = [], [], [], []
    with tempfile.TemporaryDirectory() as tmp:
        for c in spine["clips"]:
            if only and c["seq"] not in only:
                continue
            wav = Path(tmp) / f"{c['seq']}.wav"
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(c["start"]), "-to", str(c["end"]),
                            "-i", str(p.spine_dir / "voice.wav"), "-ac", "1", "-ar", "16000", str(wav)],
                           check=True)
            r = model.transcribe(str(wav), language=cfg["language"], word_timestamps=True, temperature=0,
                                 condition_on_previous_text=False)
            heard = [{"w": w["word"].strip(), "s": c["start"] + w["start"], "e": c["start"] + w["end"]}
                     for seg in r["segments"] for w in seg["words"]]
            if c["seq"] in source and clipped([w["w"] for w in source[c["seq"]]["words"]],
                                              [w["w"] for w in heard]):
                problems.append(f"{c['seq']}: source and spine disagree on the first or last word")
            tokens = texts[c["seq"]].split()
            times = align(tokens, heard, c["start"], c["end"], cfg["spoken"])
            words_out += [{"seq": c["seq"], "w": t, "s": round(s, 3), "e": round(e, 3)}
                          for t, (s, e) in zip(tokens, times)]
            line = split(c["seq"], tokens, times, cfg["max_chars"], cfg["max_words"], cfg["soft_after"])
            cues += line
            last += [q["e"] for q in line]
            print(c["seq"], "|", " ".join(w["w"] for w in heard)[:100], flush=True)
    hold(cues, last, cfg["hold"], cfg["gap"])
    write(p, words_out, cues)
    print(f"captions: {len(words_out)} words, {len(cues)} cues")
    return problems


def retime(old_spine: dict, new_spine: dict, words: list[dict], cues: list[dict],
           hold_for: float = 0.6, gap: float = 0.03) -> tuple[list[dict], list[dict], list[str]]:
    """Move words and cues from one spine to another. Exact, because speech inside a
    line never changes: only where the line sits and where it was trimmed."""
    old = {c["seq"]: c for c in old_spine["clips"]}
    new = {c["seq"]: c for c in new_spine["clips"]}
    shift = {s: round(new[s]["start"] - old[s]["start"] - (new[s]["src_in"] - old[s]["src_in"]), 4)
             for s in new}
    notes = []
    moved = []
    for w in words:
        d = shift[w["seq"]]
        w2 = dict(w, s=round(w["s"] + d, 3), e=round(w["e"] + d, 3))
        if w2["e"] > new[w["seq"]]["end"] + 0.02:
            notes.append(f"word {w['w']!r} ({w['seq']}) ends after its trimmed line")
        moved.append(w2)
    out, last = [], []
    for c in cues:
        inside = [w for w in words if c["s"] - 0.02 <= w["s"] < c["e"] - 0.001]
        seq = inside[0]["seq"] if inside else min(old, key=lambda s: abs(old[s]["start"] - c["s"]))
        d = shift[seq]
        out.append(dict(c, s=round(c["s"] + d, 3)))
        last.append(max((w["e"] for w in inside), default=c["e"]) + d)
    hold(out, last, hold_for, gap)
    return moved, out, notes


def retime_project(p: Project, baseline: Path, words: Path | None = None,
                   cues: Path | None = None) -> None:
    """`baseline` is the spine the words were transcribed on (spine.v1.json); its
    words and cues sit beside it (words.v1.json, cues.v1.json) unless given."""
    words = words or baseline.with_name(baseline.name.replace("spine", "words"))
    cues = cues or baseline.with_name(baseline.name.replace("spine", "cues"))
    cfg = p.cfg["captions"]
    w, c, notes = retime(read_json(baseline), p.spine(), read_json(words), read_json(cues),
                         cfg["hold"], cfg["gap"])
    write(p, w, c)
    for n in notes:
        print("  !", n)
    print(f"retime: {len(w)} words and {len(c)} cues moved onto {p.spine_dir / 'spine.json'}")
