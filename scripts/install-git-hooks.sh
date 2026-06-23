#!/bin/bash
# Install the repo's opt-in AI-review git hooks. Run once:
#   bash scripts/install-git-hooks.sh                # both hooks
#   bash scripts/install-git-hooks.sh pre-commit     # just the commit gate
#   bash scripts/install-git-hooks.sh pre-push       # just the push review
#
# The severity-blocking gate is adapted from turingmind-code-review (MIT) — see
# THIRD-PARTY-LICENSES.md. Both hooks are OFF until installed, and an LLM in the git path is
# slow — bypass any single run with `--no-verify`.
set -euo pipefail
root=$(git rev-parse --show-toplevel)
src="$root/scripts/git-hooks"
dst=$(git rev-parse --git-path hooks)   # worktree/submodule-safe
which=${1:-all}

install_hook() {
  install -m 0755 "$src/$1" "$dst/$1"
  echo "✅ Installed $1 -> $dst/$1"
}

if [ "$which" = "all" ] || [ "$which" = "pre-commit" ]; then
  install_hook pre-commit
  echo "   Commit gate: BLOCKS on 🔴 Critical or any §5 data-safety finding; 🟠 Warning is advisory."
  echo "   Bypass one commit with: git commit --no-verify"
fi
if [ "$which" = "all" ] || [ "$which" = "pre-push" ]; then
  install_hook pre-push
  echo "   Push review: advisory (does not block). Bypass with: git push --no-verify"
fi

echo
echo "Tip: also run 'pre-commit install' for the deterministic gates"
echo "     (tests, secret scan, no-raw-data) — separate from the AI review gate above."
