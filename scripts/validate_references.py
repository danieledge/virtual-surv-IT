#!/usr/bin/env python3
"""Reference checker for the framework's own internals - a link checker pointed inwards.

WHY THIS EXISTS. The repo's most common defect, audit after audit, is not a logic bug: it is a
document referring to something that has moved, been renamed, or never existed. The 2026-08-01
audit alone found ADRs pointing at paths a later ADR superseded, the README calling shipped work
"planned", a dead `apply-dod-stop-hook.sh` pointer of unknown age, and six references broken in
one afternoon by moving two files.

Each of those was previously caught, if at all, by someone writing a bespoke assertion into
`tests/test_docs_consistency.py` AFTER it broke. That file is twelve hand-written checks of the
form "node A's claim about node B must match node B" - the version badge against plugin.json,
the tier table against the frontmatter, the command index against the skills on disk. Meanwhile
the prompt surface references hundreds of distinct paths, and the rest are checked by nobody.

This walks the documentation and prompt surface, extracts every path-like reference, and fails
on any that cannot be resolved. One generic rule instead of a thirteenth bespoke test.

WHAT IT DELIBERATELY DOES NOT FLAG. Precision matters more than recall here: a checker that
cries wolf gets switched off. Three classes are excluded by design.
  * RUNTIME paths - files the TEAM creates during an engagement (`artifacts/<slug>/...`,
    START-HERE, engagement-state.json) or that live in the USER's project (a codebase map,
    team-extensions.md). They are correctly absent from this repo.
  * PLACEHOLDERS and globs - anything carrying `<...>`, `*`, `?` or an ellipsis is a pattern,
    not a path.
  * KNOWN-ABSENT references, listed below WITH A REASON: retired scripts named in an ADR's
    revision history, hypothetical attacker files in a threat model, and scripts a design doc
    proposes but has not built. Each entry is a deliberate judgement, not a silenced failure.

Usage:
    python -m scripts.validate_references            # human-readable, exit 1 on any unresolved
    python -m scripts.validate_references --json     # machine-readable
    python -m scripts.validate_references --orphans  # also list files nothing references
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# Markdown links `](path)` and inline-code spans `path`.
_LINK_RE = re.compile(r"\]\(([^)\s#]+)")
_TICK_RE = re.compile(r"`([^`\n]+)`")
# A reference must look like a real filename, not prose that happens to contain a dot.
_PATHY_RE = re.compile(r"^[\w./-]+\.(?:md|py|sh|json|yaml|yml|html|txt)$")

# A bare basename is a legitimate way to refer to a file the reader can find. These are the
# directories a basename may resolve in, so `agent-design.md` finds docs/agent-design.md.
_SEARCH_DIRS = (
    "",
    "docs",
    "docs/templates",
    "docs/review",
    "docs/review/lenses",
    "docs/adr",
    "docs/internal",
    "docs/scenarios",
    "docs/releases",
    "docs/demos",
    "scripts",
    "scripts/staged_hooks",
    ".claude",
    ".claude/hooks",
    ".claude/agents",
    ".claude-plugin",
    "hooks",
    "evals",
    "evals/rubrics",
    "config",
    "rules",
    "tests",
)

# Created by the team at runtime, or living in the user's working project. Never in this repo.
_MARKER = "." + "exec-consent"
_RUNTIME_PARTS = (
    "artifacts/",
    "START-HERE",
    "ENGAGEMENTS",
    "engagements.json",
    "engagement-state.json",
    ".active-engagement",
    ".dod-root-allowlist",
    "CODEBASE-MAP",
    "codebase-map",
    ".mcp.json",
    "INSTRUCTIONS.md",
    "team-preferences.json",
    "team-extensions.md",
    "engage-probe.json",  # the go-written probe cache (2026-08-18) - runtime, per project
    # The launcher hands a typed request to the session in a file rather than inside the
    # command string (2026-08-25): a quoted value does not survive PowerShell. Written at
    # `go`, read and deleted by the opening session - never present in this repo.
    ".request-pending.txt",
    _MARKER,
    "dashboard.html",
    "scst-dashboard.html",
    "dashboard-data.json",
    ".guard-interpreter",
    "SKILL.md",
    "report.md",
    "score.json",
    "findings.json",
    "gates.json",
    "transcript.md",
    "events.jsonl",
    "expected.yaml",
    "scenario.md",
    "notes.md",
    "results.jsonl",
    "fixture-baseline.json",
    # Pass-scoped artifact names the placement rule PRESCRIBES; they are examples of what the
    # team should call things, not files that exist here.
    "review-pass",
    "qa-cycle",
    "interim-findings",
    "delivery-report.md",
    "qa-handover",
    "engagement-brief",
    "rtm.md",
    "decision-log.md",
    "user-stories.md",
)

# Absent on purpose. Each needs a reason: this is a judgement list, not a way to silence a
# genuine break. Adding an entry without a reason should not pass review.
_KNOWN_ABSENT = {
    "apply-guard-fixes.sh": "retired one-shot script, named in ADR-002's revision history",
    "apply-guard-hardening.sh": "retired one-shot script, named in ADR-002's revision history",
    "evil.py": "hypothetical attacker file in the ADR-002 threat-model proof-of-concepts",
    "scripts/evil.py": "hypothetical attacker file in the ADR-002 threat-model proof-of-concepts",
    "scripts/profile_schema.py": "proposed in docs/internal/prepare-data-design.md, not built",
    # Proposed in the test-container plan (2026-08-25), not built. A plan naming what it
    # intends to add is not the same defect as a doc pointing at something deleted.
    "scripts/installer_app.py": (
        "proposed in docs/internal/plan-installer-tui-2026-08-25.md, not built"
    ),
    "compose.yml": "proposed in docs/internal/plan-test-container-2026-08-25.md, not built",
    "armed.sh": "proposed in docs/internal/plan-test-container-2026-08-25.md, not built",
    "Dockerfile.suite": "proposed in docs/internal/plan-test-container-2026-08-25.md, not built",
    "Dockerfile.fresh": "proposed in docs/internal/plan-test-container-2026-08-25.md, not built",
    "ts002_layering.py": "illustrative deliverable name inside an example QA handover",
    "driver.md": "the `driver-<name>.md` naming pattern, not a file",
    "docs/persona-anchor.md": "ADR-005 offers it as an alternative source; the guide is used",
    "docs/internal/poc-runtime-boundary.md": (
        "the runtime-boundary POC report lives on the local-only poc/runtime-boundary "
        "branch (2026-08-20 owner decision: architecture exploration kept off the public "
        "remote); the backlog entry cites it deliberately"
    ),
    "docs/internal/token-optimisation-plan-2026-08-18.md": (
        "local-only planning doc (gitignored 2026-08-18, owner decision) - present on the dev "
        "box, absent in clones"
    ),
    "docs/internal/ai-runtime-economics-audit-2026-08.md": (
        "local-only planning doc (gitignored 2026-08-18, owner decision)"
    ),
    "docs/internal/prompt-inventory-baseline-2026-08.md": (
        "local-only planning doc (gitignored 2026-08-18, owner decision)"
    ),
}

_SCAN_ROOTS = ("docs", ".claude", "evals")
_SCAN_FILES = ("CLAUDE.md", "README.md", "CONTRIBUTING.md", "SECURITY.md")
# Case fixtures and saved runs are inputs and outputs, not the prompt surface. Captured
# transcripts are excluded for a different reason: they are a verbatim RECORD of a session, so
# the paths inside them are things that existed in that run's sandbox, not claims this repo
# makes about itself. Rewriting one to satisfy a link check would destroy the only property
# that makes it worth keeping.
_SKIP_PARTS = (
    "/runs/",
    "/cases/",
    "/node_modules/",
    "/__pycache__/",
    "/demos/transcripts/",
)


def _scanned_files(root: Path) -> list[Path]:
    files = [root / name for name in _SCAN_FILES if (root / name).is_file()]
    for directory in _SCAN_ROOTS:
        base = root / directory
        if not base.is_dir():
            continue
        files += [p for p in base.rglob("*.md") if not any(part in str(p) for part in _SKIP_PARTS)]
    return sorted(files)


def _is_runtime(ref: str) -> bool:
    return any(part in ref for part in _RUNTIME_PARTS)


def extract_references(text: str) -> set[str]:
    """Path-like references in one document, placeholders and URLs already discarded."""
    found: set[str] = set()
    for candidate in set(_LINK_RE.findall(text)) | set(_TICK_RE.findall(text)):
        ref = candidate.strip().rstrip(".,;:")
        if not ref or " " in ref:
            continue
        if ref.startswith(("http://", "https://", "mailto:", "#")):
            continue
        if any(ch in ref for ch in "<>{}*?|") or "..." in ref:
            continue
        if not _PATHY_RE.match(ref) or _is_runtime(ref):
            continue
        found.add(ref)
    return found


def resolves(ref: str, referrer: Path, root: Path) -> bool:
    """True if *ref* names something reachable: repo-relative, referrer-relative, or by basename."""
    if (root / ref).exists():
        return True
    if (referrer.parent / ref).exists():
        return True
    base = Path(ref).name
    return any((root / d / base).exists() for d in _SEARCH_DIRS)


def check(root: Path = REPO_ROOT) -> tuple[list[dict], int]:
    """Return (unresolved findings, total references checked)."""
    refs: dict[str, set[Path]] = {}
    for path in _scanned_files(root):
        for ref in extract_references(path.read_text(encoding="utf-8", errors="replace")):
            refs.setdefault(ref, set()).add(path)

    findings = []
    for ref, referrers in sorted(refs.items()):
        if ref in _KNOWN_ABSENT:
            continue
        if any(resolves(ref, r, root) for r in referrers):
            continue
        findings.append(
            {
                "reference": ref,
                "referrers": sorted(str(r.relative_to(root)) for r in referrers),
            }
        )
    return findings, len(refs)


def find_orphans(root: Path = REPO_ROOT) -> list[str]:
    """Docs that nothing references. Advisory only: an entry point is legitimately unreferenced."""
    referenced: set[str] = set()
    for path in _scanned_files(root):
        for ref in extract_references(path.read_text(encoding="utf-8", errors="replace")):
            referenced.add(Path(ref).name)
    orphans = []
    for path in sorted((root / "docs").rglob("*.md")):
        if any(part in str(path) for part in _SKIP_PARTS):
            continue
        if path.name not in referenced:
            orphans.append(str(path.relative_to(root)))
    return orphans


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass
    ap = argparse.ArgumentParser(description="Check the framework's internal references resolve.")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--orphans", action="store_true", help="also list unreferenced docs")
    args = ap.parse_args(argv)

    findings, total = check()
    orphans = find_orphans() if args.orphans else []

    if args.json:
        print(json.dumps({"checked": total, "unresolved": findings, "orphans": orphans}, indent=2))
        return 1 if findings else 0

    print(f"references checked: {total}")
    if findings:
        print(f"UNRESOLVED: {len(findings)}")
        for f in findings:
            print(f"  {f['reference']}")
            for r in f["referrers"][:3]:
                print(f"      referenced by {r}")
    else:
        print("all references resolve")
    if args.orphans:
        print(f"\nunreferenced docs: {len(orphans)}")
        for o in orphans:
            print(f"  {o}")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
