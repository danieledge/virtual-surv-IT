#!/usr/bin/env bash
# Install the project-root anchoring patch for the DoD stop gate and the persona anchor.
#
# The patched hooks are STAGED at scripts/staged_hooks/{dod_stop_gate,persona_anchor}.py
# because hook changes are a HUMAN act (ADR-002 rec 5 / the hook-hardening rule). Idempotent.
#
#   Usage:  bash scripts/apply-project-anchor.sh
#   Undo:   git checkout scripts/dod_stop_gate.py scripts/persona_anchor.py
#
# What changes (tested in tests/test_staged_project_anchor.py):
#   Both hooks anchor on CLAUDE_PROJECT_DIR (the session's project root) instead of the
#   hook-input cwd. Fixes the 2026-07-25 nuisance where a shell cwd that wandered into a kept
#   eval sandbox (evals/runs/<ts>/<case>/sandbox has its own open START-HERE) made the stop
#   gate nudge about frozen evidence and the persona anchor summon Morgan uninvited. Sandboxed
#   eval sessions keep both hooks fully armed (there, project root == sandbox), and a harness
#   without CLAUDE_PROJECT_DIR falls back to the old cwd behaviour unchanged.
set -euo pipefail

here="$(cd "$(dirname "$0")/.." && pwd)"
changed=0
for name in dod_stop_gate persona_anchor; do
  src="$here/scripts/staged_hooks/$name.py"
  dst="$here/scripts/$name.py"
  [ -f "$src" ] || { echo "ERROR: staged hook not found at $src" >&2; exit 1; }
  if cmp -s "$src" "$dst"; then
    echo "$name: already installed (staged and live copies identical)."
  else
    cp "$src" "$dst"
    echo "$name: installed from the staged copy."
    changed=1
  fi
done
if [ "$changed" = 1 ]; then
  echo "Confirm: python3 -m pytest tests/test_dod_stop_gate.py tests/test_persona_anchor.py tests/test_staged_project_anchor.py -q"
  echo "Then commit the hook change."
fi
