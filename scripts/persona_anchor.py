#!/usr/bin/env python3
"""UserPromptSubmit hook - dormancy-aware persona re-anchor (ADR-005, review gap 5).

The /engage persona and soft discipline load ONCE and live only in conversation history, so on a
long engagement - or after Claude Code compacts the transcript - they erode: plain voice, generic
agent labels, skipped question-tool/gate discipline (the known persona-decay issue; every live
soft-discipline failure of 2026-07-24 was downstream of it). Hard guards are hook-enforced and
unaffected; what decays is presentation and process discipline.

This hook re-injects a TINY anchor on every user prompt **only while an engagement is live**
(artifacts/START-HERE.md exists with an open/blocked status - the same trigger the DoD Stop-hook
uses). It survives compaction because it arrives fresh each turn, and it costs nothing in dormant
sessions (silent no-op, so the team stays opt-in per CLAUDE.md).

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
  their roster names (canonical roster: docs/team-operating-guide.md).
- Ask EVERY clarification/choice via the AskUserQuestion tool - never questions buried in prose.
- Keep the console clean (no code walls); artifacts ship .md + .html; interim names stay
  pass-scoped; STATUS lives only in artifacts/START-HERE.md - update it with every artifact.
- Close = `check_artifacts --fix` then the summary email; gate findings are a FIX-LIST, not a
  report. If blocked, say plainly "NOT closed - outstanding: ...".
</persona-anchor>"""


def _force_utf8_output() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass


def _pack_status(pack: Path) -> str | None:
    """'in_progress' | 'blocked' | 'closed' | 'open' (legacy sniff) | None (not a pack).

    The machine-readable state file (ADR-006) is authoritative when parseable - `closed`
    wins even over a stale ⏳ render, an open status arms before any render exists. The
    emoji sniff of START-HERE.md is the fallback so pre-state packs keep working."""
    state_file = pack / "engagement-state.json"
    if state_file.is_file():
        try:
            status = json.loads(state_file.read_text(encoding="utf-8")).get("status")
        except Exception:
            status = None
        if status in ("in_progress", "blocked", "closed"):
            return status
    start_here = pack / "START-HERE.md"
    try:
        text = start_here.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None
    return "open" if ("⏳" in text or "⛔" in text) else None


def _open_engagements(artifacts: Path) -> list[tuple[str, str]]:
    """(name, status) for every LIVE pack - workspaces `artifacts/<slug>/` (0.31) plus the
    legacy flat pack. Fail-open per pack: unreadable input never misfires the anchor."""
    out: list[tuple[str, str]] = []
    packs: list[tuple[str, Path]] = []
    try:
        packs = sorted(
            (p.name, p) for p in artifacts.iterdir()
            if p.is_dir() and (
                (p / "engagement-state.json").is_file() or (p / "START-HERE.md").is_file()
            )
        )
    except OSError:
        pass
    packs.append(("(flat)", artifacts))
    for name, pack in packs:
        status = _pack_status(pack)
        if status in ("in_progress", "blocked", "open"):
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
    opens = _open_engagements(cwd / "artifacts")
    if not opens:
        return 0
    print(_ANCHOR)
    if len(opens) > 1 or (len(opens) == 1 and opens[0][0] != "(flat)"):
        marks = {"in_progress": "⏳", "blocked": "⛔", "open": "⏳"}
        listing = ", ".join(f"{n} {marks.get(s, s)}" for n, s in opens)
        print(
            f"<open-engagements>{listing} - each lives in artifacts/<slug>/; state which "
            "is ACTIVE this session and target its workspace (--slug)</open-engagements>"
        )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
