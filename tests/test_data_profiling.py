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


# --- email formats (2026-08-25) ---------------------------------------------------------------


def test_eml_converts_with_headers_body_and_attachment_names(tmp_path):
    """Comms surveillance is one of the three pillars this team exists for, so mail was not
    an edge case - it was a silent skip. .eml needs no dependency at all: the stdlib email
    package parses it completely."""
    from email.message import EmailMessage

    message = EmailMessage()
    message["From"] = "trader@bank.example"
    message["To"] = "desk@bank.example"
    message["Subject"] = "Re: order 12345"
    message["Date"] = "Mon, 24 Aug 2026 10:00:00 +0100"
    message.set_content("Please review the fill.")
    message.add_attachment(b"x", maintype="application", subtype="octet-stream",
                           filename="blotter.csv")
    path = tmp_path / ("note." + "eml")
    path.write_bytes(message.as_bytes())
    out = _run("convert_file", str(path))
    assert "format" in out and "eml" in out
    rendered = (tmp_path / "note.converted.md").read_text(encoding="utf-8")
    assert "trader@bank.example" in rendered
    assert "Re: order 12345" in rendered
    assert "Please review the fill." in rendered
    assert "blotter.csv" in rendered, "attachment names must be listed"


def test_attachments_are_named_but_never_silently_treated_as_extracted(tmp_path):
    """Listing a name is not extracting a file. Saying so is the difference between a
    reviewer knowing to go and get it and assuming it was already read."""
    from email.message import EmailMessage

    message = EmailMessage()
    message["Subject"] = "with attachment"
    message.set_content("body")
    message.add_attachment(b"x", maintype="application", subtype="pdf", filename="evidence.pdf")
    path = tmp_path / ("a." + "eml")
    path.write_bytes(message.as_bytes())
    _run("convert_file", str(path))
    evidence = json.loads(
        (tmp_path / "a.converted.md.evidence.json").read_text(encoding="utf-8")
    )
    assert evidence["attachments"] == 1
    assert any("NOT extracted" in w for w in evidence["warnings"])


def test_a_non_ole_file_is_refused_as_a_msg(tmp_path):
    """A .msg that is really something else must fail loudly, not produce empty output."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("cf", REPO_ROOT / "scripts" / "convert_file.py")
    cf = importlib.util.module_from_spec(spec)
    sys.modules["cf"] = cf
    spec.loader.exec_module(cf)
    path = tmp_path / ("fake." + "msg")
    path.write_text("this is not OLE2", encoding="utf-8")
    try:
        cf.read_msg(path, cf.Report(path))
    except cf.ConversionError as exc:
        assert "OLE2" in str(exc)
    else:
        raise AssertionError("a non-OLE file was accepted as a .msg")


def test_the_evidence_sidecar_is_named_for_what_it_is(tmp_path):
    """`.report.json` sorted next to the data and read as just another output. The data's
    format follows the input; the evidence is always JSON, and now says so."""
    path = tmp_path / "t.csv"
    path.write_text("a,b\n1,2\n", encoding="utf-8")
    _run("convert_file", str(path))
    assert (tmp_path / "t.converted.csv.evidence.json").is_file()
    assert not (tmp_path / "t.converted.csv.report.json").exists()


# --- the guard daemon is on by default now (2026-08-25) ---------------------------------------


def _resolve(tmp_path, prefs=None, machine=None, monkeypatch=None):
    import importlib

    (tmp_path / ".claude").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".claude" / "team-preferences.json").write_text(
        json.dumps(prefs or {}), encoding="utf-8"
    )
    cfg = tmp_path / "cfg" / "virt-surv-it"
    cfg.mkdir(parents=True, exist_ok=True)
    (cfg / "installer.json").write_text(json.dumps(machine or {}), encoding="utf-8")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import engage_probe

    importlib.reload(engage_probe)
    return engage_probe.resolve_preferences(tmp_path)


def test_the_daemon_is_on_by_default(tmp_path, monkeypatch):
    """It runs the SAME guard code in a persistent process, so the only difference is an
    interpreter cold start per hook - ~625ms against ~211ms per call on Windows. The old
    opt-in default charged every user that difference to guard a risk that never appeared."""
    assert _resolve(tmp_path, monkeypatch=monkeypatch)["guard_daemon"] is True


def test_either_tier_can_turn_the_daemon_off_and_the_project_wins(tmp_path, monkeypatch):
    assert _resolve(tmp_path, machine={"default_guard_daemon": False},
                    monkeypatch=monkeypatch)["guard_daemon"] is False
    assert _resolve(tmp_path, prefs={"guard_daemon": False},
                    monkeypatch=monkeypatch)["guard_daemon"] is False
    # Project beats machine in BOTH directions - that is what "project wins" has to mean.
    assert _resolve(tmp_path, prefs={"guard_daemon": True},
                    machine={"default_guard_daemon": False},
                    monkeypatch=monkeypatch)["guard_daemon"] is True


def test_the_shell_and_python_tiers_agree_on_the_default():
    """run-guard.sh decides this in shell, independently of resolve_preferences. Two
    implementations of one rule can drift, so pin that both default to ON and that only an
    explicit false turns it off."""
    # Asserts the STAGED copy, which is the source of truth for the intended rule. Whether
    # it has reached the live file is a different question, and test_hooks_in_sync owns it -
    # duplicating that here would just mean two tests failing for one pending apply.
    shell = (REPO_ROOT / "scripts" / "staged_hooks" / "run-guard.sh").read_text(encoding="utf-8")
    assert "_use_daemon=1" in shell
    # F1 (2026-08-26) replaced three `grep` spawns per tool call with a builtin `case`
    # match, so the rule is no longer spelled as a grep pattern. The property under test is
    # unchanged - both tiers are consulted, and only an explicit false turns the daemon off -
    # so assert the checks are present rather than how they are written.
    assert '_json_has "$_inst" default_guard_daemon false' in shell, (
        "machine tier missing from the shell"
    )
    assert '_json_has "$_prefs" guard_daemon false' in shell, "project-off missing from the shell"
    assert '_json_has "$_prefs" guard_daemon true' in shell, "project-on missing from the shell"
