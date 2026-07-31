#!/usr/bin/env python3
"""PreToolUse guard on AskUserQuestion: catches drift in the team's two LOCKED menus
before the malformed question ever reaches the user (audit finding #7, 2026-07-30).

Two locked constructions exist specifically because a loose reproduction has already
drifted in practice - both reference files name the incident:
  - review-menu.md: "a loose version once offered 'Quick and Deep' as a multi-select -
    illogical, Deep already includes Quick" (merging two locked single-selects).
  - artifact-menu.md: caps every question at 4 options precisely so the model is never
    tempted to build one giant list instead of the two-stage construction.

Both are "read this file and reproduce it exactly" today - purely prose enforcement, no
backstop. This is a NARROW, high-confidence guard, not a full menu validator: it only
checks the specific failure SHAPES the reference docs themselves warn about (a merged
question, wrong multiSelect, an invented option), and only once it has recognised the
call as an attempt at one of these two menus (via a near-unique header). Anything it
doesn't recognise - which is most AskUserQuestion calls, including every other locked
and unlocked menu in the team - passes through untouched. Blocking (exit 2) rather than
advisory: a malformed locked menu reaching the user IS the defect the incident was about,
so catching it before the call fires is strictly better than feedback after.

Wire via scripts/apply-locked-menu-guard.sh (HUMAN-run - hook/config edits are human-only,
ADR-002 rec 5) into `.claude/settings.json` + `hooks/hooks.json` -> hooks.PreToolUse,
matcher "AskUserQuestion".
"""

from __future__ import annotations

import json
import sys

_DEPTH_LABELS = {"Quick", "Deep", "Audit", "None"}
_PERF_LABELS = {"Yes", "No"}
_FIXCYCLE_LABELS = {"Report only", "Apply fixes", "Fix → re-review loop"}
_STAGE1_LABELS = {"Consolidated Delivery Report", "Separate artifacts", "Both"}
_STAGE2_CANON = {
    "Spec docs": {"Engagement Brief", "BRD", "FSD", "RTM"},
    "Reviews": {
        "Code & Compliance Review",
        "Performance Review",
        "Model Validation Report",
        "ADRs",
    },
    "Handover": {
        "Developer Handover",
        "QA Handover",
        "Ops Runbook + Release Notes",
        "Change Request",
    },
}


def _labels(q: dict) -> set:
    opts = q.get("options")
    if not isinstance(opts, list):
        return set()
    return {o.get("label") for o in opts if isinstance(o, dict) and o.get("label")}


def _header(q: dict) -> str:
    return q.get("header") if isinstance(q, dict) else None


def check_review_menu(questions: list) -> str | None:
    """Fires only once a 'Depth' header is present - the reference file's own signature
    for this locked construction. None = not this menu, or looks correct."""
    if not any(_header(q) == "Depth" for q in questions):
        return None
    headers = [_header(q) for q in questions]
    if headers != ["Depth", "Performance", "Fix-cycle"]:
        return (
            "review-menu drift: the locked construction is exactly three questions "
            "headed Depth, Performance, Fix-cycle, in that order, in ONE call - got "
            f"headers {headers!r} (review-menu.md - do not merge or reorder them)"
        )
    by_header = dict(zip(headers, questions))
    for header, expected in (
        ("Depth", _DEPTH_LABELS),
        ("Performance", _PERF_LABELS),
        ("Fix-cycle", _FIXCYCLE_LABELS),
    ):
        q = by_header[header]
        if q.get("multiSelect"):
            return (
                f"review-menu drift: '{header}' must be multiSelect: false (each of the "
                "three is a single-select question - review-menu.md)"
            )
        if _labels(q) != expected:
            return (
                f"review-menu drift: '{header}' options are {sorted(_labels(q))!r}, "
                f"expected exactly {sorted(expected)!r} (review-menu.md - do not reword, "
                "merge or drop an option)"
            )
    return None


def check_artifact_menu(questions: list) -> str | None:
    """Two independent signatures: a lone 'Artifacts' question (stage 1) and any of the
    three stage-2 group headers. Stage 2 groups are individually optional ('skip any
    group irrelevant to the engagement') - only whichever groups ARE present are checked,
    never a requirement that all three appear."""
    stage1 = next((q for q in questions if _header(q) == "Artifacts"), None)
    if stage1 is not None:
        if stage1.get("multiSelect"):
            return "artifact-menu drift: stage 1 ('Artifacts') must be multiSelect: false (artifact-menu.md)"
        if _labels(stage1) != _STAGE1_LABELS:
            return (
                f"artifact-menu drift: stage 1 options are {sorted(_labels(stage1))!r}, "
                f"expected exactly {sorted(_STAGE1_LABELS)!r} (artifact-menu.md)"
            )
    for q in questions:
        header = _header(q)
        canon = _STAGE2_CANON.get(header)
        if canon is None:
            continue
        if not q.get("multiSelect"):
            return (
                f"artifact-menu drift: stage-2 group '{header}' must be multiSelect: true "
                "(these are grouped multi-selects, not single-choice - artifact-menu.md)"
            )
        invented = _labels(q) - canon
        if invented:
            return (
                f"artifact-menu drift: stage-2 group '{header}' has option(s) not in the "
                f"canonical list ({sorted(invented)!r}) - rarer templates go through each "
                "question's automatic 'Other', not an invented option (artifact-menu.md)"
            )
    return None


def main() -> int:
    try:
        data = json.loads(sys.stdin.read() or "{}")
    except Exception:
        return 0
    if data.get("tool_name") != "AskUserQuestion":
        return 0
    questions = (data.get("tool_input") or {}).get("questions")
    if not isinstance(questions, list) or not questions:
        return 0
    questions = [q for q in questions if isinstance(q, dict)]
    try:
        problem = check_review_menu(questions) or check_artifact_menu(questions)
    except Exception:
        return 0  # a guard that can't be sure must not block a legitimate question
    if problem:
        print(problem, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
