#!/usr/bin/env python3
"""SessionStart hook - re-brief a mid-engagement session after compaction or resume.

The persona anchor (ADR-005) re-injects discipline every user turn, and 0.33.0 made every
session decision recoverable from disk (ACTIVE marker, gate answers, consent outcome,
runtime, phase - register R1-R7). What was still missing is the moment RIGHT AFTER a
compaction or a `--resume`: the model continues with a summarised transcript and no
instruction to go and re-read the disk state it now has. This hook closes that seam
(ADR-011; the natural mirror of ADR-004's capture-at-end proposal).

Dormancy-exact by construction: it emits output ONLY when a pack under the project's
`artifacts/` is genuinely live (state in_progress/blocked/closing, index sniff fallback).
A session that never engaged the team gets zero added context, in every project the plugin
is installed into. Fails open (exit 0, no output) on any internal error.

Fires on the `compact` and `resume` sources only (the apply script sets the matcher);
`startup`/`clear` sessions are untouched. Stdout (exit 0) is added to the model's context.

Wire via scripts/apply-session-brief.sh (HUMAN-run - hook/config edits are human-only,
ADR-002 rec 5) into `.claude/settings.json` + `hooks/hooks.json` -> hooks.SessionStart.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_LIVE = ("in_progress", "blocked", "closing")
_MARKS = {"in_progress": "⏳", "blocked": "⛔", "closing": "🔒"}


def _force_utf8_output() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass


def _pack_state(pack: Path) -> dict | None:
    state_file = pack / "engagement-state.json"
    if state_file.is_file():
        try:
            state = json.loads(state_file.read_text(encoding="utf-8"))
            if state.get("status") in _LIVE:
                return state
            if state.get("status") == "closed":
                return None
        except Exception:  # nosec B110 - unreadable state falls through to the index sniff
            pass
    try:
        text = (pack / "START-HERE.md").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    if any(e in text for e in ("⏳", "⛔", "🔒")):
        return {"status": "open", "engagement": {}, "legacy_sniff": True}
    return None


def main() -> int:
    _force_utf8_output()
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    if data.get("source") not in ("compact", "resume"):
        return 0  # matcher backstop: never touch startup/clear sessions
    root = Path(os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or Path.cwd())
    artifacts = root / "artifacts"
    if not artifacts.is_dir():
        return 0
    try:
        packs: list[tuple[str, Path]] = [("(flat)", artifacts)]
        packs += sorted((p.name, p) for p in artifacts.iterdir() if p.is_dir())
        live: list[tuple[str, dict]] = []
        for name, pack in packs:
            state = _pack_state(pack)
            if state is not None:
                live.append((name, state))
        if not live:
            return 0  # dormant: zero added context
        active = None
        try:
            active = json.loads(
                (artifacts / ".active-engagement.json").read_text(encoding="utf-8")
            ).get("slug")
        except Exception:
            active = None
        name, state = next((r for r in live if r[0] == active), live[0])
        status = state.get("status")
        phase = state.get("phase") or "?"
        where = "artifacts/" if name == "(flat)" else f"artifacts/{name}/"
        others = ", ".join(f"{n} {_MARKS.get(s.get('status'), '')}" for n, s in live if n != name)
        lines = [
            "<engagement-resume-brief>",
            f"🎩 This session was compacted/resumed MID-ENGAGEMENT: {name} "
            f"{_MARKS.get(status, '')} {status} · phase {phase} ({where}).",
            f"- Re-read {where}engagement-state.json FIRST: the recorded decisions "
            "(go-ahead, fix-cycle, data-attestation), execution_consent_outcome and "
            "runtime are the record - answers recorded there are NOT re-asked, and a "
            "consent 'declined' stands until the HUMAN says otherwise.",
            f"- START-HERE.md in {where} is the generated index of what exists; the "
            "outstanding list is the to-do. Continue from there - do not restart, do not "
            "re-open settled gates.",
        ]
        if others:
            lines.append(f"- Other engagements on disk: {others} (parked - target yours).")
        lines.append("</engagement-resume-brief>")
        print("\n".join(lines))
    except Exception:
        return 0  # fail open - a resume aid must never break a session start
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
