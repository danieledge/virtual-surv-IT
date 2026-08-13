#!/usr/bin/env python3
"""
PreToolUse guard: scope the four findings-pack agents' Write+Edit grant to their OWN pack
file, and (opt-in) mechanically cap how many findings one Write to a findings-pack path may
carry.

2026-08-03 token-usage audit (P4): `code-reviewer`, `compliance-reviewer`, `model-validator`
and `performance-reviewer` held no Write, so their full structured findings-pack JSON had to
transit the orchestrator's context TWICE - once as the Task tool's return value, once again
when the orchestrator re-emitted it as a Write tool call to persist the pack. Granting these
four agents `Write` lets each write its own pack directly, halving that cost.

The risk that grant opens: a Write tool with no path restriction, however it got there, is a
much bigger blast radius than "author one JSON file". This guard closes that gap the same way
the raw-data and code-execution guards close theirs - mechanically, not by trusting the
agent's own instructions to stay in scope.

How SCOPING is enforced: Claude Code's PreToolUse payload includes `agent_type` whenever the
tool call originates from a subagent (absent for the orchestrator's own calls) - see
docs/adr/ADR-002-safety-hook-threat-model.md for the guard family's threat model. This half of
the guard fires ONLY when `agent_type` is one of the four scoped names AND `tool_name` is
`Write` OR `Edit`, and blocks unless the target path matches the findings-pack shape
(`artifacts/<slug>/data/findings-*.jsonl`, or `artifacts/data/findings-*.jsonl` for a flat pack).
Every other Write/Edit call - the orchestrator's own, a build agent's, anything without a
matching `agent_type` - passes through this half untouched; it has no opinion about them.

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
`docs/team-operating-guide.md`'s orchestration-discipline bullet tells Morgan to build a large
merged pack incrementally (Write a small first batch, then Edit to append the rest) - but that
is PROSE guidance, easy to skip under pressure. This second half of the guard makes it
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
turning "she might remember the heuristic" into "she is told, mechanically, every time." As
shipped 2026-08-05, the size cap applied to `Write` ONLY, deliberately - `Edit` was the escape
hatch past it. **Superseded 2026-08-07** (see that dated note below): the JSONL migration
removed the reason for that exemption, and the cap now applies to both.

2026-08-06 (live freedom-dashboard diagnostic, --target-path): the size cap did its job - it
blocked an oversized Write - but the FOUR SCOPED AGENTS had no Edit grant to chunk past it the
way Morgan can, so a `performance-reviewer` pass that hit the cap improvised by silently
dropping three lower-confidence findings from its own pack (recovered only because it happened
to document what it dropped, and Morgan happened to read that and re-add them by hand - a
lucky, not guaranteed, save). Fix: grant the same four agents `Edit`, scoped by this guard to
the EXACT SAME path pattern `Write` already allows - not a broader capability, the same narrow
one extended to a second tool.

2026-08-07 (JSONL format migration): the pack moved from one JSON object per file to JSONL -
an envelope line plus one line per finding (`scripts/findings_pack_io.py`) - specifically so
appending is a genuine append (new lines only, nothing existing ever touched) rather than a
delicate patch to a JSON array's brackets/commas. That also removes the reason `Edit` was
exempt from the size cap: it used to be the deliberate "escape hatch" past a Write that could
no longer safely be split further; now every append (Write's initial batch, or an Edit adding
more lines later) is symmetric - just more independently-valid lines - so the cap now applies
to BOTH Write and Edit, closing a real gap the old exemption left open (a single Edit call
could otherwise still smuggle in an unbounded number of new finding lines in one generation).

Protocol: read the PreToolUse JSON on stdin; exit 2 to block (stderr fed back to the model);
exit 0 to allow. Fails CLOSED on an unexpected crash (a scoping guard that silently opened would
be a silent safety regression, same policy as guard-raw-data.py / guard-code-execution.py /
guard-consent-writes.py) but fails OPEN on a malformed/unparseable payload, OR on unreadable/
unparseable team-preferences.json, OR on Write/Edit content that doesn't parse as JSONL findings
lines (this guard validates neither pack schema nor JSON well-formedness - that is
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

# Matches .../artifacts/<slug>/data/findings-<anything>.jsonl (workspace) or
# .../artifacts/data/findings-<anything>.jsonl (flat pack), absolute or relative, either
# slash style. Anchored at the end so a path that merely CONTAINS this shape somewhere in
# the middle (not as its actual target) does not slip through.
_ALLOWED_PATH_RE = re.compile(
    r"(^|[/\\])artifacts[/\\](?:[^/\\]+[/\\])?data[/\\]findings-[^/\\]+\.jsonl$"
)

# Keep in sync with docs/team-operating-guide.md's orchestration-discipline bullet ("roughly
# >8 findings to merge... build the pack incrementally").
_MAX_FINDINGS_PER_WRITE = 8


def _block_scope(agent_type: str, path: str) -> None:
    sys.stderr.write(
        f"Blocked (findings-pack write scope, agent={agent_type}): this agent's Write grant "
        "exists ONLY to author its own findings-pack JSONL at "
        "artifacts/<slug>/data/findings-*.jsonl (or artifacts/data/findings-*.jsonl for a flat "
        f"pack) - attempted target: {path!r}. Everything else - the rendered report, any other "
        "file - stays with the orchestrator or a build agent.\n"
    )
    sys.exit(2)


def _block_size(path: str, count: int) -> None:
    sys.stderr.write(
        f"Blocked (findings-pack size limit, large_context_review_split is on): this call to "
        f"{path!r} would add {count} finding(s) at once - {_MAX_FINDINGS_PER_WRITE} is the "
        "limit per call, because a large-enough single generation is what times out on a "
        f"corporate proxy, not the number of calls. Add findings roughly "
        f"{_MAX_FINDINGS_PER_WRITE} at a time instead: the envelope line plus the first batch "
        "on the initial Write, then append the rest as more finding-lines via Edit, a batch of "
        "4-6 at a time (docs/team-operating-guide.md's orchestration-discipline bullet).\n"
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


def _count_json_lines(text: str) -> int:
    """How many lines of `text` parse as standalone JSON values - a permissive count (blank
    lines, and any line that isn't valid JSON yet, are skipped rather than erroring: this
    guard's job is counting, not validating pack/finding shape - that is
    scripts.validate_findings's job at close)."""
    count = 0
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            json.loads(line)
        except ValueError:
            continue
        count += 1
    return count


def _new_finding_count(tool_name: str, tool_input: dict) -> "int | None":
    """How many NEW finding lines this specific Write or Edit call introduces. None means
    nothing countable yet (not this guard's job to act on).

    Write always carries the FULL new file content, envelope line included - total JSON
    lines minus one (the envelope) is the finding count. Edit only carries the changed
    snippet (old_string -> new_string); the model's own append pattern is "match the last
    existing line, insert new finding lines after it", so the finding-line DELTA between
    new_string and old_string is exactly how many new findings this Edit adds - no envelope
    adjustment, since a well-formed append never touches line 1."""
    if tool_name == "Write":
        content = tool_input.get("content") or ""
        if not content.strip():
            return None
        return max(0, _count_json_lines(content) - 1)
    if tool_name == "Edit":
        new = tool_input.get("new_string") or ""
        if not new.strip():
            return None
        old = tool_input.get("old_string") or ""
        return max(0, _count_json_lines(new) - _count_json_lines(old))
    return None


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0  # malformed payload - fail open, matches every other guard's policy

    tool_name = payload.get("tool_name")
    if tool_name not in ("Write", "Edit"):
        return 0

    tool_input = payload.get("tool_input") or {}
    path = tool_input.get("file_path") or ""
    agent_type = payload.get("agent_type") or ""

    # Scoping half: only the four named reviewer agents are restricted to their own pack
    # path - applies to both Write and Edit, the same narrow grant extended to a second tool.
    if agent_type in _SCOPED_AGENTS and not _ALLOWED_PATH_RE.search(path):
        _block_scope(agent_type, path)

    # Size-limit half: applies to BOTH Write and Edit now (2026-08-07 JSONL migration - see
    # module docstring for why Edit no longer needs a blanket exemption). Any call to a
    # findings-pack-shaped path - scoped agent OR the orchestrator's own - once the project
    # has opted into large_context_review_split.
    if _ALLOWED_PATH_RE.search(path) and _large_context_split_enabled():
        count = _new_finding_count(tool_name, tool_input)
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
