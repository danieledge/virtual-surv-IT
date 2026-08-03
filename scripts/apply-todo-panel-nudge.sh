#!/usr/bin/env bash
# Install the task-panel Stop-hook nudge's CODE (scripts/staged_hooks/todo_panel_nudge.py
# -> scripts/todo_panel_nudge.py). File-copy only, by design (2026-08-03 perf audit):
#
#   WIRING (the hooks.Stop entry in .claude/settings.json / hooks/hooks.json) is now
#   scripts/apply-stop-hook-dispatcher.sh's job, not this script's - dod_stop_gate.py and
#   todo_panel_nudge.py were consolidated into ONE Stop-event process
#   (scripts/stop_hook_dispatcher.py), replacing their two separate hooks.Stop entries
#   with one entry pointing at the dispatcher. If this script still added its OLD separate
#   entry, running it after apply-stop-hook-dispatcher.sh would silently re-fragment the
#   consolidation back into two processes per Stop event. Run
#   apply-stop-hook-dispatcher.sh (which also installs this file) for a first-time setup;
#   run THIS script alone only to pick up a later code-only change to todo_panel_nudge.py
#   without re-touching the wiring.
#
# One-time, self-suppressing reminder to seed the native task-list gate panel once an
# engagement reaches delivery - a live audit (2026-07-30) found zero genuine TodoWrite
# calls across every kept eval transcript, meaning the operating guide's claim that
# gates appear there was pure prose, never nudged. Warn-first, matches
# dod_stop_gate.py's exact Stop-hook shape; fails open on any error.
#
# HUMAN-RUN by design (hook/config edits are human-only, ADR-002 rec 5). Idempotent.
#   Usage:  bash scripts/apply-todo-panel-nudge.sh
# Afterwards: commit scripts/todo_panel_nudge.py; restart the session if it was already wired.
set -euo pipefail

here="$(cd "$(dirname "$0")/.." && pwd)"

cp "$here/scripts/staged_hooks/todo_panel_nudge.py" "$here/scripts/todo_panel_nudge.py"
echo "todo_panel_nudge: staged copy installed to scripts/."
echo "Wiring is handled separately - see: bash scripts/apply-stop-hook-dispatcher.sh"
echo "Confirm: python3 -m pytest tests/test_todo_panel_nudge.py tests/test_stop_hook_dispatcher.py -q"
