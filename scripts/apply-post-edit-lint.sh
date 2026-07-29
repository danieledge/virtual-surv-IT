#!/usr/bin/env bash
# Wire the post-edit lint feedback (scripts/staged_hooks/post_edit_lint.py) into BOTH
# tracked hook files as a PostToolUse hook on Write|Edit|MultiEdit:
#   .claude/settings.json  -> repo-as-project mode
#   hooks/hooks.json        -> installed-plugin distribution
#
# Advisory feedback one edit after a defect is written (py_compile always; ruff when on
# PATH), during live engagements only; dormant sessions untouched; fails open.
#
# HUMAN-RUN by design (hook/config edits are human-only, ADR-002 rec 5). Idempotent.
#   Usage:  bash scripts/apply-post-edit-lint.sh
#   Undo:   remove the PostToolUse entry from both files (or `git checkout` them)
# Afterwards: commit both hook files + scripts/post_edit_lint.py; restart the session.
set -euo pipefail

here="$(cd "$(dirname "$0")/.." && pwd)"

cp "$here/scripts/staged_hooks/post_edit_lint.py" "$here/scripts/post_edit_lint.py"
echo "post_edit_lint: staged copy installed to scripts/."

python3 - "$here/.claude/settings.json" "$here/hooks/hooks.json" <<'PY'
import json, sys

cmd = (
    'sh "${CLAUDE_PLUGIN_ROOT:-${CLAUDE_PROJECT_DIR:-.}}/.claude/hooks/run-guard.sh" '
    '"${CLAUDE_PLUGIN_ROOT:-${CLAUDE_PROJECT_DIR:-.}}/scripts/post_edit_lint.py"'
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
    post.append(
        {"matcher": "Write|Edit|MultiEdit", "hooks": [{"type": "command", "command": cmd}]}
    )
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=2)
        fh.write("\n")
    print(f"wired post-edit lint into: {path}")
PY

echo "Done. Confirm: python3 -m pytest tests/test_post_edit_lint.py -q; then commit both hook files + scripts/post_edit_lint.py and restart the session."
