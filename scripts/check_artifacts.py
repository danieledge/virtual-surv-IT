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
  8. any structured findings pack under `artifacts/data/findings-*.json` validates against
     `docs/review/findings-schema.json` (`FINDINGS-INVALID`) - the pack is the source of truth a
     report is rendered from. (`artifacts/data/` is machine-readable source; the top-level
     `artifacts/` stays user-navigable .md/.txt/.html and is what the .html-sibling + index checks
     cover - the data/ subtree is excluded from them.)
  9. AI identity is explicit: an artifact attributing work to a team persona carries a 🤖
     marker (`AGENT-UNMARKED`), and no line joins an agent and a human with `+`/`&`
     (`AGENT-HUMAN-COMBINED`) - roster names must never read as real people, and an agent
     never shares a sign-off line with the human approver (operating guide, "Voice, names
     & console");
 10. in workspace mode, no file sits unchecked in the artifacts ROOT: a root file outside
     every `artifacts/<slug>/` workspace is `ORPHAN-ARTIFACT` unless grandfathered in the
     snapshot allowlist `.dod-root-allowlist.json`, taken on the rule's first run (D2
     ruling 2026-07-29: pre-existing flat files are exempt, the layout applies to new
     work only).

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
from pathlib import Path

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
    "hassan": "tm-sme",
    "camila": "trade-surveillance-sme",
    "cleo": "comms-surveillance-sme",
    "viktor": "model-validator",
    "ravi": "code-reviewer",
    "thabo": "performance-reviewer",
    "layla": "compliance-reviewer",
    "yuki": "data-quality-reviewer",
    "pip": "review-scorer",
}
_ROLE_TO_NAME = {slug: name for name, slug in _ROSTER.items()}
# A `Name (role)` attribution is only treated as a team-persona claim when the parenthetical is
# a FULL, hyphenated team role slug. Short forms (`qa`, `ba`, `orchestrator`, `pm`) are
# DELIBERATELY excluded: they collide with real content - "Airflow (orchestrator)",
# "Independent (QA)", "Second (QA) cycle", "Aisha (BA) from the client" - and would both
# false-alarm and drive a wrong auto-rename (2026-07-23 review). The one live failure used full
# slugs ("Chidi (code-reviewer)"), so full-slug matching still catches the real thing. `project-
# manager` is kept (unambiguous); a bare `sme` is ambiguous (three SMEs) and is not matched.
_ROLE_ALIASES = {slug: slug for slug in _ROSTER.values() if slug != "pm"}
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
_ROSTER_NAMES_RE = "|".join(sorted(n.capitalize() for n in _ROSTER))
_AGENT_JOIN_RE = re.compile(
    rf"\b({_ROSTER_NAMES_RE})\b\s*[+&]\s*([A-Z][a-z]{{2,}})\b"
    rf"|\b([A-Z][a-z]{{2,}})\s*[+&]\s*\b({_ROSTER_NAMES_RE})\b"
)
_AI_MARKER = "🤖"


def check_agent_identity(text: str, where: Path) -> list[str]:
    """Flag artifacts where an agent persona could be read as a real person.

    Fires AGENT-UNMARKED when a definite team-persona attribution (`Name (full-role-slug)`)
    exists but the file has no 🤖 marker at all; AGENT-HUMAN-COMBINED when a roster name and a
    non-roster name share one line joined by `+`/`&`. Both are AUTO-FIX class: add the marker /
    split the line - never a defect handed to the user.
    """
    findings: list[str] = []
    has_persona = any(
        m.group(1).lower() in _ROSTER
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
        if other.lower() in _ROSTER or m.group(0) in seen:
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
    for name in sorted(_ROSTER):
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
        if name in _ROSTER:
            findings.append(
                f"ROSTER-ROLE-MISMATCH: {where} attributes '{m.group(1)} ({role_raw})' but "
                f"{m.group(1)} is the {_ROSTER[name]}; {role} is {expected.capitalize()} "
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
# Judgement item, never auto-fixed - only the PM knows closed vs "pending human sign-off"
# (the latter, stated in the Status value itself, passes this check).
_STALE_DOCSTATUS_RE = re.compile(
    r"(?im)^>.*\bStatus\b[ `'·:]*(?:draft\b(?![^`\n]*pending human sign-off)"
    r"|in review\b(?![^`\n]*pending human sign-off)"
    r"|in progress\b(?![^`\n]*pending human sign-off))"
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
        and ((p / "engagement-state.json").is_file() or (p / "START-HERE.md").is_file())
    )


def find_codebase_map(project_dir: Path) -> Path | None:
    """The map's conventional locations in a working project (ADR-003)."""
    for candidate in (project_dir / "docs" / "codebase-map.md", project_dir / "CODEBASE-MAP.md"):
        if candidate.is_file():
            return candidate
    return None


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


def _split_cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def check_map(map_path: Path) -> list[str]:
    """Mechanical hygiene findings for a codebase map; empty means the gate is satisfied.

    2026-07-29 register M1/M2/M3/M7: the anchor placeholder no longer passes as no-vcs,
    per-entry As-of/Anchor cells are validated (entry SHAs must resolve), the header anchor
    is bounded against HEAD, entry detection is column-driven (rename-tolerant), and the
    line cap excludes the Deprecated section ADR-003 mandates keeping."""
    findings: list[str] = []
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
    if anchor_sha:
        resolves = _anchor_resolves(anchor_sha.group(0), map_path.parent)
        if resolves is False:
            findings.append(
                f"MAP-STALE-ANCHOR: header anchor {anchor_sha.group(0)} does not resolve "
                "in this repository - refresh the anchor (and re-verify entries) at close"
            )
        elif resolves is True:
            # M3: a resolvable anchor can still be ancient - bound it against HEAD.
            budget_m = _STALENESS_BUDGET_RE.search(header)
            budget = int(budget_m.group(1)) if budget_m else _MAP_STALENESS_BUDGET
            behind = _commits_behind(anchor_sha.group(0), map_path.parent)
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
    for sha, lineno in sorted(entry_shas.items(), key=lambda kv: kv[1]):
        if _anchor_resolves(sha, map_path.parent) is False:
            findings.append(
                f"MAP-STALE-ENTRY-ANCHOR: {map_path}:{lineno} entry anchor {sha} does not "
                "resolve in this repository - re-verify the entry and refresh its anchor"
            )

    for pattern, label in _SECRET_PATTERNS:
        if pattern.search(text):
            findings.append(
                f"MAP-SECRET: {map_path} contains {label}-shaped content - memory files "
                "must never hold secrets/credentials (CLAUDE.md §5); remove and rotate"
            )

    return findings


def check_findings_packs(artifacts_dir: Path) -> list[str]:
    """Validate any structured findings pack under artifacts/data/ against the schema. Shells out to
    validate_findings (by path, NOT an import) so this stays path-independent - an installed plugin
    invokes scripts by absolute path. A pack that fails is FINDINGS-INVALID: the model fixes the
    DATA, not the rendered report. Inert until packs exist (fails open if the validator won't run).
    Recursive over the data/ lane (2026-07-29 register P5: nested packs went unvalidated)."""
    findings: list[str] = []
    data_dir = artifacts_dir / "data"
    if not data_dir.is_dir():
        return findings
    validator = Path(__file__).with_name("validate_findings.py")
    for pack in sorted(data_dir.rglob("findings-*.json")):
        try:
            result = subprocess.run(  # nosec B603 - fixed interpreter, our own bundled script, a path
                [sys.executable, str(validator), str(pack)],
                capture_output=True,
                text=True,
            )
        except (OSError, ValueError):
            continue  # a validator that won't launch shouldn't brick the gate (fail open)
        if result.returncode != 0:
            detail = (
                "; ".join(
                    ln.split("FINDINGS-INVALID:", 1)[1].strip()
                    for ln in result.stdout.splitlines()
                    if ln.startswith("FINDINGS-INVALID:")
                )
                or "schema validation failed"
            )
            findings.append(f"FINDINGS-INVALID: {pack.name} - {detail}")
    return findings


def _load_engagement_state_module():
    """Import scripts.engagement_state in BOTH run modes (package import when available,
    __file__-relative load under direct-path plugin invocation). None = module unavailable;
    the state checks then skip rather than brick the gate."""
    try:
        from scripts import engagement_state  # normal `-m` / package mode

        return engagement_state
    # Probe only; fall through to the file-relative loader.
    except Exception:  # nosec B110
        pass
    try:
        import importlib.util

        path = Path(__file__).with_name("engagement_state.py")
        spec = importlib.util.spec_from_file_location("engagement_state", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    except Exception:
        return None


def check_state(artifacts_dir: Path) -> list[str]:
    """Machine-readable engagement state (ADR-006): `engagement-state.json` is the
    authoritative lifecycle record and START-HERE.md is rendered from it. Advisory during
    migration: a legacy engagement with no state file raises nothing - but an index that
    CLAIMS state generation with the state file gone, an invalid state file, or a render
    that no longer matches the state (by embedded state-hash) are real integrity findings."""
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

    findings.extend(_check_ratified_claims(artifacts_dir, state))
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


def _check_ratified_claims(artifacts_dir: Path, state: dict) -> list[str]:
    """RATIFIED-CLAIM-PENDING (2026-07-26 live-run review, consolidated finding 2): the FSD
    asserted "ops-lead ratified" while the decision log said pending. When the state records
    a ratification as pending, no artifact may assert it as given. Escalate, never auto-fix."""
    pending = [
        r
        for r in state.get("ratifications") or []
        if isinstance(r, dict) and r.get("status") == "pending"
    ]
    if not pending:
        return []
    findings: list[str] = []
    data_dir = artifacts_dir / "data"
    for md in sorted(artifacts_dir.rglob("*.md")):
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


def check(artifacts_dir: Path) -> list[str]:
    """Return a list of finding strings; empty means the gate is satisfied."""
    findings: list[str] = []

    if not artifacts_dir.is_dir():
        # Nothing delivered yet - nothing to gate. (A missing dir is not a failure: the
        # check is meaningful only once artifacts exist.)
        return findings

    findings.extend(check_findings_packs(artifacts_dir))
    findings.extend(check_state(artifacts_dir))
    findings.extend(check_review_fingerprints(artifacts_dir))
    # artifacts/data/ holds machine-readable source (findings packs); the top-level artifacts/ is the
    # user-navigable set. Exclude the data/ subtree from the .md/.html-sibling and index scans.
    data_dir = artifacts_dir / "data"
    md_files = [m for m in sorted(artifacts_dir.rglob("*.md")) if data_dir not in m.parents]
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
        findings.extend(check_roster(text, md))
        findings.extend(check_agent_identity(text, md))

    # A wrongly-rendered email copy - the summary email is a .txt only, never an .html.
    for stray in sorted(artifacts_dir.rglob("engagement-summary-*.html")):
        findings.append(
            f"SUMMARY-WRONG-EXT: {stray.name} - the engagement-summary email is a .txt, not "
            ".html; remove this rendered copy (the .txt is the deliverable)"
        )

    # The email itself: always FROM Morgan, agents 🤖-marked, roster/identity rules apply
    # to it exactly as to reports (it is the most-forwarded artifact of the pack).
    for email in sorted(artifacts_dir.rglob("engagement-summary-*.txt")):
        email_text = email.read_text(encoding="utf-8", errors="replace")
        findings.extend(check_summary_email(email_text, email))
        findings.extend(check_roster(email_text, email))
        findings.extend(check_agent_identity(email_text, email))

    code_files = [
        f for f in artifacts_dir.rglob("*") if f.is_file() and f.suffix.lower() in _CODE_EXTS
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
        status = _index_status(index_text)
        if status is None:
            findings.append(
                f"INDEX-NO-STATUS: {start_here} has no readable engagement Status line "
                "(⏳ in progress / ⛔ blocked - awaiting input / ✅ closed) - state must be "
                "visible so an interim pack is never mistaken for a delivery"
            )
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
    summaries = sorted(artifacts_dir.rglob("engagement-summary-*.txt"))
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
      * render each findings pack (artifacts/data/findings-*.json) to its canonical
        REVIEW-<slug>.md - AT CLOSE ONLY (🔒 closing / ✅ closed; D4 ruling 2026-07-29,
        register P3: the tool used to manufacture mid-engagement the very artifact the
        prose declares close-only);
      * normalise a mis-typed engagement-summary email (.md / .html) to the required .txt;
      * render every remaining .md that lacks its .html sibling.
    Returns a log of what changed; idempotent (a second run is a no-op)."""
    fixed: list[str] = []
    if not artifacts_dir.is_dir():
        return fixed

    # Render findings packs FIRST (data -> canonical REVIEW-<slug>.md), so the .html render pass
    # below then produces their siblings. render_findings validates + owns the layout, and refuses
    # an invalid pack (that surfaces as FINDINGS-INVALID from the check, not a silent bad report).
    data_dir = artifacts_dir / "data"
    if data_dir.is_dir() and pack_status(artifacts_dir) in ("closing", "closed"):
        renderer = Path(__file__).with_name("render_findings.py")
        for pack in sorted(data_dir.glob("findings-*.json")):
            result = subprocess.run(  # nosec B603 - fixed interpreter, our own bundled script, a path
                [sys.executable, str(renderer), str(pack)],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                fixed.append(
                    f"FIXED: rendered {result.stdout.split('-> ')[-1].strip()} from {pack.name}"
                )
            # non-zero = invalid pack; the FINDINGS-INVALID check reports it, don't double-flag here

    # Normalise the email FIRST so the render pass never renders a mis-typed .md email.
    for bad in sorted(artifacts_dir.rglob("engagement-summary-*.md")):
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
                itext = idx.read_text(encoding="utf-8", errors="replace")
                if bad.name in itext:
                    idx.write_text(itext.replace(bad.name, target.name), encoding="utf-8")
                    idx.with_suffix(".html").unlink(missing_ok=True)
                    fixed.append(
                        f"FIXED STALE-INDEX: updated START-HERE reference {bad.name} -> "
                        f"{target.name}"
                    )
    for stray in sorted(artifacts_dir.rglob("engagement-summary-*.html")):
        stray.unlink()
        fixed.append(f"FIXED SUMMARY-WRONG-EXT: removed rendered email copy {stray.name}")

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

    # Render every .md lacking its .html sibling. render_html is resolved by __file__-relative
    # path so this works both as `-m scripts.check_artifacts` and by direct-path plugin invocation.
    render_html = Path(__file__).with_name("render_html.py")
    for md in sorted(artifacts_dir.rglob("*.md")):
        if md.with_suffix(".html").is_file():
            continue
        result = subprocess.run(  # nosec B603 - fixed interpreter, our own bundled script, a path arg
            [sys.executable, str(render_html), str(md)],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            fixed.append(
                f"FIXED MISSING-HTML: rendered {md.name} -> {md.with_suffix('.html').name}"
            )
        else:
            fixed.append(f"COULD-NOT-RENDER {md.name}: {(result.stderr or '').strip()[:120]}")
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


def main(argv: list[str]) -> int:
    _force_utf8_output()
    do_fix = "--fix" in argv[1:]
    positional = [a for a in argv[1:] if not a.startswith("-")]
    artifacts_dir = Path(positional[0]) if positional else Path("artifacts")
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

    if workspaces:
        findings = []
        for pack in workspaces:
            findings.extend(f"[{pack.name}] {f}" for f in check(pack))
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
        findings.extend(check_registry(artifacts_dir))
    else:
        findings = check(artifacts_dir)
    map_note = "no codebase map found - skipped (created at first close, ADR-003)"
    if map_path is not None:
        if map_path.is_file():
            findings.extend(check_map(map_path))
            map_note = f"map checked: {map_path}"
        else:
            findings.append(f"MAP-NOT-FOUND: {map_path} was given explicitly but does not exist")
            map_note = f"map missing: {map_path}"

    if findings:
        for line in findings:
            print(line)
        print(f"DoD artifact gate: {len(findings)} finding(s) - NOT satisfied ({map_note})")
        return 1
    print(f"DoD artifact gate: OK ({artifacts_dir}; {map_note})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
