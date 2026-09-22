"""interim-status-report-N.md (docs/templates/interim-status-report.md, /status-email
--report, 2026-09-22): the mid-engagement sibling of delivery-report.md. Deliberately needs
NO new check_artifacts.py wiring - it rides entirely on the existing generic per-.md-file
checks (MISSING-HTML, STALE-INDEX, roster/AI-identity), the same way review-pass-N and
qa-cycle-N already do. These tests confirm that ride actually holds, and that the pattern
does not collide with the close-only gates."""

from __future__ import annotations

from scripts.check_artifacts import check

STATUS_OPEN = "⏳ IN PROGRESS"
STATUS_CLOSED = "✅ CLOSED 2026-07-22"


def _touch(path, content="x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _index(art, status=STATUS_OPEN, listed=()):
    rows = "\n".join(f"- `{name}` - purpose" for name in listed)
    _touch(art / "START-HERE.md", f"# START HERE\n\n| **Status** | {status} |\n\n{rows}\n")
    _touch(art / "START-HERE.html")


def test_report_while_open_is_never_final_before_close(tmp_path):
    """The naming choice IS the decoupling from FINAL-BEFORE-CLOSE, same trick as the
    interim-update email uses against SUMMARY-BEFORE-CLOSE."""
    art = tmp_path / "artifacts"
    _touch(art / "interim-status-report-1.md", "# Report\n")
    _touch(art / "interim-status-report-1.html")
    _index(art, status=STATUS_OPEN, listed=["interim-status-report-1.md"])
    assert not any("FINAL-BEFORE-CLOSE" in f for f in check(art))


def test_report_missing_html_sibling_flagged(tmp_path):
    art = tmp_path / "artifacts"
    _touch(art / "interim-status-report-1.md", "# Report\n")
    _index(art, status=STATUS_OPEN, listed=["interim-status-report-1.md"])
    assert any("MISSING-HTML" in f for f in check(art))


def test_report_unlisted_is_stale_index(tmp_path):
    art = tmp_path / "artifacts"
    _touch(art / "interim-status-report-1.md", "# Report\n")
    _touch(art / "interim-status-report-1.html")
    _index(art, status=STATUS_OPEN, listed=[])  # not listed
    assert any("STALE-INDEX" in f for f in check(art))


def test_report_unmarked_persona_flagged(tmp_path):
    art = tmp_path / "artifacts"
    _touch(
        art / "interim-status-report-1.md",
        "# Report\n\nLayla (compliance-reviewer) signed off on this section.\n",
    )
    _touch(art / "interim-status-report-1.html")
    _index(art, status=STATUS_OPEN, listed=["interim-status-report-1.md"])
    assert any("AGENT-UNMARKED" in f for f in check(art))


def test_report_marked_persona_passes(tmp_path):
    art = tmp_path / "artifacts"
    _touch(
        art / "interim-status-report-1.md",
        "# Report\n\n\U0001f916 Layla (compliance-reviewer) reviewed this section.\n",
    )
    _touch(art / "interim-status-report-1.html")
    _index(art, status=STATUS_OPEN, listed=["interim-status-report-1.md"])
    assert check(art) == []


def test_second_report_is_a_normal_interim_artifact_too(tmp_path):
    art = tmp_path / "artifacts"
    for n in (1, 2):
        _touch(art / f"interim-status-report-{n}.md", "# Report\n")
        _touch(art / f"interim-status-report-{n}.html")
    _index(
        art,
        status=STATUS_OPEN,
        listed=["interim-status-report-1.md", "interim-status-report-2.md"],
    )
    assert check(art) == []


def test_report_and_email_coexist_cleanly(tmp_path):
    art = tmp_path / "artifacts"
    _touch(art / "interim-status-report-1.md", "# Report\n")
    _touch(art / "interim-status-report-1.html")
    _touch(
        art / "interim-update-1.txt",
        "From:      \U0001f916 Morgan - PM & Orchestrator, Virtual Surveillance IT\n\n"
        "Hi,\n\nFull status report: interim-status-report-1.html\n\n"
        "\U0001f916 Morgan\nPM & Orchestrator - Virtual Surveillance IT (AI agent)\n",
    )
    _index(
        art,
        status=STATUS_OPEN,
        listed=["interim-status-report-1.md", "interim-update-1.txt"],
    )
    assert check(art) == []
