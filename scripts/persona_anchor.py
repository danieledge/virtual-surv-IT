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

Stdin: UserPromptSubmit JSON payload. Stdout (exit 0) is added to the model's context. Fails open
on any error - a presentation aid must never break a prompt. UTF-8-forced (Windows-safe).

Wire via hooks -> "UserPromptSubmit" in .claude/settings.json + hooks/hooks.json
(scripts/apply-persona-anchor.sh - human-run; hook/config edits are human-only, ADR-002 rec 5).
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
</persona-anchor>"""

_LIVE_STATUSES = ("open", "blocked", "closing")


def _force_utf8_output() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass


def _load_checker(project_root: Path):
    """scripts.check_artifacts in BOTH run modes (same loader as the staged stop gate:
    package import first, then __file__-relative for plugin installs). None = unavailable;
    the legacy sniff below then keeps the anchor working."""
    try:
        sys.path.insert(0, str(project_root))
        from scripts import check_artifacts

        return check_artifacts
    # Probe only; fall through to the file-relative loader.
    except Exception:  # nosec B110
        pass
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


def _open_engagements(artifacts: Path, ca) -> list[tuple[str, str]]:
    """(name, status) for every LIVE pack - workspaces `artifacts/<slug>/` plus the legacy
    flat pack. Shared detection + parser when the checker loads (G5/G7); fail-open per
    pack: unreadable input never misfires the anchor."""
    out: list[tuple[str, str]] = []
    packs: list[tuple[str, Path]] = []
    try:
        if ca is not None:
            packs = [(p.name, p) for p in ca.engagement_packs(artifacts)]
        else:
            packs = sorted(
                (p.name, p)
                for p in artifacts.iterdir()
                if p.is_dir()
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
            out.append((name, status))
    return out


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
    print(_ANCHOR)
    if len(opens) > 1 or (len(opens) == 1 and opens[0][0] != "(flat)"):
        marks = {"open": "⏳", "in_progress": "⏳", "blocked": "⛔", "closing": "🔒"}
        listing = ", ".join(f"{n} {marks.get(s, s)}" for n, s in opens)
        # R1: the ACTIVE slug is recorded on disk (.active-engagement.json) - surface it
        # so a resumed session targets the right workspace instead of guessing.
        active = None
        try:
            active = json.loads(
                (artifacts / ".active-engagement.json").read_text(encoding="utf-8")
            ).get("slug")
        except Exception:
            active = None
        if active and any(n == active for n, _ in opens):
            tail = (
                f" - ACTIVE: {active} (from .active-engagement.json); target its "
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
