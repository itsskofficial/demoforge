"""demoforge — product demo videos assembled from a screen recording, a voice and a face.

The pieces are deliberately separable:

    capture   run a real command, keep its output and the timing of it
    terminal  a small VT emulator and a frame painter for it
    render    replay a capture as video, paced for a voiceover
    browser   drive and record a real browser, headless
    cards     title cards for the beats that have no command to run
    voice     clone a voice and speak a script with it
    stitch    concatenate segments and write the timecodes

Nothing here knows what it is recording. A *project profile* under
`projects/<name>/` supplies the commands, the pacing and the running order.
"""

__version__ = "0.2.0"
