#!/usr/bin/env bash
# Wrapper: runs every apply-*.sh script currently pending. HUMAN-RUN by design, same as
# everything it calls (hook/config edits are human-only, ADR-002 rec 5) - this script does
# not grant itself any exemption, it just sequences already-approved human-run scripts.
# Each one it calls is independently idempotent, so re-running this wrapper (e.g. after
# only some scripts were applied, or to pick up a later round's new staged content) is
# always safe - an already-applied script just no-ops.
#
# This list is a static snapshot of what was pending at the time it was last edited, not a
# dynamic scan - as new apply-*.sh scripts appear from future audits, add them here by
# hand. Confirm nothing is left pending with:
#   python3 -m pytest tests/test_hooks_in_sync.py -q
#
#   Usage:  bash scripts/apply-outstanding.sh
set -euo pipefail

here="$(cd "$(dirname "$0")/.." && pwd)"
cd "$here"

scripts=(
  apply-project-anchor.sh          # dod_stop_gate.py + persona_anchor.py: project-root anchoring
  apply-post-edit-lint.sh          # post_edit_lint.py: in-process py_compile, no subprocess
  apply-guard-raw-segment-fix.sh   # guard-raw-data.py: compound-command segments, quote-aware
  apply-guard-exec-allow.sh        # guard-code-execution.py: same quote-aware segment fix
  apply-todo-panel-nudge.sh        # todo_panel_nudge.py: code only (wiring below)
  apply-stop-hook-dispatcher.sh    # consolidates dod_stop_gate + todo_panel_nudge into one Stop hook
  apply-guard-findings-pack-write.sh  # new PreToolUse guard for the 4 reviewers' scoped Write
  apply-bash-hook-dispatcher.sh    # re-syncs the PreToolUse dispatcher to include the new guard
)

for s in "${scripts[@]}"; do
  echo "=== $s ==="
  bash "scripts/$s"
  echo
done

echo "All done. Confirm: python3 -m pytest tests/test_hooks_in_sync.py -q"
