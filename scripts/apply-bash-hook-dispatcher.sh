#!/usr/bin/env bash
# Wire the consolidated Bash-hook dispatcher (scripts/bash_hook_dispatcher.py, P4,
# 2026-07-31 corp report) into BOTH tracked hook files, REPLACING the five separate
# PreToolUse entries it subsumes:
#   .claude/settings.json  -> repo-as-project mode
#   hooks/hooks.json        -> installed-plugin distribution
#
# Removes the five old entries pointing at guard-raw-data.py, guard-code-execution.py,
# guard-consent-writes.py, document_input_redirect.py and module_form_redirect.py, and
# adds ONE new PreToolUse entry (matcher = the union of all five) pointing at the
# dispatcher, which runs the SAME five checks - unmodified, imported by file path - in
# one process instead of five. Every other hook (locked_menu_guard on AskUserQuestion,
# the Stop/UserPromptSubmit/SessionStart/PostToolUse hooks) is untouched.
#
# HUMAN-RUN by design (hook/config edits are human-only, ADR-002 rec 5). Idempotent -
# safe to re-run; a partial prior run (old entries gone, new one not yet added, or vice
# versa) converges to the same end state.
#   Usage:  bash scripts/apply-bash-hook-dispatcher.sh
#   Undo:   git checkout .claude/settings.json hooks/hooks.json
# Afterwards: commit both hook files + scripts/bash_hook_dispatcher.py; restart the
# session (hooks are read once, at session start).
set -euo pipefail

here="$(cd "$(dirname "$0")/.." && pwd)"

cp "$here/scripts/staged_hooks/bash_hook_dispatcher.py" "$here/scripts/bash_hook_dispatcher.py"
echo "bash_hook_dispatcher: staged copy installed to scripts/."

python3 - "$here/.claude/settings.json" "$here/hooks/hooks.json" <<'PY'
import json, sys

LAUNCH = 'sh "${CLAUDE_PLUGIN_ROOT:-${CLAUDE_PROJECT_DIR:-.}}/.claude/hooks/run-guard.sh" '
OLD_COMMANDS = {
    LAUNCH + '"${CLAUDE_PLUGIN_ROOT:-${CLAUDE_PROJECT_DIR:-.}}/.claude/hooks/guard-raw-data.py"',
    LAUNCH + '"${CLAUDE_PLUGIN_ROOT:-${CLAUDE_PROJECT_DIR:-.}}/.claude/hooks/guard-code-execution.py"',
    LAUNCH + '"${CLAUDE_PLUGIN_ROOT:-${CLAUDE_PROJECT_DIR:-.}}/.claude/hooks/guard-consent-writes.py"',
    LAUNCH + '"${CLAUDE_PLUGIN_ROOT:-${CLAUDE_PROJECT_DIR:-.}}/scripts/document_input_redirect.py"',
    LAUNCH + '"${CLAUDE_PLUGIN_ROOT:-${CLAUDE_PROJECT_DIR:-.}}/scripts/module_form_redirect.py"',
}
NEW_COMMAND = LAUNCH + '"${CLAUDE_PLUGIN_ROOT:-${CLAUDE_PROJECT_DIR:-.}}/scripts/bash_hook_dispatcher.py"'
NEW_MATCHER = "Read|Grep|Glob|Write|Edit|MultiEdit|NotebookEdit|Bash"

for path in sys.argv[1:]:
    try:
        with open(path, encoding="utf-8") as fh:
            cfg = json.load(fh)
    except FileNotFoundError:
        print(f"skip (not found): {path}")
        continue
    pre = cfg.setdefault("hooks", {}).setdefault("PreToolUse", [])

    def is_old(entry):
        return any(h.get("command") in OLD_COMMANDS for h in entry.get("hooks", []))

    already_new = any(
        h.get("command") == NEW_COMMAND for entry in pre for h in entry.get("hooks", [])
    )
    removed = sum(1 for entry in pre if is_old(entry))
    kept = [entry for entry in pre if not is_old(entry)]

    if not removed and already_new:
        print(f"already consolidated: {path}")
        continue

    if not already_new:
        kept.append(
            {"matcher": NEW_MATCHER, "hooks": [{"type": "command", "command": NEW_COMMAND}]}
        )
    cfg["hooks"]["PreToolUse"] = kept

    with open(path, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=2)
        fh.write("\n")
    print(f"consolidated: {path} (removed {removed} old entr{'y' if removed == 1 else 'ies'}, "
          f"{'added' if not already_new else 'kept'} the dispatcher entry)")
PY

echo "Done. Confirm: python3 -m pytest tests/test_bash_hook_dispatcher.py -q"
echo "Then commit both hook files + scripts/bash_hook_dispatcher.py and restart the session."
