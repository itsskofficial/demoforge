---
name: voice-cloning
description: Clone a presenter's voice from one short clip and narrate a script with it, locally. Use when a demo, explainer or tutorial needs spoken narration in a specific person's voice, or when narration has to be regenerated whenever a script changes. Covers reference-clip preparation, pacing control, and the hosted fallback.
---

# Cloning a voice for narration

The job: turn a written script into narration that sounds like a particular
person, and be able to redo it every time the script changes.

## Get a usable reference first

Chatterbox is zero-shot. It needs one clean clip and nothing else, and the clip
decides most of the outcome.

```bash
python -m demoforge.voice prepare --src recording.mp3 --start 8 --dur 16
```

- **Ten to twenty seconds.** More is not better; it dilutes rather than helps.
- **Skip the opening.** The first few seconds of any recording are throat-clearing.
- **One speaker, no music, no room echo.** `prepare` high-passes at 60 Hz and
  loudness-normalises, which fixes thin phone audio but cannot fix a bad room.
- Cut two references from different parts of the recording and compare. The
  window genuinely matters and it costs one extra command to find out.

## Then control the pace, because the default is too fast

Stock settings read at roughly **220 words per minute**. Comfortable narration
is **140–155**. This is the single most common complaint about generated
narration and it is entirely fixable.

Three levers, in the order you should reach for them:

| Lever | Effect | Notes |
|---|---|---|
| `--cfg-weight` | **The real speed control.** Lower ⇒ slower. | 0.20–0.30 for narration |
| `--max-chars` / `--gap` | Chunk size and silence between chunks | Smaller chunks ⇒ more pauses |
| `--pace` | Pitch-preserving time-stretch, applied last | Keep above 0.85 or consonants smear |

```bash
python -m demoforge.voice say --text "one line" --cfg-weight 0.24 --gap 0.7 --pace 0.85
```

`--exaggeration` adds intent but **speeds speech up**, so it fights `cfg-weight`.
Raise one, lower the other.

**Measure, don't guess.** Words ÷ seconds × 60 gives words per minute, and a
number ends an argument that adjectives cannot. `say` prints it for you.

## Narrating a whole script

```bash
python -m demoforge.voice script --script narration.json --outdir out/audio
```

`narration.json` is a list of `{id, text}`. The output is one wav per line plus
`narration.json` in the output directory recording measured durations — which
is what `demoforge.assemble` uses to fit the picture to the words. Speak the
script *before* deciding how long a scene should be; guessing scene lengths and
then discovering the narration overruns means rendering everything twice.

## Writing text a speech model can read

- Spell numbers as words: "thirty percent", not "30%". Digits get read
  inconsistently, and percentages especially.
- Short sentences. The model's prosody resets at full stops, and that is the
  main thing keeping a long read from drifting.
- Avoid parentheses and semicolons; they produce odd pauses.
- Read it aloud yourself first. If you stumble, so will the model.

## When to use the hosted path instead

`demoforge.sarvam` speaks the same interface against Sarvam's Bulbul, which has
`pace` as a first-class parameter and much better Indian-language and
Indian-accented English coverage.

Reach for it when: the local clone flattens a non-Western accent, you need a
language Chatterbox does not cover, or you want a polished stock voice rather
than a specific person's.

Stay local when: you are iterating (the local model is free per run and a demo
gets re-narrated many times), or the voice belongs to a real person and you
would rather their sample never left the machine.

## Consent

A cloned voice is someone's identity. Keep reference clips out of version
control — demoforge gitignores `assets/voice/` for this reason — and only clone
a voice whose owner has agreed. Chatterbox watermarks everything it generates,
which is a feature worth keeping rather than stripping.
