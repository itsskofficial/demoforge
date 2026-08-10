"""The twelve scenes of the three-minute livingeval demo.

Aimed at someone who has never written an eval and may not write code at all,
so the vocabulary on screen is "tests", "questions" and "blind" rather than
coverage, detection power or judges. Terminals appear twice and briefly; the
rest is drawn, because a stranger watching once will read a picture and skim
a wall of output.

Durations come from the measured narration, so a scene is exactly as long as
the sentence spoken over it.

    python projects/livingeval3/scenes.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from demoforge.motion import (  # noqa: E402
    ACCENT, BG, DIM, FG, GOLD, MUTED, OK, PANEL, WARN, Scene, blend, bold, bubble,
    count_text, cross, ease_out, glow, grow_bar, mono, panel, regular, rise_text,
    tick, window, wrap,
)

W, H = 1920, 1080
NARRATION = ROOT / "out" / "audio" / "live3" / "narration.json"


def heading(d, text, t, start=0.15, sub=None, y=118):
    rise_text(d, (140, y), text, bold(64), FG, t, start)
    if sub:
        rise_text(d, (140, y + 92), sub, regular(31), MUTED, t, start + 0.2)


# ---------------------------------------------------------------------------
# 1. everyone tests it the same way
# ---------------------------------------------------------------------------
def hook(seconds):
    steps = [("Save real conversations", ACCENT), ("Check the answers by hand", ACCENT),
             ("Run them before every release", ACCENT)]

    def draw(d, img, t):
        heading(d, "Everyone tests their AI the same way.", t,
                sub="And it works. Right up until it doesn't.")
        y = 380
        for i, (label, colour) in enumerate(steps):
            start = 1.1 + i * 0.75
            if panel(d, (140, y, 1180, y + 118), t, start, radius=20):
                a = window(t, start, 0.5)
                d.ellipse([180, y + 34, 230, y + 84], fill=blend(colour, a * 0.28))
                d.text((205, y + 59), str(i + 1), font=bold(30),
                       fill=blend(colour, a), anchor="mm")
                d.text((268, y + 59), label, font=regular(37), fill=blend(FG, a), anchor="lm")
            y += 146
        rise_text(d, (140, 856), "If they pass, you ship.", bold(46), OK, t, 3.9)
        rise_text(d, (140, 934), "I did exactly that. It went wrong in a way I didn't see.",
                  regular(33), MUTED, t, 4.6)
        return img

    return Scene("s01_hook", seconds, draw)


# ---------------------------------------------------------------------------
# 2. here is the app
# ---------------------------------------------------------------------------
def app(seconds):
    q = "Where is my order NW-4143?"
    a = "Your order for a mitre saw is packed and scheduled to be shipped."

    def draw(d, img, t):
        heading(d, "This is the app.", t, sub="A support bot for a hardware shop.")
        bubble(d, (140, 360), 760, wrap(q, regular(34), 700), regular(34), t, 1.0,
               colour=(31, 41, 55))
        if panel(d, (140, 520, 900, 604), t, 2.0, radius=16, fill=(18, 32, 30)):
            al = window(t, 2.0, 0.5)
            d.text((172, 562), "looks it up in the real database", font=mono(27),
                   fill=blend(OK, al), anchor="lm")
        bubble(d, (980, 470), 800, wrap(a, regular(34), 740), regular(34), t, 3.0,
               colour=PANEL)
        rise_text(d, (140, 900), "That's the whole thing.", bold(44), FG, t, 4.4)
        return img

    return Scene("s02_app", seconds, draw)


# ---------------------------------------------------------------------------
# 3. the bug
# ---------------------------------------------------------------------------
def bug(seconds):
    q = "I need to cancel order NW-4030 if it's not gone out yet."

    def draw(d, img, t):
        heading(d, "Except sometimes it isn't.", t, sub="A real answer, unedited.")
        bubble(d, (140, 340), 900, wrap(q, regular(34), 840), regular(34), t, 0.9,
               colour=(31, 41, 55))
        if panel(d, (140, 500, 780, 584), t, 2.2, radius=16, fill=(40, 24, 24)):
            al = window(t, 2.2, 0.5)
            d.text((172, 542), "the database says:  delivered", font=mono(27),
                   fill=blend(WARN, al), anchor="lm")
        lines = ["It has already been delivered and cannot be",
                 "cancelled, as it's already out for delivery."]
        bubble(d, (140, 630), 1120, lines, regular(36), t, 3.4, colour=PANEL)
        if t > 5.6:
            al = window(t, 5.6, 0.5)
            d.line([(178, 700), (620, 700)], fill=blend(WARN, al), width=4)
            d.line([(700, 748), (1180, 748)], fill=blend(WARN, al), width=4)
        rise_text(d, (140, 880), "Delivered, or out for delivery?", bold(46), FG, t, 6.6)
        rise_text(d, (140, 954), "It can't be both. It just said both.",
                  bold(40), WARN, t, 7.5)
        cross(d, (1500, 880), 90, t, 7.8)
        return img

    return Scene("s03_bug", seconds, draw)


# ---------------------------------------------------------------------------
# 4. so I wrote tests
# ---------------------------------------------------------------------------
def tests(seconds):
    def draw(d, img, t):
        heading(d, "So I wrote tests.", t,
                sub="Fifty real conversations. Every answer checked by hand.")
        for i in range(50):
            col, row = i % 10, i // 10
            x, y = 300 + col * 118, 380 + row * 104
            start = 1.0 + i * 0.026
            a = window(t, start, 0.3)
            if a > 0.01:
                d.rounded_rectangle([x, y, x + 92, y + 80], radius=14,
                                    fill=blend((26, 44, 33), a))
                tick(d, (x + 30, y + 24), 34, t, start + 0.1)
        rise_text(d, (300, 916), "Like unit tests, but for a chatbot.",
                  regular(35), MUTED, t, 3.0)
        if t > 3.9:
            a = window(t, 3.9, 0.5)
            d.rounded_rectangle([1330, 890, 1600, 966], radius=18,
                                fill=blend((22, 60, 38), a))
            d.text((1465, 928), "ALL PASSING", font=bold(34), fill=blend(OK, a), anchor="mm")
        return img

    return Scene("s04_tests", seconds, draw)


# ---------------------------------------------------------------------------
# 5. then the business changed
# ---------------------------------------------------------------------------
def change(seconds):
    mix = [0, 0, 0, 0, .18, .30, .42, .53]

    def draw(d, img, t):
        heading(d, "Then the business changed.", t,
                sub="Week five: the shop starts renting out tools.")
        base_y, height, x0, bw, gap = 800, 340, 300, 128, 42
        for i, rental in enumerate(mix):
            x = x0 + i * (bw + gap)
            start = 1.2 + i * 0.16
            a = ease_out(window(t, start, 0.5))
            full = height * a
            d.rounded_rectangle([x, base_y - full, x + bw, base_y], radius=10,
                                fill=blend((37, 55, 84), 1.0))
            if rental:
                rh = full * rental
                d.rounded_rectangle([x, base_y - rh, x + bw, base_y], radius=10,
                                    fill=blend(WARN, 1.0))
            d.text((x + bw / 2, base_y + 34), f"wk {i + 1}", font=mono(24),
                   fill=blend(MUTED, a), anchor="mm")
            if rental and window(t, start + 0.35, 0.4) > 0.1:
                d.text((x + bw / 2, base_y - full - 34), f"{rental:.0%}", font=bold(28),
                       fill=blend(WARN, window(t, start + 0.35, 0.4)), anchor="mm")
        rise_text(d, (300, 372), "orders", regular(30), (110, 140, 200), t, 1.2)
        rise_text(d, (300, 420), "rentals — deposits, late fees, damage",
                  regular(30), WARN, t, 1.6)
        rise_text(d, (300, 900), "By week eight, half of everything people asked was rentals.",
                  bold(40), FG, t, 4.3)
        return img

    return Scene("s05_change", seconds, draw)


# ---------------------------------------------------------------------------
# 6. and the tests still pass
# ---------------------------------------------------------------------------
def trap(seconds):
    def draw(d, img, t):
        heading(d, "My tests had zero rental questions.", t,
                sub="I wrote them before rentals existed.")
        for i in range(50):
            col, row = i % 10, i // 10
            x, y = 300 + col * 118, 380 + row * 104
            d.rounded_rectangle([x, y, x + 92, y + 80], radius=14, fill=(26, 44, 33))
            tick(d, (x + 30, y + 24), 34, 1.0, 0.0)
        if t > 1.2:
            a = window(t, 1.2, 0.6)
            d.rounded_rectangle([1330, 380, 1760, 604], radius=22, fill=blend((44, 24, 24), a))
            d.text((1545, 452), "0", font=bold(96), fill=blend(WARN, a), anchor="mm")
            d.text((1545, 540), "about rentals", font=regular(31),
                   fill=blend(WARN, a), anchor="mm")
        if t > 3.0:
            a = window(t, 3.0, 0.5)
            d.rounded_rectangle([1330, 660, 1760, 742], radius=18, fill=blend((22, 60, 38), a))
            d.text((1545, 701), "STILL PASSING", font=bold(34), fill=blend(OK, a), anchor="mm")
        rise_text(d, (300, 916), "Every single time.", bold(44), FG, t, 3.8)
        return img

    return Scene("s06_trap", seconds, draw)


# ---------------------------------------------------------------------------
# 7. how much do my tests look like today's questions?
# ---------------------------------------------------------------------------
def coverage(seconds):
    weeks = [.767, .417, .450, .583, .350, .333, .350, .300]

    def draw(d, img, t):
        heading(d, "Question one.", t,
                sub="How much of what people ask today do my tests look like?")
        for i, value in enumerate(weeks):
            y = 350 + i * 76
            start = 1.4 + i * 0.14
            d.text((300, y + 22), f"week {i + 1}", font=mono(27),
                   fill=blend(MUTED, window(t, start, 0.4)), anchor="lm")
            # The bar has to be the measurement, not a progress indicator:
            # equal-length bars next to different numbers is a lying chart.
            d.rounded_rectangle([460, y, 460 + 900, y + 44], radius=8, fill=PANEL)
            grow_bar(d, (460, y), 900 * value, 44, t, start, 0.6,
                     WARN if value < 0.5 else ACCENT, track=False)
            if window(t, start + 0.3, 0.4) > 0.05:
                d.text((1396, y + 22), f"{value:.0%}", font=bold(30),
                       fill=blend(FG, window(t, start + 0.3, 0.4)), anchor="lm")
        count_text(d, (1620, 380), t, 1.5, 0.8, 0, 77, bold(120), ACCENT, "%", anchor="mm")
        rise_text(d, (1620, 470), "week one", regular(28), MUTED, t, 1.8, anchor="mm")
        count_text(d, (1620, 700), t, 3.6, 1.0, 77, 30, bold(120), WARN, "%", anchor="mm")
        rise_text(d, (1620, 790), "week eight", regular(28), MUTED, t, 3.9, anchor="mm")
        rise_text(d, (300, 966),
                  "Seventy percent of what people ask, I test nothing like.",
                  bold(38), FG, t, 5.4)
        return img

    return Scene("s07_coverage", seconds, draw)


# ---------------------------------------------------------------------------
# 8. would my tests catch it?
# ---------------------------------------------------------------------------
def power(seconds):
    import random

    rng = random.Random(7)
    # 40 x 10 at 28px pitch ends at x=1392, clear of the results panel at 1480.
    # At 33px the grid ran underneath it.
    dots = [(300 + (i % 40) * 28, 430 + (i // 40) * 28) for i in range(400)]
    caught = {i for i in range(400) if rng.random() < 0.012}

    def draw(d, img, t):
        heading(d, "Question two.", t,
                sub="If the bot got worse at rentals tomorrow, would my tests notice?")
        rise_text(d, (300, 352), "break the bot on purpose, four hundred times",
                  regular(29), MUTED, t, 1.0)
        for i, (x, y) in enumerate(dots):
            start = 1.5 + i * 0.0042
            a = window(t, start, 0.25)
            if a > 0.02:
                on = i in caught
                d.ellipse([x, y, x + 17, y + 17],
                          fill=blend(WARN if on else (44, 52, 62), a))
        if t > 4.0:
            a = window(t, 4.0, 0.5)
            d.rounded_rectangle([1480, 420, 1800, 660], radius=24, fill=blend(PANEL, a))
            count_text(d, (1640, 520), t, 4.2, 1.0, 0, 1, bold(112), WARN, "%", anchor="mm")
            d.text((1640, 606), "caught", font=regular(30), fill=blend(MUTED, a), anchor="mm")
        if t > 5.4:
            a = window(t, 5.4, 0.5)
            d.rounded_rectangle([1480, 700, 1800, 812], radius=20, fill=blend((44, 24, 24), a))
            d.text((1640, 738), "0 of 50", font=bold(40), fill=blend(WARN, a), anchor="mm")
            d.text((1640, 786), "tests are about rentals", font=regular(24),
                   fill=blend(WARN, a), anchor="mm")
        rise_text(d, (300, 940), "They'd miss it ninety-nine times out of a hundred.",
                  bold(38), FG, t, 6.4)
        return img

    return Scene("s08_power", seconds, draw)


# ---------------------------------------------------------------------------
# 9. a third answer
# ---------------------------------------------------------------------------
def blind(seconds):
    def draw(d, img, t):
        heading(d, "Every testing tool has two answers.", t)
        boxes = [("PASS", OK, (24, 58, 38), 0.9), ("FAIL", WARN, (58, 26, 26), 1.3),
                 ("BLIND", GOLD, (58, 46, 20), 2.4)]
        for i, (label, colour, fill, start) in enumerate(boxes):
            x = 260 + i * 490
            a = window(t, start, 0.55)
            if a <= 0.01:
                continue
            d.rounded_rectangle([x, 400, x + 400, 620], radius=28, fill=blend(fill, a))
            d.text((x + 200, 510), label, font=bold(72), fill=blend(colour, a), anchor="mm")
        if t > 3.1:
            img2 = glow(img, (1240, 400, 1640, 620), GOLD, min(0.5, window(t, 3.1, 0.8) * 0.5))
            d2 = __import__("PIL.ImageDraw", fromlist=["ImageDraw"]).Draw(img2)
            rise_text(d2, (260, 720), "Blind doesn't mean you're fine.", bold(48), FG, t, 3.6)
            rise_text(d2, (260, 806),
                      "It means: I can't tell — and here's the number that says why.",
                      regular(37), MUTED, t, 4.4)
            return img2
        return img

    return Scene("s09_blind", seconds, draw)


# ---------------------------------------------------------------------------
# 10. and then it fixes it
# ---------------------------------------------------------------------------
def fix(seconds):
    picked = ["I returned NR-942 — where's my deposit?",
              "the sander NR-910 was already damaged",
              "I'm a day late returning NR-934. What happens?"]

    def draw(d, img, t):
        heading(d, "And then it fixes it.", t,
                sub="It finds the real conversations your tests can't see.")
        for i, text in enumerate(picked):
            y = 380 + i * 128
            start = 1.0 + i * 0.55
            if panel(d, (260, y, 1360, y + 104), t, start, radius=18):
                a = window(t, start, 0.5)
                d.text((300, y + 52), text, font=regular(33), fill=blend(FG, a), anchor="lm")
        if t > 3.4:
            a = window(t, 3.4, 0.6)
            d.rounded_rectangle([1440, 380, 1780, 636], radius=24, fill=blend(PANEL, a))
            d.text((1610, 440), "you decide", font=bold(36), fill=blend(FG, a), anchor="mm")
            tick(d, (1500, 500), 60, t, 3.9)
            cross(d, (1660, 505), 54, t, 4.2)
            d.text((1610, 596), "right or wrong", font=regular(26),
                   fill=blend(MUTED, a), anchor="mm")
        rise_text(d, (260, 828), "A person. Not the AI.", bold(46), GOLD, t, 5.0)
        rise_text(d, (260, 906),
                  "If I let the AI grade its own homework, I've proved nothing.",
                  regular(35), MUTED, t, 5.8)
        return img

    return Scene("s10_fix", seconds, draw)


# ---------------------------------------------------------------------------
# 11. the result
# ---------------------------------------------------------------------------
def result(seconds):
    def draw(d, img, t):
        heading(d, "Same traffic. Same bug. Same everything.", t,
                sub="The only thing that changed is what the tests contain.")
        pairs = [("How much of today's questions my tests look like", 30, 60, 1.2),
                 ("Would they catch that rentals bug", 1, 43, 3.2)]
        for i, (label, lo, hi, start) in enumerate(pairs):
            y = 400 + i * 250
            rise_text(d, (260, y), label, regular(33), MUTED, t, start - 0.3)
            count_text(d, (300, y + 120), t, start, 0.35, lo, lo, bold(96), DIM, "%",
                       anchor="mm")
            a = window(t, start + 0.5, 0.4)
            if a > 0.05:
                d.text((470, y + 120), "→", font=bold(72), fill=blend(MUTED, a), anchor="mm")
            count_text(d, (700, y + 120), t, start + 0.7, 1.1, lo, hi, bold(112), OK, "%",
                       anchor="mm")
            d.rounded_rectangle([900, y + 92, 900 + 780, y + 148], radius=8, fill=PANEL)
            grow_bar(d, (900, y + 92), 780 * (lo / 100), 56, t, start, 0.35,
                     DIM, track=False)
            grow_bar(d, (900, y + 92), 780 * (hi / 100), 56, t, start + 0.7, 1.1,
                     blend(OK, 0.75), track=False)
        rise_text(d, (260, 936), "Still not finished — and it tells me that too.",
                  regular(35), MUTED, t, 5.4)
        return img

    return Scene("s11_result", seconds, draw)


# ---------------------------------------------------------------------------
# 12. close
# ---------------------------------------------------------------------------
def close(seconds):
    def draw(d, img, t):
        rise_text(d, (960, 300), "Everyone knows tests go stale.", bold(62), FG, t, 0.3,
                  anchor="ma")
        rise_text(d, (960, 400), "Nobody has a number for how stale yours are right now.",
                  bold(54), GOLD, t, 1.2, anchor="ma")
        if panel(d, (620, 580, 1300, 690), t, 2.8, radius=18):
            a = window(t, 2.8, 0.5)
            d.text((960, 635), "pip install livingeval", font=mono(40, True),
                   fill=blend(OK, a), anchor="mm")
        rise_text(d, (960, 760), "Runs on your machine. Costs nothing.",
                  regular(34), MUTED, t, 3.6, anchor="ma")
        rise_text(d, (960, 840), "github.com/itsskofficial/livingeval",
                  mono(30), ACCENT, t, 4.2, anchor="ma")
        return img

    return Scene("s12_close", seconds, draw)


BUILDERS = {
    "s01_hook": hook, "s02_app": app, "s03_bug": bug, "s04_tests": tests,
    "s05_change": change, "s06_trap": trap, "s07_coverage": coverage,
    "s08_power": power, "s09_blind": blind, "s10_fix": fix,
    "s11_result": result, "s12_close": close,
}

TAIL = 1.0   # a beat of held frame after the line ends, before the cut


def main() -> int:
    from demoforge.motion import render

    if not NARRATION.exists():
        print(f"no narration manifest at {NARRATION}; run demoforge.voice script first")
        return 1
    measured = {n["id"]: n["seconds"] for n in json.loads(NARRATION.read_text("utf-8"))}

    wanted = sys.argv[1:] or list(BUILDERS)
    order, at = [], 0.0
    for name in BUILDERS:
        seconds = round(measured.get(name, 8.0) + TAIL, 2)
        if name in wanted:
            render(BUILDERS[name](seconds))
        order.append({"segment": name, "step": name.split("_", 1)[1], "length": seconds})
        at += seconds
    (ROOT / "out" / "segments" / "order-livingeval3.json").write_text(
        json.dumps(order, indent=1), encoding="utf-8")
    print(f"\n  total {int(at) // 60}:{at % 60:05.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
