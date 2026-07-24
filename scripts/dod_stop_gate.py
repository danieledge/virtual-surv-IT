#!/usr/bin/env python3
"""Stop-hook DoD backstop - warn-first, one nudge, never a hard trap.

Implements `docs/research-virtual-team.md` refinement #4 ("verification as hooks, not prompts"):
when a turn ends while an engagement is **still open** (its `START-HERE` status is ⏳ in-progress or
⛔ blocked), run the mechanical DoD check (`scripts.check_artifacts`) and surface any findings
**once**, so a close that never ran - or a half-closed pack - self-corrects instead of silently
shipping. This is the mechanical backstop for the recurring "the close never fired, so no DoD gate
ever ran" failure class the operating guide keeps patching in prose (2026-07-22 lesson).

Deliberately low-noise and non-blocking:
  * fires **only** when `artifacts/START-HERE.md` exists AND is ⏳/⛔ (an engagement genuinely in
    flight). A dormant session, or a legacy `artifacts/` folder with no living index, stays silent -
    so it never nags on the repo's own historical artifacts;
  * nudges **once** per stop cycle - guarded by the Stop hook's `stop_hook_active` flag, so it can
    never loop the model forever (warn-first, not hard-block; escalating to always-block is a
    later, deliberate step);
  * **fails open** on any internal error - a verification backstop must never brick a stop.

Stdin: the Stop-hook JSON payload. Stdout: a single JSON `{"decision":"block","reason":...}` for the
one nudge (which feeds the findings back to the PM to act on), else nothing. Exit code is always 0.

Wire via `.claude/settings.json` -> `hooks.Stop` (human-applied - see
`scripts/apply-dod-stop-hook.sh`; hook/config edits are human-only under ADR-002 rec 5).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def _load_input() -> dict:
    try:
        return json.load(sys.stdin)
    except Exception:
        return {}


def _reason(findings: list[str]) -> str:
    bullet = "\n- ".join(findings)
    return (
        "🎩 DoD backstop (Stop hook, warn-first): this engagement's START-HERE is still OPEN "
        "(⏳/⛔) and the mechanical DoD check flags:\n- "
        f"{bullet}\n\n"
        "The gate is a FIX-LIST (docs/DEFINITION-OF-DONE.md): AUTO-FIX the deterministic ones "
        "(render a missing .html sibling, create/refresh the START-HERE index, remove a premature "
        "final-/delivery-report/summary-email asserted before close) and re-close; ESCALATE only "
        "what needs a human. If the engagement is genuinely still blocked, end the turn saying so "
        'plainly ("NOT closed - outstanding: ...") rather than stopping silently. '
        "(One-time nudge - it will not fire again this stop cycle.)"
    )


def main() -> int:
    data = _load_input()

    # Loop-safety: if we already nudged and the model is continuing because of it, do not nudge
    # again - this is what makes the hook warn-first rather than a hard block.
    if data.get("stop_hook_active"):
        return 0

    cwd = Path(data.get("cwd") or Path.cwd())
    artifacts = cwd / "artifacts"
    start_here = artifacts / "START-HERE.md"
    if not start_here.is_file():
        return 0  # no living index -> not an engagement we own (dormant / legacy): stay silent

    try:
        status_text = start_here.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return 0
    # Only fire while the engagement is OPEN. A ✅ closed index is done; don't nag.
    if "⏳" not in status_text and "⛔" not in status_text:
        return 0

    # Reuse the exact mechanical checker by import (no subprocess, so no execution-consent gate).
    try:
        sys.path.insert(0, str(cwd))
        from scripts.check_artifacts import check, check_map, find_codebase_map

        findings = list(check(artifacts))
        map_path = find_codebase_map(cwd)
        if map_path is not None and map_path.is_file():
            findings.extend(check_map(map_path))
    except Exception:
        return 0  # fail open - never brick a stop over a checker error

    if not findings:
        return 0

    print(json.dumps({"decision": "block", "reason": _reason(findings)}))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
