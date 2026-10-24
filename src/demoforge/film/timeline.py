"""The scene table: every scene pinned to the voice spine.

A scene starts where its first line starts, or just ahead of a named word
inside a line (`0036@Remember`, or `0036@and#2` for the second "and"), and ends
where the next scene starts. So the voice never stops between scenes and no
scene can drift off its words when the spine is rebuilt. Every edge is on a
whole frame.

Writes timeline.json into the film folder; the root composition, the camera
scenes, the freeze step, the mixer and every hand-built scene read it. Each
scene carries its lines, its text and its words in scene-local time, which is
what a scene builder times its beats against.
"""

from __future__ import annotations

from typing import Any

from demoforge.film.project import ANCHOR, Project, read_json, snap, write_json


def bare(w: str) -> str:
    return w.strip(".,?!")


def anchor(ref: str, clips: dict[str, dict], words: list[dict], lead: float = 0.12) -> float:
    """Film time of a scene anchor: 'NNNN' (the line's start) or 'NNNN@word[#n]'."""
    m = ANCHOR.match(ref)
    if not m:
        raise ValueError(f"bad anchor {ref!r}")
    seq, word, nth = m.groups()
    if seq not in clips:
        raise KeyError(f"anchor {ref!r}: no line {seq} in the spine")
    if not word:
        return clips[seq]["start"]
    hits = [w for w in words if w["seq"] == seq and bare(w["w"]) == bare(word)]
    n = int(nth or 1)
    if len(hits) < n:
        raise KeyError(f"anchor {ref!r}: line {seq} has {len(hits)} of {word!r}")
    return hits[n - 1]["s"] - lead  # cut just ahead of the word


def scenes(table: list[dict], spine: dict, words: list[dict], fps: int,
           lead: float = 0.12) -> list[dict[str, Any]]:
    clips = {c["seq"]: c for c in spine["clips"]}
    rows = []
    for i, sc in enumerate(table):
        start = snap(anchor(sc["at"], clips, words, lead), fps)
        end = (snap(anchor(table[i + 1]["at"], clips, words, lead), fps) if i + 1 < len(table)
               else snap(spine["duration"], fps))
        first = sc["at"].split("@")[0]
        inside = [w for w in words if start <= w["s"] < end]
        seqs = sorted({w["seq"] for w in inside} | {first})
        lines = [{"seq": s, "start": clips[s]["start"], "end": clips[s]["end"],
                  "src_in": clips[s]["src_in"], "src_out": clips[s]["src_out"], "cam": clips[s]["cam"]}
                 for s in seqs]
        rows.append({"id": sc["id"], "kind": sc["kind"], "title": sc.get("title", ""),
                     "start": start, "end": end, "duration": round(end - start, 4), "lines": lines,
                     "text": " ".join(w["w"] for w in inside),
                     "words": [{"w": w["w"], "s": round(w["s"] - start, 3), "e": round(w["e"] - start, 3)}
                               for w in inside]})
    return rows


def build(p: Project) -> dict[str, Any]:
    spine = p.spine()
    words = read_json(p.spine_dir / "words.json")
    cues = read_json(p.spine_dir / "cues.json")
    rows = scenes(p.cfg["scenes"], spine, words, p.fps, p.cfg["anchor_lead"])
    w, h = p.size
    out = {"fps": p.fps, "width": w, "height": h, "duration": snap(spine["duration"], p.fps),
           "scenes": rows, "captions": cues}
    write_json(p.emit / "timeline.json", out)
    for r in rows:
        print(f"  {r['id']} {r['kind']:9} {r['start']:7.2f}-{r['end']:7.2f} ({r['duration']:5.2f}s)"
              f"  {r['text'][:70]}")
    print(f"timeline: {len(rows)} scenes -> {p.emit / 'timeline.json'}")
    return out
