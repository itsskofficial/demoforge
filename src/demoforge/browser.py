"""Drive a real browser and keep the recording.

Playwright drives a real Chromium and records it, so this works whether or not
anyone is looking at the screen -- no window has to be visible, focused or
unlocked. The clicks are real clicks against the real server; the only thing
added is a drawn cursor, because a browser's own pointer is not in the capture.

This is the engine only. What to open and where to click belongs to the
project: a shot is a function of `(page, hand)`, and `session` records one.

    from demoforge.browser import Hand, session, visit

    def tour(page, hand: Hand) -> None:
        visit(page, hand, "/")              # relative to DEMOFORGE_BASE_URL
        hand.click("text=Settings")
        hand.scroll(700)

    session("s3_tour", tour)                # -> out/segments/s3_tour.mp4

`projects/livingeval3/capture_browser.py` is a worked example.
"""

from __future__ import annotations

import math
import subprocess
import time
from pathlib import Path
from typing import Callable

from demoforge.config import BASE_URL as BASE, HEIGHT, OUT as _OUT, SEGMENTS as OUT, WIDTH
from demoforge.media import duration

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

    def place(self, x: float, y: float) -> None:
        """Put the cursor somewhere without travelling, e.g. on a fresh page."""
        self.x, self.y = x, y
        self.page.evaluate("([x,y]) => window.__moveCursor && window.__moveCursor(x,y)",
                           [x, y])

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


def visit(page, hand: Hand, url: str, at: tuple[float, float] = (960, 900)) -> None:
    """Open a page and put the drawn cursor on it.

    The init script runs before there is a body to attach to, so the cursor is
    injected again once the page has loaded -- that second one is the one that
    is actually seen. A leading `/` is relative to the project's server.
    """
    page.goto(f"{BASE}{url}" if url.startswith("/") else url, wait_until="networkidle")
    page.evaluate(CURSOR)
    hand.place(*at)


def finish(video_path: Path, out: Path, fps: int = 30,
           pad: str = "0x0d1117") -> Path:
    """Re-encode Playwright's webm to the frame every other segment uses."""
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(video_path),
         "-vf", f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease,"
                f"pad={WIDTH}:{HEIGHT}:(ow-iw)/2:(oh-ih)/2:color={pad},fps={fps}",
         "-c:v", "libx264", "-preset", "medium", "-crf", "18",
         "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out)],
        check=True,
    )
    print(f"  {out.name}  {duration(out):.2f}s")
    return out


def session(name: str, body: Callable, out_dir: Path = OUT) -> Path:
    """Record one shot: a fresh browser, `body(page, hand)`, then `finish`."""
    # Imported here so a project that only wants `CURSOR` for its own
    # Playwright script does not need this module to pull it in first.
    from playwright.sync_api import sync_playwright

    RAW.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--force-color-profile=srgb",
                                          "--hide-scrollbars"])
        context = browser.new_context(
            viewport={"width": WIDTH, "height": HEIGHT},
            record_video_dir=str(RAW),
            record_video_size={"width": WIDTH, "height": HEIGHT},
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
    return finish(src, out_dir / f"{name}.mp4")
