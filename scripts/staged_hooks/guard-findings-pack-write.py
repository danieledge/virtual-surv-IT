#!/usr/bin/env python3
"""
PreToolUse guard: scope the four findings-pack agents' Write grant to their OWN pack file, and
(opt-in) mechanically cap how many findings one Write to a findings-pack path may carry.

2026-08-03 token-usage audit (P4): `code-reviewer`, `compliance-reviewer`, `model-validator`
and `performance-reviewer` held no Write, so their full structured findings-pack JSON had to
transit the orchestrator's context TWICE - once as the Task tool's return value, once again
when the orchestrator re-emitted it as a Write tool call to persist the pack. Granting these
four agents `Write` (never `Edit`) lets each write its own pack directly, halving that cost.

The risk that grant opens: a Write tool with no path restriction, however it got there, is a
much bigger blast radius than "author one JSON file". This guard closes that gap the same way
the raw-data and code-execution guards close theirs - mechanically, not by trusting the
agent's own instructions to stay in scope.

How SCOPING is enforced: Claude Code's PreToolUse payload includes `agent_type` whenever the
tool call originates from a subagent (absent for the orchestrator's own calls) - see
docs/adr/ADR-002-safety-hook-threat-model.md for the guard family's threat model. This half of
the guard fires ONLY when `agent_type` is one of the four scoped names AND `tool_name ==
"Write"`, and blocks unless the target path matches the findings-pack shape
(`artifacts/<slug>/data/findings-*.json`, or `artifacts/data/findings-*.json` for a flat pack).
Every other Write call - the orchestrator's own, a build agent's, anything without a matching
`agent_type` - passes through this half untouched; it has no opinion about them.

Deliberately ONE shared pattern for all four agents, not a per-agent kind-specific pattern
(e.g. requiring `compliance-reviewer` to prefix its slug `compliance-`): that naming
discipline is already documented in each agent's own instructions (so two reviewers of the
same engagement don't collide on one filename) and is a correctness concern, not a security
boundary - collapsing it into this guard as well would couple the guard to naming conventions
that may evolve, without adding to the actual property being enforced ("can this agent write
outside the findings-pack directory at all").

2026-08-05 (live corp report): a live consolidation write of 13 merged findings hit
`API Error: The operation timed out` on the same single-Write attempt twice in a row - a
generation large enough can trip a corporate proxy's timeout regardless of who's writing.
`docs/team-operating-guide.md`'s orchestration-discipline bullet now tells Morgan to build a
large merged pack incrementally (Write a small first batch, then Edit to append the rest) - but
that is PROSE guidance, easy to skip under pressure. This second half of the guard makes it
mechanical: when a project has opted into `large_context_review_split`
(`.claude/team-preferences.json`, project-only, default `false` - same key the split-review
design already uses, read fresh every call, no caching) and the Write content parses as a
findings pack whose `findings` array exceeds `_MAX_FINDINGS_PER_WRITE`, the write is blocked
with an explicit "split it" message - for ANY caller, including the orchestrator's own calls
(the scoping half above has no opinion on those; this half does, by design, since the
consolidation write that timed out live was the orchestrator's own). Off by default: a project
that has never hit this issue sees no behaviour change at all. This CANNOT prevent a timeout
that happens mid-generation before a tool call even forms (no hook fires on that - there is no
completed tool call yet); it only catches an oversized Write that DID finish generating,
turning "she might remember the heuristic" into "she is told, mechanically, every time."

Protocol: read the PreToolUse JSON on stdin; exit 2 to block (stderr fed back to the model);
exit 0 to allow. Fails CLOSED on an unexpected crash (a scoping guard that silently opened would
be a silent safety regression, same policy as guard-raw-data.py / guard-code-execution.py /
guard-consent-writes.py) but fails OPEN on a malformed/unparseable payload, OR on unreadable/
unparseable team-preferences.json, OR on Write content that doesn't parse as a findings pack
(this guard validates neither pack schema nor JSON well-formedness - that is
scripts.validate_findings's job, at close, not this guard's at write-time) - matching every
other guard in this family (nothing concrete to act on is treated the same as no opinion).
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

_SCOPED_AGENTS = frozenset(
    {"code-reviewer", "compliance-reviewer", "model-validator", "performance-reviewer"}
)

# Matches .../artifacts/<slug>/data/findings-<anything>.json (workspace) or
# .../artifacts/data/findings-<anything>.json (flat pack), absolute or relative, either
# slash style. Anchored at the end so a path that merely CONTAINS this shape somewhere in
# the middle (not as its actual target) does not slip through.
_ALLOWED_PATH_RE = re.compile(r"(^|[/\\])artifacts[/\\](?:[^/\\]+[/\\])?data[/\\]findings-[^/\\]+\.json$")

# Keep in sync with docs/team-operating-guide.md's orchestration-discipline bullet ("roughly
# >8 findings to merge... build the pack incrementally").
_MAX_FINDINGS_PER_WRITE = 8


def _block_scope(agent_type: str, path: str) -> None:
    sys.stderr.write(
        f"Blocked (findings-pack write scope, agent={agent_type}): this agent's Write grant "
        "exists ONLY to author its own findings-pack JSON at "
        "artifacts/<slug>/data/findings-*.json (or artifacts/data/findings-*.json for a flat "
        f"pack) - attempted target: {path!r}. Everything else - the rendered report, any other "
        "file - stays with the orchestrator or a build agent.\n"
    )
    sys.exit(2)


def _block_size(path: str, count: int) -> None:
    sys.stderr.write(
        f"Blocked (findings-pack size limit, large_context_review_split is on): {path!r} "
        f"would write {count} findings in one call - {_MAX_FINDINGS_PER_WRITE} is the limit for "
        "a single Write, because a large-enough single generation is what times out on a "
        "corporate proxy, not the number of calls. Write a valid pack now with the first "
        f"{_MAX_FINDINGS_PER_WRITE} findings plus every required top-level field, then use Edit "
        "to append the remaining findings in batches of roughly 4-6 "
        "(docs/team-operating-guide.md's orchestration-discipline bullet).\n"
    )
    sys.exit(2)


def _large_context_split_enabled() -> bool:
    root = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    try:
        prefs = json.loads(
            Path(root, ".claude", "team-preferences.json").read_text(encoding="utf-8-sig")
        )
        return bool(prefs.get("large_context_review_split", False))
    except (OSError, ValueError):
        return False  # absent/unreadable/unparseable - same default as everywhere else


def _finding_count(content: str) -> "int | None":
    try:
        pack = json.loads(content)
    except (ValueError, TypeError):
        return None  # not JSON (yet) - not this guard's job to validate; let it through
    findings = pack.get("findings") if isinstance(pack, dict) else None
    return len(findings) if isinstance(findings, list) else None


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0  # malformed payload - fail open, matches every other guard's policy

    if payload.get("tool_name") != "Write":
        return 0

    tool_input = payload.get("tool_input") or {}
    path = tool_input.get("file_path") or ""
    agent_type = payload.get("agent_type") or ""

    # Scoping half: only the four named reviewer agents are restricted to their own pack path.
    if agent_type in _SCOPED_AGENTS and not _ALLOWED_PATH_RE.search(path):
        _block_scope(agent_type, path)

    # Size-limit half: any Write to a findings-pack-shaped path - scoped agent OR the
    # orchestrator's own call - once the project has opted into large_context_review_split.
    if _ALLOWED_PATH_RE.search(path) and _large_context_split_enabled():
        count = _finding_count(tool_input.get("content") or "")
        if count is not None and count > _MAX_FINDINGS_PER_WRITE:
            _block_size(path, count)

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
