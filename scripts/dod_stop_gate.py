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
import os
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

    # Anchor to the session's PROJECT root, not the hook-input cwd: a shell that has
    # wandered into a foreign directory (observed 2026-07-25: a kept eval sandbox under
    # evals/runs/ with its own open START-HERE) must not make this gate adopt that
    # directory's engagement. Inside a real sandboxed eval session the two are equal,
    # so the gate stays fully armed there - which is exactly what the evals need.
    cwd = Path(os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or Path.cwd())
    artifacts = cwd / "artifacts"

    # Which packs does this turn-end gate? (0.31 workspaces: artifacts/<slug>/ each with
    # independent state, plus the legacy flat pack.) The state file (ADR-006) is
    # authoritative when parseable; the emoji sniff of START-HERE.md is the legacy
    # fallback. Workspace rule: gate ONLY ⏳ in_progress workspaces - a ⛔ BLOCKED
    # workspace is already truthfully parked and must not nag a session working a sibling
    # engagement. The flat pack keeps its pre-0.31 semantics (⏳ or ⛔ arms) so solo
    # engagements behave exactly as before. Nothing gated -> stay silent.
    def pack_status(pack: Path) -> str | None:
        state_file = pack / "engagement-state.json"
        if state_file.is_file():
            try:
                status = json.loads(state_file.read_text(encoding="utf-8")).get("status")
            except Exception:
                status = None
            if status in ("in_progress", "blocked", "closed"):
                return status
        try:
            text = (pack / "START-HERE.md").read_text(encoding="utf-8", errors="replace")
        except Exception:
            return None
        return "open" if ("⏳" in text or "⛔" in text) else None

    gated: list[tuple[str, Path]] = []
    try:
        workspaces = sorted(
            p for p in artifacts.iterdir()
            if p.is_dir() and (
                (p / "engagement-state.json").is_file() or (p / "START-HERE.md").is_file()
            )
        )
    except OSError:
        workspaces = []
    for ws in workspaces:
        if pack_status(ws) in ("in_progress", "open"):
            gated.append((ws.name, ws))
    flat_status = pack_status(artifacts)
    if flat_status in ("in_progress", "blocked", "open"):
        gated.append(("", artifacts))
    if not gated:
        return 0

    # Reuse the exact mechanical checker by import (no subprocess, so no execution-consent gate).
    try:
        sys.path.insert(0, str(cwd))
        from scripts.check_artifacts import check, check_map, find_codebase_map

        findings = []
        for name, pack in gated:
            if not name and workspaces:
                # Flat pack alongside workspaces: deep rglob checks would cross into the
                # sibling workspaces - mirror check_artifacts and demand migration instead.
                findings.append(
                    "FLAT-PACK-UNMIGRATED: legacy flat pack coexists with workspaces - "
                    "run `python -m scripts.engagement_state migrate`"
                )
                continue
            prefix = f"[{name}] " if name else ""
            findings.extend(f"{prefix}{f}" for f in check(pack))
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
