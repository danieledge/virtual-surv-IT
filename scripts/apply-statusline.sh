#!/usr/bin/env bash
# Wire the team statusline (scripts/statusline.sh) into .claude/settings.json.
#
# The statusline shows dormant-vs-engaged (ACTIVE slug, status, phase) plus model and
# session cost at ZERO context cost - it is a shell render, never a model turn. Repo-scoped
# only: statusLine is a project/user setting, so this wires .claude/settings.json (not the
# plugin's hooks.json - plugin users wire their own if they want it; see README).
#
# HUMAN-RUN by design (settings edits are human-only, ADR-002 rec 5). Idempotent.
#   Usage:  bash scripts/apply-statusline.sh
#   Undo:   remove the "statusLine" key from .claude/settings.json
# Afterwards: restart the session to see it.
set -euo pipefail

here="$(cd "$(dirname "$0")/.." && pwd)"
settings="$here/.claude/settings.json"
[ -f "$settings" ] || { echo "ERROR: $settings not found" >&2; exit 1; }

python3 - "$settings" <<'PY'
import json, sys

path = sys.argv[1]
cmd = 'bash "${CLAUDE_PROJECT_DIR:-.}/scripts/statusline.sh"'
with open(path, encoding="utf-8") as fh:
    cfg = json.load(fh)
if cfg.get("statusLine", {}).get("command") == cmd:
    print(f"already wired: {path}")
else:
    cfg["statusLine"] = {"type": "command", "command": cmd}
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=2)
        fh.write("\n")
    print(f"wired statusLine into: {path}")
PY

echo "Done. Restart the session to see the statusline."
