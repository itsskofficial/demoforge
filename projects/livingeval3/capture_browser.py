"""The two browser shots of livingeval: the review queue and the dashboard.

Real clicks against a running livingeval server (DEMOFORGE_BASE_URL, default
http://127.0.0.1:8000), recorded headless by `demoforge.browser`. `scenes.py`
cuts the s11_review beat out of the review recording, so record it before
rendering the scenes.

    python projects/livingeval3/capture_browser.py review
    python projects/livingeval3/capture_browser.py dashboard
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from demoforge.browser import Hand, session, visit  # noqa: E402


def review(page, hand: Hand) -> None:
    visit(page, hand, "/review", at=(960, 900))
    time.sleep(3.0)                       # land on the queue and let it be read
    for _ in range(3):
        page.wait_for_selector(".actions button", timeout=15000)
        time.sleep(3.2)                   # read the conversation on the card
        hand.move(760, 560, 0.6)          # drift over the turns, as if reading
        time.sleep(1.6)
        # Confirm the judge's label rather than overriding it: the point on screen
        # is that a human is the one clicking, not which way they clicked.
        label = ".actions button.pass" if page.locator(".tag.sug-pass").count() \
            else ".actions button.fail"
        hand.click(label)
        time.sleep(1.4)
    time.sleep(2.5)


def dashboard(page, hand: Hand) -> None:
    visit(page, hand, "/", at=(960, 880))
    time.sleep(4.0)
    hand.move(1200, 420, 1.1)
    time.sleep(2.0)
    hand.scroll(700, 1.6)
    time.sleep(3.0)
    hand.scroll(700, 1.4)
    time.sleep(3.5)
    hand.scroll(-1400, 1.4)
    time.sleep(2.5)


# The segment names are the ones the long cut used, and scenes.py still reads
# s5b_review by that name.
SHOTS = {"review": ("s5b_review", review), "dashboard": ("s7_dashboard", dashboard)}


def main(argv: list[str]) -> int:
    wanted = argv or ["review"]
    unknown = [w for w in wanted if w not in SHOTS]
    if unknown or "-h" in wanted or "--help" in wanted:
        print(__doc__)
        return 1 if unknown else 0
    for which in wanted:
        segment, shot = SHOTS[which]
        print(f"[browser] {which}")
        session(segment, shot)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
