"""check_function_word_attribution() / check_advisory() (scripts/check_artifacts.py):
ADVISORY ONLY, never wired into check() or the close gate. A live report (2026-09-22) found
a Confluence update saying "Compliance confirmed the mapping is accurate" - true of the
compliance-reviewer agent's own output, but readable as the real Compliance department
having said it. Kept advisory rather than a hard gate because "Compliance reviewed this
scenario historically" is a legitimate sentence about the real department this pattern
cannot distinguish from the misattribution with full confidence."""

from __future__ import annotations

from pathlib import Path

from scripts.check_artifacts import check, check_advisory, check_function_word_attribution


def test_bare_function_word_as_subject_flagged():
    findings = check_function_word_attribution(
        "Compliance confirmed the mapping is accurate.\n", Path("review-pass-1.md")
    )
    assert len(findings) == 1
    assert "FUNCTION-WORD-UNMARKED" in findings[0]
    assert "Compliance confirmed" in findings[0]


def test_marked_line_is_not_flagged():
    text = "🤖 Layla, compliance-reviewer (Virtual Surveillance IT), confirmed the mapping.\n"
    assert check_function_word_attribution(text, Path("x.md")) == []


def test_marker_elsewhere_in_text_does_not_exempt_an_unmarked_line():
    text = "🤖 Morgan opened the engagement.\n\nCompliance confirmed the mapping is accurate.\n"
    findings = check_function_word_attribution(text, Path("x.md"))
    assert len(findings) == 1


def test_bare_mention_with_no_judgement_verb_is_not_flagged():
    # "Compliance" as an object/modifier, not the subject of an action - the common,
    # legitimate shape ("escalate to Compliance", "a Compliance obligation").
    text = "Escalate to Compliance for sign-off; this is a Compliance requirement.\n"
    assert check_function_word_attribution(text, Path("x.md")) == []


def test_legal_risk_audit_also_covered():
    for word in ("Legal", "Risk", "Audit"):
        findings = check_function_word_attribution(f"{word} reviewed the change.\n", Path("x.md"))
        assert len(findings) == 1, word


def test_advisory_never_appears_in_the_gating_check(tmp_path):
    art = tmp_path / "artifacts"
    art.mkdir()
    (art / "START-HERE.md").write_text(
        "# START HERE\n\n| **Status** | ⏳ IN PROGRESS |\n\n- `review-pass-1.md` - x\n",
        encoding="utf-8",
    )
    (art / "START-HERE.html").write_text("x", encoding="utf-8")
    (art / "review-pass-1.md").write_text(
        "Compliance confirmed the mapping is accurate.\n", encoding="utf-8"
    )
    (art / "review-pass-1.html").write_text("x", encoding="utf-8")

    assert check(art) == []  # the gate stays clean - this is the whole point
    assert any("FUNCTION-WORD-UNMARKED" in f for f in check_advisory(art))


def test_advisory_scans_txt_files_too(tmp_path):
    art = tmp_path / "artifacts"
    art.mkdir()
    (art / "interim-update-1.txt").write_text(
        "Compliance approved this approach.\n", encoding="utf-8"
    )
    assert any("FUNCTION-WORD-UNMARKED" in f for f in check_advisory(art))


def test_advisory_respects_archive_exclusion(tmp_path):
    art = tmp_path / "artifacts"
    nested = art / "old-pack"
    nested.mkdir(parents=True)
    (nested / ".archive").write_text("archived\n", encoding="utf-8")
    (nested / "review-pass-1.md").write_text(
        "Compliance confirmed the mapping is accurate.\n", encoding="utf-8"
    )
    assert check_advisory(art) == []
