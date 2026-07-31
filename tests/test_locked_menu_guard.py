"""scripts/locked_menu_guard.py: a PreToolUse guard on AskUserQuestion catching drift in
the team's two LOCKED menus (review-menu.md, artifact-menu.md) before a malformed
reproduction reaches the user (audit finding #7, 2026-07-30). Both reference files name a
past drift incident as the reason they're locked - this closes the "read this file and
copy it exactly" gap with an actual mechanical check, narrow enough not to touch any
other AskUserQuestion call in the team."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
HOOK = REPO_ROOT / "scripts" / "staged_hooks" / "locked_menu_guard.py"
LIVE_HOOK = REPO_ROOT / "scripts" / "locked_menu_guard.py"


def _run(questions: list) -> subprocess.CompletedProcess:
    payload = {"tool_name": "AskUserQuestion", "tool_input": {"questions": questions}}
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=30,
    )


def _q(header, options, multi=False):
    return {
        "question": f"{header}?",
        "header": header,
        "multiSelect": multi,
        "options": [{"label": lbl, "description": lbl} for lbl in options],
    }


VALID_REVIEW_MENU = [
    _q("Depth", ["Quick", "Deep", "Audit", "None"]),
    _q("Performance", ["Yes", "No"]),
    _q("Fix-cycle", ["Report only", "Apply fixes", "Fix → re-review loop"]),
]

VALID_STAGE1 = [_q("Artifacts", ["Consolidated Delivery Report", "Separate artifacts", "Both"])]

VALID_STAGE2 = [
    _q("Spec docs", ["Engagement Brief", "BRD"], multi=True),
    _q("Reviews", ["Code & Compliance Review"], multi=True),
]


# ------------------------------------------------------------------ pass-through cases


def test_unrelated_question_passes_through(tmp_path):
    proc = _run([_q("Approach", ["A", "B"])])
    assert proc.returncode == 0
    assert proc.stderr == ""


def test_non_ask_user_question_tool_ignored():
    payload = {"tool_name": "Bash", "tool_input": {}}
    proc = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0


def test_garbage_stdin_never_crashes():
    proc = subprocess.run(
        [sys.executable, str(HOOK)], input="{not json", capture_output=True, text=True, timeout=30
    )
    assert proc.returncode == 0


def test_empty_questions_passes():
    proc = _run([])
    assert proc.returncode == 0


# ------------------------------------------------------------------ review-menu: valid


def test_correct_review_menu_passes():
    proc = _run(VALID_REVIEW_MENU)
    assert proc.returncode == 0
    assert proc.stderr == ""


# ------------------------------------------------------------------ review-menu: drift


def test_merged_quick_and_deep_is_the_named_incident():
    """The exact incident review-menu.md names: 'Quick and Deep' merged into one option
    instead of two separate depth choices."""
    bad = [
        _q("Depth", ["Quick and Deep", "Audit", "None"]),
        _q("Performance", ["Yes", "No"]),
        _q("Fix-cycle", ["Report only", "Apply fixes", "Fix → re-review loop"]),
    ]
    proc = _run(bad)
    assert proc.returncode == 2
    assert "review-menu drift" in proc.stderr


def test_performance_merged_into_depth_as_multiselect_flagged():
    bad = [
        _q("Depth", ["Quick", "Deep", "Audit", "None", "Yes", "No"], multi=True),
    ]
    proc = _run(bad)
    assert proc.returncode == 2


def test_wrong_multiselect_on_depth_flagged():
    bad = [
        _q("Depth", ["Quick", "Deep", "Audit", "None"], multi=True),
        _q("Performance", ["Yes", "No"]),
        _q("Fix-cycle", ["Report only", "Apply fixes", "Fix → re-review loop"]),
    ]
    proc = _run(bad)
    assert proc.returncode == 2
    assert "multiSelect: false" in proc.stderr


def test_reordered_headers_flagged():
    bad = [
        _q("Depth", ["Quick", "Deep", "Audit", "None"]),
        _q("Fix-cycle", ["Report only", "Apply fixes", "Fix → re-review loop"]),
        _q("Performance", ["Yes", "No"]),
    ]
    proc = _run(bad)
    assert proc.returncode == 2


def test_dropped_option_flagged():
    bad = [
        _q("Depth", ["Quick", "Deep", "Audit"]),  # None missing
        _q("Performance", ["Yes", "No"]),
        _q("Fix-cycle", ["Report only", "Apply fixes", "Fix → re-review loop"]),
    ]
    proc = _run(bad)
    assert proc.returncode == 2
    assert "'Depth'" in proc.stderr


def test_reworded_option_flagged():
    bad = [
        _q("Depth", ["Quick", "Deep", "Full Audit", "None"]),  # "Full Audit" != "Audit"
        _q("Performance", ["Yes", "No"]),
        _q("Fix-cycle", ["Report only", "Apply fixes", "Fix → re-review loop"]),
    ]
    proc = _run(bad)
    assert proc.returncode == 2


# ------------------------------------------------------------------ artifact-menu: valid


def test_correct_stage1_passes():
    proc = _run(VALID_STAGE1)
    assert proc.returncode == 0


def test_correct_stage2_passes():
    proc = _run(VALID_STAGE2)
    assert proc.returncode == 0


def test_stage2_partial_group_selection_is_legal():
    """'skip any group irrelevant to the engagement' - only Spec docs present is valid,
    never a requirement that all three groups appear."""
    proc = _run([_q("Spec docs", ["BRD", "FSD"], multi=True)])
    assert proc.returncode == 0


def test_stage2_subset_of_canonical_options_is_legal():
    proc = _run([_q("Reviews", ["Performance Review"], multi=True)])
    assert proc.returncode == 0


# ------------------------------------------------------------------ artifact-menu: drift


def test_stage1_wrong_multiselect_flagged():
    bad = [
        _q("Artifacts", ["Consolidated Delivery Report", "Separate artifacts", "Both"], multi=True)
    ]
    proc = _run(bad)
    assert proc.returncode == 2
    assert "artifact-menu drift" in proc.stderr


def test_stage1_invented_option_flagged():
    bad = [_q("Artifacts", ["Consolidated Delivery Report", "Neither"])]
    proc = _run(bad)
    assert proc.returncode == 2


def test_stage2_single_select_instead_of_multi_flagged():
    """The class of failure this exists for: a grouped multi-select accidentally built
    as single-choice."""
    bad = [_q("Handover", ["Developer Handover", "QA Handover"], multi=False)]
    proc = _run(bad)
    assert proc.returncode == 2
    assert "multiSelect: true" in proc.stderr


def test_stage2_invented_option_flagged():
    bad = [_q("Spec docs", ["BRD", "Vendor Proposal"], multi=True)]
    proc = _run(bad)
    assert proc.returncode == 2
    assert "Vendor Proposal" in proc.stderr


# ------------------------------------------------------------------ staged/live sync


def test_staged_and_live_match_when_installed():
    if not LIVE_HOOK.is_file():
        import pytest

        pytest.skip("live hook not installed in this checkout")
    assert LIVE_HOOK.read_bytes() == HOOK.read_bytes()
