#!/usr/bin/env bash
# Install the findings-pack-write guard: path scope (P4, 2026-08-03) + opt-in size limit
# (2026-08-05) + Edit grant scoped the same way as Write (2026-08-06).
#
# NEW/updated guard at scripts/staged_hooks/guard-findings-pack-write.py, plus registers it in
# scripts/staged_hooks/bash_hook_dispatcher.py's _CHECKS (no settings.json/hooks.json change
# needed - the dispatcher's existing matcher already covers Write). Both are STAGED because
# hook/config edits are human-only (ADR-002 rec 5). Idempotent - safe to re-run after either
# addition below, or both together.
#
#   Usage:  bash scripts/apply-guard-findings-pack-write.sh
#   Undo:   git checkout .claude/hooks/guard-findings-pack-write.py scripts/bash_hook_dispatcher.py
#           (then rm .claude/hooks/guard-findings-pack-write.py if it did not exist before)
#
# WHAT THIS ADDS
#   1. Path scope (2026-08-03): `code-reviewer`, `compliance-reviewer`, `model-validator` and
#      `performance-reviewer` were granted `Write` so each authors its own findings-pack JSON
#      directly (artifacts/<slug>/data/findings-*.json) instead of returning the full pack
#      through the orchestrator's context and having the orchestrator re-emit it as a Write -
#      halving that round-trip's token cost. A Write grant with no path restriction is a much
#      bigger blast radius than "author one JSON file", so this half scopes it mechanically:
#      fires only when the calling `agent_type` (a PreToolUse field Claude Code provides for
#      subagent-originated tool calls) is one of the four, and blocks unless the target matches
#      the findings-pack shape.
#   2. Size limit (2026-08-05, opt-in via `large_context_review_split` in
#      `.claude/team-preferences.json`, default off): a live corp report found a 13-finding
#      consolidation write hitting `API Error: The operation timed out` on the same single-Write
#      attempt twice - a large-enough single generation can trip a corporate proxy's timeout
#      regardless of caller. This half blocks any Write to a findings-pack path (scoped agent OR
#      the orchestrator's own call) carrying more than 8 findings, ONLY when the project has
#      opted into the split preference - a project that hasn't hit the issue sees no behaviour
#      change. See docs/team-operating-guide.md's orchestration-discipline bullet for the
#      "write a small batch, then Edit to append the rest" guidance this backs mechanically.
#   3. Edit grant (2026-08-06, live freedom-dashboard diagnostic): the four scoped agents were
#      also granted `Edit`, scoped by this guard to the identical path pattern as Write. Without
#      it, an agent that hit the size cap above had no sanctioned way to chunk past it the way
#      the orchestrator can - a live run showed `performance-reviewer` hitting the cap and
#      silently dropping findings instead. Edit is exempt from the size cap by design (it is the
#      escape hatch past it), but stays scoped to the same one path - not a broader capability.
#   Every other Write/Edit call - unrelated paths, unrelated agents - passes through untouched.
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
