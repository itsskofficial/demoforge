# The app

A window over all five modes. Nothing in it makes video; it lists projects,
writes profiles, runs the same commands the CLI would, and shows what came
out.

```bash
demoforge app              # a native window, or your browser if there is none
demoforge app --browser    # the browser on purpose
demoforge app --serve      # only the server, on :8765
demoforge shortcut         # Start Menu + desktop (Windows), .desktop (Linux), .app (macOS)
```

## Installing it as an application

Windows, from any PowerShell:

```powershell
irm https://raw.githubusercontent.com/itsskofficial/demoforge/main/install.ps1 | iex
```

macOS and Linux:

```bash
curl -fsSL https://raw.githubusercontent.com/itsskofficial/demoforge/main/install.sh | sh
```

Either script installs Python and ffmpeg if they are missing, clones the
repository into one folder, makes a virtual environment, installs the
package, and creates the shortcuts. Run it again to update; your projects
stay. `-Light` / `--light` skips the speech stack, which is enough for Short
mode and the presenter mode and is about 200 MB instead of 4 GB. `-Full` /
`--full` adds voice cloning.

This is a checkout plus a venv rather than a frozen executable on purpose.
The speech and vision models are several gigabytes and are updated on their
own schedule; freezing them into an installer means shipping a new installer
every time torch moves. A checkout updates with `git pull`.

## What the window is

```
  ┌──────────┬──────────────────────────────────────────────┐
  │ New video│  What are you making?                        │
  │          │  [Short] [Reel] [Editor] [Presenter] [Demo]  │
  │ SHORT    │                                              │
  │  ·       │  Projects                                    │
  │ REEL     │  [poster] [poster] [poster]                  │
  │  ·       │                                              │
  │ ...      │                                              │
  │ Settings │                                              │
  │ Doctor   │                                              │
  └──────────┴──────────────────────────────────────────────┘
```

**A mode card asks for what that mode needs and nothing else.** A Short wants
a clip and some points; a Reel wants one recording; an Editor project wants a
deck and a folder; a Presenter project wants the words; a Demo wants a
repository. The form is generated from `demoforge.app.catalog`, so the fields,
their help text and their defaults are in one place.

**A project page is the pipeline.** One card per step, in order, each with
what it does, whether it has run, and whether the step before it has. Run is
a button. The log streams into a dock at the bottom of the window with the
current phase and the elapsed time, and Stop kills the job and everything it
started, ffmpeg included.

**Setup is the profile, as a form.** Every field of `short.json`, `reel.json`,
`edit.json`, `presentation.json` or `demo.json`, grouped into basics, look,
speech, sound and advanced, with a raw-JSON view for anything the form does
not cover. Saving writes the file; the CLI reads the same file.

**Plan is the cut, as a table.** For Editor and Reel, `plan.json` is shown as
sections with in, out, shot and what is on screen, and both `plan.json` and a
hand-written `cut.json` are editable in place. For Presenter it is the takes:
each section, whether its recording is there, and an Add button that copies
a file in under the section's name. For Demo it is the scenes the planner
proposed.

**Output is the film.** A player, the cover, open and reveal buttons, and
everything else the build left behind.

## Tools

Everything the modes are built from is also a single command on a single
file, with no project around it. In the window they are the **Tools** page;
in a shell they are `demoforge tool <name>`.

| tool | in | out |
|---|---|---|
| `score` | a video with a voice | the video with a bed under it, ducked, mastered |
| `caption` | a video with speech | the video with word-pop captions, an `.srt`, the transcript |
| `tighten` | a recording | silence, fillers and false starts cut on word boundaries |
| `gaze` | a recording of a face | `gaze.json` and a report of the on-lens windows |
| `cover` | a video and a line or two | a JPEG at the video's own size |
| `punch` | a recording of a face | mirrored, zoomed on the face, a touch faster |
| `voice` | text and a voice clip | a `.wav` of the text in that voice |
| `lipsync` | a face video and audio | the video re-dubbed |
| `broll-generate` | a prose prompt | a four-second shot from LTX-Video |
| `broll-search` | a phrase | stock clips with a `.source.json` licence record each |

```bash
demoforge tool score   --video talk.mp4 --music-dir ~/Music --music-under -9
demoforge tool caption --video talk.mp4 --caption-words 3 --accent lime
demoforge tool tighten --video take.mp4 --pause-cut 0.6 --speed 1.05 --mirror
demoforge tool cover   --video reel.mp4 --line "Stop *vibe coding*." --line "Do this."
```

Each run writes into a fresh folder under `out/tools/<name>/` and prints every
file it made on a line starting with `  -> `. The Results panel on a tool's
page is that folder listing, newest first, with players for anything playable.

The tools are the mode code with the profile taken away, not a second copy:
`score` is Reel's music step, `tighten` is Editor's `tighten()` and `lift()`,
`cover` is Reel's cover generalised to any frame size. A fix in one place is
a fix in both.

## Where things live

Projects and output default to `projects/` and `out/` in the checkout, as
they always have. Settings can move both anywhere. The app hands the chosen
folders to each job through `DEMOFORGE_PROJECTS` and `DEMOFORGE_OUT`, which is
the same mechanism the CLI honours, so a build started in the window and a
build started in a shell see the same files.

Keys go in `.env` beside the code, and are never sent anywhere but the
service they are for. The doctor page shows which ones are set without
showing them.

## The parts

| file | what |
|---|---|
| `demoforge/app/catalog.py` | every mode: fields, steps, artifacts. The UI is derived from it |
| `demoforge/app/jobs.py` | runs a step as a subprocess, streams its log, cancels it |
| `demoforge/app/server.py` | FastAPI: projects, profiles, runs, files, media, settings, doctor |
| `demoforge/app/window.py` | a free port, uvicorn in a thread, pywebview on top; browser fallback |
| `demoforge/app/shortcuts.py` | Start Menu, desktop, `.desktop`, `.app` |
| `demoforge/app/static/` | the page: one HTML file, one stylesheet, one script, no build step |
| `demoforge/tools.py` | the ten tools as one CLI, each a thin call into the mode code |

## Adding a mode

Add a `Mode` to `catalog.py`: its profile file, its fields, its steps as CLI
argv with `{project}` and `{field}` placeholders, and what each step leaves
behind. The sidebar, the New screen, the pipeline, the Setup form and the
Output tab pick it up. Nothing in `app.js` names a mode except the icon.

## Driving it from elsewhere

The server is plain HTTP on localhost and an agent can use it the same way the
page does:

```
GET  /api/state                     modes, settings, version
GET  /api/projects                  every project, its mode, its steps
POST /api/projects                  {mode, name, profile}
GET  /api/projects/{name}           profile, artifacts, plan, jobs
PUT  /api/projects/{name}/profile   {profile}
POST /api/projects/{name}/run       {step, options} -> job
GET  /api/jobs/{id}?since=N         status + log tail
POST /api/jobs/{id}/cancel
WS   /ws                            every job event and log line
GET  /api/doctor                    what is installed
GET  /api/tools                     every tool and its fields
POST /api/tools/{key}/run           {options} -> job, run_dir
GET  /api/tools/{key}/runs          what that tool has made, newest first
```

Every run is logged to `out/_app/logs/<project>/<stamp>-<step>.log` with the
exact command on its first line.
