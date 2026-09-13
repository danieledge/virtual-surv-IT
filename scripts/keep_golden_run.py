#!/usr/bin/env python3
"""Keep one saved eval run as a golden run for CI's token-free replay (step 5.1, 2026-09-13).

    python scripts/keep_golden_run.py evals/runs/<run_id>/<case>

Copies the scoring inputs (transcript, events, saved findings, score, run-meta, tripwires,
fixture baseline, gates) to evals/golden-runs/<case>/ and, from the run's sandbox, only the
project's VSIT/ workspace and the consent marker - never the full repository copy and never
data/. Refuses a run that does not pass under the current scorer (`--rescore --replay`), so
a golden run is by construction one CI can hold the scorer to. Human/dev-run; not part of
the team's runtime tooling.
"""

from __future__ import annotations

import shutil
import subprocess  # nosec B404 - fixed argv, shell=False, this repo's own scorer
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
GOLDEN = REPO / "evals" / "golden-runs"
_FILES = (
    "transcript.md",
    "events.jsonl",
    "findings.json",
    "score.json",
    "run-meta.json",
    "tripwires.json",
    "fixture-baseline.json",
    "gates.json",
)


def _sandbox_subset(sandbox: Path, target: Path) -> int:
    """Copy VSIT/ workspaces (any depth up to the client project) and .claude/.exec-consent."""
    copied = 0
    if not sandbox.is_dir():
        return 0
    for vsit in sandbox.rglob("VSIT"):
        if vsit.is_dir() and "node_modules" not in vsit.parts:
            dest = target / vsit.relative_to(sandbox)
            shutil.copytree(vsit, dest, dirs_exist_ok=True)
            copied += 1
    for marker in sandbox.rglob(".exec-consent"):
        dest = target / marker.relative_to(sandbox)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(marker, dest)
    return copied


def keep(run_case_dir: Path) -> Path:
    src = run_case_dir.resolve()
    if not (src / "transcript.md").is_file():
        raise SystemExit(f"{src} has no transcript.md - not a saved run's case dir")
    dest = GOLDEN / src.name
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    for name in _FILES:
        if (src / name).is_file():
            shutil.copy2(src / name, dest / name)
    _sandbox_subset(src / "sandbox", dest / "sandbox")
    proc = subprocess.run(  # nosec B603
        [
            sys.executable,
            "-m",
            "scripts.eval_engage",
            "--rescore",
            str(dest),
            "--replay",
            "--skip-judge",
        ],
        cwd=str(REPO),
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        shutil.rmtree(dest)
        tail = (proc.stdout + proc.stderr).strip().splitlines()[-4:]
        raise SystemExit(
            f"refused: {src.name} does not pass under the current scorer, so it cannot be a "
            "golden run:\n  " + "\n  ".join(tail)
        )
    for stray in ("score-rescore.json",):
        (dest / stray).unlink(missing_ok=True)
    return dest


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 1:
        print(__doc__)
        return 2
    kept = keep(Path(args[0]))
    print(f"kept {kept.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
