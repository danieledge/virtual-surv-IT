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
    find_codebase_map_area_files,
    main as ca_main,
    workspace_dirs,
    _read_map_skeleton_toggle,
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


def _pack(art, obj, name="findings-t.jsonl"):
    from scripts.findings_pack_io import write_pack

    write_pack(art / "data" / name, obj)


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
    _touch(
        art / "engagement-summary-foo.txt",
        "Hi,\n\nAll done.\n\n\U0001f916 Morgan\nPM & Orchestrator - Virtual Surveillance IT (AI agent)\n",
    )
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
    _touch(
        art / "engagement-summary-spoofing.txt",
        "Hi,\n\nAll done.\n\n\U0001f916 Morgan\nPM & Orchestrator - Virtual Surveillance IT (AI agent)\n",
    )
    _index(art, listed=["delivery-report.md", "engagement-summary-spoofing.txt"])
    assert check(art) == []


def test_nested_artifacts_are_checked(tmp_path):
    art = tmp_path / "artifacts"
    _touch(art / "sub" / "spec.md")
    _touch(
        art / "engagement-summary-x.txt",
        "Hi,\n\nAll done.\n\n\U0001f916 Morgan\nPM & Orchestrator - Virtual Surveillance IT (AI agent)\n",
    )
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
    _touch(
        art / "engagement-summary-x.txt",
        "Hi,\n\nAll done.\n\n\U0001f916 Morgan\nPM & Orchestrator - Virtual Surveillance IT (AI agent)\n",
    )
    _index(art, listed=["REVIEW-x.md", "engagement-summary-x.txt"])
    findings = check(art)
    assert len(findings) == 1 and "FINDING-NO-IMPACT" in findings[0]


def test_finding_with_impact_passes(tmp_path):
    art = tmp_path / "artifacts"
    _touch(art / "REVIEW-x.md", _finding_block(with_impact=True) + _finding_block(True))
    _touch(art / "REVIEW-x.html")
    _touch(
        art / "engagement-summary-x.txt",
        "Hi,\n\nAll done.\n\n\U0001f916 Morgan\nPM & Orchestrator - Virtual Surveillance IT (AI agent)\n",
    )
    _index(art, listed=["REVIEW-x.md", "engagement-summary-x.txt"])
    assert check(art) == []


def test_artifact_without_finding_blocks_not_flagged(tmp_path):
    art = tmp_path / "artifacts"
    _touch(art / "delivery-report.md", "# Report\n\nProse only, tables elsewhere.\n")
    _touch(art / "delivery-report.html")
    _touch(
        art / "engagement-summary-x.txt",
        "Hi,\n\nAll done.\n\n\U0001f916 Morgan\nPM & Orchestrator - Virtual Surveillance IT (AI agent)\n",
    )
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
    _touch(
        art / "engagement-summary-x.txt",
        "Hi,\n\nAll done.\n\n\U0001f916 Morgan\nPM & Orchestrator - Virtual Surveillance IT (AI agent)\n",
    )
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
    _touch(
        art / "engagement-summary-x.txt",
        "Hi,\n\nAll done.\n\n\U0001f916 Morgan\nPM & Orchestrator - Virtual Surveillance IT (AI agent)\n",
    )
    _index(art, status=STATUS_OPEN, listed=["review-pass-1.md", "engagement-summary-x.txt"])
    findings = check(art)
    assert len(findings) == 1 and "SUMMARY-BEFORE-CLOSE" in findings[0]


def test_summary_email_under_archived_nested_dir_is_not_flagged(tmp_path):
    """C6 (2026-08 audit): the summaries rglob was the one recursive summary-email scan
    in check() that did not exclude .archive'd subtrees (every sibling rglob a few lines
    up/down does). A leftover summary email under an archived NESTED subdirectory used to
    get flagged as SUMMARY-BEFORE-CLOSE against the outer, still-open pack that never
    wrote it."""
    art = tmp_path / "artifacts"
    _touch(art / "review-pass-1.md")
    _touch(art / "review-pass-1.html")
    nested = art / "old-subpack"
    _touch(nested / "engagement-summary-old.txt", "Hi,\n\nAll done.\n")
    _touch(nested / ".archive", "archived\n")
    _index(art, status=STATUS_OPEN, listed=["review-pass-1.md"])
    findings = check(art)
    assert not any("SUMMARY-BEFORE-CLOSE" in f for f in findings)


def test_close_gate_trusts_the_state_file_over_a_stale_index(tmp_path):
    """C8 (2026-08 audit): check() used to read the overall engagement status from the
    RENDERED INDEX TEXT only, never engagement-state.json - register G5 made pack_status()
    (state file authoritative, index a fallback) the one shared status rule for exactly
    this class of bug. The dangerous direction: a stale or hand-edited index that LOOKS
    closed while the state file says otherwise used to silently waive the close-only gate
    for a pack that was never actually closed."""
    import re

    from scripts.engagement_state import main as es_main

    art = tmp_path / "artifacts"
    assert es_main(["--dir", str(art), "init", "--title", "T", "--slug", "t"]) == 0
    state = json.loads((art / "engagement-state.json").read_text(encoding="utf-8"))
    assert state["status"] == "in_progress"  # genuinely open - authoritative

    # Index hand-edited/stale: falsely reads as closed.
    index_path = art / "START-HERE.md"
    text = index_path.read_text(encoding="utf-8")
    text = re.sub(r"\|\s*\*\*Status\*\*\s*\|.*\|", "| **Status** | ✅ closed |", text)
    index_path.write_text(text, encoding="utf-8")
    assert _index_status(text) == "closed"  # confirms the fixture actually reads as closed

    # An early summary email - only legitimate once genuinely closed.
    _touch(art / "engagement-summary-x.txt", "Hi,\n\nDone.\n")

    findings = check(art)
    assert any("SUMMARY-BEFORE-CLOSE" in f for f in findings)


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
    _touch(
        art / "engagement-summary-x.txt",
        "Hi,\n\nAll done.\n\n\U0001f916 Morgan\nPM & Orchestrator - Virtual Surveillance IT (AI agent)\n",
    )
    _index(art, listed=["wash_trade_model.py", "report.md", "engagement-summary-x.txt"])
    codes = "".join(check(art))
    assert "CODE-NO-QA" in codes and "CODE-NO-TESTS" in codes


def test_code_with_qa_and_tests_passes(tmp_path):
    art = tmp_path / "artifacts"
    _touch(art / "wash_trade_model.py", "def score(): ...")
    _touch(art / "test_wash_trade_model.py", "def test_score(): ...")
    _touch(art / "qa-handover.md")
    _touch(art / "qa-handover.html")
    _touch(
        art / "engagement-summary-x.txt",
        "Hi,\n\nAll done.\n\n\U0001f916 Morgan\nPM & Orchestrator - Virtual Surveillance IT (AI agent)\n",
    )
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
    _touch(
        art / "engagement-summary-x.txt",
        "Hi,\n\nAll done.\n\n\U0001f916 Morgan\nPM & Orchestrator - Virtual Surveillance IT (AI agent)\n",
    )
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
    _touch(
        art / "engagement-summary-x.txt",
        "Hi,\n\nAll done.\n\n\U0001f916 Morgan\nPM & Orchestrator - Virtual Surveillance IT (AI agent)\n",
    )
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
    codes = "".join(check_map(m))
    assert "MAP-NO-BASIS" in codes
    # Since the M2 fix (2026-07-29) the '-' anchor cell is a finding too, not decoration.
    assert "MAP-ENTRY-NO-ANCHOR" in codes


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


# ---------------------------------- MAP-DRIFT / MAP-DEAD-POINTER (ADR-007 Phase 1 Chunk C)


def _good_map_with_paths(sha, entry="threshold rationale in `src/x.py:12`"):
    return (
        "# Codebase Map - Proj\n\n"
        f"> **Document control** · Owner `Morgan (PM)` · As-of `2026-07-18` · Anchor `{sha}`\n\n"
        "## 2. Map entries\n\n"
        "| # | Area | Entry | Basis | As-of | Anchor | Paths |\n"
        "|---|------|-------|-------|-------|--------|-------|\n"
        f"| 1 | rules | {entry} | 📊 seen in review | 2026-07-18 | `{sha[:9]}` | src/x.py |\n"
    )


def test_map_skeleton_toggle_off_by_default_no_new_findings(tmp_path):
    repo, sha = _map_repo(tmp_path)
    (repo / "src").mkdir()
    (repo / "src" / "x.py").write_text("threshold = 1\n", encoding="utf-8")
    m = repo / "docs" / "codebase-map.md"
    _touch(m, _good_map_with_paths(sha))
    # No team-preferences.json at all - toggle defaults to off - a Paths glob that was
    # NEVER fingerprinted (the load-bearing regression guard: this would be MAP-DRIFT if on).
    assert check_map(m, project_dir=repo) == []


def test_map_skeleton_toggle_on_via_project_preference():
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        (root / ".claude").mkdir()
        (root / ".claude" / "team-preferences.json").write_text(
            json.dumps({"map_skeleton": True}), encoding="utf-8"
        )
        assert _read_map_skeleton_toggle(root) is True


def test_map_skeleton_toggle_project_false_overrides_machine_true(tmp_path, monkeypatch):
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "team-preferences.json").write_text(
        json.dumps({"map_skeleton": False}), encoding="utf-8"
    )
    xdg = tmp_path / "xdg"
    (xdg / "virt-surv-it").mkdir(parents=True)
    (xdg / "virt-surv-it" / "installer.json").write_text(
        json.dumps({"default_map_skeleton": True}), encoding="utf-8"
    )
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))
    # project's explicit False must win even though the machine default is True (same
    # key-presence-wins precedence as docx/citations).
    assert _read_map_skeleton_toggle(tmp_path) is False


def test_map_skeleton_toggle_falls_back_to_machine_default(tmp_path, monkeypatch):
    xdg = tmp_path / "xdg"
    (xdg / "virt-surv-it").mkdir(parents=True)
    (xdg / "virt-surv-it" / "installer.json").write_text(
        json.dumps({"default_map_skeleton": True}), encoding="utf-8"
    )
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))
    assert _read_map_skeleton_toggle(tmp_path) is True


def test_map_skeleton_toggle_no_config_anywhere_is_false(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "empty-xdg"))
    assert _read_map_skeleton_toggle(tmp_path) is False


def _write_fingerprint_sidecar(repo, entries):
    """Sidecar lives NEXT TO the map file (repo/docs/, the standard map location used by
    every test below - m = repo / "docs" / "codebase-map.md"), matching exactly where
    scripts.repo_skeleton.write_fingerprints() writes it - see that function's own docstring
    for the 2026-08-06 bug this fixed (used to be repo/, silently wrong once the map isn't
    at the project root)."""
    docs = repo / "docs"
    docs.mkdir(exist_ok=True)
    (docs / "codebase-map.fingerprints.json").write_text(
        json.dumps({"generated_by": "test", "entries": entries}), encoding="utf-8"
    )


def test_map_drift_silent_when_fingerprint_matches(tmp_path):
    from scripts.map_fingerprint import compute_fingerprint

    repo, sha = _map_repo(tmp_path)
    (repo / "src").mkdir()
    (repo / "src" / "x.py").write_text("threshold = 1\n", encoding="utf-8")
    _write_fingerprint_sidecar(
        repo,
        {"rules": {"paths": ["src/x.py"], "fingerprint": compute_fingerprint(["src/x.py"], repo)}},
    )
    (repo / ".claude").mkdir()
    (repo / ".claude" / "team-preferences.json").write_text(
        json.dumps({"map_skeleton": True}), encoding="utf-8"
    )
    m = repo / "docs" / "codebase-map.md"
    _touch(m, _good_map_with_paths(sha))
    codes = "".join(check_map(m, project_dir=repo))
    assert "MAP-DRIFT" not in codes


def test_map_drift_fires_when_file_changed_since_fingerprinted(tmp_path):
    from scripts.map_fingerprint import compute_fingerprint

    repo, sha = _map_repo(tmp_path)
    (repo / "src").mkdir()
    f = repo / "src" / "x.py"
    f.write_text("threshold = 1\n", encoding="utf-8")
    _write_fingerprint_sidecar(
        repo,
        {"rules": {"paths": ["src/x.py"], "fingerprint": compute_fingerprint(["src/x.py"], repo)}},
    )
    f.write_text("threshold = 2\n", encoding="utf-8")  # changed AFTER fingerprinting
    (repo / ".claude").mkdir()
    (repo / ".claude" / "team-preferences.json").write_text(
        json.dumps({"map_skeleton": True}), encoding="utf-8"
    )
    m = repo / "docs" / "codebase-map.md"
    _touch(m, _good_map_with_paths(sha))
    codes = "".join(check_map(m, project_dir=repo))
    assert "MAP-DRIFT" in codes


def test_map_drift_fires_when_never_fingerprinted(tmp_path):
    repo, sha = _map_repo(tmp_path)
    (repo / "src").mkdir()
    (repo / "src" / "x.py").write_text("threshold = 1\n", encoding="utf-8")
    (repo / ".claude").mkdir()
    (repo / ".claude" / "team-preferences.json").write_text(
        json.dumps({"map_skeleton": True}), encoding="utf-8"
    )
    m = repo / "docs" / "codebase-map.md"
    _touch(m, _good_map_with_paths(sha))
    # No sidecar file written at all.
    codes = "".join(check_map(m, project_dir=repo))
    assert "MAP-DRIFT" in codes


def test_map_drift_corrupt_sidecar_surfaces_its_own_finding_not_never_fingerprinted(tmp_path):
    """M6 (2026-08 Fable audit): a PRESENT-but-corrupt fingerprints sidecar used to be
    caught by the same `except (OSError, ValueError)` as a genuinely MISSING one, both
    collapsing to `entries = {}` - so a corrupt sidecar produced the exact same
    "never fingerprinted" MAP-DRIFT text as no sidecar at all, hiding the real problem
    (the sidecar itself is broken) behind a misleading diagnosis."""
    repo, sha = _map_repo(tmp_path)
    (repo / "src").mkdir()
    (repo / "src" / "x.py").write_text("threshold = 1\n", encoding="utf-8")
    docs = repo / "docs"
    docs.mkdir()
    (docs / "codebase-map.fingerprints.json").write_text("{not valid json", encoding="utf-8")
    (repo / ".claude").mkdir()
    (repo / ".claude" / "team-preferences.json").write_text(
        json.dumps({"map_skeleton": True}), encoding="utf-8"
    )
    m = repo / "docs" / "codebase-map.md"
    _touch(m, _good_map_with_paths(sha))
    findings = check_map(m, project_dir=repo)
    codes = "".join(findings)
    assert "MAP-FINGERPRINTS-INVALID" in codes, (
        "a corrupt sidecar must surface its own distinct finding, not silently masquerade "
        "as 'never fingerprinted'"
    )


def test_map_dead_pointer_fires_on_missing_citation(tmp_path):
    repo, sha = _map_repo(tmp_path)
    (repo / ".claude").mkdir()
    (repo / ".claude" / "team-preferences.json").write_text(
        json.dumps({"map_skeleton": True}), encoding="utf-8"
    )
    m = repo / "docs" / "codebase-map.md"
    # No src/x.py file created - the citation is dead.
    _touch(m, _good_map_with_paths(sha, entry="described in `src/x.py:12`"))
    codes = "".join(check_map(m, project_dir=repo))
    assert "MAP-DEAD-POINTER" in codes


def test_map_dead_pointer_silent_when_citation_resolves(tmp_path):
    repo, sha = _map_repo(tmp_path)
    (repo / "src").mkdir()
    (repo / "src" / "x.py").write_text("threshold = 1\n", encoding="utf-8")
    (repo / ".claude").mkdir()
    (repo / ".claude" / "team-preferences.json").write_text(
        json.dumps({"map_skeleton": True}), encoding="utf-8"
    )
    m = repo / "docs" / "codebase-map.md"
    _touch(m, _good_map_with_paths(sha, entry="described in `src/x.py:12`"))
    codes = "".join(check_map(m, project_dir=repo))
    assert "MAP-DEAD-POINTER" not in codes


def test_map_drift_and_dead_pointer_excluded_from_apply_fixes(tmp_path):
    repo, sha = _map_repo(tmp_path)
    (repo / ".claude").mkdir()
    (repo / ".claude" / "team-preferences.json").write_text(
        json.dumps({"map_skeleton": True}), encoding="utf-8"
    )
    art = repo / "artifacts"
    m = repo / "docs" / "codebase-map.md"
    _touch(m, _good_map_with_paths(sha, entry="described in `src/x.py:12`"))
    # apply_fixes() takes an artifacts_dir, not a map_path - map hygiene was never wired into
    # it (existing precedent for every other MAP-* code); this just confirms that precedent
    # extends to the two new checks, not a behaviour change.
    assert apply_fixes(art) == []


# ---------------------------- docs/codebase-map.d/ area files (ADR-007 Phase 1 Chunk E) ----


def test_find_codebase_map_area_files_absent_directory_is_empty(tmp_path):
    assert find_codebase_map_area_files(tmp_path) == []


def test_find_codebase_map_area_files_discovers_and_sorts(tmp_path):
    area_dir = tmp_path / "docs" / "codebase-map.d"
    area_dir.mkdir(parents=True)
    (area_dir / "z-area.md").write_text("x", encoding="utf-8")
    (area_dir / "a-area.md").write_text("x", encoding="utf-8")
    (area_dir / "not-markdown.txt").write_text("x", encoding="utf-8")
    found = find_codebase_map_area_files(tmp_path)
    assert [p.name for p in found] == ["a-area.md", "z-area.md"]


def test_area_file_gets_the_same_hygiene_checks_as_the_root_map(tmp_path):
    """An area file with no As-of/Anchor header is exactly as invalid as a root map missing
    them - check_map() has no notion of "root" vs "area", it's generic per-file (this is
    the load-bearing property Chunk E relies on rather than duplicating check_map's logic)."""
    repo, sha = _map_repo(tmp_path)
    area_dir = repo / "docs" / "codebase-map.d"
    area_dir.mkdir(parents=True)
    area_file = area_dir / "scripts.md"
    area_file.write_text("# Area: scripts\n\nno header fields at all\n", encoding="utf-8")
    findings = check_map(area_file, project_dir=repo)
    assert any("MAP-NO-ASOF" in f for f in findings)
    assert any("MAP-NO-ANCHOR" in f for f in findings)


def test_main_checks_area_files_alongside_root_map(tmp_path, monkeypatch, capsys):
    repo, sha = _map_repo(tmp_path)
    m = repo / "docs" / "codebase-map.md"
    _touch(m, _good_map(sha))
    area_dir = repo / "docs" / "codebase-map.d"
    area_dir.mkdir(parents=True)
    bad_area = area_dir / "scripts.md"
    bad_area.write_text("# Area: scripts\n\nno header fields at all\n", encoding="utf-8")
    monkeypatch.chdir(repo)
    rc = ca_main(["artifacts"])
    out = capsys.readouterr().out
    assert rc == 1
    assert "MAP-NO-ASOF" in out and str(bad_area) in out


# --- two more bugs found live building Chunk E: MAP-DEAD-POINTER's "entry" column lookup was
# an exact-match .get() while every sibling column used a rename-tolerant substring search, so
# it never matched the documented template's own long header text - and the drift-row key
# required an "Area" column, which an area file's own template deliberately doesn't have (one
# area per file), so MAP-DRIFT could never fire there either. -------------------------------


def _area_map_with_paths(sha, entry="threshold rationale in `src/x.py:12`"):
    """Mirrors docs/templates/codebase-map-area.md's actual header text (the long
    descriptive "Entry (...)" column, an ID column instead of Area) - the exact shape the
    entry_idx/key_idx substring-lookup bugs were found against."""
    return (
        "# Codebase Map Area - Scripts\n\n"
        f"> **Document control** · Owner `Morgan (PM)` · As-of `2026-07-18` · Anchor `{sha}`\n\n"
        "## Entries\n\n"
        "| ID | Entry (a durable code fact - NOT a finding or an activity note) | Basis | As-of | Anchor | Paths (optional) |\n"
        "|----|-------|-------|-------|--------|-------|\n"
        f"| scripts-1 | {entry} | 📊 seen in review | 2026-07-18 | `{sha[:9]}` | src/x.py |\n"
    )


def test_map_dead_pointer_fires_against_the_documented_template_header(tmp_path):
    repo, sha = _map_repo(tmp_path)
    (repo / ".claude").mkdir()
    (repo / ".claude" / "team-preferences.json").write_text(
        json.dumps({"map_skeleton": True}), encoding="utf-8"
    )
    m = repo / "docs" / "codebase-map.md"
    # missing.py does not exist - a live dead pointer, using the TEMPLATE's real long header.
    _touch(m, _good_map_with_paths(sha, entry="described in `missing.py:1`"))
    findings = check_map(m, project_dir=repo)
    assert any("MAP-DEAD-POINTER" in f for f in findings)


def test_map_drift_keys_on_id_column_when_no_area_column_present(tmp_path):
    """An area file (docs/templates/codebase-map-area.md's shape: ID column, no Area
    column) must still get MAP-DRIFT - keyed on ID instead of Area."""
    repo, sha = _map_repo(tmp_path)
    (repo / "src").mkdir()
    (repo / "src" / "x.py").write_text("threshold = 1\n", encoding="utf-8")
    (repo / ".claude").mkdir()
    (repo / ".claude" / "team-preferences.json").write_text(
        json.dumps({"map_skeleton": True}), encoding="utf-8"
    )
    area_dir = repo / "docs" / "codebase-map.d"
    area_dir.mkdir(parents=True)
    m = area_dir / "scripts.md"
    _touch(m, _area_map_with_paths(sha))
    # never fingerprinted -> MAP-DRIFT, proving drift_rows was actually populated (keyed on
    # "scripts-1", the ID column) rather than silently skipped for lack of an Area column.
    findings = check_map(m, project_dir=repo)
    assert any("MAP-DRIFT" in f for f in findings)


# ------------------------------------------------ entry-anchor resolution is batched (2026-08-03)
#
# check_map()'s per-entry loop used to call _anchor_resolves (one `git cat-file -e`
# subprocess) PER ENTRY - a well-filled map could spawn 20-50 processes on every gated
# Stop event. Now one `git cat-file --batch-check` call resolves them all. No prior test
# covered MAP-STALE-ENTRY-ANCHOR at all (single-entry _good_map fixtures never exercised
# more than one SHA), so these are new coverage, not just a refactor regression net.


def test_multiple_entry_anchors_mixed_resolve_correctly(tmp_path):
    """Several entries, some resolving and some not, in ONE real repo - proves the batch
    call correctly attributes each result back to the right entry, not just a single-sha
    happy path."""
    repo, sha = _map_repo(tmp_path)
    m = repo / "docs" / "codebase-map.md"
    bogus = "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"
    _touch(
        m,
        _good_map(sha)
        + f"| 2 | etl | good entry | 📊 seen | 2026-07-18 | `{sha[:9]}` |\n"
        + f"| 3 | ml | stale entry | 📊 seen | 2026-07-18 | `{bogus[:9]}` |\n"
        + f"| 4 | tuning | another stale one | 📊 seen | 2026-07-18 | `{bogus}` |\n",
    )
    findings = check_map(m)
    stale = [f for f in findings if "MAP-STALE-ENTRY-ANCHOR" in f]
    assert len(stale) == 2  # rows 3 and 4 only - rows 1 (header) and 2 both resolve fine
    assert any(bogus[:9] in f for f in stale)  # the short-form bogus entry
    assert any(bogus in f for f in stale)  # the full-length bogus entry
    assert not any(sha[:9] in f for f in stale)  # the two genuinely-resolving entries are clean


def test_batch_resolve_shas_handles_mix_in_one_call(tmp_path):
    from scripts.check_artifacts import _batch_resolve_shas

    repo, sha = _map_repo(tmp_path)
    bogus = "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"
    result = _batch_resolve_shas([sha, bogus], repo)
    assert result[sha] is True
    assert result[bogus] is False


def test_batch_resolve_shas_empty_list_makes_no_subprocess_call(tmp_path, monkeypatch):
    import scripts.check_artifacts as ca

    def _boom(*a, **k):
        raise AssertionError("subprocess.run must not be called for an empty sha list")

    monkeypatch.setattr(ca.subprocess, "run", _boom)
    assert ca._batch_resolve_shas([], tmp_path) == {}


def test_batch_resolve_shas_outside_git_returns_none_for_every_sha(tmp_path):
    from scripts.check_artifacts import _batch_resolve_shas

    result = _batch_resolve_shas(["deadbeefdeadbeefdeadbeefdeadbeefdeadbeef", "abc123"], tmp_path)
    assert result == {"deadbeefdeadbeefdeadbeefdeadbeefdeadbeef": None, "abc123": None}


def test_many_entry_anchors_spawn_exactly_one_subprocess(tmp_path, monkeypatch):
    """The actual performance property: N entries must cost ONE git process, not N."""
    repo, sha = _map_repo(tmp_path)
    m = repo / "docs" / "codebase-map.md"
    rows = "".join(
        f"| {i} | area{i} | entry {i} | 📊 seen | 2026-07-18 | `{sha[:9]}` |\n"
        for i in range(2, 12)
    )
    _touch(m, _good_map(sha) + rows)

    import scripts.check_artifacts as ca

    calls = []
    real_run = ca.subprocess.run

    def _counting_run(cmd, *a, **k):
        if isinstance(cmd, list) and "cat-file" in cmd:
            calls.append(cmd)
        return real_run(cmd, *a, **k)

    monkeypatch.setattr(ca.subprocess, "run", _counting_run)
    findings = check_map(m)
    assert not any("MAP-STALE-ENTRY-ANCHOR" in f for f in findings)  # all 10 entries resolve
    batch_calls = [c for c in calls if any(str(a).startswith("--batch-check") for a in c)]
    assert len(batch_calls) == 1  # ten entries, one subprocess


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


def test_stale_docstatus_pending_flagged_when_closed(tmp_path):
    # Live report 2026-08-03: a closed delivery-report.md and its .html both still read
    # `Status `Pending`` - no template's placeholder uses this word, so it was scaffolding
    # text the author never went back to fill in. The regex used to only check for
    # draft/in review/in progress and silently missed this class of leftover entirely.
    art = tmp_path / "artifacts"
    _index(art, status=STATUS_CLOSED, listed=["delivery-report.md", "engagement-summary-x.txt"])
    _touch(
        art / "delivery-report.md",
        "# Report\n\n> **Document control** · ID `DLVR-001` · Version `1.0` · Status `Pending`\n",
    )
    _touch(art / "delivery-report.html", "<html></html>")
    _touch(art / "engagement-summary-x.txt", "Hi,\n\nMorgan\n")
    assert "STALE-DOCSTATUS" in "\n".join(check(art))


def test_stale_docstatus_bare_pending_human_signoff_passes(tmp_path):
    # Symmetric with the Draft/In review case: `pending` immediately followed by `human
    # sign-off` is the same legitimate terminal state, even with no preceding status word.
    art = tmp_path / "artifacts"
    _index(art, status=STATUS_CLOSED, listed=["delivery-report.md", "engagement-summary-x.txt"])
    _touch(
        art / "delivery-report.md",
        "# Report\n\n> **Document control** · ID `DLVR-001` · Version `1.0` · "
        "Status `Pending human sign-off`\n",
    )
    _touch(art / "delivery-report.html", "<html></html>")
    _touch(art / "engagement-summary-x.txt", "Hi,\n\nMorgan\n")
    assert "STALE-DOCSTATUS" not in "\n".join(check(art))


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


# ------------------------------------------------ findings-pack validation is in-process (2026-08-03)
#
# check_findings_packs() used to shell out to validate_findings.py as a SEPARATE subprocess
# PER PACK - several review passes/re-reviews means several packs, so several process spawns
# on every gated Stop event. Now calls validate_findings.load_and_validate() in-process.


def test_findings_pack_validation_never_spawns_a_subprocess(tmp_path, monkeypatch):
    from scripts.check_artifacts import check_findings_packs

    art = tmp_path / "artifacts"
    _pack(art, _VALID_PACK)
    bad = copy.deepcopy(_VALID_PACK)
    del bad["findings"][0]["likely_cause"]
    _pack(art, bad, name="findings-bad.jsonl")

    def _boom(*a, **k):
        raise AssertionError("subprocess.run must not be called for findings-pack validation")

    monkeypatch.setattr("scripts.check_artifacts.subprocess.run", _boom)
    findings = check_findings_packs(art)
    assert any("findings-bad.jsonl" in f for f in findings)
    assert not any("findings-t.jsonl" in f for f in findings)  # the valid pack stays clean


def test_findings_pack_validation_handles_multiple_packs(tmp_path):
    from scripts.check_artifacts import check_findings_packs

    art = tmp_path / "artifacts"
    _pack(art, _VALID_PACK, name="findings-a.jsonl")
    _pack(art, _VALID_PACK, name="findings-b.jsonl")
    bad = copy.deepcopy(_VALID_PACK)
    del bad["findings"][0]["standard"]
    _pack(art, bad, name="findings-c.jsonl")

    findings = check_findings_packs(art)
    assert len(findings) == 1
    assert "findings-c.jsonl" in findings[0]


def test_findings_pack_unreadable_json_reports_cannot_parse(tmp_path):
    from scripts.check_artifacts import check_findings_packs

    art = tmp_path / "artifacts"
    d = art / "data"
    d.mkdir(parents=True)
    (d / "findings-broken.jsonl").write_text("{not valid json", encoding="utf-8")

    findings = check_findings_packs(art)
    assert len(findings) == 1
    assert "FINDINGS-INVALID" in findings[0]
    assert "findings-broken.jsonl" in findings[0]
    assert "cannot read/parse" in findings[0]


def test_findings_pack_validator_loader_is_memoized_across_calls(monkeypatch):
    import scripts.check_artifacts as ca

    _block_scripts_import(monkeypatch, "validate_findings")
    monkeypatch.setattr(ca, "_VALIDATE_FINDINGS_MODULE_CACHE", None)
    exec_calls = _counting_spec_from_file_location(monkeypatch)

    first = ca._load_validate_findings_module()
    second = ca._load_validate_findings_module()

    assert first is not None
    assert first is second
    assert len(exec_calls) == 1


# ---------------------------------------- review-scorer attestation (PACK-UNSCORED)
#
# 2026-08-08: two live /engage runs skipped the review-scorer delegation entirely, after two
# prose strengthenings of the same rule - so the evidence is now mechanical: a scored-kind
# pack with findings must record the scorer pass in its envelope `scoring` field.


def test_scored_kind_pack_without_scoring_record_flagged(tmp_path):
    from scripts.check_artifacts import check_findings_scoring

    art = tmp_path / "artifacts"
    _pack(art, _VALID_PACK)
    findings = check_findings_scoring(art)
    assert len(findings) == 1
    assert "PACK-UNSCORED" in findings[0] and "findings-t.jsonl" in findings[0]


def test_scoring_record_naming_review_scorer_passes(tmp_path):
    from scripts.check_artifacts import check_findings_scoring

    art = tmp_path / "artifacts"
    ok = copy.deepcopy(_VALID_PACK)
    ok["scoring"] = "scored by review-scorer: Found 3 · Reported 1 · Filtered 2"
    _pack(art, ok)
    assert check_findings_scoring(art) == []


def test_self_scored_record_still_flagged(tmp_path):
    # docs/code-review-method.md: the scorer still runs even after self-scoring - a
    # self-score note is provenance, not a scorer pass.
    from scripts.check_artifacts import check_findings_scoring

    art = tmp_path / "artifacts"
    selfscored = copy.deepcopy(_VALID_PACK)
    selfscored["scoring"] = "self-scored against the rubric; no scorer in the loop"
    _pack(art, selfscored)
    findings = check_findings_scoring(art)
    assert len(findings) == 1 and "PACK-UNSCORED" in findings[0]


def test_performance_kind_is_a_scored_kind(tmp_path):
    from scripts.check_artifacts import check_findings_scoring

    art = tmp_path / "artifacts"
    perf = copy.deepcopy(_VALID_PACK)
    perf["kind"] = "performance"
    _pack(art, perf, name="findings-performance-t.jsonl")
    findings = check_findings_scoring(art)
    assert len(findings) == 1 and "PACK-UNSCORED" in findings[0]


def test_compliance_and_model_validation_packs_exempt(tmp_path):
    # Their findings are never score-filtered; the scorer's dedup pass over them is optional.
    from scripts.check_artifacts import check_findings_scoring

    art = tmp_path / "artifacts"
    for kind, name in (
        ("compliance", "findings-compliance-t.jsonl"),
        ("model-validation", "findings-model-validation-t.jsonl"),
    ):
        p = copy.deepcopy(_VALID_PACK)
        p["kind"] = kind
        _pack(art, p, name=name)
    assert check_findings_scoring(art) == []


def test_empty_findings_pack_needs_no_scoring_record(tmp_path):
    from scripts.check_artifacts import check_findings_scoring

    art = tmp_path / "artifacts"
    clean = copy.deepcopy(_VALID_PACK)
    clean["findings"] = []
    _pack(art, clean)
    assert check_findings_scoring(art) == []


def test_unparseable_pack_left_to_findings_invalid(tmp_path):
    from scripts.check_artifacts import check_findings_scoring

    art = tmp_path / "artifacts"
    d = art / "data"
    d.mkdir(parents=True)
    (d / "findings-broken.jsonl").write_text("{not json", encoding="utf-8")
    assert check_findings_scoring(art) == []


def test_pack_unscored_surfaces_via_check(tmp_path):
    art = tmp_path / "artifacts"
    _index(art, status=STATUS_OPEN)
    _pack(art, _VALID_PACK)
    assert any("PACK-UNSCORED" in f for f in check(art))


def test_data_subfolder_pack_not_treated_as_deliverable(tmp_path):
    # A .json pack under data/ must not trip MISSING-HTML or STALE-INDEX (it's machine source).
    art = tmp_path / "artifacts"
    _index(art, listed=["engagement-summary-t.txt"])
    _touch(art / "engagement-summary-t.txt", "Hi,\n\nMorgan\n")
    scored = copy.deepcopy(_VALID_PACK)  # scored, so PACK-UNSCORED can't name the file either
    scored["scoring"] = "scored by review-scorer: Found 1 · Reported 1 · Filtered 0"
    _pack(art, scored)
    joined = "\n".join(check(art))
    assert "findings-t.jsonl" not in joined  # never named by MISSING-HTML / STALE-INDEX


def test_apply_fixes_never_touches_an_archived_nested_pack(tmp_path):
    """C7 (2026-08 audit): apply_fixes()'s rglobs did not exclude .archive'd subtrees the
    way check()'s equivalent scans do - archived is meant to be frozen, but --fix would
    rename a mis-typed summary email, DELETE a stray rendered .html copy, and render new
    .html siblings inside an archived pack it should never touch at all."""
    art = tmp_path / "artifacts"
    _index(art, listed=["review-pass-1.md"])
    _touch(art / "review-pass-1.md", "# Review\n")
    _touch(art / "review-pass-1.html")

    archived = art / "old-engagement"
    _touch(archived / "engagement-summary-old.md", "Hi,\n\nDone.\n")  # would be renamed
    _touch(archived / "engagement-summary-stray.html")  # would be DELETED
    _touch(archived / "notes.md", "# notes\n")  # would get a new .html rendered
    _touch(archived / ".archive", "archived\n")

    apply_fixes(art)

    assert (archived / "engagement-summary-old.md").is_file()  # not renamed
    assert not (archived / "engagement-summary-old.txt").exists()
    assert (archived / "engagement-summary-stray.html").is_file()  # not deleted
    assert not (archived / "notes.html").exists()  # not rendered


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


def test_apply_fixes_invalid_pack_does_not_crash_or_get_flagged(tmp_path):
    art = tmp_path / "artifacts"
    _index(art, status="🔒 CLOSING - finishing close artifacts")
    bad = copy.deepcopy(_VALID_PACK)
    del bad["findings"][0]["likely_cause"]
    _pack(art, bad)
    fixed = "\n".join(apply_fixes(art))  # must not crash; FINDINGS-INVALID reports it, not this
    assert "FIXED: rendered" not in fixed
    assert not (art / "REVIEW-t.md").exists()


# --------------------------------------- findings/HTML rendering is in-process (2026-08-05)
#
# apply_fixes() used to shell out to render_findings.py (once per pack) and render_html.py
# (once per un-rendered .md) as SEPARATE subprocesses - on a host where every python.exe spawn
# is inflated by endpoint-security scanning (corp Windows), a handover pack with several
# deliverables chained enough untimed spawns to present as the whole close step hanging. Now
# calls render_findings.render_pack_file() / render_html.render_file() in-process.


def test_apply_fixes_never_spawns_a_subprocess_for_rendering(tmp_path, monkeypatch):
    import scripts.check_artifacts as ca

    art = tmp_path / "artifacts"
    _index(art, status="🔒 CLOSING - finishing close artifacts", listed=["notes.md"])
    _pack(art, _VALID_PACK)  # slug "t" -> renders REVIEW-t.md, then REVIEW-t.html
    _touch(art / "notes.md", "# Notes\n")  # a second .md missing its .html sibling

    def _boom(*a, **k):
        raise AssertionError("subprocess.run must not be called for rendering")

    monkeypatch.setattr(ca.subprocess, "run", _boom)
    fixed = apply_fixes(art)

    assert (art / "REVIEW-t.md").is_file()
    assert (art / "REVIEW-t.html").is_file()
    assert (art / "notes.html").is_file()
    assert any("REVIEW-t.md" in f or "REVIEW-t" in f for f in fixed)
    assert any("notes.md -> notes.html" in f for f in fixed)


def test_render_findings_loader_is_memoized_across_calls(monkeypatch):
    import scripts.check_artifacts as ca

    _block_scripts_import(monkeypatch, "render_findings")
    monkeypatch.setattr(ca, "_RENDER_FINDINGS_MODULE_CACHE", None)
    exec_calls = _counting_spec_from_file_location(monkeypatch)

    first = ca._load_render_findings_module()
    second = ca._load_render_findings_module()

    assert first is not None
    assert first is second
    assert len(exec_calls) == 1


def test_render_html_loader_is_memoized_across_calls(monkeypatch):
    import scripts.check_artifacts as ca

    _block_scripts_import(monkeypatch, "render_html")
    monkeypatch.setattr(ca, "_RENDER_HTML_MODULE_CACHE", None)
    exec_calls = _counting_spec_from_file_location(monkeypatch)

    first = ca._load_render_html_module()
    second = ca._load_render_html_module()

    assert first is not None
    assert first is second
    assert len(exec_calls) == 1


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


# ------------------------------------------------ summary email identity (2026-07-30)

from pathlib import Path  # noqa: E402


MORGAN_EMAIL = """To:        Daniel
From:      🤖 Morgan - PM & Orchestrator, Virtual Surveillance IT (AI agent, not a human)
Subject:   Review complete

Hi Daniel,

The review is complete. 🤖 Yuki (data-quality-reviewer) confirmed coverage.

🤖 Morgan
PM & Orchestrator - Virtual Surveillance IT (AI agent)
"""


def test_summary_email_from_morgan_passes():
    from scripts.check_artifacts import check_summary_email

    assert check_summary_email(MORGAN_EMAIL, Path("e.txt")) == []


def test_summary_email_signed_by_human_fires():
    """The live failure: the email went out signed by the requester, not Morgan."""
    from scripts.check_artifacts import check_summary_email

    text = MORGAN_EMAIL.replace(
        "🤖 Morgan\nPM & Orchestrator - Virtual Surveillance IT (AI agent)\n",
        "Best regards,\nDaniel\n",
    ).replace("From:      🤖 Morgan - PM & Orchestrator", "From:      Daniel")
    codes = [f.split(":")[0] for f in check_summary_email(text, Path("e.txt"))]
    assert codes.count("EMAIL-NOT-MORGAN") == 2  # From line AND sign-off


def test_summary_email_unmarked_agent_mention_fires():
    """User rule 2026-07-30: any agent mentioned in the body carries 🤖."""
    from scripts.check_artifacts import check_summary_email

    text = MORGAN_EMAIL.replace("🤖 Yuki", "Yuki")
    findings = check_summary_email(text, Path("e.txt"))
    assert any("EMAIL-AGENT-UNMARKED" in f and "Yuki" in f for f in findings)
    # Morgan is marked in the signature, so no Morgan finding
    assert not any("'Morgan'" in f for f in findings)


def test_summary_email_checked_inside_pack(tmp_path):
    """The email content check runs as part of the artifacts scan (and so as part of
    the close gate)."""
    pack = tmp_path / "artifacts" / "eng-x"
    pack.mkdir(parents=True)
    (pack / "engagement-summary-eng-x.txt").write_text(
        "Hi,\n\nAll done.\n\nBest,\nDaniel\n", encoding="utf-8"
    )
    findings = check(tmp_path / "artifacts")
    assert any("EMAIL-NOT-MORGAN" in f for f in findings)


def test_registry_html_mirror_staleness_flagged(tmp_path):
    """The HTML mirror is best-effort at write time (silently skipped when render libs
    are missing) - so the checker must flag a missing or older ENGAGEMENTS.html
    (user report 2026-07-30)."""
    import os
    import time

    art = _ws(tmp_path, "audit")
    from scripts.engagement_state import render_registry

    render_registry(art)
    md, html = art / "ENGAGEMENTS.md", art / "ENGAGEMENTS.html"
    assert md.is_file()
    if html.is_file():  # render libs present in dev env: exercise both variants
        assert check_registry(art) == []
        old = time.time() - 3600
        os.utime(html, (old, old))
        assert any("REGISTRY-HTML-STALE" in f and "older" in f for f in check_registry(art))
        html.unlink()
    findings = check_registry(art)
    assert any("REGISTRY-HTML-STALE" in f and "no rendered .html" in f for f in findings)
    assert any("pip install -r requirements.txt" in f for f in findings)


# ------------------------------------------------ developer-guidance check (audit #2)


def test_dev_guidance_missing_heading_fires(tmp_path):
    from scripts.check_artifacts import check_summary_email as _unused  # noqa: F401
    from scripts.check_artifacts import check as run_check

    art = tmp_path / "artifacts"
    art.mkdir()
    review = art / "REVIEW-x.md"
    review.write_text(
        "# Review\n\n## Findings\n\n_No findings._\n\n## Limitations & residual risk\n"
        "_(none stated)_\n",
        encoding="utf-8",
    )
    (review.with_suffix(".html")).write_text("<p>x</p>", encoding="utf-8")
    _index(art, listed=["REVIEW-x.md"])
    findings = run_check(art)
    assert any(
        "FINDINGS-NO-DEV-GUIDANCE" in f and "no '## 🔵 Developer guidance'" in f for f in findings
    )


def test_dev_guidance_placeholder_only_fires(tmp_path):
    from scripts.check_artifacts import check as run_check

    art = tmp_path / "artifacts"
    art.mkdir()
    review = art / "REVIEW-x.md"
    review.write_text(
        "# Review\n\n## Findings\n\n_No findings._\n\n"
        "## 🔵 Developer guidance - improving future code\n_(none provided)_\n\n"
        "## Limitations & residual risk\n_(none stated)_\n",
        encoding="utf-8",
    )
    (review.with_suffix(".html")).write_text("<p>x</p>", encoding="utf-8")
    _index(art, listed=["REVIEW-x.md"])
    findings = run_check(art)
    assert any("FINDINGS-NO-DEV-GUIDANCE" in f and "empty/unfilled" in f for f in findings)


def test_dev_guidance_filled_in_passes(tmp_path):
    from scripts.check_artifacts import check as run_check

    art = tmp_path / "artifacts"
    art.mkdir()
    review = art / "REVIEW-x.md"
    review.write_text(
        "# Review\n\n## Findings\n\n_No findings._\n\n"
        "## 🔵 Developer guidance - improving future code\n"
        "Consider adding docstrings to the public API.\n\n"
        "## Limitations & residual risk\n_(none stated)_\n",
        encoding="utf-8",
    )
    (review.with_suffix(".html")).write_text("<p>x</p>", encoding="utf-8")
    _index(art, listed=["REVIEW-x.md"])
    findings = run_check(art)
    assert not any("FINDINGS-NO-DEV-GUIDANCE" in f for f in findings)


def test_non_review_artifact_without_findings_section_unaffected(tmp_path):
    """A BRD/FSD has no '## Findings' section at all - never flagged for lacking
    developer guidance, which is a review-only concept."""
    from scripts.check_artifacts import check as run_check

    art = tmp_path / "artifacts"
    art.mkdir()
    brd = art / "BRD-x.md"
    brd.write_text("# BRD\n\n## Executive summary\n\nSomething.\n", encoding="utf-8")
    (brd.with_suffix(".html")).write_text("<p>x</p>", encoding="utf-8")
    _index(art, listed=["BRD-x.md"])
    findings = run_check(art)
    assert not any("FINDINGS-NO-DEV-GUIDANCE" in f for f in findings)


# --------------------------------------------------------------- RTM traceability gate


_RTM_HEADER = (
    "| BRD | FSD | Design / ADR | Code (module / fn) | Test | Regulatory obligation "
    "| Status | Gap / exception disposition |\n|---|---|---|---|---|---|---|---|\n"
)


def _rtm_pack(
    tmp_path,
    code,
    test="`tests/test_spoofing.py::test_x`",
    obligation="MAR Art.12(1)(a)",
):
    """An engagement pack carrying an RTM whose cells resolve against THIS repo (the working
    project a check_artifacts run sees), so the gate's disk resolution is exercised for real."""
    art = tmp_path / "artifacts"
    art.mkdir()
    _touch(
        art / "rtm.md",
        "# RTM\n\n"
        + _RTM_HEADER
        + f"| BRD-001 | FSD-001 | ADR-001 | {code} | {test} | {obligation} | done | - |\n",
    )
    _touch(art / "rtm.html")
    _index(art, status=STATUS_OPEN, listed=["rtm.md"])
    return art


def test_pack_without_an_rtm_raises_no_rtm_finding(tmp_path):
    """Absence is the normal case - most engagements never author an RTM, and the gate must
    stay silent for them (this is the check that keeps it non-blocking by default)."""
    art = tmp_path / "artifacts"
    _touch(art / "review-pass-1.md")
    _touch(art / "review-pass-1.html")
    _index(art, status=STATUS_OPEN, listed=["review-pass-1.md"])
    assert not any(f.startswith("RTM-") for f in check(art))


def test_rtm_that_traces_is_silent(tmp_path):
    from scripts.check_artifacts import check_rtm

    art = _rtm_pack(tmp_path, code="`rules/spoofing.py::detect_spoofing`")
    assert check_rtm(art) == []


def test_rtm_with_a_broken_code_path_is_unresolved(tmp_path):
    art = _rtm_pack(tmp_path, code="`rules/renamed.py::detect_spoofing`")
    findings = [f for f in check(art) if f.startswith("RTM-")]
    assert len(findings) == 1
    assert findings[0].startswith("RTM-UNRESOLVED: rtm.md")
    assert "rules/renamed.py" in findings[0]
    assert "scripts.validate_rtm" in findings[0]


def test_rtm_with_a_broken_test_path_is_unresolved(tmp_path):
    from scripts.check_artifacts import check_rtm

    art = _rtm_pack(tmp_path, code="`rules/spoofing.py`", test="`tests/test_gone.py::test_x`")
    findings = check_rtm(art)
    assert len(findings) == 1 and findings[0].startswith("RTM-UNRESOLVED")


def test_rtm_row_without_an_obligation_is_incomplete(tmp_path):
    from scripts.check_artifacts import check_rtm

    art = _rtm_pack(tmp_path, code="`rules/spoofing.py`", obligation="-")
    findings = check_rtm(art)
    assert len(findings) == 1
    assert findings[0].startswith("RTM-INCOMPLETE: rtm.md")
    assert "no regulatory/business obligation" in findings[0]


def test_unparseable_rtm_is_incomplete(tmp_path):
    from scripts.check_artifacts import check_rtm

    art = tmp_path / "artifacts"
    art.mkdir()
    _touch(art / "rtm.md", "# RTM\n\nThe matrix is coming.\n")
    findings = check_rtm(art)
    assert len(findings) == 1 and findings[0].startswith("RTM-INCOMPLETE")


def test_orphan_sweeps_stay_out_of_the_gate(tmp_path):
    """validate_rtm also reports RTM-ORPHAN-OBLIGATION / RTM-ORPHAN-TEST; both are
    scope-dependent (a firm-wide register, a project-wide suite) and must not fire here -
    an engagement RTM covering one scenario is not delinquent for the other 8 obligations."""
    from scripts.check_artifacts import check_rtm

    art = _rtm_pack(tmp_path, code="`rules/spoofing.py::detect_spoofing`")
    assert not any("ORPHAN" in f for f in check_rtm(art))


def test_archived_rtm_is_not_checked(tmp_path):
    from scripts.check_artifacts import check_rtm

    art = _rtm_pack(tmp_path, code="`rules/renamed.py`")
    (art / ".archive").write_text("archived\n", encoding="utf-8")
    assert check_rtm(art) == []


# ------------------------------------------------ module-loader memoization (2026-08-03 perf audit)
#
# _load_engagement_state_module / _load_validate_rtm_module are called many times across one
# check_artifacts run (check_state, check_registry, check_root_orphans, check_rtm, ...). The
# fast `from scripts import X` branch is already cached by Python's own import machinery; the
# __file__-relative FALLBACK (taken in plugin mode, where no `scripts` package resolves) used
# to re-parse and re-exec the whole file on every call. These tests force the fallback branch
# by intercepting __import__ itself for the exact `from scripts import X` call (poisoning
# sys.modules alone is NOT reliable here: once a real prior test has genuinely imported
# scripts.engagement_state, CPython caches it as an attribute on the `scripts` package
# object too, and `from scripts import X` can resolve via that attribute without ever
# consulting sys.modules again - order-dependent and exactly the kind of flake this test
# must not have). Proves the SAME module object comes back on a second call, with
# exec_module invoked only once.


def _block_scripts_import(monkeypatch, blocked_name: str) -> None:
    import builtins

    real_import = builtins.__import__

    def _guarded(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "scripts" and fromlist and blocked_name in fromlist:
            raise ImportError(f"blocked for test: scripts.{blocked_name}")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _guarded)


def _counting_spec_from_file_location(monkeypatch):
    import importlib.util

    exec_calls = []
    orig = importlib.util.spec_from_file_location

    def _counting(*a, **k):
        spec = orig(*a, **k)
        orig_exec = spec.loader.exec_module

        def _counted_exec(module):
            exec_calls.append(1)
            return orig_exec(module)

        spec.loader.exec_module = _counted_exec
        return spec

    monkeypatch.setattr(importlib.util, "spec_from_file_location", _counting)
    return exec_calls


def test_engagement_state_loader_is_memoized_across_calls(monkeypatch):
    import scripts.check_artifacts as ca

    _block_scripts_import(monkeypatch, "engagement_state")
    monkeypatch.setattr(ca, "_ENGAGEMENT_STATE_MODULE_CACHE", None)  # start uncached
    exec_calls = _counting_spec_from_file_location(monkeypatch)

    first = ca._load_engagement_state_module()
    second = ca._load_engagement_state_module()

    assert first is not None
    assert first is second  # same object, not two independent re-execs
    assert len(exec_calls) == 1  # the file was only ever parsed+executed once


def test_validate_rtm_loader_is_memoized_across_calls(monkeypatch):
    import scripts.check_artifacts as ca

    _block_scripts_import(monkeypatch, "validate_rtm")
    monkeypatch.setattr(ca, "_VALIDATE_RTM_MODULE_CACHE", None)
    exec_calls = _counting_spec_from_file_location(monkeypatch)

    first = ca._load_validate_rtm_module()
    second = ca._load_validate_rtm_module()

    assert first is not None
    assert first is second
    assert len(exec_calls) == 1


# ------------------------------------------------ check() shares ONE *.md walk (2026-08-03 perf audit)
#
# check_state() -> _check_ratified_claims() and check_rtm() each used to independently
# rglob("*.md") the same tree check() itself also scans - three (or more, with a pending
# ratification in play) separate full walks per gated Stop event. check() now walks once
# and passes the list down; each sub-check applies its OWN unchanged filter to it.


def test_check_walks_for_md_files_exactly_once(tmp_path, monkeypatch):
    """The decisive proof: build a pack that exercises check_state (with a pending
    ratification, so _check_ratified_claims's OWN scan is reached) and check_rtm (a real
    rtm.md) together, then count how many times Path.rglob("*.md") actually executes."""
    from scripts.engagement_state import main as es_main

    art = tmp_path / "artifacts"
    assert es_main(["--dir", str(art), "init", "--title", "T", "--slug", "t"]) == 0
    state_path = art / "engagement-state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["ratifications"] = [{"status": "pending", "text": "ops-lead sign-off pending review"}]
    state_path.write_text(json.dumps(state), encoding="utf-8")
    _touch(art / "rtm.md", "# RTM\n\n| Req | Code | Test | Obligation |\n|---|---|---|---|\n")

    real_rglob = Path.rglob
    calls = []

    def _counting_rglob(self, pattern, *a, **k):
        if pattern == "*.md":
            calls.append(self)
        return real_rglob(self, pattern, *a, **k)

    monkeypatch.setattr(Path, "rglob", _counting_rglob)
    check(art)
    md_walks_of_artifacts_dir = [c for c in calls if c == art]
    assert len(md_walks_of_artifacts_dir) == 1, (
        f"expected exactly one rglob('*.md') walk of {art}, got {len(md_walks_of_artifacts_dir)}"
    )


def test_check_state_standalone_call_still_works_without_shared_walk(tmp_path):
    """A direct call (as many other tests in this file make) must behave identically to
    going through check() - _all_md defaulting to None must walk fresh, not skip the scan."""
    from scripts.check_artifacts import check_state
    from scripts.engagement_state import main as es_main

    art = tmp_path / "artifacts"
    assert es_main(["--dir", str(art), "init", "--title", "T", "--slug", "t"]) == 0
    state_path = art / "engagement-state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["ratifications"] = [{"status": "pending", "text": "ops-lead sign-off pending review"}]
    state_path.write_text(json.dumps(state), encoding="utf-8")
    _touch(art / "fsd.md", "The change was already ratified by ops-lead sign-off.\n")

    findings = check_state(art)  # no _all_md - must still find it via its own fresh walk
    assert any("RATIFIED-CLAIM-PENDING" in f for f in findings)


# ---------------------------- unrecognized --flag is a usage error (2026-08-07) ------------
#
# Found by a framework-wide audit: `do_fix = "--fix" in argv[1:]` matched only the exact
# string, so a typo'd flag was silently ignored - `check_artifacts --fx` ran a silent
# check-only pass instead of the fix pass the human asked for, with no error explaining why
# nothing got fixed.


def test_typo_fix_flag_is_a_usage_error_not_a_silent_no_op(tmp_path, capsys):
    art = tmp_path / "artifacts"
    art.mkdir()
    # argv[0] is the discarded "program name", matching every real invocation
    # (`python -m scripts.check_artifacts ...`) and this file's own existing convention
    # (e.g. ca_main(["check_artifacts", str(art)])) - omitting it would silently drop the
    # directory argument into the discarded slot instead of testing it.
    rc = ca_main(["check_artifacts", str(art), "--fx"])
    assert rc == 2
    assert "unrecognized flag" in capsys.readouterr().err


def test_unknown_flag_is_a_usage_error(tmp_path, capsys):
    art = tmp_path / "artifacts"
    art.mkdir()
    rc = ca_main(["check_artifacts", str(art), "--verbose"])
    assert rc == 2
    assert "unrecognized flag" in capsys.readouterr().err


def test_real_fix_flag_still_works(tmp_path):
    art = tmp_path / "artifacts"
    art.mkdir()
    rc = ca_main(["check_artifacts", str(art), "--fix"])
    assert rc in (0, 1)  # never 2 - a real, recognized flag is not a usage error


def test_no_flags_still_works(tmp_path):
    art = tmp_path / "artifacts"
    art.mkdir()
    rc = ca_main(["check_artifacts", str(art)])
    assert rc in (0, 1)
