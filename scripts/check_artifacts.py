#!/usr/bin/env python3
"""
Mechanical Definition-of-Done check for the artifact gates CI can never see.

`artifacts/` is deliberately git-ignored (engagement deliverables never leave the box), so no
CI job can verify the DoD's "Distributable" and "Engagement-summary email" items - and the
codebase map lives in the *working* project, which our CI never sees either. This script is
the one-command check the PM runs at the gate instead (docs/DEFINITION-OF-DONE.md):

  1. every `artifacts/**/*.md` has a rendered `.html` sibling (same stem, same directory) -
     the `.md` + `.html` dual-artifact rule (CLAUDE.md §8);
  2. at least one `engagement-summary-*.txt` exists (the required closing email, §6a) -
     unless the artifacts directory is empty, in which case there is nothing to gate;
  3. if the working project has a codebase map (ADR-003: `docs/codebase-map.md` or root
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
    if not anchor_sha:
        findings.append(
            f"MAP-NO-ANCHOR: {map_path} header has no `Anchor <commit sha>` - entries "
            "cannot be checked against the code they describe"
        )
    else:
        resolves = _anchor_resolves(anchor_sha.group(0), map_path.parent)
        if resolves is False:
            findings.append(
                f"MAP-STALE-ANCHOR: header anchor {anchor_sha.group(0)} does not resolve "
                "in this repository - refresh the anchor (and re-verify entries) at close"
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

    # An engagement with several deliverables needs an entry point: the START-HERE index
    # (docs/templates/start-here.md), written LAST, listing every artifact and the reading
    # order. Below two .md artifacts there is nothing to index.
    non_index_md = [m for m in md_files if m.name.upper() != "START-HERE.MD"]
    if len(non_index_md) >= 2 and not any(m.name.upper() == "START-HERE.MD" for m in md_files):
        findings.append(
            f"MISSING-INDEX: {len(non_index_md)} artifacts but no START-HERE.md - the "
            "index artifact is the reader's entry point (docs/templates/start-here.md); "
            "write it last, listing everything"
        )

    # The summary email is required per engagement close; mechanically we can only assert
    # "at least one exists once there are deliverables to summarise".
    has_deliverables = bool(md_files)
    summaries = sorted(artifacts_dir.rglob("engagement-summary-*.txt"))
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
