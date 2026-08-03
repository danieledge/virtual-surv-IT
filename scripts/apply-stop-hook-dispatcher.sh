#!/usr/bin/env bash
# Wire the consolidated Stop-event dispatcher (scripts/stop_hook_dispatcher.py, perf audit,
# 2026-08-03) into BOTH tracked hook files, REPLACING the two separate Stop entries it
# subsumes:
#   .claude/settings.json  -> repo-as-project mode
#   hooks/hooks.json        -> installed-plugin distribution
#
# Removes the two old entries pointing at dod_stop_gate.py and todo_panel_nudge.py, and
# adds ONE new Stop entry pointing at the dispatcher, which runs the SAME two checks -
# unmodified, imported by file path - in one process instead of two. Every other hook
# (the PreToolUse dispatcher, locked_menu_guard, UserPromptSubmit's persona_anchor,
# SessionStart's session_resume_brief, PostToolUse's post_edit_lint/subagent_return_budget)
# is untouched.
#
# HUMAN-RUN by design (hook/config edits are human-only, ADR-002 rec 5). Idempotent - safe
# to re-run; a partial prior run converges to the same end state.
#   Usage:  bash scripts/apply-stop-hook-dispatcher.sh
#   Undo:   git checkout .claude/settings.json hooks/hooks.json
# Afterwards: commit both hook files + scripts/stop_hook_dispatcher.py; restart the
# session (hooks are read once, at session start).
set -euo pipefail

here="$(cd "$(dirname "$0")/.." && pwd)"

cp "$here/scripts/staged_hooks/stop_hook_dispatcher.py" "$here/scripts/stop_hook_dispatcher.py"
echo "stop_hook_dispatcher: staged copy installed to scripts/."

python3 - "$here/.claude/settings.json" "$here/hooks/hooks.json" <<'PY'
import json, sys

LAUNCH = 'sh "${CLAUDE_PLUGIN_ROOT:-${CLAUDE_PROJECT_DIR:-.}}/.claude/hooks/run-guard.sh" '
OLD_COMMANDS = {
    LAUNCH + '"${CLAUDE_PLUGIN_ROOT:-${CLAUDE_PROJECT_DIR:-.}}/scripts/dod_stop_gate.py"',
    LAUNCH + '"${CLAUDE_PLUGIN_ROOT:-${CLAUDE_PROJECT_DIR:-.}}/scripts/todo_panel_nudge.py"',
}
NEW_COMMAND = LAUNCH + '"${CLAUDE_PLUGIN_ROOT:-${CLAUDE_PROJECT_DIR:-.}}/scripts/stop_hook_dispatcher.py"'

for path in sys.argv[1:]:
    try:
        with open(path, encoding="utf-8") as fh:
            cfg = json.load(fh)
    except FileNotFoundError:
        print(f"skip (not found): {path}")
        continue
    stop = cfg.setdefault("hooks", {}).setdefault("Stop", [])

    def is_old(entry):
        return any(h.get("command") in OLD_COMMANDS for h in entry.get("hooks", []))

    already_new = any(
        h.get("command") == NEW_COMMAND for entry in stop for h in entry.get("hooks", [])
    )
    removed = sum(1 for entry in stop if is_old(entry))
    kept = [entry for entry in stop if not is_old(entry)]

    if not removed and already_new:
        print(f"already consolidated: {path}")
        continue

    if not already_new:
        kept.append({"hooks": [{"type": "command", "command": NEW_COMMAND}]})
    cfg["hooks"]["Stop"] = kept

    with open(path, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=2)
        fh.write("\n")
    print(f"consolidated: {path} (removed {removed} old entr{'y' if removed == 1 else 'ies'}, "
          f"{'added' if not already_new else 'kept'} the dispatcher entry)")
PY

echo "Done. Confirm: python3 -m pytest tests/test_stop_hook_dispatcher.py -q"
echo "Then commit both hook files + scripts/stop_hook_dispatcher.py and restart the session."
