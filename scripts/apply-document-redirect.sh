#!/usr/bin/env bash
# Wire the document-input redirect (scripts/staged_hooks/document_input_redirect.py) into
# BOTH tracked hook files as a PreToolUse hook on Read|Bash:
#   .claude/settings.json  -> repo-as-project mode
#   hooks/hooks.json        -> installed-plugin distribution
#
# The hook blocks binary-document reads/hand-parsing DURING A LIVE ENGAGEMENT ONLY and
# redirects to the vendored converter (scripts/convert_file.py). Dormant sessions are
# untouched. It is a quality redirect, not a safety guard, and fails open.
#
# HUMAN-RUN by design (hook/config edits are human-only, ADR-002 rec 5). Idempotent.
#   Usage:  bash scripts/apply-document-redirect.sh
#   Undo:   remove the entry from both files (or `git checkout` them)
# Afterwards: commit both hook files; restart the session (or /hooks) to reload.
set -euo pipefail

here="$(cd "$(dirname "$0")/.." && pwd)"

# The hook script runs from scripts/ (like the DoD stop gate), via the portable launcher.
cp "$here/scripts/staged_hooks/document_input_redirect.py" "$here/scripts/document_input_redirect.py"
echo "document_input_redirect: staged copy installed to scripts/."

python3 - "$here/.claude/settings.json" "$here/hooks/hooks.json" <<'PY'
import json, sys

cmd = (
    'sh "${CLAUDE_PLUGIN_ROOT:-${CLAUDE_PROJECT_DIR:-.}}/.claude/hooks/run-guard.sh" '
    '"${CLAUDE_PLUGIN_ROOT:-${CLAUDE_PROJECT_DIR:-.}}/scripts/document_input_redirect.py"'
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
    pre.append({"matcher": "Read|Bash", "hooks": [{"type": "command", "command": cmd}]})
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=2)
        fh.write("\n")
    print(f"wired document-input redirect into: {path}")
PY

echo "Done. Confirm: python3 -m pytest tests/test_document_redirect.py -q; then commit both hook files + scripts/document_input_redirect.py and restart the session (or /hooks)."
