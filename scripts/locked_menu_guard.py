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
_ORIGIN_LABELS = {"AI-assisted / vibe-coded", "Mixed", "Hand-written"}
_TARGET_LABELS = {
    "Uncommitted changes",
    "Branch vs main",
    "Whole working directory",
    "A file or folder I'll name",
}
# The ONE permitted variation (target-menu.md): a non-git working directory drops the
# two diff-shaped options.
_TARGET_NON_GIT_LABELS = {"Whole working directory", "A file or folder I'll name"}
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


_RECOMMENDED_SUFFIX = " (Recommended)"


def _strip_recommended(label: str) -> str:
    """The AskUserQuestion tool's OWN guidance is to mark a recommended option by
    appending exactly this suffix to its label - a canonical option carrying that
    marker is still the same canonical option, not an invented one. Live report,
    2026-08-04: 'Quick (Recommended)' on the locked Depth question was flagged as
    drift, even though adding the marker is the tool's own recommended practice."""
    return label[: -len(_RECOMMENDED_SUFFIX)] if label.endswith(_RECOMMENDED_SUFFIX) else label


def _labels(q: dict) -> set:
    opts = q.get("options")
    if not isinstance(opts, list):
        return set()
    return {
        _strip_recommended(o.get("label")) for o in opts if isinstance(o, dict) and o.get("label")
    }


def _header(q: dict) -> str:
    return q.get("header") if isinstance(q, dict) else None


def check_review_menu(questions: list) -> str | None:
    """Fires only once a 'Depth' header is present - the reference file's own signature
    for this locked construction. None = not this menu, or looks correct."""
    if not any(_header(q) == "Depth" for q in questions):
        return None
    headers = [_header(q) for q in questions]
    if headers != ["Depth", "Performance", "Fix-cycle", "Origin"]:
        return (
            "review-menu drift: the locked construction is exactly four questions "
            "headed Depth, Performance, Fix-cycle, Origin, in that order, in ONE call "
            f"- got headers {headers!r} (review-menu.md - do not merge, drop or "
            "reorder them; Origin joined the locked set 2026-08-17)"
        )
    by_header = dict(zip(headers, questions))
    for header, expected in (
        ("Depth", _DEPTH_LABELS),
        ("Performance", _PERF_LABELS),
        ("Fix-cycle", _FIXCYCLE_LABELS),
        ("Origin", _ORIGIN_LABELS),
    ):
        q = by_header[header]
        if q.get("multiSelect"):
            return (
                f"review-menu drift: '{header}' must be multiSelect: false (each of the "
                "four is a single-select question - review-menu.md)"
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
        # RETIRED question (2026-08-17 user decision): every real engagement chose the
        # Consolidated Delivery Report, so packaging is a stated default in the brief,
        # never a question - re-asking it is drift, whatever its options say.
        return (
            "artifact-menu drift: the packaging question ('Artifacts') is RETIRED - "
            "packaging defaults to the Consolidated Delivery Report, stated in the "
            "brief and adjustable at the go-ahead gate; ask ONLY the stage-2 group "
            "questions, and only when the user asked for standalone artifacts "
            "(artifact-menu.md, 2026-08-17)"
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


def check_target_menu(questions: list) -> str | None:
    """Locked review-target construction (2026-08-17 user decision: 'it changes nearly
    every time in some way' - same drift class the locked review menu closed). Fires on
    a 'Target' header: single-select, exactly the canonical labels - the full set, or
    the two-option non-git subset, nothing else (target-menu.md)."""
    for q in questions:
        if _header(q) != "Target":
            continue
        if q.get("multiSelect"):
            return (
                "target-menu drift: 'Target' must be multiSelect: false - one target "
                "per review (target-menu.md)"
            )
        labels = _labels(q)
        if labels not in (_TARGET_LABELS, _TARGET_NON_GIT_LABELS):
            return (
                f"target-menu drift: 'Target' options are {sorted(labels)!r}, expected "
                f"exactly {sorted(_TARGET_LABELS)!r} (or, in a non-git directory, "
                f"{sorted(_TARGET_NON_GIT_LABELS)!r}) - do not reword, add or drop "
                "options; exotic targets go through the automatic 'Other' "
                "(target-menu.md)"
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
        problem = (
            check_review_menu(questions)
            or check_artifact_menu(questions)
            or check_target_menu(questions)
        )
    except Exception:
        return 0  # a guard that can't be sure must not block a legitimate question
    if problem:
        print(problem, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
