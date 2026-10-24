"""Phrase-level narration: the lever that actually controls pace.

Chatterbox has no speed control, and the guidance knobs barely move it --
measured here across `exaggeration` 0.5 -> 0.8: 228 -> 232 wpm, and across
`cfg_weight` 0.34 -> 0.15 elsewhere: 221 -> 210. Effectively flat, and both
sit far above the 165-175 wpm a narration read wants.

Time-stretching afterwards (`atempo`) buys the rate at the cost of smeared
consonants on a voice that will sit exposed under a quiet music bed. The
earlier passes here did exactly that and it is why the reads sounded wrong.

What works instead is owning the silence:

1. Split each line into phrases at its natural rhetorical breaks.
2. Give each phrase an explicit pause to follow it.
3. Generate each phrase separately, varying the seed per phrase so repeated
   short phrases do not sound cloned.
4. **Trim each phrase's own head and tail silence** to a small fixed pad --
   model-emitted silence is variable, and yours must not be.
5. Concatenate with exactly the pauses you asked for.

That lands a natural rate with no processing artifacts, and it turns pacing
into an editable text file rather than a model property.

Adapted from SkillsForge's explainer-video local-tts notes.
"""

from __future__ import annotations

import re

# Pause lengths that read as human, in seconds.
CLAUSE = 0.40      # between clauses of one thought
SENTENCE = 0.55    # between sentences
LANDING = 0.70     # before a line meant to land hard

HEAD_PAD = 0.045   # silence kept before a phrase
TAIL_PAD = 0.030   # silence kept after a phrase
THRESHOLD = 0.012  # amplitude below this counts as silence


def trim(wav, sample_rate: int):
    """Strip the model's variable head/tail silence down to a fixed pad."""
    mono = wav.abs().max(dim=0).values
    voiced = (mono > THRESHOLD).nonzero()
    if voiced.numel() == 0:
        return wav
    lo = max(0, int(voiced[0]) - int(HEAD_PAD * sample_rate))
    hi = min(wav.shape[-1], int(voiced[-1]) + int(TAIL_PAD * sample_rate))
    return wav[:, lo:hi]


def auto_phrases(text: str) -> list[dict]:
    """A first-draft phrasing, to be edited by hand.

    Splits at sentence ends and at commas that carry a real breath, then
    assigns pauses by which kind of break it was. A short sentence standing
    alone -- "One percent." -- is treated as a landing, because in narration
    that is nearly always what it is.
    """
    text = " ".join(text.split())
    sentences = [s for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    out: list[dict] = []
    for si, sentence in enumerate(sentences):
        parts = [p.strip() for p in re.split(r",\s+(?=(?:and|but|so|then|which|where)\b)", sentence)]
        if len(parts) == 1:
            parts = [sentence]
        for pi, part in enumerate(parts):
            last_in_sentence = pi == len(parts) - 1
            if not last_in_sentence:
                pause = CLAUSE
            elif si == len(sentences) - 1:
                pause = 0.0
            elif len(part.split()) <= 3:
                pause = LANDING          # a short standalone line lands
            else:
                pause = SENTENCE
            out.append({"text": part, "pause": pause})
    return out
