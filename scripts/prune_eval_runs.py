#!/usr/bin/env python3
"""Apply the eval-run retention rule to evals/runs/ (step 5.3, 2026-09-13).

The rule (evals/README.md, 2026-07-30 audit): keep IN FULL (a) any run cited by a committed
evals/eval-baseline-*.md or evals/artifact-review-*.md, and (b) every run from the last 7
days. For anything else delete the `*/sandbox/` (and plugin-mode `*/home/`) subtrees and keep
the scoring outputs; whole run directories older than 30 days may be purged unless cited.
The rule existed as prose for six weeks while evals/runs/ grew to 435 MB; this makes it a
command. Dry run by default; `--apply` deletes. Human/dev-run; never part of a session.

    python scripts/prune_eval_runs.py            # show the plan
    python scripts/prune_eval_runs.py --apply
"""

from __future__ import annotations

import argparse
import datetime as _dt
import re
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
RUNS = REPO / "evals" / "runs"
EVALS = REPO / "evals"
_RUN_ID = re.compile(r"\b(\d{8}T\d{6}Z)\b")
KEEP_DAYS = 7
PURGE_DAYS = 30
_BULK = ("sandbox", "home")


def cited_run_ids(evals_dir: Path = EVALS) -> set[str]:
    ids: set[str] = set()
    for pattern in ("eval-baseline-*.md", "artifact-review-*.md"):
        for path in evals_dir.glob(pattern):
            ids |= set(_RUN_ID.findall(path.read_text(encoding="utf-8", errors="replace")))
    return ids


def _age_days(run_dir: Path, now: _dt.datetime) -> float:
    m = _RUN_ID.match(run_dir.name)
    if m:
        stamp = _dt.datetime.strptime(m.group(1), "%Y%m%dT%H%M%SZ").replace(tzinfo=_dt.timezone.utc)
    else:
        stamp = _dt.datetime.fromtimestamp(run_dir.stat().st_mtime, tz=_dt.timezone.utc)
    return (now - stamp).total_seconds() / 86400


def _size(path: Path) -> int:
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


def plan(
    runs_dir: Path = RUNS, evals_dir: Path = EVALS, now: _dt.datetime | None = None
) -> list[tuple[Path, str, str, int]]:
    """(path, action, reason, bytes) per decision; action is keep | trim | purge."""
    now = now or _dt.datetime.now(_dt.timezone.utc)
    cited = cited_run_ids(evals_dir)
    out: list[tuple[Path, str, str, int]] = []
    if not runs_dir.is_dir():
        return out
    for run_dir in sorted(p for p in runs_dir.iterdir() if p.is_dir()):
        age = _age_days(run_dir, now)
        if run_dir.name in cited:
            out.append((run_dir, "keep", "cited by a baseline or artifact review", 0))
        elif age < KEEP_DAYS:
            out.append((run_dir, "keep", f"{age:.1f} days old (under {KEEP_DAYS})", 0))
        elif age > PURGE_DAYS:
            out.append(
                (
                    run_dir,
                    "purge",
                    f"{age:.0f} days old (over {PURGE_DAYS}), uncited",
                    _size(run_dir),
                )
            )
        else:
            bulk = [
                d
                for case in run_dir.iterdir()
                if case.is_dir()
                for d in (case / b for b in _BULK)
                if d.is_dir()
            ]
            for d in bulk:
                out.append(
                    (d, "trim", f"{age:.0f} days old: scoring outputs kept, bulk removed", _size(d))
                )
            if not bulk:
                out.append((run_dir, "keep", f"{age:.0f} days old, already trimmed", 0))
    return out


def apply(decisions: list[tuple[Path, str, str, int]]) -> int:
    freed = 0
    for path, action, _reason, size in decisions:
        if action in ("trim", "purge"):
            shutil.rmtree(path, ignore_errors=True)
            freed += size
    return freed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--apply", action="store_true", help="delete; without it, only print the plan"
    )
    parser.add_argument("--runs", type=Path, default=RUNS)
    args = parser.parse_args(argv)
    decisions = plan(args.runs)
    for path, action, reason, size in decisions:
        mb = f" ({size / 1e6:.0f} MB)" if size else ""
        print(
            f"{action:5} {path.relative_to(args.runs.parent) if path.is_relative_to(args.runs.parent) else path}{mb}: {reason}"
        )
    reclaim = sum(s for _, a, _, s in decisions if a != "keep")
    if not args.apply:
        print(f"dry run: {reclaim / 1e6:.0f} MB would be reclaimed (re-run with --apply)")
        return 0
    freed = apply(decisions)
    print(f"reclaimed {freed / 1e6:.0f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
