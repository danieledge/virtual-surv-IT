#!/usr/bin/env python3
"""Stop-hook nudge: "this looks ready to close" - warn-first, one-time, self-suppressing.

WHY THIS EXISTS (2026-09-22, user report). `dod_stop_gate.py` already runs the mechanical
DoD check at every turn-end while an engagement is open - but it only ever SPEAKS when it
finds a defect. A long-running engagement (a multi-day `/build-solution`, many interim
artifacts) that is fully clean by every check that applies to an OPEN engagement produces
total silence, turn after turn, forever - nothing ever nudges toward actually STARTING the
close sequence. That is the real gap: not "DoD doesn't fire until done" (most of it already
fires continuously), but "nothing ever suggests the engagement IS done."

Deliberately narrow and low-noise, same posture as `todo_panel_nudge.py` (its closest
sibling - a separate small file rather than bolted onto `dod_stop_gate.py`, which is already
dense and heavily scarred by past incidents; keeping this concern isolated matches that
precedent):
  * fires only while a pack is gated to OPEN specifically (not "closing" - a close already
    under way needs no nudge to start one; not "blocked" - a paused engagement is truthfully
    parked, nudging "looks done" there would be confusing, not helpful);
  * fires only once `phase` has reached "delivery" or "close" (same `_GATED_PHASES` concept
    `todo_panel_nudge.py` already uses) AND the pack's own `outstanding` list is empty AND a
    fresh `check_artifacts` run on it reports NO findings - three independent signals, all
    required, so an engagement that is merely quiet (not yet at delivery phase, or still has
    open questions, or has an unrelated defect) is never nudged;
    it stays silent on active work;
  * fires ONCE EVER per engagement (like `todo_panel_nudge.py`, not `dod_stop_gate.py`'s
    hash-based re-arming - there is no adversarial pressure here, unlike a defect someone
    might be tempted to paper over, so the simpler one-shot marker is enough) - a
    `readiness-nudged` marker in the pack's own log, recorded by the model via `log-note`
    same as the model records every other marker this hook family uses (every hook here
    stays read-only);
  * session-scoped (the acting-session stamp, same as `dod_stop_gate.py` and
    `todo_panel_nudge.py`) so a pack left open by ANOTHER session never nudges a session that
    never drove it;
  * fails open on any internal error - a soft UX nicety must never brick a stop.

Stdin: the Stop-hook JSON payload. Stdout: a single JSON `{"decision":"block","reason":...}`
for the one nudge, else nothing. Exit code is always 0.

Wired in `hooks/hooks.json` -> `hooks.Stop`, alongside `dod_stop_gate.py` and
`todo_panel_nudge.py` (hook/config edits are human-only, ADR-002 rec 5).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def _vsit_paths():
    """Same lazy loader as every sibling hook here (this file may run standalone from a
    bare clone where scripts/ is not yet on sys.path, and also exists as a staged copy
    under scripts/staged_hooks/)."""
    import sys as _sys

    _here = Path(__file__).resolve().parent
    for _candidate in (_here, _here.parent, _here.parent / "scripts"):
        if (_candidate / "vsit_paths.py").is_file():
            if str(_candidate) not in _sys.path:
                _sys.path.insert(0, str(_candidate))
            break
    import vsit_paths

    return vsit_paths


_GATED_PHASES = ("delivery", "close")
_READY_MARKER = "readiness-nudged"


def _load_input() -> dict:
    try:
        return json.load(sys.stdin)
    except Exception:
        return {}


def _reason(slug: str | None) -> str:
    name = f"'{slug}'" if slug else "this engagement (flat pack)"
    log_note = (
        f'engagement_state --slug {slug} log-note "{_READY_MARKER}"'
        if slug
        else f'engagement_state log-note "{_READY_MARKER}"'
    )
    return (
        f"🎩 Readiness nudge (Stop hook, one-time, informational only) for {name}: it has "
        "reached the delivery/close phase, the outstanding list is empty, and a fresh "
        "check_artifacts run reports no findings. This may be ready to close - or there may "
        "be real reasons it is not (more work planned, waiting on something not tracked as "
        "'outstanding'). This is an observation, not a directive: if it really is done, "
        "the close sequence is `set-status closing` -> finalise-artifacts -> the summary "
        "email -> `check_artifacts --fix` -> `set-status closed` "
        "(`.claude/skills/.shared/engagement-bookends.md`). If it is not, say so in one line "
        "and continue exactly as planned - this nudge does not need a decision right now, "
        f"just an acknowledgement. Either way, record `{log_note}` so it does not repeat for "
        "this engagement."
    )


_CHECK_ARTIFACTS_MODULE_CACHE = None


def _load_checker(project_root: Path):
    """Mirrors dod_stop_gate.py's / todo_panel_nudge.py's loader exactly (package import
    first, then a __file__-relative fallback for plugin mode against a foreign project).
    Memoized the same way, for the same reason (2026-08-03 perf audit)."""
    global _CHECK_ARTIFACTS_MODULE_CACHE
    try:
        if str(project_root) not in sys.path:
            sys.path.insert(0, str(project_root))
        from scripts import check_artifacts

        return check_artifacts
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
        except Exception:  # nosec B112
            continue
    return None


def _looks_ready(pack: Path, ca) -> bool:
    """All three required, independently: delivery/close phase, nothing outstanding, and a
    fresh check_artifacts pass with no findings. Fail-safe: any unreadable/missing state, or
    an exception from the checker, means NOT ready (never nudges on uncertain state)."""
    state_file = pack / "engagement-state.json"
    try:
        state = json.loads(state_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if state.get("phase") not in _GATED_PHASES:
        return False
    if state.get("outstanding"):
        return False
    log = state.get("log")
    if isinstance(log, list) and any(_READY_MARKER in str(entry) for entry in log):
        return False
    try:
        if ca.check(pack):
            return False
    except Exception:
        return False
    return True


def main() -> int:
    data = _load_input()
    if data.get("stop_hook_active"):
        return 0

    cwd = Path(os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or Path.cwd())
    artifacts = _vsit_paths().engagements_dir(cwd)
    if not artifacts.is_dir():
        return 0

    # Session scoping (same fix as dod_stop_gate.py / todo_panel_nudge.py, same live
    # report class): a pack left open by ANOTHER session must not nudge a session that
    # never drove it. Matches against every session the stamp remembers, current AND
    # legacy formats alike, same as dod_stop_gate.py's own read.
    session_id = data.get("session_id")
    try:
        stamp = json.loads((artifacts / ".team-session.json").read_text(encoding="utf-8"))
        stamped = [
            s for s in (stamp.get("session_id"), stamp.get("session")) if isinstance(s, str) and s
        ]
        stamped += [
            e.get("id")
            for e in (stamp.get("sessions") or [])
            if isinstance(e, dict) and isinstance(e.get("id"), str) and e.get("id")
        ]
    except Exception:
        stamped = []
    if not session_id or session_id not in stamped:
        return 0

    ca = _load_checker(cwd)
    if ca is None:
        return 0

    try:
        packs = ca.engagement_packs(artifacts)
        # OPEN only - not "closing" (already starting one) and not "blocked" (truthfully
        # parked; a "looks done" nudge there would be confusing, not helpful).
        gated = [ws for ws in packs if ca.pack_status(ws) == "open"]
        if ca.pack_status(artifacts) == "open":
            gated.append(artifacts)
        if not gated:
            return 0
        pack = next((p for p in gated if _looks_ready(p, ca)), None)
        if pack is None:
            return 0
    except Exception:
        return 0

    slug = None if pack == artifacts else pack.name
    print(json.dumps({"decision": "block", "reason": _reason(slug)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
