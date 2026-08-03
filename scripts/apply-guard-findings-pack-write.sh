#!/usr/bin/env bash
# Install the findings-pack-write scope guard (token-usage audit, P4, 2026-08-03).
#
# NEW guard at scripts/staged_hooks/guard-findings-pack-write.py, plus registers it in
# scripts/staged_hooks/bash_hook_dispatcher.py's _CHECKS (no settings.json/hooks.json change
# needed - the dispatcher's existing matcher already covers Write). Both are STAGED because
# hook/config edits are human-only (ADR-002 rec 5). Idempotent.
#
#   Usage:  bash scripts/apply-guard-findings-pack-write.sh
#   Undo:   git checkout .claude/hooks/guard-findings-pack-write.py scripts/bash_hook_dispatcher.py
#           (then rm .claude/hooks/guard-findings-pack-write.py if it did not exist before)
#
# WHAT THIS ADDS
#   `code-reviewer`, `compliance-reviewer`, `model-validator` and `performance-reviewer` were
#   granted `Write` so each authors its own findings-pack JSON directly (artifacts/<slug>/data/
#   findings-*.json) instead of returning the full pack through the orchestrator's context and
#   having the orchestrator re-emit it as a Write - halving that round-trip's token cost. A
#   Write grant with no path restriction is a much bigger blast radius than "author one JSON
#   file", so this guard scopes it mechanically: fires only when the calling `agent_type` (a
#   PreToolUse field Claude Code provides for subagent-originated tool calls) is one of the
#   four, and blocks unless the target matches the findings-pack shape. Every other Write call -
#   the orchestrator's own, a build agent's - passes through untouched.
#
# Regression net: tests/test_guard_findings_pack_write.py (the live-vs-staged sync test FAILS -
# it does not skip - until this script has been run), tests/test_bash_hook_dispatcher.py.
set -euo pipefail

here="$(cd "$(dirname "$0")/.." && pwd)"

guard_src="$here/scripts/staged_hooks/guard-findings-pack-write.py"
guard_dst="$here/.claude/hooks/guard-findings-pack-write.py"
[ -f "$guard_src" ] || { echo "ERROR: staged guard not found at $guard_src" >&2; exit 1; }

if [ -f "$guard_dst" ] && cmp -s "$guard_src" "$guard_dst"; then
  echo "guard-findings-pack-write: already installed."
else
  cp "$guard_src" "$guard_dst"
  echo "guard-findings-pack-write: installed to $guard_dst."
fi

dispatcher_src="$here/scripts/staged_hooks/bash_hook_dispatcher.py"
dispatcher_dst="$here/scripts/bash_hook_dispatcher.py"
if cmp -s "$dispatcher_src" "$dispatcher_dst"; then
  echo "bash_hook_dispatcher: already up to date."
else
  cp "$dispatcher_src" "$dispatcher_dst"
  echo "bash_hook_dispatcher: updated (registered the new guard)."
fi

echo "Now commit the changes:"
echo "  git add .claude/hooks/guard-findings-pack-write.py scripts/bash_hook_dispatcher.py scripts/staged_hooks/guard-findings-pack-write.py scripts/staged_hooks/bash_hook_dispatcher.py"
echo "Confirm: python3 -m pytest tests/test_guard_findings_pack_write.py tests/test_bash_hook_dispatcher.py -q"
echo "Then restart the session (hooks are read once, at session start)."
