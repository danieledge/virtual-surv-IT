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

2026-09-12 audit, two changes:
  * W-13 - the canonical label sets are PARSED from the reference `.md` files at hook start
    instead of being a second hand-synced copy inside the guard. Editing the spec now
    changes what the guard accepts, in the same commit, which is the drift this closes; the
    literals remain as a complete fallback for a layout that ships no references or a file
    caught mid-edit.
  * W-28 - the header is the guard's recognition signature, so renaming it used to walk a
    divergent (or retired) locked menu straight past every check. A question whose OPTION
    SET is exactly a locked set, under a header that is not that set's own, is now blocked
    too. Exact-set matching, minimum three options: a near-match or a Yes/No is where false
    positives live, and this guard blocks rather than advises.

Wire via scripts/apply-locked-menu-guard.sh (HUMAN-run - hook/config edits are human-only,
ADR-002 rec 5) into `.claude/settings.json` + `hooks/hooks.json` -> hooks.PreToolUse,
matcher "AskUserQuestion".
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------- canonical label sets
#
# W-13 (2026-09-12 audit): these used to be the ONLY copy, hand-synced with the reference
# files the skill actually tells the model to reproduce. That pairing has already drifted
# once in practice (Origin joined the locked review menu on 2026-08-17 and the guard's own
# comment records catching up late), and the failure mode is the worst kind: a correctly
# formed question under the CURRENT spec gets hard-blocked, with no retry hint, because the
# guard is enforcing last month's spec.
#
# So the sets are now PARSED from the same `.md` files the prose cites, at hook start, and
# these literals are the fallback. Parsing can fail for perfectly ordinary reasons - a
# plugin layout that does not ship the references, a reference file mid-edit - and a guard
# that cannot read the spec must fall back to a known-good set rather than block everything
# or nothing. The fallback is therefore kept complete and correct, not a stub.
_FALLBACK_DEPTH_LABELS = {"Quick", "Deep", "Audit", "None"}
_FALLBACK_PERF_LABELS = {"Yes", "No"}
_FALLBACK_FIXCYCLE_LABELS = {"Report only", "Apply fixes", "Fix → re-review loop"}
_FALLBACK_ORIGIN_LABELS = {"AI-assisted / vibe-coded", "Mixed", "Hand-written"}
_FALLBACK_TARGET_LABELS = (
    "Uncommitted changes",
    "Branch vs main",
    "Whole working directory",
    "A file or folder I'll name",
)
_FALLBACK_STAGE2_CANON = {
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
_STAGE1_LABELS = {"Consolidated Delivery Report", "Separate artifacts", "Both"}

_REFERENCE_SUBPATH = Path(".claude") / "skills" / "engage" / "references"


def _references_dir() -> Path | None:
    """Where the locked-menu reference files live, found by walking up from this file.

    Up from `__file__` rather than from the cwd: this guard runs against whatever project
    the session is in, but the spec it enforces belongs to the plugin/repo the guard itself
    ships in. Covers both the live copy (scripts/) and the staged one
    (scripts/staged_hooks/), because the parents walk covers both depths."""
    for anc in Path(__file__).resolve().parents:
        candidate = anc / _REFERENCE_SUBPATH
        if (candidate / "review-menu.md").is_file():
            return candidate
    return None


_BOLD_ROW = re.compile(r"^\|\s*\*\*(?P<label>[^*|]+?)\*\*\s*\|")


def _table_labels_after(lines: list, start: int) -> list:
    """Labels from the first markdown table that follows `start`, in document order.

    The reference tables are `| **Label** | description |`, so the bold first cell is the
    label. Reading stops at the blank line after the table so a later table cannot bleed
    into this one."""
    labels: list = []
    seen_table = False
    for line in lines[start + 1 :]:
        match = _BOLD_ROW.match(line)
        if match:
            seen_table = True
            labels.append(match.group("label").strip())
            continue
        if seen_table and not line.strip().startswith("|"):
            break
    return labels


def _parse_review_menu(path: Path) -> dict:
    """{header: [labels]} for the four locked review questions, in document order.

    Headers come from the file's own "**Headers:**" line (backticked names, in order), so
    adding a fifth question to the spec is picked up here rather than needing a guard
    edit."""
    lines = path.read_text(encoding="utf-8").splitlines()
    headers: list = []
    for line in lines:
        if "**Headers:**" in line:
            headers = re.findall(r"`([^`]+)`", line)
            break
    if not headers:
        raise ValueError("review-menu.md: no **Headers:** line")
    out: dict = {}
    for index, header in enumerate(headers, start=1):
        marker = f"**Q{index} - "
        pos = next((i for i, line in enumerate(lines) if line.startswith(marker)), None)
        if pos is None:
            raise ValueError(f"review-menu.md: no Q{index} block for header {header!r}")
        labels = _table_labels_after(lines, pos)
        if not labels:
            raise ValueError(f"review-menu.md: no option table under Q{index}")
        out[header] = labels
    return out


def _parse_target_menu(path: Path) -> list:
    """The full Target option list, in document order."""
    lines = path.read_text(encoding="utf-8").splitlines()
    pos = next((i for i, line in enumerate(lines) if "header `Target`" in line), None)
    if pos is None:
        raise ValueError("target-menu.md: no `Target` question")
    labels = _table_labels_after(lines, pos)
    if len(labels) < 3:
        raise ValueError("target-menu.md: option table too short to be the locked menu")
    return labels


def _parse_artifact_menu(path: Path) -> dict:
    """{group header: {labels}} for the stage-2 grouped multi-selects.

    Their spec is a bullet list, not a table: ``- header `Spec docs`: A · B · C``."""
    out: dict = {}
    pattern = re.compile(r"^-\s*header\s*`(?P<header>[^`]+)`:\s*(?P<labels>.+?)\s*$")
    for line in path.read_text(encoding="utf-8").splitlines():
        match = pattern.match(line)
        if not match:
            continue
        labels = {part.strip() for part in match.group("labels").split("·") if part.strip()}
        if labels:
            out[match.group("header")] = labels
    if not out:
        raise ValueError("artifact-menu.md: no stage-2 group bullets")
    return out


def _load_canonical() -> dict:
    """The canonical sets for this run: parsed from the reference docs, else the fallback.

    Returns a `source` field purely so the behaviour is testable in both directions - a
    guard silently running on stale literals is the failure W-13 is about."""
    parsed = {
        "source": "fallback",
        "review": {
            "headers": ["Depth", "Performance", "Fix-cycle", "Origin"],
            "labels": {
                "Depth": set(_FALLBACK_DEPTH_LABELS),
                "Performance": set(_FALLBACK_PERF_LABELS),
                "Fix-cycle": set(_FALLBACK_FIXCYCLE_LABELS),
                "Origin": set(_FALLBACK_ORIGIN_LABELS),
            },
        },
        "target": set(_FALLBACK_TARGET_LABELS),
        # target-menu.md's ONE permitted variation: in a non-git directory the two
        # diff-shaped options are meaningless, so the menu is the LAST TWO only. Derived
        # from the ordered list rather than listed separately, so it cannot drift from it.
        "target_non_git": set(_FALLBACK_TARGET_LABELS[2:]),
        "stage2": {k: set(v) for k, v in _FALLBACK_STAGE2_CANON.items()},
    }
    refs = _references_dir()
    if refs is None:
        return parsed
    try:
        review = _parse_review_menu(refs / "review-menu.md")
        target = _parse_target_menu(refs / "target-menu.md")
        stage2 = _parse_artifact_menu(refs / "artifact-menu.md")
    except Exception:
        return parsed  # unreadable or reshaped spec: keep the known-good literals
    return {
        "source": "parsed",
        "review": {
            "headers": list(review.keys()),
            "labels": {h: set(v) for h, v in review.items()},
        },
        "target": set(target),
        "target_non_git": set(target[2:]),
        "stage2": stage2,
    }


CANONICAL = _load_canonical()


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
    spec = CANONICAL["review"]
    canonical_headers = spec["headers"]
    if not any(_header(q) == canonical_headers[0] for q in questions):
        return None
    headers = [_header(q) for q in questions]
    if headers != canonical_headers:
        return (
            f"review-menu drift: the locked construction is exactly {len(canonical_headers)} "
            f"questions headed {', '.join(canonical_headers)}, in that order, in ONE call "
            f"- got headers {headers!r} (review-menu.md - do not merge, drop or "
            "reorder them; Origin joined the locked set 2026-08-17)"
        )
    by_header = dict(zip(headers, questions))
    for header in canonical_headers:
        expected = spec["labels"][header]
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
        canon = CANONICAL["stage2"].get(header)
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
        full = CANONICAL["target"]
        non_git = CANONICAL["target_non_git"]
        if labels not in (full, non_git):
            return (
                f"target-menu drift: 'Target' options are {sorted(labels)!r}, expected "
                f"exactly {sorted(full)!r} (or, in a non-git directory, "
                f"{sorted(non_git)!r}) - do not reword, add or drop "
                "options; exotic targets go through the automatic 'Other' "
                "(target-menu.md)"
            )
    return None


# W-28: the smallest set size worth treating as a recognisable menu SHAPE. A two-option
# Yes/No is the whole vocabulary of ordinary questions, so matching on it would block
# half the team's legitimate asks; three distinct labels matching a locked set exactly is
# already a deliberate reproduction, not a coincidence.
_SHAPE_MIN_OPTIONS = 3


def _shape_registry() -> dict:
    """{canonical header: label set} for every locked shape worth recognising by options.

    The Performance question is deliberately absent: its options are Yes/No."""
    registry = {
        header: labels
        for header, labels in CANONICAL["review"]["labels"].items()
        if len(labels) >= _SHAPE_MIN_OPTIONS
    }
    registry["Target"] = CANONICAL["target"]
    registry["Artifacts"] = _STAGE1_LABELS
    registry.update(CANONICAL["stage2"])
    return registry


def check_menu_shape_reuse(questions: list) -> str | None:
    """W-28: a locked menu rebuilt under a DIFFERENT header is still the locked menu.

    The header checks above are the guard's recognition signature, which means renaming
    the header is all it takes to walk a divergent - or a retired - locked menu straight
    past them. A question whose option set IS a locked set, under a header that is not
    that set's own, is a reconstruction: block it and name the menu it belongs to.

    Deliberately exact-match only, and only on sets of `_SHAPE_MIN_OPTIONS` or more. A
    near-match is where false positives live, and this guard blocks rather than advises."""
    registry = _shape_registry()
    for q in questions:
        header = _header(q)
        labels = _labels(q)
        if len(labels) < _SHAPE_MIN_OPTIONS:
            continue
        for canonical_header, canonical_labels in registry.items():
            if labels == canonical_labels and header != canonical_header:
                return (
                    f"locked-menu drift: the question headed {header!r} carries exactly the "
                    f"locked {canonical_header!r} option set ({sorted(labels)!r}) under a "
                    "different header. Ask the locked menu as specified, with its own header "
                    "(engage/references/), or ask a genuinely different question - renaming "
                    "the header does not make it a new menu."
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
            or check_menu_shape_reuse(questions)
        )
    except Exception:
        return 0  # a guard that can't be sure must not block a legitimate question
    if problem:
        print(problem, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
