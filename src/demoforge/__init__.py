"""demoforge — product videos from a codebase, a voice, a face and whatever was filmed.

Five modes, each a pipeline over a project folder, each starting from a
different amount of material:

    demo      plan, capture and narrate a demo of a repository     (cli build)
    present   your recorded takes, the picture built to fit them   present.py
    edit      a deck and a pile of raw takes, cut into a film      edit.py
    reel      one vertical take, cut into a short vertical film    reel.py
    short     points over ambient footage, nobody on camera        short.py

and a sixth on the way, `film`, for a narrated film made scene by scene
(`demoforge.film`).

Underneath them, the shared pieces:

    capture, terminal, render   a real command, replayed as video
    browser                     a real Chromium, driven and recorded headless
    motion, cards               drawn scenes for what no recording can show
    slidekit, reelkit, deck     the look of a slide, of a reel, and a deck read in
    transcribe, captions        words and their times, burned back in
    voice, face, gaze           a cloned voice, a re-dubbed face, where the eyes are
    music, music_source         a bed, sourced or synthesised, ducked under speech
    media                       the ffprobe and ffmpeg plumbing every mode shares
    assemble, compose           the picture fitted to the narration, the face on top

`tools` exposes the single operations the modes are built from as one-file
commands, and `app` is a desktop window over all of it -- one more caller of
the same CLI, never a second copy of the pipeline.

Nothing here knows what it is recording. A *project profile* under
`projects/<name>/` supplies the commands, the pages, the pacing and the
running order.
"""

__version__ = "0.3.0"
