#!/bin/bash
# HUMAN-run (ADR-002 rec 5: hook wiring is a human act): wires the module-form
# redirect hook into the plugin's hooks.json AND the repo's .claude/settings.json
# (test_hooks_in_sync requires the two PreToolUse sets identical). The hook script
# itself is already staged AND live (scripts/module_form_redirect.py, byte-synced
# with scripts/staged_hooks/); this only adds the PreToolUse(Bash) entries.
# Idempotent - safe to re-run.
#
#   bash scripts/apply-module-redirect.sh
set -euo pipefail
cd "$(dirname "$0")/.."

python3 - <<'PY' || python - <<'PY2'
import json
from pathlib import Path

p = Path("hooks/hooks.json")
data = json.loads(p.read_text(encoding="utf-8"))
pre = data["hooks"]["PreToolUse"]
cmd = (
    'sh "${CLAUDE_PLUGIN_ROOT:-${CLAUDE_PROJECT_DIR:-.}}/.claude/hooks/run-guard.sh" '
    '"${CLAUDE_PLUGIN_ROOT:-${CLAUDE_PROJECT_DIR:-.}}/scripts/module_form_redirect.py"'
)
def wire(entries):
    """Exact-command idempotency + dedupe. The first version of this script tested
    `cmd in json.dumps(entry)` - dumps escapes the quotes, so the check NEVER matched
    and a re-run appended a duplicate (live 2026-07-30). Compare the command value
    itself, and remove any extra copies a previous run left behind."""
    keep, seen, changed = [], 0, False
    for e in entries:
        cmds = [h.get("command") for h in e.get("hooks", [])]
        if cmds == [cmd]:
            seen += 1
            if seen > 1:
                changed = True
                continue  # drop the duplicate
        keep.append(e)
    if seen == 0:
        keep.append({"matcher": "Bash", "hooks": [{"type": "command", "command": cmd}]})
        changed = True
    entries[:] = keep
    return changed, seen

changed, seen = wire(pre)
if changed:
    p.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(("deduped" if seen > 1 else "wired") + " module_form_redirect in hooks/hooks.json")
else:
    print("module_form_redirect already wired in hooks/hooks.json")

sp = Path(".claude/settings.json")
sdata = json.loads(sp.read_text(encoding="utf-8"))
spre = sdata.setdefault("hooks", {}).setdefault("PreToolUse", [])
changed, seen = wire(spre)
if changed:
    sp.write_text(json.dumps(sdata, indent=2) + "\n", encoding="utf-8")
    print(("deduped" if seen > 1 else "wired") + " module_form_redirect in project settings")
else:
    print("module_form_redirect already wired in project settings")
PY
import json
from pathlib import Path

p = Path("hooks/hooks.json")
data = json.loads(p.read_text(encoding="utf-8"))
pre = data["hooks"]["PreToolUse"]
cmd = (
    'sh "${CLAUDE_PLUGIN_ROOT:-${CLAUDE_PROJECT_DIR:-.}}/.claude/hooks/run-guard.sh" '
    '"${CLAUDE_PLUGIN_ROOT:-${CLAUDE_PROJECT_DIR:-.}}/scripts/module_form_redirect.py"'
)
def wire(entries):
    """Exact-command idempotency + dedupe. The first version of this script tested
    `cmd in json.dumps(entry)` - dumps escapes the quotes, so the check NEVER matched
    and a re-run appended a duplicate (live 2026-07-30). Compare the command value
    itself, and remove any extra copies a previous run left behind."""
    keep, seen, changed = [], 0, False
    for e in entries:
        cmds = [h.get("command") for h in e.get("hooks", [])]
        if cmds == [cmd]:
            seen += 1
            if seen > 1:
                changed = True
                continue  # drop the duplicate
        keep.append(e)
    if seen == 0:
        keep.append({"matcher": "Bash", "hooks": [{"type": "command", "command": cmd}]})
        changed = True
    entries[:] = keep
    return changed, seen

changed, seen = wire(pre)
if changed:
    p.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(("deduped" if seen > 1 else "wired") + " module_form_redirect in hooks/hooks.json")
else:
    print("module_form_redirect already wired in hooks/hooks.json")

sp = Path(".claude/settings.json")
sdata = json.loads(sp.read_text(encoding="utf-8"))
spre = sdata.setdefault("hooks", {}).setdefault("PreToolUse", [])
changed, seen = wire(spre)
if changed:
    sp.write_text(json.dumps(sdata, indent=2) + "\n", encoding="utf-8")
    print(("deduped" if seen > 1 else "wired") + " module_form_redirect in project settings")
else:
    print("module_form_redirect already wired in project settings")
PY2
