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
    start_here = cwd / "artifacts" / "START-HERE.md"
    if not start_here.is_file():
        return 0  # dormant / no engagement -> stay silent (team is opt-in)
    try:
        text = start_here.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return 0
    # Anchor only while the engagement is OPEN (⏳) or BLOCKED (⛔); a ✅ closed one is done.
    if "⏳" not in text and "⛔" not in text:
        return 0
    print(_ANCHOR)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
