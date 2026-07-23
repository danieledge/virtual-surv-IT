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
     engagement Status (⏳ in progress / ⛔ blocked / ✅ closed), and stays current: every
     artifact file is listed in it, every local link in it resolves. Born of a live
     failure (2026-07-22): an engagement stalled on an unanswered clarification, the user
     read an interim report as the delivery, and QA never ran - state must be visible;
  3. close-only artifacts stay close-only: `delivery-report*.md` / `final-*` and the
     `engagement-summary-*.txt` email may exist only when the index Status is ✅ closed
     (before that they mislabel work-in-progress as a delivery);
  4. at least one `engagement-summary-*.txt` exists once the engagement is ✅ closed (or in
     a legacy folder with no status to read) - the required closing email, §6a;
  5. if the working project has a codebase map (ADR-003: `docs/codebase-map.md` or root
     `CODEBASE-MAP.md`), it passes mechanical hygiene: bounded size, an As-of date and a
     commit-SHA anchor in the header, 📊/🧠 basis tags on map entries, no secret-shaped
     content, and (best effort, when `git` is available) an anchor that still resolves.
     A missing map is NOT a failure - first engagements create it at close.

Exit 0 = gate satisfied; exit 1 = findings printed (one line each, machine-readable prefix).
No third-party dependencies. Usage:
`python -m scripts.check_artifacts [artifacts_dir] [codebase_map_path]`.
"""

from __future__ import annotations

import re

# Used for one fixed-argv git query below - no shell, no untrusted argv.
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
_NOVCS_ANCHOR_RE = re.compile(r"(?i)\bno[\s-]?(?:vcs|git)\b")

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
# Short forms an artifact might use in a `Name (role)` attribution, mapped to the canonical slug.
# Deliberately conservative - a bare "sme" is ambiguous (three SMEs) and is NOT matched.
_ROLE_ALIASES = {
    "pm": "pm",
    "project-manager": "pm",
    "orchestrator": "pm",
    "ba": "business-analyst",
    "qa": "qa-engineer",
    "qa-engineer": "qa-engineer",
    "code-reviewer": "code-reviewer",
    "compliance-reviewer": "compliance-reviewer",
    "performance-reviewer": "performance-reviewer",
    "data-quality-reviewer": "data-quality-reviewer",
    "model-validator": "model-validator",
    "tm-sme": "tm-sme",
    "trade-surveillance-sme": "trade-surveillance-sme",
    "comms-surveillance-sme": "comms-surveillance-sme",
    "rules-developer": "rules-developer",
    "data-analyst": "data-analyst",
    "tuning-analyst": "tuning-analyst",
    "ml-engineer": "ml-engineer",
    "platform-engineer": "platform-engineer",
    "business-analyst": "business-analyst",
    "review-scorer": "review-scorer",
}
# Persona attribution pattern: "Name (role)". Name is a single capitalised word.
_PERSONA_RE = re.compile(r"\b([A-Z][a-z]{2,})\s*\(([A-Za-z][A-Za-z /_-]{1,40})\)")


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
                "(auto-fix: replace with the canonical persona, never invent a specialist)"
            )
    return findings


# Engagement-state gate: the START-HERE index is a LIVING document (created at open,
# updated on every artifact write, finalised at close) and carries the engagement Status.
# A live failure (2026-07-22) motivated it: an engagement paused on an unanswered
# clarification, the close never ran, no DoD gate ever fired, and an interim report with a
# final-sounding name was read as the delivery - with QA never run. The status makes
# "not done" visible; the close-only rules below stop interim work masquerading as final.
_STATUS_LINE_RE = re.compile(r"(?im)^.*\bstatus\b.*$")
# Local link targets in the index ([text](file.md)) - no scheme, no pure-anchor links.
_LOCAL_LINK_RE = re.compile(r"\]\(([^)#][^)]*)\)")
# Files that may only exist once the engagement is closed.
_CLOSE_ONLY_MD_RE = re.compile(r"(?i)^(delivery-report.*|final-.*)\.md$")


def _index_status(text: str) -> str | None:
    """Read the engagement status from START-HERE text: 'open' | 'blocked' | 'closed'.

    Emoji first (the template's canonical form), then words, scanning only lines that
    mention "status" so prose elsewhere can't masquerade as state. None = no status found.
    """
    for line in _STATUS_LINE_RE.findall(text):
        if "✅" in line:
            return "closed"
        if "⛔" in line:
            return "blocked"
        if "⏳" in line:
            return "open"
        lowered = line.lower()
        if re.search(r"\bclosed\b", lowered):
            return "closed"
        if re.search(r"\bblocked\b", lowered):
            return "blocked"
        if re.search(r"\bin progress\b|\bopen\b", lowered):
            return "open"
    return None


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


def check_map(map_path: Path) -> list[str]:
    """Mechanical hygiene findings for a codebase map; empty means the gate is satisfied."""
    findings: list[str] = []
    text = map_path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()

    if len(lines) > _MAP_MAX_LINES:
        findings.append(
            f"MAP-TOO-LONG: {map_path} is {len(lines)} lines (target ~200, max "
            f"{_MAP_MAX_LINES}) - move detail to linked docs/artifacts, keep the map an index"
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
    elif _NOVCS_ANCHOR_RE.search(anchor_line):
        # A working project with no git repo has no commit SHA to anchor to. An honest
        # `Anchor no-vcs` (the team is instructed to write exactly this, with a note) is a
        # valid anchor, not a defect - entries anchor to the delivered file state instead.
        pass
    else:
        findings.append(
            f"MAP-NO-ANCHOR: {map_path} header has no `Anchor <commit sha>` - entries "
            "cannot be checked against the code they describe (a working project with no "
            "git repo writes `Anchor no-vcs`)"
        )

    # Every map-entry table row needs a 📊/🧠 basis tag. Entry rows are the data rows of
    # the "Map entries" section's table (skip its header and |---| divider rows).
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

    for pattern, label in _SECRET_PATTERNS:
        if pattern.search(text):
            findings.append(
                f"MAP-SECRET: {map_path} contains {label}-shaped content - memory files "
                "must never hold secrets/credentials (CLAUDE.md §5); remove and rotate"
            )

    return findings


def check(artifacts_dir: Path) -> list[str]:
    """Return a list of finding strings; empty means the gate is satisfied."""
    findings: list[str] = []

    if not artifacts_dir.is_dir():
        # Nothing delivered yet - nothing to gate. (A missing dir is not a failure: the
        # check is meaningful only once artifacts exist.)
        return findings

    md_files = sorted(artifacts_dir.rglob("*.md"))
    for md in md_files:
        html = md.with_suffix(".html")
        if not html.is_file():
            findings.append(
                f"MISSING-HTML: {md} has no rendered sibling {html.name} "
                "(run: python -m scripts.render_html "
                f"{md})"
            )
        text = md.read_text(encoding="utf-8", errors="replace")
        heads = len(_FINDING_HEAD_RE.findall(text))
        impacts = len(_IMPACT_LINE_RE.findall(text))
        if heads and impacts < heads:
            findings.append(
                f"FINDING-NO-IMPACT: {md} has {heads} Critical/Warning finding block(s) but "
                f"only {impacts} '**Impact if unaddressed:**' line(s) - every finding must "
                "state its impact (docs/review/output-format.md)"
            )
        findings.extend(check_roster(text, md))

    code_files = [
        f for f in artifacts_dir.rglob("*") if f.is_file() and f.suffix.lower() in _CODE_EXTS
    ]
    non_test_code = [f for f in code_files if not _TEST_FILE_RE.search(f.name)]
    if non_test_code:
        qa_handovers = sorted(artifacts_dir.rglob("qa-handover*.md")) + sorted(
            artifacts_dir.rglob("*qa-handover*.md")
        )
        if not qa_handovers:
            findings.append(
                f"CODE-NO-QA: {len(non_test_code)} code file(s) in {artifacts_dir} but no "
                "qa-handover*.md - delivered code requires an independent QA pass "
                "(DoD; no workflow exempts it)"
            )
        test_files = [f for f in code_files if _TEST_FILE_RE.search(f.name)]
        if not test_files:
            findings.append(
                f"CODE-NO-TESTS: {len(non_test_code)} code file(s) in {artifacts_dir} but no "
                "test files (test_*/-_test.*/*.spec.*) - delivered code ships with its tests "
                "(DoD 'Tested')"
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
        for f in listable:
            if f.name not in index_text:
                findings.append(
                    f"STALE-INDEX: {f.name} exists in {artifacts_dir} but is not listed in "
                    "START-HERE.md - the index is updated with every artifact write, "
                    "nothing in the folder goes unlisted"
                )
        for target in _LOCAL_LINK_RE.findall(index_text):
            target = target.strip()
            if "://" in target or target.startswith("mailto:"):
                continue
            if not (start_here.parent / target).exists():
                findings.append(
                    f"STALE-INDEX: START-HERE.md links to {target!r} which does not exist - "
                    "remove the row or restore the artifact"
                )

    # Close-only artifacts: the delivery report and the summary email SIGNAL a close, so
    # while the index says the engagement is still open/blocked they must not exist yet -
    # an interim pack carrying them is how work-in-progress gets read as done.
    summaries = sorted(artifacts_dir.rglob("engagement-summary-*.txt"))
    if status in ("open", "blocked"):
        for md in non_index_md:
            if _CLOSE_ONLY_MD_RE.match(md.name):
                findings.append(
                    f"FINAL-BEFORE-CLOSE: {md.name} exists but START-HERE.md says the "
                    f"engagement is still {status} - the delivery report is written at "
                    "close only; interim output takes a pass-scoped name "
                    "(review-pass-N / qa-cycle-N / interim-*)"
                )
        if summaries:
            findings.append(
                f"SUMMARY-BEFORE-CLOSE: {len(summaries)} engagement-summary-*.txt present "
                f"but START-HERE.md says the engagement is still {status} - the summary "
                "email is the closing artifact; a blocked engagement ends its turn stating "
                "what is outstanding instead"
            )
    elif status == "closed" or start_here is None:
        # Closed - or legacy (no index at all): the closing email is required once there
        # are deliverables to summarise. (An index with an unreadable status already got
        # INDEX-NO-STATUS; piling the email demand on top would point at the wrong fix.)
        has_deliverables = bool(md_files)
        if has_deliverables and not summaries:
            findings.append(
                "MISSING-SUMMARY-EMAIL: no artifacts/engagement-summary-*.txt found - the "
                "closing email (DoD / CLAUDE.md §6a) is a required artifact"
            )

    return findings


def main(argv: list[str]) -> int:
    artifacts_dir = Path(argv[1]) if len(argv) > 1 else Path("artifacts")
    map_path = Path(argv[2]) if len(argv) > 2 else find_codebase_map(Path.cwd())

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
