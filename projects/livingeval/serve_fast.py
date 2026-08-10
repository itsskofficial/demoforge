"""Start the platform for recording, without the startup refit.

`python scripts/dev.py serve` refits the online scorer over all 480 traces
before it binds the port, which takes long enough that a recording session
sits waiting on a dead socket. Nothing being recorded reads the fitted
scorer -- the dashboard and the review queue both read the store -- so the
recording starts it with refit off and everything on screen is the same.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from demo.run import SUITE_NAME, load_env  # noqa: E402

load_env()

# scripts/ is deliberately not on sys.path: it contains its own demo.py, which
# would shadow the demo package this file just imported from.
import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location("livingeval_dev", ROOT / "scripts" / "dev.py")
dev = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dev)

dev.apply_env()

from livingeval import serve  # noqa: E402

print(f"serving suite {SUITE_NAME!r} on http://127.0.0.1:8000", flush=True)
serve.run(port=8000, suite=SUITE_NAME, judge="ollama:qwen2.5:7b", demo=False, refit=False)
