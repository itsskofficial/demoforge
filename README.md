<br/>
<p align="center">

  <h3 align="center">demoforge</h3>

  <p align="center">
    Local video creation: demos, presenter cuts, edited talks, reels, shorts and narrated films, on your machine
    <br/>
    <br/>
    <a href="./docs/app.md">The app</a>
    ·
    <a href="./docs/quickstart.md">Quickstart</a>
    ·
    <a href="./skills">Skills</a>
    ·
    <a href="https://github.com/itsskofficial/demoforge/issues">Report Bug</a>
  </p>
</p>

![License](https://img.shields.io/badge/license-Apache%202.0-blue)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)

## Six ways in

Each mode starts from a different amount of material:

| mode | you bring | it makes | starts with |
|---|---|---|---|
| **Short** | a clip and a few points | a 10-second vertical with cards over footage | `demoforge short build --project X` |
| **Reel** | one long phone take | a cut reel: retakes and silence out, captions, cards, music | `demoforge reel ingest --project X` |
| **Editor** | a deck and raw recordings | a captioned 16:9 film with the slides redrawn in motion | `demoforge edit new --project X --deck d.pptx --footage ...` |
| **Presenter** | the words, then one take per section | slides drawn to your takes, you full-frame or in the corner | `demoforge present script --project X` |
| **Demo** | a repository | a narrated product demo in a clone of your voice | `demoforge init --repo ../X` |
| **Film** | a story recorded line by line, some to camera | a narrated film of camera and animated scenes, scored and mixed | `demoforge film new projects/X` |

And thirteen **tools** for when you want one thing done to one file and no
project: `score`, `caption`, `tighten`, `gaze`, `cover`, `punch`, `voice`,
`lipsync`, `matte`, `restore`, `voice-check`, `broll-generate`,
`broll-search`.

```sh
demoforge tool caption --video talk.mp4
demoforge tool caption --help             # one tool's options
python -m demoforge.tools --help          # every tool, one example each
```

Each tool writes into a fresh folder under `out/tools/<name>/` and is the same
code the modes call, with the profile taken out of the way.

## The app

```sh
demoforge app              # a native window, or your browser if there is none
demoforge shortcut         # Start Menu and desktop (Windows), .desktop (Linux), .app (macOS)
```

One window over all six modes and every tool. It is a thin caller of the same
CLI: anything it does can be repeated from a shell, and every run is logged
with the exact command on its first line. See [docs/app.md](./docs/app.md).

## About The Project

A product demo goes stale the moment the product changes. The numbers on screen
are wrong, the CLI moved, and re-recording means setting up the environment,
running the commands without fumbling, reading a script into a microphone, and
editing it together again. So nobody does it, and the demo on the landing page
quietly describes software that no longer exists.

**demoforge** started by treating a demo as something you *build*, not something
you *perform*. It reads your codebase and proposes a script. The commands run
for real and their output is captured with its timing. The narration is spoken
by a clone of your voice. Your face is lip-synced to it and dropped in the
corner. Change the product, run it again, get a current demo.

The other modes apply the same idea to footage you already have: whatever can
be measured (word times, the eye line, the waveform) is measured, and the
picture is built to fit it.

**Nothing on screen is staged.** Every terminal frame is real captured output,
and browser segments are a real browser driving a real server. Two things are
constructed and both are stated in the handoff: dead air is compressed, with the
real elapsed time left on screen, and title cards are drawn rather than captured.

**It runs on your machine.** No upload, no per-minute pricing, no account. The
exceptions are calls you opt into: `plan` sends a digest of the repository to
Anthropic's API, stock search (`broll-search`, `music_source`) talks to
Pixabay, the Sarvam narrator is a hosted API, and Film mode fetches HyperFrames
through `npx` and GSAP from a CDN.

## Built With

* [Chatterbox](https://github.com/resemble-ai/chatterbox): zero-shot voice cloning
* [IndexTTS-2](https://github.com/index-tts/index-tts): an alternative local narrator, timbre and emotion set separately
* [Sarvam Bulbul](https://www.sarvam.ai/): an alternative hosted narrator
* [LatentSync](https://github.com/bytedance/LatentSync): lip synchronisation
* [GFPGAN](https://github.com/TencentARC/GFPGAN) and [RobustVideoMatting](https://github.com/PeterL1n/RobustVideoMatting): `restore` and `matte`
* [Whisper](https://github.com/openai/whisper): word-level transcription for Editor, Reel and Film
* [MediaPipe](https://developers.google.com/mediapipe): the eye line, face-centred punch-ins, thumbnail scoring
* [LTX-Video](https://github.com/Lightricks/LTX-Video): generated B-roll, through diffusers
* [HyperFrames](https://www.npmjs.com/package/hyperframes) and [GSAP](https://gsap.com/): Film mode's compositions and renderer
* [PyAV](https://pyav.org/) with libdav1d: decoding phone AV1 without dropped frames
* [Playwright](https://playwright.dev/): headless browser recording
* [Pillow](https://python-pillow.org/): motion graphics and cards
* [python-pptx](https://python-pptx.readthedocs.io/): reading a deck for its structure
* [FastAPI](https://fastapi.tiangolo.com/) and [pywebview](https://pywebview.flowrl.com/): the app
* [FFmpeg](https://ffmpeg.org/)
* [Pixabay](https://pixabay.com/): music beds and stock clips, licence recorded at download
* [librosa](https://librosa.org/): ranking tracks on arrangement
* [Claude](https://www.anthropic.com/): codebase understanding

## Getting Started

### Prerequisites

* **Python 3.10+** and **ffmpeg** on `PATH`
* **Node.js 20+** for Film mode (`npx hyperframes` is fetched on first use)
* A **CUDA GPU** for voice, lip-sync, matting, restoration and B-roll. Most of
  it runs on CPU, slowly; B-roll generation wants 8 GB of VRAM.
* About **12 GB of disk** for model weights

### Install it as an application

```powershell
# Windows
irm https://raw.githubusercontent.com/itsskofficial/demoforge/main/install.ps1 | iex
```

```bash
# macOS / Linux
curl -fsSL https://raw.githubusercontent.com/itsskofficial/demoforge/main/install.sh | sh
```

These install the repository's default branch into one folder
(`%LOCALAPPDATA%\demoforge` or `~/.local/share/demoforge`), make a venv,
install `demoforge[app,speech]`, and run `demoforge shortcut`. Run either
from a checkout to install that checkout instead. `-Light` / `--light` is the
app and Short mode only; `-Full` / `--full` adds everything, voice cloning
included. Re-running updates and keeps your projects.

### Install from source

```sh
git clone https://github.com/itsskofficial/demoforge
cd demoforge
python -m venv .venv --system-site-packages
.venv/Scripts/pip install -e ".[all]"
demoforge doctor
```

`doctor` tells you what is missing and the command to fix it. Start there. The
app's Doctor page also checks LTX weights and the native window, and says which
mode needs each.

Where things live is set by environment variables: `DEMOFORGE_HOME` (default:
the checkout), `DEMOFORGE_PROJECTS`, `DEMOFORGE_OUT`, and `DEMOFORGE_MODELS` for
the large model weights kept outside the repo.

> **Do not reinstall torch.** Create venvs with `--system-site-packages` and add
> only what is genuinely absent. The model repos pin old torch versions, but the
> pins are conservative. See [skills/lip-sync](./skills/lip-sync/SKILL.md).

## Usage

### Demo mode: a repository, narrated

```sh
demoforge init  --repo ../yourproject      # asks for a voice clip, a face clip, a key
demoforge voice --script projects/yourproject/narration.json
demoforge build --project yourproject
demoforge music --video out/yourproject-final.mp4 --style lofi --out out/yourproject-scored.mp4
```

`init` is the onboarding: it checks the toolchain, asks for the three things
only you can supply, prepares them, reads your codebase and drafts
`plan.json` and `narration.json`. Everything it asks for is skippable. Scenes
are a `scenes.py` in the project folder; `init` tells you to start from
`projects/livingeval3/scenes.py`.

`demoforge music` with `--video` and `--style` synthesises a bed exactly as
long as the cut, ducks it under the narration and masters the mix to -14 LUFS,
-1 dB true peak. With `--video` alone it lays an existing `--music` file under
the cut the same way; with no `--video` it only writes a bed. For a sourced
track instead of a synthesised one, use `demoforge tool score`.

#### Stage by stage

| Stage | Run it with | What it does | Cost |
|---|---|---|---|
| plan | `demoforge plan --repo ...` | Reads the repo, proposes scenes and narration | seconds |
| voice | `demoforge voice --script ...` | Clones a voice, speaks the script | minutes |
| scenes | `build --only scenes` | Runs the project's `scenes.py`: cards, captured terminals | minutes |
| assemble | `build --only assemble` | Fits picture to narration, lays audio under | seconds |
| face | `build --only face` | Lip-syncs the presenter (`demoforge face --src` prepares the footage first) | **hours** |
| compose | `build --only compose` | Drops the head in the corner | seconds |
| music | `demoforge music ...` | Scores it, ducked under the narration | seconds |

`build` with no `--only` runs scenes, assemble, face and compose in order; for
a demo with no face, run `build --only scenes,assemble`. Each stage also runs
alone as `python -m demoforge.assemble`, `demoforge.face sync` or
`demoforge.compose`, and `python -m demoforge.stitch` cuts the picture alone,
end to end, with a timecode table, for watching the running order before
anything is spoken.

Each stage writes files the next one reads, so any of them re-runs alone.
That matters because the face stage runs at roughly 20x realtime: **lock the
script and the voice before you run it.** See
[docs/quickstart.md](./docs/quickstart.md).

### Presenter mode: you record the words, demoforge builds the picture

A cloned voice is convincing right up until someone who knows you watches it.
Your real voice reading your real script beats any model, and it costs one
afternoon.

```sh
demoforge present script --project yourproject   # what to say, and when
demoforge present intake --project yourproject   # what you have recorded
demoforge present build  --project yourproject   # the cut
```

`script` writes a recording document: one block per take, with the words, the
delivery direction, the framing, and a target duration. You record one file per
take into `takes/`. `build` renders the slides, composites you into them and
cuts it together.

The inversion is the whole point:

    the generated path knows the picture and discovers the words
    presenter mode knows the words and builds the picture to fit

So a slide is rendered at **exactly** the length of the take that goes over it,
and re-recording one section re-renders one slide. Reveals are scheduled as
fractions of the take, so a twenty-second delivery and a thirty-second one are
both paced correctly. Framing is per section: `full`, `corner` or `off`. See
[docs/presenter-mode.md](./docs/presenter-mode.md) and
[projects/probeit](./projects/probeit).

### Editor mode: a deck and a pile of raw takes, cut into a film

Editor mode assumes what people actually have on the evening they decide to
make a video: a deck written last week, and twelve files in which the same
paragraph was attempted four times.

```sh
demoforge edit new    --project talk --deck deck.pptx --footage "~/Videos/2026-08-27*"
demoforge edit ingest --project talk    # transcribe, find the attempts
demoforge edit plan   --project talk    # choose the keepers, design the slides
demoforge edit build  --project talk    # cut, render, caption, score
```

`ingest` transcribes every recording to word-level timestamps and splits each
one into its separate goes at the same paragraph. **From that point nothing
opens the audio again**: which take survived, where a cut lands and what the
caption says are all decisions about a list of words, so captions cannot drift.

    the model chooses which span, and what the slide says
    arithmetic chooses where exactly the cuts land

`plan` writes `plan.json` and stops: the whole edit in one document, in seconds
and words. `build --only 08_evals` re-renders the one section you changed, and
a cut written by hand goes through the same settling pass with
`plan --from cut.json`. The deck is read for **structure**, never rendered into
the film: `slidekit` redraws each slide with every element arriving on its own
beat. See [docs/editor-mode.md](./docs/editor-mode.md) and
[projects/vibecoding](./projects/vibecoding).

### Reel mode: one phone take, cut into a short vertical film

```sh
demoforge reel ingest --project talk    # transcribe, find silences, measure the eye line
demoforge reel plan   --project talk    # settle the cut
demoforge reel build  --project talk    # cut, cards, captions, music
demoforge reel cover  --project talk --at 1.2 --line "Stop *vibe coding*."
```

The shot list is derived from the footage: `gaze` measures where your eyes
were, and you only go full-frame where they were on the lens. See
[docs/reel-mode.md](./docs/reel-mode.md).

### Short mode: points over ambient footage, nothing filmed

```sh
demoforge short build --project signs   # cards with alpha, over a clip, scored
demoforge short cover --project signs   # a still for the feed
```

Timing is authored, not derived, because there is no speech to derive it
from. A profile (`short.json`) is a background clip and a list of cards; the
app has a form for it.

### Film mode: a story recorded line by line, built scene by scene

For a narrated film that is *made* rather than cut: one voice file per line,
the on-camera lines as video with the same numbers, and every other line
playing under an animated HyperFrames scene. The engine builds the voice
spine, the captions, the timeline, the camera scenes, the root composition
with its transitions, the score and the mix. The animated scenes are written
by hand, or by an agent, against the timeline it produces.

```sh
demoforge film new    projects/myfilm      # scaffold film.json, FOOTAGE.md, FILM.md, SCENES.md
demoforge film check  --project myfilm     # validate film.json
demoforge film build  --project myfilm     # decode, spine, captions, timeline, camprep,
                                           #   scenes, root, freeze, score, mix
demoforge film render --project myfilm
demoforge film qa     --project myfilm     # dark frames, clipped words, captions, contact sheets
demoforge film thumbs --project myfilm
```

Every step also runs alone (`demoforge film spine --project myfilm`), and
`--work` / `--into` write somewhere other than the project's own folders, so a
rebuild can be checked against a finished film. Needs Node.js 20+. See
[docs/film-mode.md](./docs/film-mode.md) for the folder, every `film.json`
key and the rules the engine enforces, and
[skills/film-making](./skills/film-making/SKILL.md) for the workflow.

## How Demo mode works

```
  your codebase
       │
       ▼
  ┌──────────┐  read the README, the manifests, the entry points
  │   plan   │  → scenes, narration, commands worth showing
  └──────────┘
       │
       ├──► capture ── run the real commands, keep output and timing
       ├──► browser ── a real Chromium, recorded headless
       ├──► motion  ── the parts no recording can show
       │
       ▼
  ┌──────────┐  your voice, cloned locally, reading the script
  │  voice   │
  └──────────┘
       │
       ▼
  ┌──────────┐  measure the words, fit the picture to them
  │ assemble │
  └──────────┘
       │
       ▼
  ┌──────────┐  your face, re-dubbed, in the corner
  │   face   │
  └──────────┘
       │
       ▼
  ┌──────────┐  a bed sized to the cut and ducked under the voice
  │  music   │
  └──────────┘
       │
       ▼
     one cut
```

## Docs

* [docs/quickstart.md](./docs/quickstart.md): from nothing to a narrated demo
* [docs/app.md](./docs/app.md): the window, the tools, the HTTP API
* [docs/presenter-mode.md](./docs/presenter-mode.md)
* [docs/editor-mode.md](./docs/editor-mode.md)
* [docs/reel-mode.md](./docs/reel-mode.md)
* [docs/film-mode.md](./docs/film-mode.md): the folder, `film.json`, the rules
* [docs/example-plan.json](./docs/example-plan.json): what `plan` writes

### Skills

Each capability is documented as a standalone skill, readable on its own and
usable by an agent:

* [codebase-understanding](./skills/codebase-understanding/SKILL.md): repo → demo plan
* [screen-capture](./skills/screen-capture/SKILL.md): terminals and browsers without a screen
* [motion-graphics](./skills/motion-graphics/SKILL.md): drawing what you cannot record
* [voice-cloning](./skills/voice-cloning/SKILL.md): a voice from one clip, and how to slow it down
* [lip-sync](./skills/lip-sync/SKILL.md): record once, re-dub forever
* [video-assembly](./skills/video-assembly/SKILL.md): fitting, muxing, picture-in-picture
* [audio-mix](./skills/audio-mix/SKILL.md): a bed and effects, ducked under the voice
* [video-editing](./skills/video-editing/SKILL.md): bloopers out, deck rebuilt, captions burned
* [reel-editing](./skills/reel-editing/SKILL.md): one take, the eye line, a vertical cut
* [film-making](./skills/film-making/SKILL.md): a narrated film with Film mode, from approved text to review

## Design Decisions

* **Nothing is captured off the physical screen.** Terminal segments replay
  captured output; browser segments record headless. A render does not depend on
  the machine being awake, unlocked, or free of notifications.

* **Pacing is anchored to output, not timestamps.** A hold matches a line of real
  text, so re-capturing on a faster machine does not desynchronise the edit.

* **The picture fits the words, by holding frames.** Narration length is only
  known after it is spoken. Segments extend by freezing the last frame; slowing
  the footage instead looks broken.

* **Cuts are placed on the waveform, not on transcript times.** Whisper's word
  times are good enough to say *which* words sit at a join and off by up to a
  second on *where*. Every trim is taken from a full-band envelope and lands on
  a whole frame.

* **The presenter appears only while speaking.** Lip-sync models regenerate the
  mouth over silence, so a face left on screen through a pause makes expressions
  that belong to words nobody is hearing.

* **The planner never runs what it proposes.** Commands are written to a file for
  a human to read. "Let a model read a repo and run the shell commands it chose"
  is not a shape this should have.

* **Music is sourced where it can be.** A mastered cue grooves and a generated
  one does not, so the modes and `tool score` look in your music folder first,
  then search. Tracks are ranked on arrangement density by band rather than
  RMS: stock music is limited hard, so ranking on dynamic range just picks
  whichever track has the longest outro. `demoforge music` synthesises a bed
  for when a licence dependency is unacceptable.

* **Licences are recorded at download time**, including what they forbid. Most
  stock licences bar redistributing the audio standalone: fine for a bed inside
  a video, and it matters the first time someone asks for the music on its own.

* **Voice references are gitignored.** A cloned voice is someone's identity; the
  sample stays on the machine that recorded it.

* **The engine knows nothing about your project.** A profile under `projects/`
  (`short.json`, `reel.json`, `edit.json`, `presentation.json`, `demo.json`,
  `film.json`) supplies everything particular to one video. A new video is a new
  profile, not a change to `src/`.

## Roadmap

* Generate Demo-mode scene visuals from the plan, instead of a hand-written `scenes.py`
* Film mode in the app beyond running steps: editing `film.json` and previewing scenes
* A hosted-render path for people without a GPU
* Narration in several languages from one script
* B-roll from the repo: architecture diagrams, dependency graphs
* Image-conditioned B-roll, so a cutaway is your desk rather than a stock desk
* A motion-graph presenter: index one long take by pose and gaze, then search
  it for head motion that matches the new delivery instead of looping it

## Tests

```sh
python -m pytest tests -q
```

About 150 fast tests over the parts with no model, GPU or ffmpeg in them:
terminal emulation, narration chunking, easing bounds, text wrapping, the
arithmetic that keeps picture and narration on one timeline, film.json
validation and anchoring, and the table the app is generated from. Those are
the things that would otherwise break a render an hour in and give no clue why.

## Contributing

Contributions are welcome. The most useful thing you can add is a **project in
a mode that has not met your kind of material yet**: a deck in a different
shape, a phone that records differently, a repository unlike the ones in
`projects/`. What breaks there is what is still secretly shaped like the
projects it was built on.

1. Fork the project
2. Create your branch (`git checkout -b feature/AmazingFeature`)
3. Run the tests, then commit your changes
4. Push and open a pull request

## License

Apache 2.0. See [LICENSE](./LICENSE).

The models this drives carry their own terms: Chatterbox is MIT, LatentSync is
Apache 2.0, and LTX-Video, IndexTTS, GFPGAN and RobustVideoMatting each have
their own. Check a model's licence before shipping anything commercial: several
popular voice models are non-commercial.

## Authors

* **Sarthak Karandikar**: [itsskofficial](https://github.com/itsskofficial)

## Acknowledgements

* [Resemble AI](https://github.com/resemble-ai/chatterbox) for Chatterbox
* [ByteDance](https://github.com/bytedance/LatentSync) for LatentSync
* [livingeval](https://github.com/itsskofficial/livingeval), the first thing this recorded
