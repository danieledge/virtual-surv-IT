#!/usr/bin/env bash
# Install the consent-write guard fix closing the git-execution-config escape (audit 2026-08-01).
#
# The improved guard is STAGED at scripts/staged_hooks/guard-consent-writes.py because the live
# guard blocks the model from editing .claude/hooks/** (correctly - a model that can edit a guard
# can neuter it). Installing is therefore a HUMAN act (ADR-002 rec 5). Idempotent.
#
#   Usage:  bash scripts/apply-guard-git-config.sh
#   Undo:   git checkout .claude/hooks/guard-consent-writes.py
#
# WHAT THIS CLOSES
#   `.git/config` was not in the protected set, so `git config core.hooksPath /tmp/h`, an
#   external diff/merge driver, or a plain Write of .git/config handed the NEXT `git commit` /
#   `git diff` arbitrary execution - with no consent marker written and no gate consulted. The
#   "model cannot grant itself execution consent" property stayed technically true while its
#   purpose was defeated. ADR-002 rec 14c recorded the external-driver shape as "adjacent
#   unfixed" and never named core.hooksPath.
#
#   Also adds Bash MUTATION protection for the guard files themselves (sed -i / tee / cp / rm /
#   redirect). Reading and static-analysing a guard stays allowed - that read/analyse case is the
#   false positive the original Write/Edit-only rule was protecting, and it is regression-tested.
#
# Regression net: tests/test_guard_git_config.py (its live-vs-staged test FAILS - it does not
# skip - until this script has been run).
set -euo pipefail

here="$(cd "$(dirname "$0")/.." && pwd)"
src="$here/scripts/staged_hooks/guard-consent-writes.py"
dst="$here/.claude/hooks/guard-consent-writes.py"

[ -f "$src" ] || { echo "ERROR: staged guard not found at $src" >&2; exit 1; }

if cmp -s "$src" "$dst"; then
  echo "already installed - staged and live guards are identical."
  exit 0
fi

cp "$src" "$dst"
echo "installed: $dst updated from staged copy."
echo "Now commit the change (both files ship together):"
echo "  git add .claude/hooks/guard-consent-writes.py scripts/staged_hooks/guard-consent-writes.py"
