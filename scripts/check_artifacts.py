#!/usr/bin/env python3
"""
Mechanical Definition-of-Done check for the artifact gates CI can never see.

`artifacts/` is deliberately git-ignored (engagement deliverables never leave the box), so no
CI job can verify the DoD's "Distributable" and "Engagement-summary email" items - and the
codebase map lives in the *working* project, which our CI never sees either. This script is
the one-command check the PM runs at the gate instead (docs/DEFINITION-OF-DONE.md):

  1. every `artifacts/**/*.md` has a rendered `.html` sibling (same stem, same directory) -
     the `.md` + `.html` dual-artifact rule (CLAUDE.md §8);
  2. the START-HERE living index exists from the FIRST artifact onward, carries an
     engagement Status (⏳ in progress / ⛔ blocked / 🔒 closing / ✅ closed), and stays
     current: every artifact file is listed in it, every local link in it resolves. Born of
     a live failure (2026-07-22): an engagement stalled on an unanswered clarification, the
     user read an interim report as the delivery, and QA never ran - state must be visible;
  3. close-only artifacts stay close-only: `delivery-report*.md` / `final-*` and the
     `engagement-summary-*.txt` email may exist only when the Status is 🔒 closing or
     ✅ closed (before that they mislabel work-in-progress as a delivery). A pack with NO
     readable status - including no index at all - is treated as NOT closed (fail-safe,
     2026-07-29 register G1: the pack whose team forgot the index is exactly the pack this
     guard exists for);
  4. at least one `engagement-summary-*.txt` exists once the engagement is ✅ closed - the
     required closing email, §6a;
  5. if the working project has a codebase map (ADR-003: `docs/codebase-map.md` or root
     `CODEBASE-MAP.md`), it passes mechanical hygiene: bounded size, an As-of date and a
     commit-SHA anchor in the header, 📊/🧠 basis tags on map entries, no secret-shaped
     content, and (best effort, when `git` is available) an anchor that still resolves.
     A missing map is NOT a failure - first engagements create it at close.
  6. the engagement-summary email is a `.txt` (the one artifact never rendered to HTML) - a
     `.md`/`.html` email is `SUMMARY-WRONG-EXT`; the email is always FROM Morgan
     (`EMAIL-NOT-MORGAN`) and every roster name it mentions carries a 🤖-marked mention
     (`EMAIL-AGENT-UNMARKED`) - it is the pack's most-forwarded artifact;
  7. once the engagement is ✅ closed, no content artifact still carries a mutable interim/
     in-progress status banner - the status lives only in START-HERE (`STALE-STATUS`);
  8. any structured findings pack under `artifacts/data/findings-*.jsonl` validates against
     `docs/review/findings-schema.json` (`FINDINGS-INVALID`) - the pack is the source of truth a
     report is rendered from. (`artifacts/data/` is machine-readable source; the top-level
     `artifacts/` stays user-navigable .md/.txt/.html and is what the .html-sibling + index checks
     cover - the data/ subtree is excluded from them.)
  9. AI identity is explicit: an artifact attributing work to a team persona carries a 🤖
     marker (`AGENT-UNMARKED`), and no line joins an agent and a human with `+`/`&`
     (`AGENT-HUMAN-COMBINED`) - roster names must never read as real people, and an agent
     never shares a sign-off line with the human approver (operating guide, "Voice, names
     & console");
 10. an RTM in the pack actually traces: every Code/Test cell resolves to a file on disk
     (`RTM-UNRESOLVED`) and every requirement carries an obligation or a gap disposition,
     in a table that parses (`RTM-INCOMPLETE`) - the BRD → FSD → code → test → obligation
     spine is the audit "golden thread", and until this it was asserted by nobody.
     Delegated to `scripts.validate_rtm`; a pack with no RTM raises nothing (most
     engagements never author one), and that script's advisory orphan-obligation /
     orphan-test sweeps stay out of the gate (scope-dependent, run them by hand).
 11. in workspace mode, no file sits unchecked in the artifacts ROOT: a root file outside
     every `artifacts/<slug>/` workspace is `ORPHAN-ARTIFACT` unless grandfathered in the
     snapshot allowlist `.dod-root-allowlist.json`, taken on the rule's first run (D2
     ruling 2026-07-29: pre-existing flat files are exempt, the layout applies to new
     work only).
 12. a scored-kind findings pack (review / security-audit / performance) that carries
     findings records its review-scorer pass in the envelope `scoring` field
     (`PACK-UNSCORED`) - the scorer delegation was silently skipped in two live runs on
     2026-08-08 after repeated prose fixes, and only a recorded attestation on disk is
     mechanically checkable; compliance/model-validation packs are exempt (their findings
     are never score-filtered).

Exit 0 = gate satisfied; exit 1 = findings printed (one line each, machine-readable prefix).
No third-party dependencies. Output is forced to UTF-8 so the emoji basis tags don't crash a
Windows console. Usage:
`python -m scripts.check_artifacts [artifacts_dir] [codebase_map_path] [--fix]`.
`--fix` also renders each findings pack to its canonical REVIEW-<slug>.md before verifying.
`--fix` mechanically resolves the auto-fixable defects (render missing `.html` siblings; rename a
mis-typed summary email to `.txt` and sync the index) before the gate verifies - so the close
does not depend on the model remembering each step.
"""

from __future__ import annotations

import hashlib
import json
import re

# Used for the git anchor query and for --fix's render_html call - both fixed-argv, no shell.
import subprocess  # nosec B404
import sys
from pathlib import Path, PurePosixPath

# Map hygiene thresholds (ADR-003: target ~200 lines; the gate hard-flags past 250).
_MAP_MAX_LINES = 250

# Secret-shaped content that must never appear in a memory file (CLAUDE.md §5).
_SECRET_PATTERNS = [
    (re.compile(r"AKIA[0-9A-Z]{16}"), "AWS access key id"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY"), "private key block"),
    (
        re.compile(
            r"(?i)\b(password|passwd|secret|api[_-]?key|token)\b\s*[=:]\s*['\"][^'\"<>\s]{8,}"
        ),
        "hardcoded credential assignment",
    ),
]

_SHA_RE = re.compile(r"\b[0-9a-f]{7,40}\b")
_DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
# Honest no-VCS anchor: a working project with no git repo has no SHA to anchor to.
# STRICT since the 2026-07-29 register M1 [reproduced]: the token must be the anchor VALUE
# (immediately after the label / alone in an entry cell) - the template's own placeholder
# prose contains the words "no-vcs" and used to pass the gate as a valid anchor.
_NOVCS_VALUE_RE = re.compile(r"(?i)\bAnchor\b[\s`'·:*]*no[\s-]?vcs\b")
_NOVCS_CELL_RE = re.compile(r"(?i)^[\s`']*no[\s-]?vcs[\s`']*$")
# Staleness budget (register M3): how many commits the header anchor may trail HEAD before
# the map must be re-verified. Default 50 - roughly a small project's sprint of commits, so
# a map refreshed each engagement never trips it while a genuinely abandoned map does
# (chosen 2026-07-29 with the M3 fix; override per map with a `Staleness-budget` header
# field and a stated rationale - CLAUDE.md §4, no unexplained thresholds).
_MAP_STALENESS_BUDGET = 50
_STALENESS_BUDGET_RE = re.compile(r"(?i)staleness-budget[^0-9]*(\d+)")

# ADR-007 Phase 1 Chunk C: MAP-DRIFT/MAP-DEAD-POINTER. Backtick-wrapped `path/file.py:123` (or
# a `:12-34` range) citations inside an entry's own text - the shape every existing map entry
# already uses (see docs/templates/codebase-map.md's own examples), not a new convention.
_MAP_CITATION_RE = re.compile(r"`([\w./-]+\.\w+):(\d+)(?:-\d+)?`")
_FINGERPRINTS_FILENAME = "codebase-map.fingerprints.json"


def _split_paths_cell(cell: str) -> list[str]:
    return [g.strip() for g in cell.split(",") if g.strip()]


def _read_map_skeleton_toggle(project_dir: Path) -> bool:
    """map_skeleton toggle for MAP-DRIFT/MAP-DEAD-POINTER - off by default. Same 3-tier
    precedence as the docx/citations preferences (project's own team-preferences.json key,
    present-or-not, wins even if false; else this machine's installer.json default; else
    built-in False). Deliberately re-derived, not imported, matching
    engage_probe.read_machine_defaults()'s own stated standalone-runnability rationale - this
    file must keep working invoked by path in plugin mode, not just as -m scripts.check_artifacts."""
    try:
        prefs = json.loads(
            (project_dir / ".claude" / "team-preferences.json").read_text(encoding="utf-8-sig")
        )
        if isinstance(prefs, dict) and "map_skeleton" in prefs:
            return bool(prefs["map_skeleton"])
    except (OSError, ValueError):
        pass
    try:
        import os

        base = os.environ.get("XDG_CONFIG_HOME")
        root = Path(base) if base else Path.home() / ".config"
        installer_cfg = json.loads(
            (root / "virt-surv-it" / "installer.json").read_text(encoding="utf-8-sig")
        )
        if isinstance(installer_cfg, dict):
            return bool(installer_cfg.get("default_map_skeleton", False))
    except (OSError, ValueError):
        pass
    return False


# Code-without-QA gate: a live engagement (2026-07-21) delivered phase-2 implementation
# code from inside an analysis workflow and no QA pass ever ran - the DoD items are
# PM-attested, so nothing mechanical caught it. This check does: deliverable code in
# artifacts/ requires a QA handover and at least one test file. (Code delivered into the
# working repo's source tree is out of this gate's sight - the skill/operating-guide
# escalation rule covers that path; this is the belt for the common artifacts/ case.)
_CODE_EXTS = {".py", ".scala", ".sql", ".sh", ".ps1", ".java", ".js", ".ts"}
_TEST_FILE_RE = re.compile(r"(^test_|_test\.|\.spec\.|^conftest\.py$)", re.I)

# Finding-shape gate: a reported Critical/Warning finding block (output-format shape,
# `### 🔴 {{title}}` / `### 🟠 {{title}}`) must state its impact - the cheap binary check
# the evidence says captures most of a critique pass's value (operating guide, Outcome
# discipline 6). Table-format findings aren't parseable this way and are left to the
# critic; this gate only asserts block-format findings carry the mandatory line.
_FINDING_HEAD_RE = re.compile(r"^###\s+[🔴🟠]\s+\S", re.M)
_IMPACT_LINE_RE = re.compile(r"^\*\*Impact if unaddressed:?\*\*", re.M)
# A findings report must use the five NAMED fields (Standard/Problem/Likely cause/Impact/Fix), NOT
# the audit C-words as labels ("Condition/Consequence/Correction") or a collapsed "5C summary" block
# - that drift ran inline with an inconsistent 3-to-5 items per finding (2026-07-24 report). Flag a
# C-word bold label at line start, or any "5C summary" label. (output-format.md.)
_FINDINGS_CWORD_RE = re.compile(
    r"^\*\*(?:condition|consequence|correction)\b|\b5[\s\-]?c\b[\s\-]*summary", re.I | re.M
)

# Developer guidance (audit finding #2, 2026-07-30): output-format.md states this section
# is "mandatory even on a clean review" and claims "the review skills mechanically check
# the artifact for it" - but nothing did. Four files (deep-review, audit-review,
# security-audit SKILL.md + the code-reviewer agent) each carry their own prose reminder
# to verify it before finishing; none is backed by a check. "## Findings" (render_findings.py
# always emits it) identifies a genuine review-shaped artifact - only those are held to this.
_FINDINGS_SECTION_RE = re.compile(r"^## Findings\s*$", re.M)
_DEV_GUIDANCE_HEADING_RE = re.compile(r"^## 🔵 Developer guidance\b.*$", re.M)
_DEV_GUIDANCE_PLACEHOLDER = "_(none provided)_"

# Roster gate: an artifact must not attribute work to a persona who is not on the team, or to
# the wrong role. A live delivery report (2026-07-23) invented "Chidi (code-reviewer)" and
# "Priya (compliance-reviewer)" and called Ravi the TM-SME - fabricated reviewers on a
# customer-facing document. The canonical roster is name -> role slug; SOURCE OF TRUTH is
# docs/team-operating-guide.md "Roster & routing" - a docs-consistency test asserts they match.
# This is an AUTO-FIX class finding: the close step corrects the name to the canonical persona
# for the stated role and re-checks; it is never a defect to hand to the user.
_ROSTER = {
    "morgan": "pm",
    "amara": "business-analyst",
    "mateo": "rules-developer",
    "ana": "data-analyst",
    "theo": "tuning-analyst",
    "mei": "ml-engineer",
    "kenji": "platform-engineer",
    "linh": "qa-engineer",
    "viktor": "model-validator",
    "ravi": "code-reviewer",
    "thabo": "performance-reviewer",
    "layla": "compliance-reviewer",
    "yuki": "data-quality-reviewer",
    "pip": "review-scorer",
}
# Retired 2026-08-17 (the SME agents became docs/sme/ knowledge packs, assessment
# rec 5) but kept RECOGNISED wherever recognition matters: historical artifacts and
# still-open packs written before the change legitimately carry these attributions
# and must not start flagging ROSTER-UNKNOWN. Deliberately NOT in _ROSTER: the
# roster-gate consistency test pins _ROSTER to the operating guide's live roster,
# and auto-rename suggestions must never propose a retired persona. New artifacts
# cite the pack, never a persona (docs/sme/README.md).
_RETIRED = {
    "hassan": "tm-sme",
    "camila": "trade-surveillance-sme",
    "cleo": "comms-surveillance-sme",
}
_KNOWN_PERSONAS = {**_ROSTER, **_RETIRED}
_ROLE_TO_NAME = {slug: name for name, slug in _KNOWN_PERSONAS.items()}
# A `Name (role)` attribution is only treated as a team-persona claim when the parenthetical is
# a FULL, hyphenated team role slug. Short forms (`qa`, `ba`, `orchestrator`, `pm`) are
# DELIBERATELY excluded: they collide with real content - "Airflow (orchestrator)",
# "Independent (QA)", "Second (QA) cycle", "Aisha (BA) from the client" - and would both
# false-alarm and drive a wrong auto-rename (2026-07-23 review). The one live failure used full
# slugs ("Chidi (code-reviewer)"), so full-slug matching still catches the real thing. `project-
# manager` is kept (unambiguous); a bare `sme` is ambiguous (three SMEs) and is not matched.
_ROLE_ALIASES = {slug: slug for slug in _KNOWN_PERSONAS.values() if slug != "pm"}
_ROLE_ALIASES["project-manager"] = "pm"
# Persona attribution pattern: "Name (role)". Name is a single capitalised word.
_PERSONA_RE = re.compile(r"\b([A-Z][a-z]{2,})\s*\(([A-Za-z][A-Za-z /_-]{1,40})\)")

# AI-identity gate (operating guide "Voice, names & console", user rule 2026-07-29): a roster
# name in an artifact must be unmistakably an AI agent (🤖 + Virtual Surveillance IT), and an
# agent must never share one sign-off/approval line with a human - only the human grant carries
# authority. Two mechanical checks:
#   AGENT-UNMARKED (auto-fix) - the artifact makes a persona attribution but carries no 🤖
#     marker anywhere (add the marker / the sign-off legend);
#   AGENT-HUMAN-COMBINED (auto-fix: split the line) - a roster name is joined by `+`/`&` to a
#     capitalised non-roster name on one line ("sign-off from Layla + Daniel"). Two roster
#     names joined ("Theo + Ana") is fine; the other token must be name-shaped
#     ([A-Z][a-z]{2,}), so "Layla + RTM" never trips it.
_ROSTER_NAMES_RE = "|".join(sorted(n.capitalize() for n in _KNOWN_PERSONAS))
_AGENT_JOIN_RE = re.compile(
    rf"\b({_ROSTER_NAMES_RE})\b\s*[+&]\s*([A-Z][a-z]{{2,}})\b"
    rf"|\b([A-Z][a-z]{{2,}})\s*[+&]\s*\b({_ROSTER_NAMES_RE})\b"
)
_AI_MARKER = "🤖"


def _auto_mode_findings(artifacts_dir: Path) -> list[str]:
    """Unattended runs must never read as signed off (2026-08-20).

    The same principle as QA-QUICK-NOT-PARTIAL, applied to autonomy: an engagement nobody
    was asked about can reach every Definition-of-Done line EXCEPT human sign-off, and the
    one thing that would make it dangerous is for it to look complete. Two gates:

      AUTO-NOT-PARTIAL     - it closed without saying PARTIAL anywhere a reader will look.
      AUTO-LEDGER-MISSING  - it recorded no assumptions. An unattended run that answered
                             its own questions and then listed none of them has hidden the
                             judgement calls, which is precisely what the ledger exists to
                             prevent. (Zero assumptions is possible but rare; the finding
                             says to record "none" explicitly rather than stay silent.)

    Only fires on engagements that actually ran unattended - state carries `auto: true`."""
    findings: list[str] = []
    for pack in sorted(p for p in artifacts_dir.rglob("engagement-state.json") if p.is_file()):
        workspace = pack.parent
        if _under_archive(pack, artifacts_dir):
            continue
        try:
            state = json.loads(pack.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue  # STATE-INVALID owns that failure
        if not state.get("auto"):
            continue
        if str(state.get("status") or "") not in ("closed", "closing"):
            continue  # still running, or parked - nothing to assert about a verdict yet
        evidence = str(state.get("verdict") or "")
        for name in ("delivery-report.md", "START-HERE.md"):
            candidate = workspace / name
            if candidate.is_file():
                try:
                    evidence += candidate.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    pass
        if "PARTIAL" not in evidence.upper():
            findings.append(
                f"AUTO-NOT-PARTIAL: {workspace} ran unattended but nothing in the verdict, "
                "delivery report or START-HERE says PARTIAL - an unattended run reaches "
                "every DoD line except human sign-off and must say so (DoD: state "
                "'DoD: PARTIAL - unattended run, human sign-off outstanding')"
            )
        decisions = state.get("decisions")
        decisions = decisions if isinstance(decisions, dict) else {}
        if not any(str(k).startswith("assumed-") for k in decisions):
            findings.append(
                f"AUTO-LEDGER-MISSING: {workspace} ran unattended but recorded no "
                "'assumed-*' decisions - the assumption ledger is what makes an "
                "unattended run reviewable (record each judgement call, or one entry "
                "stating explicitly that none were needed)"
            )
    return findings


def _qa_depth_findings(artifacts_dir: Path) -> list[str]:
    """QA-level honesty gates (2026-08-20). Breadth of QA is tierable; pretending a
    reduced pass was a full one is not.

    QA-QUICK-NOT-PARTIAL is the keystone of the whole tiering feature: choosing cheap QA
    costs the engagement the word "done". Without it, `qa_depth: quick` would be a silent
    way to buy a full-looking verdict at half price. QA-LEVEL-UNDECLARED catches the other
    direction - a QA handover that never says which level produced it, leaving a reader
    unable to tell what was skipped.

    Only fires where a QA handover actually exists: an engagement that built nothing has
    no level and must not be nagged about one."""
    findings: list[str] = []
    for pack in sorted(p for p in artifacts_dir.rglob("engagement-state.json") if p.is_file()):
        workspace = pack.parent
        if _under_archive(pack, artifacts_dir):
            continue
        handovers = sorted(workspace.glob("qa-handover*.md"))
        if not handovers:
            continue
        try:
            state = json.loads(pack.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue  # STATE-INVALID owns that failure; don't double-report it here
        level = state.get("qa_depth")
        if not level:
            findings.append(
                f"QA-LEVEL-UNDECLARED: {workspace} has a QA handover but the state records "
                "no qa_depth - a reader cannot tell what breadth of QA was bought "
                "(`engagement_state set-qa-depth quick|deep|audit`)"
            )
            continue
        if level != "quick":
            continue
        verdict = str(state.get("verdict") or "")
        evidence = verdict
        for name in ("delivery-report.md", "START-HERE.md"):
            candidate = workspace / name
            if candidate.is_file():
                try:
                    evidence += candidate.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    pass
        if "PARTIAL" not in evidence.upper():
            findings.append(
                f"QA-QUICK-NOT-PARTIAL: {workspace} closed at QA level 'quick' but nothing "
                "in the verdict, delivery report or START-HERE says PARTIAL - a reduced QA "
                "pass must never read as a full one (DoD: state 'DoD: PARTIAL - QA scope "
                "reduced (QA-Quick)' and name the uncovered classes in residual risk)"
            )
    return findings


# A Markdown table separator row is ONLY pipes, dashes, colons and spaces. Anything else on
# the same line means the table was written collapsed onto one line, which Python-Markdown
# renders as a paragraph of literal pipes rather than a table.
_SEPARATOR_RUN_RE = re.compile(r"\|\s*:?-{3,}:?\s*\|")
_PURE_SEPARATOR_RE = re.compile(r"^[|\s:-]+$")


def _collapsed_table_findings(md: Path, text: str) -> list[str]:
    """TABLE-COLLAPSED - a Markdown table written without line breaks (2026-08-24).

    Live report: a client-facing regulatory narrative shipped with its Document Control
    table rendered as one paragraph of literal pipes, `|---|---|` and all. The renderer was
    innocent (`tables` is enabled and a well-formed table renders correctly); the SOURCE had
    the whole table on a single line, which Markdown cannot see as a table by definition.

    Worth a gate rather than a style note because the failure is silent and asymmetric: the
    .md looks passable to whoever wrote it, the .html is what the client opens, and nothing
    else in the pipeline compares the two. Detection is exact rather than heuristic - a
    genuine separator row contains nothing but pipes, dashes, colons and spaces, so a
    separator run sharing a line with other content is collapsed, always."""
    out: list[str] = []
    for number, line in enumerate(text.splitlines(), 1):
        if not _SEPARATOR_RUN_RE.search(line):
            continue
        # Strip blockquote markers first: `> |---|---|` is a table inside a blockquote, which
        # every template's Document Control block uses and which renders correctly. Without
        # this the check flagged 62 healthy files - a checker that cries wolf gets switched
        # off, which would cost more than the defect it was written for.
        bare = re.sub(r"^\s*(?:>\s*)+", "", line).strip()
        if _PURE_SEPARATOR_RE.match(bare):
            continue  # a normal separator row on its own line
        out.append(
            f"TABLE-COLLAPSED: {md}:{number} has a Markdown table written on one line - it "
            "renders as a paragraph of literal pipes, not a table (put each row, and the "
            "|---|---| separator, on its own line and re-render the HTML)"
        )
    return out


def check_agent_identity(text: str, where: Path) -> list[str]:
    """Flag artifacts where an agent persona could be read as a real person.

    Fires AGENT-UNMARKED when a definite team-persona attribution (`Name (full-role-slug)`)
    exists but the file has no 🤖 marker at all; AGENT-HUMAN-COMBINED when a roster name and a
    non-roster name share one line joined by `+`/`&`. Both are AUTO-FIX class: add the marker /
    split the line - never a defect handed to the user.
    """
    findings: list[str] = []
    has_persona = any(
        m.group(1).lower() in _KNOWN_PERSONAS
        and _ROLE_ALIASES.get(re.sub(r"[\s_]+", "-", m.group(2).strip().lower())) is not None
        for m in _PERSONA_RE.finditer(text)
    )
    if has_persona and _AI_MARKER not in text:
        findings.append(
            f"AGENT-UNMARKED: {where} attributes work to a team persona but carries no 🤖 "
            "marker - roster names must read as AI agents (🤖 + Virtual Surveillance IT on "
            "first mention; auto-fix: add the marker / the sign-off legend)"
        )
    seen: set[str] = set()
    for m in _AGENT_JOIN_RE.finditer(text):
        agent = m.group(1) or m.group(4)
        other = m.group(2) or m.group(3)
        if other.lower() in _KNOWN_PERSONAS or m.group(0) in seen:
            continue  # two agents on one line is not an agent+human combination
        seen.add(m.group(0))
        findings.append(
            f"AGENT-HUMAN-COMBINED: {where} joins agent '{agent}' and '{other}' on one line "
            f"('{m.group(0)}') - an agent and a human never share a sign-off/approval line; "
            "auto-fix: split into separate lines (only the human grant carries authority)"
        )
    return findings


def check_summary_email(text: str, where: Path) -> list[str]:
    """The engagement-summary email is Morgan's cover note to an outside reader - the
    artifact most likely to be forwarded with no context, so identity is enforced
    harder here than in reports (template + user rule 2026-07-30, after a live email
    went out signed by the human requester).

    EMAIL-NOT-MORGAN - a `From:` line that does not name Morgan, or a sign-off tail
      (last non-empty lines) with no Morgan in it: the email is always FROM Morgan;
      the human's sign-off lives in the delivery report, never the email.
    EMAIL-AGENT-UNMARKED - a roster name mentioned anywhere in the email with no line
      carrying both that name and the 🤖 marker: every agent mentioned must be
      unmistakably an AI on at least its first marked mention (per-name, stricter
      than the file-level AGENT-UNMARKED used for reports).
    """
    findings: list[str] = []
    lines = text.splitlines()
    for ln in lines:
        if re.match(r"(?i)^\s*From\s*:", ln):
            if "morgan" not in ln.lower():
                findings.append(
                    f"EMAIL-NOT-MORGAN: {where} From line does not name Morgan - the summary "
                    "email is Morgan's cover note (docs/templates/engagement-summary-email.md): "
                    "From: 🤖 Morgan - PM & Orchestrator, Virtual Surveillance IT"
                )
            break
    tail = [ln.strip() for ln in lines if ln.strip()][-6:]
    if not any("morgan" in ln.lower() for ln in tail):
        findings.append(
            f"EMAIL-NOT-MORGAN: {where} sign-off does not name Morgan - the summary email is "
            "signed off as 🤖 Morgan, never the human requester (the human's sign-off lives "
            "in the delivery report; DoD / operating guide rule 3)"
        )
    for name in sorted(_KNOWN_PERSONAS):
        cap = name.capitalize()
        name_re = re.compile(rf"\b{cap}\b")
        if not name_re.search(text):
            continue
        if not any(_AI_MARKER in ln and name_re.search(ln) for ln in lines):
            findings.append(
                f"EMAIL-AGENT-UNMARKED: {where} mentions agent '{cap}' but no line marks "
                f"'{cap}' with 🤖 - every roster name in the email must be unmistakably an "
                "AI agent on at least one mention (add 🤖 at the first mention)"
            )
    return findings


def check_roster(text: str, where: Path) -> list[str]:
    """Flag `Name (role)` attributions whose name is off-roster or in the wrong role.

    Only fires when the parenthetical normalises to a *known team role slug* - a stakeholder
    like `Aymen (sponsor)` never trips it. AUTO-FIX class: the caller corrects to the canonical
    persona for the role. De-duplicated per (name, role).
    """
    findings: list[str] = []
    seen: set[tuple[str, str]] = set()
    for m in _PERSONA_RE.finditer(text):
        name, role_raw = m.group(1).lower(), m.group(2).strip().lower()
        role = _ROLE_ALIASES.get(re.sub(r"[\s_]+", "-", role_raw))
        if role is None:
            continue  # not a team-role attribution (e.g. a stakeholder, a tool, a heading)
        expected = _ROLE_TO_NAME[role]
        if name == expected or (name, role) in seen:
            continue
        seen.add((name, role))
        if role in _RETIRED.values():
            # A retired SME role attributed to anyone NEW: the role has no persona any
            # more - the fix is citing the knowledge pack, never re-attributing.
            findings.append(
                f"SME-PACK-ATTRIBUTION: {where} attributes '{m.group(1)} ({role_raw})' but "
                f"the {role} role is retired (2026-08-17) - new work cites the matching "
                "docs/sme/ knowledge pack instead of a persona (docs/sme/README.md)"
            )
            continue
        if name in _KNOWN_PERSONAS:
            findings.append(
                f"ROSTER-ROLE-MISMATCH: {where} attributes '{m.group(1)} ({role_raw})' but "
                f"{m.group(1)} is the {_KNOWN_PERSONAS[name]}; {role} is {expected.capitalize()} "
                "(auto-fix: correct to the canonical persona for the role)"
            )
        else:
            findings.append(
                f"ROSTER-UNKNOWN: {where} attributes work to '{m.group(1)} ({role_raw})' - "
                f"{m.group(1)} is not on the team; {role} is {expected.capitalize()} "
                "(verify-then-fix: if a fabricated specialist, replace with the canonical "
                "persona; if a genuine external person, keep the name and mark them external - "
                "never rename a real external to a team member)"
            )
    return findings


# Engagement-state gate: the START-HERE index is a LIVING document (created at open,
# updated on every artifact write, finalised at close) and carries the engagement Status.
# A live failure (2026-07-22) motivated it: an engagement paused on an unanswered
# clarification, the close never ran, no DoD gate ever fired, and an interim report with a
# final-sounding name was read as the delivery - with QA never run. The status makes
# "not done" visible; the close-only rules below stop interim work masquerading as final.
_STATUS_LINE_RE = re.compile(r"(?im)^.*\bstatus\b.*$")
_STATUS_EMOJI = {"✅": "closed", "⛔": "blocked", "⏳": "open", "🔒": "closing"}
# Local link targets in the index ([text](file.md)) - no scheme, no pure-anchor links.
_LOCAL_LINK_RE = re.compile(r"\]\(([^)#][^)]*)\)")
# Files that may only exist once the engagement is closing/closed.
_CLOSE_ONLY_MD_RE = re.compile(r"(?i)^(delivery-report.*|final-.*)\.md$")
# The canonical rendered review report is close-only too (operating guide "REVIEW-*";
# D4 ruling 2026-07-29, register P3). CASE-SENSITIVE by design: the interim, pass-scoped
# `review-pass-N.md` names stay legal mid-engagement.
_CLOSE_ONLY_REVIEW_RE = re.compile(r"^REVIEW-.*\.md$")
# Filename-shaped tokens ("review-pass-1.md") - used for whole-token index-listing checks so a
# short name is not treated as listed just because it is a substring of a longer listed name.
_FILENAME_TOKEN_RE = re.compile(r"[\w.\-]+\.[A-Za-z0-9]+")
# The engagement-summary email is a .txt by design (the one artifact never rendered to HTML). A
# summary written as .md/.html is the wrong file type - SUMMARY-WRONG-EXT (auto-fixable).
_SUMMARY_WRONG_EXT_RE = re.compile(r"(?i)^engagement-summary-.*\.(?:md|html)$")
# A mutable engagement STATUS lives only in START-HERE (single source of truth). A stale
# interim/in-progress banner left near the top of a content artifact after close is STALE-STATUS.
_STALE_STATUS_RE = re.compile(
    r"(?im)^>.*(?:⏳|\bINTERIM\b|engagement not closed|\bin progress\b|\bnot closed\b)"
)
# Document-control Status fields must be closed out once START-HERE is ✅ CLOSED: a doc still
# declaring `Status `Draft`` / `In review` under a closed index is the status machinery
# contradicting the index (independent review 2026-07-25: 5 of 7 "final" docs read Draft).
# `pending` alone is the same defect under a different word: no template's placeholder uses it
# (they all say `Draft | In review | Approved`), so a report reading bare `Status `Pending``
# is scaffolding text an author wrote and never went back to update (live report, 2026-08-03:
# a closed delivery-report.md and its .html both still read Pending) - not caught before
# because this pattern only checked for draft/in review/in progress, never pending itself.
# Judgement item, never auto-fixed - only the PM knows closed vs "pending human sign-off"
# (the latter, stated in the Status value itself, passes this check).
_STALE_DOCSTATUS_RE = re.compile(
    r"(?im)^>.*\bStatus\b[ `'·:]*(?:draft\b(?![^`\n]*pending human sign-off)"
    r"|in review\b(?![^`\n]*pending human sign-off)"
    r"|in progress\b(?![^`\n]*pending human sign-off)"
    r"|pending\b(?!\s+human sign-off))"
)


def _force_utf8_output() -> None:
    """Windows consoles default to cp1252 and raise UnicodeEncodeError on the emoji basis tags
    (this gate prints ⏳/✅/📊/🧠), so the check crashed instead of running (live report,
    2026-07-24). Force UTF-8 on stdout/stderr so it runs everywhere without a `-X utf8` flag.
    Inlined (not a shared import) because this script is also invoked by direct path in an
    installed-plugin session, where `from scripts...` would not resolve."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):  # pragma: no cover - stream without a real fd
                pass


def _closed_is_negated(lowered: str) -> bool:
    """True if every 'closed' on the line is negated/qualified ('not', 'cannot be', 'to be')."""
    for m in re.finditer(r"\bclosed\b", lowered):
        pre = lowered[max(0, m.start() - 30) : m.start()]
        if not re.search(r"\b(not|never|cannot|can|to|before|once|when|until|isn|aren)\b", pre):
            return False  # at least one unqualified 'closed'
    return True


def _index_status(text: str) -> str | None:
    """Read the engagement status from START-HERE: 'open' | 'blocked' | 'closing' |
    'closed', or None.

    Fail-SAFE by construction (a wrong 'closed' silently disables the close-only guards, which
    is the exact failure the gate exists to stop):
    - A status line carrying MORE THAN ONE distinct status emoji is a legend/key, not a state -
      it is skipped, not read as closed.
    - Exactly one emoji -> that state (the template's canonical form).
    - Word fallback (no emoji): blocked/closing/open are resolved BEFORE closed (not-done wins
      on ambiguity), and a negated/qualified 'closed' ('not closed', 'cannot be closed') does
      not count. Only lines that mention 'status' are considered, so prose elsewhere can't pose
      as state.
    """
    for line in _STATUS_LINE_RE.findall(text):
        emojis = {e for e in _STATUS_EMOJI if e in line}
        if len(emojis) > 1:
            continue  # a legend line lists the status symbols - not the engagement's state
        if len(emojis) == 1:
            return _STATUS_EMOJI[next(iter(emojis))]
        lowered = line.lower()
        if re.search(r"\bblocked\b", lowered):
            return "blocked"
        if re.search(r"\bclosing\b", lowered):
            return "closing"
        if re.search(r"\bin progress\b|\bopen\b", lowered):
            return "open"
        if re.search(r"\bclosed\b", lowered) and not _closed_is_negated(lowered):
            return "closed"
    return None


# The state file's vocabulary mapped onto the index parser's (ADR-006 statuses on the
# left). An unknown/unparseable state status falls through to the index parse.
_STATE_STATUS_MAP = {
    "in_progress": "open",
    "blocked": "blocked",
    "closing": "closing",
    "closed": "closed",
}


def pack_status(pack: Path) -> str | None:
    """The one shared "what state is this pack in" answer for the checker and both hooks.

    2026-07-29 register G5: three non-equivalent parsers (this module's legend-aware one,
    the hooks' raw emoji-substring sniff, the eval harness's first-status-line grab) meant
    a words-only status line armed the checker but not the stop gate, and a stray ⏳
    anywhere in a closed index re-armed the hooks. This helper is now the single rule:
    the machine-readable state file (ADR-006) is authoritative when its status parses;
    the fallback is the legend-aware `_index_status` - never a substring sniff.

    Returns 'open' | 'blocked' | 'closing' | 'closed', or None (not an engagement pack).
    """
    state_file = pack / "engagement-state.json"
    if state_file.is_file():
        try:
            raw = json.loads(state_file.read_text(encoding="utf-8")).get("status")
        except Exception:
            raw = None
        mapped = _STATE_STATUS_MAP.get(raw)
        if mapped is not None:
            return mapped
    try:
        text = (pack / "START-HERE.md").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    return _index_status(text)


def engagement_packs(artifacts_dir: Path) -> list[Path]:
    """Subdirectories that LOOK like engagement packs: a state file OR a START-HERE index.

    2026-07-29 register G7: the checker required a state file where the persona anchor
    accepted an index alone, so a hand-made `artifacts/<slug>/` pack was anchored but
    never gated. This is now the single detection rule for gating and anchoring, in the
    fail-safe direction: the gate sees everything the anchor sees. Registry consistency
    stays keyed on the narrower `workspace_dirs` (state file present) because only
    stateful packs are registrable."""
    if not artifacts_dir.is_dir():
        return []
    return sorted(
        p
        for p in artifacts_dir.iterdir()
        if p.is_dir()
        and not (p / ".archive").is_file()  # archived packs are out of play (0.33.2)
        and ((p / "engagement-state.json").is_file() or (p / "START-HERE.md").is_file())
    )


def _under_archive(path: Path, base: Path) -> bool:
    """True when any directory from path's parent up to (and including) base carries the
    `.archive` marker - the subtree is excluded from every scan (0.33.2)."""
    cur = path if path.is_dir() else path.parent
    while True:
        try:
            if (cur / ".archive").is_file():
                return True
        except OSError:
            return False
        if cur == base or cur == cur.parent:
            return False
        cur = cur.parent


def archived_open_packs(artifacts_dir: Path) -> list[str]:
    """ARCHIVED-OPEN safeguard: a `.archive` marker on a pack whose state is not closed
    would silently dodge the close gate. One cheap state-file read per archived pack -
    that is the entire cost archived packs keep. CLI-report only (the stop gate stays
    silent for archived packs by design - archiving IS the mute button; this warning
    surfaces on explicit checker runs so the dodge is visible, not fatal)."""
    findings = []
    if not artifacts_dir.is_dir():
        return findings
    for p in sorted(artifacts_dir.iterdir()):
        if not (p.is_dir() and (p / ".archive").is_file()):
            continue
        state_file = p / "engagement-state.json"
        if not state_file.is_file():
            continue  # a plain archived directory - nothing to guard
        try:
            status = json.loads(state_file.read_text(encoding="utf-8")).get("status")
        except Exception:
            status = "unreadable"
        if status != "closed":
            findings.append(
                f"ARCHIVED-OPEN: {p.name}/ is archived but its status is '{status}' - "
                "archiving does not close an engagement; unarchive it and close properly "
                "(python -m scripts.engagement_state unarchive " + p.name + "), or leave "
                "this warning standing as the record of abandoned work"
            )
    return findings


def find_codebase_map(project_dir: Path) -> Path | None:
    """The map's conventional locations in a working project (ADR-003)."""
    for candidate in (project_dir / "docs" / "codebase-map.md", project_dir / "CODEBASE-MAP.md"):
        if candidate.is_file():
            return candidate
    return None


def find_codebase_map_area_files(project_dir: Path) -> list[Path]:
    """ADR-007 Phase 1 Chunk E: `docs/codebase-map.d/*.md` area files - the root map's
    Index (docs/templates/codebase-map.md) points to these for detail the ~200-line root
    budget can't hold. Each one is a map in its own right (same doc-control header, same
    §2 entries shape) and gets the identical per-file hygiene check_map() already runs on
    the root map - sorted for deterministic output, absent directory is the common case
    (a project that never ran /map-codebase), not an error."""
    area_dir = project_dir / "docs" / "codebase-map.d"
    if not area_dir.is_dir():
        return []
    return sorted(p for p in area_dir.glob("*.md") if p.is_file())


def _anchor_resolves(sha: str, repo_dir: Path) -> bool | None:
    """True/False if git could answer; None when git/repo is unavailable (skip check)."""
    try:
        # argv list (no shell); `git` from PATH is deliberate (a pinned absolute path
        # would break Windows/mac); sha is regex-validated hex by the caller.
        result = subprocess.run(  # nosec B603 B607
            ["git", "-C", str(repo_dir), "cat-file", "-e", f"{sha}^{{commit}}"],
            capture_output=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode == 0:
        return True
    # Distinguish "unknown object" (a real staleness finding) from "not a git repo at all".
    stderr = result.stderr.decode(errors="replace")
    if "not a git repository" in stderr.lower():
        return None
    return False


def _commits_behind(sha: str, repo_dir: Path) -> int | None:
    """How many commits HEAD is ahead of the anchor (register M3), or None when git can't
    answer (no repo, unrelated history, detached oddities) - the bound then skips."""
    try:
        result = subprocess.run(  # nosec B603 B607 - fixed argv, regex-validated hex sha
            ["git", "-C", str(repo_dir), "rev-list", "--count", f"{sha}..HEAD"],
            capture_output=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    try:
        return int(result.stdout.decode().strip())
    except ValueError:
        return None


def _batch_resolve_shas(shas: list[str], repo_dir: Path) -> dict[str, bool | None]:
    """Resolve MANY commit SHAs in ONE git subprocess instead of one-per-sha (2026-08-03
    perf audit): check_map()'s entry-anchor loop used to call _anchor_resolves once PER
    MAP ENTRY, so a well-filled map (capped at 250 lines, plausibly 20-50 unique entry
    SHAs) meant that many separate `git cat-file -e` process spawns on every gated Stop
    event. `git cat-file --batch-check` accepts a newline-separated list of revision
    specifiers on stdin and answers all of them in ONE process, in the SAME order. Same
    per-sha semantics as _anchor_resolves: True = resolves as a commit, False = git
    answered but it doesn't resolve (a real staleness finding), None = git/repo
    unavailable entirely (skip that sha's check, never a false STALE finding)."""
    if not shas:
        return {}
    stdin_text = "".join(f"{sha}^{{commit}}\n" for sha in shas)
    try:
        result = subprocess.run(  # nosec B603 B607 - fixed argv, regex-validated hex shas
            ["git", "-C", str(repo_dir), "cat-file", "--batch-check=%(objectname) %(objecttype)"],
            input=stdin_text,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return dict.fromkeys(shas)
    if "not a git repository" in result.stderr.lower():
        return dict.fromkeys(shas)
    lines = result.stdout.splitlines()
    # git answers one line per input line, in order - zip by position, never by string
    # match (a RESOLVED line echoes the resolved objectname, not the "<sha>^{commit}"
    # text we sent; only a MISSING line echoes the literal input back).
    out: dict[str, bool | None] = dict(zip(shas, (ln.strip().endswith(" commit") for ln in lines)))
    for sha in shas:
        out.setdefault(sha, None)  # a git error mid-stream left this sha unanswered - skip it
    return out


# H1 (2026-08-14 perf audit): dod_stop_gate.py's Stop-hook gate calls check_map() on every
# Stop event while a codebase map exists, each call spawning up to 3 `git` subprocesses
# (_anchor_resolves, _commits_behind, _batch_resolve_shas) even when nothing has changed
# since the previous turn - a per-turn tax that compounds with turn count. The three
# memoized wrappers below key on the CURRENT git HEAD sha (plus the specific sha(s) being
# asked about), so a Stop event with no new commits since the last one reuses the prior
# answer instead of re-spawning git. This only helps when check_artifacts runs inside the
# ADR-014 guard daemon (a persistent process across calls, via its stop_hook_dispatcher
# target) - a plain per-call fresh-process invocation starts with an empty cache and costs
# exactly what it always did, never more.
#
# Correctness: HEAD itself is deliberately NEVER cached (computed fresh, one cheap spawn,
# on every check_map() call) - a cached HEAD would silently miss real commits landing
# between Stop events, permanently freezing MAP-STALE/MAP-STALE-ANCHOR findings at
# whatever they were the first time. Only the (repo, HEAD, sha) -> answer mapping is
# memoized, so any commit landing (HEAD moves) invalidates every cached answer for that
# repo at once, never later - and a HEAD lookup failure (no repo, git unavailable)
# disables caching for that call entirely rather than caching under a None key.
_MAP_GIT_CACHE: dict[tuple, object] = {}


def _current_head_sha(repo_dir: Path) -> str | None:
    """One cheap `git rev-parse HEAD`. Always computed fresh by the caller - see
    _MAP_GIT_CACHE's module comment for why this specific value must never be cached."""
    try:
        result = subprocess.run(  # nosec B603 B607 - fixed argv, shell=False
            ["git", "-C", str(repo_dir), "rev-parse", "HEAD"],
            capture_output=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    sha = result.stdout.decode(errors="replace").strip()
    return sha or None


def _cached_anchor_resolves(sha: str, repo_dir: Path, head: str | None) -> bool | None:
    key = (str(repo_dir), head, "anchor", sha) if head else None
    if key is not None and key in _MAP_GIT_CACHE:
        return _MAP_GIT_CACHE[key]
    result = _anchor_resolves(sha, repo_dir)
    if key is not None:
        _MAP_GIT_CACHE[key] = result
    return result


def _cached_commits_behind(sha: str, repo_dir: Path, head: str | None) -> int | None:
    key = (str(repo_dir), head, "behind", sha) if head else None
    if key is not None and key in _MAP_GIT_CACHE:
        return _MAP_GIT_CACHE[key]
    result = _commits_behind(sha, repo_dir)
    if key is not None:
        _MAP_GIT_CACHE[key] = result
    return result


def _cached_batch_resolve_shas(
    shas: list[str], repo_dir: Path, head: str | None
) -> dict[str, bool | None]:
    key = (str(repo_dir), head, "batch", frozenset(shas)) if head else None
    if key is not None and key in _MAP_GIT_CACHE:
        return _MAP_GIT_CACHE[key]
    result = _batch_resolve_shas(shas, repo_dir)
    if key is not None:
        _MAP_GIT_CACHE[key] = result
    return result


def _split_cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _check_map_drift(
    map_path: Path, project_dir: Path, drift_rows: list[tuple[int, str, list[str]]]
) -> list[str]:
    """MAP-DRIFT: a §2 entry's `Paths` glob no longer matches its recorded fingerprint (or
    was never fingerprinted at all) - toggle-gated, called only when map_skeleton is on
    (check_map). Escalate-only, matching the existing precedent that apply_fixes() never
    auto-resolves map hygiene findings - re-verifying an entry's PROSE against the code it
    now describes is a judgement call, not something to mechanically "fix".

    Sidecar lives NEXT TO map_path (map_path.parent), never project_dir - matching exactly
    where scripts.repo_skeleton.write_fingerprints() writes it. Bug found 2026-08-06
    (building Chunk E): this used to read project_dir/<name>, which only happened to equal
    map_path.parent when the map lives at the project ROOT - silently wrong for the
    documented default location (docs/codebase-map.md), where the two paths differ. Fixed on
    both sides together; project_dir stays a parameter (used elsewhere in this function,
    below, for globs resolved relative to the project root) but no longer decides where the
    sidecar itself is looked up.

    M6 (2026-08 Fable audit): MISSING and CORRUPT sidecars used to collapse to the same
    `entries = {}` fallback - a genuinely absent sidecar (nothing fingerprinted yet, one
    MAP-DRIFT "never fingerprinted" per row is the right answer) and a PRESENT-but-corrupt
    one (a real integrity problem - drift cannot be judged at all, and every row reporting
    "never fingerprinted" is actively misleading about why) read identically to a human
    fixing it. Missing (OSError - no file) still degrades to the per-row fallback; corrupt
    (present, but invalid JSON or the wrong shape) now raises its own distinct finding
    instead of masquerading as "nothing to see here"."""
    if not drift_rows:
        return []
    mf = _load_map_fingerprint_module()
    if mf is None:
        return []  # fail open, same posture as every other optional-module load in this file
    sidecar_path = map_path.parent / _FINGERPRINTS_FILENAME
    entries: dict = {}
    findings: list[str] = []
    try:
        raw = sidecar_path.read_text(encoding="utf-8")
    except OSError:
        pass  # genuinely no sidecar yet - the per-row "never fingerprinted" fallback is correct
    else:
        try:
            sidecar = json.loads(raw)
            if isinstance(sidecar, dict):
                entries = sidecar.get("entries") or {}
            else:
                raise ValueError("fingerprints sidecar is not a JSON object")
        except ValueError as exc:
            findings.append(
                f"MAP-FINGERPRINTS-INVALID: {sidecar_path} exists but is not readable as "
                f"fingerprint data ({exc}) - drift cannot be checked against it; regenerate "
                f"via `<python> -m scripts.repo_skeleton --fingerprint {map_path}`"
            )
    for lineno, area, globs in drift_rows:
        recorded = entries.get(area)
        if recorded is None:
            findings.append(
                f"MAP-DRIFT: {map_path}:{lineno} area {area!r} has a Paths glob but was never "
                f"fingerprinted - run `<python> -m scripts.repo_skeleton --fingerprint "
                f"{map_path}` (or `/map-codebase --refresh`)"
            )
            continue
        current = mf.compute_fingerprint(globs, project_dir)
        if current != recorded.get("fingerprint"):
            findings.append(
                f"MAP-DRIFT: {map_path}:{lineno} area {area!r} changed since mapped - "
                f"re-verify the entry and refresh its fingerprint (`<python> -m "
                f"scripts.repo_skeleton --fingerprint {map_path}`)"
            )
    return findings


def _check_map_dead_pointers(
    map_path: Path, project_dir: Path, citation_checks: list[tuple[int, str]]
) -> list[str]:
    """MAP-DEAD-POINTER: a `file:line` citation in an entry's own text that no longer resolves
    on disk - independent of the fingerprint sidecar, a pure filesystem check. Toggle-gated,
    called only when map_skeleton is on (check_map)."""
    findings: list[str] = []
    for lineno, entry_text in citation_checks:
        for m in _MAP_CITATION_RE.finditer(entry_text):
            cited_path = m.group(1)
            if not (project_dir / cited_path).is_file():
                findings.append(
                    f"MAP-DEAD-POINTER: {map_path}:{lineno} cites `{m.group(0)[1:-1]}` - "
                    f"{cited_path} no longer exists"
                )
    return findings


def check_map(map_path: Path, project_dir: Path | None = None) -> list[str]:
    """Mechanical hygiene findings for a codebase map; empty means the gate is satisfied.

    2026-07-29 register M1/M2/M3/M7: the anchor placeholder no longer passes as no-vcs,
    per-entry As-of/Anchor cells are validated (entry SHAs must resolve), the header anchor
    is bounded against HEAD, entry detection is column-driven (rename-tolerant), and the
    line cap excludes the Deprecated section ADR-003 mandates keeping.

    ADR-007 Phase 1 Chunk C: MAP-DRIFT (a §2 entry's optional `Paths` glob no longer matches
    its recorded fingerprint) and MAP-DEAD-POINTER (a `file:line` citation in an entry's own
    text that no longer resolves on disk) - both gated behind the map_skeleton toggle
    (_read_map_skeleton_toggle), off by default: a project that hasn't opted in sees zero new
    findings, identical to pre-Chunk-C behaviour."""
    findings: list[str] = []
    project_dir = project_dir or map_path.parent
    map_skeleton_on = _read_map_skeleton_toggle(project_dir)
    text = map_path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()

    # Line cap, EXCLUDING the Deprecated section (M7: ADR-003 mandates keeping deprecated
    # entries, so they must not eat the live-content budget).
    dep_lines = 0
    in_dep = False
    for line in lines:
        if line.startswith("#"):
            in_dep = "deprecated" in line.lower()
        if in_dep:
            dep_lines += 1
    effective = len(lines) - dep_lines
    if effective > _MAP_MAX_LINES:
        findings.append(
            f"MAP-TOO-LONG: {map_path} is {effective} lines excluding Deprecated (target "
            f"~200, max {_MAP_MAX_LINES}) - move detail to linked docs/artifacts, keep the "
            "map an index"
        )

    # Header requirements: an As-of date and an Anchor SHA (document-control block).
    header = "\n".join(lines[:30])
    if not ("As-of" in header and _DATE_RE.search(header)):
        findings.append(
            f"MAP-NO-ASOF: {map_path} header has no `As-of <YYYY-MM-DD>` date - staleness "
            "cannot be judged without it"
        )
    anchor_line = next((ln for ln in lines[:30] if "Anchor" in ln), "")
    anchor_sha = _SHA_RE.search(anchor_line)
    # H1: one HEAD lookup, shared by every git-derived fact check_map() computes below -
    # see _MAP_GIT_CACHE's module comment.
    head = _current_head_sha(map_path.parent)
    if anchor_sha:
        resolves = _cached_anchor_resolves(anchor_sha.group(0), map_path.parent, head)
        if resolves is False:
            findings.append(
                f"MAP-STALE-ANCHOR: header anchor {anchor_sha.group(0)} does not resolve "
                "in this repository - refresh the anchor (and re-verify entries) at close"
            )
        elif resolves is True:
            # M3: a resolvable anchor can still be ancient - bound it against HEAD.
            budget_m = _STALENESS_BUDGET_RE.search(header)
            budget = int(budget_m.group(1)) if budget_m else _MAP_STALENESS_BUDGET
            behind = _cached_commits_behind(anchor_sha.group(0), map_path.parent, head)
            if behind is not None and behind > budget:
                findings.append(
                    f"MAP-STALE: header anchor is {behind} commits behind HEAD (budget "
                    f"{budget}) - the code has moved on; re-verify the entries and refresh "
                    "the anchor (raise `Staleness-budget` in the header, with a rationale, "
                    "if this cadence is intended)"
                )
    elif _NOVCS_VALUE_RE.search(anchor_line):
        # A working project with no git repo has no commit SHA to anchor to. An honest
        # `Anchor no-vcs` (the token as the anchor VALUE - M1: prose mentioning no-vcs,
        # like the template's own placeholder, does not count) is valid - entries anchor
        # to the delivered file state instead.
        pass
    else:
        placeholder = " (the template placeholder was left unfilled)" if "<" in anchor_line else ""
        findings.append(
            f"MAP-NO-ANCHOR: {map_path} header has no `Anchor <commit sha>`{placeholder} - "
            "entries cannot be checked against the code they describe (a working project "
            "with no git repo writes exactly `Anchor no-vcs`)"
        )

    # Entry rows: column-driven detection (M7 - a renamed section no longer disables the
    # scan): any table whose header row carries a Basis column is an entries table. Each
    # data row needs its 📊/🧠 tag, and - where the columns exist - a real As-of date and
    # a real Anchor (SHA or the strict no-vcs token). Entry SHAs must resolve (M2: they
    # read as verified provenance on resume, so they may not be decorative).
    entry_shas: dict[str, int] = {}
    # ADR-007 Phase 1 Chunk C - gathered during the same scan, only when the toggle is on
    # (an empty list either way costs nothing extra below when map_skeleton_on is False).
    drift_rows: list[tuple[int, str, list[str]]] = []  # lineno, area, globs
    citation_checks: list[tuple[int, str]] = []  # lineno, entry cell text
    columns: dict[str, int] | None = None
    found_entry_table = False
    for lineno, line in enumerate(lines, start=1):
        if not line.lstrip().startswith("|"):
            columns = None
            continue
        cells = _split_cells(line)
        if not cells or set("".join(cells)) <= {"-", ":", " "}:
            continue  # |---| divider
        lowered = [c.lower() for c in cells]
        if any("basis" in c for c in lowered):
            columns = {name: i for i, name in enumerate(lowered)}
            found_entry_table = True
            continue  # the header row itself
        if columns is None:
            continue  # a table without a Basis column (history, deprecated, doc control)
        if "📊" not in line and "🧠" not in line:
            findings.append(
                f"MAP-NO-BASIS: {map_path}:{lineno} map entry has no 📊 observed / 🧠 "
                "inferred tag - every entry must state its evidence basis"
            )
        asof_idx = next((i for n, i in columns.items() if "as-of" in n or "as of" in n), None)
        if asof_idx is not None and asof_idx < len(cells):
            if not _DATE_RE.search(cells[asof_idx]):
                findings.append(
                    f"MAP-ENTRY-NO-ASOF: {map_path}:{lineno} entry has no real As-of date - "
                    "provenance must be datable (ADR-003)"
                )
        anchor_idx = next((i for n, i in columns.items() if "anchor" in n), None)
        if anchor_idx is not None and anchor_idx < len(cells):
            cell = cells[anchor_idx]
            sha_m = _SHA_RE.search(cell)
            if sha_m:
                entry_shas.setdefault(sha_m.group(0), lineno)
            elif not _NOVCS_CELL_RE.match(cell):
                findings.append(
                    f"MAP-ENTRY-NO-ANCHOR: {map_path}:{lineno} entry anchor cell holds "
                    f"neither a commit SHA nor `no-vcs` ({cell[:30]!r}) - entry provenance "
                    "may not be decorative (ADR-003)"
                )
        if map_skeleton_on:
            # Substring lookups throughout (not columns.get("area")/("entry") exact-match) -
            # matching the same rename-tolerant column-driven design already used for
            # asof_idx/anchor_idx/paths_idx above. Bug found 2026-08-06 (Chunk E): "entry"
            # was an exact-match .get() while every sibling column used a substring search,
            # so it never matched the documented template's own header ("Entry (a durable
            # code fact - NOT a finding or an activity note)") - MAP-DEAD-POINTER silently
            # never fired for any project that followed the template as written.
            #
            # The sidecar KEY per row is the Area column on the root map (many areas, one
            # table) but an ID column on an area file (one area, many entries, no Area
            # column to key on - docs/templates/codebase-map-area.md) - try Area first,
            # fall back to ID, so ONE function handles both table shapes with no bespoke
            # area-file branch.
            key_idx = next((i for n, i in columns.items() if "area" in n), None)
            if key_idx is None:
                key_idx = next((i for n, i in columns.items() if "id" in n), None)
            paths_idx = next((i for n, i in columns.items() if "paths" in n), None)
            if (
                key_idx is not None
                and paths_idx is not None
                and key_idx < len(cells)
                and paths_idx < len(cells)
            ):
                area = cells[key_idx].strip()
                globs = _split_paths_cell(cells[paths_idx])
                if area and globs:
                    drift_rows.append((lineno, area, globs))
            entry_idx = next((i for n, i in columns.items() if "entry" in n), None)
            if entry_idx is not None and entry_idx < len(cells):
                citation_checks.append((lineno, cells[entry_idx]))
    if not found_entry_table:
        # Fallback for legacy maps whose entries table predates the Basis column: the old
        # section-name scan, so their rows still get the basis check.
        in_entries = False
        for lineno, line in enumerate(lines, start=1):
            if line.startswith("#"):
                in_entries = "map entries" in line.lower()
                continue
            if not in_entries or not line.lstrip().startswith("|"):
                continue
            stripped = line.strip().strip("|").strip()
            if not stripped or set(stripped) <= {"-", "|", ":", " "}:
                continue
            first_cell = stripped.split("|", 1)[0].strip().lower()
            if first_cell in {"#", ""}:
                continue  # column-header row
            if "📊" not in line and "🧠" not in line:
                findings.append(
                    f"MAP-NO-BASIS: {map_path}:{lineno} map entry has no 📊 observed / 🧠 "
                    "inferred tag - every entry must state its evidence basis"
                )
    resolved = _cached_batch_resolve_shas(list(entry_shas), map_path.parent, head)
    for sha, lineno in sorted(entry_shas.items(), key=lambda kv: kv[1]):
        if resolved.get(sha) is False:
            findings.append(
                f"MAP-STALE-ENTRY-ANCHOR: {map_path}:{lineno} entry anchor {sha} does not "
                "resolve in this repository - re-verify the entry and refresh its anchor"
            )

    if map_skeleton_on:
        findings.extend(_check_map_drift(map_path, project_dir, drift_rows))
        findings.extend(_check_map_dead_pointers(map_path, project_dir, citation_checks))

    for pattern, label in _SECRET_PATTERNS:
        if pattern.search(text):
            findings.append(
                f"MAP-SECRET: {map_path} contains {label}-shaped content - memory files "
                "must never hold secrets/credentials (CLAUDE.md §5); remove and rotate"
            )

    return findings


_VALIDATE_FINDINGS_MODULE_CACHE = None
_FINDINGS_PACK_IO_MODULE_CACHE = None


def _load_findings_pack_io_module():
    """Import scripts.findings_pack_io in BOTH run modes - same dual-mode pattern and
    memoization as _load_validate_findings_module below."""
    global _FINDINGS_PACK_IO_MODULE_CACHE
    try:
        from scripts import findings_pack_io  # normal `-m` / package mode

        return findings_pack_io
    except Exception:  # nosec B110 - probe only; fall through to the file-relative loader
        pass
    if _FINDINGS_PACK_IO_MODULE_CACHE is not None:
        return _FINDINGS_PACK_IO_MODULE_CACHE
    try:
        import importlib.util

        path = Path(__file__).with_name("findings_pack_io.py")
        spec = importlib.util.spec_from_file_location("findings_pack_io", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _FINDINGS_PACK_IO_MODULE_CACHE = module
        return module
    except Exception:
        return None


def _load_validate_findings_module():
    """Import scripts.validate_findings in BOTH run modes - same dual-mode pattern and
    memoization as _load_engagement_state_module / _load_validate_rtm_module above.

    2026-08-03 perf audit: check_findings_packs() used to shell out to this script (one
    subprocess PER PACK - a review with several passes/re-reviews means several packs, so
    several process spawns on every gated Stop event) specifically to stay path-independent
    in plugin mode. The __file__-relative fallback branch here gives the exact same
    path-independence without a subprocess: it resolves the file next to this one, exactly
    as the subprocess invocation did, just executed in-process."""
    global _VALIDATE_FINDINGS_MODULE_CACHE
    try:
        from scripts import validate_findings  # normal `-m` / package mode

        return validate_findings
    except Exception:  # nosec B110 - probe only; fall through to the file-relative loader
        pass
    if _VALIDATE_FINDINGS_MODULE_CACHE is not None:
        return _VALIDATE_FINDINGS_MODULE_CACHE
    try:
        import importlib.util

        path = Path(__file__).with_name("validate_findings.py")
        spec = importlib.util.spec_from_file_location("validate_findings", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _VALIDATE_FINDINGS_MODULE_CACHE = module
        return module
    except Exception:
        return None


_RENDER_FINDINGS_MODULE_CACHE = None
_RENDER_HTML_MODULE_CACHE = None


def _load_render_findings_module():
    """Import scripts.render_findings in BOTH run modes - same dual-mode pattern and
    memoization as _load_validate_findings_module above.

    2026-08-05 perf fix: apply_fixes() used to shell out to this script once PER PACK,
    immediately followed by one subprocess spawn PER UN-RENDERED .md (see
    _load_render_html_module below) - on a host where every python.exe spawn is inflated by
    endpoint-security scanning (corp Windows), a handover pack with several deliverables
    chained enough untimed spawns to present as the whole close step hanging. Both loops in
    apply_fixes() now call the render function in-process instead."""
    global _RENDER_FINDINGS_MODULE_CACHE
    try:
        from scripts import render_findings

        return render_findings
    except Exception:  # nosec B110 - probe only; fall through to the file-relative loader
        pass
    if _RENDER_FINDINGS_MODULE_CACHE is not None:
        return _RENDER_FINDINGS_MODULE_CACHE
    try:
        import importlib.util

        path = Path(__file__).with_name("render_findings.py")
        spec = importlib.util.spec_from_file_location("render_findings", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _RENDER_FINDINGS_MODULE_CACHE = module
        return module
    except Exception:
        return None


def _load_render_html_module():
    """Import scripts.render_html in BOTH run modes - same dual-mode pattern as
    _load_render_findings_module above (2026-08-05 perf fix)."""
    global _RENDER_HTML_MODULE_CACHE
    try:
        from scripts import render_html

        return render_html
    except Exception:  # nosec B110 - probe only; fall through to the file-relative loader
        pass
    if _RENDER_HTML_MODULE_CACHE is not None:
        return _RENDER_HTML_MODULE_CACHE
    try:
        import importlib.util

        path = Path(__file__).with_name("render_html.py")
        spec = importlib.util.spec_from_file_location("render_html", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _RENDER_HTML_MODULE_CACHE = module
        return module
    except Exception:
        return None


_MAP_FINGERPRINT_MODULE_CACHE = None


def _load_map_fingerprint_module():
    """Import scripts.map_fingerprint in BOTH run modes - same dual-mode pattern as
    _load_render_findings_module above (ADR-007 Phase 1 Chunk C: MAP-DRIFT needs
    compute_fingerprint to agree byte-for-byte with what repo_skeleton --fingerprint wrote)."""
    global _MAP_FINGERPRINT_MODULE_CACHE
    try:
        from scripts import map_fingerprint

        return map_fingerprint
    except Exception:  # nosec B110 - probe only; fall through to the file-relative loader
        pass
    if _MAP_FINGERPRINT_MODULE_CACHE is not None:
        return _MAP_FINGERPRINT_MODULE_CACHE
    try:
        import importlib.util

        path = Path(__file__).with_name("map_fingerprint.py")
        spec = importlib.util.spec_from_file_location("map_fingerprint", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _MAP_FINGERPRINT_MODULE_CACHE = module
        return module
    except Exception:
        return None


def check_findings_packs(artifacts_dir: Path) -> list[str]:
    """Validate any structured findings pack under artifacts/data/ against the schema,
    in-process (2026-08-03 perf audit - was one subprocess spawn per pack). A pack that
    fails is FINDINGS-INVALID: the model fixes the DATA, not the rendered report. Inert
    until packs exist (fails open if the validator module won't load). Recursive over the
    data/ lane (2026-07-29 register P5: nested packs went unvalidated)."""
    findings: list[str] = []
    data_dir = artifacts_dir / "data"
    if not data_dir.is_dir():
        return findings
    vf = _load_validate_findings_module()
    if vf is None:
        return findings  # validator unavailable - fail open, same posture as before
    for pack in sorted(data_dir.rglob("findings-*.jsonl")):
        try:
            errs = vf.load_and_validate(pack)
        except (OSError, ValueError) as exc:
            findings.append(f"FINDINGS-INVALID: {pack.name} - cannot read/parse {pack}: {exc}")
            continue
        except Exception:  # nosec B112 - deliberate fail-open, see comment below
            continue  # an unexpected validator crash must not brick the gate (fail open)
        if errs:
            findings.append(f"FINDINGS-INVALID: {pack.name} - " + "; ".join(errs))
    return findings


# Kinds whose findings are genuinely scored and filtered by review-scorer
# (docs/code-review-method.md): compliance/model-validation are never score-filtered, and
# the scorer's dedup pass over those is optional - so they are exempt from PACK-UNSCORED.
_SCORED_PACK_KINDS = {"review", "security-audit", "performance"}
_SCORER_ATTEST_RE = re.compile(r"(?i)review[-_ ]?scorer")


def check_findings_scoring(artifacts_dir: Path) -> list[str]:
    """PACK-UNSCORED: a scored-kind findings pack must record its review-scorer pass.

    Born of two live runs on 2026-08-08 (a Flask review and a full-lifecycle golden case)
    where the review-scorer delegation was silently skipped in BOTH, after two prior prose
    strengthenings of the same rule - the pipeline step exists only in instructions the
    orchestrator does not reliably follow, and nothing on disk evidenced whether it ran.
    This makes the evidence mechanical: a pack of a scored kind (review / security-audit /
    performance - docs/code-review-method.md: those findings are genuinely filtered, and
    the scorer still runs even after self-scoring) that carries findings must record the
    scorer pass in its envelope `scoring` field. By construction never a wrong accusation:
    a pack that WAS scored but not recorded has a real provenance gap, and the fix is to
    record the pass - same posture as STALE-FINDINGS-RENDER. Judgement item, never
    auto-fixed (recording a scorer pass that never ran would be fabrication)."""
    findings: list[str] = []
    data_dir = artifacts_dir / "data"
    if not data_dir.is_dir():
        return findings
    fp_io = _load_findings_pack_io_module()
    if fp_io is None:
        return findings  # loader unavailable - fail open, same posture as before
    unscored: list[tuple[Path, int]] = []
    for pack_path in sorted(data_dir.rglob("findings-*.jsonl")):
        try:
            pack = fp_io.read_pack(pack_path)
        except (OSError, ValueError):
            continue  # FINDINGS-INVALID already covers unreadable/malformed packs
        except Exception:  # nosec B112 - deliberate fail-open, see comment below
            continue  # fail open - an unexpected reader crash must not brick the gate
        if not isinstance(pack, dict):
            continue
        if pack.get("kind", "review") not in _SCORED_PACK_KINDS:
            continue
        n = len(pack.get("findings") or [])
        if n == 0:
            continue  # a clean pack has nothing to score/filter
        scoring = pack.get("scoring")
        if isinstance(scoring, str) and _SCORER_ATTEST_RE.search(scoring):
            continue
        unscored.append((pack_path, n))
    if not unscored:
        return findings
    if len(unscored) == 1:
        pack_path, n = unscored[0]
        findings.append(
            f"PACK-UNSCORED: {pack_path.name} carries {n} finding(s) but its envelope "
            "records no review-scorer pass - code/performance findings are scored and "
            "filtered by review-scorer, even after self-scoring "
            "(docs/code-review-method.md). Dispatch review-scorer over the pack, apply "
            "its numbers, then record the pass in the envelope's `scoring` field (e.g. "
            '"scored by review-scorer: Found N · Reported R · Filtered F"); if the '
            "scorer already ran, record that pass there (judgement item, never "
            "auto-fixed)"
        )
        return findings
    # 2026-08-12 live report: with the old one-string-per-pack shape, several unscored
    # packs in the same engagement (a live corp session hit 3 in one, plus more across
    # sibling engagements in the same project) each repeated the full explanatory
    # paragraph verbatim - a wall of near-identical text for what is really one
    # instruction ("dispatch review-scorer") applied to a short list of packs. State the
    # shared explanation once; list the affected packs concisely rather than repeating it.
    packs_desc = "; ".join(f"{p.name} ({n} finding(s))" for p, n in unscored)
    findings.append(
        f"PACK-UNSCORED: {len(unscored)} packs carry findings but their envelopes "
        "record no review-scorer pass - code/performance findings are scored and "
        "filtered by review-scorer, even after self-scoring "
        "(docs/code-review-method.md). Dispatch review-scorer over each pack, apply "
        "its numbers, then record the pass in the envelope's `scoring` field (e.g. "
        '"scored by review-scorer: Found N · Reported R · Filtered F"); if the '
        "scorer already ran, record that pass there (judgement item, never "
        f"auto-fixed). Affected: {packs_desc}"
    )
    return findings


_FINDING_ID_RE = re.compile(r"^###\s+\S+\s+(\S+)\s+—", re.M)
_TALLY_LINE_RE = re.compile(r"^\*\*Disposition tally:\*\*\s*(.+)$", re.M)
_KIND_PREFIX = {"review": "REVIEW", "security-audit": "SECURITY-AUDIT", "performance": "PERF"}


def check_findings_render_freshness(artifacts_dir: Path) -> list[str]:
    """Close-time reconciliation, mechanised (audit finding #3, 2026-07-30): a 2026-07-25
    live failure shipped a stale finding count and a struck citation still cited elsewhere
    - the close-checklist's "one authoritative number everywhere" rule was, and largely
    still is, a prose re-read-every-document instruction. This closes the two pieces that
    ARE mechanically checkable without inventing a new textual convention: does the
    rendered REVIEW-<slug>.md's finding-ID set and disposition tally still match the
    CURRENT data/findings-<slug>.jsonl pack, or did the pack change after the last render
    (a fix cycle, a re-review) without a re-render catching up. (Late-cycle prose changes
    and struck-citation sweeping stay judgement calls - no existing marker distinguishes a
    struck citation from a live one in free text, so a mechanical check there would be
    guessing at a convention nothing emits yet.)"""
    findings: list[str] = []
    data_dir = artifacts_dir / "data"
    if not data_dir.is_dir():
        return findings
    fp_io = _load_findings_pack_io_module()
    if fp_io is None:
        return findings  # loader unavailable - fail open, same posture as before
    for pack_path in sorted(data_dir.rglob("findings-*.jsonl")):
        try:
            pack = fp_io.read_pack(pack_path)
        except (OSError, ValueError):
            continue  # FINDINGS-INVALID already covers unreadable/malformed packs
        if not isinstance(pack, dict):
            continue
        slug = pack.get("slug")
        if not slug:
            continue
        prefix = _KIND_PREFIX.get(pack.get("kind", "review"), "REVIEW")
        root = pack_path.parent.parent if pack_path.parent.name == "data" else pack_path.parent
        rendered = root / f"{prefix}-{slug}.md"
        if not rendered.is_file():
            continue  # MISSING-HTML-style existence gap is a different, already-covered check
        text = rendered.read_text(encoding="utf-8", errors="replace")
        pack_findings = pack.get("findings") or []
        pack_ids = {f.get("id") for f in pack_findings if isinstance(f, dict) and f.get("id")}
        rendered_ids = set(_FINDING_ID_RE.findall(text))
        if pack_ids != rendered_ids:
            missing = pack_ids - rendered_ids
            extra = rendered_ids - pack_ids
            detail = []
            if missing:
                detail.append(f"in the pack but not rendered: {', '.join(sorted(missing))}")
            if extra:
                detail.append(f"rendered but not in the pack: {', '.join(sorted(extra))}")
            findings.append(
                f"STALE-FINDINGS-RENDER: {rendered.name} finding IDs no longer match "
                f"{pack_path.name} ({'; '.join(detail)}) - the pack changed after the last "
                f"render (run: python -m scripts.render_findings {pack_path})"
            )
            continue  # a mismatched ID set makes a tally comparison meaningless too
        disp_counts = {
            d: sum(1 for f in pack_findings if isinstance(f, dict) and f.get("disposition") == d)
            for d in ("fixed", "open", "accepted", "deferred")
        }
        expected_tally = (
            f"✅ {disp_counts['fixed']}  ·  🔴 {disp_counts['open']}  ·  "
            f"⚖️ {disp_counts['accepted']}  ·  ⏭️ {disp_counts['deferred']}"
        )
        m = _TALLY_LINE_RE.search(text)
        actual_tally = m.group(1).strip() if m else None
        if actual_tally is not None and actual_tally != expected_tally:
            findings.append(
                f"COUNT-MISMATCH: {rendered.name}'s Disposition tally ({actual_tally}) does "
                f"not match {pack_path.name}'s current dispositions ({expected_tally}) - a "
                f"finding's disposition changed after the last render "
                f"(run: python -m scripts.render_findings {pack_path})"
            )
    return findings


_ENGAGEMENT_STATE_MODULE_CACHE = None


def _load_engagement_state_module():
    """Import scripts.engagement_state in BOTH run modes (package import when available,
    __file__-relative load under direct-path plugin invocation). None = module unavailable;
    the state checks then skip rather than brick the gate.

    2026-08-03 perf audit: this is called 6+ times across one check_artifacts run (check_state,
    check_registry, check_root_orphans, ...), and in plugin mode (no `scripts` package on
    path, so the fast branch always fails) the fallback used to re-parse and re-exec this
    file from scratch on every single call. Memoized in a module-level variable - not
    sys.modules, so this cache can never collide with an unrelated `engagement_state` some
    other import path might load."""
    global _ENGAGEMENT_STATE_MODULE_CACHE
    try:
        from scripts import engagement_state  # normal `-m` / package mode

        return engagement_state
    # Probe only; fall through to the file-relative loader.
    except Exception:  # nosec B110
        pass
    if _ENGAGEMENT_STATE_MODULE_CACHE is not None:
        return _ENGAGEMENT_STATE_MODULE_CACHE
    try:
        import importlib.util

        path = Path(__file__).with_name("engagement_state.py")
        spec = importlib.util.spec_from_file_location("engagement_state", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _ENGAGEMENT_STATE_MODULE_CACHE = module
        return module
    except Exception:
        return None


def check_state(artifacts_dir: Path, _all_md: list[Path] | None = None) -> list[str]:
    """Machine-readable engagement state (ADR-006): `engagement-state.json` is the
    authoritative lifecycle record and START-HERE.md is rendered from it. Advisory during
    migration: a legacy engagement with no state file raises nothing - but an index that
    CLAIMS state generation with the state file gone, an invalid state file, or a render
    that no longer matches the state (by embedded state-hash) are real integrity findings.

    `_all_md` (2026-08-03 perf audit): an optional pre-walked `sorted(artifacts_dir.rglob(
    "*.md"))` that check() shares across its several .md-scanning sub-checks, so a gated
    Stop event pays for ONE recursive walk instead of one per sub-check. None (the default,
    and always the case for a direct/standalone call) means "walk it yourself" - behaviour
    is identical either way, this only changes whether the walk is shared or fresh."""
    findings: list[str] = []
    es = _load_engagement_state_module()
    if es is None:
        return findings
    state_file = artifacts_dir / es.STATE_FILENAME
    index = artifacts_dir / "START-HERE.md"
    index_text = index.read_text(encoding="utf-8", errors="replace") if index.is_file() else ""
    if not state_file.is_file():
        if es.STATE_FILENAME in index_text:
            findings.append(
                f"STATE-MISSING: START-HERE.md is generated from {es.STATE_FILENAME} but "
                "the state file is gone - restore it (or re-run "
                "`python -m scripts.engagement_state init` and rebuild the state)"
            )
        return findings
    try:
        state = json.loads(state_file.read_text(encoding="utf-8"))
    except Exception as exc:
        findings.append(f"STATE-INVALID: {es.STATE_FILENAME} is not valid JSON ({exc})")
        return findings
    problems = es.validate_state(state)
    if problems:
        more = f" (+{len(problems) - 1} more)" if len(problems) > 1 else ""
        findings.append(
            f"STATE-INVALID: {es.STATE_FILENAME} fails validation: {problems[0]}{more} - "
            "fix the state, then `python -m scripts.engagement_state render`"
        )
        return findings
    if not index.is_file():
        findings.append(
            f"STATE-STALE-RENDER: {es.STATE_FILENAME} exists but START-HERE.md was never "
            "rendered - run `python -m scripts.engagement_state render`"
        )
    elif es.embedded_hash(index_text) != es.state_hash(state):
        findings.append(
            f"STATE-STALE-RENDER: START-HERE.md no longer matches {es.STATE_FILENAME} "
            "(state-hash differs or is missing) - the state is authoritative; run "
            "`python -m scripts.engagement_state render`"
        )
    else:
        # P7 (2026-07-29 register): the state-hash is copied verbatim into the render, so
        # a hand-edit of the INDEX passed the staleness check. The render also embeds a
        # content-hash; a mismatch means someone edited the generated view directly.
        # Pre-P7 renders (no content-hash in the marker) are tolerated.
        emb_content = getattr(es, "embedded_content_hash", None)
        chash = getattr(es, "content_hash", None)
        if emb_content is not None and chash is not None:
            expected = emb_content(index_text)
            if expected is not None and chash(index_text) != expected:
                findings.append(
                    "INDEX-HAND-EDITED: START-HERE.md content differs from what the state "
                    "rendered - the index is a GENERATED view (ADR-006), never hand-edited; "
                    "put the change into the state via `scripts.engagement_state` mutators "
                    "(--fix re-renders and backs the hand-edited file up)"
                )

    findings.extend(_check_ratified_claims(artifacts_dir, state, _all_md=_all_md))
    return findings


# A line ASSERTS ratification only when it uses the word without pending/withheld phrasing -
# deliberately narrow (2026-07-26 design note: false positives erode trust in the fix-list;
# widen only on evidence).
_RATIFIED_ASSERT_RE = re.compile(r"\bratified\b", re.I)
_RATIFIED_NEGATE_RE = re.compile(
    r"pending|await|flagged|require|to be ratified|not yet|un-?ratified|at close|"
    r"outstanding|for ratification",
    re.I,
)
_RATIFY_STOPWORDS = {"ratification", "ratified", "decision", "close", "human"}


def _check_ratified_claims(
    artifacts_dir: Path, state: dict, _all_md: list[Path] | None = None
) -> list[str]:
    """RATIFIED-CLAIM-PENDING (2026-07-26 live-run review, consolidated finding 2): the FSD
    asserted "ops-lead ratified" while the decision log said pending. When the state records
    a ratification as pending, no artifact may assert it as given. Escalate, never auto-fix.

    `_all_md`: see check_state()'s docstring - an optional pre-walked file list, shared by
    check() across its sub-checks; None walks fresh (identical result, just not shared)."""
    pending = [
        r
        for r in state.get("ratifications") or []
        if isinstance(r, dict) and r.get("status") == "pending"
    ]
    if not pending:
        return []
    findings: list[str] = []
    data_dir = artifacts_dir / "data"
    md_source = _all_md if _all_md is not None else sorted(artifacts_dir.rglob("*.md"))
    for md in md_source:
        if md.name.upper() == "START-HERE.MD" or data_dir in md.parents:
            continue  # the index renders the pending list itself
        text = md.read_text(encoding="utf-8", errors="replace")
        for lineno, line in enumerate(text.splitlines(), 1):
            if not _RATIFIED_ASSERT_RE.search(line) or _RATIFIED_NEGATE_RE.search(line):
                continue
            low = line.lower()
            for r in pending:
                tokens = [
                    w
                    for w in re.findall(r"[a-z0-9_-]{5,}", str(r.get("text", "")).lower())
                    if w not in _RATIFY_STOPWORDS
                ]
                if tokens and any(t in low for t in tokens):
                    findings.append(
                        f"RATIFIED-CLAIM-PENDING: {md.name}:{lineno} asserts a ratification "
                        f"the state records as PENDING ({str(r.get('text'))[:60]!r}) - "
                        "reconcile the claim, or record the human's grant via "
                        "`engagement_state ratify` (escalate: never self-ratify)"
                    )
                    break
    return findings


_HEX32_RE = re.compile(r"\b[0-9a-f]{32}\b", re.I)


def check_review_fingerprints(artifacts_dir: Path) -> list[str]:
    """REVIEW-FINGERPRINT-GAP (2026-07-26 live-run review, consolidated finding 3): the DoD
    claimed "code-reviewed" over a shipped build whose md5 no review pass had seen. Fires
    only when the pack already uses fingerprints (a 32-hex hash appears in a review
    artifact), so packs that never hash raise nothing; then every shipped non-test code
    file's md5 must appear in at least one review artifact. Judgement item - the fix is a
    delta review or an explicit disclosure, never silence."""
    reviews = sorted(artifacts_dir.rglob("review-pass-*.md")) + sorted(
        artifacts_dir.rglob("REVIEW-*.md")
    )
    if not reviews:
        return []
    mentioned: set[str] = set()
    for review in reviews:
        text = review.read_text(encoding="utf-8", errors="replace")
        mentioned.update(h.lower() for h in _HEX32_RE.findall(text))
    if not mentioned:
        return []
    findings: list[str] = []
    for f in sorted(artifacts_dir.rglob("*")):
        if not (
            f.is_file() and f.suffix.lower() in _CODE_EXTS and not _TEST_FILE_RE.search(f.name)
        ):
            continue
        md5 = hashlib.md5(f.read_bytes()).hexdigest()  # nosec B324 - fingerprint, not crypto
        if md5 not in mentioned:
            findings.append(
                f"REVIEW-FINGERPRINT-GAP: {f.name} ships at md5 {md5} but no review "
                "artifact records that fingerprint - the reviewed build is not the shipped "
                "build. Run a delta review of the change, or disclose the un-reviewed "
                "delta explicitly at the DoD code-review row (judgement item)"
            )
    return findings


# RTM gate: `scripts/validate_rtm.py` reports six RTM-* codes; the DoD gate carries the two
# that are unambiguous defects in ANY engagement. RTM-ORPHAN-OBLIGATION and RTM-ORPHAN-TEST are
# deliberately NOT gated - the register is firm-wide and the test suite is project-wide, so both
# are scope-dependent judgement calls (run validate_rtm directly at a review gate for those).
_RTM_GATE_CODES = {
    "RTM-CODE-MISSING": "RTM-UNRESOLVED",
    "RTM-TEST-MISSING": "RTM-UNRESOLVED",
    "RTM-NO-OBLIGATION": "RTM-INCOMPLETE",
    "RTM-MALFORMED": "RTM-INCOMPLETE",
}
# How many per-row details a single aggregated finding prints before "+N more" - one line per
# broken row would swamp the gate output on a large matrix.
_RTM_DETAIL_CAP = 3


_VALIDATE_RTM_MODULE_CACHE = None


def _load_validate_rtm_module():
    """Import scripts.validate_rtm in BOTH run modes (package import, else a __file__-relative
    load under direct-path plugin invocation). None = unavailable; the RTM check then skips
    rather than bricking the gate - the same posture _load_engagement_state_module takes.
    Memoized the same way, for the same reason (2026-08-03 perf audit)."""
    global _VALIDATE_RTM_MODULE_CACHE
    try:
        from scripts import validate_rtm

        return validate_rtm
    # Probe only; fall through to the file-relative loader.
    except Exception:  # nosec B110
        pass
    if _VALIDATE_RTM_MODULE_CACHE is not None:
        return _VALIDATE_RTM_MODULE_CACHE
    try:
        import importlib.util

        path = Path(__file__).with_name("validate_rtm.py")
        spec = importlib.util.spec_from_file_location("validate_rtm", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _VALIDATE_RTM_MODULE_CACHE = module
        return module
    except Exception:
        return None


def check_rtm(
    artifacts_dir: Path, project_root: Path | None = None, _all_md: list[Path] | None = None
) -> list[str]:
    """Gate the traceability spine of any RTM in the pack (CLAUDE.md §8).

    A missing RTM is NOT a finding - most engagements never author one, and absence is the
    normal case. When one exists it is the audit golden thread, so a cell pointing at a file
    that no longer exists (RTM-UNRESOLVED) or a requirement with neither an obligation nor a
    gap disposition (RTM-INCOMPLETE) is a real defect. Findings are aggregated per file and
    per code, and carry the command that reproduces the detail.

    `_all_md`: see check_state()'s docstring - an optional pre-walked file list, shared by
    check() across its sub-checks; None walks fresh (identical result, just not shared).
    """
    validate_rtm = _load_validate_rtm_module()
    if validate_rtm is None:
        return []
    findings: list[str] = []
    md_source = _all_md if _all_md is not None else sorted(artifacts_dir.rglob("*.md"))
    for rtm in md_source:
        if not rtm.stem.lower().startswith("rtm") or _under_archive(rtm, artifacts_dir):
            continue
        try:
            result = validate_rtm.validate(rtm, project_root=project_root)
        except OSError:
            continue  # an unreadable artifact is not this gate's finding to make
        grouped: dict[str, list[str]] = {}
        for f in result["findings"]:
            code = _RTM_GATE_CODES.get(f["code"])
            if code is not None:
                grouped.setdefault(code, []).append(f["detail"])
        for code, details in sorted(grouped.items()):
            extra = len(details) - _RTM_DETAIL_CAP
            more = f" (+{extra} more)" if extra > 0 else ""
            findings.append(
                f"{code}: {rtm.name} - {'; '.join(details[:_RTM_DETAIL_CAP])}{more} - the "
                "BRD → FSD → code → test → obligation trace must hold (run: python -m "
                f"scripts.validate_rtm {rtm})"
            )
    return findings


def check(artifacts_dir: Path) -> list[str]:
    """Return a list of finding strings; empty means the gate is satisfied."""
    findings: list[str] = []

    if not artifacts_dir.is_dir():
        # Nothing delivered yet - nothing to gate. (A missing dir is not a failure: the
        # check is meaningful only once artifacts exist.)
        return findings

    # ONE recursive walk for every .md-scanning sub-check below to share (2026-08-03 perf
    # audit: check_state -> _check_ratified_claims and check_rtm each independently
    # rglob("*.md")'d the same tree check() itself also scans a few lines down - a gated
    # Stop event paid for that walk 3+ times over). Each sub-check still applies its OWN
    # filter to this shared, UNfiltered list exactly as it did to its own fresh rglob() -
    # only the walk is shared, no filtering logic changed.
    all_md = sorted(artifacts_dir.rglob("*.md"))

    findings.extend(check_findings_packs(artifacts_dir))
    findings.extend(check_findings_render_freshness(artifacts_dir))
    findings.extend(check_findings_scoring(artifacts_dir))
    findings.extend(check_state(artifacts_dir, _all_md=all_md))
    findings.extend(check_review_fingerprints(artifacts_dir))
    findings.extend(check_rtm(artifacts_dir, _all_md=all_md))
    # artifacts/data/ holds machine-readable source (findings packs); the top-level artifacts/ is the
    # user-navigable set. Exclude the data/ subtree from the .md/.html-sibling and index scans.
    data_dir = artifacts_dir / "data"
    md_files = [
        m for m in all_md if data_dir not in m.parents and not _under_archive(m, artifacts_dir)
    ]
    for md in md_files:
        # The summary email must be a .txt; a .md copy is the wrong type, not a missing render -
        # flag it and do NOT demand an .html sibling for it (that would be the wrong fix).
        if _SUMMARY_WRONG_EXT_RE.match(md.name):
            findings.append(
                f"SUMMARY-WRONG-EXT: {md.name} - the engagement-summary email must be a .txt "
                "(the one artifact never rendered to HTML); rename it to "
                f"{md.with_suffix('.txt').name} (DoD / CLAUDE.md §6a)"
            )
            continue
        html = md.with_suffix(".html")
        if not html.is_file():
            findings.append(
                f"MISSING-HTML: {md} has no rendered sibling {html.name} "
                "(run: python -m scripts.render_html "
                f"{md})"
            )
        text = md.read_text(encoding="utf-8", errors="replace")
        findings.extend(_collapsed_table_findings(md, text))
        # Per-BLOCK impact check: split the file at each `### ` header and require each block
        # that opens with a 🔴/🟠 finding head to carry its own impact line. A global count let
        # one block with two impact lines mask another with none (2026-07-23 review).
        blocks = re.split(r"(?m)^(?=###\s)", text)
        without_impact = sum(
            1 for b in blocks if _FINDING_HEAD_RE.match(b) and not _IMPACT_LINE_RE.search(b)
        )
        if without_impact:
            findings.append(
                f"FINDING-NO-IMPACT: {md} has {without_impact} Critical/Warning finding "
                "block(s) with no '**Impact if unaddressed:**' line - every finding must "
                "state its impact (docs/review/output-format.md)"
            )
        if _FINDINGS_CWORD_RE.search(text):
            findings.append(
                f"FINDINGS-CWORD-LABELS: {md} labels findings with audit C-words / a '5C summary' - "
                "print the five NAMED fields instead (Standard, Problem, Likely cause, Impact, Fix), "
                "each on its own line, the same five for every finding (docs/review/output-format.md)"
            )
        if _FINDINGS_SECTION_RE.search(text):
            dg = _DEV_GUIDANCE_HEADING_RE.search(text)
            if not dg:
                findings.append(
                    f"FINDINGS-NO-DEV-GUIDANCE: {md} is a review-shaped artifact (has a "
                    "'## Findings' section) but has no '## 🔵 Developer guidance' heading - "
                    "mandatory even on a clean review (docs/review/output-format.md)"
                )
            else:
                rest = text[dg.end() :]
                next_heading = re.search(r"^## ", rest, re.M)
                body = rest[: next_heading.start()] if next_heading else rest
                if not body.strip() or body.strip() == _DEV_GUIDANCE_PLACEHOLDER:
                    findings.append(
                        f"FINDINGS-NO-DEV-GUIDANCE: {md} has the Developer guidance heading "
                        "but the section is empty/unfilled - constructive guidance is mandatory "
                        "even on a clean review, not just the header (docs/review/output-format.md)"
                    )
        findings.extend(check_roster(text, md))
        findings.extend(check_agent_identity(text, md))

    # A wrongly-rendered email copy - the summary email is a .txt only, never an .html.
    for stray in sorted(artifacts_dir.rglob("engagement-summary-*.html")):
        if _under_archive(stray, artifacts_dir):
            continue
        findings.append(
            f"SUMMARY-WRONG-EXT: {stray.name} - the engagement-summary email is a .txt, not "
            ".html; remove this rendered copy (the .txt is the deliverable)"
        )

    # The email itself: always FROM Morgan, agents 🤖-marked, roster/identity rules apply
    # to it exactly as to reports (it is the most-forwarded artifact of the pack).
    for email in sorted(artifacts_dir.rglob("engagement-summary-*.txt")):
        if _under_archive(email, artifacts_dir):
            continue
        email_text = email.read_text(encoding="utf-8", errors="replace")
        findings.extend(check_summary_email(email_text, email))
        findings.extend(check_roster(email_text, email))
        findings.extend(check_agent_identity(email_text, email))

    code_files = [
        f
        for f in artifacts_dir.rglob("*")
        if f.is_file() and f.suffix.lower() in _CODE_EXTS and not _under_archive(f, artifacts_dir)
    ]
    non_test_code = [f for f in code_files if not _TEST_FILE_RE.search(f.name)]
    if non_test_code:
        # 2026-07-29 register G9 [reproduced]: coverage is scoped to the code file's
        # top-level container within this pack. Previously ANY qa-handover*.md in the tree
        # satisfied the gate, so code in one engagement's subfolder passed on a SIBLING
        # engagement's paperwork sitting at the root (the live vendorx case).
        def _container(f: Path) -> str:
            rel = f.relative_to(artifacts_dir)
            return rel.parts[0] if len(rel.parts) > 1 else ""

        qa_handovers = sorted(
            set(artifacts_dir.rglob("qa-handover*.md"))
            | set(artifacts_dir.rglob("*qa-handover*.md"))
        )
        qa_containers = {_container(qa) for qa in qa_handovers}
        test_containers = {_container(f) for f in code_files if _TEST_FILE_RE.search(f.name)}
        by_container: dict[str, list[Path]] = {}
        for f in non_test_code:
            by_container.setdefault(_container(f), []).append(f)
        for container, files in sorted(by_container.items()):
            scope = str(artifacts_dir / container) if container else str(artifacts_dir)
            if container not in qa_containers:
                findings.append(
                    f"CODE-NO-QA: {len(files)} code file(s) in {scope} but no "
                    "qa-handover*.md in the same scope - delivered code requires an "
                    "independent QA pass (DoD; no workflow exempts it, and a sibling "
                    "engagement's handover does not count)"
                )
            if container not in test_containers:
                findings.append(
                    f"CODE-NO-TESTS: {len(files)} code file(s) in {scope} but no "
                    "test files (test_*/-_test.*/*.spec.*) in the same scope - delivered "
                    "code ships with its tests (DoD 'Tested')"
                )
        # A REDUCED QA level must never read as a full pass (2026-08-20). qa_depth is a
        # typed state field, so this is a deterministic check rather than prose-matching:
        # 'quick' narrows what QA authors, and the price of that is the engagement closing
        # PARTIAL and saying so where a reader will see it. CODE-NO-QA above is untouched
        # and no level satisfies it - this gate is about honesty, that one is about
        # existence.
        findings.extend(_qa_depth_findings(artifacts_dir))
        findings.extend(_auto_mode_findings(artifacts_dir))

    # The START-HERE living index: created at OPEN (with the first artifact), updated on
    # every artifact write, finalised at close (docs/templates/start-here.md). It is also
    # the engagement's state record - the one place a reader learns "this is not done yet".
    non_index_md = [m for m in md_files if m.name.upper() != "START-HERE.MD"]
    start_here = next((m for m in md_files if m.name.upper() == "START-HERE.MD"), None)
    status: str | None = None
    if non_index_md and start_here is None:
        findings.append(
            f"MISSING-INDEX: {len(non_index_md)} artifact(s) but no START-HERE.md - the "
            "living index is created at engagement OPEN and updated with every artifact "
            "(docs/templates/start-here.md), not written at the end"
        )
    if start_here is not None:
        index_text = start_here.read_text(encoding="utf-8", errors="replace")
        if _index_status(index_text) is None:
            findings.append(
                f"INDEX-NO-STATUS: {start_here} has no readable engagement Status line "
                "(⏳ in progress / ⛔ blocked - awaiting input / ✅ closed) - state must be "
                "visible so an interim pack is never mistaken for a delivery"
            )
        # C8 (2026-08 audit): this used to be _index_status(index_text) directly - reading
        # ONLY the rendered index, never the state file. Register G5 made pack_status()
        # the one shared status rule (state file authoritative, index fallback) precisely
        # to kill exactly this class of divergent parser; check() alone kept the old
        # index-only read, so a not-yet-rendered index could either spuriously trip
        # FINAL-BEFORE-CLOSE/SUMMARY-BEFORE-CLOSE against a pack the state file already
        # calls closed, or - the dangerous direction - a stale/hand-edited index reading
        # "closed" while the state file says otherwise would silently WAIVE the close-only
        # gate for a pack that was never actually closed. INDEX-NO-STATUS above still
        # checks the index text specifically (a human reader needs a visible status line
        # regardless of what the state file says); everything gating on the overall
        # engagement status now agrees with apply_fixes() and the hooks.
        status = pack_status(artifacts_dir)
        # Every artifact file must be listed in the index (by name), and every local link
        # in the index must resolve - the two directions of index staleness.
        listable = (
            [m for m in non_index_md]
            + sorted(artifacts_dir.rglob("engagement-summary-*.txt"))
            + [
                f
                for f in artifacts_dir.rglob("*")
                if f.is_file() and f.suffix.lower() in _CODE_EXTS
            ]
        )
        # Match filenames as whole tokens, not raw substrings - else a short name (`report.md`)
        # is treated as listed just because a longer listed name (`final-report.md`) contains
        # it (2026-07-23 review).
        listed_names = set(_FILENAME_TOKEN_RE.findall(index_text))
        for f in listable:
            if f.name not in listed_names:
                findings.append(
                    f"STALE-INDEX: {f.name} exists in {artifacts_dir} but is not listed in "
                    "START-HERE.md - the index is updated with every artifact write, "
                    "nothing in the folder goes unlisted"
                )
        for target in _LOCAL_LINK_RE.findall(index_text):
            # Strip a Markdown link title (`file.md "the spec"`) and a #fragment before the
            # existence check - both are valid links to an existing file (2026-07-23 review).
            target = re.sub(r'\s+"[^"]*"$', "", target.strip())
            target = target.split("#", 1)[0].strip()
            if not target or "://" in target or target.startswith("mailto:"):
                continue
            if not (start_here.parent / target).exists():
                findings.append(
                    f"STALE-INDEX: START-HERE.md links to {target!r} which does not exist - "
                    "remove the row or restore the artifact"
                )

    # Close-only artifacts: the delivery report and the summary email SIGNAL a close, so
    # while the engagement is not yet closed they must not exist. Fail-safe (2026-07-29
    # register G1 [reproduced]): NO readable status - an unparseable line OR no index at
    # all - is NOT closed. The old code routed a missing index down the closed/legacy
    # branch, disarming every close-only guard exactly when the team forgot the index
    # (the 2026-07-22 failure class). A 🔒 closing pack is the sanctioned close window:
    # close artifacts are legitimate there, and nothing demands them yet (register R5).
    # C6 (2026-08 audit): this rglob was the one recursive summary-email scan in check()
    # that did NOT exclude .archive'd subtrees (compare the same pattern applied a few
    # lines up for stray START-HERE.html/summary files and code artifacts) - a summary
    # email left behind under an archived nested pack was flagged as SUMMARY-BEFORE-CLOSE
    # against the OUTER, still-open pack that never wrote it.
    summaries = sorted(
        s
        for s in artifacts_dir.rglob("engagement-summary-*.txt")
        if not _under_archive(s, artifacts_dir)
    )
    not_closed = status in ("open", "blocked") or status is None
    if not_closed:
        state = status or ("no index" if start_here is None else "not readable")
        for md in non_index_md:
            if _CLOSE_ONLY_MD_RE.match(md.name) or _CLOSE_ONLY_REVIEW_RE.match(md.name):
                findings.append(
                    f"FINAL-BEFORE-CLOSE: {md.name} exists but the engagement status is "
                    f"'{state}', not closed - the delivery report is written at close only; "
                    "interim output takes a pass-scoped name (review-pass-N / qa-cycle-N / "
                    "interim-*). If this IS the close underway, enter it explicitly "
                    "(`set-status closing`) and finish - never delete completed deliverables"
                )
        if summaries:
            findings.append(
                f"SUMMARY-BEFORE-CLOSE: {len(summaries)} engagement-summary-*.txt present "
                f"but the engagement status is '{state}', not closed - the summary email is "
                "the closing artifact. If this IS the close underway, enter it explicitly "
                "(`set-status closing`) and finish - never delete completed deliverables"
            )
    elif status == "closed":
        # Closed: the closing email is required once there are deliverables to summarise.
        has_deliverables = bool(md_files)
        if has_deliverables and not summaries:
            # Uniform across profiles (user ruling 2026-07-27): every close ends with the
            # summary email - light keeps it SHORT, it does not drop it.
            findings.append(
                "MISSING-SUMMARY-EMAIL: no engagement-summary-*.txt in this pack - the "
                "closing email (DoD / CLAUDE.md §6a) is a required artifact in EVERY "
                "profile (light keeps it short, never absent)"
            )
        # Status is single-source: it lives ONLY in START-HERE. A content artifact still
        # carrying a mutable interim/in-progress banner after close points readers at an
        # out-of-date state (live report 2026-07-24: the brief said "in progress" at close).
        for md in non_index_md:
            head = "\n".join(md.read_text(encoding="utf-8", errors="replace").splitlines()[:8])
            if _STALE_STATUS_RE.search(head):
                findings.append(
                    f"STALE-STATUS: {md.name} still carries an interim/in-progress status "
                    "banner but START-HERE is closed - engagement status lives ONLY in "
                    "START-HERE; remove the stale banner"
                )
            if _STALE_DOCSTATUS_RE.search(head):
                findings.append(
                    f"STALE-DOCSTATUS: {md.name} document-control Status still reads "
                    "Draft/In review/In progress under a ✅ CLOSED index - close it out, "
                    "or state 'pending human sign-off' in the Status value where the human "
                    "act is the only gap (close checklist: reconciliation sweep)"
                )

    return findings


def apply_fixes(artifacts_dir: Path) -> list[str]:
    """Mechanically resolve the auto-fixable DoD defects (docs/DEFINITION-OF-DONE.md 'AUTO-FIX'
    class) so the close does not depend on the model remembering each step:
      * render each findings pack (artifacts/data/findings-*.jsonl) to its canonical
        REVIEW-<slug>.md - AT CLOSE ONLY (🔒 closing / ✅ closed; D4 ruling 2026-07-29,
        register P3: the tool used to manufacture mid-engagement the very artifact the
        prose declares close-only);
      * normalise a mis-typed engagement-summary email (.md / .html) to the required .txt;
      * re-render START-HERE.md from the authoritative state when its embedded content
        hash is stale (STATE-STALE-RENDER), or back up and re-render it when its content
        no longer matches its own embedded hash (INDEX-HAND-EDITED - ADR-006: the index
        is a generated view, so a hand-edit is preserved to a `.bak` sibling, never lost,
        then overwritten by the regenerated render);
      * render every remaining .md that lacks its .html sibling.
    M4 (2026-08 Fable audit): this docstring used to list only 3 of these 4 fix classes -
    the STATE-STALE-RENDER/INDEX-HAND-EDITED re-render (below, before the generic .md
    render pass) is real behaviour that predates this note, just previously undocumented.
    Returns a log of what changed; idempotent (a second run is a no-op)."""
    fixed: list[str] = []
    if not artifacts_dir.is_dir():
        return fixed

    # Render findings packs FIRST (data -> canonical REVIEW-<slug>.md), so the .html render pass
    # below then produces their siblings. render_findings validates + owns the layout, and refuses
    # an invalid pack (that surfaces as FINDINGS-INVALID from the check, not a silent bad report).
    data_dir = artifacts_dir / "data"
    if data_dir.is_dir() and pack_status(artifacts_dir) in ("closing", "closed"):
        rf = _load_render_findings_module()
        if rf is not None:  # fail open if the renderer module won't load, same posture as
            for pack in sorted(data_dir.glob("findings-*.jsonl")):  # check_findings_packs()
                try:
                    out = rf.render_pack_file(pack)
                except Exception:  # nosec B112 - deliberate fail-open, see comment below
                    continue  # invalid pack; FINDINGS-INVALID reports it, don't double-flag
                fixed.append(f"FIXED: rendered {out} from {pack.name}")

    # Normalise the email FIRST so the render pass never renders a mis-typed .md email.
    # C7 (2026-08 audit): every rglob below is now filtered through _under_archive, the
    # same guard check() itself uses for the equivalent scans - an archived pack is
    # frozen (out of scope everywhere else), so --fix must not rename, delete or
    # re-render anything inside one. The .html rglob two blocks down used to UNLINK
    # archived historical copies outright; that was real, not just cosmetic.
    for bad in sorted(artifacts_dir.rglob("engagement-summary-*.md")):
        if _under_archive(bad, artifacts_dir):
            continue
        target = bad.with_suffix(".txt")
        if target.exists():
            continue  # a correct .txt already exists - leave the duplicate for a human
        bad.rename(target)
        fixed.append(f"FIXED SUMMARY-WRONG-EXT: renamed {bad.name} -> {target.name}")
        # Keep the record in sync so the rename can't create a STALE-INDEX. With a state
        # file, the STATE is the record (P7: hand-editing the render is exactly the defect
        # this tool polices) - update the artifact row and let the stale-render branch
        # below re-render. Only a legacy hand-written index is text-patched directly.
        es_sync = _load_engagement_state_module()
        state_file = artifacts_dir / es_sync.STATE_FILENAME if es_sync is not None else None
        if state_file is not None and state_file.is_file():
            try:
                state = json.loads(state_file.read_text(encoding="utf-8"))
                for row in state.get("artifacts") or []:
                    if isinstance(row, dict) and row.get("path") == bad.name:
                        row["path"] = target.name
                        state_file.write_text(
                            json.dumps(state, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8",
                        )
                        fixed.append(
                            f"FIXED STALE-INDEX: updated state artifact row {bad.name} -> "
                            f"{target.name} (index re-renders below)"
                        )
                        break
            except Exception as exc:
                fixed.append(f"COULD-NOT-SYNC state after email rename: {exc}")
        else:
            for idx in artifacts_dir.rglob("START-HERE.md"):
                if _under_archive(idx, artifacts_dir):
                    continue
                itext = idx.read_text(encoding="utf-8", errors="replace")
                if bad.name in itext:
                    idx.write_text(itext.replace(bad.name, target.name), encoding="utf-8")
                    idx.with_suffix(".html").unlink(missing_ok=True)
                    fixed.append(
                        f"FIXED STALE-INDEX: updated START-HERE reference {bad.name} -> "
                        f"{target.name}"
                    )
    for stray in sorted(artifacts_dir.rglob("engagement-summary-*.html")):
        if _under_archive(stray, artifacts_dir):
            continue  # C7: archived is frozen - never delete a historical copy in there
        stray.unlink()
        fixed.append(f"FIXED SUMMARY-WRONG-EXT: removed rendered email copy {stray.name}")

    # Duplicate ghost artifact rows (2026-08-17 live report): a row recorded before the
    # add-artifact path-healing fix carries a mis-rooted path ("artifacts/<slug>/x.md"
    # resolved against the pack dir), flagged added_before_file_existed, and its file
    # can never exist at that resolved path - while a correct row for the SAME basename
    # resolves fine. STALE-INDEX flagged it and --fix used to stall on it (exit 1), so
    # the live session hand-edited state for minutes instead. Removal is mechanically
    # safe exactly when BOTH hold: the flagged path resolves to nothing AND a sibling
    # row with the same basename resolves to a real file - that is this finding's own
    # "remove the row or restore the artifact" instruction, the remove branch.
    es_dup = _load_engagement_state_module()
    if es_dup is not None:
        state_file = artifacts_dir / es_dup.STATE_FILENAME
        if state_file.is_file():
            try:
                state = json.loads(state_file.read_text(encoding="utf-8"))
                rows = [r for r in (state.get("artifacts") or []) if isinstance(r, dict)]
                resolvable = {
                    PurePosixPath(str(r.get("path", "")).replace("\\", "/")).name
                    for r in rows
                    if r.get("path") and (artifacts_dir / str(r["path"])).exists()
                }
                keep, dropped = [], []
                for r in rows:
                    path = str(r.get("path") or "")
                    if (
                        r.get("added_before_file_existed")
                        and path
                        and not (artifacts_dir / path).exists()
                        and PurePosixPath(path.replace("\\", "/")).name in resolvable
                    ):
                        dropped.append(path)
                    else:
                        keep.append(r)
                if dropped:
                    state["artifacts"] = keep
                    state_file.write_text(
                        json.dumps(state, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8",
                    )
                    for path in dropped:
                        fixed.append(
                            f"FIXED STALE-INDEX: removed ghost artifact row {path} "
                            "(added_before_file_existed, never resolvable; the same "
                            "basename resolves via its correct row - index re-renders "
                            "below)"
                        )
            except Exception as exc:
                fixed.append(f"COULD-NOT-FIX ghost artifact rows: {exc}")

    # Re-render the living index from the machine-readable state when the render is stale
    # (ADR-006: the state is authoritative). Before the generic .md render pass, so the fresh
    # START-HERE gets a fresh .html too rather than keeping a stale sibling.
    es = _load_engagement_state_module()
    if es is not None:
        state_file = artifacts_dir / es.STATE_FILENAME
        if state_file.is_file():
            try:
                state = json.loads(state_file.read_text(encoding="utf-8"))
                index = artifacts_dir / "START-HERE.md"
                index_text = (
                    index.read_text(encoding="utf-8", errors="replace") if index.is_file() else ""
                )
                stale = not index.is_file() or es.embedded_hash(index_text) != es.state_hash(state)
                # P7: a hand-edited index (content-hash mismatch) is re-rendered too, but
                # the hand-edited text is preserved in a backup first - never destroyed.
                hand_edited = False
                emb_content = getattr(es, "embedded_content_hash", None)
                chash = getattr(es, "content_hash", None)
                if index.is_file() and not stale and emb_content is not None and chash is not None:
                    expected = emb_content(index_text)
                    hand_edited = expected is not None and chash(index_text) != expected
                if (stale or hand_edited) and not es.validate_state(state):
                    if hand_edited:
                        backup = index.with_name("START-HERE.md.hand-edited.bak")
                        backup.write_text(index_text, encoding="utf-8")
                        fixed.append(
                            "FIXED INDEX-HAND-EDITED: backed up the hand-edited index to "
                            f"{backup.name}, then re-rendered (the index is a generated "
                            "view - ADR-006; put the change into the state instead)"
                        )
                    index.with_suffix(".html").unlink(missing_ok=True)
                    es.render_files(artifacts_dir)
                    fixed.append(
                        "FIXED STATE-STALE-RENDER: re-rendered START-HERE.md from "
                        f"{es.STATE_FILENAME}"
                    )
            except Exception as exc:  # STATE-INVALID surfaces from the check; log, don't crash
                fixed.append(f"COULD-NOT-RENDER START-HERE from state: {exc}")

    # Render every .md lacking its .html sibling, in-process (2026-08-05 perf fix - see
    # _load_render_html_module above).
    rh = _load_render_html_module()
    for md in sorted(artifacts_dir.rglob("*.md")):
        if _under_archive(md, artifacts_dir):
            continue  # C7: don't write a new render into a frozen archived subtree
        if md.with_suffix(".html").is_file():
            continue
        if rh is None:
            fixed.append(f"COULD-NOT-RENDER {md.name}: render_html module unavailable")
            continue
        try:
            out = rh.render_file(md)
        except Exception as exc:
            fixed.append(f"COULD-NOT-RENDER {md.name}: {exc}")
            continue
        fixed.append(f"FIXED MISSING-HTML: rendered {md.name} -> {out.name}")
    return fixed


def workspace_dirs(artifacts_dir: Path) -> list[Path]:
    """STATEFUL engagement workspaces `artifacts/<slug>/` (0.31 layout) - the registrable
    subset. Gating iterates the broader `engagement_packs` (G7)."""
    if not artifacts_dir.is_dir():
        return []
    return sorted(
        p for p in artifacts_dir.iterdir() if p.is_dir() and (p / "engagement-state.json").is_file()
    )


_ROOT_ALLOWLIST = ".dod-root-allowlist.json"
_REGISTRY_NAMES = {"engagements.json", "ENGAGEMENTS.md", "ENGAGEMENTS.html"}


def check_root_orphans(artifacts_dir: Path, create_snapshot: bool = False) -> list[str]:
    """2026-07-29 register G2 [reproduced]: in workspace mode, a file written to the
    artifacts ROOT belonged to no engagement and was checked by NOTHING - a real workspace
    plus `artifacts/orphan-report.md` returned `DoD artifact gate: OK`. Every visible root
    file must now be grandfathered in the snapshot allowlist or it is ORPHAN-ARTIFACT.

    The allowlist (`.dod-root-allowlist.json`) is a one-time snapshot taken by the CLI
    checker on its first workspace-mode run after this rule landed (D2 ruling 2026-07-29:
    pre-existing flat files are exempt; the workspace layout applies to new work only).
    The stop-gate consumer calls this read-only (create_snapshot=False): it never writes
    the snapshot and stays silent until the CLI has taken one - a turn-end hook must not
    mutate the pack it is judging."""
    root_files = sorted(
        p
        for p in artifacts_dir.iterdir()
        if p.is_file() and not p.name.startswith(".") and p.name not in _REGISTRY_NAMES
    )
    allowlist_path = artifacts_dir / _ROOT_ALLOWLIST
    if not allowlist_path.is_file():
        if create_snapshot:
            allowlist_path.write_text(
                json.dumps(
                    {
                        "grandfathered": [p.name for p in root_files],
                        "note": "pre-existing artifacts-root files exempt from "
                        "ORPHAN-ARTIFACT (D2 ruling 2026-07-29); new work goes in "
                        "artifacts/<slug>/",
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            if root_files:
                print(
                    f"note: grandfathered {len(root_files)} pre-existing root file(s) "
                    f"into {allowlist_path.name}"
                )
        return []
    try:
        allowed = set(
            json.loads(allowlist_path.read_text(encoding="utf-8")).get("grandfathered") or []
        )
    except Exception:
        allowed = set()
    return [
        f"ORPHAN-ARTIFACT: {p.name} sits in the artifacts ROOT, outside every engagement "
        "workspace - no per-pack gate covers root files; move it into its engagement's "
        f"artifacts/<slug>/ (pre-existing files are grandfathered in {_ROOT_ALLOWLIST})"
        for p in root_files
        if p.name not in allowed
    ]


def check_registry(artifacts_dir: Path) -> list[str]:
    """REGISTRY-STALE: the derived root registry (engagements.json) no longer matches a
    fresh scan of the packs on disk. Auto-fixed by regeneration under --fix."""
    es = _load_engagement_state_module()
    if es is None or not workspace_dirs(artifacts_dir):
        return []
    try:
        fresh = es.scan_engagements(artifacts_dir)
        reg_path = artifacts_dir / es.REGISTRY_JSON
        if not reg_path.is_file():
            return [
                "REGISTRY-STALE: workspaces exist but the root registry "
                f"({es.REGISTRY_JSON}) is missing - regenerate via "
                "`python -m scripts.engagement_state render` (any mutator regenerates it)"
            ]
        stored = json.loads(reg_path.read_text(encoding="utf-8")).get("engagements")
        if stored != fresh:
            return [
                "REGISTRY-STALE: the root registry no longer matches the workspaces on "
                "disk - it is DERIVED; regenerate it (auto-fixed by --fix)"
            ]
    except Exception as exc:
        return [f"REGISTRY-STALE: registry unreadable ({exc}) - regenerate it"]
    # Nested packs: a state file deeper than artifacts/<slug>/ means an engagement was
    # initialised from inside another workspace (live defect 2026-07-30 - a cd into
    # artifacts/<old>/ before init created artifacts/<old>/artifacts/<new>/). Flag it;
    # the fix is a move, which only the human/PM should perform on real deliverables.
    for sp in sorted(artifacts_dir.rglob("engagement-state.json")):
        if _under_archive(sp, artifacts_dir):
            continue
        rel = sp.relative_to(artifacts_dir)
        if len(rel.parts) > 2:
            return [
                f"NESTED-PACK: {sp.parent} is an engagement pack nested inside another "
                "engagement - packs live at artifacts/<slug>/ only; move the folder "
                f"to {artifacts_dir / sp.parent.name} and re-run the check (a session "
                "that cd's into a workspace before init causes this)"
            ]
    # The HTML mirror is written best-effort: when the render libraries are not
    # installed, every mutation silently updates the .md/.json and leaves the .html
    # behind (user report 2026-07-30) - so its freshness needs an explicit check.
    md_path = artifacts_dir / es.REGISTRY_MD
    html_path = md_path.with_suffix(".html")
    if md_path.is_file():
        hint = (
            "re-render via `python -m scripts.engagement_state render`; if that still "
            "skips it, the HTML render libraries are missing - install them with "
            "`python -m pip install -r requirements.txt` (the installer's pip step)"
        )
        try:
            if not html_path.is_file():
                return [
                    f"REGISTRY-HTML-STALE: {es.REGISTRY_MD} has no rendered .html mirror - {hint}"
                ]
            if html_path.stat().st_mtime < md_path.stat().st_mtime - 1:
                return [
                    f"REGISTRY-HTML-STALE: ENGAGEMENTS.html is older than {es.REGISTRY_MD} "
                    f"(a mutation updated the registry without the mirror) - {hint}"
                ]
        except OSError:
            pass
    return []


_KNOWN_FLAGS = frozenset({"--fix"})


def main(argv: list[str]) -> int:
    _force_utf8_output()
    rest = argv[1:]
    # --slug <workspace> (2026-08-17 live report: a session reached twice for the same
    # `--slug` shape every OTHER team script accepts, got a usage error both times, and
    # burned a retry each): sugar for targeting one workspace, equivalent to passing
    # `<artifacts_dir>/<slug>` positionally.
    slug = None
    if "--slug" in rest:
        i = rest.index("--slug")
        if i + 1 >= len(rest) or rest[i + 1].startswith("-"):
            print("--slug needs a workspace name", file=sys.stderr)
            return 2
        slug = rest[i + 1]
        rest = rest[:i] + rest[i + 2 :]
    # 2026-08-07 (found by a framework-wide audit): `do_fix = "--fix" in argv[1:]` matched
    # only the exact string - a typo'd flag (--fx, --Fix, --fixx) or an unrecognized one
    # was silently ignored rather than erroring, so a human typing `check_artifacts --fx`
    # got a silent check-only run instead of the fix pass they asked for, with nothing
    # telling them why nothing got fixed. Every flag-shaped argument is now validated
    # against the one real flag this script accepts; an unrecognized one is a usage error
    # (exit 2, distinct from 1 = "gate not satisfied"), not a silent no-op.
    unknown = [a for a in rest if a.startswith("-") and a not in _KNOWN_FLAGS]
    if unknown:
        print(
            f"unrecognized flag(s): {' '.join(unknown)} - accepted: --fix, "
            "--slug <workspace> (positional args: [artifacts_dir] [map_path])",
            file=sys.stderr,
        )
        return 2
    do_fix = "--fix" in rest
    positional = [a for a in rest if not a.startswith("-")]
    artifacts_dir = Path(positional[0]) if positional else Path("artifacts")
    if slug:
        artifacts_dir = artifacts_dir / slug
    map_path = Path(positional[1]) if len(positional) > 1 else find_codebase_map(Path.cwd())

    # 0.31 layout: with per-engagement workspaces, each pack is checked in its own scope
    # (findings slug-prefixed) plus the derived-registry consistency and the root orphan
    # scan (G2); a legacy flat pack alongside (or alone) is checked exactly as before.
    # Gating iterates engagement_packs (state file OR index - G7); registry consistency
    # stays keyed on the stateful workspace_dirs subset.
    workspaces = engagement_packs(artifacts_dir)

    if do_fix:
        for pack in workspaces or [artifacts_dir]:
            prefix = f"[{pack.name}] " if pack != artifacts_dir else ""
            for line in apply_fixes(pack):
                print(f"{prefix}{line}")
        if workspace_dirs(artifacts_dir):
            es = _load_engagement_state_module()
            if es is not None and check_registry(artifacts_dir):
                es.render_registry(artifacts_dir)
                print("FIXED REGISTRY-STALE: regenerated the root registry")

    es = _load_engagement_state_module()
    skipped_fresh = 0
    if workspaces:
        findings = []
        for pack in workspaces:
            # 0.33.2 fast path: a closed pack whose stat-only fingerprint still matches
            # the one stored at its gate-passing close needs no content re-scan.
            if es is not None and not do_fix:
                try:
                    state = json.loads((pack / "engagement-state.json").read_text(encoding="utf-8"))
                    if state.get("status") == "closed" and state.get(
                        "scan_fingerprint"
                    ) == es.compute_fingerprint(pack):
                        skipped_fresh += 1
                        continue
                except (
                    Exception
                ):  # best-effort probe; unreadable state falls through to a full scan  # nosec B110
                    pass
            findings.extend(f"[{pack.name}] {f}" for f in check(pack))
        findings.extend(archived_open_packs(artifacts_dir))
        if (artifacts_dir / "engagement-state.json").is_file():
            # A flat pack's rglob checks would cross into sibling workspaces and produce
            # noise; during the transitional coexistence the one finding is "migrate it".
            findings.append(
                "FLAT-PACK-UNMIGRATED: a legacy flat pack coexists with workspaces - run "
                "`python -m scripts.engagement_state migrate` (flat pack not deep-checked "
                "to avoid cross-workspace noise)"
            )
        else:
            findings.extend(check_root_orphans(artifacts_dir, create_snapshot=True))
            # P5: the ROOT data/ lane in workspace mode was validated by nothing.
            findings.extend(check_findings_packs(artifacts_dir))
            findings.extend(check_findings_render_freshness(artifacts_dir))
        findings.extend(check_registry(artifacts_dir))
    else:
        findings = check(artifacts_dir)
    map_note = "no codebase map found - skipped (created at first close, ADR-003)"
    if map_path is not None:
        if map_path.is_file():
            findings.extend(check_map(map_path, project_dir=Path.cwd()))
            map_note = f"map checked: {map_path}"
        else:
            findings.append(f"MAP-NOT-FOUND: {map_path} was given explicitly but does not exist")
            map_note = f"map missing: {map_path}"

    area_files = find_codebase_map_area_files(Path.cwd())
    for area_file in area_files:
        findings.extend(check_map(area_file, project_dir=Path.cwd()))

    notes = [map_note]
    if area_files:
        notes.append(f"{len(area_files)} area file(s) checked")
    if skipped_fresh:
        notes.append(f"{skipped_fresh} closed pack(s) skipped via fingerprint")
    archived_count = sum(
        1
        for p in (artifacts_dir.iterdir() if artifacts_dir.is_dir() else [])
        if p.is_dir() and (p / ".archive").is_file()
    )
    if archived_count:
        notes.append(f"{archived_count} archived dir(s) excluded")
    # Startup-cost nudge: many closed, unarchived, unfingerprinted packs = slow scans
    # the user can end with one command. Informational, never a finding.
    stale_closed = 0
    if es is not None and workspaces:
        for pack in workspaces:
            try:
                st = json.loads((pack / "engagement-state.json").read_text(encoding="utf-8"))
                if st.get("status") == "closed" and not st.get("scan_fingerprint"):
                    stale_closed += 1
            except (
                Exception
            ):  # best-effort nudge count; an unreadable state just isn't counted  # nosec B112
                continue
    if stale_closed >= 5:
        print(
            f"note: {stale_closed} closed engagement(s) are re-scanned every run - archive "
            "them (`python -m scripts.engagement_state archive --all-closed`) or re-close "
            "once to store a fingerprint; either ends the cost"
        )
    note_text = "; ".join(notes)
    if findings:
        for line in findings:
            print(line)
        print(f"DoD artifact gate: {len(findings)} finding(s) - NOT satisfied ({note_text})")
        return 1
    print(f"DoD artifact gate: OK ({artifacts_dir}; {note_text})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
