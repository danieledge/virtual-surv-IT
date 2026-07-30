#!/usr/bin/env bash
# Wire the locked-menu drift guard (scripts/staged_hooks/locked_menu_guard.py) into BOTH
# tracked hook files as a PreToolUse hook on AskUserQuestion:
#   .claude/settings.json  -> repo-as-project mode
#   hooks/hooks.json        -> installed-plugin distribution
#
# Blocks (exit 2 + stderr) a malformed reproduction of the review-menu or artifact-menu
# LOCKED constructions before it reaches the user - narrow, only fires once it recognises
# the call as one of these two specific menus; every other AskUserQuestion call, locked
# or not, passes through untouched.
#
# HUMAN-RUN by design (hook/config edits are human-only, ADR-002 rec 5). Idempotent.
#   Usage:  bash scripts/apply-locked-menu-guard.sh
#   Undo:   remove the PreToolUse entry from both files (or `git checkout` them)
# Afterwards: commit both hook files + scripts/locked_menu_guard.py; restart the session.
set -euo pipefail

here="$(cd "$(dirname "$0")/.." && pwd)"

cp "$here/scripts/staged_hooks/locked_menu_guard.py" "$here/scripts/locked_menu_guard.py"
echo "locked_menu_guard: staged copy installed to scripts/."

python3 - "$here/.claude/settings.json" "$here/hooks/hooks.json" <<'PY'
import json, sys

cmd = (
    'sh "${CLAUDE_PLUGIN_ROOT:-${CLAUDE_PROJECT_DIR:-.}}/.claude/hooks/run-guard.sh" '
    '"${CLAUDE_PLUGIN_ROOT:-${CLAUDE_PROJECT_DIR:-.}}/scripts/locked_menu_guard.py"'
)

for path in sys.argv[1:]:
    try:
        with open(path, encoding="utf-8") as fh:
            cfg = json.load(fh)
    except FileNotFoundError:
        print(f"skip (not found): {path}")
        continue
    pre = cfg.setdefault("hooks", {}).setdefault("PreToolUse", [])
    if any(h.get("command") == cmd for entry in pre for h in entry.get("hooks", [])):
        print(f"already wired: {path}")
        continue
    pre.append({"matcher": "AskUserQuestion", "hooks": [{"type": "command", "command": cmd}]})
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=2)
        fh.write("\n")
    print(f"wired locked-menu guard into: {path}")
PY

echo "Done. Confirm: python3 -m pytest tests/test_locked_menu_guard.py -q; then commit both hook files + scripts/locked_menu_guard.py and restart the session."
