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


# Origin joined the locked set 2026-08-17 (user request: the was-it-vibe-coded question,
# folded forward from the retired post-gate scope screen into the menu itself).
VALID_REVIEW_MENU = [
    _q("Depth", ["Quick", "Deep", "Audit", "None"]),
    _q("Performance", ["Yes", "No"]),
    _q("Fix-cycle", ["Report only", "Apply fixes", "Fix → re-review loop"]),
    _q("Origin", ["AI-assisted / vibe-coded", "Mixed", "Hand-written"]),
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
        _q("Origin", ["AI-assisted / vibe-coded", "Mixed", "Hand-written"]),
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


def test_any_stage1_packaging_question_is_retired_drift():
    """2026-08-17 user decision: every real engagement chose the Consolidated Delivery
    Report, so packaging is a stated default, never a question - even the previously
    canonical construction now flags."""
    proc = _run(VALID_STAGE1)
    assert proc.returncode == 2
    assert "RETIRED" in proc.stderr


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


# ------------------------------------------- (Recommended) marker (2026-08-04 live report)
# The AskUserQuestion tool's own guidance: "make that the first option in the list and add
# '(Recommended)' at the end of the label" - a canonical option carrying that marker must
# still pass, on both locked menus.


def test_recommended_marker_on_review_menu_option_passes():
    good = [
        _q("Depth", ["Quick (Recommended)", "Deep", "Audit", "None"]),
        _q("Performance", ["Yes", "No"]),
        _q("Fix-cycle", ["Report only", "Apply fixes", "Fix → re-review loop"]),
        _q("Origin", ["AI-assisted / vibe-coded", "Mixed", "Hand-written"]),
    ]
    proc = _run(good)
    assert proc.returncode == 0
    assert proc.stderr == ""


def test_recommended_marker_on_multiple_options_passes():
    good = [
        _q("Depth", ["Quick", "Deep", "Audit", "None"]),
        _q("Performance", ["Yes (Recommended)", "No"]),
        _q("Fix-cycle", ["Report only", "Apply fixes (Recommended)", "Fix → re-review loop"]),
        _q("Origin", ["AI-assisted / vibe-coded", "Mixed", "Hand-written"]),
    ]
    proc = _run(good)
    assert proc.returncode == 0


def test_recommended_marker_does_not_resurrect_the_retired_stage1():
    bad = [
        _q(
            "Artifacts",
            ["Consolidated Delivery Report (Recommended)", "Separate artifacts", "Both"],
        )
    ]
    proc = _run(bad)
    assert proc.returncode == 2
    assert "RETIRED" in proc.stderr


def test_recommended_marker_on_artifact_menu_stage2_passes():
    good = [
        _q("Reviews", ["Code & Compliance Review (Recommended)", "Performance Review"], multi=True)
    ]
    proc = _run(good)
    assert proc.returncode == 0


def test_recommended_marker_does_not_mask_a_genuinely_invented_option():
    """The suffix strip must not become a bypass - a bogus label plus the marker is
    still bogus once the marker is removed."""
    bad = [_q("Artifacts", ["Consolidated Delivery Report", "Neither (Recommended)"])]
    proc = _run(bad)
    assert proc.returncode == 2


# ------------------------------------------------------------------ artifact-menu: drift


def test_stage1_wrong_multiselect_still_drift_via_retirement():
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
    """HARD FAILURE, never a skip - see tests/test_hooks_in_sync.py for why (audit 2026-08-01:
    a skipping sync test hid a live guard that was missing three allow-list entries)."""
    assert LIVE_HOOK.is_file(), f"live hook missing at {LIVE_HOOK} - it is not installed"
    assert LIVE_HOOK.read_bytes() == HOOK.read_bytes(), (
        "staged locked-menu guard not yet applied - run: bash scripts/apply-locked-menu-guard.sh"
    )


def test_legacy_three_question_menu_now_flags_the_missing_origin():
    """The pre-2026-08-17 shape (no Origin) is drift now - the guard names what joined."""
    legacy = [
        _q("Depth", ["Quick", "Deep", "Audit", "None"]),
        _q("Performance", ["Yes", "No"]),
        _q("Fix-cycle", ["Report only", "Apply fixes", "Fix → re-review loop"]),
    ]
    proc = _run(legacy)
    assert proc.returncode == 2
    assert "Origin" in proc.stderr


# --- locked Target menu (2026-08-17 user decision: "it changes nearly every time") ---------

_TARGET_FULL = [
    "Uncommitted changes",
    "Branch vs main",
    "Whole working directory",
    "A file or folder I'll name",
]


def test_target_menu_canonical_full_set_passes():
    r = _run([_q("Target", _TARGET_FULL)])
    assert r.returncode == 0, r.stderr


def test_target_menu_non_git_subset_passes():
    r = _run([_q("Target", ["Whole working directory", "A file or folder I'll name"])])
    assert r.returncode == 0, r.stderr


def test_target_menu_reworded_option_flagged():
    opts = ["Uncommitted changes", "Branch vs main", "Whole codebase", "A file or folder I'll name"]
    r = _run([_q("Target", opts)])
    assert r.returncode == 2
    assert "target-menu drift" in r.stderr


def test_target_menu_dropped_option_flagged():
    r = _run([_q("Target", _TARGET_FULL[:3])])
    assert r.returncode == 2
    assert "target-menu drift" in r.stderr


def test_target_menu_multiselect_flagged():
    r = _run([_q("Target", _TARGET_FULL, multi=True)])
    assert r.returncode == 2
    assert "multiSelect: false" in r.stderr


def test_target_menu_recommended_suffix_is_not_drift():
    opts = ["Uncommitted changes (Recommended)"] + _TARGET_FULL[1:]
    r = _run([_q("Target", opts)])
    assert r.returncode == 0, r.stderr


def test_target_labels_match_the_reference_doc():
    """The guard's canonical set and target-menu.md must name the same options - a
    retier that updates one without the other would block every legitimate ask."""
    doc = (REPO_ROOT / ".claude" / "skills" / "engage" / "references" / "target-menu.md").read_text(
        encoding="utf-8"
    )
    for label in _TARGET_FULL:
        assert f"**{label}**" in doc, f"target-menu.md missing option {label!r}"


# ---------------------------------------------- W-13: canonical sets come from the docs


def _load_guard():
    import importlib.util

    spec = importlib.util.spec_from_file_location("staged_locked_menu_guard", HOOK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_w13_canonical_sets_are_parsed_from_the_reference_docs():
    """W-13: the guard used to enforce a hand-synced copy of the spec, which had already
    drifted once. In a normal checkout it now reads the same files the skill cites."""
    guard = _load_guard()
    assert guard.CANONICAL["source"] == "parsed"
    assert guard.CANONICAL["review"]["headers"] == ["Depth", "Performance", "Fix-cycle", "Origin"]
    assert guard.CANONICAL["review"]["labels"]["Depth"] == {"Quick", "Deep", "Audit", "None"}
    assert guard.CANONICAL["target_non_git"] == {
        "Whole working directory",
        "A file or folder I'll name",
    }
    assert set(guard.CANONICAL["stage2"]) == {"Spec docs", "Reviews", "Handover"}


def test_w13_parsed_sets_agree_with_the_hardcoded_fallback():
    """Both directions of W-13 in one assertion: the parse is right AND the fallback is
    still correct. A fallback that has quietly gone stale is the same defect one layer
    down, and only a comparison catches it."""
    guard = _load_guard()
    labels = guard.CANONICAL["review"]["labels"]
    assert labels["Depth"] == guard._FALLBACK_DEPTH_LABELS
    assert labels["Performance"] == guard._FALLBACK_PERF_LABELS
    assert labels["Fix-cycle"] == guard._FALLBACK_FIXCYCLE_LABELS
    assert labels["Origin"] == guard._FALLBACK_ORIGIN_LABELS
    assert guard.CANONICAL["target"] == set(guard._FALLBACK_TARGET_LABELS)
    assert guard.CANONICAL["stage2"] == guard._FALLBACK_STAGE2_CANON


def test_w13_unreachable_references_fall_back_instead_of_failing(monkeypatch):
    """The other direction: a plugin layout that ships no reference files, or a file
    mid-edit, must leave the guard working on the known-good literals - never blocking
    everything and never blocking nothing."""
    guard = _load_guard()
    monkeypatch.setattr(guard, "_references_dir", lambda: None)
    canonical = guard._load_canonical()
    assert canonical["source"] == "fallback"
    assert canonical["review"]["labels"]["Depth"] == guard._FALLBACK_DEPTH_LABELS


def test_w13_a_malformed_reference_file_falls_back(tmp_path, monkeypatch):
    guard = _load_guard()
    (tmp_path / "review-menu.md").write_text("# nothing useful here\n", encoding="utf-8")
    monkeypatch.setattr(guard, "_references_dir", lambda: tmp_path)
    assert guard._load_canonical()["source"] == "fallback"


def test_w13_a_changed_spec_changes_what_the_guard_accepts(tmp_path, monkeypatch):
    """The point of parsing: the guard follows the spec instead of needing its own edit.
    A reference file with a renamed option makes the OLD wording the drift."""
    guard = _load_guard()
    (tmp_path / "review-menu.md").write_text(
        "- **Headers:** Q1 `Depth`\n"
        '\n**Q1 - "What depth?"  (single-select):**\n'
        "\n| Label | Description |\n|---|---|\n"
        "| **Skim** | shallow |\n| **Deep** | thorough |\n\n",
        encoding="utf-8",
    )
    (tmp_path / "target-menu.md").write_text("broken\n", encoding="utf-8")
    monkeypatch.setattr(guard, "_references_dir", lambda: tmp_path)
    canonical = guard._load_canonical()
    # target-menu.md is unparseable, so the whole load falls back - the sets are one
    # spec, not four independent ones, and a half-parsed spec is worse than the literals.
    assert canonical["source"] == "fallback"

    (tmp_path / "target-menu.md").write_text(
        "**Q - pick one (header `Target`, single-select):**\n"
        "\n| Label | Description |\n|---|---|\n"
        "| **Uncommitted changes** | a |\n| **Branch vs main** | b |\n"
        "| **Whole working directory** | c |\n| **A file or folder I'll name** | d |\n\n",
        encoding="utf-8",
    )
    (tmp_path / "artifact-menu.md").write_text(
        "- header `Spec docs`: BRD · FSD\n", encoding="utf-8"
    )
    canonical = guard._load_canonical()
    assert canonical["source"] == "parsed"
    assert canonical["review"]["labels"]["Depth"] == {"Skim", "Deep"}


# ------------------------------------- W-28: a locked menu rebuilt under another header


def test_w28_locked_depth_options_under_another_header_are_blocked():
    """Renaming the header was all it took to walk a divergent or retired locked menu past
    a guard that recognises menus BY header."""
    proc = _run([_q("Review type", ["Quick", "Deep", "Audit", "None"])])
    assert proc.returncode == 2
    assert "locked 'Depth' option set" in proc.stderr


def test_w28_retired_packaging_menu_under_a_new_header_is_blocked():
    """The packaging question is retired outright; a rename must not resurrect it."""
    proc = _run([_q("Packaging", ["Consolidated Delivery Report", "Separate artifacts", "Both"])])
    assert proc.returncode == 2
    assert "locked 'Artifacts' option set" in proc.stderr


def test_w28_target_options_under_another_header_are_blocked():
    proc = _run(
        [
            _q(
                "Scope",
                [
                    "Uncommitted changes",
                    "Branch vs main",
                    "Whole working directory",
                    "A file or folder I'll name",
                ],
            )
        ]
    )
    assert proc.returncode == 2
    assert "locked 'Target' option set" in proc.stderr


def test_w28_the_menus_under_their_own_headers_still_pass():
    """The other direction, and the one that matters: the shape check must not fire on the
    locked menus asked correctly."""
    assert _run(VALID_REVIEW_MENU).returncode == 0
    assert _run(VALID_STAGE2).returncode == 0
    assert (
        _run(
            [
                _q(
                    "Target",
                    [
                        "Uncommitted changes",
                        "Branch vs main",
                        "Whole working directory",
                        "A file or folder I'll name",
                    ],
                )
            ]
        ).returncode
        == 0
    )


def test_w28_ordinary_questions_are_not_caught_by_the_shape_check():
    """False positives are the risk with a blocking guard. A yes/no, a two-option pick and
    an unrelated three-option question must all pass."""
    assert _run([_q("Proceed", ["Yes", "No"])]).returncode == 0
    assert _run([_q("Env", ["Dev", "Prod"])]).returncode == 0
    assert _run([_q("Format", ["Markdown", "HTML", "DOCX"])]).returncode == 0


def test_w28_a_near_miss_is_not_blocked():
    """Exact-set matching only: a question that merely overlaps a locked set is somebody
    asking something else, and a blocking guard must not guess."""
    assert _run([_q("Review type", ["Quick", "Deep", "Exhaustive"])]).returncode == 0
