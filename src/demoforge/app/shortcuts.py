"""Putting the app where an installed application lives.

A Start Menu entry and a desktop icon on Windows, a `.desktop` file on
Linux, and a small launcher app on macOS. Each one runs the interpreter this
was installed into with `-m demoforge.cli app`, so there is exactly one
install and the shortcut is only a pointer to it. Nothing is copied.

Windows uses `pythonw.exe` beside the `python.exe` in use, so no console
opens behind the window. The server's own log goes to a file instead.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from demoforge.config import ROOT

ICON = ROOT / "assets/app/demoforge.ico"
PNG = ROOT / "assets/app/demoforge.png"


def _windowless_python() -> Path:
    python = Path(sys.executable)
    quiet = python.with_name("pythonw.exe")
    return quiet if quiet.exists() else python


def install() -> list[Path]:
    if sys.platform == "win32":
        return _windows()
    if sys.platform == "darwin":
        return _macos()
    return _linux()


def _windows() -> list[Path]:
    made: list[Path] = []
    python = _windowless_python()
    targets = [
        Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs"
        / "demoforge.lnk",
        Path.home() / "Desktop" / "demoforge.lnk",
    ]
    for link in targets:
        if not link.parent.exists():
            continue
        script = (
            "$s = (New-Object -ComObject WScript.Shell).CreateShortcut(%s); "
            "$s.TargetPath = %s; $s.Arguments = '-m demoforge.cli app'; "
            "$s.WorkingDirectory = %s; $s.IconLocation = %s; "
            "$s.Description = 'demoforge: local video creation'; $s.Save()"
        ) % (_ps(str(link)), _ps(str(python)), _ps(str(ROOT)),
             _ps(str(ICON) if ICON.exists() else str(python)))
        subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                       check=True, capture_output=True)
        made.append(link)
    return made


def _ps(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


def _linux() -> list[Path]:
    apps = Path.home() / ".local/share/applications"
    apps.mkdir(parents=True, exist_ok=True)
    entry = apps / "demoforge.desktop"
    entry.write_text(
        "[Desktop Entry]\nType=Application\nName=demoforge\n"
        "Comment=Local video creation: demos, reels, shorts\n"
        f"Exec={sys.executable} -m demoforge.cli app\n"
        f"Icon={PNG if PNG.exists() else 'video-x-generic'}\n"
        f"Path={ROOT}\nTerminal=false\nCategories=AudioVideo;Video;\n",
        encoding="utf-8")
    entry.chmod(0o755)
    return [entry]


def _macos() -> list[Path]:
    bundle = Path.home() / "Applications" / "demoforge.app"
    macos = bundle / "Contents/MacOS"
    macos.mkdir(parents=True, exist_ok=True)
    launcher = macos / "demoforge"
    launcher.write_text(
        f"#!/bin/sh\ncd {_sh(str(ROOT))}\nexec {_sh(sys.executable)} -m demoforge.cli app\n",
        encoding="utf-8")
    launcher.chmod(0o755)
    (bundle / "Contents/Info.plist").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<plist version="1.0"><dict>'
        "<key>CFBundleName</key><string>demoforge</string>"
        "<key>CFBundleExecutable</key><string>demoforge</string>"
        "<key>CFBundleIdentifier</key><string>dev.demoforge.app</string>"
        "<key>CFBundlePackageType</key><string>APPL</string>"
        "<key>LSMinimumSystemVersion</key><string>11.0</string>"
        "</dict></plist>\n", encoding="utf-8")
    return [bundle]


def _sh(text: str) -> str:
    return "'" + text.replace("'", "'\\''") + "'"


def main() -> int:
    for path in install():
        print(f"  {path}")
    return 0
