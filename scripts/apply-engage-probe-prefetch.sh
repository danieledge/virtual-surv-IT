#!/usr/bin/env bash
# Wire the /engage step-0 probe prefetch (scripts/staged_hooks/engage_probe_prefetch.py)
# into BOTH tracked hook files as a UserPromptSubmit hook, alongside the existing
# persona_anchor.py entry:
#   .claude/settings.json  -> repo-as-project mode
#   hooks/hooks.json        -> installed-plugin distribution
#
# Pre-runs the /engage /engage-light /map-codebase step-0 probe from a hook (fires before
# the model's turn, plain stdout added to context - same mechanism persona_anchor.py and
# session_resume_brief.py already use) so the steady-state open skips the Bash heredoc
# round-trip entirely. Dormancy-exact: near-zero cost on every other prompt, and declines
# silently (no injected block) on a cold interpreter cache or any internal error - the
# live Bash-heredoc probe in engage-open.md stays the fallback, unchanged.
#
# HUMAN-RUN by design (hook/config edits are human-only, ADR-002 rec 5). Idempotent.
#   Usage:  bash scripts/apply-engage-probe-prefetch.sh
#   Undo:   remove the engage_probe_prefetch entry from both files (or `git checkout` them)
# Afterwards: commit both hook files + scripts/engage_probe_prefetch.py; restart the session.
set -euo pipefail

here="$(cd "$(dirname "$0")/.." && pwd)"

cp "$here/scripts/staged_hooks/engage_probe_prefetch.py" "$here/scripts/engage_probe_prefetch.py"
echo "engage_probe_prefetch: staged copy installed to scripts/."

python3 - "$here/.claude/settings.json" "$here/hooks/hooks.json" <<'PY'
import json, sys

cmd = (
    'sh "${CLAUDE_PLUGIN_ROOT:-${CLAUDE_PROJECT_DIR:-.}}/.claude/hooks/run-guard.sh" '
    '"${CLAUDE_PLUGIN_ROOT:-${CLAUDE_PROJECT_DIR:-.}}/scripts/engage_probe_prefetch.py"'
)

for path in sys.argv[1:]:
    try:
        with open(path, encoding="utf-8") as fh:
            cfg = json.load(fh)
    except FileNotFoundError:
        print(f"skip (not found): {path}")
        continue
    entries = cfg.setdefault("hooks", {}).setdefault("UserPromptSubmit", [])
    if any(h.get("command") == cmd for e in entries for h in e.get("hooks", [])):
        print(f"already wired: {path}")
        continue
    entries.append({"hooks": [{"type": "command", "command": cmd}]})
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=2)
        fh.write("\n")
    print(f"wired engage probe prefetch into: {path}")
PY

echo "Done. Confirm: python3 -m pytest tests/test_engage_probe_prefetch.py -q; then commit both hook files + scripts/engage_probe_prefetch.py and restart the session."
