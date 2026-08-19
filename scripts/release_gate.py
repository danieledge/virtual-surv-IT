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
  2b. that the declared numbers are CORROBORATED, not merely self-reported (2026-08-01
     review): the slice is wide enough to mean something (`cases_total` >= _MIN_SLICE_CASES,
     overridable with `--min-cases`), the cited `runs:` exist in the tracked results log
     `evals/results.jsonl`, the declared case and raw-pass counts match the rows recorded
     for those runs, and a baseline carrying more than one verdict block is rejected
     outright rather than judged on whichever block the parser happens to reach first;
  3. freshness - no prompt-bearing file (_PROMPT_PATHS, below) has a git commit NEWER than
     the baseline record's last commit, AND no prompt-bearing file is dirty in the working
     tree. A stale baseline (prompt changed after the eval ran) fails the gate, and so does
     an uncommitted prompt edit, which no commit timestamp can see.

The verdict block (fenced so a human reading the baseline sees the claim being made):

    ```eval-verdict
    verdict: pass-with-adjudication
    cases_total: 7
    cases_passed_raw: 2
    cases_adjudicated_pass: 5
    unadjudicated_failures: 0
    runs: 20260729T225110Z, 20260730T010541Z, 20260730T015116Z
    ```

`scripts.eval_engage` emits the raw draft into each run's report.md; the human adjudicates
failures against the transcripts and moves them into `cases_adjudicated_pass`. The counts
must satisfy raw + adjudicated + unadjudicated == total, and `verdict: pass` may only be
claimed when every case passed RAW - so an adjudicated release says so in machine-readable
form and cannot be mistaken for a clean run. `runs:` is required on a full baseline: it is
the only handle the gate has on the evidence, and the drafted block already carries it.

Escape hatch: `--allow-deterministic` accepts a baseline whose record declares
`Scope: deterministic-only` (pytest + scorer, no LLM-judge slice) - intended for patch releases
with no prompt changes; it also waives the `runs:` requirement (there are no live runs to
cite), while the freshness rule and the case floor still apply.

Exit 0 = promote; exit 1 = findings printed (`RELEASE-GATE:` prefix). Dependency-free; UTF-8-safe.
Usage: python -m scripts.release_gate [--allow-deterministic] [--min-cases N]
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
# skill edit does, yet none of them aged a baseline before now. The 2026-08-01 review added
# the rest: the guard hooks and the settings that arm them ARE behaviour under test (the
# injection and consent cases score them), the scope/stack doc supplies the jurisdictions and
# platforms every deliverable cites, the coding standards are the checklist code-reviewer
# grades against, team-extensions drives the extensions cases, and the templates are the
# shape of the artifacts the judge scores.
_PROMPT_PATHS = [
    ".claude/agents",
    ".claude/skills",
    ".claude/hooks",
    ".claude/settings.json",
    "CLAUDE.md",
    "docs/DEFINITION-OF-DONE.md",
    "docs/house-rules.md",
    "docs/team-operating-guide.md",
    "docs/WAYS-OF-WORKING.md",
    "docs/code-review-method.md",
    "docs/coding-standards.md",
    "docs/scope-and-stack.md",
    "docs/team-extensions.md",
    "docs/review",
    "docs/templates",
]

# Smallest golden slice a baseline may stand on. Rationale (set 2026-08-01, review of the
# eval harness): nothing tied `cases_total` to reality, so `cases_total: 1, cases_passed_raw:
# 1, verdict: pass` promoted a release on a single case. CONTRIBUTING's promotion step asks
# for "a representative ~10-15 of the 43 golden cases"; the floor is deliberately set BELOW
# that target, at the widest single slice any committed baseline has actually stood on (6
# cases, 0.33.1 / 2026-07-30), so it rejects the degenerate one-case claim without inventing a
# bar no release has ever cleared. Raise it as the harness gets cheaper; a deliberately narrow
# run (a patch release, a single-surface re-check) passes `--min-cases N` and says so out loud.
_MIN_SLICE_CASES = 6

# Tracked, append-only, one row per scored case-run (evals/README.md). The gate corroborates
# the verdict block against it: run_id, case, passed, mode.
_RESULTS_LOG = "evals/results.jsonl"

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


def _git_dirty_paths(paths: list[str], root: Path = _ROOT) -> list[str] | None:
    """Prompt-bearing paths with UNCOMMITTED changes; [] when clean, None if git is unavailable.

    Covers staged, unstaged and untracked files (`--untracked-files=all`, so a new agent file
    is listed by name rather than as its directory). Commit timestamps cannot see a working-tree
    edit, so without this an uncommitted change to, say, `.claude/agents/code-reviewer.md`
    promotes against a baseline that never exercised it (2026-08-01 review finding).
    """
    try:
        out = subprocess.run(  # nosec B603 B607 - fixed argv
            ["git", "status", "--porcelain", "--untracked-files=all", "--", *paths],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    dirty = set()
    for line in out.stdout.splitlines():
        entry = line[3:].strip()  # porcelain v1: "XY <path>", renames as "<old> -> <new>"
        if entry:
            dirty.add(entry.rpartition(" -> ")[2].strip('"'))
    return sorted(dirty)


def _results_rows(root: Path) -> tuple[list[dict] | None, int]:
    """Rows of the tracked results log, plus a count of lines that would not parse.

    Returns (None, 0) when the log is unreadable or absent - the caller decides whether that
    is fatal (it is, for a baseline claiming runs the log is supposed to corroborate).
    """
    try:
        raw = root.joinpath(*_RESULTS_LOG.split("/")).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None, 0
    rows: list[dict] = []
    unparseable = 0
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            unparseable += 1
            continue
        if isinstance(row, dict):
            rows.append(row)
        else:
            unparseable += 1
    return rows, unparseable


def parse_verdict(text: str) -> dict[str, str] | None:
    """Key/value pairs from a baseline's ```eval-verdict block; None when there is none.

    Values are returned as raw strings (the caller decides what must be an integer).
    Blank lines and `#` comments inside the block are ignored, and the FIRST block is the one
    returned. That choice is not load-bearing: `_verdict_findings` REJECTS a baseline carrying
    more than one block, so the gate never silently picks between contradictory claims.
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


def _cited_run_ids(fields: dict[str, str]) -> list[str]:
    """Run ids named by the block's `runs:` line, in order (empty when the line is absent)."""
    return [rid for rid in re.split(r"[,\s]+", fields.get("runs", "")) if rid]


def _runs_findings(
    baseline_name: str, run_ids: list[str], counts: dict[str, int], root: Path
) -> list[str]:
    """Corroborate the declared counts against `evals/results.jsonl` for the cited runs.

    The verdict block is written by hand, so on its own it is a claim about a claim. The
    results log is written by the harness, one row per scored case-run. This ties the two
    together: the cited run ids must be recorded, the number of DISTINCT cases recorded under
    them must equal `cases_total`, and the number of those cases with at least one passing row
    must equal `cases_passed_raw`. A case is credited as a raw pass if ANY recorded row for it
    passes (a rerun or a `--rescore` counts), which is the generous reading - so a mismatch
    means the block overstates the evidence or has drifted from the runs it cites, either way
    a finding rather than a promotion.
    """
    rows, unparseable = _results_rows(root)
    if rows is None:
        return [
            f"RELEASE-GATE: {baseline_name} cites eval runs ({', '.join(run_ids)}) but "
            f"{_RESULTS_LOG} is missing or unreadable - the declared counts "
            "cannot be corroborated (backfill it: python -m scripts.eval_engage --record evals/runs)"
        ]

    findings: list[str] = []
    if unparseable:
        findings.append(
            f"RELEASE-GATE: {_RESULTS_LOG} has {unparseable} unparseable "
            "line(s) - repair the results log before relying on it to corroborate a verdict"
        )

    recorded = [row for row in rows if row.get("run_id") in set(run_ids)]
    missing = sorted({rid for rid in run_ids} - {str(row.get("run_id")) for row in recorded})
    if missing:
        findings.append(
            f"RELEASE-GATE: {baseline_name} cites run id(s) {', '.join(missing)} with no rows in "
            f"{_RESULTS_LOG} - an eval run the tracked log never saw is not "
            "evidence"
        )
        return findings  # counts cannot be compared against a partial evidence set

    # Raw pass/fail comes from mode=="run" scoring rows ONLY (a rescore row is the
    # adjudication lane's evidence, never a raw pass), and where several cited runs scored
    # the same case, the LATEST cited run's row is that case's raw state. The previous
    # any-row-wins union let an early PASS hide a later FAIL, and let a rescore silently
    # inflate the raw count (2026-08-19 external audit finding 5B; the 0.35.0 baseline's
    # own rescore row demonstrated the inflation live).
    scored = [row for row in recorded if str(row.get("mode") or "run") == "run"]
    latest: dict[str, dict] = {}
    for row in scored:  # file order breaks run_id ties: the log is append-only/chronological
        case = str(row.get("case"))
        prior = latest.get(case)
        if prior is None or str(row.get("run_id")) >= str(prior.get("run_id")):
            latest[case] = row
    cases_recorded = set(latest)
    cases_passed = {case for case, row in latest.items() if row.get("passed") is True}
    if counts["cases_total"] != len(cases_recorded):
        findings.append(
            f"RELEASE-GATE: {baseline_name} declares cases_total: {counts['cases_total']} but the "
            f"cited run(s) record {len(cases_recorded)} distinct case(s) in "
            f"{_RESULTS_LOG} - the block must account for the runs it cites"
        )
    if counts["cases_passed_raw"] != len(cases_passed):
        findings.append(
            f"RELEASE-GATE: {baseline_name} declares cases_passed_raw: "
            f"{counts['cases_passed_raw']} but the cited run(s) record {len(cases_passed)} case(s) "
            f"passing raw in {_RESULTS_LOG}"
        )
    return findings


def _verdict_findings(baseline_name: str, text: str) -> list[str]:
    """Findings INTERNAL to the baseline's verdict block: exactly one block, a recognised
    verdict, whole-number counts that account for every case, no unadjudicated failures, and a
    clean `pass` only where every case passed raw. Empty list = the block is self-consistent.

    Self-consistency is not evidence: `_corroboration_findings` checks the same block against
    the golden-slice floor and the tracked results log."""
    # Multiple blocks are REJECTED rather than resolved by position. Each run's report.md tells
    # the human to paste its drafted block, so a baseline with the raw draft above (or below)
    # the adjudicated one is a realistic accident - and any positional rule (first wins, last
    # wins) silently picks one of two contradictory claims, which is precisely the failure a
    # promotion gate exists to prevent. Deleting the stale block is a two-second human edit.
    if len(_VERDICT_BLOCK_RE.findall(text)) > 1:
        return [
            f"RELEASE-GATE: {baseline_name} carries more than one ```eval-verdict block - the "
            "gate will not choose between contradictory claims; delete the superseded draft so "
            "exactly one block states the verdict being promoted on"
        ]

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


def _corroboration_findings(
    baseline_name: str,
    text: str,
    root: Path,
    deterministic_only: bool = False,
    min_cases: int = _MIN_SLICE_CASES,
) -> list[str]:
    """Findings from checking the block's claim against reality: is the slice wide enough, and
    do the cited runs and their recorded rows support the declared counts?

    Silently returns [] when the block is absent or its counts do not parse - `_verdict_findings`
    has already reported that, and there is nothing to corroborate.
    """
    fields = parse_verdict(text)
    if fields is None or len(_VERDICT_BLOCK_RE.findall(text)) > 1:
        return []
    counts: dict[str, int] = {}
    for key in _VERDICT_COUNTS:
        raw = fields.get(key, "")
        if re.fullmatch(r"\d+", raw):
            counts[key] = int(raw)
    if len(counts) < len(_VERDICT_COUNTS):
        return []

    findings: list[str] = []
    total = counts["cases_total"]
    if 0 < total < min_cases:
        findings.append(
            f"RELEASE-GATE: {baseline_name} stands on {total} case(s); a promotion needs at least "
            f"{min_cases} (CONTRIBUTING's golden slice is ~10-15 of the golden cases). Widen the "
            "slice, or pass --min-cases N to promote deliberately on a narrow one"
        )

    run_ids = _cited_run_ids(fields)
    if run_ids:
        findings += _runs_findings(baseline_name, run_ids, counts, root)
    elif not deterministic_only:
        findings.append(
            f"RELEASE-GATE: {baseline_name} eval-verdict names no 'runs:' - without run ids the "
            f"declared counts cannot be checked against {_RESULTS_LOG} and "
            "the verdict is self-reported; paste the block drafted in each run's report.md (it "
            "carries the run id)"
        )
    return findings


def gate(
    root: Path = _ROOT, allow_deterministic: bool = False, min_cases: int = _MIN_SLICE_CASES
) -> list[str]:
    """Every promotion finding for the repo at `root`; empty list means dev -> main may proceed.

    `allow_deterministic` accepts a `Scope: deterministic-only` baseline (patch releases) and
    waives the `runs:` requirement with it; `min_cases` is the golden-slice floor (_MIN_SLICE_CASES
    unless the human deliberately narrows it via --min-cases).
    """
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
    # 2b. ...on a slice wide enough to mean something, corroborated by the tracked results log.
    findings += _corroboration_findings(
        baseline.name, text, root, deterministic_only=deterministic_only, min_cases=min_cases
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

    # 3b. Freshness the commit log cannot see: a prompt edited in the working tree was never
    # exercised by the eval that produced the baseline, committed or not.
    dirty = _git_dirty_paths(_PROMPT_PATHS, root)
    if dirty is None:
        findings.append(
            "RELEASE-GATE: cannot read `git status` for the prompt paths - cannot verify the "
            "working tree is free of uncommitted prompt edits"
        )
    elif dirty:
        shown = ", ".join(dirty[:5]) + (f" (+{len(dirty) - 5} more)" if len(dirty) > 5 else "")
        findings.append(
            f"RELEASE-GATE: UNCOMMITTED prompt changes in the working tree ({shown}) - the eval "
            "behind the baseline never exercised them; commit them and re-run the golden slice"
        )

    return findings


def parse_min_cases(args: list[str]) -> tuple[int | None, str | None]:
    """Explicit `--min-cases N` / `--min-cases=N` override: (value, error message).

    (None, None) means the flag was not given and the default floor applies. A bad value is
    an error rather than a silent fallback: a mistyped override must not quietly relax the gate.
    """
    for index, arg in enumerate(args):
        if arg == "--min-cases":
            raw = args[index + 1] if index + 1 < len(args) else ""
        elif arg.startswith("--min-cases="):
            raw = arg.partition("=")[2]
        else:
            continue
        if not re.fullmatch(r"\d+", raw):
            return None, f"RELEASE-GATE: --min-cases needs a whole number, got '{raw}'"
        return int(raw), None
    return None, None


def main(argv: list[str]) -> int:
    _force_utf8_output()
    args = argv[1:]
    allow_det = "--allow-deterministic" in args
    min_cases, error = parse_min_cases(args)
    if error:
        print(error)
        return 1
    if min_cases is not None and min_cases < _MIN_SLICE_CASES:
        # Loud, because a narrowed slice is exactly the thing a reader of the console must see.
        print(
            f"release gate: NOTE - golden-slice floor lowered to {min_cases} case(s) by "
            f"--min-cases (default {_MIN_SLICE_CASES})"
        )
    findings = gate(
        allow_deterministic=allow_det,
        min_cases=_MIN_SLICE_CASES if min_cases is None else min_cases,
    )
    if findings:
        for line in findings:
            print(line)
        print(f"release gate: {len(findings)} finding(s) - do NOT promote dev -> main")
        return 1
    print("release gate: OK - promotion conditions met")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
