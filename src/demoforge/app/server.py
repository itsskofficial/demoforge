"""The HTTP face of the app.

Everything the window can do is a request here, and every request is small:
list the projects, read a profile, write one, start a step, watch its log,
show what it made. The heavy lifting is in the subprocesses `jobs.py` runs.

The server only ever binds to localhost. It reads and writes inside the
projects folder and the output folder and nowhere else, and the file
endpoints check that before touching anything -- a page in a webview is still
a page, and the same rules apply as to one in a browser.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from demoforge import __version__
from demoforge.app import catalog, window
from demoforge.app.jobs import Bridge, Runner, cli_argv
from demoforge.config import ROOT
from demoforge.config import HOME as DEFAULT_HOME

STATIC = Path(__file__).with_name("static")
SETTINGS = DEFAULT_HOME / "demoforge.settings.json"
ENV = ROOT / ".env"
KEYS = ("ANTHROPIC_API_KEY", "PIXABAY_API_KEY")
NAME = re.compile(r"[^a-z0-9]+")

@asynccontextmanager
async def lifespan(_app: FastAPI):
    loop = asyncio.get_running_loop()
    bridge.attach(loop)
    if sys.platform == "win32":
        # A browser aborting a video range request closes the socket hard,
        # and the proactor loop reports every one as an exception. It is not.
        default = loop.get_exception_handler()

        def quiet(loop_, context):
            if isinstance(context.get("exception"), ConnectionResetError):
                return
            (default or loop_.default_exception_handler)(context)
        loop.set_exception_handler(quiet)
    yield


app = FastAPI(title="demoforge", version=__version__, docs_url=None, redoc_url=None,
              lifespan=lifespan)
runner = Runner()
bridge = Bridge(runner)


# ---------------------------------------------------------------------------
# settings and paths
# ---------------------------------------------------------------------------


def settings() -> dict[str, Any]:
    base = {"projects_dir": str(DEFAULT_HOME / "projects"),
            "out_dir": str(DEFAULT_HOME / "out"),
            "music_dir": "", "whisper_model": "medium.en"}
    if SETTINGS.exists():
        try:
            base.update(json.loads(SETTINGS.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            pass
    return base


def save_settings(update: dict[str, Any]) -> dict[str, Any]:
    current = settings()
    for key in ("projects_dir", "out_dir", "music_dir", "whisper_model"):
        if key in update and update[key] is not None:
            current[key] = str(update[key])
    SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS.write_text(json.dumps(current, indent=2), encoding="utf-8")
    return current


def projects_dir() -> Path:
    path = Path(settings()["projects_dir"])
    path.mkdir(parents=True, exist_ok=True)
    return path


def out_dir() -> Path:
    path = Path(settings()["out_dir"])
    path.mkdir(parents=True, exist_ok=True)
    return path


def job_env() -> dict[str, str]:
    return {"DEMOFORGE_PROJECTS": str(projects_dir()),
            "DEMOFORGE_OUT": str(out_dir())}


def env_keys() -> dict[str, str]:
    found: dict[str, str] = {}
    if ENV.exists():
        for line in ENV.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                key, value = line.split("=", 1)
                found[key.strip()] = value.strip().strip('"').strip("'")
    for key in KEYS:
        if os.environ.get(key):
            found.setdefault(key, os.environ[key])
    return found


def write_key(key: str, value: str) -> None:
    lines = ENV.read_text(encoding="utf-8").splitlines() if ENV.exists() else []
    kept = [l for l in lines if not l.strip().startswith(f"{key}=")]
    if value:
        kept.append(f"{key}={value}")
    ENV.write_text("\n".join(kept).strip() + "\n", encoding="utf-8")


def allowed(path: Path, write: bool = False) -> Path:
    """A path inside the folders the app is allowed to touch, or a 403."""
    resolved = path.expanduser().resolve()
    roots = [projects_dir().resolve()] + ([] if write else [out_dir().resolve()])
    for root in roots:
        try:
            resolved.relative_to(root)
            return resolved
        except ValueError:
            continue
    raise HTTPException(403, f"not inside the projects or output folder: {path}")


# ---------------------------------------------------------------------------
# projects
# ---------------------------------------------------------------------------


def slug(title: str) -> str:
    name = NAME.sub("-", title.lower()).strip("-")
    return name[:48] or "video"


def _stat(path: Path) -> dict[str, Any]:
    st = path.stat()
    return {"path": str(path), "size": st.st_size, "mtime": st.st_mtime,
            "name": path.name}


def _find(mode: catalog.Mode, art: catalog.Artifact, name: str,
          directory: Path) -> list[Path]:
    pattern = art.pattern.replace("{name}", name)
    base = {"project": directory, "out": out_dir(), "root": ROOT}[art.where]
    if any(ch in pattern for ch in "*?["):
        return sorted(base.glob(pattern))
    path = base / pattern
    return [path] if path.exists() else []


def artifacts(mode: catalog.Mode, name: str, directory: Path) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for art in mode.artifacts:
        found = _find(mode, art, name, directory)
        entry: dict[str, Any] = {**art.public(), "exists": bool(found), "files": []}
        for path in found:
            if path.is_dir():
                entry["files"].append({"path": str(path), "name": path.name,
                                       "count": len(list(path.iterdir()))})
            else:
                info = _stat(path)
                if art.kind in ("video", "image"):
                    info["url"] = media_url(path)
                    if art.kind == "video":
                        info["thumb"] = f"/api/thumb?path={path}"
                entry["files"].append(info)
        out[art.key] = entry
    return out


def media_url(path: Path) -> str:
    return f"/api/media?path={path}"


def project_summary(directory: Path) -> dict[str, Any] | None:
    mode = catalog.detect(directory)
    if not mode:
        return None
    name = directory.name
    profile: dict[str, Any] = {}
    profile_path = directory / mode.profile
    if profile_path.exists():
        try:
            profile = json.loads(profile_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            profile = {"_broken": True}
    arts = artifacts(mode, name, directory)
    output = arts.get(mode.output) if mode.output else None
    latest = max((f["mtime"] for a in arts.values() for f in a["files"]
                  if "mtime" in f), default=profile_path.stat().st_mtime
                 if profile_path.exists() else directory.stat().st_mtime)
    deliverable = output["files"][-1] if output and output["files"] else None
    return {
        "name": name, "mode": mode.key, "title": profile.get("title") or name,
        "aspect": profile.get("aspect", mode.aspect), "path": str(directory),
        "updated": latest, "output": deliverable,
        "built": bool(deliverable),
        "steps": step_status(mode, arts),
    }


def step_status(mode: catalog.Mode, arts: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"key": s.key, "label": s.label,
             "done": bool(s.makes) and all(arts.get(k, {}).get("exists") for k in s.makes),
             "ready": all(arts.get(k, {}).get("exists") for k in s.needs)}
            for s in mode.steps]


def project_detail(name: str) -> dict[str, Any]:
    directory = projects_dir() / name
    if not directory.is_dir():
        raise HTTPException(404, f"no project {name}")
    mode = catalog.detect(directory)
    if not mode:
        raise HTTPException(404, f"{name} has no profile the app recognises")
    profile_path = directory / mode.profile
    profile = json.loads(profile_path.read_text(encoding="utf-8")) \
        if profile_path.exists() else {}
    arts = artifacts(mode, name, directory)
    detail = {
        "name": name, "mode": mode.key, "path": str(directory),
        "title": profile.get("title") or name,
        "profile": profile, "profile_path": str(profile_path),
        "artifacts": arts, "steps": step_status(mode, arts),
        "plan": plan_summary(mode, directory),
        "files": folder_listing(directory),
        "jobs": [j for j in runner.recent(200) if j["project"] == name][:20],
        "home": str(out_dir() / name),
    }
    return detail


def plan_summary(mode: catalog.Mode, directory: Path) -> dict[str, Any] | None:
    """The cut as a table, for the modes that have one."""
    path = directory / "plan.json"
    if not path.exists() or mode.key not in ("edit", "reel", "demo"):
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"error": "plan.json is not valid JSON"}
    if mode.key == "demo":
        return {"kind": "scenes", "rows": [
            {"id": s.get("id"), "visual": s.get("visual", "card"),
             "text": s.get("narration", "")[:160],
             "extra": s.get("command") or s.get("url") or ""}
            for s in data.get("scenes", [])]}
    rows = []
    for section in data.get("sections", []):
        card = section.get("card") or section.get("slide") or {}
        rows.append({
            "id": section.get("id"), "start": section.get("start"),
            "end": section.get("end"), "shot": section.get("shot", ""),
            "source": section.get("source", ""),
            "headline": card.get("headline") or section.get("banner") or "",
            "layout": card.get("layout", ""),
            "seconds": round((section.get("end") or 0) - (section.get("start") or 0), 2),
            "say": (section.get("say") or section.get("text") or "")[:200],
        })
    return {"kind": "sections", "rows": rows,
            "seconds": round(sum(r["seconds"] for r in rows), 1)}


def folder_listing(directory: Path) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for sub in ("takes", "broll", "captures", "transcripts"):
        folder = directory / sub
        if folder.is_dir():
            out[sub] = [_stat(p) for p in sorted(folder.iterdir())
                        if p.is_file() and not p.name.startswith(".")]
    return out


def create_project(mode: catalog.Mode, name: str, profile: dict[str, Any]) -> Path:
    directory = projects_dir() / name
    if directory.exists() and any(directory.iterdir()):
        raise HTTPException(409, f"a project called {name} already exists")
    directory.mkdir(parents=True, exist_ok=True)
    body = {**catalog.defaults(mode), **profile}
    body.setdefault("title", name)
    if mode.key == "present":
        (directory / "takes").mkdir(exist_ok=True)
        (directory / "takes" / "README.md").write_text(
            "One recording per section, named after its id: `01_hook.mp4`.\n"
            "Two seconds of silence at both ends; they are trimmed.\n",
            encoding="utf-8")
    if mode.key == "reel":
        (directory / "broll").mkdir(exist_ok=True)
    (directory / mode.profile).write_text(json.dumps(body, indent=2, ensure_ascii=False),
                                          encoding="utf-8")
    return directory


# ---------------------------------------------------------------------------
# running a step
# ---------------------------------------------------------------------------


def build_argv(mode: catalog.Mode, step: catalog.Step, name: str, directory: Path,
               profile: dict[str, Any], options: dict[str, Any]) -> list[str]:
    values = {**profile, "project": name, "project_dir": str(directory),
              "out_dir": str(out_dir())}

    def blank(key: str) -> bool:
        return values.get(key) in (None, "")

    def fill(token: str) -> str:
        def sub(match: re.Match) -> str:
            key = match.group(1)
            if blank(key):
                raise HTTPException(400, f"step {step.key} needs `{key}` in the profile")
            return str(values[key])
        return re.sub(r"\{(\w+)\}", sub, token)

    argv = [fill(t) for t in step.argv]
    for group in step.optional:
        if not any(blank(k) for t in group for k in re.findall(r"\{(\w+)\}", t)):
            argv += [fill(t) for t in group]

    for opt in step.options:
        value = options.get(opt.key, opt.default)
        if value in (None, "", False, []):
            continue
        if opt.key == "from_cut":
            argv += ["--from", str(directory / "cut.json")]
        elif opt.kind == "list":
            for item in value:
                argv += [f"--{opt.key}", str(item)]
        else:
            argv += [f"--{opt.key}", str(value)]
    return cli_argv(argv)


# ---------------------------------------------------------------------------
# doctor
# ---------------------------------------------------------------------------


def _importable(name: str) -> bool:
    import importlib.util
    return importlib.util.find_spec(name) is not None


def doctor() -> list[dict[str, Any]]:
    keys = env_keys()
    checks: list[dict[str, Any]] = []

    def add(key: str, label: str, good: bool, detail: str = "", fix: str = "",
            needed_by: str = "") -> None:
        checks.append({"key": key, "label": label, "ok": bool(good), "detail": detail,
                       "fix": fix, "needed_by": needed_by})

    add("ffmpeg", "ffmpeg", shutil.which("ffmpeg") is not None,
        shutil.which("ffmpeg") or "", "winget install Gyan.FFmpeg  ·  brew install ffmpeg",
        "everything")
    add("whisper", "Speech recognition (whisper)", _importable("whisper"), "",
        "pip install openai-whisper", "Editor, Reel")
    add("mediapipe", "Gaze (mediapipe)", _importable("mediapipe"), "",
        "pip install mediapipe", "Reel")
    add("pptx", "Deck reading (python-pptx)", _importable("pptx"), "",
        "pip install python-pptx", "Editor")
    try:
        import torch
        cuda = torch.cuda.is_available()
        detail = torch.cuda.get_device_name(0) if cuda else "CPU only"
        add("torch", "GPU (torch)", True, detail,
            "" if cuda else "transcription will be slow on CPU", "Editor, Reel, Demo")
    except Exception:
        add("torch", "GPU (torch)", False, "", "pip install torch", "Editor, Reel, Demo")
    from demoforge.tools import ENCODER_RAM_GB, free_ram_gb
    free = free_ram_gb()
    add("ram", "System RAM", free is None or free >= ENCODER_RAM_GB,
        f"{free:.1f} GB free" if free is not None else "",
        "close the browser before generating b-roll; the text encoder needs ~10 GB",
        "B-roll: generate")
    add("anthropic", "Anthropic key", bool(keys.get("ANTHROPIC_API_KEY")), "",
        "Settings → keys", "Editor plan, Demo plan")
    add("pixabay", "Pixabay key", bool(keys.get("PIXABAY_API_KEY")), "",
        "Settings → keys. Optional: a local music folder works without it.", "music")
    add("music_dir", "Music folder", bool(settings().get("music_dir")),
        settings().get("music_dir", ""), "Settings → music folder", "music")
    add("chatterbox", "Voice cloning (chatterbox)", _importable("chatterbox"), "",
        "pip install chatterbox-tts", "Demo voice")
    add("lipsync", "Lip-sync (LatentSync)",
        (ROOT / "vendor/latentsync/checkpoints/latentsync_unet.pt").exists(), "",
        "see docs/quickstart.md", "Demo face")
    try:
        from demoforge import broll as brollmod
        stack = all(_importable(m) for m in ("diffusers", "transformers", "sentencepiece", "accelerate", "gguf"))
        add("ltx", "B-roll generation (LTX-Video)",
            brollmod.CHECKPOINT.exists() and stack,
            str(brollmod.MODELS) if brollmod.CHECKPOINT.exists() else "no weights",
            ("pip install -e .[broll]" if not stack else
             "see src/demoforge/broll.py for the weights"),
            "B-roll: generate")
    except Exception:
        add("ltx", "B-roll generation (LTX-Video)", False, "", "", "B-roll: generate")
    add("webview", "Native window (pywebview)", _importable("webview"), "",
        "pip install pywebview", "the app")
    add("playwright", "Browser capture (playwright)", _importable("playwright"), "",
        "pip install playwright && playwright install chromium", "Demo browser scenes")
    add("node", "HyperFrames renderer (node + npx)", shutil.which("npx") is not None, "",
        "install Node.js 20+ (npx hyperframes is fetched on first use)", "Film")
    return checks


# ---------------------------------------------------------------------------
# routes
# ---------------------------------------------------------------------------


@app.get("/api/ping")
def ping() -> dict[str, Any]:
    return {"ok": True, "version": __version__}


@app.get("/api/state")
def state() -> dict[str, Any]:
    return {
        "version": __version__, "root": str(ROOT), "platform": sys.platform,
        "window": window.WINDOW is not None,
        "settings": settings(), "modes": catalog.public(),
        "tools": catalog.public_tools(),
        "faces": sorted(__import__("demoforge.short", fromlist=["FACES"]).FACES),
        "layouts": {"slide": list(__import__("demoforge.slidekit",
                                             fromlist=["LAYOUTS"]).LAYOUTS),
                    "reel": ["step", "punch", "code", "chain", "versus", "stat"]},
        "active": (runner.active().public() if runner.active() else None),
    }


@app.get("/api/doctor")
def api_doctor() -> list[dict[str, Any]]:
    return doctor()


@app.get("/api/settings")
def get_settings() -> dict[str, Any]:
    keys = env_keys()
    return {**settings(), "keys": {k: bool(keys.get(k)) for k in KEYS},
            "env_path": str(ENV), "settings_path": str(SETTINGS)}


@app.put("/api/settings")
async def put_settings(body: dict[str, Any]) -> dict[str, Any]:
    for key in KEYS:
        if key in body.get("keys", {}):
            write_key(key, str(body["keys"][key] or "").strip())
    save_settings(body)
    return get_settings()


@app.get("/api/projects")
def list_projects() -> list[dict[str, Any]]:
    found = []
    for directory in sorted(projects_dir().iterdir()):
        if directory.is_dir() and not directory.name.startswith((".", "_")):
            summary = project_summary(directory)
            if summary:
                found.append(summary)
    found.sort(key=lambda p: p["updated"], reverse=True)
    return found


@app.post("/api/projects")
async def post_project(body: dict[str, Any]) -> dict[str, Any]:
    mode = catalog.MODES.get(body.get("mode", ""))
    if not mode:
        raise HTTPException(400, "unknown mode")
    profile = body.get("profile") or {}
    name = slug(body.get("name") or profile.get("title") or "")
    missing = [f.label for f in mode.fields
               if f.required and not profile.get(f.key)]
    if missing:
        raise HTTPException(400, "missing: " + ", ".join(missing))
    create_project(mode, name, profile)
    return project_detail(name)


@app.get("/api/projects/{name}")
def get_project(name: str) -> dict[str, Any]:
    return project_detail(name)


@app.put("/api/projects/{name}/profile")
async def put_profile(name: str, body: dict[str, Any]) -> dict[str, Any]:
    directory = projects_dir() / name
    mode = catalog.detect(directory)
    if not mode:
        raise HTTPException(404, f"no project {name}")
    profile = body.get("profile")
    if not isinstance(profile, dict):
        raise HTTPException(400, "profile must be an object")
    (directory / mode.profile).write_text(
        json.dumps(profile, indent=2, ensure_ascii=False), encoding="utf-8")
    return project_detail(name)


@app.get("/api/file")
def get_file(path: str) -> dict[str, Any]:
    target = allowed(Path(path))
    if not target.is_file():
        raise HTTPException(404, "no such file")
    if target.stat().st_size > 4_000_000:
        raise HTTPException(413, "too large to show")
    return {"path": str(target), "text": target.read_text(encoding="utf-8",
                                                          errors="replace")}


@app.put("/api/file")
async def put_file(body: dict[str, Any]) -> dict[str, Any]:
    target = allowed(Path(body.get("path", "")), write=True)
    text = body.get("text", "")
    if target.suffix == ".json":
        try:
            json.loads(text)
        except json.JSONDecodeError as exc:
            raise HTTPException(400, f"not valid JSON: {exc}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return {"path": str(target), "ok": True}


@app.post("/api/projects/{name}/run")
async def run_step(name: str, body: dict[str, Any]) -> dict[str, Any]:
    directory = projects_dir() / name
    mode = catalog.detect(directory)
    if not mode:
        raise HTTPException(404, f"no project {name}")
    step = mode.step(body.get("step", ""))
    if not step:
        raise HTTPException(400, f"{mode.name} has no step {body.get('step')!r}")
    profile = json.loads((directory / mode.profile).read_text(encoding="utf-8"))
    argv = build_argv(mode, step, name, directory, profile, body.get("options") or {})
    job = runner.submit(name, mode.key, step.key, argv, job_env(), ROOT,
                        out_dir() / "_app" / "logs" / name)
    return job.public()


@app.post("/api/projects/{name}/import")
async def import_files(name: str, body: dict[str, Any]) -> dict[str, Any]:
    """Copy recordings into a project's own folder.

    Copy, never move: the original is the person's, and a project folder is
    disposable in a way a phone's camera roll is not.
    """
    directory = projects_dir() / name
    if not directory.is_dir():
        raise HTTPException(404, f"no project {name}")
    sub = body.get("into", "takes")
    if sub not in ("takes", "broll", "captures"):
        raise HTTPException(400, "into must be takes, broll or captures")
    target = directory / sub
    target.mkdir(exist_ok=True)
    copied = []
    for source in body.get("paths", []):
        src = Path(source).expanduser()
        if not src.is_file():
            continue
        rename = (body.get("rename") or {}).get(source)
        dest = target / (rename or src.name)
        shutil.copy2(src, dest)
        copied.append(str(dest))
    return {"copied": copied}


# ---------------------------------------------------------------------------
# tools
# ---------------------------------------------------------------------------

TOOL_MEDIA = {".mp4": "video", ".mov": "video", ".webm": "video", ".jpg": "image",
              ".jpeg": "image", ".png": "image", ".wav": "audio", ".mp3": "audio",
              ".m4a": "audio", ".txt": "text", ".srt": "text", ".json": "json",
              ".ass": "text"}


def tool_argv(tool: catalog.Tool, options: dict[str, Any], run_dir: Path) -> list[str]:
    """`demoforge tool <key> --field value ...`, one flag per field.

    Bools become bare flags when true, lists repeat the flag, the corrections
    table travels as JSON. Field keys with underscores become dashed flags,
    which is what the tool parser declares.
    """
    argv = ["tool", tool.key.replace("_", "-"), "--out", str(run_dir)]
    for f in tool.fields:
        value = options.get(f.key, f.default)
        flag = "--" + f.key.replace("_", "-")
        if value in (None, "", [], {}):
            continue
        if f.kind == "bool":
            if value:
                argv.append(flag)
        elif f.kind == "list":
            for item in value:
                argv += [flag, str(item)]
        elif f.kind == "corrections":
            argv += [flag, json.dumps(value, ensure_ascii=False)]
        else:
            argv += [flag, str(value)]
    return cli_argv(argv)


def tool_runs(key: str) -> list[dict[str, Any]]:
    base = out_dir() / "tools" / key
    if not base.is_dir():
        return []
    runs = []
    for folder in sorted(base.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if not folder.is_dir():
            continue
        files = []
        for path in sorted(folder.iterdir()):
            if not path.is_file() or path.name.startswith("."):
                continue
            kind = TOOL_MEDIA.get(path.suffix.lower(), "file")
            info = {**_stat(path), "kind": kind}
            if kind in ("video", "image", "audio"):
                info["url"] = media_url(path)
                if kind == "video":
                    info["thumb"] = f"/api/thumb?path={path}"
            files.append(info)
        runs.append({"name": folder.name, "path": str(folder),
                     "mtime": folder.stat().st_mtime, "files": files})
    return runs[:40]


@app.get("/api/tools")
def list_tools() -> dict[str, Any]:
    return catalog.public_tools()


@app.get("/api/tools/{key}/runs")
def get_tool_runs(key: str) -> list[dict[str, Any]]:
    if key not in catalog.TOOLS:
        raise HTTPException(404, f"no tool {key}")
    return tool_runs(key)


@app.post("/api/tools/{key}/run")
async def run_tool(key: str, body: dict[str, Any]) -> dict[str, Any]:
    tool = catalog.TOOLS.get(key)
    if not tool:
        raise HTTPException(404, f"no tool {key}")
    options = body.get("options") or {}
    missing = [f.label for f in tool.fields if f.required and not options.get(f.key)]
    if missing:
        raise HTTPException(400, "missing: " + ", ".join(missing))
    seed = ""
    for f in tool.fields:
        if f.kind in ("path", "text", "textarea") and options.get(f.key):
            seed = Path(str(options[f.key])).stem if f.kind == "path" else str(options[f.key])
            break
    stem = re.sub(r"[^A-Za-z0-9]+", "-", seed).strip("-")[:40] or key
    run_dir = out_dir() / "tools" / key / f"{time.strftime('%Y%m%d-%H%M%S')}-{stem}"
    argv = tool_argv(tool, options, run_dir)
    job = runner.submit(f"tool:{key}", "tool", tool.key, argv, job_env(), ROOT,
                        out_dir() / "_app" / "logs" / "tools" / key)
    return {**job.public(), "run_dir": str(run_dir)}


@app.get("/api/jobs")
def list_jobs() -> list[dict[str, Any]]:
    return runner.recent()


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str, since: int = 0) -> dict[str, Any]:
    job = runner.jobs.get(job_id)
    if not job:
        raise HTTPException(404, "no such job")
    return {**job.public(), "tail": runner.tail(job_id, since)}


@app.post("/api/jobs/{job_id}/cancel")
async def cancel_job(job_id: str) -> dict[str, Any]:
    return {"cancelled": runner.cancel(job_id)}


@app.websocket("/ws")
async def events(socket: WebSocket) -> None:
    await socket.accept()
    queue = bridge.subscribe()
    try:
        await socket.send_json({"type": "hello", "jobs": runner.recent(),
                                "active": runner.active().public()
                                if runner.active() else None})
        while True:
            event = await queue.get()
            await socket.send_json(event)
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        bridge.unsubscribe(queue)


MEDIA = (".mp4", ".mov", ".mkv", ".webm", ".m4v", ".jpg", ".jpeg", ".png", ".gif",
         ".mp3", ".wav", ".m4a", ".flac", ".ogg")


def media_file(path: str) -> Path:
    """A media file to preview. Anything the person picked is fair game; only
    media, so the endpoint cannot be turned into a way of reading text files."""
    target = Path(path).expanduser()
    if not target.is_file() or target.suffix.lower() not in MEDIA:
        raise HTTPException(404, "no such media file")
    return target


@app.get("/api/media")
def media(path: str):
    return FileResponse(str(media_file(path)))


@app.get("/api/thumb")
def thumb(path: str, at: float = 0.5):
    target = media_file(path)
    cache = out_dir() / "_app" / "thumbs"
    cache.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha1(f"{target}|{target.stat().st_mtime}|{at}".encode()).hexdigest()
    jpg = cache / f"{key}.jpg"
    if not jpg.exists():
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{at:.2f}", "-i", str(target),
             "-frames:v", "1", "-vf", "scale=640:-2", "-q:v", "4", str(jpg)],
            capture_output=True)
        if not jpg.exists():
            raise HTTPException(500, "could not take a frame")
    return FileResponse(str(jpg), headers={"Cache-Control": "max-age=86400"})


@app.get("/api/probe")
def probe(path: str) -> dict[str, Any]:
    """Duration and size of a media file the person is about to use."""
    target = Path(path).expanduser()
    if not target.is_file():
        raise HTTPException(404, "no such file")
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
             "stream=width,height:format=duration", "-of", "json", str(target)],
            capture_output=True, text=True, check=True).stdout
        data = json.loads(out)
        stream = (data.get("streams") or [{}])[0]
        return {"seconds": float(data.get("format", {}).get("duration", 0) or 0),
                "width": stream.get("width"), "height": stream.get("height")}
    except (subprocess.CalledProcessError, json.JSONDecodeError, FileNotFoundError):
        return {"seconds": 0, "width": None, "height": None}


@app.post("/api/pick")
async def pick(body: dict[str, Any]) -> dict[str, Any]:
    paths = await asyncio.get_running_loop().run_in_executor(
        None, lambda: window.pick(body.get("kind", "file"), bool(body.get("multiple")),
                                  body.get("filters") or None, body.get("directory") or ""))
    return {"paths": paths}


@app.post("/api/open")
async def open_path(body: dict[str, Any]) -> dict[str, Any]:
    target = Path(body.get("path", "")).expanduser()
    if not target.exists():
        raise HTTPException(404, "no such path")
    reveal = bool(body.get("reveal")) and target.is_file()
    if sys.platform == "win32":
        if reveal:
            subprocess.Popen(["explorer", "/select,", str(target)])
        else:
            os.startfile(str(target))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R" if reveal else str(target)] + ([str(target)] if reveal else []))
    else:
        subprocess.Popen(["xdg-open", str(target.parent if reveal else target)])
    return {"ok": True}


@app.post("/api/shortcuts")
async def make_shortcuts() -> dict[str, Any]:
    from demoforge.app import shortcuts
    try:
        made = shortcuts.install()
    except Exception as exc:
        raise HTTPException(500, f"could not create shortcuts: {exc}")
    return {"made": [str(p) for p in made]}


_ICONS: list[str] = []


@app.get("/api/icons")
def icons(q: str = "", limit: int = 80) -> list[str]:
    global _ICONS
    if not _ICONS:
        table = ROOT / "assets/fonts/MaterialSymbols.codepoints"
        _ICONS = [line.split(" ", 1)[0] for line in
                  table.read_text(encoding="utf-8").splitlines() if " " in line]
    needle = q.strip().lower().replace(" ", "_")
    if not needle:
        return _ICONS[:limit]
    starts = [n for n in _ICONS if n.startswith(needle)]
    inside = [n for n in _ICONS if needle in n and not n.startswith(needle)]
    return (starts + inside)[:limit]


@app.get("/api/music")
def music(dir: str = "") -> list[dict[str, Any]]:
    folder = Path(dir or settings().get("music_dir") or "").expanduser()
    if not folder.is_dir():
        return []
    tracks = []
    for path in sorted(folder.rglob("*")):
        if path.suffix.lower() in (".mp3", ".wav", ".m4a", ".flac", ".ogg"):
            tracks.append({"path": str(path), "rel": str(path.relative_to(folder)),
                           "name": path.stem})
    return tracks[:500]


@app.get("/")
def index():
    return FileResponse(str(STATIC / "index.html"),
                        headers={"Cache-Control": "no-store"})


app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")
app.mount("/fonts", StaticFiles(directory=str(ROOT / "assets/fonts")), name="fonts")
