---
name: codebase-understanding
description: Read a repository and turn it into a demo plan — scenes, narration and the commands worth showing. Use when starting a demo video for an unfamiliar codebase, or when a demo needs to be regenerated after a product changes. Covers what to read, what to send a model, and why proposed commands are never auto-run.
---

# Turning a repository into a demo plan

The hard part of a product demo is not rendering it. It is knowing what the
product *is*, and which three minutes of it are worth showing.

```bash
python -m demoforge.understand --repo . --seconds 180 \
    --audience "developers who have never seen this project"
```

Writes `plan.json` (scenes, narration, commands) and `narration.json` (ready for
the voice stage).

## What gets read, and in what order

Deliberately the order a new engineer would use:

1. **README** — the pitch the author already chose.
2. **Packaging metadata** — `pyproject.toml`, `package.json`, `Cargo.toml`.
   Names the product, its dependencies, and often its console scripts.
3. **Long-form docs** — `DEMO.md`, `EXPLAINER.md`, `ARCHITECTURE.md`,
   `DECISIONS.md`. Where the *why* usually lives.
4. **Entry points** — console scripts, npm scripts, Makefile targets. This is
   the highest-value section: it is the set of things a demo can actually run.
5. **File tree** — shape and scale, not contents.

Source files are deliberately *not* dumped in. A demo is about what the product
does, and implementation detail crowds out the docs that explain intent. If the
plan comes back vague, the fix is nearly always a better README rather than
feeding it more code.

## Reading the plan

You are meant to edit it. It is a first draft by something that has read your
repo and never used your product. Expect to fix:

- **Ordering.** Models like to explain before demonstrating. Lead with the
  problem; show a result before describing a capability.
- **Narration length.** Roughly 2.4 words per second of video. Overrun is the
  most common defect, and it costs a full re-render.
- **Invented flags.** Commands are drawn from entry points and docs, but a flag
  that does not exist will still appear occasionally. Check every command.

## Commands are never run during planning

The planner writes commands into a file. It does not execute them, and nothing
downstream executes them without you pointing a capture at one.

This is not incidental. "Let a model read a repo and then run the shell commands
it chose" is a bad shape, and the gap between planning and running is where a
person reads what was proposed. Keep it.

## When the plan is thin

- **No README** → say what the product does in `--audience` and expect to write
  more of the narration yourself.
- **Library with no CLI** → there is nothing to film. Demo it through a test
  suite, a notebook, or a small script you write for the purpose.
- **Product is a UI** → plan browser scenes; capture with `demoforge.browser`
  against a locally running instance.
