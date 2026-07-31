#!/usr/bin/env bash
# Install the interpreter-caching fix for the guard launcher (run-guard.sh).
#
# The live launcher is STAGED at scripts/staged_hooks/run-guard.sh because
# .claude/hooks/** is guard-protected - a model that could edit a guard/launcher could
# neuter it, so installing is a HUMAN act (ADR-002 rec 5). Idempotent.
#
#   Usage:  bash scripts/apply-guard-interpreter-cache.sh
#   Undo:   git checkout .claude/hooks/run-guard.sh
#
# What changes (tested in tests/test_run_guard_interpreter_cache.py):
#   run-guard.sh fires for every PreToolUse hook (5 of them match Bash - one Bash call
#   re-runs the interpreter-selection loop 5 times). On a Windows box where python3.exe
#   is the App Execution Alias stub, actually EXECUTING it to version-check (not just
#   checking it exists) triggers a multi-second Microsoft Store redirect check, every
#   single time - live corporate report 2026-07-30: "/engage takes several minutes",
#   traced to this stub hang repeated dozens of times across one session. The launcher
#   now caches the FIRST successfully version-checked interpreter to
#   .claude/.guard-interpreter and trusts it (re-verified only via cheap `command -v`,
#   never re-executed) on every call after.
set -euo pipefail

here="$(cd "$(dirname "$0")/.." && pwd)"
src="$here/scripts/staged_hooks/run-guard.sh"
dst="$here/.claude/hooks/run-guard.sh"

[ -f "$src" ] || { echo "ERROR: staged launcher not found at $src" >&2; exit 1; }

if cmp -s "$src" "$dst"; then
  echo "already installed - staged and live launchers are identical."
  exit 0
fi

cp "$src" "$dst"
chmod +x "$dst"
echo "installed: $dst updated from staged copy."
echo "Confirm: bash tests/... (see test_run_guard_interpreter_cache.py) or just use the team normally."
echo "Now commit the change (both files ship together):"
echo "  git add .claude/hooks/run-guard.sh scripts/staged_hooks/run-guard.sh"
