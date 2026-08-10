"""livingeval's two card beats: "so I wrote tests" and "then my users changed".

The week table is counted out of the 480 traces in livingeval's database at
render time rather than typed in, so the picture cannot drift from the data it
is describing.

    python projects/livingeval/cards.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from demoforge.cards import ACCENT, FG, MUTED, OK, WARN, base, bullet, font, write  # noqa: E402
from demoforge.config import TARGET  # noqa: E402


def weekly_mix() -> list[tuple[int, float]]:
    """Rental share of each week, counted from the traces that were recorded."""
    sys.path.insert(0, str(TARGET / "src"))
    sys.path.insert(0, str(TARGET))
    from demo.run import SOURCE, connect, load_env
    from demo.world import WEEK_SECONDS, WORLD_START

    load_env()
    store = connect()
    traces = store.get_traces(source=SOURCE)
    start = WORLD_START.timestamp()
    rows = []
    for week in range(8):
        window = traces.window(start + week * WEEK_SECONDS, start + (week + 1) * WEEK_SECONDS)
        rentals = sum(1 for t in window
                      if str(t.meta.get("intent", "")).startswith("rental"))
        rows.append((week + 1, rentals / max(1, len(window))))
    store.close()
    return rows


def suite_examples(n: int = 4) -> list[str]:
    """A few of the questions that are actually in the frozen suite."""
    data = json.loads((TARGET / "demo" / "results" / "suite.json").read_text(encoding="utf-8"))
    out = []
    for case in data["cases"]:
        for turn in case["trace"]["turns"]:
            if turn["role"] == "user":
                out.append(turn["content"])
                break
        if len(out) >= n:
            break
    return out


def card_suite():
    img, d = base("So I wrote tests.",
                  "50 real conversations from week 1, checked by hand, saved.")
    y = 360
    d.text((150, y), "the eval suite", font=font("segoeuib.ttf", 30), fill=ACCENT)
    y += 70
    for question in suite_examples(4):
        bullet(d, y, question)
        y += 96
    d.text((150, y + 40),
           "Saved examples with a known-good answer. Unit tests, for a chatbot.",
           font=font("segoeui.ttf", 32), fill=MUTED)
    d.text((150, y + 100), "They run before every deploy. They pass.",
           font=font("segoeuib.ttf", 34), fill=OK)
    return [(img, 9.0)]


def card_drift(rows):
    """Reveal the table a week at a time, so the launch lands as a beat."""
    frames = []
    for shown in range(1, 9):
        img, d = base("Then my users changed.",
                      "Week 5: Northwind starts renting out tools. Deposits, late fees, damage.")
        x0, y0, colw, rowh = 190, 420, 190, 82
        d.text((x0 - 40, y0 - 70), "week", font=font("consola.ttf", 30), fill=MUTED)
        d.text((x0 - 40, y0), "orders", font=font("consola.ttf", 30), fill=MUTED)
        d.text((x0 - 40, y0 + rowh), "rentals", font=font("consola.ttf", 30), fill=MUTED)
        for i, (week, rental) in enumerate(rows[:shown]):
            x = x0 + 190 + i * colw
            live = week >= 5
            d.text((x, y0 - 70), str(week), font=font("consolab.ttf", 32),
                   fill=ACCENT if live else MUTED, anchor="mm")
            d.text((x, y0), f"{1 - rental:.0%}", font=font("consola.ttf", 34),
                   fill=FG if not live else MUTED, anchor="mm")
            d.text((x, y0 + rowh), f"{rental:.0%}", font=font("consolab.ttf", 34),
                   fill=WARN if live else (60, 66, 76), anchor="mm")
        if shown >= 5:
            x = x0 + 190 + 4 * colw - colw // 2
            d.line([x, y0 - 110, x, y0 + rowh + 50], fill=WARN, width=3)
            d.text((x + 16, y0 - 130), "Northwind Rentals launches",
                   font=font("segoeui.ttf", 27), fill=WARN)
        if shown == 8:
            d.text((150, y0 + 230), "By week 8, half the traffic is rentals.",
                   font=font("segoeuib.ttf", 44), fill=FG)
            d.text((150, y0 + 300),
                   "The suite has zero rental examples — it was written before rentals existed.",
                   font=font("segoeui.ttf", 32), fill=MUTED)
            d.text((150, y0 + 366), "And it still passes. Every time.",
                   font=font("segoeuib.ttf", 36), fill=OK)
        frames.append((img, 0.55 if shown < 8 else 8.5))
    return frames


if __name__ == "__main__":
    print("[cards]")
    write("s2_suite", card_suite())
    write("s3_drift", card_drift(weekly_mix()))
