"""The desktop app: a window over the five modes.

Nothing in here makes video. It lists projects, writes profiles, starts the
same commands the CLI would, and shows what came out. That is a deliberate
shape -- the pipeline stays a set of Python modules that an agent or a shell
can drive, and the app is one more caller of them, not a second copy.

    demoforge app            a native window, or the browser if there is none
    demoforge app --serve    the server alone, for another window to attach to
"""
