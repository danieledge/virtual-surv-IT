"""scripts/prune_eval_runs.py - the retention rule from evals/README.md as a command
(2026-09-13 framework review, step 5.3)."""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from scripts import prune_eval_runs as prune  # noqa: E402

NOW = dt.datetime(2026, 9, 14, tzinfo=dt.timezone.utc)


def _run(runs: Path, stamp: str, with_bulk: bool = True) -> Path:
    case = runs / stamp / "some-case"
    case.mkdir(parents=True)
    (case / "transcript.md").write_text("t", encoding="utf-8")
    (case / "score.json").write_text("{}", encoding="utf-8")
    if with_bulk:
        (case / "sandbox" / "repo").mkdir(parents=True)
        (case / "sandbox" / "repo" / "big.bin").write_bytes(b"x" * 1000)
        (case / "home" / "cache").mkdir(parents=True)
        (case / "home" / "cache" / "plugin.bin").write_bytes(b"y" * 500)
    return runs / stamp


def test_plan_keeps_recent_and_cited_trims_middle_aged_and_purges_old(tmp_path):
    evals = tmp_path / "evals"
    runs = evals / "runs"
    recent = _run(runs, "20260912T120000Z")
    cited = _run(runs, "20260801T120000Z")
    middle = _run(runs, "20260825T120000Z")
    old = _run(runs, "20260701T120000Z")
    (evals / "eval-baseline-0.38.0.md").write_text("runs: 20260801T120000Z\n", encoding="utf-8")
    decisions = {p: a for p, a, _, _ in prune.plan(runs, evals, NOW)}
    assert decisions[recent] == "keep"
    assert decisions[cited] == "keep"
    assert decisions[old] == "purge"
    assert decisions[middle / "some-case" / "sandbox"] == "trim"
    assert decisions[middle / "some-case" / "home"] == "trim"
    assert middle not in decisions

    freed = prune.apply(prune.plan(runs, evals, NOW))
    assert freed >= 1500 + 1500  # bulk bytes; the purged run adds its small scoring files
    assert not old.exists()
    assert (middle / "some-case" / "transcript.md").is_file(), "scoring outputs survive a trim"
    assert not (middle / "some-case" / "sandbox").exists()
    assert (cited / "some-case" / "sandbox").is_dir()


def test_dry_run_deletes_nothing(tmp_path, capsys):
    runs = tmp_path / "evals" / "runs"
    old = _run(runs, "20260601T120000Z")
    assert prune.main(["--runs", str(runs)]) == 0
    assert old.exists()
    assert "dry run" in capsys.readouterr().out
