#!/usr/bin/env bash
# Remove semgrep/pip-audit from .claude/settings.json's permissions.allow (2026-08-05 report).
#
# Both tools were deliberately removed from the actual tool-probing logic on 2026-08-04
# (unconditional network calls, no reliable offline mode, hung on corp-proxy environments -
# see code-reviewer.md, requirements-review.txt, scripts/check-review-tools.sh for the full
# rationale). install_helper.py's RECOMMENDED_ALLOW (what --permissions actually writes to
# new/existing projects) was already updated to exclude both. This repo's own checked-in
# .claude/settings.json predates that removal and still allow-lists Bash(semgrep:*) and
# Bash(pip-audit:*) - directly contradicting the "deliberately excluded, never invoked" policy
# documented everywhere else. A user asking Morgan about semgrep got a correct "not used here"
# answer that this stale permission entry contradicts.
#
# HUMAN-RUN by design (settings.json edits are human-only, ADR-002 rec 5). Idempotent.
#   Usage:  bash scripts/apply-remove-stale-tool-allowlist.sh
#   Undo:   git checkout .claude/settings.json
set -euo pipefail

here="$(cd "$(dirname "$0")/.." && pwd)"
target="$here/.claude/settings.json"

[ -f "$target" ] || { echo "skip (not found): $target"; exit 0; }

python3 - "$target" <<'PY'
import json, sys

STALE = {"Bash(semgrep:*)", "Bash(pip-audit:*)"}
path = sys.argv[1]

with open(path, encoding="utf-8") as fh:
    cfg = json.load(fh)

allow = cfg.get("permissions", {}).get("allow", [])
removed = [e for e in allow if e in STALE]
if not removed:
    print(f"already clean: {path} (no stale entries present)")
    sys.exit(0)

cfg["permissions"]["allow"] = [e for e in allow if e not in STALE]
with open(path, "w", encoding="utf-8") as fh:
    json.dump(cfg, fh, indent=2)
    fh.write("\n")
print(f"removed {len(removed)} stale entr{'y' if len(removed) == 1 else 'ies'}: {', '.join(sorted(removed))}")
PY

echo "Done. Confirm: python3 -m pytest tests/ -q"
echo "Then commit .claude/settings.json."
