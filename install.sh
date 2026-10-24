#!/usr/bin/env sh
# Install demoforge on macOS or Linux and register it as an application.
#
#     curl -fsSL https://raw.githubusercontent.com/itsskofficial/demoforge/main/install.sh | sh
#
# or from a checkout:
#
#     ./install.sh            # the app, Short mode, and the editing modes
#     ./install.sh --light    # the app and Short mode only (no torch)
#     ./install.sh --full     # everything, including voice cloning
#
# It needs python3 (3.10+) and git, and installs ffmpeg with brew or apt if
# it can. Everything lands in one folder: ~/.local/share/demoforge unless the
# script is run from inside a checkout. Re-running it updates and keeps your
# projects.

set -eu

REPO="https://github.com/itsskofficial/demoforge"
EXTRAS="app,speech"
INTO=""
for arg in "$@"; do
  case "$arg" in
    --light) EXTRAS="app" ;;
    --full) EXTRAS="all" ;;
    --into=*) INTO="${arg#--into=}" ;;
  esac
done

say() { printf '  %s\n' "$*"; }
head_() { printf '\n== %s ==\n' "$*"; }

head_ toolchain
PY=""
for c in python3.13 python3.12 python3.11 python3.10 python3 python; do
  if command -v "$c" >/dev/null 2>&1; then
    if "$c" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
      PY="$c"; break
    fi
  fi
done
[ -n "$PY" ] || { echo "Python 3.10+ is required. Install it and run this again."; exit 1; }
say "python: $PY ($($PY --version))"

if ! command -v ffmpeg >/dev/null 2>&1; then
  if command -v brew >/dev/null 2>&1; then say "installing ffmpeg with brew"; brew install ffmpeg
  elif command -v apt-get >/dev/null 2>&1; then say "installing ffmpeg with apt"; sudo apt-get install -y ffmpeg
  else say "ffmpeg not found; install it and run this again"; exit 1
  fi
fi
say "ffmpeg: $(command -v ffmpeg)"
command -v git >/dev/null 2>&1 || { echo "git is required."; exit 1; }

head_ checkout
HERE="$(cd "$(dirname "$0")" 2>/dev/null && pwd || true)"
if [ -n "$INTO" ]; then TARGET="$INTO"
elif [ -n "$HERE" ] && [ -f "$HERE/pyproject.toml" ]; then TARGET="$HERE"
else TARGET="${XDG_DATA_HOME:-$HOME/.local/share}/demoforge"
fi
if [ ! -f "$TARGET/pyproject.toml" ]; then
  say "cloning into $TARGET"; git clone --depth 1 "$REPO" "$TARGET"
elif [ "$TARGET" != "$HERE" ] && [ -d "$TARGET/.git" ]; then
  say "updating $TARGET"; git -C "$TARGET" pull --ff-only
fi
say "demoforge: $TARGET"

head_ packages
VENV="$TARGET/.venv"
[ -x "$VENV/bin/python" ] || { say "creating a virtual environment"; "$PY" -m venv "$VENV"; }
"$VENV/bin/python" -m pip install --upgrade pip --quiet
say "installing demoforge[$EXTRAS]"
(cd "$TARGET" && "$VENV/bin/python" -m pip install -e ".[$EXTRAS]")

# The native window needs the platform webview. Linux wants GTK's WebKit.
if [ "$(uname)" = "Linux" ] && ! "$VENV/bin/python" -c 'import gi; gi.require_version("WebKit2", "4.1")' 2>/dev/null; then
  say "for a native window on Linux: sudo apt-get install python3-gi gir1.2-webkit2-4.1"
  say "without it the app opens in your browser, which works the same."
fi

head_ shortcuts
"$VENV/bin/python" -m demoforge.cli shortcut

head_ done
say "Run:  $VENV/bin/python -m demoforge.cli app"
say "Projects and output live under $TARGET. Change that in Settings."
