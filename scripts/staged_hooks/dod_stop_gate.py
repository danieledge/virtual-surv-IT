#!/usr/bin/env python3
"""Stop-hook DoD backstop - warn-first, one nudge, never a hard trap.

Implements `docs/internal/research-virtual-team.md` refinement #4 ("verification as hooks, not prompts"):
when a turn ends while an engagement is **still open** (its state is open/closing, or the flat
pack is open/blocked/closing), run the mechanical DoD check (`scripts.check_artifacts`) and
surface any findings **once**, so a close that never ran - or a half-closed pack - self-corrects
instead of silently shipping. This is the mechanical backstop for the recurring "the close never
fired, so no DoD gate ever ran" failure class the operating guide keeps patching in prose
(2026-07-22 lesson).

2026-07-29 gate-hardening (workflow-robustness register, phase 1):
  * G3 [reproduced] - the checker import falls back to a __file__-relative load, so the hook
    is no longer a silent no-op in plugin mode (a foreign project has no `scripts` package on
    any path; the bare fail-open swallowed the ImportError). Same fallback pattern
    `check_artifacts._load_engagement_state_module` already carries.
  * G5/G7 - pack state and workspace detection delegate to the checker's shared
    `pack_status` / `engagement_packs`: ONE parser (a words-only status arms this gate too;
    a stray ⏳ in a closed index no longer re-arms it) and ONE workspace rule (a hand-made
    index-only pack is gated, not just anchored).
  * G8 - the derived registry (REGISTRY-STALE) and the root orphan scan (ORPHAN-ARTIFACT,
    read-only - the hook never writes the snapshot) run at turn end while any pack is gated.
  * R5 - the nudge tells an interrupted close to FINISH (`set-status closing` -> complete the
    artifacts -> `--fix` -> `set-status closed`), NEVER to delete close deliverables.

Deliberately low-noise and non-blocking:
  * fires **only** while a pack is genuinely gated (workspaces: open/closing - a ⛔ BLOCKED
    workspace is truthfully parked and stays silent; the flat pack keeps its pre-0.31
    semantics: open/blocked/closing arm it). A dormant session, or a folder with no readable
    engagement state, stays silent;
  * nudges **once** per stop cycle - guarded by the Stop hook's `stop_hook_active` flag, so it
    can never loop the model forever (warn-first, not hard-block);
  * **fails open** on any internal error - a verification backstop must never brick a stop.

2026-08-03 cross-turn suppression (token-usage audit): the loop-safety above only ever
covered ONE stop cycle. An engagement left open with an unaddressed, unchanging finding (a
mid-delivery unrendered .html sibling, a stale map anchor, a user who chose not to fix
something) re-fired this SAME nudge at every single stop, in every later session in that
project, until the pack closed or archived - a per-turn tax that compounds with turn count
and was never noticed because each individual nudge looked correct in isolation. Fixed the
same way `todo_panel_nudge.py` already solves the analogous one-time-nudge problem: the
findings are hashed, and the hash is compared against a `dod-nudged:<hash>` marker in the
gating pack's own `log` (recorded by the model via `log-note`, since every hook in this repo
stays read-only). Unchanged findings nudge once, then go silent; a NEW or DIFFERENT finding
set changes the hash and nudges again - the backstop still catches drift, it just stops
repeating itself.

Stdin: the Stop-hook JSON payload. Stdout: a single JSON `{"decision":"block","reason":...}` for
the one nudge (which feeds the findings back to the PM to act on), else nothing. Exit code is
always 0.

Wired in `.claude/settings.json` + `hooks/hooks.json` -> `hooks.Stop` (it ships wired; hook and
config edits are human-only under ADR-002 rec 5). Patches to this file are staged at
`scripts/staged_hooks/dod_stop_gate.py` and installed by the human via
`bash scripts/apply-project-anchor.sh`.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

_NUDGE_MARKER_PREFIX = "dod-nudged:"


def _load_input() -> dict:
    try:
        return json.load(sys.stdin)
    except Exception:
        return {}


def _findings_hash(findings: list[str]) -> str:
    """Stable, order-independent fingerprint of the current finding set - so re-sorting or
    re-ordering the checker's own output never spuriously looks like "something changed"."""
    joined = "\n".join(sorted(findings))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]


def _already_nudged(pack: Path, findings_hash: str) -> bool:
    """True if this EXACT finding set was already nudged for this pack - read-only, mirrors
    todo_panel_nudge.py's marker check. An unreadable or marker-less state file is "not yet
    nudged", never a suppression (fail toward warning, not toward silence)."""
    try:
        state = json.loads((pack / "engagement-state.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    log = state.get("log")
    if not isinstance(log, list):
        return False
    marker = f"{_NUDGE_MARKER_PREFIX}{findings_hash}"
    return any(marker in str(entry) for entry in log)


def _reason(findings: list[str], slug: str | None, findings_hash: str) -> str:
    bullet = "\n- ".join(findings)
    log_note = (
        f'engagement_state --slug {slug} log-note "{_NUDGE_MARKER_PREFIX}{findings_hash}"'
        if slug
        else f'engagement_state log-note "{_NUDGE_MARKER_PREFIX}{findings_hash}"'
    )
    return (
        "🎩 DoD backstop (Stop hook, warn-first): an engagement in this project is still "
        "OPEN and the mechanical DoD check flags:\n- "
        f"{bullet}\n\n"
        "The gate is a FIX-LIST (docs/DEFINITION-OF-DONE.md): AUTO-FIX the deterministic ones "
        "(render a missing .html sibling, create/refresh the START-HERE index, regenerate a "
        "stale registry) and re-close; ESCALATE only what needs a human. A final-/"
        "delivery-report/summary-email flagged before close means a close is UNDERWAY or was "
        "interrupted - resume and FINISH it (`set-status closing`, complete the close "
        "artifacts, `check_artifacts --fix`, `set-status closed`); NEVER delete completed "
        "close deliverables to satisfy the gate. If the engagement is genuinely still "
        'blocked, end the turn saying so plainly ("NOT closed - outstanding: ...") rather '
        "than stopping silently. (One-time nudge - it will not fire again this stop cycle, "
        f"and once you record `{log_note}` it will not repeat for this SAME finding set in "
        "any later turn or session either - only a new or changed finding re-arms it.)"
    )


_CHECK_ARTIFACTS_MODULE_CACHE = None


def _load_checker(project_root: Path):
    """The mechanical checker, importable in BOTH run modes (G3 fix).

    Package import first (repo mode - what the in-process tests exercise), then a
    __file__-relative load: a plugin install runs this hook by absolute path from the
    plugin dir against a foreign project, where no `scripts` package resolves - that was
    the silent no-op. The second candidate covers the staged copy's own location
    (scripts/staged_hooks/ -> scripts/). None = unavailable (fail open).

    2026-08-03 perf audit: memoized. Since stop_hook_dispatcher.py now runs this hook and
    todo_panel_nudge.py (which carries the identical loader) in ONE process, each still
    loading check_artifacts.py as its OWN separate module object - this cache at least
    stops THIS hook's own repeated calls from re-parsing+re-executing it."""
    global _CHECK_ARTIFACTS_MODULE_CACHE
    try:
        sys.path.insert(0, str(project_root))
        from scripts import check_artifacts

        return check_artifacts
    # Probe only; fall through to the file-relative loader.
    except Exception:  # nosec B110
        pass
    if _CHECK_ARTIFACTS_MODULE_CACHE is not None:
        return _CHECK_ARTIFACTS_MODULE_CACHE
    import importlib.util

    here = Path(__file__).resolve()
    for candidate in (
        here.with_name("check_artifacts.py"),
        here.parent.parent / "check_artifacts.py",
    ):
        try:
            if candidate.is_file():
                spec = importlib.util.spec_from_file_location("check_artifacts", candidate)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                _CHECK_ARTIFACTS_MODULE_CACHE = module
                return module
        # A candidate that won't load must not stop the next one being tried.
        except Exception:  # nosec B112
            continue
    return None


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
    if not artifacts.is_dir():
        return 0

    ca = _load_checker(cwd)
    if ca is None:
        return 0  # fail open - never brick a stop over a missing checker

    try:
        # Which packs does this turn-end gate? Shared detection + shared parser (G5/G7):
        # workspaces gate on open/closing (a ⛔ parked workspace must not nag a session
        # working a sibling engagement); the flat pack keeps its pre-0.31 semantics
        # (open/blocked/closing arm it) so solo engagements behave exactly as before.
        packs = ca.engagement_packs(artifacts)
        gated: list[tuple[str, Path]] = [
            (ws.name, ws) for ws in packs if ca.pack_status(ws) in ("open", "closing")
        ]
        flat_status = ca.pack_status(artifacts)
        if flat_status in ("open", "blocked", "closing"):
            gated.append(("", artifacts))
        if not gated:
            return 0

        findings = []
        for name, pack in gated:
            if not name and packs:
                # Flat pack alongside workspaces: deep rglob checks would cross into the
                # sibling workspaces - mirror check_artifacts and demand migration instead.
                findings.append(
                    "FLAT-PACK-UNMIGRATED: legacy flat pack coexists with workspaces - "
                    "run `python -m scripts.engagement_state migrate`"
                )
                continue
            prefix = f"[{name}] " if name else ""
            findings.extend(f"{prefix}{f}" for f in ca.check(pack))
        if packs:
            # G8: surface registry drift at turn end too; the orphan scan is read-only
            # here (the CLI checker owns the grandfather snapshot).
            findings.extend(ca.check_registry(artifacts))
            findings.extend(ca.check_root_orphans(artifacts))
        map_path = ca.find_codebase_map(cwd)
        if map_path is not None and map_path.is_file():
            findings.extend(ca.check_map(map_path))
    except Exception:
        return 0  # fail open - never brick a stop over a checker error

    if not findings:
        return 0

    findings_hash = _findings_hash(findings)
    # Marker home: prefer the flat pack when it's among the gated set (it's what most
    # single-engagement projects have), else the first gated workspace. Which specific pack
    # holds the marker is not semantically load-bearing - it is just a durable place to
    # record "this exact finding set was already nudged", shared across every gated pack.
    marker_name, marker_pack = next((g for g in gated if not g[0]), gated[0])
    if _already_nudged(marker_pack, findings_hash):
        return 0

    slug = marker_name or None
    print(json.dumps({"decision": "block", "reason": _reason(findings, slug, findings_hash)}))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
