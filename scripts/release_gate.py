#!/usr/bin/env python3
"""Promotion gate for dev -> main: is this version actually ready to become the stable release?

Born of the 2026-07-24 best-practice review: the DoD says team/prompt changes "gate on the eval
harness", yet nine prompt-touching releases shipped with no eval run - a documented gate nobody
runs is decoration. This script makes the promotion condition MECHANICAL:

  1. version consistency - plugin.json version == README badge, and CHANGELOG.md has an entry
     for that version;
  2. an EVAL BASELINE RECORD exists for the version being promoted -
     `evals/eval-baseline-<version>.md` (a tracked point-in-time record of a golden-slice
     `/run-evals` result: date, cases run, pass/fail, notes);
  3. freshness - no prompt-bearing file (.claude/agents|skills/**, CLAUDE.md,
     docs/team-operating-guide.md, docs/review/**) has a git commit NEWER than the baseline
     record's last commit. A stale baseline (prompt changed after the eval ran) fails the gate.

Escape hatch: `--allow-deterministic` accepts a baseline whose record declares
`Scope: deterministic-only` (pytest + scorer, no LLM-judge slice) - intended for patch releases
with no prompt changes; the freshness rule still applies.

Exit 0 = promote; exit 1 = findings printed (`RELEASE-GATE:` prefix). Dependency-free; UTF-8-safe.
Usage: python -m scripts.release_gate [--allow-deterministic]
"""

from __future__ import annotations

import json
import re

# Fixed-argv git queries only - no shell, no untrusted argv.
import subprocess  # nosec B404
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_PROMPT_PATHS = [
    ".claude/agents",
    ".claude/skills",
    "CLAUDE.md",
    "docs/team-operating-guide.md",
    "docs/review",
]


def _force_utf8_output() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass


def _git_last_commit_ts(paths: list[str], root: Path = _ROOT) -> int | None:
    """Unix timestamp of the newest commit touching any of `paths` (None if git unavailable)."""
    try:
        out = subprocess.run(  # nosec B603 B607 - fixed argv
            ["git", "log", "-1", "--format=%ct", "--", *paths],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    ts = out.stdout.strip()
    return int(ts) if ts.isdigit() else None


def gate(root: Path = _ROOT, allow_deterministic: bool = False) -> list[str]:
    findings: list[str] = []

    # 1. Version consistency.
    try:
        version = json.loads((root / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))[
            "version"
        ]
    except (OSError, KeyError, json.JSONDecodeError) as exc:
        return [f"RELEASE-GATE: cannot read plugin version: {exc}"]
    readme = (root / "README.md").read_text(encoding="utf-8", errors="replace")
    m = re.search(r"badge/version-([\d.]+)-", readme)
    if not m or m.group(1) != version:
        findings.append(
            f"RELEASE-GATE: README version badge ({m.group(1) if m else 'missing'}) != "
            f"plugin.json ({version})"
        )
    changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8", errors="replace")
    if f"## [{version}]" not in changelog:
        findings.append(f"RELEASE-GATE: CHANGELOG.md has no entry for [{version}]")

    # 2. Eval baseline record for THIS version.
    baseline = root / "evals" / f"eval-baseline-{version}.md"
    if not baseline.is_file():
        findings.append(
            f"RELEASE-GATE: no eval baseline record evals/eval-baseline-{version}.md - run the "
            "golden-slice /run-evals on dev and record the result before promoting "
            "(CONTRIBUTING.md 'Promotion')"
        )
        return findings  # freshness is meaningless without a baseline

    text = baseline.read_text(encoding="utf-8", errors="replace")
    deterministic_only = re.search(r"(?im)^scope:\s*deterministic-only", text) is not None
    if deterministic_only and not allow_deterministic:
        findings.append(
            f"RELEASE-GATE: {baseline.name} is deterministic-only; a prompt-touching promotion "
            "needs the LLM-judge golden slice (or pass --allow-deterministic for a patch release)"
        )

    # 3. Freshness: prompts must not have changed since the baseline's last commit.
    base_ts = _git_last_commit_ts([f"evals/{baseline.name}"], root)
    prompt_ts = _git_last_commit_ts(_PROMPT_PATHS, root)
    if base_ts is None or prompt_ts is None:
        findings.append(
            "RELEASE-GATE: git history unavailable (or baseline uncommitted) - cannot verify the "
            "baseline is fresher than the prompt changes; commit the baseline record"
        )
    elif prompt_ts > base_ts:
        findings.append(
            "RELEASE-GATE: STALE baseline - prompt files were committed after the eval baseline; "
            "re-run the golden slice against the current prompts and update the record"
        )

    return findings


def main(argv: list[str]) -> int:
    _force_utf8_output()
    allow_det = "--allow-deterministic" in argv[1:]
    findings = gate(allow_deterministic=allow_det)
    if findings:
        for line in findings:
            print(line)
        print(f"release gate: {len(findings)} finding(s) - do NOT promote dev -> main")
        return 1
    print("release gate: OK - promotion conditions met")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
