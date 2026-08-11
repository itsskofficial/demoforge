<br/>
<p align="center">

  <h3 align="center">demoforge</h3>

  <p align="center">
    Product demo videos that rebuild themselves — your commands, your voice, your face
    <br/>
    <br/>
    <a href="./docs/quickstart.md">Quickstart</a>
    ·
    <a href="./skills">Skills</a>
    ·
    <a href="https://github.com/itsskofficial/demoforge/issues">Report Bug</a>
  </p>
</p>

![License](https://img.shields.io/badge/license-Apache%202.0-blue)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)

## About The Project

A product demo goes stale the moment the product changes. The numbers on screen
are wrong, the CLI moved, and re-recording means setting up the environment,
running the commands without fumbling, reading a script into a microphone, and
editing it together again. So nobody does it, and the demo on the landing page
quietly describes software that no longer exists.

**demoforge** treats a demo as something you *build*, not something you
*perform*. It reads your codebase and proposes a script. The commands run for
real and their output is captured with its timing. The narration is spoken by a
clone of your voice. Your face is lip-synced to it and dropped in the corner.
Change the product, run it again, get a current demo.

Everything runs on your machine. No upload, no per-minute pricing, no account.

**Nothing on screen is staged.** Every terminal frame is real captured output,
and browser segments are a real browser driving a real server. Two things are
constructed and both are stated in the handoff: dead air is compressed, with the
real elapsed time left on screen, and title cards are drawn rather than captured.

## Built With

* [Chatterbox](https://github.com/resemble-ai/chatterbox) — zero-shot voice cloning
* [LatentSync](https://github.com/bytedance/LatentSync) — lip synchronisation
* [Playwright](https://playwright.dev/) — headless browser recording
* [Pillow](https://python-pillow.org/) — motion graphics
* [FFmpeg](https://ffmpeg.org/)
* [Claude](https://www.anthropic.com/) — codebase understanding

## Getting Started

### Prerequisites

* **Python 3.10+** and **ffmpeg** on `PATH`
* A **CUDA GPU** for the voice and face stages. Both run on CPU, slowly.
* About **12 GB of disk** for model weights

### Installation

```sh
git clone https://github.com/itsskofficial/demoforge
cd demoforge
python -m venv .venv --system-site-packages
.venv/Scripts/pip install -e ".[all]"
demoforge doctor
```

`doctor` tells you what is missing and the command to fix it. Start there.

> **Do not reinstall torch.** Create venvs with `--system-site-packages` and add
> only what is genuinely absent. The model repos pin old torch versions, but the
> pins are conservative — see [skills/lip-sync](./skills/lip-sync/SKILL.md).

## Usage

### The whole thing

```sh
demoforge init  --repo ../yourproject      # asks for a voice clip, a face clip, a key
demoforge voice --script projects/yourproject/narration.json
demoforge build --project yourproject
demoforge music --video out/yourproject-final.mp4 --style lofi
```

`init` is the whole onboarding: it checks the toolchain, asks for the three
things only you can supply, prepares them, reads your codebase and drafts a
script. Everything it asks for is skippable — a repo with no face clip still
produces a narrated demo.

Out comes a narrated demo with you in the corner, plus a timecode table.

### Stage by stage

| Stage | What it does | Cost |
|---|---|---|
| `plan` | Reads the repo, proposes scenes and narration | seconds |
| `voice` | Clones a voice, speaks the script | minutes |
| *scenes* | Draws animated cards, replays captured terminals | minutes |
| `assemble` | Fits picture to narration, lays audio under | seconds |
| `face` | Lip-syncs the presenter | **hours** |
| `compose` | Drops the head in the corner | seconds |
| `music` | Scores it, ducked under the narration | seconds |

Each stage writes files the next one reads, so any of them re-runs alone.
That matters because the face stage runs at roughly 20× realtime: **lock the
script and the voice before you run it.**

## How It Works

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
     one cut + timecodes
```

## Skills

Each capability is documented as a standalone skill, readable on its own and
usable by an agent:

* [codebase-understanding](./skills/codebase-understanding/SKILL.md) — repo → demo plan
* [screen-capture](./skills/screen-capture/SKILL.md) — terminals and browsers without a screen
* [motion-graphics](./skills/motion-graphics/SKILL.md) — drawing what you cannot record
* [voice-cloning](./skills/voice-cloning/SKILL.md) — a voice from one clip, and how to slow it down
* [lip-sync](./skills/lip-sync/SKILL.md) — record once, re-dub forever
* [video-assembly](./skills/video-assembly/SKILL.md) — fitting, muxing, picture-in-picture
* [audio-mix](./skills/audio-mix/SKILL.md) — a licence-free bed, ducked under the voice

## Design Decisions

* **Nothing is captured off the physical screen.** Terminal segments replay
  captured output; browser segments record headless. A render does not depend on
  the machine being awake, unlocked, or free of notifications.

* **Pacing is anchored to output, not timestamps.** A hold matches a line of real
  text, so re-capturing on a faster machine does not desynchronise the edit.

* **The picture fits the words, by holding frames.** Narration length is only
  known after it is spoken. Segments extend by freezing the last frame — slowing
  the footage instead looks broken.

* **The presenter appears only while speaking.** Lip-sync models regenerate the
  mouth over silence, so a face left on screen through a pause makes expressions
  that belong to words nobody is hearing.

* **The planner never runs what it proposes.** Commands are written to a file for
  a human to read. "Let a model read a repo and run the shell commands it chose"
  is not a shape this should have.

* **Voice references are gitignored.** A cloned voice is someone's identity; the
  sample stays on the machine that recorded it.

* **The engine knows nothing about your project.** A profile under `projects/`
  supplies commands, pacing and running order. Adding a second project means
  adding a profile, not touching `src/`.

## Roadmap

* Auto-generate scene visuals from the plan, instead of hand-written profiles
* Captions and burned-in subtitles
* A hosted-render path for people without a GPU
* Multi-language narration from one script
* B-roll from the repo: architecture diagrams, dependency graphs

## Tests

```sh
python -m pytest tests -q
```

Seventeen fast tests over the parts with no model, GPU or ffmpeg in them:
terminal emulation, narration chunking, easing bounds, text wrapping, and the
arithmetic that keeps picture and narration on one timeline. Those are the
things that would otherwise break a render an hour in and give no clue why.

## Contributing

Contributions are welcome. The most useful thing you can add is a **second
project profile** — this has been built against one repository, and the fastest
way to find what is still secretly livingeval-shaped is to point it at something
else.

1. Fork the project
2. Create your branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes
4. Push and open a pull request

## License

Apache 2.0. See [LICENSE](./LICENSE).

Note that the models this drives carry their own terms — Chatterbox is MIT,
LatentSync is Apache 2.0. If you swap in another model, check its licence before
shipping anything commercial: several popular voice models are non-commercial.

## Authors

* **Sarthak Karandikar** — [itsskofficial](https://github.com/itsskofficial)

## Acknowledgements

* [Resemble AI](https://github.com/resemble-ai/chatterbox) for Chatterbox
* [ByteDance](https://github.com/bytedance/LatentSync) for LatentSync
* [livingeval](https://github.com/itsskofficial/livingeval) — the first thing this recorded
