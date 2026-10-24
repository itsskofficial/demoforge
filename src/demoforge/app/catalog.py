"""What each mode is, for a screen that has to explain it.

The CLI can assume the person has read the docs. A window cannot, so every
mode is described here once: what it takes in, which file holds its profile,
which fields that profile has and what they mean, which steps run in which
order, and what it leaves behind. The form the app shows, the buttons it
offers and the "done" ticks on the pipeline are all derived from this table
rather than written by hand per mode, so a sixth mode is one more entry.

Nothing here runs anything. `steps` describe argv for `demoforge.cli`, and
`jobs.py` runs them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from demoforge import short as shortmod
from demoforge import slidekit


@dataclass
class Field:
    """One profile field, described well enough to draw a control for it."""

    key: str
    label: str
    kind: str = "text"        # text textarea number bool select path paths folder
                              # color list corrections cards sections repairs json
    help: str = ""
    default: Any = None
    options: list[Any] = field(default_factory=list)
    filters: list[str] = field(default_factory=list)   # file dialog patterns
    step: float | None = None
    min: float | None = None
    max: float | None = None
    required: bool = False
    group: str = "basics"     # basics · look · sound · speech · advanced
    create: bool = True       # asked for on the "new" screen

    def public(self) -> dict[str, Any]:
        return dict(self.__dict__)


@dataclass
class Step:
    key: str
    label: str
    help: str
    argv: list[str]           # after `demoforge`; {project} and {field} substituted
    needs: list[str] = field(default_factory=list)   # artifact keys that should exist first
    # Flag groups appended after `argv`, each only when every field it names is
    # filled in. A blank in `argv` itself is an error; a blank here drops the
    # group, so an optional clip never reaches the CLI as `--src ""`.
    optional: list[list[str]] = field(default_factory=list)
    makes: list[str] = field(default_factory=list)   # artifact keys this produces
    heavy: bool = False       # minutes, not seconds
    options: list[Field] = field(default_factory=list)   # per-run switches

    def public(self) -> dict[str, Any]:
        return {**{k: v for k, v in self.__dict__.items() if k != "options"},
                "options": [o.public() for o in self.options]}


@dataclass
class Artifact:
    key: str
    label: str
    where: str                # "project" or "out"
    pattern: str              # relative path, {name} substituted; globs allowed
    kind: str = "file"        # file video image text json folder

    def public(self) -> dict[str, Any]:
        return dict(self.__dict__)


@dataclass
class Mode:
    key: str
    name: str
    tagline: str
    blurb: str
    needs: list[str]          # what the person has to bring
    profile: str              # the file that marks a project as this mode
    fields: list[Field]
    steps: list[Step]
    artifacts: list[Artifact]
    aspect: str = "16:9"
    output: str = ""          # artifact key of the deliverable
    accent: str = "blue"
    requires: list[str] = field(default_factory=list)   # doctor keys

    def public(self) -> dict[str, Any]:
        return {
            "key": self.key, "name": self.name, "tagline": self.tagline,
            "blurb": self.blurb, "needs": self.needs, "profile": self.profile,
            "aspect": self.aspect, "output": self.output, "accent": self.accent,
            "requires": self.requires,
            "fields": [f.public() for f in self.fields],
            "steps": [s.public() for s in self.steps],
            "artifacts": [a.public() for a in self.artifacts],
        }

    def step(self, key: str) -> Step | None:
        return next((s for s in self.steps if s.key == key), None)

    def artifact(self, key: str) -> Artifact | None:
        return next((a for a in self.artifacts if a.key == key), None)


ASPECTS = ["16:9", "9:16", "1:1"]
SLIDE_ACCENTS = sorted(slidekit.ACCENTS)
REEL_ACCENTS = ["lime", "cyan", "coral", "gold", "violet", "white"]
WHISPER = ["medium.en", "large-v3", "small.en", "base.en"]
VIDEO = ["*.mp4", "*.mov", "*.mkv", "*.webm", "*.m4v"]
AUDIO = ["*.mp3", "*.wav", "*.m4a", "*.flac", "*.ogg"]

_corrections = Field(
    "corrections", "Corrections", "corrections", group="speech", default={},
    help="What the recogniser mis-hears, and what it should say. A product name, "
         "a library, the thing the whole video is about. Longest match wins.")

_music_dir = Field(
    "music_dir", "Your music folder", "folder", group="sound", default="",
    help="A folder of tracks you already own. Searched before anything is fetched.")
_music_file = Field(
    "music_file", "Track", "path", group="sound", default="", filters=AUDIO,
    help="Pin one track, relative to the music folder or absolute. Blank lets the "
         "ranking choose.")
_music_offset = Field(
    "music_offset", "Start the track at", "number", group="sound", default=0.0,
    step=0.5, min=0, help="Seconds into the track. Skip a long intro.")

# ---------------------------------------------------------------------------

SHORT = Mode(
    key="short", name="Short", aspect="9:16", accent="lime",
    tagline="A list of points over ambient footage. Nothing filmed.",
    blurb="You know the five things you want to say and you are not going to film "
          "yourself saying them. Cards with a headline, an icon and a line of "
          "context, over a clip that only has to move. Ten seconds, one afternoon.",
    needs=["A background clip, ideally vertical", "Three to six points"],
    profile="short.json",
    requires=["ffmpeg"],
    fields=[
        Field("title", "Title", "text", required=True,
              help="Only used to name things. The cards carry the words."),
        Field("background", "Background clip", "path", required=True, filters=VIDEO,
              help="Ambient footage. Hands on a keyboard, a café, a server aisle. "
                   "It is cropped to 9:16 and looped or cut to the length of the cards."),
        Field("cards", "Cards", "cards", default=[
            {"kind": "title", "headline": "", "note": "", "seconds": 1.9},
            {"kind": "point", "index": "01", "headline": "", "icon": "bolt",
             "note": "", "seconds": 1.5},
            {"kind": "point", "index": "02", "headline": "", "icon": "bolt",
             "note": "", "seconds": 1.5},
            {"kind": "point", "index": "03", "headline": "", "icon": "bolt",
             "note": "", "seconds": 1.5},
            {"kind": "cta", "headline": "", "note": "save this", "seconds": 1.0},
        ], help="A title, the points, and a close. Each card has how long it stays."),
        Field("face", "Type", "select", group="look", default="bold",
              options=sorted(shortmod.FACES),
              help="hand and marker look written on; editorial is a serif; bold is "
                   "a poster; casual is a note."),
        Field("accent", "Accent", "color", group="look", default="lime",
              options=REEL_ACCENTS),
        Field("scrim", "Darken background", "number", group="look", default=0.0,
              step=0.05, min=0, max=1,
              help="0 leaves the footage exactly as shot. Type carries its own outline."),
        Field("push", "Slow push-in", "number", group="look", default=1.04,
              step=0.01, min=1.0, max=1.3,
              help="How much the background zooms over the run. 1 is none."),
        Field("trim_bottom", "Crop bottom", "number", group="look", default=0.0,
              step=0.01, min=0, max=0.4,
              help="Fraction of the clip's height to cut off the bottom. "
                   "Removes a watermark."),
        Field("music", "Music", "bool", group="sound", default=True),
        _music_dir, _music_file, _music_offset,
        Field("music_target", "Music level", "number", group="sound", default=-14.0,
              step=0.5, min=-30, max=-6, help="LUFS. -14 is streaming loud."),
    ],
    steps=[
        Step("build", "Build", "Render the cards with alpha, prepare the background, "
             "composite, score.", ["short", "build", "--project", "{project}"],
             makes=["short"]),
        Step("cover", "Cover", "A still from the title card, for the feed.",
             ["short", "cover", "--project", "{project}"], needs=["short"],
             makes=["cover"]),
    ],
    artifacts=[
        Artifact("short", "The short", "out", "{name}/{name}-short.mp4", "video"),
        Artifact("cover", "Cover", "out", "{name}/{name}-cover.jpg", "image"),
    ],
    output="short",
)

REEL = Mode(
    key="reel", name="Reel", aspect="9:16", accent="lime",
    tagline="One long phone take, cut into a short vertical film.",
    blurb="You talked at your phone for seven minutes. This finds the words, "
          "throws out the retakes and the silence, measures where your eyes were, "
          "and only puts you full-frame where you were looking at the lens. "
          "Everywhere else gets a card or a cutaway.",
    needs=["One vertical recording of you talking", "Optional: screen recordings for cutaways"],
    profile="reel.json",
    requires=["ffmpeg", "whisper", "mediapipe"],
    fields=[
        Field("title", "Title", "text", required=True),
        Field("source", "The take", "path", required=True, filters=VIDEO,
              help="One continuous vertical recording."),
        Field("speed", "Speed", "number", group="look", default=1.1, step=0.05,
              min=1.0, max=1.3, help="A reel runs slightly fast. Not enough to hear."),
        Field("mirror", "Mirror the presenter", "bool", group="look", default=True,
              help="How most people prefer to see themselves. Cards are never flipped."),
        Field("presenter_zoom", "Presenter zoom", "number", group="look",
              default=1.2, step=0.05, min=1.0, max=1.6,
              help="Punch-in on full-frame shots, centred on the face."),
        Field("accent", "Accent", "color", group="look", default="lime",
              options=REEL_ACCENTS),
        Field("captions", "Captions", "bool", group="speech", default=True),
        Field("caption_words", "Words per caption", "number", group="speech",
              default=3, step=1, min=1, max=6),
        Field("whisper_model", "Recogniser", "select", group="speech",
              default="medium.en", options=WHISPER,
              help="medium.en fits 8 GB of VRAM. large-v3 is better and needs more."),
        _corrections,
        Field("repairs", "Re-hear these windows", "repairs", group="speech", default=[],
              help="Seconds into the take where the transcript was wrong and no "
                   "heuristic caught it. Each window is re-transcribed alone."),
        Field("pause_cut", "Cut pauses over", "number", group="advanced", default=0.42,
              step=0.02, min=0.1, max=2.0, help="Seconds."),
        Field("look_away", "Cut away after", "number", group="advanced", default=0.7,
              step=0.1, min=0.2, max=3.0,
              help="A glance off the lens longer than this, inside a full shot, "
                   "cuts to the section's visual."),
        Field("loudness", "Voice level", "number", group="sound", default=-12.0,
              step=0.5, min=-24, max=-8, help="LUFS."),
        Field("music", "Music", "bool", group="sound", default=True),
        _music_dir, _music_file, _music_offset,
        Field("music_under", "Music under voice", "number", group="sound",
              default=-6.0, step=0.5, min=-24, max=0,
              help="LU below the voice. -6 is scored; -16 is a hint."),
        Field("music_ratio", "Duck depth", "number", group="sound", default=3.0,
              step=0.5, min=1, max=12, help="How hard the bed drops under speech."),
        Field("music_query", "Search for", "list", group="sound",
              default=["energetic trap hip hop beat"],
              help="Used when no local track is pinned."),
    ],
    steps=[
        Step("ingest", "Ingest", "Transcribe to word timestamps, find the silences, "
             "measure the eye line.", ["reel", "ingest", "--project", "{project}"],
             makes=["transcript", "gaze"], heavy=True),
        Step("plan", "Plan", "Settle the cut: sections, shots and cards.",
             ["reel", "plan", "--project", "{project}"], needs=["transcript"],
             makes=["plan"],
             options=[Field("from_cut", "Settle cut.json written by hand", "bool",
                            default=False, create=False)]),
        Step("build", "Build", "Cut, render the cards, caption, score.",
             ["reel", "build", "--project", "{project}"], needs=["plan"],
             makes=["reel"], heavy=True,
             options=[Field("steps", "Only these steps", "text", default="",
                            help="sections,concat,captions,music", create=False)]),
        Step("cover", "Cover", "A cover frame with the hook set across it.",
             ["reel", "cover", "--project", "{project}"], needs=["reel"],
             makes=["cover"],
             options=[Field("line", "Banner lines", "list", default=[],
                            help="One per line. *word* is accented.", create=False),
                      Field("at", "Frame at", "number", default=0.0, step=0.5,
                            create=False)]),
    ],
    artifacts=[
        Artifact("transcript", "Transcript", "project", "transcripts/*.json", "json"),
        Artifact("gaze", "Gaze", "project", "gaze.json", "json"),
        Artifact("plan", "Plan", "project", "plan.json", "json"),
        Artifact("cut", "Cut", "project", "cut.json", "json"),
        Artifact("reel", "The reel", "out", "{name}/{name}-reel.mp4", "video"),
        Artifact("timeline", "Timeline", "out", "{name}/{name}-reel.timeline.json", "json"),
        Artifact("cover", "Cover", "out", "{name}/{name}-cover.jpg", "image"),
    ],
    output="reel",
)

EDIT = Mode(
    key="edit", name="Editor", aspect="16:9", accent="blue",
    tagline="A deck and a pile of raw takes, cut into a film.",
    blurb="A deck written last week and twelve recordings in which the same "
          "paragraph was attempted four times. This transcribes everything, "
          "finds the attempts, keeps the good one of each, redraws every slide "
          "with motion, captions it and scores it.",
    needs=["A .pptx deck", "Your recordings, in any order, with the bloopers left in"],
    profile="edit.json",
    requires=["ffmpeg", "whisper", "pptx"],
    fields=[
        Field("title", "Title", "text", required=True),
        Field("deck", "Deck", "path", required=True, filters=["*.pptx"],
              help="Read for structure. Never rendered into the film."),
        Field("footage", "Recordings", "paths", required=True, filters=VIDEO,
              help="Files, folders or globs. Order is recording order."),
        Field("aspect", "Aspect", "select", default="16:9", options=ASPECTS),
        Field("target_seconds", "Target length", "number", default=0, step=5, min=0,
              help="Seconds. 0 means as tight as it goes."),
        Field("accent", "Accent", "color", group="look", default="blue",
              options=SLIDE_ACCENTS),
        Field("inset", "Presenter inset", "number", group="look", default=330,
              step=10, min=160, max=640, help="Diameter of the corner circle, px."),
        Field("captions", "Captions", "bool", group="speech", default=True),
        Field("whisper_model", "Recogniser", "select", group="speech",
              default="medium.en", options=WHISPER),
        _corrections,
        Field("music", "Music", "bool", group="sound", default=True),
        Field("music_style", "Style", "select", group="sound", default="lofi",
              options=["lofi", "trap"]),
        Field("music_under", "Music under voice", "number", group="sound",
              default=-9.0, step=0.5, min=-24, max=0),
        Field("music_ratio", "Duck depth", "number", group="sound", default=4.0,
              step=0.5, min=1, max=12),
    ],
    steps=[
        Step("ingest", "Ingest", "Read the deck, transcribe every recording, "
             "find the attempts.", ["edit", "ingest", "--project", "{project}"],
             makes=["transcript", "intake"], heavy=True),
        Step("plan", "Plan", "Choose the keeper of each attempt and design the "
             "slide for it. Uses your Anthropic key; falls back to longest take.",
             ["edit", "plan", "--project", "{project}"], needs=["transcript"],
             makes=["plan"],
             options=[Field("from_cut", "Settle cut.json written by hand", "bool",
                            default=False, create=False)]),
        Step("build", "Build", "Cut, render, composite, caption, score.",
             ["edit", "build", "--project", "{project}"], needs=["plan"],
             makes=["film"], heavy=True,
             options=[Field("steps", "Only these steps", "text", default="",
                            help="sections,concat,captions,music", create=False)]),
    ],
    artifacts=[
        Artifact("transcript", "Transcripts", "project", "transcripts/*.json", "json"),
        Artifact("intake", "Intake report", "project", "INTAKE.md", "text"),
        Artifact("plan", "Plan", "project", "plan.json", "json"),
        Artifact("cut", "Cut", "project", "cut.json", "json"),
        Artifact("film", "The film", "out", "{name}/{name}-edited.mp4", "video"),
        Artifact("timeline", "Timeline", "out", "{name}/{name}-edited.timeline.json", "json"),
    ],
    output="film",
)

PRESENT = Mode(
    key="present", name="Presenter", aspect="16:9", accent="blue",
    tagline="You record the words. It builds the picture to fit.",
    blurb="Write what you will say, section by section. It writes you a "
          "recording script with timings. You record one clean take per section. "
          "Each slide is then drawn at exactly the length of its take, with you "
          "full-frame, in the corner, or off.",
    needs=["The words, per section", "One recording per section, named after it"],
    profile="presentation.json",
    requires=["ffmpeg"],
    fields=[
        Field("title", "Title", "text", required=True),
        Field("aspect", "Aspect", "select", default="16:9", options=ASPECTS),
        Field("sections", "Sections", "sections", default=[
            {"id": "01_hook", "presenter": "full", "visual": {"kind": "none"},
             "say": "", "note": "Straight down the lens."},
            {"id": "02_point", "presenter": "corner",
             "visual": {"kind": "slide"}, "say": "",
             "meta": {"slide": {"layout": "statement", "headline": ""}}},
            {"id": "03_close", "presenter": "full", "visual": {"kind": "none"},
             "say": ""},
        ], help="What you will say, how you are framed, and what is behind you."),
    ],
    steps=[
        Step("script", "Script", "Write RECORDING-SCRIPT.md: every take, with its "
             "words, direction and target length.",
             ["present", "script", "--project", "{project}"], makes=["script"]),
        Step("intake", "Intake", "Measure every take you have dropped in, find its "
             "speech, flag the ones worth another go.",
             ["present", "intake", "--project", "{project}"], needs=["script"]),
        Step("build", "Build", "Render each slide to its take, composite you in, cut.",
             ["present", "build", "--project", "{project}"], needs=["script"],
             makes=["film"], heavy=True,
             options=[Field("only", "Only these sections", "text", default="",
                            help="comma-separated ids", create=False)]),
    ],
    artifacts=[
        Artifact("script", "Recording script", "project", "RECORDING-SCRIPT.md", "text"),
        Artifact("takes", "Takes", "project", "takes", "folder"),
        Artifact("film", "The film", "out", "{name}-presented.mp4", "video"),
        Artifact("timeline", "Timeline", "out", "{name}-presented.timeline.json", "json"),
    ],
    output="film",
)

DEMO = Mode(
    key="demo", name="Demo", aspect="16:9", accent="blue",
    tagline="Read a codebase, propose a demo, narrate it in your voice.",
    blurb="The original path. It reads a repository and drafts scenes and "
          "narration, runs the real commands and captures them, speaks the script "
          "in a clone of your voice, and can lip-sync your face into the corner. "
          "Change the product, run it again, get a current demo. The voice and "
          "face stages need their own model stacks; the doctor says what is missing.",
    needs=["A repository", "Optional: a voice clip, a face clip, an Anthropic key"],
    profile="demo.json",
    requires=["ffmpeg", "anthropic"],
    fields=[
        Field("title", "Title", "text", required=True),
        Field("repo", "Repository", "folder", required=True,
              help="The project being demonstrated."),
        Field("seconds", "Target length", "number", default=180, step=10, min=30,
              help="Seconds."),
        Field("audience", "Audience", "text",
              default="developers who have not seen this project before"),
        Field("voice_clip", "Voice clip", "path", group="sound", default="",
              filters=AUDIO + VIDEO,
              help="30 to 60 seconds of you talking. Cloned locally, never uploaded."),
        Field("face_clip", "Face clip", "path", group="look", default="",
              filters=VIDEO, help="20 to 40 seconds looking at the camera."),
        Field("pace", "Pace", "number", group="sound", default=0.85, step=0.05,
              min=0.6, max=1.2, help="Below 1 slows the cloned voice down."),
        Field("music_style", "Music", "select", group="sound", default="lofi",
              options=["lofi", "trap"],
              help="The bed the Music step synthesises. Skip that step for none."),
    ],
    steps=[
        Step("plan", "Plan", "Read the repository and propose scenes and narration. "
             "Nothing it proposes is run.",
             ["plan", "--repo", "{repo}", "--seconds", "{seconds}",
              "--audience", "{audience}", "--out", "{project_dir}/plan.json"],
             makes=["plan"]),
        # The reference is re-cut from the clip on every run, so changing the
        # clip changes the voice; with no clip, the last reference is reused.
        Step("voice", "Voice", "Clone the voice from the clip and speak the narration.",
             ["voice", "--script", "{project_dir}/narration.json", "--pace", "{pace}"],
             optional=[["--src", "{voice_clip}"]],
             needs=["plan"], makes=["narration"], heavy=True),
        Step("face", "Face", "Prepare the presenter footage from the face clip. "
             "Skip it for a demo with no face in the corner.",
             ["face", "--src", "{face_clip}"], makes=["driver"]),
        Step("build", "Build", "Render scenes, fit them to the narration, lip-sync, "
             "composite.", ["build", "--project", "{project}"],
             needs=["narration"], makes=["film"], heavy=True,
             options=[Field("only", "Only these stages", "text", default="",
                            help="scenes,assemble,face,compose", create=False)]),
        Step("music", "Music", "Synthesise a bed in the chosen style, as long as the "
             "demo, and duck it under the narration.",
             ["music", "--video", "{out_dir}/{project}-final.mp4",
              "--style", "{music_style}", "--music", "{out_dir}/{project}-bed.wav",
              "--out", "{out_dir}/{project}-scored.mp4"],
             needs=["film"], makes=["scored"]),
    ],
    artifacts=[
        Artifact("plan", "Plan", "project", "plan.json", "json"),
        Artifact("script", "Narration", "project", "narration.json", "json"),
        Artifact("narration", "Spoken narration", "out", "audio/narration.json", "json"),
        Artifact("driver", "Presenter footage", "root", "assets/face/driver.mp4", "video"),
        Artifact("film", "The demo", "out", "{name}-final.mp4", "video"),
        Artifact("scored", "The demo, scored", "out", "{name}-scored.mp4", "video"),
        Artifact("silent", "Silent cut", "out", "{name}-silent.mp4", "video"),
    ],
    output="film",
)

MODES: dict[str, Mode] = {m.key: m for m in (SHORT, REEL, EDIT, PRESENT, DEMO)}


# ---------------------------------------------------------------------------
# tools: one feature, one file
# ---------------------------------------------------------------------------


@dataclass
class Tool:
    """A single operation on a file or two, with no project around it.

    A mode owns a folder and a pipeline. A tool owns nothing: it takes what it
    is given, writes into a fresh folder under `out/tools/<key>/`, and prints
    where. Every one of them is `demoforge tool <key> --<field> <value> ...`,
    with the fields below as the arguments, so the window and the shell run
    exactly the same command.
    """

    key: str
    name: str
    tagline: str
    blurb: str
    needs: list[str]
    fields: list[Field]
    makes: str                 # what comes back, in words
    requires: list[str] = field(default_factory=list)
    heavy: bool = False
    accent: str = "lime"

    def public(self) -> dict[str, Any]:
        return {"key": self.key, "name": self.name, "tagline": self.tagline,
                "blurb": self.blurb, "needs": self.needs, "makes": self.makes,
                "requires": self.requires, "heavy": self.heavy, "accent": self.accent,
                "fields": [f.public() for f in self.fields]}


_video = Field("video", "Video", "path", required=True, filters=VIDEO)
_model = Field("whisper_model", "Recogniser", "select", group="speech",
               default="medium.en", options=WHISPER)
_accent_any = Field("accent", "Accent", "color", group="look", default="lime",
                    options=REEL_ACCENTS + SLIDE_ACCENTS)

TOOLS: dict[str, Tool] = {t.key: t for t in (
    Tool("score", "Score",
         "Find a bed, lay it under the voice, duck it.",
         "Hand it any video with speech in it. It cleans the voice, picks a track "
         "from your music folder ranked on drive, or fetches one, levels the bed "
         "the stated distance under the voice, ducks it while you talk, and "
         "masters the result to streaming loudness.",
         ["A video with a voice in it", "Optional: a folder of music you own"],
         [_video,
          _music_dir, _music_file, _music_offset,
          Field("music_under", "Music under voice", "number", group="sound",
                default=-9.0, step=0.5, min=-24, max=0, help="LU below the voice."),
          Field("music_ratio", "Duck depth", "number", group="sound", default=4.0,
                step=0.5, min=1, max=12),
          Field("music_query", "Search for", "list", group="sound",
                default=["upbeat energetic tech"], help="Used when nothing local fits."),
          Field("music_style", "Fallback style", "select", group="sound",
                default="lofi", options=["lofi", "trap"],
                help="Synthesised only if nothing can be sourced."),
          Field("loudness", "Final loudness", "number", group="sound", default=-14.0,
                step=0.5, min=-24, max=-8, help="LUFS. -14 is streaming loud.")],
         "the same video, scored", ["ffmpeg"]),
    Tool("caption", "Caption",
         "Word-pop captions burned in, plus an .srt.",
         "Transcribes to word timestamps and burns captions that highlight each "
         "word as it is said, sized to the frame. Also writes a sidecar .srt for "
         "platforms that render their own.",
         ["A video with speech"],
         [_video, _model,
          Field("caption_words", "Words per caption", "number", group="look",
                default=3, step=1, min=1, max=8),
          _accent_any, _corrections],
         "the video with captions, an .srt, and the transcript", ["ffmpeg", "whisper"],
         heavy=True),
    Tool("tighten", "Tighten",
         "Silence, retakes and fillers out. Nothing else touched.",
         "Transcribes, then cuts every pause over the limit down to a breath, "
         "lifts fillers with the hesitation around them, and drops repeated "
         "false starts. Cuts land on word boundaries, never mid-consonant.",
         ["A recording of somebody talking"],
         [_video, _model,
          Field("pause_cut", "Cut pauses over", "number", default=0.72, step=0.02,
                min=0.1, max=3.0, help="Seconds."),
          Field("pause_keep", "Leave behind", "number", default=0.30, step=0.02,
                min=0.05, max=1.0, help="Seconds of each cut pause that survive."),
          Field("speed", "Speed", "number", group="look", default=1.0, step=0.05,
                min=1.0, max=1.3),
          Field("mirror", "Mirror", "bool", group="look", default=False),
          _corrections],
         "the recording, tightened, with its transcript", ["ffmpeg", "whisper"],
         heavy=True),
    Tool("gaze", "Gaze",
         "Where the eyes were, second by second.",
         "Measures head yaw and iris offset per frame and reports the windows "
         "where the presenter is looking at the lens. Use it to decide where a "
         "full-frame shot is honest.",
         ["A recording of a face"],
         [_video, Field("fps", "Samples per second", "number", default=5, step=1,
                        min=1, max=30)],
         "gaze.json and a report of the on-lens windows", ["ffmpeg", "mediapipe"]),
    Tool("cover", "Cover",
         "One frame, the hook set across it.",
         "Pulls a still from the video and sets your lines over the caption "
         "band with a scrim, at the video's own size. Wrap a word in *asterisks* "
         "to accent it.",
         ["A video", "One to three short lines"],
         [_video,
          Field("at", "Frame at", "number", default=0.5, step=0.1, min=0,
                help="Seconds into the video."),
          Field("line", "Lines", "list", default=["Stop *scrolling*."],
                help="One per line."),
          _accent_any],
         "a JPEG cover", ["ffmpeg"]),
    Tool("punch", "Punch",
         "Mirror, zoom on the face, and a touch of speed.",
         "The presenter treatment from Reel mode on its own: a horizontal flip "
         "if you look better that way, a zoom centred on where your face "
         "actually is, and a speed you feel rather than hear.",
         ["A recording of a face"],
         [_video,
          Field("zoom", "Zoom", "number", default=1.2, step=0.05, min=1.0, max=1.8),
          Field("mirror", "Mirror", "bool", default=True),
          Field("speed", "Speed", "number", default=1.0, step=0.05, min=1.0, max=1.3),
          Field("face", "Centre on the face", "bool", default=True,
                help="Measures the face with mediapipe. Off centres the frame.")],
         "the recording, treated", ["ffmpeg"]),
    Tool("voice", "Voice",
         "Say it in a clone of a voice.",
         "One clip of somebody talking, one piece of text. The clip is cloned "
         "locally with Chatterbox and the text is read in it. Nothing leaves the "
         "machine. Only clone a voice you have the right to.",
         ["Ten to thirty seconds of a voice", "The words"],
         [Field("text", "Text", "textarea", required=True),
          Field("reference", "Voice clip", "path", required=True, filters=AUDIO + VIDEO),
          Field("pace", "Pace", "number", default=0.85, step=0.05, min=0.6, max=1.2,
                help="Below 1 slows it down.")],
         "a .wav of the text, spoken", ["chatterbox"], heavy=True),
    Tool("lipsync", "Lip-sync",
         "Re-dub a face so the mouth matches new audio.",
         "LatentSync regenerates the mouth; everything else is the original. "
         "Long tracks are done in chunks and joined. Slow: minutes per minute.",
         ["A video of a face, talking", "The audio it should be saying"],
         [_video,
          Field("audio", "Audio", "path", required=True, filters=AUDIO + VIDEO),
          Field("chunk", "Chunk length", "number", default=20, step=5, min=0, max=120,
                help="Seconds per piece. 0 does it in one go, which needs more RAM.")],
         "the video, re-dubbed", ["lipsync"], heavy=True),
    Tool("broll_generate", "B-roll: generate",
         "A short cinematic shot from a prose prompt.",
         "LTX-Video on your own GPU. Write the shot as a sentence or three of "
         "action and camera, chronological, and it comes back as a four-second "
         "clip. Terse prompts underperform badly.",
         ["A prompt", "A GPU with 8 GB"],
         [Field("prompt", "Prompt", "textarea", required=True,
                help="Long, prose, chronological. Describe the action and the camera."),
          Field("aspect", "Aspect", "select", default="vertical",
                options=["vertical", "wide", "square"]),
          Field("seconds", "Seconds", "number", default=4, step=1, min=2, max=8),
          Field("refine", "Upscale and refine", "bool", default=True,
                help="Six times slower, and a shot rather than a preview.")],
         "an .mp4 shot", ["torch", "ltx"], heavy=True),
    Tool("broll_search", "B-roll: search",
         "Licence-free stock clips, with the licence recorded.",
         "Searches Pixabay's video library, downloads the best matches, and "
         "writes a .source.json beside each one saying where it came from and "
         "what its licence allows.",
         ["A search phrase", "A Pixabay key, in Settings"],
         [Field("query", "Search for", "text", required=True),
          Field("count", "How many", "number", default=4, step=1, min=1, max=20),
          Field("orientation", "Orientation", "select", default="vertical",
                options=["vertical", "horizontal", "any"]),
          Field("min_seconds", "At least", "number", default=5, step=1, min=1,
                help="Seconds long.")],
         "clips, each with its licence record", ["pixabay"]),
    Tool("matte", "Matte",
         "Cut the person out of their background.",
         "Separates the speaker from the room with a video matting model and "
         "writes the cutout with an alpha channel, or lays it over another clip "
         "when you give one. Use it as an invisible depth layer: graphics behind "
         "the speaker, the footage itself unchanged.",
         ["A video of a person"],
         [_video,
          Field("over", "Lay over", "path", filters=VIDEO,
                help="Optional background clip; without it you get an alpha .mov."),
          Field("ratio", "Downsample", "number", default=None, step=0.05, min=0.1, max=1,
                help="Model resolution; blank lets it choose.")],
         "the cutout, with alpha or composited", ["ffmpeg", "torch"], heavy=True),
    Tool("restore", "Restore",
         "Sharpen a lip-synced mouth or face back up.",
         "Runs face restoration over the region lip-sync softened, blended back "
         "at the strength you set and smoothed over time so it does not flicker.",
         ["A lip-synced video"],
         [_video,
          Field("region", "Region", "select", default="mouth", options=["mouth", "face"]),
          Field("strength", "Strength", "number", default=0.85, step=0.05, min=0, max=1),
          Field("smooth", "Smoothing", "number", default=0.6, step=0.05, min=0, max=1)],
         "the restored video", ["ffmpeg", "torch"], heavy=True),
    Tool("voice_check", "Voice check",
         "Score generated narration before you build on it.",
         "Measures pace, loudness, clipping and how closely the narration matches "
         "the reference voice, and writes the numbers to voice-check.json, so a "
         "bad generation is caught before the picture is cut to it.",
         ["Narration audio", "Optional: the reference clip"],
         [Field("audio", "Narration", "path", required=True, filters=AUDIO),
          Field("reference", "Reference clip", "path", filters=AUDIO),
          Field("words", "Script words", "number", default=None, step=1, min=1,
                help="Word count, for pace in words per minute.")],
         "voice-check.json", ["ffmpeg"]),
)}


def public_tools() -> dict[str, Any]:
    return {k: t.public() for k, t in TOOLS.items()}

# Detection order matters: a folder can carry more than one profile, and the
# newest modes are the ones a person is most likely to be working in.
DETECT = [SHORT, REEL, EDIT, PRESENT, DEMO]


def detect(directory: Path) -> Mode | None:
    for mode in DETECT:
        if (directory / mode.profile).exists():
            return mode
    # The generated path predates its profile file: a scenes.py or a
    # narration.json is what marks it.
    if (directory / "scenes.py").exists() or (directory / "narration.json").exists():
        return DEMO
    return None


def defaults(mode: Mode) -> dict[str, Any]:
    return {f.key: f.default for f in mode.fields if f.default is not None}


def public() -> dict[str, Any]:
    return {k: m.public() for k, m in MODES.items()}
