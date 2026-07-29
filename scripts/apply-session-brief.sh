#!/usr/bin/env bash
# Wire the compaction/resume brief (scripts/staged_hooks/session_resume_brief.py) into BOTH
# tracked hook files as a SessionStart hook (matcher: compact|resume):
#   .claude/settings.json  -> repo-as-project mode
#   hooks/hooks.json        -> installed-plugin distribution
#
# The hook re-briefs a session that was compacted or resumed MID-ENGAGEMENT: which pack is
# ACTIVE, and the instruction to re-read the on-disk state (decisions, consent outcome,
# runtime) instead of re-asking. Dormancy-exact: zero output in any session where no
# engagement pack is live (ADR-011).
#
# HUMAN-RUN by design (hook/config edits are human-only, ADR-002 rec 5). Idempotent.
#   Usage:  bash scripts/apply-session-brief.sh
#   Undo:   remove the SessionStart entry from both files (or `git checkout` them)
# Afterwards: commit both hook files + scripts/session_resume_brief.py; restart the session.
set -euo pipefail

here="$(cd "$(dirname "$0")/.." && pwd)"

cp "$here/scripts/staged_hooks/session_resume_brief.py" "$here/scripts/session_resume_brief.py"
echo "session_resume_brief: staged copy installed to scripts/."

python3 - "$here/.claude/settings.json" "$here/hooks/hooks.json" <<'PY'
import json, sys

cmd = (
    'sh "${CLAUDE_PLUGIN_ROOT:-${CLAUDE_PROJECT_DIR:-.}}/.claude/hooks/run-guard.sh" '
    '"${CLAUDE_PLUGIN_ROOT:-${CLAUDE_PROJECT_DIR:-.}}/scripts/session_resume_brief.py"'
)

for path in sys.argv[1:]:
    try:
        with open(path, encoding="utf-8") as fh:
            cfg = json.load(fh)
    except FileNotFoundError:
        print(f"skip (not found): {path}")
        continue
    entries = cfg.setdefault("hooks", {}).setdefault("SessionStart", [])
    if any(h.get("command") == cmd for e in entries for h in e.get("hooks", [])):
        print(f"already wired: {path}")
        continue
    entries.append({"matcher": "compact|resume", "hooks": [{"type": "command", "command": cmd}]})
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=2)
        fh.write("\n")
    print(f"wired session resume-brief into: {path}")
PY

echo "Done. Confirm: python3 -m pytest tests/test_session_brief.py -q; then commit both hook files + scripts/session_resume_brief.py and restart the session."
