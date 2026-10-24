"""Film mode: a voiced, scene-by-scene film built on a voice spine.

The sixth path, and the one with the most hand work in it. The other modes cut
footage that already says what it needs to say. This one is for a film that
is *made*: a narration recorded line by line, some lines on camera, every
other line under an animated HyperFrames scene, music cut to the story and a
sound on every join. It is the pitch film's pipeline, taken out of one
project's scripts and made to read everything particular from `film.json`.

The order is the order the film was made in, and each step reads only what
the step before it wrote:

    decode    AV1 phone clips through libdav1d, checked for repeated frames
    spine     the voice: every line trimmed on its envelope, placed on frames
    captions  what was actually said, aligned to whisper's word times
    retime    move words and cues onto a rebuilt spine without re-transcribing
    timeline  every scene pinned to a line, or a word inside one
    camprep   plates and cleaned cutouts for the on-camera lines
    scenes    the footage base of every camera scene, overlays carried over
    root      the root composition: hosts, transitions, karaoke captions
    freeze    stills for the joins that shatter
    score     the music bed, each section pinned to a line
    mix       voice, ducked music and every SFX, mastered
    render    `hyperframes render`, with the temp and timeout it needs
    qa        dark frames, clipped joins, missing captions, contact sheets
    thumbs    thumbnail candidates scored on the face

The spine is the master clock. Nothing downstream measures time any other way.
"""
