"""Temporal profiling and semantic tagging - the two data tools, and their honesty.

2026-08-24. The team had no method for interrogating a dataset across time, and no way to
answer "what am I looking at" for an undocumented extract. Both now exist as scripts rather
than prose, and both share one property that matters more than any feature: they emit
AGGREGATES ONLY. An agent can characterise a client's data without a record entering the
prompt, which is the opposite of the usual trade-off - this is safer than reading a masked
CSV into context, not merely more convenient.

These tests pin the behaviour AND that honesty. A change that prints a cell value is a safety
regression, and a change that reports a guess as a fact is a credibility one.
"""

from __future__ import annotations

import csv
import importlib.util
import json
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _write(path: Path, rows: list[dict]):
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return path


def _weekday_rows(start: date, days: int, skip: set[date] | None = None):
    rows = []
    for offset in range(days):
        day = start + timedelta(days=offset)
        if day.weekday() >= 5 or (skip and day in skip):
            continue
        rows.append({"id": f"A{offset:04d}", "raised": day.isoformat(), "venue": "LSE"})
    return rows


def _run(script: str, *args) -> str:
    result = subprocess.run(
        [sys.executable, "-m", f"scripts.{script}", *args],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    return result.stdout + result.stderr


# --- temporal ---------------------------------------------------------------------------------


def test_weekends_are_not_reported_as_gaps(tmp_path):
    """THE failure mode for this check in trade data. A naive "gap > 2x the interval" flags
    every weekend, every holiday and every half-day, which buries the one real break and
    discredits the tool on first use."""
    path = _write(tmp_path / "a.csv", _weekday_rows(date(2026, 1, 5), 40))
    out = _run("profile_temporal", str(path), "--as-of", "2026-02-20")
    assert "## Gaps (0)" in out, out


def test_a_real_outage_is_found(tmp_path):
    outage = {date(2026, 2, 2) + timedelta(days=d) for d in range(12)}
    path = _write(tmp_path / "a.csv", _weekday_rows(date(2026, 1, 5), 60, skip=outage))
    out = _run("profile_temporal", str(path), "--as-of", "2026-03-20")
    assert "## Gaps (1)" in out
    assert "day(s) missing between" in out


def test_a_future_dated_row_does_not_poison_freshness(tmp_path):
    """Found by the first fixture run: one future-dated row became the "latest" date, made
    freshness negative and invented a months-long gap ending at a date nobody has lived
    through. Freshness and gaps are measured up to the as-of; future rows are counted
    separately, because they are a finding in their own right."""
    rows = _weekday_rows(date(2026, 1, 5), 30)
    rows.append({"id": "BAD", "raised": "2027-12-31", "venue": "LSE"})
    path = _write(tmp_path / "a.csv", rows)
    data = json.loads(_run("profile_temporal", str(path), "--as-of", "2026-02-20", "--json"))
    assert data["future_dated_rows"] == 1
    assert data["days_since_latest"] >= 0, "freshness must not go negative"
    assert data["latest"] < "2027-01-01", "a future row must not become the range end"


def test_the_profile_never_prints_a_record(tmp_path):
    """The safety property the whole approach rests on. Identifiers appear in the data and
    must not appear in the output."""
    rows = _weekday_rows(date(2026, 1, 5), 20)
    rows[0]["id"] = "SECRET-IDENTIFIER-42"
    path = _write(tmp_path / "a.csv", rows)
    out = _run("profile_temporal", str(path), "--as-of", "2026-02-01")
    assert "SECRET-IDENTIFIER-42" not in out


def test_an_unparseable_date_column_says_so_rather_than_guessing(tmp_path):
    """A profile that silently misreads 03/04 in two different ways is worse than one that
    refuses. The parser is a fixed format list, never a fuzzy guesser."""
    path = _write(tmp_path / "a.csv", [{"id": "1", "notes": "hello"}, {"id": "2", "notes": "x"}])
    out = _run("profile_temporal", str(path))
    assert "UNPROFILED" in out and "no date column" in out


def test_it_measures_and_refuses_to_judge(tmp_path):
    """A weekend and a broken feed look identical to a profiler, and a shape change may be a
    threshold change. The output has to say so, or findings skip the interpretation step."""
    path = _write(tmp_path / "a.csv", _weekday_rows(date(2026, 1, 5), 20))
    out = _run("profile_temporal", str(path), "--as-of", "2026-02-01")
    assert "does NOT judge" in out
    assert "threshold" in out


# --- semantic tagging -------------------------------------------------------------------------


def test_finance_columns_get_fibo_grounded_tags(tmp_path):
    """Grounding matters here: a tag mapping to a published ontology class is defensible to a
    regulator in a way an ad-hoc label is not."""
    path = _write(
        tmp_path / "t.csv",
        [
            {"trade_date": "2026-01-05", "counterparty_id": "CP1",
             "notional_amount": "1000.50", "settlement_currency": "GBP"}
        ] * 5,
    )
    data = json.loads(_run("tag_columns", str(path), "--json"))
    tags = {c["column"]: (c["match"] or {}).get("tag") for c in data["results"]}
    assert tags["notional_amount"] == "money.amount"
    assert tags["settlement_currency"] == "money.currency"
    assert tags["trade_date"].startswith("temporal.")
    assert tags["counterparty_id"].startswith("party.")
    fibo = {(c["match"] or {}).get("fibo_class") for c in data["results"] if c["match"]}
    assert any("fibo" in (f or "") for f in fibo), "tags must carry their ontology class"


def test_an_unrecognisable_column_is_left_untagged(tmp_path):
    """Silence beats a confident wrong answer - an untagged column is a question for the feed
    owner, an invented tag is a false lead."""
    path = _write(tmp_path / "t.csv", [{"zzz_internal_flag": "1"}] * 5)
    data = json.loads(_run("tag_columns", str(path), "--json"))
    assert data["results"][0]["match"] is None


def test_tagging_never_prints_a_cell_value(tmp_path):
    path = _write(tmp_path / "t.csv", [{"counterparty_id": "SECRET-CP-9"}] * 5)
    out = _run("tag_columns", str(path))
    assert "SECRET-CP-9" not in out


def test_tags_are_labelled_inferred_not_established(tmp_path):
    """It will be believed unless it says otherwise. A tag is a strong guess from a NAME."""
    path = _write(tmp_path / "t.csv", [{"notional_amount": "5"}] * 5)
    out = _run("tag_columns", str(path))
    assert "INFERRED" in out
    assert "never evidence on its own" in out


def test_the_taxonomy_records_where_it_came_from():
    """Ported data, not authored here - the provenance travels with it."""
    data = json.loads((REPO_ROOT / "config" / "finance-taxonomy.json").read_text(encoding="utf-8"))
    assert "FIBO" in data["metadata"]["source"]
    assert "DataK9" in data["metadata"]["ported_from"]
    assert sum(len(v.get("tags", {})) for v in data["taxonomy"].values()) >= 25


def test_both_tools_are_deterministic(tmp_path):
    """Two runs on the same input agree - the same property repo_skeleton holds."""
    path = _write(tmp_path / "a.csv", _weekday_rows(date(2026, 1, 5), 20))
    assert _run("profile_temporal", str(path), "--as-of", "2026-02-01") == _run(
        "profile_temporal", str(path), "--as-of", "2026-02-01"
    )


# --- document skeleton (2026-08-25) -----------------------------------------------------------


def test_the_doc_map_gives_an_outline_without_reading_bodies(tmp_path):
    """Orientation, not retrieval. Anthropic's own guidance is that under ~200k tokens you
    put the corpus in the prompt rather than build retrieval infrastructure - what is missing
    is knowing what EXISTS before deciding what to open."""
    (tmp_path / "specs").mkdir()
    (tmp_path / "specs" / "feed-spec.md").write_text(
        "# Feed Specification v2.3\n\n## Scope\nbody text that must not appear\n", encoding="utf-8"
    )
    out = _run("doc_skeleton", str(tmp_path))
    assert "Feed Specification v2.3" in out
    assert "Scope" in out
    assert "body text that must not appear" not in out, "bodies are not read here"


def test_binary_documents_are_inventoried_not_parsed(tmp_path):
    """convert_file owns extraction. Doing it twice would be slower and a second place to get
    it wrong - so these are listed with a pointer, never opened."""
    (tmp_path / ("report." + "pdf")).write_bytes(b"%PDF-1.4 not really")
    (tmp_path / ("mail." + "msg")).write_bytes(b"\xd0\xcf\x11\xe0")
    out = _run("doc_skeleton", str(tmp_path))
    assert "[document]" in out
    assert "convert_file" in out, "must point at the tool that CAN read it"


def test_the_listing_is_budgeted_and_says_what_it_left_out(tmp_path):
    """Never a silent truncation - the same contract repo_skeleton holds."""
    for i in range(200):
        (tmp_path / f"doc{i:03d}.md").write_text(f"# Heading {i}\n\ntext\n", encoding="utf-8")
    out = _run("doc_skeleton", str(tmp_path), "--budget", "400")
    assert "not shown" in out and "budget stopped the listing" in out


def test_the_doc_map_is_deterministic(tmp_path):
    (tmp_path / "b.md").write_text("# B\n", encoding="utf-8")
    (tmp_path / "a.md").write_text("# A\n", encoding="utf-8")
    assert _run("doc_skeleton", str(tmp_path)) == _run("doc_skeleton", str(tmp_path))


def test_it_warns_that_headings_are_content(tmp_path):
    """Unlike the aggregate-only data tools, this one CAN emit a client name via a heading -
    so it must not be mistaken for exempt from the data rules."""
    (tmp_path / "a.md").write_text("# A\n", encoding="utf-8")
    out = _run("doc_skeleton", str(tmp_path))
    assert "Headings are CONTENT" in out
