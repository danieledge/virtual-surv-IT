#!/usr/bin/env python3
"""
PreToolUse guard: scope the four findings-pack agents' Write grant to their OWN pack file.

2026-08-03 token-usage audit (P4): `code-reviewer`, `compliance-reviewer`, `model-validator`
and `performance-reviewer` held no Write, so their full structured findings-pack JSON had to
transit the orchestrator's context TWICE - once as the Task tool's return value, once again
when the orchestrator re-emitted it as a Write tool call to persist the pack. Granting these
four agents `Write` (never `Edit`) lets each write its own pack directly, halving that cost.

The risk that grant opens: a Write tool with no path restriction, however it got there, is a
much bigger blast radius than "author one JSON file". This guard closes that gap the same way
the raw-data and code-execution guards close theirs - mechanically, not by trusting the
agent's own instructions to stay in scope.

How it's enforced: Claude Code's PreToolUse payload includes `agent_type` whenever the tool
call originates from a subagent (absent for the orchestrator's own calls) - see
docs/adr/ADR-002-safety-hook-threat-model.md for the guard family's threat model. This guard
fires ONLY when `agent_type` is one of the four scoped names AND `tool_name == "Write"`, and
blocks unless the target path matches the findings-pack shape
(`artifacts/<slug>/data/findings-*.json`, or `artifacts/data/findings-*.json` for a flat pack).
Every other Write call - the orchestrator's own, a build agent's, anything without a matching
`agent_type` - passes through untouched; this guard has no opinion about them.

Deliberately ONE shared pattern for all four agents, not a per-agent kind-specific pattern
(e.g. requiring `compliance-reviewer` to prefix its slug `compliance-`): that naming
discipline is already documented in each agent's own instructions (so two reviewers of the
same engagement don't collide on one filename) and is a correctness concern, not a security
boundary - collapsing it into this guard as well would couple the guard to naming conventions
that may evolve, without adding to the actual property being enforced ("can this agent write
outside the findings-pack directory at all").

Protocol: read the PreToolUse JSON on stdin; exit 2 to block (stderr fed back to the model);
exit 0 to allow. Fails CLOSED on an unexpected crash (a scoping guard that silently opened would
be a silent safety regression, same policy as guard-raw-data.py / guard-code-execution.py /
guard-consent-writes.py) but fails OPEN on a malformed/unparseable payload, matching every
other guard in this family (a hook that cannot even parse the input has nothing concrete to
act on, and bricking every tool call over a malformed payload would be worse than the risk it
guards against).
"""

from __future__ import annotations

import json
import re
import sys

_SCOPED_AGENTS = frozenset(
    {"code-reviewer", "compliance-reviewer", "model-validator", "performance-reviewer"}
)

# Matches .../artifacts/<slug>/data/findings-<anything>.json (workspace) or
# .../artifacts/data/findings-<anything>.json (flat pack), absolute or relative, either
# slash style. Anchored at the end so a path that merely CONTAINS this shape somewhere in
# the middle (not as its actual target) does not slip through.
_ALLOWED_PATH_RE = re.compile(r"(^|[/\\])artifacts[/\\](?:[^/\\]+[/\\])?data[/\\]findings-[^/\\]+\.json$")


def _block(agent_type: str, path: str) -> None:
    sys.stderr.write(
        f"Blocked (findings-pack write scope, agent={agent_type}): this agent's Write grant "
        "exists ONLY to author its own findings-pack JSON at "
        "artifacts/<slug>/data/findings-*.json (or artifacts/data/findings-*.json for a flat "
        f"pack) - attempted target: {path!r}. Everything else - the rendered report, any other "
        "file - stays with the orchestrator or a build agent.\n"
    )
    sys.exit(2)


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0  # malformed payload - fail open, matches every other guard's policy

    if payload.get("tool_name") != "Write":
        return 0

    agent_type = payload.get("agent_type") or ""
    if agent_type not in _SCOPED_AGENTS:
        return 0  # the orchestrator's own call, or an agent this guard has no opinion on

    path = (payload.get("tool_input") or {}).get("file_path") or ""
    if not _ALLOWED_PATH_RE.search(path):
        _block(agent_type, path)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.stderr.write(
            "guard-findings-pack-write crashed unexpectedly; failing closed (blocked). "
            "See docs/adr/ADR-002-safety-hook-threat-model.md.\n"
        )
        sys.exit(2)
