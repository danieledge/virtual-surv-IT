"""
Tests for the mechanical DoD artifact gate (scripts/check_artifacts.py).

The gate asserts the two DoD items CI can never see (artifacts/ is git-ignored):
every .md deliverable has a rendered .html sibling, and the closing
engagement-summary-*.txt email exists once there are deliverables.
"""

from __future__ import annotations

from scripts.check_artifacts import check


def _touch(path, content="x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def test_missing_dir_is_not_a_failure(tmp_path):
    assert check(tmp_path / "artifacts") == []


def test_empty_dir_passes(tmp_path):
    (tmp_path / "artifacts").mkdir()
    assert check(tmp_path / "artifacts") == []


def test_md_without_html_is_flagged(tmp_path):
    art = tmp_path / "artifacts"
    _touch(art / "REVIEW-foo.md")
    _touch(art / "engagement-summary-foo.txt")
    findings = check(art)
    assert len(findings) == 1
    assert "MISSING-HTML" in findings[0]
    assert "REVIEW-foo.md" in findings[0]


def test_missing_summary_email_is_flagged(tmp_path):
    art = tmp_path / "artifacts"
    _touch(art / "delivery-report.md")
    _touch(art / "delivery-report.html")
    findings = check(art)
    assert len(findings) == 1
    assert "MISSING-SUMMARY-EMAIL" in findings[0]


def test_complete_gate_passes(tmp_path):
    art = tmp_path / "artifacts"
    _touch(art / "delivery-report.md")
    _touch(art / "delivery-report.html")
    _touch(art / "engagement-summary-spoofing.txt")
    assert check(art) == []


def test_nested_artifacts_are_checked(tmp_path):
    art = tmp_path / "artifacts"
    _touch(art / "sub" / "spec.md")
    _touch(art / "engagement-summary-x.txt")
    findings = check(art)
    assert len(findings) == 1
    assert "sub" in findings[0]
