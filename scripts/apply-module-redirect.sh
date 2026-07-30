#!/bin/bash
# HUMAN-run (ADR-002 rec 5: hook wiring is a human act): wires the module-form
# redirect hook into the plugin's hooks.json. The hook script itself is already
# staged AND live (scripts/module_form_redirect.py, byte-synced with
# scripts/staged_hooks/); this only adds the PreToolUse(Bash) entry.
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
if any(cmd in json.dumps(entry) for entry in pre):
    print("module_form_redirect already wired - nothing to do")
else:
    pre.append({"matcher": "Bash", "hooks": [{"type": "command", "command": cmd}]})
    p.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print("wired module_form_redirect into hooks/hooks.json")
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
if any(cmd in json.dumps(entry) for entry in pre):
    print("module_form_redirect already wired - nothing to do")
else:
    pre.append({"matcher": "Bash", "hooks": [{"type": "command", "command": cmd}]})
    p.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print("wired module_form_redirect into hooks/hooks.json")
PY2
