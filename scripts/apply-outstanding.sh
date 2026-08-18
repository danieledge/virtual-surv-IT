#!/usr/bin/env bash
# Wrapper: runs every apply-*.sh script in this directory. HUMAN-RUN by design, same as
# everything it calls (hook/config edits are human-only, ADR-002 rec 5) - this script does
# not grant itself any exemption, it just sequences already-approved human-run scripts.
# Each one it calls is independently idempotent (confirmed across all of them, 2026-08-12
# audit: every apply-*.sh in this directory documents itself as idempotent, none prompts
# interactively), so re-running this wrapper - whether nothing, some, or everything is
# actually pending - is always safe: an already-applied script just no-ops.
#
# DYNAMIC glob, not a hand-maintained list (2026-08-12 rewrite). The previous version was
# a static array that had to be hand-edited every time a new apply-*.sh script was added -
# and had already drifted stale (missing apply-guard-daemon.sh, among others) by the time
# this was caught. A static allowlist here is exactly the "looks healthy, silently
# doesn't cover something new" failure mode this project's own tests warn about elsewhere
# (test_staged_matches_live's docstring, FCA Market Watch 79) - so this now discovers
# every apply-*.sh in the directory automatically and always runs the current set,
# nothing to remember to update.
#
#   Usage:  bash scripts/apply-outstanding.sh
set -euo pipefail

here="$(cd "$(dirname "$0")/.." && pwd)"
cd "$here"

self="$(basename "$0")"
ran=0

for path in scripts/apply-*.sh; do
  name="$(basename "$path")"
  [ "$name" = "$self" ] && continue  # never invoke this wrapper from inside itself
  echo "=== $name ==="
  bash "$path"
  echo
  ran=$((ran + 1))
done

if [ "$ran" -eq 0 ]; then
  echo "No apply-*.sh scripts found other than this wrapper - nothing to run."
  exit 1
fi

echo "All done ($ran script(s) run). Confirm nothing is still pending:"
echo "  python3 -m pytest tests/test_hooks_in_sync.py tests/test_run_guard_interpreter_cache.py -q"
