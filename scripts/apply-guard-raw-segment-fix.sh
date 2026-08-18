#!/usr/bin/env bash
# Install the raw-data guard's compound-command segment fix + git message exemption
# (token-usage audit, 2026-08-03).
#
# The improved guard is STAGED at scripts/staged_hooks/guard-raw-data.py because the live
# guard blocks the model from editing .claude/hooks/** (correctly - a model that can edit a
# guard can neuter it). Installing is therefore a HUMAN act (ADR-002 rec 5). Idempotent.
#
#   Usage:  bash scripts/apply-guard-raw-segment-fix.sh
#   Undo:   git checkout .claude/hooks/guard-raw-data.py
#
# WHAT THIS CLOSES
#   1. Compound-command segment blindness. A multi-statement Bash command
#      (`grep ...; echo "..."`, `a && b`, `a | b`) was shlex-split and judged as ONE search
#      invocation, so words from a LATER, unrelated statement could become "file operands"
#      of an EARLIER search verb - fired live on the audit's own multi-statement command
#      mid-session. Segments are now split the same way guard-code-execution.py already does
#      (`;`, `&&`, `||`, `|`, newline, backtick, `$(`) and judged independently.
#   2. `git commit`/`git tag -m "..."` (or --message=...) false positive: a commit/tag
#      message is prose the user wrote, not a file read, so it must not trip the marker scan
#      just for MENTIONING the guard's own marker string - the fourth instance of the
#      prose/argument false-positive class this project keeps hitting. `-F <file>` (a message
#      FILE) is deliberately NOT exempted - that is a real file read.
#
# NOT changed by this script (left as explicit design tradeoffs, not bugs):
#   - Path-less/ancestor-rooted Grep still hard-blocks whenever data/raw/ holds any file -
#     the audit flagged this as hitting every reviewer subagent's default search in a project
#     that actually has raw data, and proposed relaxing it when settings.json's own deny-list
#     already covers the same ground. Left alone pending a human decision - it trades a real
#     lexical safety layer for convenience.
#   - A Bash command that independently mentions the marker as plain prose (`echo "see
#     data/raw/ for details"`) still blocks - the documented belt-and-braces behaviour,
#     unchanged.
#
# Regression net: tests/test_guard_raw_coverage.py (the live-vs-staged sync test FAILS - it
# does not skip - until this script has been run).
set -euo pipefail

here="$(cd "$(dirname "$0")/.." && pwd)"
src="$here/scripts/staged_hooks/guard-raw-data.py"
dst="$here/.claude/hooks/guard-raw-data.py"

[ -f "$src" ] || { echo "ERROR: staged guard not found at $src" >&2; exit 1; }

if cmp -s "$src" "$dst"; then
  echo "already installed - staged and live guards are identical."
  exit 0
fi

cp "$src" "$dst"
echo "installed: $dst updated from staged copy."
echo "Now commit the change (both files ship together):"
echo "  git add .claude/hooks/guard-raw-data.py scripts/staged_hooks/guard-raw-data.py"
