#!/usr/bin/env python3
"""UserPromptSubmit hook - dormancy-aware persona re-anchor (ADR-005, review gap 5).

The /engage persona and soft discipline load ONCE and live only in conversation history, so on a
long engagement - or after Claude Code compacts the transcript - they erode: plain voice, generic
agent labels, skipped question-tool/gate discipline (the known persona-decay issue; every live
soft-discipline failure of 2026-07-24 was downstream of it). Hard guards are hook-enforced and
unaffected; what decays is presentation and process discipline.

This hook re-injects a TINY anchor on every user prompt **only while an engagement is live**
(open/blocked/closing state - the same packs the DoD Stop-hook watches). It survives compaction
because it arrives fresh each turn, and it costs nothing in dormant sessions (silent no-op, so
the team stays opt-in per CLAUDE.md).

2026-07-29 gate-hardening (workflow-robustness register, phase 1, G5/G7): pack state and
workspace detection now delegate to the checker's shared `pack_status` / `engagement_packs`
(loaded package-first, then __file__-relative for plugin installs) - one parser, one detection
rule, shared with the stop gate and the CLI checker. A raw emoji sniff survives only as the
last-resort fallback when the checker itself cannot be loaded.

Size is the design constraint: the anchor is ~8 lines of pointers, not a reload of the rules -
right-altitude, minimal high-signal tokens (Anthropic context-engineering).

2026-08-03 steady-state shrink (token-usage audit): the full anchor above fires on EVERY
prompt for the entire life of an engagement - on a long delivery that's dozens of turns paying
the full ~9-line anchor each time, when the decay risk it exists to counter is really about a
handful of rules (voice marker, question-tool discipline, roster names), not the close
procedure or artifact-placement detail restated every turn. So: the FULL anchor fires once per
pack (tracked the same read-only way `todo_panel_nudge.py` tracks its own one-time nudge - a
`persona-anchor-seeded` marker in the pack's own `log`, written by the model via `log-note`,
since hooks in this repo stay read-only); every later prompt gets a short 3-line anchor with
just the rules that actually decay. A brand-new engagement, or one whose marker cannot be read,
gets the full anchor - erring toward more context, never toward silently under-anchoring.

Stdin: UserPromptSubmit JSON payload. Stdout (exit 0) is added to the model's context. Fails open
on any error - a presentation aid must never break a prompt. UTF-8-forced (Windows-safe).

Wire via hooks -> "UserPromptSubmit" in .claude/settings.json + hooks/hooks.json
(scripts/apply-persona-anchor.sh - human-run; hook/config edits are human-only, ADR-002 rec 5).

2026-08-14 (ADR-014 daemon, multi-target extension): daemon-servable (fires on every
user message, the highest-frequency point besides Bash calls, so the biggest single
win in the daemon's target set) - was excluded from the FIRST daemon pass pending two
fixes an audit found: the sys.path insert above is now deduped (see its own comment),
and scripts/check_artifacts.py - the one real staleness risk, since _load_checker's
fallback path caches it at module level - is in guard_daemon.py's own watch list, so a
live edit to it correctly restarts the daemon (a fresh process re-imports everything,
including this module's own _CHECK_ARTIFACTS_MODULE_CACHE reset to None) rather than
silently serving a stale cached module.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_ANCHOR = """<persona-anchor>
🎩 Engagement live - persona/discipline anchor (auto, survives compaction):
- You are Morgan, the PM (opt-in team persona). Open every reply with 🎩. Name specialists by
  their roster names (roster: team-operating-guide.md - $PLUGIN_ROOT/docs/ in plugin mode).
- Ask EVERY clarification/choice via the AskUserQuestion tool - never questions buried in prose.
- Clean console (no code walls); artifacts ship .md + .html in artifacts/<slug>/. STATUS lives
  in the workspace's engagement-state.json - mutate via scripts.engagement_state; START-HERE
  is generated, never hand-edit. On resume re-read the state (decisions, consent, runtime).
- Close = set-status closing -> check_artifacts --fix -> summary email -> set-status closed
  (the close gate refuses on findings; findings are a FIX-LIST). If blocked, say plainly
  "NOT closed - outstanding: ...".
Record `{log_note}` now so later turns get the short form of this reminder instead of this
full one - the rules above stay true either way.
</persona-anchor>"""

# Steady-state: just the rules that actually decay turn-to-turn (voice, question-tool,
# roster) - the close procedure and artifact-placement detail are reference material a
# model consults when it reaches that gate, not something that erodes mid-turn.
_ANCHOR_SHORT = """<persona-anchor>
🎩 Morgan, PM (persona anchor, short form - full text already seeded this engagement): open
every reply with 🎩, ask every clarification via AskUserQuestion (never buried in prose), name
specialists by roster name. If blocked, say plainly "NOT closed - outstanding: ...".
</persona-anchor>"""

_SEEDED_MARKER = "persona-anchor-seeded"
_LIVE_STATUSES = ("open", "blocked", "closing")


def _force_utf8_output() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass


_CHECK_ARTIFACTS_MODULE_CACHE = None


def _load_checker(project_root: Path):
    """scripts.check_artifacts in BOTH run modes (same loader as the staged stop gate:
    package import first, then __file__-relative for plugin installs). None = unavailable;
    the legacy sniff below then keeps the anchor working.

    2026-08-03 perf audit: memoized - this hook is one process per prompt, so the win here
    is small on its own, but the same pattern applies uniformly across every hook that
    carries this loader (consistency, and it costs nothing if this hook is ever combined
    with another in one process, the way the Stop hooks were)."""
    global _CHECK_ARTIFACTS_MODULE_CACHE
    try:
        # 2026-08-14 (daemon-safety audit): deduped, not an unconditional insert - this
        # hook used to run once per prompt in its own fresh process, where an unbounded
        # sys.path (dying with the process every time) was harmless. Serving it from a
        # long-lived daemon changes that: without the dedup check, every call would grow
        # sys.path by one more entry for the same project_root, and if this daemon ever
        # served more than one project's requests over its lifetime, stale entries from
        # an earlier project would sit ahead of a later one, silently shadowing it. Same
        # dedup pattern guard_daemon.py's own _load_targets() already uses.
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


def _fallback_status(pack: Path) -> str | None:
    """Last-resort pack state when the checker cannot be loaded: state file first
    (ADR-006), then the legacy emoji sniff of START-HERE.md - the pre-hardening rule,
    kept ONLY so a stripped install still anchors."""
    state_file = pack / "engagement-state.json"
    if state_file.is_file():
        try:
            status = json.loads(state_file.read_text(encoding="utf-8")).get("status")
        except Exception:
            status = None
        if status in ("in_progress", "blocked", "closing", "closed"):
            return {"in_progress": "open"}.get(status, status)
    try:
        text = (pack / "START-HERE.md").read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None
    return "open" if ("⏳" in text or "⛔" in text) else None


def _open_engagements(artifacts: Path, ca) -> list[tuple[str, str, Path]]:
    """(name, status, pack path) for every LIVE pack - workspaces `artifacts/<slug>/` plus
    the legacy flat pack. Shared detection + parser when the checker loads (G5/G7);
    fail-open per pack: unreadable input never misfires the anchor."""
    out: list[tuple[str, str, Path]] = []
    packs: list[tuple[str, Path]] = []
    try:
        if ca is not None:
            packs = [(p.name, p) for p in ca.engagement_packs(artifacts)]
        else:
            packs = sorted(
                (p.name, p)
                for p in artifacts.iterdir()
                if p.is_dir()
                and not (p / ".archive").is_file()  # archived = out of play (0.33.2)
                and ((p / "engagement-state.json").is_file() or (p / "START-HERE.md").is_file())
            )
    except OSError:
        pass
    packs.append(("(flat)", artifacts))
    for name, pack in packs:
        try:
            status = ca.pack_status(pack) if ca is not None else _fallback_status(pack)
        except Exception:
            status = _fallback_status(pack)
        if status in _LIVE_STATUSES:
            out.append((name, status, pack))
    return out


def _already_seeded(pack: Path) -> bool:
    """True if the full anchor was already shown at least once for this pack - read-only,
    mirrors todo_panel_nudge.py's marker check. Unreadable state or no marker means "not yet
    seeded" (errs toward the full anchor, never toward silently under-anchoring)."""
    try:
        state = json.loads((pack / "engagement-state.json").read_text(encoding="utf-8"))
    except Exception:
        return False
    log = state.get("log")
    if not isinstance(log, list):
        return False
    return any(_SEEDED_MARKER in str(entry) for entry in log)


def _log_note_command(slug: str | None) -> str:
    return (
        f'engagement_state --slug {slug} log-note "{_SEEDED_MARKER}"'
        if slug
        else f'engagement_state log-note "{_SEEDED_MARKER}"'
    )


def main() -> int:
    _force_utf8_output()
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    # Project-root anchored, not cwd-anchored - same rationale as the staged DoD stop
    # gate: a wandered shell cwd (e.g. a kept eval sandbox under evals/runs/) must not
    # summon Morgan into a session that never engaged the team.
    cwd = Path(os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or Path.cwd())
    artifacts = cwd / "artifacts"
    if not artifacts.is_dir():
        return 0
    ca = _load_checker(cwd)
    opens = _open_engagements(artifacts, ca)
    if not opens:
        return 0

    # Marker home for the full-vs-short decision: prefer the flat pack when it's among the
    # live set, else the ACTIVE workspace if named, else the first. Not semantically tied to
    # one specific pack - just a durable place to record "the full anchor was already shown".
    active_slug = None
    try:
        active_slug = json.loads(
            (artifacts / ".active-engagement.json").read_text(encoding="utf-8")
        ).get("slug")
    except Exception:
        active_slug = None
    marker_name, _marker_status, marker_pack = next(
        (o for o in opens if o[0] == "(flat)"),
        next((o for o in opens if o[0] == active_slug), opens[0]),
    )
    slug = None if marker_name == "(flat)" else marker_name
    if _already_seeded(marker_pack):
        print(_ANCHOR_SHORT)
    else:
        print(_ANCHOR.format(log_note=_log_note_command(slug)))

    if len(opens) > 1 or (len(opens) == 1 and opens[0][0] != "(flat)"):
        marks = {"open": "⏳", "in_progress": "⏳", "blocked": "⛔", "closing": "🔒"}
        listing = ", ".join(f"{n} {marks.get(s, s)}" for n, s, _ in opens)
        # R1: the ACTIVE slug is recorded on disk (.active-engagement.json) - surface it
        # so a resumed session targets the right workspace instead of guessing.
        if active_slug and any(n == active_slug for n, _, _ in opens):
            tail = (
                f" - ACTIVE: {active_slug} (from .active-engagement.json); target its "
                "workspace (--slug), or set-active to switch"
            )
        else:
            tail = (
                " - each lives in artifacts/<slug>/; record which is ACTIVE this session "
                "(`engagement_state set-active <slug>`) and target its workspace (--slug)"
            )
        print(f"<open-engagements>{listing}{tail}</open-engagements>")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
