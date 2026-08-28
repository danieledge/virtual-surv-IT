#!/usr/bin/env python3
"""Stop-hook nudge: seed the native task-list gate panel - warn-first, self-suppressing.

The operating guide claims delivery-phase engagements track their gates in Claude Code's
native task list (TodoWrite): "the moment the plan is agreed, seed one todo per planned
gate... keep exactly one in_progress, ticking each as its evidence lands." A search of
every kept live eval transcript found ZERO genuine TodoWrite tool calls (2026-07-30) -
this was pure prose, never mechanically encouraged, and evidently not happening
reliably. TodoWrite itself cannot be called BY a hook (it is model-invoked, no external
driver) and its live content is not observable from outside the running turn (ephemeral,
never persisted) - so this cannot verify compliance the way dod_stop_gate.py verifies
DoD findings from disk. It can only nudge at the structurally right moment.

Self-suppressing WITHOUT the hook writing state (every hook in this repo stays
read-only - engagement-state.json is mutated only via engagement_state.py commands, by
the model): the nudge asks Morgan to record `log-note "todo-panel-seeded"` once the
panel is seeded, and this hook checks the pack's `log` for that exact marker before
nudging again. Fires only once per engagement (not once per turn, which would itself
become the console noise the task-list feature exists to avoid) - after the marker
appears, silent for the rest of the engagement, including through close.

Deliberately narrow, matching dod_stop_gate.py's low-noise design:
  * fires only while a pack is genuinely gated (open/closing; the flat pack's pre-0.31
    open/blocked/closing semantics) AND `phase` has reached "delivery" or "close" - the
    point the operating guide names ("the moment the plan is agreed");
  * nudges once per stop cycle (the Stop hook's `stop_hook_active` flag, same loop-safety
    as dod_stop_gate.py) and self-suppresses permanently once the marker is logged;
  * fails open on any internal error - a soft UX nicety must never brick a stop.

Stdin: the Stop-hook JSON payload. Stdout: a single JSON `{"decision":"block","reason":...}`
for the one nudge, else nothing. Exit code is always 0.

Wire via scripts/apply-todo-panel-nudge.sh (HUMAN-run - hook/config edits are human-only,
ADR-002 rec 5) into `.claude/settings.json` + `hooks/hooks.json` -> hooks.Stop.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def _vsit_paths():
    """The layout resolver (VSIT migration), imported lazily.

    Lazy because this file may run standalone from a bare clone where `scripts/` is not yet
    on sys.path - the same reason the other cross-script imports here are deferred.

    Searches its own directory AND a sibling `scripts/`, because this file also exists as a
    staged copy under `scripts/staged_hooks/`, which the human applies. A first version
    looked only beside __file__ and the staged copy died with ModuleNotFoundError - caught
    by the tests that run the staged copies directly, which is what they are for."""
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
_SEEDED_MARKER = "todo-panel-seeded"


def _load_input() -> dict:
    try:
        return json.load(sys.stdin)
    except Exception:
        return {}


def _reason(slug: str | None, phase: str) -> str:
    name = f"'{slug}'" if slug else "this engagement (flat pack)"
    log_note = (
        f'engagement_state --slug {slug} log-note "{_SEEDED_MARKER}"'
        if slug
        else f'engagement_state log-note "{_SEEDED_MARKER}"'
    )
    return (
        f"🎩 Task-panel nudge (Stop hook, warn-first, one-time) for {name}: its phase just "
        f"reached '{phase}' and the operating guide's 'native task-list progress' rule "
        "applies - seed one todo per planned gate (brief → build → tests → review → QA "
        "→ DoD gate → close) via TodoWrite if you have not already, keeping exactly one "
        "in_progress and ticking each as its evidence lands. Once the panel reflects the "
        f"current gates, record `{log_note}` so this reminder never fires again for this "
        "engagement. (One-time nudge - it will not repeat this stop cycle regardless.)"
    )


_CHECK_ARTIFACTS_MODULE_CACHE = None


def _load_checker(project_root: Path):
    """Mirrors dod_stop_gate.py's loader exactly (G3 fix: package import first, then a
    __file__-relative fallback for plugin mode against a foreign project). Memoized the
    same way, for the same reason (2026-08-03 perf audit)."""
    global _CHECK_ARTIFACTS_MODULE_CACHE
    try:
        # M3 (2026-08-14 daemon-safety audit): deduped, not an unconditional insert -
        # mirrors dod_stop_gate.py's own identical fix (and persona_anchor.py's
        # original one). Re-exec'd fresh per Stop event inside the daemon when
        # daemon-served, so an unconditional insert would grow the daemon's
        # process-global sys.path without bound over its life.
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


def _needs_nudge(pack: Path) -> str | None:
    """Reads the pack's own state file directly (phase + log aren't exposed by
    pack_status, which only returns the words-only status). Fail-safe: an unreadable or
    missing state file never nudges. Returns the triggering phase, or None."""
    state_file = pack / "engagement-state.json"
    try:
        state = json.loads(state_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    phase = state.get("phase")
    if phase not in _GATED_PHASES:
        return None
    log = state.get("log")
    if isinstance(log, list) and any(_SEEDED_MARKER in str(entry) for entry in log):
        return None
    return phase


def main() -> int:
    data = _load_input()
    if data.get("stop_hook_active"):
        return 0

    cwd = Path(os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or Path.cwd())
    artifacts = _vsit_paths().engagements_dir(cwd)
    if not artifacts.is_dir():
        return 0

    # Session scoping (2026-08-16 live report, same fix as the staged DoD stop gate
    # and persona anchor): a pack left open by ANOTHER session must not nudge a
    # session that never drove the team. Arm only when this payload's session_id
    # matches the acting-session stamp engagement_state writes to
    # artifacts/.team-session.json on every mutating command; missing either id, or a
    # mismatch, means a dormant session - stay silent.
    session_id = data.get("session_id")
    try:
        stamped = json.loads((artifacts / ".team-session.json").read_text(encoding="utf-8")).get(
            "session"
        )
    except Exception:
        stamped = None
    if not session_id or stamped != session_id:
        return 0

    ca = _load_checker(cwd)
    if ca is None:
        return 0

    try:
        packs = ca.engagement_packs(artifacts)
        gated = [ws for ws in packs if ca.pack_status(ws) in ("open", "closing")]
        flat_status = ca.pack_status(artifacts)
        if flat_status in ("open", "blocked", "closing"):
            gated.append(artifacts)
        if not gated:
            return 0
        triggered = next(((pack, phase) for pack in gated if (phase := _needs_nudge(pack))), None)
        if triggered is None:
            return 0
    except Exception:
        return 0

    pack, phase = triggered
    slug = None if pack == artifacts else pack.name
    print(json.dumps({"decision": "block", "reason": _reason(slug, phase)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
