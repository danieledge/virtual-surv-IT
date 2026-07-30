#!/usr/bin/env python3
"""PostToolUse feedback on Task completion: the condensed-return budget, mechanised
(audit finding #4, 2026-07-30).

The operating guide states the delegation budget in absolute terms - "a hard budget, not
a nicety... A return over budget is a defect to trim, not something to pass through" - but
nothing measured the actual return; the ~1,500 token / ~30 line ceiling was enforced
purely by wording in the delegation brief. This gives Morgan feedback the moment an
over-budget return lands, the same PostToolUse-feedback pattern post_edit_lint.py already
uses for lint findings (exit 2 + stderr; the call already happened, nothing is blocked).

Token count is estimated (chars / 4, a standard rough proxy for English text - the true
count needs the model's own tokenizer, unavailable to a hook) - the trigger is "clearly,
not marginally, over budget" by design (2x the stated ceiling), so a rough estimate is
good enough and a borderline return is never falsely flagged.

Payload-shape caveat (documented honestly, not glossed over): Claude Code's exact
PostToolUse `tool_response` schema for the Task tool is NOT documented anywhere in this
repo, and this hook was written without a live sample to verify against. It therefore
tries several plausible shapes (a bare string; {content: str}; {content: [{type: text,
text: str}, ...]}; {output}/{result}/{text}) and extracts the first one that yields
non-empty text - anything unrecognized is a silent no-op, never a crash and never a false
report. If this hook is observed to never fire in live use, the extraction shapes below
are the first thing to check against an actual captured payload.

Advisory by design: NOT a safety guard, fails open on every error path, silent outside a
live engagement (dormancy invariant) and on any subagent whose task genuinely needs a
longer return (a completed handover pack summary, for instance) - it nudges once per
over-budget return, it does not block or retry.

Wire via scripts/apply-subagent-budget.sh (HUMAN-run - hook/config edits are human-only,
ADR-002 rec 5) into `.claude/settings.json` + `hooks/hooks.json` -> hooks.PostToolUse,
matcher "Task".
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# ~1,500 tokens / ~30 lines is the STATED budget; the trigger is 2x that (clearly, not
# marginally, over) so a rough char/4 token estimate never falsely flags a borderline return.
_TOKEN_BUDGET = 1500
_LINE_BUDGET = 30
_TOKEN_TRIGGER = _TOKEN_BUDGET * 2
_LINE_TRIGGER = _LINE_BUDGET * 2

_LIVE = ("in_progress", "blocked", "closing")


def _pack_live(pack: Path) -> bool:
    state_file = pack / "engagement-state.json"
    if state_file.is_file():
        try:
            status = json.loads(state_file.read_text(encoding="utf-8")).get("status")
            if status in _LIVE:
                return True
            if status == "closed":
                return False
        except (
            Exception
        ):  # best-effort; unreadable state falls through to the index sniff  # nosec B110
            pass
    try:
        text = (pack / "START-HERE.md").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return any(e in text for e in ("⏳", "⛔", "🔒"))


def _engagement_live(project_root: Path) -> bool:
    artifacts = project_root / "artifacts"
    if not artifacts.is_dir():
        return False
    if _pack_live(artifacts):
        return True
    try:
        for child in artifacts.iterdir():
            if child.is_dir() and _pack_live(child):
                return True
    except OSError:
        pass
    return False


def _extract_text(tool_response) -> str:
    """Best-effort text extraction across several plausible response shapes - see the
    module docstring's payload-shape caveat. Returns "" (never raises) when nothing
    recognizable is found."""
    if isinstance(tool_response, str):
        return tool_response
    if not isinstance(tool_response, dict):
        return ""
    content = tool_response.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and isinstance(block.get("text"), str):
                parts.append(block["text"])
            elif isinstance(block, str):
                parts.append(block)
        if parts:
            return "\n".join(parts)
    for key in ("output", "result", "text"):
        val = tool_response.get(key)
        if isinstance(val, str) and val:
            return val
    return ""


def main() -> int:
    try:
        data = json.loads(sys.stdin.read() or "{}")
    except Exception:
        return 0
    if data.get("tool_name") != "Task":
        return 0
    project_root = Path(data.get("cwd") or ".")
    if not _engagement_live(project_root):
        return 0
    text = _extract_text(data.get("tool_response"))
    if not text:
        return 0
    tokens_est = len(text) // 4
    lines = text.count("\n") + 1
    if tokens_est <= _TOKEN_TRIGGER and lines <= _LINE_TRIGGER:
        return 0
    label = data.get("tool_input", {}).get("description") or "a subagent"
    print(
        f"Subagent return over the condensed-return budget: '{label}' returned "
        f"~{tokens_est} tokens / {lines} lines (budget: ~{_TOKEN_BUDGET} tokens / "
        f"~{_LINE_BUDGET} lines - operating guide, 'Condensed returns'). The artifact "
        "carries the detail; distil this return, or re-brief future delegations to this "
        "agent with a tighter output-format instruction.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
