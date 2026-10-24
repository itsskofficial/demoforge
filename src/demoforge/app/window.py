"""The window, and the server it looks at.

`demoforge app` starts uvicorn on a free localhost port in a thread and opens
a native window on it through pywebview -- WebView2 on Windows, WebKit on
macOS and Linux. No browser tab, no address bar, and the file dialogs are the
operating system's own, which is the part that makes it feel installed.

If pywebview is missing or its runtime is not there, the same server opens in
the default browser instead. Everything works identically; only the picker
falls back to a typed path.
"""

from __future__ import annotations

import logging
import socket
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path
from typing import Any

WINDOW: Any = None          # the pywebview window, once there is one
TITLE = "demoforge"


def free_port(preferred: int = 0) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", preferred))
        return sock.getsockname()[1]


def serve(host: str, port: int, log_file: Path | None = None) -> threading.Thread:
    import uvicorn

    from demoforge.app.server import app

    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(log_file, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "demoforge.app"):
            logger = logging.getLogger(name)
            logger.addHandler(handler)
            logger.setLevel(logging.INFO)

    config = uvicorn.Config(app, host=host, port=port, log_level="warning",
                            access_log=False)
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, name="demoforge-http", daemon=True)
    thread.start()
    return thread


def wait_for(url: str, seconds: float = 15.0) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url + "/api/ping", timeout=1) as res:
                if res.status == 200:
                    return True
        except Exception:
            time.sleep(0.15)
    return False


def open_window(url: str, icon: Path | None = None) -> bool:
    """A native window on the url. False if there is no webview to be had."""
    global WINDOW
    try:
        import webview
    except ImportError:
        return False
    try:
        WINDOW = webview.create_window(
            TITLE, url, width=1400, height=880, min_size=(980, 640),
            background_color="#0b0c10", text_select=True)
        webview.start(icon=str(icon) if icon and icon.exists() else None,
                      private_mode=False)
        return True
    except Exception as exc:   # no WebView2 runtime, no GTK, a headless box
        logging.getLogger("demoforge.app").warning("no native window: %s", exc)
        WINDOW = None
        return False


def pick(kind: str, multiple: bool = False, filters: list[str] | None = None,
         directory: str = "") -> list[str]:
    """The operating system's own file dialog, from whichever shell we have.

    pywebview's dialog is used when the app is in its own window. Otherwise
    tkinter's, which ships with CPython on Windows and macOS and is usually
    present on Linux -- and if neither works the caller gets an empty list and
    the UI falls back to a typed path.
    """
    if WINDOW is not None:
        try:
            import webview
            if kind == "folder":
                result = WINDOW.create_file_dialog(webview.FOLDER_DIALOG,
                                                   directory=directory)
            else:
                types = _webview_types(filters)
                result = WINDOW.create_file_dialog(
                    webview.OPEN_DIALOG, directory=directory,
                    allow_multiple=multiple, file_types=types)
            return [str(p) for p in (result or [])]
        except Exception as exc:
            logging.getLogger("demoforge.app").warning("dialog failed: %s", exc)
    return _tk_pick(kind, multiple, filters, directory)


def _webview_types(filters: list[str] | None) -> tuple[str, ...]:
    if not filters:
        return ("All files (*.*)",)
    return (f"Files ({';'.join(filters)})", "All files (*.*)")


def _tk_pick(kind: str, multiple: bool, filters: list[str] | None,
             directory: str) -> list[str]:
    out: list[str] = []

    def run() -> None:
        try:
            import tkinter as tk
            from tkinter import filedialog
        except ImportError:
            return
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        try:
            if kind == "folder":
                chosen = filedialog.askdirectory(initialdir=directory or None)
                if chosen:
                    out.append(chosen)
            else:
                types = [("Files", " ".join(filters))] if filters else []
                types.append(("All files", "*.*"))
                if multiple:
                    out.extend(filedialog.askopenfilenames(
                        initialdir=directory or None, filetypes=types))
                else:
                    chosen = filedialog.askopenfilename(
                        initialdir=directory or None, filetypes=types)
                    if chosen:
                        out.append(chosen)
        finally:
            root.destroy()

    # tkinter wants the main thread on macOS; on Windows and Linux a fresh
    # thread is fine and keeps the server responsive while the dialog is up.
    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    thread.join()
    return out


def launch(port: int | None = None, browser: bool = False, serve_only: bool = False,
           host: str = "127.0.0.1", log_file: Path | None = None) -> int:
    port = port or free_port(0 if not serve_only else 8765)
    url = f"http://{host}:{port}"
    serve(host, port, log_file)
    if not wait_for(url):
        print("the server did not come up; see", log_file or "the console")
        return 1
    print(f"  demoforge app  {url}")

    if serve_only:
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            return 0

    from demoforge.config import ROOT
    icon = ROOT / "assets/app/demoforge.ico"
    if not browser and open_window(url, icon):
        return 0
    webbrowser.open(url)
    print("  running in the browser; close this window to stop")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        return 0
