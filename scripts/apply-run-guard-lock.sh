#!/usr/bin/env bash
# Serialize concurrent guard-launcher invocations under subagent fan-out (corp report,
# 2026-08-10).
#
# The improved launcher is STAGED at scripts/staged_hooks/run-guard.sh because the live
# guard blocks the model from editing .claude/hooks/** (correctly - a model that can edit a
# guard can neuter it). Installing is therefore a HUMAN act (ADR-002 rec 5). Idempotent.
#
#   Usage:  bash scripts/apply-run-guard-lock.sh
#   Undo:   git checkout .claude/hooks/run-guard.sh
#
# WHAT THIS CLOSES
#   A Workflow-tool fan-out fires several subagents' tool calls within the same instant,
#   each independently spawning this launcher - normally hidden (one spawn finishes before
#   the next tool call starts), but under real concurrency N interpreter cold-starts hit CPU
#   scheduling and endpoint-security scanning on a Windows box AT ONCE, measured live turning
#   ~50-100ms hook latency into 2,000-8,000ms across the board. An mkdir-based lock (atomic,
#   portable - no flock dependency) now queues concurrent launches instead of letting them
#   all spawn simultaneously. Total process-creation work is unchanged; it stops happening in
#   one contended burst. Live-tested: 5 truly concurrent calls now show zero overlap in their
#   execution windows (previously all 5 would spawn at once).
#
# TWO FAILURE MODES HANDLED EXPLICITLY (this gates every tool call in the session - a bug
# here is worse than the slowness it fixes):
#   - Bounded wait, not indefinite: gives up and proceeds WITHOUT the lock (fails open) after
#     ~1.5s rather than risk hanging every tool call on a stuck lock.
#   - Stale-lock reclaim: a lock older than 10s is treated as an abandoned (crashed/killed)
#     holder and removed immediately rather than waited out.
#   Both are covered by real tests, not just asserted: tests/test_run_guard_lock.py drives
#   genuine concurrent subprocess calls (a thread pool, not a loop) and measures actual
#   overlap, plus dedicated stale-lock and held-lock-fails-open cases.
#
# NOT changed by this script:
#   - The interpreter resolution/caching logic itself (scripts/apply-guard-interpreter-cache.sh)
#     - this only wraps it with a lock, and switches `exec` to a foreground child + wait so the
#       lock can be released after the guard completes (exec would replace this process before
#       that could run). Documented stdin/exit-code passthrough contract is unchanged either way.
#
# Regression net: tests/test_run_guard_lock.py (new) + tests/test_run_guard_interpreter_cache.py
# + tests/test_hooks_in_sync.py's test_staged_matches_live - the sync tests FAIL (do not skip)
# until this script has been run.
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
echo "installed: $dst updated from staged copy."
echo "Now commit the change (both files ship together):"
echo "  git add .claude/hooks/run-guard.sh scripts/staged_hooks/run-guard.sh"
