#!/usr/bin/env bash
# Wire the task-panel Stop-hook nudge (scripts/staged_hooks/todo_panel_nudge.py) into
# BOTH tracked hook files as a Stop hook (no matcher - Stop events aren't tool-specific):
#   .claude/settings.json  -> repo-as-project mode
#   hooks/hooks.json        -> installed-plugin distribution
#
# One-time, self-suppressing reminder to seed the native task-list gate panel once an
# engagement reaches delivery - a live audit (2026-07-30) found zero genuine TodoWrite
# calls across every kept eval transcript, meaning the operating guide's claim that
# gates appear there was pure prose, never nudged. Warn-first, matches
# dod_stop_gate.py's exact Stop-hook shape; fails open on any error.
#
# HUMAN-RUN by design (hook/config edits are human-only, ADR-002 rec 5). Idempotent.
#   Usage:  bash scripts/apply-todo-panel-nudge.sh
#   Undo:   remove the Stop entry pointing at todo_panel_nudge.py from both files
# Afterwards: commit both hook files + scripts/todo_panel_nudge.py; restart the session.
set -euo pipefail

here="$(cd "$(dirname "$0")/.." && pwd)"

cp "$here/scripts/staged_hooks/todo_panel_nudge.py" "$here/scripts/todo_panel_nudge.py"
echo "todo_panel_nudge: staged copy installed to scripts/."

python3 - "$here/.claude/settings.json" "$here/hooks/hooks.json" <<'PY'
import json, sys

cmd = (
    'sh "${CLAUDE_PLUGIN_ROOT:-${CLAUDE_PROJECT_DIR:-.}}/.claude/hooks/run-guard.sh" '
    '"${CLAUDE_PLUGIN_ROOT:-${CLAUDE_PROJECT_DIR:-.}}/scripts/todo_panel_nudge.py"'
)

for path in sys.argv[1:]:
    try:
        with open(path, encoding="utf-8") as fh:
            cfg = json.load(fh)
    except FileNotFoundError:
        print(f"skip (not found): {path}")
        continue
    stop = cfg.setdefault("hooks", {}).setdefault("Stop", [])
    if any(h.get("command") == cmd for entry in stop for h in entry.get("hooks", [])):
        print(f"already wired: {path}")
        continue
    stop.append({"hooks": [{"type": "command", "command": cmd}]})
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=2)
        fh.write("\n")
    print(f"wired todo-panel nudge into: {path}")
PY

echo "Done. Confirm: python3 -m pytest tests/test_todo_panel_nudge.py -q; then commit both hook files + scripts/todo_panel_nudge.py and restart the session."
