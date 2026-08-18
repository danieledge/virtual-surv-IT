#!/usr/bin/env python3
"""Enumeration redirect - Bash PreToolUse rule, ENGAGED SESSIONS ONLY (advisory tier).

2026-08-17 live report ("it's doing a find - shouldn't it be running the code map?"):
a review session priced its target by running a bare `find <project> -type f` that
dumped 217 paths into the transcript and counted caches, artifacts/ and .claude/
internals. The map-first rules were prose; this makes them mechanical: in a session
that invoked the team, a FULL-TREE enumeration command is denied with the sanctioned
alternatives named - the codebase map, `git ls-files`, a count-only pipe, or the
deterministic `scripts.repo_skeleton` inventory.

What still passes, deliberately:
- targeted lookups (`find ... -name/-iname/-path ...`) - locating a file is not
  enumerating a repo;
- count-only forms (`... | wc -l` / `| Measure-Object`) - the sizing rule's number;
- shallow listings (`-maxdepth 1/2`, plain `ls`) and `git ls-files`/`repo_skeleton`.

Dormant sessions are untouched (session-scoped arming, same stamp as the exec gate -
but ADVISORY polarity: an unknown/missing stamp stays SILENT, this is a cost rule,
not a safety wall). Fail-open on any internal error."""

from __future__ import annotations

import json
import os
import re
import sys

_ENUM_RE = re.compile(
    r"(?:\bfind\s+\S+[^|;&]*-type\s+f\b"  # find <dir> ... -type f
    r"|\bls\s+-[a-zA-Z]*R"  # ls -R recursive listings
    r"|\brg\s+--files\b"
    r"|\bGet-ChildItem\b[^|;&]*-Recurse\b"
    r"|\bgci\b[^|;&]*-Recurse\b"
    r"|\bdir\s+/s\b)",
    re.IGNORECASE,
)

_ALLOW_RE = re.compile(
    r"(?:\|\s*wc\s+-l"  # count-only
    r"|\|\s*Measure-Object\b"
    r"|-name\b|-iname\b|-path\b|-Filter\b|-Include\b"  # targeted lookups
    r"|-maxdepth\s+[12]\b"
    r"|\bgit\s+ls-files\b"
    r"|\brepo_skeleton\b)",
    re.IGNORECASE,
)


def _team_invoked_this_session(payload) -> bool:
    """Advisory polarity: arm only on a POSITIVE stamp match; anything unknowable
    (no session id, no stamp) stays silent - a dormant or plain-Claude session must
    never hit this rule (contrast guard-code-execution, a safety gate, which fails
    toward armed on the same inputs)."""
    sid = payload.get("session_id")
    if not sid:
        return False
    root = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    try:
        stamp = json.loads(
            open(os.path.join(root, "artifacts", ".team-session.json"), encoding="utf-8").read()
        ).get("session")
    except Exception:
        return False
    return stamp == sid


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except Exception:
        return 0
    if payload.get("tool_name") != "Bash":
        return 0
    command = (payload.get("tool_input") or {}).get("command") or ""
    if not isinstance(command, str) or not command:
        return 0
    try:
        if not _team_invoked_this_session(payload):
            return 0
        if _ENUM_RE.search(command) and not _ALLOW_RE.search(command):
            sys.stderr.write(
                "full-tree enumeration blocked during an engagement (map-first rule, "
                "2026-08-17): the inventory already exists - read docs/codebase-map.md "
                "when the project has one, use `git ls-files` (or `git ls-files | wc -l` "
                "for a count), or run `<python> -m scripts.repo_skeleton <dir>` for a "
                "deterministic, token-budgeted skeleton. Targeted lookups (-name/-path) "
                "and count-only pipes pass this rule; a bare recursive listing never "
                "does. To create the standing map, route to /map-codebase.\n"
            )
            return 2
    except Exception:
        return 0  # advisory tier - never break a session over a cost rule
    return 0


if __name__ == "__main__":
    sys.exit(main())
