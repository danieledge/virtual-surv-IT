"""The interim update email (/status-email, scripts/check_artifacts.py): the optional
mid-engagement sibling of the close-only engagement-summary email. Same identity checks
(signed Morgan, 🤖-marked, must be a .txt), but deliberately a DIFFERENT filename
(interim-update-N.txt vs engagement-summary-*.txt) so it never trips SUMMARY-BEFORE-CLOSE
and never satisfies MISSING-SUMMARY-EMAIL - that decoupling is the whole point of the
naming choice, and is what this file's regression tests exist to guard."""

from __future__ import annotations

from scripts.check_artifacts import apply_fixes, check, check_summary_email

STATUS_OPEN = "⏳ IN PROGRESS"
STATUS_BLOCKED = "⛔ BLOCKED - awaiting input"
STATUS_CLOSED = "✅ CLOSED 2026-07-22"

_VALID_INTERIM = (
    "To:        \n"
    "From:      🤖 Morgan - PM & Orchestrator, Virtual Surveillance IT (AI agent, not a human)\n"
    "Date:      22 September 2026\n"
    "Subject:   Progress update - demo (in progress)\n"
    "\n"
    "Hi,\n\nQuick update - still in progress.\n\n"
    "WHERE THINGS STAND\n-------------------\n- Brief written, review under way.\n\n"
    "🤖 Morgan\nPM & Orchestrator - Virtual Surveillance IT (AI agent)\n"
)


def _touch(path, content="x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _index(art, status=STATUS_CLOSED, listed=()):
    rows = "\n".join(f"- `{name}` - purpose" for name in listed)
    _touch(art / "START-HERE.md", f"# START HERE\n\n| **Status** | {status} |\n\n{rows}\n")
    _touch(art / "START-HERE.html")


def test_check_summary_email_interim_kind_points_at_the_right_template():
    findings = check_summary_email(
        "From:      Daniel\n\nno sign-off here\n", "interim-update-1.txt", kind="interim"
    )
    joined = "\n".join(findings)
    assert "interim-update-email.md" in joined
    assert "engagement-summary-email.md" not in joined
    assert "rule 3a" in joined


def test_check_summary_email_close_kind_is_unchanged_by_default():
    findings = check_summary_email("From:      Daniel\n\nno sign-off here\n", "engagement-summary-x.txt")
    joined = "\n".join(findings)
    assert "engagement-summary-email.md" in joined
    assert "rule 3" in joined and "rule 3a" not in joined


def test_interim_update_legal_while_open_no_summary_before_close(tmp_path):
    art = tmp_path / "artifacts"
    _touch(art / "engagement-brief.md")
    _touch(art / "engagement-brief.html")
    _touch(art / "interim-update-1.txt", _VALID_INTERIM)
    _index(art, status=STATUS_OPEN, listed=["engagement-brief.md", "interim-update-1.txt"])
    findings = check(art)
    assert not any("SUMMARY-BEFORE-CLOSE" in f for f in findings)
    assert findings == []


def test_interim_update_legal_while_blocked(tmp_path):
    art = tmp_path / "artifacts"
    _touch(art / "interim-update-1.txt", _VALID_INTERIM)
    _index(art, status=STATUS_BLOCKED, listed=["interim-update-1.txt"])
    assert not any("SUMMARY-BEFORE-CLOSE" in f for f in check(art))


def test_interim_update_missing_from_index_is_stale_index(tmp_path):
    art = tmp_path / "artifacts"
    _touch(art / "interim-update-1.txt", _VALID_INTERIM)
    _index(art, status=STATUS_OPEN, listed=[])  # not listed
    assert any("STALE-INDEX" in f for f in check(art))


def test_interim_update_as_md_is_wrong_ext(tmp_path):
    art = tmp_path / "artifacts"
    _index(art, status=STATUS_OPEN, listed=["interim-update-1.md"])
    _touch(art / "interim-update-1.md", "Hi,\n\nMorgan\n")
    codes = "\n".join(check(art))
    assert "INTERIM-WRONG-EXT" in codes
    assert "MISSING-HTML" not in codes


def test_interim_update_stray_html_is_wrong_ext(tmp_path):
    art = tmp_path / "artifacts"
    _touch(art / "interim-update-1.txt", _VALID_INTERIM)
    _touch(art / "interim-update-1.html", "<html></html>")
    _index(art, status=STATUS_OPEN, listed=["interim-update-1.txt"])
    assert "INTERIM-WRONG-EXT" in "\n".join(check(art))


def test_interim_update_not_morgan_flagged(tmp_path):
    art = tmp_path / "artifacts"
    _touch(art / "interim-update-1.txt", "Hi,\n\nStill working on it.\n\nDaniel\n")
    _index(art, status=STATUS_OPEN, listed=["interim-update-1.txt"])
    assert "EMAIL-NOT-MORGAN" in "\n".join(check(art))


def test_interim_update_agent_unmarked_flagged(tmp_path):
    art = tmp_path / "artifacts"
    _touch(
        art / "interim-update-1.txt",
        "Hi,\n\nLayla is reviewing it.\n\n🤖 Morgan\nPM & Orchestrator - Virtual Surveillance IT\n",
    )
    _index(art, status=STATUS_OPEN, listed=["interim-update-1.txt"])
    assert "EMAIL-AGENT-UNMARKED" in "\n".join(check(art))


def test_interim_update_does_not_satisfy_missing_summary_email_at_close(tmp_path):
    art = tmp_path / "artifacts"
    _touch(art / "engagement-brief.md")
    _touch(art / "engagement-brief.html")
    _touch(art / "interim-update-1.txt", _VALID_INTERIM)
    _index(
        art,
        status=STATUS_CLOSED,
        listed=["engagement-brief.md", "interim-update-1.txt"],
    )
    assert "MISSING-SUMMARY-EMAIL" in "\n".join(check(art))


def test_apply_fixes_renames_interim_update_md_to_txt(tmp_path):
    art = tmp_path / "artifacts"
    _index(art, listed=["interim-update-1.md"])
    _touch(art / "interim-update-1.md", "Hi,\n\nMorgan\n")

    fixed = "\n".join(apply_fixes(art))

    assert "interim-update-1.md -> interim-update-1.txt" in fixed
    assert (art / "interim-update-1.txt").is_file()
    assert not (art / "interim-update-1.md").exists()
    index_text = (art / "START-HERE.md").read_text(encoding="utf-8")
    assert "interim-update-1.txt" in index_text
    assert "interim-update-1.md" not in index_text


def test_apply_fixes_removes_stray_interim_update_html(tmp_path):
    art = tmp_path / "artifacts"
    _touch(art / "interim-update-1.txt", _VALID_INTERIM)
    _touch(art / "interim-update-1.html", "<html></html>")
    _index(art, status=STATUS_OPEN, listed=["interim-update-1.txt"])

    fixed = "\n".join(apply_fixes(art))

    assert "removed rendered email copy interim-update-1.html" in fixed
    assert not (art / "interim-update-1.html").exists()
