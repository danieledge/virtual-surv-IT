#!/usr/bin/env bash
# Promote the /engage step-0 probe prefetch (scripts/staged_hooks/engage_probe_prefetch.py)
# to scripts/. It is RUN by scripts/prompt_hook_dispatcher.py (wired once in both hook files
# by apply-prompt-hook-dispatcher.sh), so this script adds no hook entry of its own.
#
# Pre-runs the /engage /engage-light /map-codebase step-0 probe from a hook (fires before
# the model's turn, plain stdout added to context - same mechanism persona_anchor.py and
# session_resume_brief.py already use) so the steady-state open skips the Bash heredoc
# round-trip entirely. Dormancy-exact: near-zero cost on every other prompt, and declines
# silently (no injected block) on a cold interpreter cache or any internal error - the
# live Bash-heredoc probe in engage-open.md stays the fallback, unchanged.
#
# HUMAN-RUN by design (hook/config edits are human-only, ADR-002 rec 5). Idempotent.
#   Usage:  bash scripts/apply-engage-probe-prefetch.sh
#   Undo:   remove the engage_probe_prefetch entry from both files (or `git checkout` them)
# Afterwards: commit both hook files + scripts/engage_probe_prefetch.py; restart the session.
set -euo pipefail

here="$(cd "$(dirname "$0")/.." && pwd)"

cp "$here/scripts/staged_hooks/engage_probe_prefetch.py" "$here/scripts/engage_probe_prefetch.py"
echo "engage_probe_prefetch: staged copy installed to scripts/."

# 2026-09-13: the hook is run by scripts/prompt_hook_dispatcher.py (wired by
# apply-prompt-hook-dispatcher.sh), so NO top-level UserPromptSubmit entry is added here any
# more. The block this replaced appended one unconditionally, which is how the entry came back
# in 5fc5174 after 7d2898a had removed it, and every prompt then paid an extra sh + Python
# spawn (tests/test_hooks_in_sync.py::test_no_script_wired_both_in_dispatcher_and_top_level).
if ! grep -q "prompt_hook_dispatcher.py" "$here/hooks/hooks.json"; then
    echo "note: the prompt-hook dispatcher is not wired - run: bash scripts/apply-prompt-hook-dispatcher.sh"
fi

echo "Done. Confirm: python3 -m pytest tests/test_engage_probe_prefetch.py -q; then commit both hook files + scripts/engage_probe_prefetch.py and restart the session."
