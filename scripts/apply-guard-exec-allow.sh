#!/usr/bin/env bash
# Install the 0.29.1 code-execution guard allow-list fix.
#
# The improved guard is STAGED at scripts/staged_hooks/guard-code-execution.py because the live
# guard blocks the model from editing .claude/hooks/** (correctly - a model that can edit a guard
# can neuter it). Installing is therefore a HUMAN act (ADR-002 rec 5). Idempotent.
#
#   Usage:  bash scripts/apply-guard-exec-allow.sh
#   Undo:   git checkout .claude/hooks/guard-code-execution.py
#
# What changes (both directions tested in tests/test_guard_exec_team_allow.py):
#   ALLOW now: the team's own engagement_state.py invoked by bundled-copy path (new in 0.29.0,
#   missing from the basename list), and quoted plugin paths CONTAINING SPACES
#   ("~/Library/Application Support/.../scripts/render_html.py") for the allow-listed basenames.
#   STILL BLOCK: any non-team basename by path (quoted or not), inline python, pytest, and every
#   other execution pattern - the exec pattern list is byte-identical to the live guard's.
set -euo pipefail

here="$(cd "$(dirname "$0")/.." && pwd)"
src="$here/scripts/staged_hooks/guard-code-execution.py"
dst="$here/.claude/hooks/guard-code-execution.py"

[ -f "$src" ] || { echo "ERROR: staged guard not found at $src" >&2; exit 1; }

if cmp -s "$src" "$dst"; then
  echo "already installed - staged and live guards are identical."
  exit 0
fi

cp "$src" "$dst"
echo "installed: $dst updated from staged copy."
echo "Now commit the change (both files ship together):"
echo "  git add .claude/hooks/guard-code-execution.py scripts/staged_hooks/guard-code-execution.py"
