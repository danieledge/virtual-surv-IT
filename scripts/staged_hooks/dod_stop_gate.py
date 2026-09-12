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

2026-09-12 audit (W-6): the suppression above was self-serve. `dod-nudged:<hash>` is a
deterministic SHA-256 of the findings text the nudge itself prints, so the model could record
it without doing any of the work it claims, and the backstop then stayed silent for that exact
finding set forever. Two changes, both structural rather than a firmer instruction:

  * The marker no longer decides anything on its own. The findings this gate reports come
    from a `check_artifacts` run that just happened, so a marker matching the CURRENT hash is
    a marker whose findings are still being reported - evidence the work was not done. The
    suppression is therefore honoured only by the finding set changing, which is the same
    thing as a fresh run reporting them resolved. A claimed-but-stale marker is called out in
    the block text rather than being quietly ignored.
  * That alone would nudge forever on something genuinely unfixable, so the gate counts its
    own blocks (`dod-gate-block:<hash>` notes it writes itself, never the model) and gives up
    after `_BLOCK_CEILING` of them PER ENGAGEMENT: it degrades to a plain stderr warning so the
    turn can end, and records `DOD-GATE-EXHAUSTED:<hash>` so a gate that went quiet is
    distinguishable from a gate that was satisfied. The warning still prints the findings at
    every stop after that, so nothing disappears - only the blocking stops.

Fail-open is unchanged: every new path is wrapped, an unreadable log counts as zero blocks
(fail toward blocking, matching `_already_nudged`'s direction), and a failed log-note costs the
record, never the block.

Stdin: the Stop-hook JSON payload. Stdout: a single JSON `{"decision":"block","reason":...}` for
the one nudge (which feeds the findings back to the PM to act on), else nothing. Exit code is
always 0.

Wired in `.claude/settings.json` + `hooks/hooks.json` -> `hooks.Stop` (it ships wired; hook and
config edits are human-only under ADR-002 rec 5). Patches to this file are staged at
`scripts/staged_hooks/dod_stop_gate.py` and installed by the human via
`bash scripts/apply-project-anchor.sh`.

2026-08-14 live report (corp Windows dogfooding session, screenshots): a session was nudged
about an unrelated OPEN engagement while its own most recent message had just asked for a new,
different review - exactly the case the "proceed with THAT first" branch below exists for. It
narrated "quick note - fixing the two ... state issues ... before we proceed" and then actually
fixed them, before starting the new work: diverting into the fix, just a fast one. The wording
at the time said "rather than diverting into fixing it now," which apparently reads as
compatible with "but this one's quick" - tightened below to name that exact rationalization and
rule it out explicitly, and to give a concrete one-line deferral so there's a specific correct
action to take instead of an abstract instruction to not do something.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path


def _vsit_paths():
    """The layout resolver (VSIT migration), imported lazily.

    Lazy because this file may run standalone from a bare clone where `scripts/` is not yet
    on sys.path. Searches its own directory AND a sibling `scripts/`, because several of
    these files also exist as staged copies under `scripts/staged_hooks/`."""
    import sys as _sys

    _here = Path(__file__).resolve().parent
    for _candidate in (_here, _here.parent, _here.parent / "scripts"):
        if (_candidate / "vsit_paths.py").is_file():
            if str(_candidate) not in _sys.path:
                _sys.path.insert(0, str(_candidate))
            break
    import vsit_paths

    return vsit_paths


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
    """True if this EXACT finding set carries a suppression marker for this pack.

    Read-only, mirrors todo_panel_nudge.py's marker check. An unreadable or marker-less
    state file is "not yet nudged", never a suppression (fail toward warning, not toward
    silence).

    W-6, 2026-09-12: this is no longer the suppression decision on its own. See
    `_suppression_is_stale` and main() - a marker whose findings are still being reported
    by a fresh `check_artifacts` run is evidence that nothing was fixed, not evidence that
    it was."""
    try:
        state = json.loads((pack / "engagement-state.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    log = state.get("log")
    if not isinstance(log, list):
        return False
    marker = f"{_NUDGE_MARKER_PREFIX}{findings_hash}"
    return any(marker in str(entry) for entry in log)


# W-6: how many times this gate may re-block ONE ENGAGEMENT before it gives up and degrades
# to a warning. Three is enough to be unmissable and few enough that a genuinely stuck session
# can still end its turn; the DOD-GATE-EXHAUSTED note is what keeps the give-up from being
# invisible - a gate going quiet has to leave a record, or it is indistinguishable from a gate
# that was satisfied.
#
# Per ENGAGEMENT, not per finding-hash, and that is deliberate. Recording a block is itself a
# state mutation, which re-renders the index and the registry - and that can legitimately
# change the finding set (a REGISTRY-HTML-STALE appearing between two stops was seen doing
# exactly this). A per-hash ceiling is therefore resettable by the gate's own bookkeeping,
# which is not a ceiling at all. After exhaustion the findings are still printed at every
# stop as a warning, so nothing goes unseen; only the blocking stops.
_BLOCK_CEILING = 3
_BLOCK_MARKER_PREFIX = "dod-gate-block:"
_EXHAUSTED_MARKER_PREFIX = "DOD-GATE-EXHAUSTED:"


def _log_entries(pack: Path) -> list:
    try:
        state = json.loads((pack / "engagement-state.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    log = state.get("log")
    return log if isinstance(log, list) else []


def _blocks_recorded(pack: Path) -> int:
    """How many times THIS gate has already blocked this engagement.

    Counted from hook-written markers, never from the model-written suppression note: the
    whole point of W-6 is that a count the blocked party maintains is not a count."""
    return sum(1 for entry in _log_entries(pack) if _BLOCK_MARKER_PREFIX in str(entry))


def _exhausted_recorded(pack: Path) -> bool:
    return any(_EXHAUSTED_MARKER_PREFIX in str(entry) for entry in _log_entries(pack))


def _engagement_state_module():
    """`engagement_state`, importable from a repo checkout AND from a plugin install.

    Same two-step every other hook here uses: the package import first, then a
    file-relative load that also covers this file's staged copy under
    scripts/staged_hooks/. None means "cannot record", which the caller treats as a reason
    to keep blocking rather than a reason to go quiet."""
    try:
        from scripts import engagement_state  # noqa: PLC0415

        return engagement_state
    except Exception:  # nosec B110 - probe only; the file-relative loader is next
        pass
    import importlib.util

    here = Path(__file__).resolve()
    for candidate in (
        here.with_name("engagement_state.py"),
        here.parent.parent / "engagement_state.py",
    ):
        try:
            if candidate.is_file():
                spec = importlib.util.spec_from_file_location("engagement_state", candidate)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                return module
        except Exception:  # nosec B112 - a candidate that won't load must not stop the next
            continue
    return None


def _log_note(pack: Path, text: str) -> bool:
    """Append one note to the pack's log through `engagement_state`, silently.

    Through the CLI entry point rather than a direct file write so the pack lock and the
    atomic write are the ones `engagement_state` already owns. Both streams are swallowed:
    a Stop hook's stdout is the block-decision channel and must carry nothing else, and its
    stderr is the user's console. `SystemExit` is caught because several `engagement_state`
    error paths exit rather than return, and bookkeeping must never take the gate down."""
    state = _engagement_state_module()
    if state is None:
        return False
    try:
        import contextlib
        import io

        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return int(state.main(["log-note", text, "--dir", str(pack)])) == 0
    except SystemExit:
        return False
    except Exception:
        return False


def _summarise_pack_findings(name: str, findings: list[str]) -> str:
    """One line per OTHER pack: count + finding CODES only (2026-08-17 live report: the
    other-engagements section pasted 13 findings' FULL text - schema details, line
    numbers, the lot - into the console of a session that had just opened unrelated new
    work; the user read a wall of another engagement's internals and the model then
    spent 7 minutes fixing it. Surfacing drift needs the existence and the shape, never
    the body)."""
    codes: dict[str, int] = {}
    for f in findings:
        code = f.split(":", 1)[0].strip() or "FINDING"
        codes[code] = codes.get(code, 0) + 1
    detail = ", ".join(f"{c} x{n}" if n > 1 else c for c, n in sorted(codes.items()))
    return f"[{name}] {len(findings)} finding(s): {detail}"


def _reason(
    active_findings: list[str],
    other_findings: list[str],
    slug: str | None,
    findings_hash: str,
    session_owned: bool = True,
    suppression_claimed: bool = False,
    blocks_so_far: int = 0,
) -> str:
    log_note = (
        f'engagement_state --slug {slug} log-note "{_NUDGE_MARKER_PREFIX}{findings_hash}"'
        if slug
        else f'engagement_state log-note "{_NUDGE_MARKER_PREFIX}{findings_hash}"'
    )
    # Other packs are a COUNT, never a list (2026-08-18 live report: even summarised
    # code lines sent a --new session reasoning about siblings' tasks every stop before
    # "deciding to move on" - existence is the only fact this session needs; the go
    # menu is the human surface where open engagements actually get picked up).
    other_block = ""
    if other_findings and active_findings:
        other_block = (
            f"\n\n({len(other_findings)} other open engagement(s)/area(s) in this project "
            "also carry outstanding DoD findings - not this session's scope; do not fix, "
            "list or narrate them. They get picked up from the go menu.)"
        )
    if active_findings:
        bullet = "\n- ".join(active_findings)
        head = (
            "🎩 DoD backstop (Stop hook, warn-first): your ACTIVE engagement is still "
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
            "than stopping silently. **If the user's own most recent message clearly asked for "
            "something else - new/different work, not this engagement** - proceed with THAT "
            'first. Note this nudge in one line (e.g. "noted: N DoD finding(s) on <slug>, '
            'deferred") and move on - **not even a fast, looks-harmless fix first.** '
            '"I\'ll just quickly fix this before starting" is still diverting; it is not the '
            "same as proceeding with THAT first, however small the detour looks, and do **NOT** "
            f"record `{log_note}` (that marker means the findings were actually acted on - "
            "recording it while deferring would wrongly suppress a real gap, not postpone it). "
            "Nothing is lost by deferring this way: this finding set re-arms and nudges again "
            "the next time a turn ends while this same engagement is still active and gated, so "
            "it cannot silently drop out of sight - it just doesn't override an explicit request "
            "you were just given, no matter how quick the detour looks."
        )
    elif not session_owned:
        # NOTHING here belongs to work this session started (2026-08-17 live report: a
        # fresh engagement's intake ended a turn before its workspace existed, the
        # ACTIVE marker still named the PREVIOUS engagement, and the model spent 7
        # minutes repairing it). 2026-08-18 tightening: even the per-pack code
        # summaries cost a reasoning detour every stop - this is now ONE compact
        # paragraph, count only, no per-pack lines.
        head = (
            f"🎩 DoD backstop (Stop hook, warn-first): {len(other_findings)} open "
            "engagement(s)/area(s) in this project carry outstanding DoD findings. "
            "**None belongs to work this session started - do NOT fix, open, list or "
            "narrate them.** Continue with the user's current request; open engagements "
            "get picked up from the go menu."
        )
        other_block = ""
    else:
        # Session-owned with a CLEAN active engagement: main() suppresses this case
        # entirely now (2026-08-18) - nothing for this session to act on means no
        # nudge at all. Kept as a harmless fallback should a caller still reach it.
        head = (
            "🎩 DoD backstop (Stop hook, warn-first): your active engagement has no "
            "outstanding DoD findings of its own."
        )
        other_block = ""
    # W-6: the suppression note is no longer a silencer the model can write ahead of the
    # work. It is honoured by the findings actually clearing - which is what changes the
    # hash - so the tail says what will and will not make this stop, and how many blocks
    # are left before the gate degrades to a warning and records that it gave up.
    stale_block = ""
    if suppression_claimed:
        stale_block = (
            f"\n\n⚠️ A `{_NUDGE_MARKER_PREFIX}{findings_hash}` note is already in this pack's "
            "log, but the check that just ran STILL reports the same findings - so the work "
            "the note claims was done was not done, or did not clear them. The note does not "
            "suppress this gate; only the findings going away does."
        )
    # Deliberately NOT a live countdown. The block count IS tracked (see _blocks_recorded),
    # but printing "N blocks left" would make this text differ between two otherwise
    # identical stops, and the reason string is compared for equality by the stop-hook
    # dispatcher's own contract test - a gate whose message shifts under its callers is a
    # worse trade than a reader not knowing the exact number, which the log records anyway.
    return (
        f"{head}"
        f"{other_block}"
        f"{stale_block}"
        "\n\n(This nudge will not fire again this stop cycle. It stops repeating when a fresh "
        f"`check_artifacts` run no longer reports these findings; recording `{log_note}` is the "
        "audit trail for that work, not a way to silence the gate. Repeated blocks on an "
        f"unchanged engagement are counted, and after {_BLOCK_CEILING} the gate degrades to a "
        "warning and records DOD-GATE-EXHAUSTED - the findings stay open either way.)"
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
        # M3 (2026-08-14 daemon-safety audit): deduped, not an unconditional insert -
        # same fix as persona_anchor.py's own _load_checker (see its comment for the
        # full rationale). This hook is re-exec'd fresh per Stop event INSIDE the
        # daemon when daemon-served (stop_hook_dispatcher.py loads it via importlib on
        # every call); an unconditional insert would grow the daemon's process-global
        # sys.path by one more entry per Stop event without bound over the daemon's
        # life, and risk a stale project's entry shadowing a later one.
        if str(project_root) not in sys.path:
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
    artifacts = _vsit_paths().engagements_dir(cwd)
    if not artifacts.is_dir():
        return 0

    # Session scoping (2026-08-16 live report): a pure-dormant "hello" session in a
    # project holding another session's leftover OPEN pack got the full fix-list and
    # was pulled into working that engagement - this gate keyed on disk state alone,
    # so one abandoned pack made dormancy impossible project-wide. Arm only for the
    # session that actually drove the team: engagement_state stamps the acting
    # session's id (from CLAUDE_CODE_SESSION_ID) into artifacts/.team-session.json on
    # every mutating command, and this payload carries this session's own id. Missing
    # stamp, missing payload id, or mismatch = a session that never engaged - stay
    # SILENT (user decision: fully dormant; open engagements still surface at the
    # /engage resume menu, virt-surv go, and the statusline). Fail-direction note:
    # this deliberately fails toward silence, the opposite of _already_nudged's
    # fail-toward-warning - dormancy is the promise being kept here.
    # 2026-09-12: match against EVERY session the stamp still remembers, not just the
    # latest one. The marker now records a `sessions` history alongside the single latest
    # `session`/`session_id` (engagement_state.stamp_team_session), and a single-id check
    # disarms this gate for session A the moment session B - or this hook's own W-6 block
    # note - writes a state mutation. Same semantics as engagement_state.team_sessions;
    # reimplemented here rather than imported so the gate keeps working when the module is
    # unreachable, and still failing toward silence on anything unreadable.
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

        # Which of the gated workspaces is the SESSION's active one (ADR-008's
        # .active-engagement.json, read via the same loader check_artifacts.py itself
        # uses)? 2026-08-11 fix, live report: a multi-engagement project opened for a
        # code review in ONE workspace got a single undifferentiated nudge covering
        # every open pack project-wide, and the reason text said "AUTO-FIX... and
        # re-close" with no scoping - the session got pulled into fixing unrelated,
        # unattended engagements it was never asked to touch. The SCAN stays broad on
        # purpose (that is the whole point of this backstop - catch a close that
        # silently never ran, anywhere in the project) but the FIX instruction now only
        # applies to the active engagement; other gated packs are surfaced, not
        # actioned. No active marker, or only one gated pack: no scoping question to
        # answer - falls back to the pre-fix, undifferentiated behaviour exactly.
        # Whose ACTIVE marker is it? (2026-08-17 live report: a new engagement's intake
        # ended a turn before its workspace init, the marker still named the PREVIOUS
        # engagement, and the fix-list sent the model off repairing it for 7 minutes
        # against the deferral rule - prose failed to hold this twice, so it is
        # mechanical now.) The marker records the SESSION that set it (write_active);
        # the fix-list is issued only when that session is THIS one. A legacy marker
        # with no session recorded, or a payload with no session id, keeps the old
        # slug-based behaviour exactly.
        active_slug = None
        active_owned = True
        try:
            record = json.loads((artifacts / ".active-engagement.json").read_text(encoding="utf-8"))
            active_slug = record.get("slug") or None
            marker_session = record.get("session")
            payload_session = data.get("session_id")
            if marker_session and payload_session:
                active_owned = marker_session == payload_session
        except Exception:  # nosec B110
            active_slug = None

        active_findings: list[str] = []
        other_findings: list[str] = []
        for name, pack in gated:
            if not name and packs:
                flat_finding = (
                    "FLAT-PACK-UNMIGRATED: legacy flat pack coexists with workspaces - "
                    "run `python -m scripts.engagement_state migrate`"
                )
                # Structural, not any one engagement's - but a fix instruction only for
                # a session that owns the active work; otherwise surface-only.
                (active_findings if active_owned else other_findings).append(flat_finding)
                continue
            raw = ca.check(pack)
            if not raw:
                continue
            if not active_owned:
                other_findings.append(_summarise_pack_findings(name or "(flat)", raw))
            elif active_slug is None or len(gated) == 1 or name == active_slug:
                prefix = f"[{name}] " if name else ""
                active_findings.extend(f"{prefix}{f}" for f in raw)
            else:
                # OTHER packs are summarised, never pasted in full (the same live
                # report's other half: 13 findings' full bodies in the console).
                other_findings.append(_summarise_pack_findings(name, raw))
        project_findings: list[str] = []
        if packs:
            # G8: project-level, not any one engagement's - always surfaced, same as
            # before (the orphan scan is read-only here - the CLI checker owns the
            # grandfather snapshot).
            project_findings.extend(ca.check_registry(artifacts))
            project_findings.extend(ca.check_root_orphans(artifacts))
        map_path = ca.find_codebase_map(cwd)
        if map_path is not None and map_path.is_file():
            project_findings.extend(ca.check_map(map_path))
        if project_findings:
            if active_owned:
                active_findings.extend(project_findings)
            else:
                other_findings.append(_summarise_pack_findings("project", project_findings))
    except Exception:
        return 0  # fail open - never brick a stop over a checker error

    if not active_findings and not other_findings:
        return 0
    if not active_findings and active_owned:
        # This session owns its active engagement and IT is clean - siblings' findings
        # are none of this session's business (2026-08-18 user report: a --new session
        # kept spending tokens on other engagements' DoD tasks before "moving on").
        # The human surface for those is the go menu's open-engagement list.
        return 0

    findings_hash = _findings_hash(active_findings + other_findings)
    # Marker home: prefer the flat pack when it's among the gated set (it's what most
    # single-engagement projects have), else the first gated workspace. Which specific pack
    # holds the marker is not semantically load-bearing - it is just a durable place to
    # record "this exact finding set was already nudged", shared across every gated pack.
    marker_name, marker_pack = next((g for g in gated if not g[0]), gated[0])
    slug = marker_name or None

    # W-6 (2026-09-12 audit). The suppression marker used to end the story: a
    # `dod-nudged:<hash>` note in the log silenced this gate permanently for that exact
    # finding set, with nothing checking that the findings had actually gone. The hash is a
    # deterministic SHA-256 of the printed findings, so recording it required none of the
    # work it claimed to represent.
    #
    # The correction is structural rather than a stronger instruction: the findings above
    # come from a check_artifacts run that just happened, this turn. So a marker matching
    # THIS hash is a marker whose findings are, right now, still being reported - that is
    # evidence the work was not done, not evidence that it was. The marker is therefore
    # honoured only by the finding set changing (a different hash never matches in the
    # first place), which is the same thing as "a fresh run reports them resolved".
    #
    # That alone would nudge forever on a genuinely unfixable finding, so the gate counts
    # its own blocks and gives up after _BLOCK_CEILING of them - degrading to a plain
    # stderr warning that lets the turn end, and recording DOD-GATE-EXHAUSTED so the
    # give-up is in the engagement's own record rather than silent. Both the counting and
    # the give-up note are written by this hook, not by the model.
    suppression_claimed = _already_nudged(marker_pack, findings_hash)
    try:
        blocks = _blocks_recorded(marker_pack)
    except Exception:
        blocks = 0  # unreadable log: fail toward blocking, same direction as _already_nudged

    if blocks >= _BLOCK_CEILING:
        if not _exhausted_recorded(marker_pack):
            _log_note(
                marker_pack,
                f"{_EXHAUSTED_MARKER_PREFIX}{findings_hash} - the DoD backstop blocked "
                f"{blocks} times on this engagement without its findings clearing, and has "
                "degraded to a warning so turns can end. The findings are still open; they "
                "are printed at every stop from here on, but nothing blocks on them.",
            )
        print(
            f"🎩 DoD backstop: still {len(active_findings) + len(other_findings)} outstanding "
            f"DoD finding(s) on this engagement after {blocks} blocks (DOD-GATE-EXHAUSTED "
            "recorded). The gate has degraded to this warning so the turn can end; the "
            "findings are still open and the record now says so:\n- "
            + "\n- ".join(active_findings or other_findings),
            file=sys.stderr,
        )
        return 0

    _log_note(marker_pack, f"{_BLOCK_MARKER_PREFIX}{findings_hash} (block {blocks + 1})")
    reason = _reason(
        active_findings,
        other_findings,
        slug,
        findings_hash,
        session_owned=active_owned,
        suppression_claimed=suppression_claimed,
        blocks_so_far=blocks,
    )
    print(json.dumps({"decision": "block", "reason": reason}))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
