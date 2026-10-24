<br/>
<p align="center">

  <h3 align="center">demoforge</h3>

  <p align="center">
    Local video creation — demos, presenter cuts, edited talks, reels and shorts, on your machine
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

## Install it as an application

```powershell
# Windows
irm https://raw.githubusercontent.com/itsskofficial/demoforge/main/install.ps1 | iex
```

```bash
# macOS / Linux
curl -fsSL https://raw.githubusercontent.com/itsskofficial/demoforge/main/install.sh | sh
```

Then open **demoforge** from the Start Menu, or run `demoforge app`. One
window, five ways in:

| mode | you bring | it makes |
|---|---|---|
| **Short** | a clip and a few points | a 10-second vertical with cards over footage |
| **Reel** | one long phone take | a cut reel: retakes and silence out, captions, cards, music |
| **Editor** | a deck and raw recordings | a captioned 16:9 film with the slides redrawn in motion |
| **Presenter** | the words, then one take per section | slides drawn to your takes, you full-frame or in the corner |
| **Demo** | a repository | a narrated product demo in a clone of your voice |

And ten **tools** for when you want one thing done to one file and no
project: score, caption, tighten, gaze, cover, punch, voice, lip-sync,
b-roll generate, b-roll search. `demoforge tool caption --video talk.mp4`.

Everything runs locally. The app is a thin window over the same commands
below; anything it does can be repeated from a shell, and every run is
logged with the exact command. See [docs/app.md](./docs/app.md).

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
* [Pixabay Music](https://pixabay.com/music/) — beds, free for commercial use
* [librosa](https://librosa.org/) — ranking tracks on arrangement
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

### Presenter mode — you record the words, demoforge builds the picture

A second path through the same toolkit, for the videos with your name on them.
A cloned voice is convincing right up until someone who knows you watches it,
and a re-dubbed face is convincing right up until it is on a big screen. Your
real voice reading your real script beats any model, and it costs one
afternoon.

```sh
demoforge present script --project yourproject   # what to say, and when
demoforge present intake --project yourproject   # what you have recorded
demoforge present build  --project yourproject   # the cut
```

`script` writes a recording document: one block per take, with the words, the
delivery direction, the framing, and a target duration. You record one file per
take and drop them in `takes/`. `build` renders the slides, composites you into
them and cuts it together.

The inversion is the whole point:

    the generated path knows the picture and discovers the words
    presenter mode knows the words and builds the picture to fit

So a slide is rendered at **exactly** the length of the take that goes over it
— nothing is padded, and re-recording one section re-renders one slide. Slides
schedule their reveals as fractions of the take rather than at fixed seconds,
so a twenty-second delivery and a thirty-second delivery are both paced
correctly instead of one of them ending in a long stare.

Framing is per section: `full` for the moments you are making an argument,
`corner` for the ones where the screen is carrying it, `off` for a beat that
should have the frame to itself.

Both paths stay installed, and they fail in different places — a generated demo
is free to re-render when the product changes, and a recorded one is the one
people believe. See [docs/presenter-mode.md](./docs/presenter-mode.md), and
[projects/probeit](./projects/probeit) for a worked example that also renders
its own vertical cut from the same deck.

### Editor mode — a deck and a pile of raw takes, cut into a film

The third path, and the one that assumes the least about you. `build` writes a
script and speaks it. `present` asks you to record one clean take per section
against a script it wrote first. Both assume the words come before the
recording.

Editor mode assumes the opposite, because that is what people actually have on
the evening they decide to make a video: a deck written last week, and twelve
files in which the same paragraph was attempted four times.

```sh
demoforge edit new    --project talk --deck deck.pptx --footage "~/Videos/2026-08-27*"
demoforge edit ingest --project talk    # transcribe, find the attempts
demoforge edit plan   --project talk    # choose the keepers, design the slides
demoforge edit build  --project talk    # cut, render, caption, score
```

`ingest` transcribes every recording to word-level timestamps and splits each
one into its separate goes at the same paragraph. **From that point nothing
opens the audio again** — which take survived, where a cut lands, what the
caption says at 1:14 are all decisions about a list of words. That is what
stops captions drifting: a word cut from the film was never in the caption
list.

The division of labour is the load-bearing choice, and it is not the obvious
one:

    the model chooses which span, and what the slide says
    arithmetic chooses where exactly the cuts land

A model is genuinely good at *"the third attempt is the one where he doesn't
trail off"* and unreliable at *"and it starts at 41.72 seconds"*. So `plan`
asks for spans and slide content and then snaps every boundary to a whole word.
Filler removal and pause tightening are never asked for at all — they are
computed from word timings, so they are identical on every re-run and work with
no API key at all.

`plan` writes `plan.json` and stops: the whole edit in one document, in seconds
and words. Disagreeing with it means changing a number, and
`build --only 08_evals` re-renders the one section you changed. A cut written
entirely by hand goes through the same settling pass with
`plan --from cut.json`.

The deck is read for **structure**, never rendered into the film. Exporting
slides to PNG gives you a picture of a deck, and a still on screen for twenty
seconds is where attention goes to die — so `slidekit` redraws each one with
every element arriving on its own beat, and the beats are fractions of however
long the take turned out to be.

See [docs/editor-mode.md](./docs/editor-mode.md) and
[projects/vibecoding](./projects/vibecoding) for a worked example: twelve
recordings, thirteen minutes raw, one six-minute cut with word-level captions
and a ducked bed.

### Reel mode — one phone take, cut into a short vertical film

```sh
demoforge reel ingest --project talk    # transcribe, find silences, measure the eye line
demoforge reel plan   --project talk    # settle the cut
demoforge reel build  --project talk    # cut, cards, captions, music
```

The shot list is derived from the footage: `gaze` measures where your eyes
were, and you only go full-frame where they were on the lens. See
[docs/reel-mode.md](./docs/reel-mode.md).

### Short mode — points over ambient footage, nothing filmed

```sh
demoforge short build --project signs   # cards with alpha, over a clip, scored
demoforge short cover --project signs   # a still for the feed
```

Timing is authored, not derived, because there is no speech to derive it
from. A profile is a background clip and a list of cards; the app has a form
for it.

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
  ┌──────────┐  a sourced bed, shaped to the act map and ducked under the voice
  │  music   │
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
* [video-editing](./skills/video-editing/SKILL.md) — bloopers out, deck rebuilt, captions burned
* [reel-editing](./skills/reel-editing/SKILL.md) — one take, the eye line, a vertical cut

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

* **Music is sourced, not synthesised.** A mastered cue grooves and a generated
  one does not. Tracks are ranked on arrangement density by band rather than
  RMS — stock music is limited hard, so total level is nearly flat and ranking
  on dynamic range just picks whichever track has the longest outro.

* **Licences are recorded at download time**, including what they forbid. Most
  stock licences bar redistributing the audio standalone: fine for a bed inside
  a video, and it matters the first time someone asks for the music on its own.

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
* Image-conditioned B-roll, so a cutaway is your desk rather than a stock desk
* A motion-graph presenter: index one long take by pose and gaze, then search
  it for head motion that matches the new delivery instead of looping it

## Tests

```sh
python -m pytest tests -q
```

A hundred fast tests over the parts with no model, GPU or ffmpeg in them:
terminal emulation, narration chunking, easing bounds, text wrapping, the
arithmetic that keeps picture and narration on one timeline, and the table
the app is generated from. Those are the
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
