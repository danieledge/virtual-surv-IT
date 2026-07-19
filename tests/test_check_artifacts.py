"""
Tests for the mechanical DoD artifact gate (scripts/check_artifacts.py).

The gate asserts the DoD items CI can never see (artifacts/ is git-ignored; the codebase
map lives in the working project): every .md deliverable has a rendered .html sibling, the
closing engagement-summary-*.txt email exists once there are deliverables, and any codebase
map (ADR-003) passes mechanical hygiene (size, As-of/Anchor header, basis tags, no
secret-shaped content, resolvable anchor).
"""

from __future__ import annotations

import subprocess

from scripts.check_artifacts import check, check_map, find_codebase_map


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


# --- codebase-map hygiene (ADR-003) ------------------------------------------------------


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def _map_repo(tmp_path):
    """A tiny real repo so header-anchor SHAs can resolve."""
    repo = tmp_path / "proj"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(
        repo,
        "-c",
        "user.email=t@t",
        "-c",
        "user.name=t",
        "commit",
        "-q",
        "--allow-empty",
        "-m",
        "x",
    )
    sha = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()
    return repo, sha


def _good_map(sha):
    return (
        "# Codebase Map - Proj\n\n"
        f"> **Document control** · Owner `Morgan (PM)` · As-of `2026-07-18` · Anchor `{sha}`\n\n"
        "## 2. Map entries\n\n"
        "| # | Area | Entry | Basis | As-of | Anchor |\n"
        "|---|------|-------|-------|-------|--------|\n"
        f"| 1 | rules | threshold rationale in x.py | 📊 seen in review | 2026-07-18 | `{sha[:9]}` |\n"
    )


def test_good_map_passes(tmp_path):
    repo, sha = _map_repo(tmp_path)
    m = repo / "docs" / "codebase-map.md"
    _touch(m, _good_map(sha))
    assert check_map(m) == []


def test_map_discovery(tmp_path):
    repo, sha = _map_repo(tmp_path)
    assert find_codebase_map(repo) is None
    _touch(repo / "docs" / "codebase-map.md", _good_map(sha))
    assert find_codebase_map(repo) == repo / "docs" / "codebase-map.md"


def test_map_missing_asof_and_anchor_flagged(tmp_path):
    m = tmp_path / "codebase-map.md"
    _touch(m, "# Map\n\nno header here\n")
    codes = "".join(check_map(m))
    assert "MAP-NO-ASOF" in codes and "MAP-NO-ANCHOR" in codes


def test_map_entry_without_basis_tag_flagged(tmp_path):
    repo, sha = _map_repo(tmp_path)
    m = repo / "docs" / "codebase-map.md"
    _touch(m, _good_map(sha) + "| 2 | etl | untagged claim | none | 2026-07-18 | - |\n")
    findings = check_map(m)
    assert len(findings) == 1 and "MAP-NO-BASIS" in findings[0]


def test_map_secret_content_flagged(tmp_path):
    repo, sha = _map_repo(tmp_path)
    m = repo / "docs" / "codebase-map.md"
    _touch(m, _good_map(sha) + '\nnote: api_key = "abcd1234efgh5678"\n')
    findings = check_map(m)
    assert len(findings) == 1 and "MAP-SECRET" in findings[0]


def test_map_unresolvable_anchor_flagged(tmp_path):
    repo, _sha = _map_repo(tmp_path)
    m = repo / "docs" / "codebase-map.md"
    _touch(m, _good_map("deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"))
    codes = "".join(check_map(m))
    assert "MAP-STALE-ANCHOR" in codes


def test_map_outside_git_skips_anchor_check(tmp_path):
    m = tmp_path / "nogit" / "docs" / "codebase-map.md"
    _touch(m, _good_map("deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"))
    assert check_map(m) == []


def test_map_too_long_flagged(tmp_path):
    repo, sha = _map_repo(tmp_path)
    m = repo / "docs" / "codebase-map.md"
    _touch(m, _good_map(sha) + "filler\n" * 260)
    codes = "".join(check_map(m))
    assert "MAP-TOO-LONG" in codes
