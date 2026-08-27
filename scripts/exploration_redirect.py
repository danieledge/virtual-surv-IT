#!/usr/bin/env python3
"""Exploration redirect - Read/Grep PreToolUse rule, ENGAGED SESSIONS ONLY (advisory tier).

WHY THIS EXISTS AS CODE AND NOT AS PROSE (2026-08-26). The exploration rules were already
written, and written well: `docs/team-operating-guide-orchestration.md` Exploration
discipline, copied verbatim into `.claude/agents/code-reviewer.md`. A real review then
burned an estimated 75k tokens, of which roughly 25k was covered by those exact rules -
two full-file source reads and two unbounded greps. The owner's verdict on the audit that
found it: "a written policy that isn't followed doesn't help."

That is the whole design brief. `enumeration_redirect.py` already proved the pattern for
one rule (map-first) after the same discovery - "the map-first rules were prose; this makes
them mechanical". This does it for the other two, the ones that actually cost the money:
broad Reads and broad Greps.

WHAT IT DOES
- A Read of a LARGE file with no offset/limit is redirected once, naming the cheap paths:
  `repo_skeleton --slice FILE:SYMBOL` for one symbol, Grep with context for an anchor, or
  Read with offset/limit for a known region.
- A content-mode Grep with no head_limit is redirected once, naming `output_mode: "count"`
  first. Two greps in that review returned 80 and 50 near-identical config lines.

REDIRECTED ONCE, NOT BLOCKED. Each distinct target gets exactly one redirect per session;
repeating the call goes straight through. Sometimes the full read IS right - that review's
own retrospective recorded one scorer that "genuinely needed a full read - that one was
well spent" - so the mechanism must cost a deliberate choice one turn, never make it
impossible.
A rule that blocks correct work gets switched off, and then protects nothing.

Dormant sessions are untouched (same session stamp as the exec gate, ADVISORY polarity: an
unknown or missing stamp stays SILENT - this is a cost rule, not a safety wall). Fail-open
on any internal error, and on anything it cannot measure.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys

# A Read above this many lines should be a deliberate act. Chosen from the live evidence:
# the three reads that dominated that review's waste were 499, 529 and 531 lines (~51k of
# the ~75k). Deliberately NOT set at the "small file" line of ~150 - a medium file read
# whole is usually the right call, and a rule that fires constantly is a rule that gets
# disabled. Project-overridable via .claude/team-preferences.json "read_nudge_lines".
_DEFAULT_LARGE_FILE_LINES = 400

_STATE_NAME = ".exploration-nudges.json"
_MAX_REMEMBERED = 400  # bounded: this file must not grow without limit in a long session


def _prefs_int(root: str, key: str, default: int) -> int:
    try:
        with open(os.path.join(root, ".claude", "team-preferences.json"), encoding="utf-8") as fh:
            value = json.load(fh).get(key)
        return int(value) if isinstance(value, (int, float, str)) else default
    except Exception:
        return default


def _team_invoked_this_session(payload: dict) -> bool:
    """Same stamp as the exec gate. Advisory polarity: anything unknown means SILENT."""
    sid = payload.get("session_id")
    if not sid:
        return False
    root = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    try:
        with open(os.path.join(root, "artifacts", ".team-session.json"), encoding="utf-8") as fh:
            return json.load(fh).get("session") == sid
    except Exception:
        return False


def _already_nudged(root: str, sid: str, key: str) -> bool:
    """True if this exact target has been redirected before in this session.

    Best-effort on every failure path: an unwritable or corrupt state file means the nudge
    may repeat, which is mildly annoying, rather than the rule silently vanishing.
    """
    path = os.path.join(root, "artifacts", _STATE_NAME)
    digest = hashlib.sha256(f"{sid}\n{key}".encode("utf-8")).hexdigest()[:16]
    seen = []
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict) and data.get("session") == sid:
            seen = data.get("seen") or []
    except Exception:
        seen = []
    if digest in seen:
        return True
    seen.append(digest)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"session": sid, "seen": seen[-_MAX_REMEMBERED:]}, fh)
    except Exception:
        pass
    return False


def _line_count(path: str) -> int | None:
    """Lines in a text file, or None if it cannot be counted (binary, missing, unreadable).

    Counts bytes in chunks rather than reading the file into memory - this runs before
    every Read in an engaged session, so it must not itself be the expensive step.
    """
    try:
        if os.path.getsize(path) > 8_000_000:
            return None  # far past any sane read; let the harness handle it
        count = 0
        with open(path, "rb") as fh:
            while True:
                chunk = fh.read(1 << 20)
                if not chunk:
                    break
                if b"\x00" in chunk:
                    return None  # binary
                count += chunk.count(b"\n")
        return count + 1
    except OSError:
        return None


def _read_advice(path: str, lines: int) -> str:
    return (
        f"Reading {os.path.basename(path)} whole is {lines} lines. During an engagement, "
        "reach for the cheap path first (exploration discipline, "
        "docs/team-operating-guide-orchestration.md):\n"
        f"  - ONE symbol: `<python> -m scripts.repo_skeleton --slice {path}:<symbol> .` "
        "(exact for Python, best-effort elsewhere; typically ~1% of a whole-file read)\n"
        "  - a known anchor: Grep with -C for the surrounding window\n"
        f"  - a known region: Read {os.path.basename(path)} with offset/limit\n"
        "If the whole file genuinely is the answer - control flow matters, or you need "
        "whole-file semantics - repeat this exact call and it will go through. This "
        "redirect fires ONCE per file per session."
    )


def _grep_advice(pattern: str) -> str:
    return (
        f"Grep for {pattern!r} is running in content mode with no head_limit. During an "
        "engagement, count before content: a repeated config key returns dozens of "
        "near-identical lines (two greps in one live review returned 80 and 50).\n"
        '  - `output_mode: "count"` first to size the answer, then read a targeted block\n'
        "  - or keep content mode and set head_limit\n"
        "Repeat this exact call to proceed anyway. This redirect fires ONCE per pattern "
        "per session."
    )


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except Exception:
        return 0
    tool = payload.get("tool_name")
    if tool not in ("Read", "Grep"):
        return 0
    tool_input = payload.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        return 0
    try:
        if not _team_invoked_this_session(payload):
            return 0
        root = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
        sid = str(payload.get("session_id") or "")

        if tool == "Read":
            path = tool_input.get("file_path")
            if not isinstance(path, str) or not path:
                return 0
            # An explicit window is already the disciplined form - never redirect it.
            if tool_input.get("offset") or tool_input.get("limit"):
                return 0
            threshold = _prefs_int(root, "read_nudge_lines", _DEFAULT_LARGE_FILE_LINES)
            if threshold <= 0:
                return 0  # project opted out
            lines = _line_count(path)
            if lines is None or lines <= threshold:
                return 0
            if _already_nudged(root, sid, f"read:{path}"):
                return 0
            sys.stderr.write(_read_advice(path, lines) + "\n")
            return 2

        pattern = tool_input.get("pattern")
        if not isinstance(pattern, str) or not pattern:
            return 0
        mode = tool_input.get("output_mode") or "content"
        if mode != "content" or tool_input.get("head_limit"):
            return 0
        if _already_nudged(root, sid, f"grep:{pattern}"):
            return 0
        sys.stderr.write(_grep_advice(pattern) + "\n")
        return 2
    except Exception:
        return 0  # advisory tier - never break a session over a cost rule
    return 0


if __name__ == "__main__":
    sys.exit(main())
