<br/>
<p align="center">

  <h3 align="center">demoforge</h3>

  <p align="center">
    Product demo videos that rebuild themselves — screen capture, a cloned voice, and eventually a face
    <br/>
    <br/>
    <a href="./projects/livingeval/HANDOFF.md">See it applied to a real project</a>
  </p>
</p>

## About The Project

A product demo goes stale the moment the product changes. The numbers on screen are
wrong, the UI moved, and re-recording means setting up the environment, running the
commands without fumbling, reading a script into a microphone, and editing it together
again — so nobody does it, and the demo on the landing page quietly describes software
that no longer exists.

**demoforge** treats a demo as something you *build*, not something you *perform*. The
commands run for real and their output is captured with its timing. The narration is
spoken by a clone of your voice from a script held in version control. The segments are
assembled against a running order, and the timecodes fall out of it. Change the product,
run it again, get a current demo.

Nothing on screen is staged: every terminal frame is real captured output, and the
browser segments are a real browser driven against a real server.

## How it fits together

```
  your project
       │
       ▼
  ┌──────────┐   run the real commands, keep the output and its timing
  │ capture  │
  └──────────┘
       │
       ▼
  ┌──────────┐   replay it as video, paced for a voiceover, holding on
  │  render  │   the moments the script has a line about
  └──────────┘
       │            ┌──────────┐  a real browser, recorded headless
       ├────────────│ browser  │
       │            └──────────┘
       │            ┌──────────┐  the beats with no command to run
       ├────────────│  cards   │
       │            └──────────┘
       │            ┌──────────┐  your voice, cloned locally, reading the script
       ├────────────│  voice   │
       │            └──────────┘
       ▼
  ┌──────────┐   one cut, plus the timecode table
  │  stitch  │
  └──────────┘
```

## Layout

```
src/demoforge/       the engine — knows nothing about what it is recording
  capture.py           run a real command, keep stdout and the timing of it
  terminal.py          a small VT emulator and a frame painter
  render.py            replay a capture as video, with holds for the voiceover
  browser.py           drive and record a real browser, headless
  cards.py             title-card primitives
  voice.py             clone a voice with Chatterbox, read a script
  stitch.py            concatenate to a master and write timecodes
  config.py            where things live

projects/<name>/     a profile: the commands, the pacing, the running order
assets/voice/        reference clips (gitignored — personal data)
out/                 captures, segments, audio, masters
```

The split matters: the engine takes no position on what a demo contains, and a profile
is a few hundred lines of "run this, hold there". Adding a second project means adding a
profile, not touching `src/`.

## Getting Started

### Prerequisites

* **Python 3.10+**, **ffmpeg** on `PATH`.
* A **CUDA GPU** if you want the voice half to be fast. It runs on CPU, slowly.

### Installation

```sh
python -m venv .venv --system-site-packages
.venv/Scripts/pip install -e ".[all]"
```

Chatterbox pins `torch==2.6.0`. On Windows, install the CUDA build first or you get a
CPU-only wheel from PyPI:

```sh
.venv/Scripts/pip install torch==2.6.0 torchaudio==2.6.0 --index-url https://download.pytorch.org/whl/cu124
```

## Usage

Point it at the project you are recording, then run a profile:

```sh
export DEMOFORGE_TARGET=/path/to/your/project

python -m demoforge.capture step4.json -- python -m your.demo measure   # real run
python projects/<name>/build.py                                        # render segments
python -m demoforge.browser review                                     # browser segments
python -m demoforge.stitch                                             # master + timecodes
```

### The voice

```sh
python -m demoforge.voice prepare --src recording.mp3 --start 8 --dur 16
python -m demoforge.voice say --text "one line, to hear whether it sounds like you"
python -m demoforge.voice script --script projects/<name>/narration.json
```

The reference clip never leaves the machine. That is most of the reason the voice model
here is local rather than an API.

## Design Decisions

* **Nothing is captured off the physical screen.** Terminal segments are replayed from
  captured output and browser segments are recorded headless, so a render does not depend
  on the machine being awake, unlocked, or free of notifications.

* **Dead air is compressed, and the compression is stated.** Long computations collapse
  to about a second, while the title bar keeps showing the real elapsed time of the run
  that actually happened.

* **Pacing is anchored to output, not to timestamps.** A hold matches a line of real
  text, so re-capturing on a faster machine does not desynchronise the edit.

* **Cards do not impersonate terminals.** A card is something the presenter talks over; a
  card styled as program output implies a run that never happened.

* **Voice cloning is local and consent-gated by construction.** Reference clips are
  gitignored, and Chatterbox watermarks everything it generates.

## Roadmap

* Retime segments automatically from measured narration length, instead of by hand
* The face: re-dub a short base recording with a lip-sync model
* Mix narration onto the master and cut the picture-in-picture
* A second project profile, to find out what is still secretly livingeval-shaped
* Localised narration — the same demo in another language

## License

Apache 2.0.

## Authors

* **Sarthak Karandikar** — [itsskofficial](https://github.com/itsskofficial)

## Acknowledgements

* [Chatterbox](https://github.com/resemble-ai/chatterbox) — the voice model
* [Playwright](https://playwright.dev/) — headless browser recording
* [FFmpeg](https://ffmpeg.org/)
