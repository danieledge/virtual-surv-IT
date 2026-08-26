#!/usr/bin/env bash
# Collapse the TWO UserPromptSubmit hook entries into ONE dispatcher, in both tracked hook
# files:
#   .claude/settings.json  -> repo-as-project mode
#   hooks/hooks.json        -> installed-plugin distribution
#
# WHY (F4, 2026-08-26 perf audit). persona_anchor.py and engage_probe_prefetch.py were
# registered as two independent UserPromptSubmit entries, so every user message paid two
# complete launcher chains - two `sh run-guard.sh`, two Python cold starts, two daemon
# round trips - to run 0.88ms and 0.66ms of actual work. Roughly 99% of the second
# invocation was pure overhead: ~90ms per prompt on Linux, and a whole extra sh+python.exe
# spawn pair per prompt on the corporate Windows box, where run-guard.sh's own field
# measurement is ~211ms per daemon-served invocation.
#
# scripts/prompt_hook_dispatcher.py runs both in one process, in the same registration
# order, concatenating their stdout - the same pattern bash_hook_dispatcher.py already
# established for the five hooks that match Bash.
#
# SAFETY NOTE: neither hook is a safety guard. Both inject context via stdout and always
# return 0, and the dispatcher fails open throughout - a crash costs the injected context,
# never the user's prompt. Nothing here touches the code-execution, raw-data or
# consent-write guards.
#
# HUMAN-RUN by design (hook/config edits are human-only, ADR-002 rec 5). Idempotent.
#   Usage:  bash scripts/apply-prompt-hook-dispatcher.sh
#   Undo:   git checkout .claude/settings.json hooks/hooks.json
# Afterwards: commit both hook files; restart the session so the daemon reloads.
set -euo pipefail

here="$(cd "$(dirname "$0")/.." && pwd)"

python3 - "$here/.claude/settings.json" "$here/hooks/hooks.json" <<'PY'
import json, sys

def cmd_for(script):
    return (
        'sh "${CLAUDE_PLUGIN_ROOT:-${CLAUDE_PROJECT_DIR:-.}}/.claude/hooks/run-guard.sh" '
        f'"${{CLAUDE_PLUGIN_ROOT:-${{CLAUDE_PROJECT_DIR:-.}}}}/scripts/{script}"'
    )

SUPERSEDED = {cmd_for("persona_anchor.py"), cmd_for("engage_probe_prefetch.py")}
DISPATCHER = cmd_for("prompt_hook_dispatcher.py")

for path in sys.argv[1:]:
    try:
        with open(path, encoding="utf-8") as fh:
            cfg = json.load(fh)
    except FileNotFoundError:
        print(f"skip (not found): {path}")
        continue

    entries = cfg.setdefault("hooks", {}).setdefault("UserPromptSubmit", [])
    if any(h.get("command") == DISPATCHER for e in entries for h in e.get("hooks", [])):
        print(f"already wired: {path}")
        continue

    # Drop only the two entries the dispatcher subsumes. Anything else a user or a later
    # change has added to UserPromptSubmit is left exactly where it is - this script owns
    # its own two entries, not the whole event.
    kept = []
    removed = 0
    for entry in entries:
        hooks = [h for h in entry.get("hooks", []) if h.get("command") not in SUPERSEDED]
        removed += len(entry.get("hooks", [])) - len(hooks)
        if hooks:
            entry["hooks"] = hooks
            kept.append(entry)
        elif not entry.get("hooks"):
            kept.append(entry)

    kept.append({"hooks": [{"type": "command", "command": DISPATCHER}]})
    cfg["hooks"]["UserPromptSubmit"] = kept
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=2)
        fh.write("\n")
    print(f"wired prompt dispatcher into {path} (superseded {removed} separate entr"
          f"{'y' if removed == 1 else 'ies'})")
PY

echo
echo "Done. Confirm with:"
echo "  python3 -m pytest tests/test_prompt_hook_dispatcher.py -q"
echo "Then commit both hook files and restart the session so the daemon reloads."
