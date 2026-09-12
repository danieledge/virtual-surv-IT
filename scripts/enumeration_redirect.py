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


_STAMP_NAME = ".team-session.json"
_MAX_STAMPED_SESSIONS = 8


def _stamp_candidates(root):
    """Every place the acting-session stamp may live, newest layout first.

    2026-09-12 audit (H-22). On 2026-09-11 both safety guards were fixed to read the stamp
    from BOTH layouts, with a comment recording what the single-path read had cost ("in every
    project created since then the stamp was never found, this returned False, and the gate
    was OFF"). The same fix was not applied here, so in any VSIT-layout project - the default
    since PREFER_NEW_LAYOUT became true on 2026-08-28 - this rule was permanently silent: a
    cost control reporting healthy and doing nothing. Copied verbatim from
    guard-code-execution.py rather than imported, for the reason given there: a hook must not
    depend on the scripts package being importable.
    """
    return (
        os.path.join(root, "VSIT", "engagements", _STAMP_NAME),
        os.path.join(root, "artifacts", _STAMP_NAME),
    )


def _stamped_session_ids(stamp_path) -> tuple:
    """Every session id this stamp arms - legacy {"session": id} and the current
    {"session_id": ..., "sessions": [...]} alike (2026-09-12, H-13)."""
    try:
        with open(stamp_path, encoding="utf-8") as handle:
            data = json.loads(handle.read())
    except Exception:  # noqa: BLE001 - absent/unreadable: arms nothing
        return ()
    if not isinstance(data, dict):
        return ()
    ids = []
    for key in ("session", "session_id"):
        value = data.get(key)
        if isinstance(value, str) and value:
            ids.append(value)
    sessions = data.get("sessions")
    if isinstance(sessions, list):
        for entry in sessions[-_MAX_STAMPED_SESSIONS:]:
            value = entry.get("id") if isinstance(entry, dict) else entry
            if isinstance(value, str) and value:
                ids.append(value)
    return tuple(ids)


def _team_invoked_this_session(payload) -> bool:
    """Advisory polarity: arm only on a POSITIVE stamp match; anything unknowable
    (no session id, no stamp) stays silent - a dormant or plain-Claude session must
    never hit this rule (contrast guard-code-execution, a safety gate, which fails
    toward armed on the same inputs)."""
    sid = payload.get("session_id")
    if not sid:
        return False
    root = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    return any(sid in _stamped_session_ids(path) for path in _stamp_candidates(root))


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
                # repo_skeleton leads (2026-08-20, live corporate session): the old wording
                # opened with "the inventory already exists - read docs/codebase-map.md",
                # which is untrue for the directory that actually triggers this most often -
                # an archive the session extracted seconds earlier. No map covers it and it
                # is not a git repo, so the first two suggestions both dead-end and the one
                # that always works was listed third. Note also that the rule matches the
                # WHOLE command, so a listing at the end of an && chain blocks the earlier
                # steps too; run the extraction separately.
                "full-tree enumeration blocked during an engagement (map-first rule, "
                "2026-08-17): run `<python> -m scripts.repo_skeleton <dir>` for a "
                "deterministic, token-budgeted inventory - this works for ANY directory, "
                "including one you just extracted. The Glob tool also enumerates by "
                "pattern and is cheaper than a Bash walk. "
                "including one you just extracted or downloaded. For the working project "
                "itself, docs/codebase-map.md (when it has one) or `git ls-files` (or "
                "`git ls-files | wc -l` for a count) are cheaper still. Targeted lookups "
                "(-name/-path) and count-only pipes pass this rule; a bare recursive "
                "listing never does. This matches the whole command, so a listing at the "
                "end of an `&&` chain blocks the earlier steps too - run those separately. "
                "To create the standing map, route to /map-codebase.\n"
            )
            return 2
    except Exception:
        return 0  # advisory tier - never break a session over a cost rule
    return 0


if __name__ == "__main__":
    sys.exit(main())
