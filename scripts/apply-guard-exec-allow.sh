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
# GENERIC apply: copies whatever exec-guard change is currently STAGED. Read the staged
# file's own comments + tests/test_guard_exec_team_allow.py for what the pending change is
# (0.29.1: engagement_state + quoted space paths; 0.32/ADR-009: extensions + convert_sarif
# basenames and the human-curated CST_COMPANY_ALLOW literal-prefix allowlist).
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
