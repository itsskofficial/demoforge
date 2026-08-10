#!/usr/bin/env bash
# Phase A of the recording: everything that has to happen before the browser
# segments. Runs for real, in the order RECORDING.md asks for.
set -u
cd "$(dirname "$0")/../.."
S=demo/record/sessions
mkdir -p "$S"

echo "=== [0/5] reset: back to the frozen week-1 suite, empty review queue ==="
python -m demo.loop --reset 2>&1 | tail -5
echo "reset exit: $?"

echo "=== [1/5] step 1a: one live question ==="
python -m demo.record.capture step1_ask.json -- \
  python -m demo.ask "Where is my order NW-4143?" > /dev/null 2>&1
echo "step1_ask exit: $?"

echo "=== [2/5] step 1b: a recorded failure ==="
python -m demo.record.capture step1_failure.json -- \
  python -m demo.ask --failure > /dev/null 2>&1
echo "step1_failure exit: $?"

echo "=== [3/5] step 4: measure (the long one) ==="
python -m demo.record.capture step4_measure.json -- \
  python -m demo.run measure > /dev/null 2>&1
echo "step4_measure exit: $?"

echo "=== [4/5] step 5a: propose ==="
python -m demo.record.capture step5_propose.json -- \
  python -m demo.loop > /dev/null 2>&1
echo "step5_propose exit: $?"

echo "=== phase A done ==="
ls -la "$S"
