#!/bin/bash
# Install the repo's opt-in git hooks (AI review on push). Run once:
#   bash scripts/install-git-hooks.sh
set -e
root=$(git rev-parse --show-toplevel)
src="$root/scripts/git-hooks"
dst="$root/.git/hooks"

install -m 0755 "$src/pre-push" "$dst/pre-push"
echo "✅ Installed pre-push AI review hook -> $dst/pre-push"
echo "   (advisory — does not block the push). Remove with: rm $dst/pre-push"
echo
echo "Tip: also run 'pre-commit install' to enable the deterministic gates"
echo "     (tests, secret scan, no-raw-data) before each commit."
