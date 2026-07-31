#!/usr/bin/env bash
# Wire the subagent condensed-return budget feedback
# (scripts/staged_hooks/subagent_return_budget.py) into BOTH tracked hook files as a
# PostToolUse hook on Task:
#   .claude/settings.json  -> repo-as-project mode
#   hooks/hooks.json        -> installed-plugin distribution
#
# Advisory feedback the moment a subagent's return is clearly over the operating guide's
# condensed-return budget (~1,500 tokens / ~30 lines, triggers at 2x); during live
# engagements only; dormant sessions untouched; fails open on any parsing surprise.
#
# HUMAN-RUN by design (hook/config edits are human-only, ADR-002 rec 5). Idempotent.
#   Usage:  bash scripts/apply-subagent-budget.sh
#   Undo:   remove the PostToolUse entry from both files (or `git checkout` them)
# Afterwards: commit both hook files + scripts/subagent_return_budget.py; restart the session.
set -euo pipefail

here="$(cd "$(dirname "$0")/.." && pwd)"

cp "$here/scripts/staged_hooks/subagent_return_budget.py" "$here/scripts/subagent_return_budget.py"
echo "subagent_return_budget: staged copy installed to scripts/."

python3 - "$here/.claude/settings.json" "$here/hooks/hooks.json" <<'PY'
import json, sys

cmd = (
    'sh "${CLAUDE_PLUGIN_ROOT:-${CLAUDE_PROJECT_DIR:-.}}/.claude/hooks/run-guard.sh" '
    '"${CLAUDE_PLUGIN_ROOT:-${CLAUDE_PROJECT_DIR:-.}}/scripts/subagent_return_budget.py"'
)

for path in sys.argv[1:]:
    try:
        with open(path, encoding="utf-8") as fh:
            cfg = json.load(fh)
    except FileNotFoundError:
        print(f"skip (not found): {path}")
        continue
    post = cfg.setdefault("hooks", {}).setdefault("PostToolUse", [])
    if any(h.get("command") == cmd for entry in post for h in entry.get("hooks", [])):
        print(f"already wired: {path}")
        continue
    post.append({"matcher": "Task", "hooks": [{"type": "command", "command": cmd}]})
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=2)
        fh.write("\n")
    print(f"wired subagent-return-budget into: {path}")
PY

echo "Done. Confirm: python3 -m pytest tests/test_subagent_return_budget.py -q; then commit both hook files + scripts/subagent_return_budget.py and restart the session."
