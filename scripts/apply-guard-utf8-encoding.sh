#!/usr/bin/env bash
# Install the UTF-8 encoding pin for the guard launcher (run-guard.sh).
#
# The live launcher is STAGED at scripts/staged_hooks/run-guard.sh because
# .claude/hooks/** is guard-protected - a model that could edit a guard/launcher could
# neuter it, so installing is a HUMAN act (ADR-002 rec 5). Idempotent.
#
#   Usage:  bash scripts/apply-guard-utf8-encoding.sh
#   Undo:   git checkout .claude/hooks/run-guard.sh
#
# What changes (tested in tests/test_run_guard_utf8_encoding.py):
#   Corporate report 2026-07-31: locked_menu_guard.py kept blocking a correctly-formed
#   Fix-cycle answer ("Fix → re-review loop") with "review-menu drift" on a Windows box,
#   even though the option text matched review-menu.md exactly. Root cause: run-guard.sh
#   exec'd the resolved Python interpreter without pinning its text encoding. Native
#   Windows Python decodes stdin/stdout/stderr using the console codepage (e.g. cp1252)
#   unless told otherwise - and cp1252 doesn't raise on the arrow's multi-byte UTF-8
#   sequence, it silently mis-decodes it into different-but-valid characters, so the
#   guard's string comparison failed even though both sides "looked" identical on screen.
#   The launcher now exports PYTHONIOENCODING=utf-8 and PYTHONUTF8=1 before every exec
#   path, forcing UTF-8 regardless of OS locale/console codepage.
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
echo "Confirm: bash tests/... (see test_run_guard_utf8_encoding.py) or just use the team normally."
echo "Now commit the change (both files ship together):"
echo "  git add .claude/hooks/run-guard.sh scripts/staged_hooks/run-guard.sh"
