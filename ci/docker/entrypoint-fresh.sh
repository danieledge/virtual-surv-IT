#!/usr/bin/env bash
# Install the plugin the way a user does, into a throwaway client project, and prove the
# guards fire there. Exit non-zero on any failure. No model call is made unless a session is
# started explicitly by the caller afterwards.
set -euo pipefail

BRANCH="${VS_BRANCH:-dev}"
REPO_URL="${VS_REPO_URL:-https://github.com/danieledge/virtual-surv-IT.git}"
CLONE="${VS_CLONE:-/home/tester/virt-survtecb}"
PROJECT="${VS_PROJECT:-/home/tester/client-project}"

echo "== clone $BRANCH =="
git clone --branch "$BRANCH" --quiet "$REPO_URL" "$CLONE"

echo "== the real marketplace commands =="
claude plugin marketplace add "$CLONE"
claude plugin install compliance-surveillance-team@virtual-surv-it

echo "== a client project with the plugin enabled =="
mkdir -p "$PROJECT/.claude"
cat > "$PROJECT/.claude/settings.json" <<'JSON'
{ "enabledPlugins": { "compliance-surveillance-team@virtual-surv-it": true } }
JSON
echo "# client project" > "$PROJECT/README.md"

echo "== installed copy, resolved the way the hooks resolve it =="
PLUGIN_ROOT="$(python3 "$CLONE/scripts/find_plugin_root.py" "$HOME" "$PROJECT" 2>/dev/null || true)"
if [ -z "$PLUGIN_ROOT" ] || [ ! -d "$PLUGIN_ROOT" ]; then
    PLUGIN_ROOT="$(ls -d "$HOME"/.claude/plugins/cache/virtual-surv-it/compliance-surveillance-team/* 2>/dev/null | tail -1 || true)"
fi
[ -n "$PLUGIN_ROOT" ] && [ -d "$PLUGIN_ROOT" ] || { echo "FAIL: no installed plugin copy found" >&2; exit 1; }
echo "PLUGIN_ROOT=$PLUGIN_ROOT"

echo "== guards armed in the client project? =="
python3 "$PLUGIN_ROOT/scripts/armed_check.py" --repo "$PLUGIN_ROOT" --project "$PROJECT"
