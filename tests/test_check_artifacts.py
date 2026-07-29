"""
Tests for the mechanical DoD artifact gate (scripts/check_artifacts.py).

The gate asserts the DoD items CI can never see (artifacts/ is git-ignored; the codebase
map lives in the working project): every .md deliverable has a rendered .html sibling, the
START-HERE living index exists from the first artifact and carries the engagement Status
(⏳/⛔/✅) with every file listed and every link resolving, close-only artifacts
(delivery-report / summary email) exist only once the status is ✅ closed, the closing
engagement-summary-*.txt exists at close, and any codebase map (ADR-003) passes mechanical
hygiene (size, As-of/Anchor header, basis tags, no secret-shaped content, resolvable anchor).
"""

from __future__ import annotations

import copy
import json
import subprocess

from scripts.check_artifacts import (
    _index_status,
    apply_fixes,
    check,
    check_agent_identity,
    check_map,
    check_registry,
    check_roster,
    find_codebase_map,
    main as ca_main,
    workspace_dirs,
)

_VALID_PACK = {
    "slug": "t",
    "scope": "s",
    "mode": "audit",
    "verdict": "conditional",
    "findings": [
        {
            "id": "F1",
            "title": "t",
            "severity": "warning",
            "location": "a.py:1",
            "basis": "coded",
            "standard": "CWE-1",
            "problem": "p",
            "likely_cause": "c",
            "impact": "i",
            "fix": {"diff": "-x\n+y", "why": "w"},
            "disposition": "open",
        }
    ],
}


def _pack(art, obj, name="findings-t.json"):
    d = art / "data"
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(json.dumps(obj), encoding="utf-8")


STATUS_OPEN = "⏳ IN PROGRESS"
STATUS_BLOCKED = "⛔ BLOCKED - awaiting input"
STATUS_CLOSED = "✅ CLOSED 2026-07-22"


def _touch(path, content="x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    # UTF-8 explicitly: map fixtures carry emoji basis tags, and Windows' default
    # locale encoding (cp1252) raises UnicodeEncodeError on them.
    path.write_text(content, encoding="utf-8")


def _index(art, status=STATUS_CLOSED, listed=()):
    """A minimal valid START-HERE living index: a Status line + one row per artifact."""
    rows = "\n".join(f"- `{name}` - purpose" for name in listed)
    _touch(art / "START-HERE.md", f"# START HERE\n\n| **Status** | {status} |\n\n{rows}\n")
    _touch(art / "START-HERE.html")


def test_missing_dir_is_not_a_failure(tmp_path):
    assert check(tmp_path / "artifacts") == []


def test_empty_dir_passes(tmp_path):
    (tmp_path / "artifacts").mkdir()
    assert check(tmp_path / "artifacts") == []


def test_md_without_html_is_flagged(tmp_path):
    art = tmp_path / "artifacts"
    _touch(art / "REVIEW-foo.md")
    _touch(art / "engagement-summary-foo.txt")
    _index(art, listed=["REVIEW-foo.md", "engagement-summary-foo.txt"])
    findings = check(art)
    assert len(findings) == 1
    assert "MISSING-HTML" in findings[0]
    assert "REVIEW-foo.md" in findings[0]


def test_missing_summary_email_is_flagged(tmp_path):
    art = tmp_path / "artifacts"
    _touch(art / "delivery-report.md")
    _touch(art / "delivery-report.html")
    _index(art, listed=["delivery-report.md"])
    findings = check(art)
    assert len(findings) == 1
    assert "MISSING-SUMMARY-EMAIL" in findings[0]


def test_complete_gate_passes(tmp_path):
    art = tmp_path / "artifacts"
    _touch(art / "delivery-report.md")
    _touch(art / "delivery-report.html")
    _touch(art / "engagement-summary-spoofing.txt")
    _index(art, listed=["delivery-report.md", "engagement-summary-spoofing.txt"])
    assert check(art) == []


def test_nested_artifacts_are_checked(tmp_path):
    art = tmp_path / "artifacts"
    _touch(art / "sub" / "spec.md")
    _touch(art / "engagement-summary-x.txt")
    _index(art, listed=["spec.md", "engagement-summary-x.txt"])
    findings = check(art)
    assert len(findings) == 1
    assert "sub" in findings[0]


# --- finding-shape gate (every 🔴/🟠 block states its impact) -----------------------------


def _finding_block(with_impact):
    impact = "**Impact if unaddressed:** missed detections on venue X.\n" if with_impact else ""
    return (
        "### 🔴 Threshold hardcoded\n"
        "**Location:** `x.py:42`\n"
        "**Problem:** threshold is in code, spec says config.\n" + impact + "**Fix:** move it.\n"
    )


def test_finding_without_impact_flagged(tmp_path):
    art = tmp_path / "artifacts"
    _touch(art / "REVIEW-x.md", _finding_block(with_impact=False))
    _touch(art / "REVIEW-x.html")
    _touch(art / "engagement-summary-x.txt")
    _index(art, listed=["REVIEW-x.md", "engagement-summary-x.txt"])
    findings = check(art)
    assert len(findings) == 1 and "FINDING-NO-IMPACT" in findings[0]


def test_finding_with_impact_passes(tmp_path):
    art = tmp_path / "artifacts"
    _touch(art / "REVIEW-x.md", _finding_block(with_impact=True) + _finding_block(True))
    _touch(art / "REVIEW-x.html")
    _touch(art / "engagement-summary-x.txt")
    _index(art, listed=["REVIEW-x.md", "engagement-summary-x.txt"])
    assert check(art) == []


def test_artifact_without_finding_blocks_not_flagged(tmp_path):
    art = tmp_path / "artifacts"
    _touch(art / "delivery-report.md", "# Report\n\nProse only, tables elsewhere.\n")
    _touch(art / "delivery-report.html")
    _touch(art / "engagement-summary-x.txt")
    _index(art, listed=["delivery-report.md", "engagement-summary-x.txt"])
    assert check(art) == []


# --- START-HERE living-index gate ---------------------------------------------------------
# The index is created at engagement OPEN (with the first artifact), carries the Status,
# and is updated on every artifact write - born of the 2026-07-22 dangling-engagement
# failure, where an unindexed interim pack was read as a finished delivery.


def test_any_artifact_requires_index(tmp_path):
    art = tmp_path / "artifacts"
    _touch(art / "review-pass-1.md")
    _touch(art / "review-pass-1.html")
    findings = check(art)
    assert any("MISSING-INDEX" in f for f in findings)


def test_index_satisfies_gate(tmp_path):
    art = tmp_path / "artifacts"
    for stem in ("delivery-report", "qa-handover"):
        _touch(art / f"{stem}.md")
        _touch(art / f"{stem}.html")
    _touch(art / "engagement-summary-x.txt")
    _index(art, listed=["delivery-report.md", "qa-handover.md", "engagement-summary-x.txt"])
    assert check(art) == []


def test_index_without_status_flagged(tmp_path):
    art = tmp_path / "artifacts"
    _touch(art / "review-pass-1.md")
    _touch(art / "review-pass-1.html")
    _touch(art / "START-HERE.md", "# START HERE\n\n- `review-pass-1.md` - first pass\n")
    _touch(art / "START-HERE.html")
    findings = check(art)
    assert len(findings) == 1 and "INDEX-NO-STATUS" in findings[0]


def test_unlisted_artifact_is_stale_index(tmp_path):
    art = tmp_path / "artifacts"
    _touch(art / "review-pass-1.md")
    _touch(art / "review-pass-1.html")
    _touch(art / "qa-cycle-1.md")
    _touch(art / "qa-cycle-1.html")
    _index(art, status=STATUS_OPEN, listed=["review-pass-1.md"])
    findings = check(art)
    assert len(findings) == 1
    assert "STALE-INDEX" in findings[0] and "qa-cycle-1.md" in findings[0]


def test_dangling_index_link_is_stale_index(tmp_path):
    art = tmp_path / "artifacts"
    _touch(art / "review-pass-1.md")
    _touch(art / "review-pass-1.html")
    _touch(
        art / "START-HERE.md",
        "# START HERE\n\n| **Status** | ⏳ IN PROGRESS |\n\n"
        "- [`review-pass-1.md`](review-pass-1.md)\n- [`rtm.md`](rtm.md)\n",
    )
    _touch(art / "START-HERE.html")
    findings = check(art)
    assert len(findings) == 1
    assert "STALE-INDEX" in findings[0] and "rtm.md" in findings[0]


def test_external_links_in_index_are_ignored(tmp_path):
    art = tmp_path / "artifacts"
    _touch(art / "review-pass-1.md")
    _touch(art / "review-pass-1.html")
    _touch(
        art / "START-HERE.md",
        "# START HERE\n\n| **Status** | ⏳ IN PROGRESS |\n\n"
        "- [`review-pass-1.md`](review-pass-1.md)\n"
        "- [MAR Art.12](https://eur-lex.europa.eu/x)\n",
    )
    _touch(art / "START-HERE.html")
    assert check(art) == []


def test_word_status_forms_are_readable(tmp_path):
    art = tmp_path / "artifacts"
    _touch(art / "notes-1.md")
    _touch(art / "notes-1.html")
    _touch(
        art / "START-HERE.md",
        "# START HERE\n\nStatus: in progress\n\n- `notes-1.md` - notes\n",
    )
    _touch(art / "START-HERE.html")
    assert check(art) == []


# --- close-only artifacts (state gate) ----------------------------------------------------


def test_delivery_report_before_close_flagged(tmp_path):
    art = tmp_path / "artifacts"
    _touch(art / "delivery-report.md")
    _touch(art / "delivery-report.html")
    _index(art, status=STATUS_BLOCKED, listed=["delivery-report.md"])
    findings = check(art)
    assert len(findings) == 1 and "FINAL-BEFORE-CLOSE" in findings[0]


def test_summary_email_before_close_flagged(tmp_path):
    art = tmp_path / "artifacts"
    _touch(art / "review-pass-1.md")
    _touch(art / "review-pass-1.html")
    _touch(art / "engagement-summary-x.txt")
    _index(art, status=STATUS_OPEN, listed=["review-pass-1.md", "engagement-summary-x.txt"])
    findings = check(art)
    assert len(findings) == 1 and "SUMMARY-BEFORE-CLOSE" in findings[0]


def test_blocked_engagement_with_interim_names_passes(tmp_path):
    art = tmp_path / "artifacts"
    for stem in ("engagement-brief", "review-pass-1"):
        _touch(art / f"{stem}.md")
        _touch(art / f"{stem}.html")
    _index(art, status=STATUS_BLOCKED, listed=["engagement-brief.md", "review-pass-1.md"])
    assert check(art) == []


def test_open_engagement_needs_no_summary_email(tmp_path):
    art = tmp_path / "artifacts"
    _touch(art / "engagement-brief.md")
    _touch(art / "engagement-brief.html")
    _index(art, status=STATUS_OPEN, listed=["engagement-brief.md"])
    assert check(art) == []


def test_folder_without_index_is_not_closed(tmp_path):
    # 2026-07-29 register G1 [reproduced]: a pack with NO index used to route down the
    # closed/legacy branch, disarming the close-only guards exactly when the team forgot
    # the index. No readable status is now fail-safe NOT closed: the delivery report is
    # premature and the email is not demanded (creating the index is the fix, not the
    # email).
    art = tmp_path / "artifacts"
    _touch(art / "delivery-report.md")
    _touch(art / "delivery-report.html")
    findings = check(art)
    codes = "".join(findings)
    assert "MISSING-INDEX" in codes and "FINAL-BEFORE-CLOSE" in codes
    assert "MISSING-SUMMARY-EMAIL" not in codes


# --- code-without-QA gate (the 2026-07-21 live failure) ----------------------------------


def test_code_without_qa_handover_flagged(tmp_path):
    art = tmp_path / "artifacts"
    _touch(art / "wash_trade_model.py", "def score(): ...")
    _touch(art / "report.md")
    _touch(art / "report.html")
    _touch(art / "engagement-summary-x.txt")
    _index(art, listed=["wash_trade_model.py", "report.md", "engagement-summary-x.txt"])
    codes = "".join(check(art))
    assert "CODE-NO-QA" in codes and "CODE-NO-TESTS" in codes


def test_code_with_qa_and_tests_passes(tmp_path):
    art = tmp_path / "artifacts"
    _touch(art / "wash_trade_model.py", "def score(): ...")
    _touch(art / "test_wash_trade_model.py", "def test_score(): ...")
    _touch(art / "qa-handover.md")
    _touch(art / "qa-handover.html")
    _touch(art / "engagement-summary-x.txt")
    _index(
        art,
        listed=[
            "wash_trade_model.py",
            "test_wash_trade_model.py",
            "qa-handover.md",
            "engagement-summary-x.txt",
        ],
    )
    assert check(art) == []


def test_test_files_alone_do_not_trigger_gate(tmp_path):
    art = tmp_path / "artifacts"
    _touch(art / "test_something.py", "def test_x(): ...")
    _touch(art / "engagement-summary-x.txt")
    _touch(art / "notes.md")
    _touch(art / "notes.html")
    _index(art, listed=["test_something.py", "engagement-summary-x.txt", "notes.md"])
    assert check(art) == []


# --- gate-hardening regressions (2026-07-23 adversarial review) ---------------------------
# Every reproduced-failing input from the review is pinned here so it can't silently return.


def test_index_status_negated_closed_is_not_closed():
    # C1: a negated/qualified 'closed' must not read as closed (fail-unsafe otherwise).
    assert _index_status("Status: not closed") is None
    assert _index_status("Status: blocked, cannot be closed until sign-off") == "blocked"
    assert _index_status("Status: closed to new scope; work still in progress") == "open"


def test_index_status_legend_line_is_not_closed():
    # C2: a line listing all three status symbols is a legend, not a state.
    assert _index_status("| Status | Legend: ⏳ in progress, ⛔ blocked, ✅ closed |") is None
    assert _index_status("Status key: ⏳=open ⛔=blocked ✅=closed. Current: ⏳") is None


def test_index_status_canonical_forms_still_work():
    assert _index_status("| **Status** | ✅ CLOSED 2026-07-22 |") == "closed"
    assert _index_status("| **Status** | ⛔ BLOCKED - awaiting input |") == "blocked"
    assert _index_status("| **Status** | ⏳ IN PROGRESS |") == "open"
    assert _index_status("Status: in progress") == "open"


def test_stale_index_uses_whole_tokens_not_substrings(tmp_path):
    # H1: report.md must not count as listed just because final-report.md contains it.
    art = tmp_path / "artifacts"
    for stem in ("report", "final-report"):
        _touch(art / f"{stem}.md")
        _touch(art / f"{stem}.html")
    _touch(art / "engagement-summary-x.txt")
    _touch(
        art / "START-HERE.md",
        "# S\n| Status | ✅ CLOSED |\n- final-report.md\n- engagement-summary-x.txt\n",
    )
    _touch(art / "START-HERE.html")
    findings = [f for f in check(art) if "STALE-INDEX" in f and "report.md" in f]
    assert any("report.md" in f and "final-report" not in f for f in findings)


def test_stale_index_ignores_link_fragment_and_title(tmp_path):
    # M1: [Spec](spec.md#requirements) and [Spec](spec.md "the spec") are valid links.
    art = tmp_path / "artifacts"
    _touch(art / "spec.md")
    _touch(art / "spec.html")
    _touch(
        art / "START-HERE.md",
        "# S\n| Status | ⏳ IN PROGRESS |\n- [Spec](spec.md#requirements)\n"
        '- [Spec2](spec.md "the spec")\n',
    )
    _touch(art / "START-HERE.html")
    assert not [f for f in check(art) if "STALE-INDEX" in f]


def test_finding_impact_checked_per_block(tmp_path):
    # M2: block B (no impact) is flagged even though block A carries two impact lines.
    art = tmp_path / "artifacts"
    body = (
        "### 🔴 A\n**Impact if unaddressed:** x\n**Impact if unaddressed:** y\n"
        "### 🟠 B\nno impact line here\n"
    )
    _touch(art / "review-pass-1.md", body)
    _touch(art / "review-pass-1.html")
    _touch(art / "START-HERE.md", "# S\n| Status | ⏳ IN PROGRESS |\n- review-pass-1.md\n")
    _touch(art / "START-HERE.html")
    assert any("FINDING-NO-IMPACT" in f for f in check(art))


def test_unreadable_status_still_gates_close_only(tmp_path):
    # M3: an unreadable status is treated as not-closed, so a delivery report still fails.
    art = tmp_path / "artifacts"
    _touch(art / "delivery-report.md")
    _touch(art / "delivery-report.html")
    _touch(art / "START-HERE.md", "# S\n| Status | (garbled) |\n- delivery-report.md\n")
    _touch(art / "START-HERE.html")
    codes = "".join(check(art))
    assert "FINAL-BEFORE-CLOSE" in codes and "INDEX-NO-STATUS" in codes


def test_roster_ignores_short_form_aliases(tmp_path):
    # H2: short forms collide with real content - tools, adjectives, client stakeholders.
    for t in (
        "Airflow (orchestrator) schedules the ETL.",
        "An Independent (QA) pass was performed by Linh.",
        "Second (QA) cycle completed.",
        "Aisha (BA) from the client confirmed the scope.",
    ):
        assert check_roster(t, tmp_path / "d.md") == [], t


def test_roster_still_catches_full_slug_fabrication(tmp_path):
    # H2: the real failure used full slugs - those must still be caught.
    assert check_roster("Chidi (code-reviewer) reviewed it.", tmp_path / "d.md")
    assert check_roster("Ravi (tm-sme) advised.", tmp_path / "d.md")


# --- roster gate (2026-07-23: fabricated reviewers on a delivery report) ------------------
# Synthetic names only - never the real reported content.


def test_roster_unknown_name_flagged(tmp_path):
    findings = check_roster("Quinn (code-reviewer) reviewed it.", tmp_path / "d.md")
    assert len(findings) == 1
    assert "ROSTER-UNKNOWN" in findings[0] and "Quinn" in findings[0] and "Ravi" in findings[0]


def test_roster_role_mismatch_flagged(tmp_path):
    # A real roster name in the wrong role: Ravi is the code-reviewer, not the TM-SME.
    findings = check_roster("Ravi (tm-sme) advised on typology.", tmp_path / "d.md")
    assert len(findings) == 1
    assert "ROSTER-ROLE-MISMATCH" in findings[0] and "Hassan" in findings[0]


def test_roster_correct_attributions_pass(tmp_path):
    text = "Ravi (code-reviewer), Layla (compliance-reviewer), Hassan (tm-sme), Amara (BA), Morgan (PM)."
    assert check_roster(text, tmp_path / "d.md") == []


# --- AI-identity gate (2026-07-29 user rule: agents never readable as real people) --------


def test_agent_unmarked_when_persona_and_no_marker(tmp_path):
    findings = check_agent_identity("Ravi (code-reviewer) reviewed it.", tmp_path / "d.md")
    assert len(findings) == 1 and "AGENT-UNMARKED" in findings[0]


def test_agent_marked_passes(tmp_path):
    text = "🤖 Ravi (code-reviewer), Virtual Surveillance IT, reviewed it."
    assert check_agent_identity(text, tmp_path / "d.md") == []


def test_agent_no_persona_no_finding(tmp_path):
    # Prose with no team-persona attribution never needs a marker.
    assert check_agent_identity("The ETL runs nightly.", tmp_path / "d.md") == []


def test_agent_human_combined_flagged(tmp_path):
    findings = check_agent_identity(
        "🤖 legend present\nAwaiting sign-off from Layla + Daniel.", tmp_path / "d.md"
    )
    assert len(findings) == 1
    assert "AGENT-HUMAN-COMBINED" in findings[0] and "Layla" in findings[0]


def test_agent_human_combined_reversed_order(tmp_path):
    findings = check_agent_identity("🤖\nApproved by Daniel & Layla.", tmp_path / "d.md")
    assert len(findings) == 1 and "AGENT-HUMAN-COMBINED" in findings[0]


def test_two_agents_joined_pass(tmp_path):
    # Two roster names on one line is delegation, not an agent+human approval line.
    assert check_agent_identity("🤖\nTheo + Ana pair on tuning.", tmp_path / "d.md") == []


def test_agent_joined_to_acronym_passes(tmp_path):
    # The other token must be name-shaped; an acronym like RTM never trips it.
    assert check_agent_identity("🤖\nLayla + RTM check.", tmp_path / "d.md") == []


def test_roster_ignores_non_team_parentheticals(tmp_path):
    # Stakeholders / tools / headings with a parenthetical that is not a team role never trip.
    text = "Jordan (sponsor) confirmed. Sam (product owner) noted. Output (final) delivered."
    assert check_roster(text, tmp_path / "d.md") == []


def test_roster_deduplicates(tmp_path):
    text = "Quinn (code-reviewer) did X. Later, Quinn (code-reviewer) did Y."
    assert len(check_roster(text, tmp_path / "d.md")) == 1


def test_roster_check_runs_inside_check(tmp_path):
    art = tmp_path / "artifacts"
    _touch(art / "review-pass-1.md", "Quinn (compliance-reviewer) signed off.")
    _touch(art / "review-pass-1.html")
    _index(art, status=STATUS_OPEN, listed=["review-pass-1.md"])
    codes = "".join(check(art))
    assert "ROSTER-UNKNOWN" in codes


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


def test_map_novcs_anchor_accepted(tmp_path):
    # A working project with no git repo writes `Anchor no-vcs` - a valid anchor, not a
    # defect (surfaced by the 2026-07-22 end-to-end validation: two engagements in git-less
    # working projects could never pass the gate otherwise).
    m = tmp_path / "nogit" / "docs" / "codebase-map.md"
    _touch(
        m,
        "# Map - Proj\n\n"
        "> **Document control** · Owner `Morgan (PM)` · As-of `2026-07-22` · Anchor `no-vcs`\n\n"
        "## 2. Map entries\n\n"
        "| # | Area | Entry | Basis | As-of | Anchor |\n"
        "|---|------|-------|-------|-------|--------|\n"
        "| 1 | rules | threshold in x.py | 📊 seen | 2026-07-22 | no-vcs |\n",
    )
    assert check_map(m) == []


def test_map_no_anchor_still_flagged_without_sentinel(tmp_path):
    # The escape is explicit: a header with neither a SHA nor a no-vcs token still fails.
    m = tmp_path / "docs" / "codebase-map.md"
    _touch(
        m,
        "# Map\n\n> Owner `Morgan` · As-of `2026-07-22` · Anchor `TBD`\n\n"
        "## 2. Map entries\n\n| # | Entry | Basis |\n|---|-------|-------|\n"
        "| 1 | x | 📊 seen |\n",
    )
    codes = "".join(check_map(m))
    assert "MAP-NO-ANCHOR" in codes


def test_map_too_long_flagged(tmp_path):
    repo, sha = _map_repo(tmp_path)
    m = repo / "docs" / "codebase-map.md"
    _touch(m, _good_map(sha) + "filler\n" * 260)
    codes = "".join(check_map(m))
    assert "MAP-TOO-LONG" in codes


# --- summary-email extension, single-source status, and the --fix auto-fixer ----------------


def test_summary_email_as_md_is_wrong_ext_not_missing_html(tmp_path):
    art = tmp_path / "artifacts"
    _index(art, listed=["engagement-summary-x.md"])
    _touch(art / "engagement-summary-x.md", "Hi,\n\nSummary.\n\nMorgan\n")
    codes = "\n".join(check(art))
    assert "SUMMARY-WRONG-EXT" in codes
    # The email is a .txt, never rendered - it must NOT be nagged for a missing .html sibling.
    assert "MISSING-HTML" not in codes


def test_summary_email_as_html_is_wrong_ext(tmp_path):
    art = tmp_path / "artifacts"
    _index(art, listed=["engagement-summary-x.txt"])
    _touch(art / "engagement-summary-x.txt", "Hi,\n\nMorgan\n")
    _touch(art / "engagement-summary-x.html", "<html></html>")
    assert "SUMMARY-WRONG-EXT" in "\n".join(check(art))


def test_stale_status_banner_flagged_when_closed(tmp_path):
    art = tmp_path / "artifacts"
    _index(art, status=STATUS_CLOSED, listed=["engagement-brief.md", "engagement-summary-x.txt"])
    _touch(
        art / "engagement-brief.md",
        "# Brief\n\n> ⏳ INTERIM - engagement not closed; DoD checks have not run.\n",
    )
    _touch(art / "engagement-brief.html", "<html></html>")
    _touch(art / "engagement-summary-x.txt", "Hi,\n\nMorgan\n")
    assert "STALE-STATUS" in "\n".join(check(art))


def test_stale_status_not_flagged_while_open(tmp_path):
    art = tmp_path / "artifacts"
    _index(art, status=STATUS_OPEN, listed=["engagement-brief.md"])
    _touch(
        art / "engagement-brief.md",
        "# Brief\n\n> ⏳ INTERIM - engagement not closed; DoD checks have not run.\n",
    )
    _touch(art / "engagement-brief.html", "<html></html>")
    # An interim banner is CORRECT while open - only a closed engagement makes it stale.
    assert "STALE-STATUS" not in "\n".join(check(art))


def test_stale_docstatus_draft_flagged_when_closed(tmp_path):
    art = tmp_path / "artifacts"
    _index(art, status=STATUS_CLOSED, listed=["fsd.md", "engagement-summary-x.txt"])
    _touch(
        art / "fsd.md",
        "# FSD\n\n> **Document control** · ID `FSD-001` · Version `0.2` · Status `Draft (revised)`"
        " · Owner `Amara`\n",
    )
    _touch(art / "fsd.html", "<html></html>")
    _touch(art / "engagement-summary-x.txt", "Hi,\n\nMorgan\n")
    assert "STALE-DOCSTATUS" in "\n".join(check(art))


def test_stale_docstatus_in_review_flagged_when_closed(tmp_path):
    art = tmp_path / "artifacts"
    _index(art, status=STATUS_CLOSED, listed=["delivery-report.md", "engagement-summary-x.txt"])
    _touch(
        art / "delivery-report.md",
        "# Report\n\n> **Document control** · ID `DLVR-001` · Version `1.0` · Status `In review`\n",
    )
    _touch(art / "delivery-report.html", "<html></html>")
    _touch(art / "engagement-summary-x.txt", "Hi,\n\nMorgan\n")
    assert "STALE-DOCSTATUS" in "\n".join(check(art))


def test_stale_docstatus_pending_human_signoff_passes(tmp_path):
    # The one legitimate open state under a closed index: the human act is the only gap,
    # and the Status value says so explicitly.
    art = tmp_path / "artifacts"
    _index(art, status=STATUS_CLOSED, listed=["delivery-report.md", "engagement-summary-x.txt"])
    _touch(
        art / "delivery-report.md",
        "# Report\n\n> **Document control** · ID `DLVR-001` · Version `1.0` · "
        "Status `In review - pending human sign-off`\n",
    )
    _touch(art / "delivery-report.html", "<html></html>")
    _touch(art / "engagement-summary-x.txt", "Hi,\n\nMorgan\n")
    assert "STALE-DOCSTATUS" not in "\n".join(check(art))


def test_stale_docstatus_not_flagged_while_open(tmp_path):
    art = tmp_path / "artifacts"
    _index(art, status=STATUS_OPEN, listed=["fsd.md"])
    _touch(
        art / "fsd.md",
        "# FSD\n\n> **Document control** · ID `FSD-001` · Version `0.1` · Status `Draft`\n",
    )
    _touch(art / "fsd.html", "<html></html>")
    # Draft is the CORRECT state while the engagement is open.
    assert "STALE-DOCSTATUS" not in "\n".join(check(art))


def test_stale_docstatus_closed_status_value_passes(tmp_path):
    art = tmp_path / "artifacts"
    _index(art, status=STATUS_CLOSED, listed=["fsd.md", "engagement-summary-x.txt"])
    _touch(
        art / "fsd.md",
        "# FSD\n\n> **Document control** · ID `FSD-001` · Version `1.0` · Status `Final`\n",
    )
    _touch(art / "fsd.html", "<html></html>")
    _touch(art / "engagement-summary-x.txt", "Hi,\n\nMorgan\n")
    assert "STALE-DOCSTATUS" not in "\n".join(check(art))


def test_apply_fixes_renames_email_renders_html_and_syncs_index(tmp_path):
    art = tmp_path / "artifacts"
    _index(art, listed=["review-pass-1.md", "engagement-summary-x.md"])
    _touch(art / "review-pass-1.md", "# Review\n")  # no .html sibling
    _touch(art / "engagement-summary-x.md", "Hi,\n\nMorgan\n")  # wrong extension

    fixed = "\n".join(apply_fixes(art))

    assert "engagement-summary-x.md -> engagement-summary-x.txt" in fixed
    assert (art / "engagement-summary-x.txt").is_file()
    assert not (art / "engagement-summary-x.md").exists()
    assert (art / "review-pass-1.html").is_file()  # rendered by the fixer
    # the index reference was synced, so the rename leaves no residual STALE-INDEX
    index_text = (art / "START-HERE.md").read_text(encoding="utf-8")
    assert "engagement-summary-x.txt" in index_text
    assert "engagement-summary-x.md" not in index_text


def test_apply_fixes_is_idempotent(tmp_path):
    art = tmp_path / "artifacts"
    _index(art, listed=["review-pass-1.md"])
    _touch(art / "review-pass-1.md", "# Review\n")
    apply_fixes(art)  # first pass renders the missing HTML
    assert apply_fixes(art) == []  # second pass: nothing left to fix


def test_findings_5c_summary_label_flagged(tmp_path):
    art = tmp_path / "artifacts"
    _index(art, listed=["REVIEW-x.md", "engagement-summary-x.txt"])
    _touch(
        art / "REVIEW-x.md",
        "# Review\n\n## WF-07\n\n**5C Summary:** - Condition: x - Consequence: y - Correction: z\n",
    )
    _touch(art / "REVIEW-x.html", "<html></html>")
    _touch(art / "engagement-summary-x.txt", "Hi,\n\nMorgan\n")
    assert "FINDINGS-CWORD-LABELS" in "\n".join(check(art))


def test_findings_cword_bold_labels_flagged(tmp_path):
    art = tmp_path / "artifacts"
    _index(art, listed=["REVIEW-z.md", "engagement-summary-z.txt"])
    # C-words as bold field labels (no "5C summary" text) - still the drift.
    _touch(
        art / "REVIEW-z.md",
        "# Review\n\n### 🔴 WF-08\n\n**Condition:** x\n\n**Consequence:** y\n\n**Correction:** z\n",
    )
    _touch(art / "REVIEW-z.html", "<html></html>")
    _touch(art / "engagement-summary-z.txt", "Hi,\n\nMorgan\n")
    assert "FINDINGS-CWORD-LABELS" in "\n".join(check(art))


def test_canonical_named_fields_not_flagged(tmp_path):
    art = tmp_path / "artifacts"
    _index(art, listed=["REVIEW-y.md", "engagement-summary-y.txt"])
    _touch(
        art / "REVIEW-y.md",
        "# Review\n\n### 🔴 WF-07\n\n**Standard:** CWE-1\n\n**Problem:** x\n\n"
        "**Likely cause:** y\n\n**Impact if unaddressed:** z\n\n**Fix:**\n",
    )
    _touch(art / "REVIEW-y.html", "<html></html>")
    _touch(art / "engagement-summary-y.txt", "Hi,\n\nMorgan\n")
    assert "FINDINGS-CWORD-LABELS" not in "\n".join(check(art))


def test_valid_findings_pack_passes(tmp_path):
    art = tmp_path / "artifacts"
    _index(art, listed=["engagement-summary-t.txt"])
    _touch(art / "engagement-summary-t.txt", "Hi,\n\nMorgan\n")
    _pack(art, _VALID_PACK)
    assert "FINDINGS-INVALID" not in "\n".join(check(art))


def test_invalid_findings_pack_flagged(tmp_path):
    art = tmp_path / "artifacts"
    _index(art, listed=["engagement-summary-t.txt"])
    _touch(art / "engagement-summary-t.txt", "Hi,\n\nMorgan\n")
    bad = copy.deepcopy(_VALID_PACK)
    del bad["findings"][0]["likely_cause"]  # drop a required field
    _pack(art, bad)
    assert "FINDINGS-INVALID" in "\n".join(check(art))


def test_data_subfolder_pack_not_treated_as_deliverable(tmp_path):
    # A .json pack under data/ must not trip MISSING-HTML or STALE-INDEX (it's machine source).
    art = tmp_path / "artifacts"
    _index(art, listed=["engagement-summary-t.txt"])
    _touch(art / "engagement-summary-t.txt", "Hi,\n\nMorgan\n")
    _pack(art, _VALID_PACK)
    joined = "\n".join(check(art))
    assert "findings-t.json" not in joined  # never named by MISSING-HTML / STALE-INDEX


def test_apply_fixes_renders_report_from_pack_at_close(tmp_path):
    # D4 ruling 2026-07-29 (register P3): REVIEW-<slug>.md is close-only, so --fix renders
    # it during the 🔒 closing window (tests/test_placement_fixes.py pins the mid-engagement
    # refusal side).
    art = tmp_path / "artifacts"
    _index(art, status="🔒 CLOSING - finishing close artifacts")
    _pack(art, _VALID_PACK)  # slug "t" -> REVIEW-t.md rendered up into artifacts/
    apply_fixes(art)
    report = art / "REVIEW-t.md"
    assert report.is_file()
    assert "**Likely cause:**" in report.read_text(encoding="utf-8")


# ----------------------------------------------------- machine-readable state (ADR-006)


def _state_engagement(tmp_path):
    """An artifacts dir with a state file and its fresh render, via the real CLI."""
    from scripts.engagement_state import main as es_main

    art = tmp_path / "artifacts"
    assert es_main(["--dir", str(art), "init", "--title", "T", "--slug", "t"]) == 0
    return art


def test_state_engagement_fresh_render_passes(tmp_path):
    art = _state_engagement(tmp_path)
    assert [f for f in check(art) if f.startswith("STATE-")] == []


def test_state_stale_render_flagged_and_fixed(tmp_path):
    from scripts.engagement_state import load_state, state_path

    art = _state_engagement(tmp_path)
    # Hand-edit the state without re-rendering - the exact crash/hand-edit window.
    state = load_state(art)
    state["status"] = "blocked"
    state_path(art).write_text(json.dumps(state), encoding="utf-8")
    findings = check(art)
    assert any("STATE-STALE-RENDER" in f for f in findings)
    fixed = apply_fixes(art)
    assert any("STATE-STALE-RENDER" in f for f in fixed)
    assert "⛔" in (art / "START-HERE.md").read_text(encoding="utf-8")
    assert not any("STATE-STALE-RENDER" in f for f in check(art))


def test_state_invalid_flagged_not_autofixed(tmp_path):
    from scripts.engagement_state import state_path

    art = _state_engagement(tmp_path)
    state_path(art).write_text("{not json", encoding="utf-8")
    assert any("STATE-INVALID" in f for f in check(art))
    apply_fixes(art)  # must not crash, must not fabricate a render from bad state
    assert any("STATE-INVALID" in f for f in check(art))


def test_state_consent_key_is_invalid(tmp_path):
    """The hard exclusion end-to-end: a consent-shaped key in the state file is a gate
    finding, not something a render can launder."""
    from scripts.engagement_state import load_state, state_path

    art = _state_engagement(tmp_path)
    state = load_state(art)
    state["execution_consent"] = True
    state_path(art).write_text(json.dumps(state), encoding="utf-8")
    assert any("STATE-INVALID" in f and "consent" in f for f in check(art))


def test_state_missing_after_generated_index_flagged(tmp_path):
    from scripts.engagement_state import state_path

    art = _state_engagement(tmp_path)
    state_path(art).unlink()
    assert any("STATE-MISSING" in f for f in check(art))


def test_legacy_engagement_without_state_raises_no_state_findings(tmp_path):
    """Migration safety: a hand-written START-HERE with no state file is still legal."""
    art = tmp_path / "artifacts"
    art.mkdir()
    (art / "START-HERE.md").write_text(
        "# START HERE - legacy\n\n| **Status** | ⏳ IN PROGRESS |\n", encoding="utf-8"
    )
    (art / "START-HERE.html").write_text("<p>x</p>", encoding="utf-8")
    assert [f for f in check(art) if f.startswith("STATE-")] == []


# --------------------------------------- ratified-claims + review-fingerprint gates (v2)


def test_ratified_claim_pending_flagged(tmp_path):
    from scripts.engagement_state import main as es_main

    art = tmp_path / "artifacts"
    es_main(["--dir", str(art), "init", "--title", "T", "--slug", "t"])
    es_main(["--dir", str(art), "add-ratification", "reserved-column case-insensitivity ruling"])
    (art / "fsd.md").write_text(
        "# spec\n\nFR-023: reserved-column handling (ops-lead ratified 2026-07-26).\n",
        encoding="utf-8",
    )
    (art / "fsd.html").write_text("<p>x</p>", encoding="utf-8")
    findings = check(art)
    assert any("RATIFIED-CLAIM-PENDING" in f and "fsd.md" in f for f in findings)


def test_ratified_claim_negated_or_granted_not_flagged(tmp_path):
    from scripts.engagement_state import main as es_main

    art = tmp_path / "artifacts"
    es_main(["--dir", str(art), "init", "--title", "T", "--slug", "t"])
    es_main(["--dir", str(art), "add-ratification", "reserved-column case-insensitivity ruling"])
    (art / "fsd.md").write_text(
        "# spec\n\nFR-023: reserved-column ruling flagged for ops-lead ratification at close.\n",
        encoding="utf-8",
    )
    (art / "fsd.html").write_text("<p>x</p>", encoding="utf-8")
    assert not any("RATIFIED-CLAIM-PENDING" in f for f in check(art))
    # Once the human grant is recorded, the assertion is legitimate.
    (art / "fsd.md").write_text(
        "# spec\n\nFR-023: reserved-column handling (ops-lead ratified 2026-07-26).\n",
        encoding="utf-8",
    )
    es_main(["--dir", str(art), "ratify", "reserved-column", "--by", "ops lead"])
    assert not any("RATIFIED-CLAIM-PENDING" in f for f in check(art))


def test_review_fingerprint_gap_flagged_and_match_passes(tmp_path):
    import hashlib

    art = tmp_path / "artifacts"
    art.mkdir()
    code = art / "dedupe.py"
    code.write_text("def run():\n    return 1\n", encoding="utf-8")
    md5 = hashlib.md5(code.read_bytes()).hexdigest()
    # Review recorded a DIFFERENT fingerprint -> the shipped build was never reviewed.
    (art / "review-pass-1.md").write_text(
        f"# review\n\nReviewed build md5 {'0' * 32}.\n", encoding="utf-8"
    )
    (art / "review-pass-1.html").write_text("<p>x</p>", encoding="utf-8")
    findings = check(art)
    assert any("REVIEW-FINGERPRINT-GAP" in f and "dedupe.py" in f for f in findings)
    # Matching fingerprint -> silent.
    (art / "review-pass-1.md").write_text(
        f"# review\n\nReviewed build md5 {md5}.\n", encoding="utf-8"
    )
    assert not any("REVIEW-FINGERPRINT-GAP" in f for f in check(art))


def test_review_without_fingerprints_raises_nothing(tmp_path):
    art = tmp_path / "artifacts"
    art.mkdir()
    (art / "tool.py").write_text("x = 1\n", encoding="utf-8")
    (art / "review-pass-1.md").write_text("# review\n\nNo hashes here.\n", encoding="utf-8")
    (art / "review-pass-1.html").write_text("<p>x</p>", encoding="utf-8")
    assert not any("REVIEW-FINGERPRINT-GAP" in f for f in check(art))


def _closed_light_pack(tmp_path, profile_args):
    # A DEFECTIVE closed pack (no summary email). `set-status closed` now refuses such a
    # close (R6 gate, tests/test_closing_status.py), so this fixture hand-mints the closed
    # state on disk - exactly the resumed-session mint the checker must still judge.
    from scripts.engagement_state import load_state, main as es_main, state_path

    art = tmp_path / "artifacts"
    es_main(["--dir", str(art), "init", "--title", "T", "--slug", "t", *profile_args])
    (art / "engagement-brief.md").write_text("# brief\n\nClose note: done.\n", encoding="utf-8")
    (art / "engagement-brief.html").write_text("<p>x</p>", encoding="utf-8")
    es_main(["--dir", str(art), "add-artifact", "engagement-brief.md", "--title", "Brief"])
    es_main(["--dir", str(art), "set-team", "Ana (analysis)"])
    es_main(["--dir", str(art), "finalise-artifacts"])
    state = load_state(art)
    state["status"] = "closed"
    state["engagement"]["closed"] = "2026-07-29"
    state["outstanding"] = []
    state["verdict"] = "done"
    state_path(art).write_text(json.dumps(state), encoding="utf-8")
    es_main(["--dir", str(art), "render"])
    return art


def test_light_profile_close_requires_email_too(tmp_path):
    """User ruling 2026-07-27: the summary email is uniform across profiles - light keeps
    it short, never absent. The brief waiver was reverted the same day it was added."""
    art = _closed_light_pack(tmp_path, ["--profile", "light"])
    assert any("MISSING-SUMMARY-EMAIL" in f for f in check(art))
    (art / "engagement-summary-t.txt").write_text("Hi,\n\nDone. - Morgan\n", encoding="utf-8")
    from scripts.engagement_state import main as es_main

    es_main(
        [
            "--dir",
            str(art),
            "add-artifact",
            "engagement-summary-t.txt",
            "--title",
            "Summary email",
            "--final",
        ]
    )
    assert not any("MISSING-SUMMARY-EMAIL" in f for f in check(art))


def test_standard_profile_close_still_requires_email(tmp_path):
    art = _closed_light_pack(tmp_path, [])
    assert any("MISSING-SUMMARY-EMAIL" in f for f in check(art))


# ----------------------------------------------------- workspaces + registry (0.31)


def _ws(tmp_path, slug, close=False):
    from scripts.engagement_state import main as es_main

    art = tmp_path / "artifacts"
    es_main(["--dir", str(art / slug), "init", "--title", slug, "--slug", slug])
    if close:
        es_main(["--dir", str(art / slug), "set-team", "Ana (analysis)"])
        es_main(["--dir", str(art / slug), "finalise-artifacts"])
        es_main(["--dir", str(art / slug), "set-status", "closed", "--verdict", "done"])
    return art


def test_workspaces_checked_independently_with_prefixes(tmp_path, capsys):
    art = _ws(tmp_path, "audit")
    _ws(tmp_path, "scoping")
    (art / "audit" / "review-pass-1.md").write_text("# interim\n", encoding="utf-8")
    from scripts.engagement_state import render_registry

    render_registry(art)
    rc = ca_main(["check_artifacts", str(art)])
    out = capsys.readouterr().out
    assert rc == 1
    assert "[audit] " in out and "MISSING-HTML" in out
    assert "[scoping] MISSING-HTML" not in out  # sibling not polluted


def test_registry_stale_flagged_and_fixed(tmp_path):
    art = _ws(tmp_path, "audit")
    from scripts.engagement_state import load_state, render_registry, state_path

    render_registry(art)
    state = load_state(art / "audit")
    state["status"] = "blocked"
    state_path(art / "audit").write_text(json.dumps(state), encoding="utf-8")
    assert any("REGISTRY-STALE" in f for f in check_registry(art))
    render_registry(art)
    assert check_registry(art) == []


def test_flat_pack_alongside_workspaces_demands_migration(tmp_path, capsys):
    from scripts.engagement_state import main as es_main

    art = _ws(tmp_path, "audit")
    es_main(["--dir", str(art), "init", "--title", "Old", "--slug", "old"])  # flat
    from scripts.engagement_state import render_registry

    render_registry(art)
    ca_main(["check_artifacts", str(art)])
    out = capsys.readouterr().out
    assert "FLAT-PACK-UNMIGRATED" in out


def test_workspace_dirs_discovery(tmp_path):
    art = _ws(tmp_path, "audit")
    (art / "not-a-pack").mkdir()
    assert [p.name for p in workspace_dirs(art)] == ["audit"]
