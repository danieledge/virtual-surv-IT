#!/usr/bin/env bash
# Cache _raw_data_present()'s result instead of re-walking data/raw/ on every path-less
# Grep/Glob call (corp report, 2026-08-10).
#
# The improved guard is STAGED at scripts/staged_hooks/guard-raw-data.py because the live
# guard blocks the model from editing .claude/hooks/** (correctly - a model that can edit a
# guard can neuter it). Installing is therefore a HUMAN act (ADR-002 rec 5). Idempotent.
#
#   Usage:  bash scripts/apply-raw-data-present-cache.sh
#   Undo:   git checkout .claude/hooks/guard-raw-data.py
#
# WHAT THIS CLOSES
#   A path-less Grep/Glob call always roots at the project dir, which is trivially an
#   ancestor of data/raw (_RAW_DIR = project_root / "data" / "raw"), so _raw_data_present()
#   ran a full os.walk() on nearly every real search - measurable latency on a corporate
#   Windows box where endpoint security scans each filesystem operation. Now cached to
#   .claude/.raw-data-present with a 30s TTL, same pattern as the existing
#   .claude/.guard-interpreter cache.
#
# NOT changed by this script (left as explicit design tradeoffs, not bugs):
#   - The cache only gates this ONE function, which per its own docstring only gates the
#     ancestor-rooted BLANKET heuristic - the guard's unconditional precise-path checks
#     never consult it, and the fail-closed exception handler is untouched.
#   - Cache read/write failures fall straight through to a real check - the cache is an
#     optimization only, never load-bearing.
#   - 30s TTL is a starting heuristic, not tuned against a real corp-box measurement yet.
#
# Regression net: tests/test_guard_raw_coverage.py + tests/test_hooks_in_sync.py's
# test_staged_matches_live - it FAILS (does not skip) until this script has been run.
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
