"""Read a codebase and propose a demo for it.

The hard part of a product demo is not the rendering, it is knowing what the
product *is* and which three minutes of it are worth showing. This walks a
repository the way a new engineer would -- README first, then the packaging
metadata, then the entry points, then the shape of the source tree -- builds a
digest, and asks a model to turn it into a plan: scenes, narration, and the
commands worth running on camera.

The plan is a JSON file you are expected to edit. It is a first draft written
by something that has read your repo but has never used your product.

    python -m demoforge.understand --repo . --out projects/myapp/plan.json

Nothing is executed during planning. Commands the model proposes are written
into the plan for a human to read before anything runs them, because "let a
model pick shell commands and run them" is not a thing this should do quietly.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

from demoforge.config import ROOT

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

ENDPOINT = "https://api.anthropic.com/v1/messages"
MODEL = "claude-sonnet-5"
MAX_FILE = 14000
MAX_DIGEST = 90000

READMES = ["README.md", "README.rst", "README.txt", "readme.md"]
MANIFESTS = ["pyproject.toml", "package.json", "Cargo.toml", "go.mod", "setup.py",
             "requirements.txt", "Makefile", "justfile"]
DOCS = ["DEMO.md", "EXPLAINER.md", "ARCHITECTURE.md", "DECISIONS.md", "docs/index.md",
        "USAGE.md", "GETTING_STARTED.md", "docs/guide.md"]
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build",
             ".mypy_cache", ".pytest_cache", ".ruff_cache", "target", ".next", "vendor"}


def api_key() -> str:
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key:
        env = ROOT / ".env"
        if env.exists():
            for line in env.read_text(encoding="utf-8").splitlines():
                if line.strip().startswith("ANTHROPIC_API_KEY"):
                    key = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break
    if not key:
        raise SystemExit(f"no ANTHROPIC_API_KEY (env, or {ROOT / '.env'})")
    return key


def read(path: Path, limit: int = MAX_FILE) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return text[:limit] + ("\n… (truncated)" if len(text) > limit else "")


def tree(repo: Path, max_entries: int = 400) -> str:
    lines, count = [], 0
    for path in sorted(repo.rglob("*")):
        if count >= max_entries:
            lines.append("… (truncated)")
            break
        if any(part in SKIP_DIRS or part.startswith(".") for part in path.relative_to(repo).parts):
            continue
        if path.is_file():
            lines.append(str(path.relative_to(repo)).replace("\\", "/"))
            count += 1
    return "\n".join(lines)


def entrypoints(repo: Path) -> str:
    """Anything that looks like a way to actually run the thing."""
    found = []
    pyproject = repo / "pyproject.toml"
    if pyproject.exists():
        text = read(pyproject, 6000)
        for match in re.finditer(r"^\s*([\w-]+)\s*=\s*\"([\w.]+):(\w+)\"", text, re.M):
            found.append(f"console script: {match.group(1)} -> {match.group(2)}:{match.group(3)}")
    package = repo / "package.json"
    if package.exists():
        try:
            data = json.loads(read(package, 6000))
            for name, cmd in (data.get("scripts") or {}).items():
                found.append(f"npm script: {name} -> {cmd}")
        except json.JSONDecodeError:
            pass
    for name in ("Makefile", "justfile"):
        path = repo / name
        if path.exists():
            for match in re.finditer(r"^([a-zA-Z][\w-]*):", read(path, 4000), re.M):
                found.append(f"{name} target: {match.group(1)}")
    return "\n".join(found[:60]) or "(none found)"


def digest(repo: Path) -> str:
    parts = [f"# Repository: {repo.name}\n"]
    for name in READMES:
        if (repo / name).exists():
            parts.append(f"\n## {name}\n{read(repo / name)}")
            break
    for name in MANIFESTS:
        if (repo / name).exists():
            parts.append(f"\n## {name}\n{read(repo / name, 5000)}")
    for name in DOCS:
        if (repo / name).exists():
            parts.append(f"\n## {name}\n{read(repo / name, 9000)}")
    parts.append(f"\n## Entry points\n{entrypoints(repo)}")
    parts.append(f"\n## File tree\n{tree(repo)}")
    text = "\n".join(parts)
    return text[:MAX_DIGEST]


SYSTEM = """You plan short product demo videos from a codebase.

You will be given a digest of a repository. Produce a plan for a demo video of
the requested length, for the requested audience.

Rules that matter:
- Lead with the problem the product solves, in the viewer's language. Never open
  with architecture or a feature list.
- Prefer showing a real result over describing a capability.
- Narration must be spoken English: short sentences, no bullet fragments, no
  jargon the stated audience would not use, numbers written as words where it
  helps a text-to-speech engine ("thirty percent", not "30%").
- Every `terminal` scene must name a command that plausibly exists in this repo,
  taken from the entry points or docs. Never invent flags.
- A demo of N seconds needs roughly N*2.4 words of narration total.
- Aim for 8-14 scenes. Every scene earns its place or is cut.

Return ONLY a JSON object:
{
  "product": "one line: what it is",
  "problem": "one line: the pain it removes",
  "audience": "who this cut is for",
  "scenes": [
    {"id": "s01_snake_case",
     "narration": "what the presenter says",
     "visual": "card" | "terminal" | "browser",
     "command": "only for terminal scenes, else null",
     "url": "only for browser scenes, else null",
     "headline": "3-7 words on screen",
     "note": "what the picture should show"}
  ]
}"""


def plan(repo: Path, seconds: int, audience: str, model: str = MODEL) -> dict:
    body = json.dumps({
        "model": model,
        "max_tokens": 8000,
        "system": SYSTEM,
        "messages": [{"role": "user", "content":
                      f"Length: {seconds} seconds.\nAudience: {audience}\n\n{digest(repo)}"}],
    }).encode("utf-8")
    req = urllib.request.Request(ENDPOINT, data=body, headers={
        "x-api-key": api_key(),
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            payload = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"anthropic {exc.code}: {exc.read().decode('utf-8','replace')[:400]}")
    text = "".join(block.get("text", "") for block in payload.get("content", []))
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        raise SystemExit(f"no JSON in response: {text[:400]}")
    return json.loads(match.group(0))


def to_narration(plan_data: dict) -> list[dict]:
    """The plan's narration, in the shape demoforge.voice expects."""
    return [{"id": scene["id"], "segment": scene["id"], "text": scene["narration"]}
            for scene in plan_data["scenes"]]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", default=".")
    ap.add_argument("--out", default=None)
    ap.add_argument("--seconds", type=int, default=180)
    ap.add_argument("--audience", default="developers who have not seen this project before")
    ap.add_argument("--model", default=MODEL)
    ap.add_argument("--digest-only", action="store_true",
                    help="print what would be sent, and send nothing")
    args = ap.parse_args()

    repo = Path(args.repo).resolve()
    if args.digest_only:
        print(digest(repo))
        return 0

    print(f"  reading {repo} …")
    result = plan(repo, args.seconds, args.audience, args.model)
    out = Path(args.out) if args.out else ROOT / "projects" / repo.name / "plan.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=1), encoding="utf-8")

    narration = out.parent / "narration.json"
    narration.write_text(json.dumps(to_narration(result), indent=1), encoding="utf-8")

    print(f"\n  {result['product']}")
    print(f"  problem: {result['problem']}")
    print(f"\n  {len(result['scenes'])} scenes -> {out}")
    for scene in result["scenes"]:
        kind = scene.get("visual", "card")
        extra = scene.get("command") or scene.get("url") or ""
        print(f"    {scene['id']:<22} {kind:<8} {extra[:52]}")
    print(f"\n  narration -> {narration}")
    print("  read the plan before running anything in it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
