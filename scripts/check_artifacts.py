#!/usr/bin/env python3
"""
Mechanical Definition-of-Done check for the two artifact gates CI can never see.

`artifacts/` is deliberately git-ignored (engagement deliverables never leave the box), so no
CI job can verify the DoD's "Distributable" and "Engagement-summary email" items. This script
is the one-command check the PM runs at the gate instead (docs/DEFINITION-OF-DONE.md):

  1. every `artifacts/**/*.md` has a rendered `.html` sibling (same stem, same directory) -
     the `.md` + `.html` dual-artifact rule (CLAUDE.md §8);
  2. at least one `engagement-summary-*.txt` exists (the required closing email, §6a) -
     unless the artifacts directory is empty, in which case there is nothing to gate.

Exit 0 = gate satisfied; exit 1 = findings printed (one line each, machine-readable prefix).
No third-party dependencies. Usage: `python -m scripts.check_artifacts [artifacts_dir]`.
"""

from __future__ import annotations

import sys
from pathlib import Path


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
    findings = check(artifacts_dir)
    if findings:
        for line in findings:
            print(line)
        print(f"DoD artifact gate: {len(findings)} finding(s) - NOT satisfied")
        return 1
    print(f"DoD artifact gate: OK ({artifacts_dir})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
