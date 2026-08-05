#!/usr/bin/env bash
# Close the WebFetch/NotebookRead wiring gap in the raw-data guard (whole-plugin review,
# 2026-08-05).
#
# The 2026-08-01 coverage fix (ADR-002 rec 22, applied via apply-guard-raw-coverage.sh) taught
# guard-raw-data.py itself to handle WebFetch (file:// URLs address the local filesystem) and
# NotebookRead, plus a defence-in-depth scan for any other unknown tool. But nothing wired those
# tool names through to the guard: the PreToolUse matcher in hooks/hooks.json and
# .claude/settings.json only ever listed
#   Read|Grep|Glob|Write|Edit|MultiEdit|NotebookEdit|Bash
# so a WebFetch or NotebookRead call never even started the dispatcher process, and the
# dispatcher's own _CHECKS table further restricted guard_raw_data to
# {Read, Grep, Glob, Bash} regardless. The 2026-08-01 fix was live code with a dead wiring path.
#
# This script:
#   1. Installs the staged scripts/bash_hook_dispatcher.py, which adds WebFetch and
#      NotebookRead to guard_raw_data's tool set in _CHECKS.
#   2. Widens the PreToolUse matcher for the dispatcher entry in BOTH tracked hook files to
#      include WebFetch and NotebookRead, so those tool calls reach the dispatcher at all.
#
# HUMAN-RUN by design (hook/config edits are human-only, ADR-002 rec 5). Idempotent.
#   Usage:  bash scripts/apply-guard-raw-webfetch-wiring.sh
#   Undo:   git checkout .claude/settings.json hooks/hooks.json scripts/bash_hook_dispatcher.py
# Afterwards: commit all three files; restart the session (hooks are read once, at session
# start).
set -euo pipefail

here="$(cd "$(dirname "$0")/.." && pwd)"

cp "$here/scripts/staged_hooks/bash_hook_dispatcher.py" "$here/scripts/bash_hook_dispatcher.py"
echo "bash_hook_dispatcher: staged copy (WebFetch/NotebookRead coverage) installed to scripts/."

python3 - "$here/.claude/settings.json" "$here/hooks/hooks.json" <<'PY'
import json, sys

DISPATCHER_COMMAND = (
    'sh "${CLAUDE_PLUGIN_ROOT:-${CLAUDE_PROJECT_DIR:-.}}/.claude/hooks/run-guard.sh" '
    '"${CLAUDE_PLUGIN_ROOT:-${CLAUDE_PROJECT_DIR:-.}}/scripts/bash_hook_dispatcher.py"'
)
OLD_MATCHER = "Read|Grep|Glob|Write|Edit|MultiEdit|NotebookEdit|Bash"
NEW_MATCHER = "Read|Grep|Glob|Write|Edit|MultiEdit|NotebookEdit|NotebookRead|WebFetch|Bash"

for path in sys.argv[1:]:
    try:
        with open(path, encoding="utf-8") as fh:
            cfg = json.load(fh)
    except FileNotFoundError:
        print(f"skip (not found): {path}")
        continue
    pre = cfg.get("hooks", {}).get("PreToolUse", [])
    changed = False
    for entry in pre:
        if any(h.get("command") == DISPATCHER_COMMAND for h in entry.get("hooks", [])):
            if entry.get("matcher") == NEW_MATCHER:
                print(f"already widened: {path}")
            elif entry.get("matcher") == OLD_MATCHER:
                entry["matcher"] = NEW_MATCHER
                changed = True
            else:
                print(
                    f"WARNING: dispatcher matcher in {path} is neither the expected old nor "
                    f"new value ({entry.get('matcher')!r}) - left untouched, check manually."
                )
    if changed:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(cfg, fh, indent=2)
            fh.write("\n")
        print(f"widened: {path} (dispatcher matcher now includes WebFetch|NotebookRead)")
PY

echo "Done. Confirm: python3 -m pytest tests/test_bash_hook_dispatcher.py tests/test_guard_raw_coverage.py -q"
echo "Then commit .claude/settings.json, hooks/hooks.json and scripts/bash_hook_dispatcher.py, and restart the session."
