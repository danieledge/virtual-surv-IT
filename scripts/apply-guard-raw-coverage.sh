#!/usr/bin/env bash
# Install the raw-data guard coverage fixes (audit 2026-08-01).
#
# The improved guard is STAGED at scripts/staged_hooks/guard-raw-data.py because the live
# consent-write guard blocks the model from editing .claude/hooks/** (correctly - a model that
# can edit a guard can neuter it). Installing is therefore a HUMAN act (ADR-002 rec 5).
# Idempotent.
#
#   Usage:  bash scripts/apply-guard-raw-coverage.sh
#   Undo:   git checkout .claude/hooks/guard-raw-data.py
#
# WHAT THIS CLOSES
#   1. ADR-002 rec 22 (was rated "architectural, not live"): _extract_path_candidates returned
#      [] for any tool outside {Read,Grep,Glob,Bash}, so a read tool outside that set reached
#      data/raw with NOTHING checking it. The rec assumed no local-filesystem tool was
#      installed - but WebFetch resolves file:// against the local filesystem and is live, so
#      the gap was live. WebFetch and NotebookRead are now handled, and an UNKNOWN tool gets a
#      defence-in-depth scan of its string inputs instead of a free pass.
#   2. ADR-002 recs 7 and 15: `Grep(path="data")` and path-less Grep descend INTO data/raw
#      while naming a path that does not resolve under it, so both the path check and the
#      literal deny globs missed them. Now blocked - but ONLY when raw data actually exists on
#      disk, so a fresh clone or a synthetic-only project keeps normal repo-wide search.
#   3. A live false positive: `grep -n "data/raw" .claude/settings.json` (reading the DENY-LIST
#      CONFIG) was blocked because the search PATTERN contained the marker. Search verbs now
#      distinguish the pattern operand from the file operands. A file operand under data/raw
#      still blocks.
#
# NOTE: this guard had no staged copy before today, so it had never had a live-vs-staged sync
# test. It has one now, and it FAILS rather than skips until this script is run.
#
# Regression net: tests/test_guard_raw_coverage.py
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
