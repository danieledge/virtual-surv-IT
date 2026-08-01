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
  2a. that record carries a machine-readable ```eval-verdict block that DECLARES a verdict
     and accounts for every case (format below and in evals/README.md), and the declared
     verdict is a pass with zero unadjudicated failures. Added 2026-08-01 after an audit
     found the gate accepted a baseline whose own prose said "No clean-pass claim is made
     for this baseline": existence was the only test, so four versions shipped unevaluated;
  3. freshness - no prompt-bearing file (.claude/agents|skills/**, CLAUDE.md, docs/
     DEFINITION-OF-DONE.md, docs/house-rules.md, docs/team-operating-guide.md,
     docs/WAYS-OF-WORKING.md, docs/code-review-method.md, docs/review/**) has a git commit
     NEWER than the baseline record's last commit. A stale baseline (prompt changed after
     the eval ran) fails the gate.

The verdict block (fenced so a human reading the baseline sees the claim being made):

    ```eval-verdict
    verdict: pass-with-adjudication
    cases_total: 7
    cases_passed_raw: 2
    cases_adjudicated_pass: 5
    unadjudicated_failures: 0
    runs: 20260729T225110Z, 20260730T010541Z
    ```

`scripts.eval_engage` emits the raw draft into each run's report.md; the human adjudicates
failures against the transcripts and moves them into `cases_adjudicated_pass`. The counts
must satisfy raw + adjudicated + unadjudicated == total, and `verdict: pass` may only be
claimed when every case passed RAW - so an adjudicated release says so in machine-readable
form and cannot be mistaken for a clean run.

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
# Every file whose text steers the team at run time. The four docs/ additions (2026-08-01
# audit) are standing instructions the agents read and act on - a change to the DoD, the
# house rules, the ways-of-working menu or the review method changes behaviour exactly as a
# skill edit does, yet none of them aged a baseline before now.
_PROMPT_PATHS = [
    ".claude/agents",
    ".claude/skills",
    "CLAUDE.md",
    "docs/DEFINITION-OF-DONE.md",
    "docs/house-rules.md",
    "docs/team-operating-guide.md",
    "docs/WAYS-OF-WORKING.md",
    "docs/code-review-method.md",
    "docs/review",
]

_VERDICT_FENCE = "eval-verdict"
_VERDICT_BLOCK_RE = re.compile(r"(?ms)^```" + _VERDICT_FENCE + r"[ \t]*\n(.*?)^```[ \t]*$")
_VERDICT_VALUES = ("pass", "pass-with-adjudication", "fail")
_VERDICT_COUNTS = (
    "cases_total",
    "cases_passed_raw",
    "cases_adjudicated_pass",
    "unadjudicated_failures",
)
_VERDICT_TEMPLATE = (
    "```eval-verdict / verdict: pass|pass-with-adjudication|fail / cases_total: N / "
    "cases_passed_raw: N / cases_adjudicated_pass: N / unadjudicated_failures: N / ```"
)


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


def parse_verdict(text: str) -> dict[str, str] | None:
    """Key/value pairs from a baseline's ```eval-verdict block; None when there is none.

    Values are returned as raw strings (the caller decides what must be an integer).
    Blank lines and `#` comments inside the block are ignored, and only the FIRST block is
    read - a baseline that pastes a second draft below cannot quietly override the claim.
    """
    m = _VERDICT_BLOCK_RE.search(text)
    if not m:
        return None
    fields: dict[str, str] = {}
    for line in m.group(1).splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, _, value = line.partition(":")
        fields[key.strip().lower()] = value.strip()
    return fields


def _verdict_findings(baseline_name: str, text: str) -> list[str]:
    """Gate findings from the baseline's verdict block: is a PASS actually being claimed,
    and does the case arithmetic account for every case? Empty list = the claim is clean."""
    fields = parse_verdict(text)
    if fields is None:
        return [
            f"RELEASE-GATE: {baseline_name} has no machine-readable ```eval-verdict block - "
            f"the gate cannot read a verdict out of prose. Add: {_VERDICT_TEMPLATE} "
            "(scripts.eval_engage drafts it into each run's report.md; see evals/README.md)"
        ]

    findings: list[str] = []
    verdict = fields.get("verdict", "").lower()
    if verdict not in _VERDICT_VALUES:
        findings.append(
            f"RELEASE-GATE: {baseline_name} eval-verdict '{verdict or 'missing'}' is not one of "
            f"{'|'.join(_VERDICT_VALUES)}"
        )

    counts: dict[str, int] = {}
    for key in _VERDICT_COUNTS:
        raw = fields.get(key)
        if raw is None:
            findings.append(f"RELEASE-GATE: {baseline_name} eval-verdict block is missing '{key}'")
        elif not re.fullmatch(r"\d+", raw):
            findings.append(
                f"RELEASE-GATE: {baseline_name} eval-verdict '{key}: {raw}' is not a whole number"
            )
        else:
            counts[key] = int(raw)
    if len(counts) < len(_VERDICT_COUNTS):
        return findings  # arithmetic checks below need all four

    total = counts["cases_total"]
    accounted = (
        counts["cases_passed_raw"]
        + counts["cases_adjudicated_pass"]
        + counts["unadjudicated_failures"]
    )
    if total <= 0:
        findings.append(f"RELEASE-GATE: {baseline_name} eval-verdict records cases_total: {total}")
    elif accounted != total:
        findings.append(
            f"RELEASE-GATE: {baseline_name} eval-verdict counts do not add up - "
            f"{counts['cases_passed_raw']} raw + {counts['cases_adjudicated_pass']} adjudicated + "
            f"{counts['unadjudicated_failures']} unadjudicated = {accounted}, cases_total {total}"
        )
    if counts["unadjudicated_failures"] > 0:
        findings.append(
            f"RELEASE-GATE: {baseline_name} records {counts['unadjudicated_failures']} "
            "UNADJUDICATED eval failure(s) - adjudicate each against its transcript (or re-run "
            "the case) before promoting; a truncated/budget-killed case is unevidenced, not passed"
        )
    if verdict == "fail":
        findings.append(f"RELEASE-GATE: {baseline_name} declares 'verdict: fail'")
    if verdict == "pass" and counts["cases_passed_raw"] != total:
        findings.append(
            f"RELEASE-GATE: {baseline_name} claims a clean 'verdict: pass' but only "
            f"{counts['cases_passed_raw']}/{total} cases passed RAW - declare "
            "'verdict: pass-with-adjudication' so the record cannot be misread"
        )
    return findings


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

    # 2a. The declared verdict - the record has to CLAIM a pass, in machine-readable form.
    findings += _verdict_findings(baseline.name, text)

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
