"""Record the review queue and the dashboard as video.

Playwright drives a real Chromium and records it, so this works whether or not
anyone is looking at the screen -- no window has to be visible, focused or
unlocked. The clicks are real clicks against the real server; the only thing
added is a drawn cursor, because a browser's own pointer is not in the capture.

    python -m demo.record.browser review
    python -m demo.record.browser dashboard
"""

from __future__ import annotations

import math
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

from demoforge.config import BASE_URL as BASE, OUT as _OUT, SEGMENTS as OUT

RAW = _OUT / "_browser_raw"

CURSOR = """
(() => {
  if (document.getElementById('__cursor')) return;
  const c = document.createElement('div');
  c.id = '__cursor';
  c.style.cssText = `position:fixed;left:0;top:0;width:26px;height:26px;z-index:2147483647;
    pointer-events:none;transform:translate(-3px,-3px);transition:none;`;
  c.innerHTML = `<svg viewBox="0 0 24 24" width="26" height="26">
    <path d="M4 2 L4 20 L9 15.5 L12 22 L15 20.5 L12 14.5 L19 14 Z"
          fill="#fff" stroke="#111" stroke-width="1.4" stroke-linejoin="round"/></svg>`;
  const r = document.createElement('div');
  r.id = '__ring';
  r.style.cssText = `position:fixed;left:0;top:0;width:44px;height:44px;border-radius:50%;
    z-index:2147483646;pointer-events:none;border:3px solid rgba(88,166,255,.9);
    transform:translate(-22px,-22px) scale(.2);opacity:0;transition:transform .35s ease-out,opacity .35s;`;
  document.body.appendChild(c); document.body.appendChild(r);
  window.__moveCursor = (x, y) => {
    c.style.left = x + 'px'; c.style.top = y + 'px';
    r.style.left = x + 'px'; r.style.top = y + 'px';
  };
  window.__pulse = () => {
    r.style.transition = 'none'; r.style.transform = 'translate(-22px,-22px) scale(.2)';
    r.style.opacity = '1';
    requestAnimationFrame(() => {
      r.style.transition = 'transform .4s ease-out, opacity .4s';
      r.style.transform = 'translate(-22px,-22px) scale(1.15)';
      r.style.opacity = '0';
    });
  };
})();
"""


class Hand:
    """A cursor that moves the way a hand does: accelerate, arrive, settle."""

    def __init__(self, page) -> None:
        self.page = page
        self.x = 960.0
        self.y = 900.0

    def move(self, x: float, y: float, seconds: float = 0.7) -> None:
        steps = max(2, int(seconds * 60))
        x0, y0 = self.x, self.y
        for i in range(1, steps + 1):
            p = i / steps
            ease = 0.5 - 0.5 * math.cos(math.pi * p)          # ease in and out
            cx = x0 + (x - x0) * ease
            cy = y0 + (y - y0) * ease
            self.page.mouse.move(cx, cy)
            self.page.evaluate("([x,y]) => window.__moveCursor && window.__moveCursor(x,y)",
                               [cx, cy])
            time.sleep(1 / 60)
        self.x, self.y = x, y

    def click(self, selector: str, settle: float = 0.45) -> None:
        box = self.page.locator(selector).first.bounding_box()
        if box is None:
            raise RuntimeError(f"no box for {selector!r}")
        self.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        time.sleep(settle)
        self.page.evaluate("() => window.__pulse && window.__pulse()")
        time.sleep(0.12)
        self.page.mouse.click(self.x, self.y)
        time.sleep(0.35)

    def scroll(self, amount: int, seconds: float = 1.0) -> None:
        steps = max(1, int(seconds * 30))
        for _ in range(steps):
            self.page.mouse.wheel(0, amount / steps)
            time.sleep(seconds / steps)


def _finish(video_path: Path, out: Path, fps: int = 30) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(video_path),
         "-vf", f"scale=1920:1080:force_original_aspect_ratio=decrease,"
                f"pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=0x0d1117,fps={fps}",
         "-c:v", "libx264", "-preset", "medium", "-crf", "18",
         "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out)],
        check=True,
    )
    dur = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "default=nw=1:nk=1", str(out)],
                         capture_output=True, text=True).stdout.strip()
    print(f"  {out.name}  {dur}s")


def _session(name: str, body) -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--force-color-profile=srgb",
                                          "--hide-scrollbars"])
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            record_video_dir=str(RAW),
            record_video_size={"width": 1920, "height": 1080},
            device_scale_factor=1,
        )
        context.add_init_script(CURSOR)
        page = context.new_page()
        try:
            body(page, Hand(page))
        finally:
            video = page.video
            context.close()
            browser.close()
            src = Path(video.path())
    _finish(src, OUT / f"{name}.mp4")


def review(page, hand: Hand) -> None:
    page.goto(f"{BASE}/review", wait_until="networkidle")
    page.evaluate(CURSOR)
    page.evaluate("() => window.__moveCursor(960, 900)")
    time.sleep(3.0)                       # land on the queue and let it be read
    for i in range(3):
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
    page.goto(f"{BASE}/", wait_until="networkidle")
    page.evaluate(CURSOR)
    page.evaluate("() => window.__moveCursor(960, 880)")
    time.sleep(4.0)
    hand.move(1200, 420, 1.1)
    time.sleep(2.0)
    hand.scroll(700, 1.6)
    time.sleep(3.0)
    hand.scroll(700, 1.4)
    time.sleep(3.5)
    hand.scroll(-1400, 1.4)
    time.sleep(2.5)


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "review"
    print(f"[browser] {which}")
    _session({"review": "s5b_review", "dashboard": "s7_dashboard"}[which],
             {"review": review, "dashboard": dashboard}[which])
