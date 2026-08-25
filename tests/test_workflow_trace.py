"""The workflow trace: stages, models, cost, loops, export (2026-08-25).

Built against REAL captured transcript lines, not invented ones. The transcript is Claude
Code's internal file and not a public API, so a format change must fail here rather than on
someone's screen - which only works if the fixtures are shaped like the real thing.
"""

from __future__ import annotations

import csv
import importlib.util
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load(name: str):
    if str(REPO_ROOT / "scripts") not in sys.path:
        sys.path.insert(0, str(REPO_ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _assistant(model: str, out_tokens: int, cache_read: int = 0, stamp: str = "2026-08-25T10:00:00Z"):
    return {
        "type": "assistant", "timestamp": stamp,
        "message": {"model": model, "usage": {
            "input_tokens": 10, "output_tokens": out_tokens,
            "cache_creation_input_tokens": 100, "cache_read_input_tokens": cache_read}},
    }


def _agent(agent: str, model: str, out_tokens: int = 300, ms: int = 15268, status="completed"):
    """Shaped from a REAL toolUseResult captured 2026-08-25."""
    return {
        "type": "user", "timestamp": "2026-08-25T10:01:00Z",
        "toolUseResult": {
            "agentId": "x", "agentType": agent, "resolvedModel": model, "status": status,
            "totalDurationMs": ms, "totalTokens": 19372, "totalToolUseCount": 1,
            "toolStats": {"readCount": 0, "bashCount": 1, "editFileCount": 0},
            "usage": {"input_tokens": 8, "cache_creation_input_tokens": 913,
                      "cache_read_input_tokens": 18092, "output_tokens": out_tokens},
        },
    }


def _write(tmp_path: Path, records: list) -> Path:
    path = tmp_path / "session.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
    return path


# --- tokens and cost -------------------------------------------------------------------


def test_cache_reads_are_not_counted_as_new_tokens():
    """The bug found on first contact with a real 31MB transcript: summing cache reads across
    3,546 turns produced 1.8 BILLION tokens for one session - arithmetically defensible and
    completely misleading. Cache reads are billed, so they stay in the cost, but they are the
    same context re-read and never 'work done'."""
    wt = _load("workflow_trace")
    usage = {"input_tokens": 100, "output_tokens": 50,
             "cache_creation_input_tokens": 25, "cache_read_input_tokens": 900_000}
    assert wt.total_tokens(usage) == 175
    assert wt.cache_reads(usage) == 900_000


def test_an_unpriced_model_reports_unknown_rather_than_a_guess():
    """New model IDs will appear. A figure derived from a neighbouring model's rate would
    look authoritative and be wrong, which is worse than a visible gap."""
    wt = _load("workflow_trace")
    usage = {"input_tokens": 1_000_000, "output_tokens": 0,
             "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}
    assert wt.cost_of(usage, "claude-opus-5") == 5.0
    assert wt.cost_of(usage, "claude-model-from-the-future") is None


def test_there_is_exactly_one_rate_table_in_the_repo():
    """2026-08-25: the workflow view shipped with its own hand-written table that DISAGREED
    with dashboard.py's - opus at 15/75 against 5/25, fable at 3/15 against 10/50. Two tables
    that disagree are worse than one that is stale, because budget-status measures an
    unattended run's ceiling against dashboard's, so the workflow view and the spend gate
    would have reported different costs for the same run."""
    wt = _load("workflow_trace")
    dash = _load("dashboard")
    usage = {"input_tokens": 1_000_000, "output_tokens": 1_000_000,
             "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}
    for model in ("claude-opus-5", "claude-sonnet-5", "claude-fable-5"):
        assert wt.cost_of(usage, model) == round(dash.price_usage(model, usage), 4), (
            f"{model} priced differently by the two paths"
        )
    assert not (REPO_ROOT / "config" / "model-pricing.json").exists(), (
        "a second rate table has reappeared"
    )


def test_the_rate_provenance_is_reported():
    """A cost with no rate date cannot be judged stale."""
    wt = _load("workflow_trace")
    dash = _load("dashboard")
    assert wt.load_rates()["rates_as_of"] == dash.PRICING_AS_OF


def test_a_total_with_an_unpriced_stage_says_so(tmp_path):
    """A partial total presented as a total is the same lie as a guessed rate."""
    wt = _load("workflow_trace")
    path = _write(tmp_path, [_agent("qa-engineer", "claude-model-x"),
                             _agent("code-reviewer", "claude-opus-5")])
    trace = wt.parse(path)
    assert trace["totals"]["unpriced_stages"] == 1


def test_a_trace_reports_the_rate_date_it_used():
    wt = _load("workflow_trace")
    assert wt.load_rates().get("rates_as_of"), "an undated cost cannot be judged stale"


# --- stages and loops ------------------------------------------------------------------


def test_stages_come_back_in_order_with_their_model(tmp_path):
    wt = _load("workflow_trace")
    path = _write(tmp_path, [
        _agent("business-analyst", "claude-sonnet-5"),
        _agent("code-reviewer", "claude-opus-5"),
    ])
    trace = wt.parse(path)
    agents = [s["agent"] for s in trace["stages"] if s["kind"] == "agent"]
    models = [s["model"] for s in trace["stages"] if s["kind"] == "agent"]
    assert agents == ["business-analyst", "code-reviewer"]
    assert models == ["claude-sonnet-5", "claude-opus-5"]
    assert trace["stages"][0]["duration_ms"] == 15268


def test_a_repeat_run_is_numbered(tmp_path):
    wt = _load("workflow_trace")
    path = _write(tmp_path, [_agent("code-reviewer", "claude-opus-5"),
                             _agent("code-reviewer", "claude-opus-5")])
    loops = [s["loop_index"] for s in wt.parse(path)["stages"] if s["kind"] == "agent"]
    assert loops == [1, 2]


def test_a_fix_cycle_is_recognised(tmp_path):
    """review -> fix -> re-review is what a delivery team does, and its cost is the number
    nobody can see today."""
    wt = _load("workflow_trace")
    path = _write(tmp_path, [
        _agent("code-reviewer", "claude-opus-5"),
        _agent("rules-developer", "claude-sonnet-5"),
        _agent("code-reviewer", "claude-opus-5"),
    ])
    stages = [s for s in wt.parse(path)["stages"] if s["kind"] == "agent"]
    assert stages[2]["cycle_with"] == ["rules-developer"]
    assert stages[0].get("cycle_start") is True
    assert "cycle_with" not in stages[1]


def test_back_to_back_repeats_are_not_a_cycle(tmp_path):
    """Two runs of the same agent with nothing between them is a repeat, not a fix cycle -
    calling it one would make the bracket meaningless."""
    wt = _load("workflow_trace")
    path = _write(tmp_path, [_agent("qa-engineer", "claude-sonnet-5")] * 2)
    stages = [s for s in wt.parse(path)["stages"] if s["kind"] == "agent"]
    assert stages[1]["loop_index"] == 2
    assert "cycle_with" not in stages[1]


def test_orchestrator_work_gets_its_own_rows(tmp_path):
    """Work the PM does between delegations is real cost belonging to no stage. Spreading it
    over the neighbours would quietly inflate them."""
    wt = _load("workflow_trace")
    path = _write(tmp_path, [
        _assistant("claude-opus-5", 30_000),
        _agent("qa-engineer", "claude-sonnet-5"),
    ])
    kinds = [s["kind"] for s in wt.parse(path)["stages"]]
    assert kinds == ["orchestration", "agent"]


def test_trivial_orchestrator_chatter_is_not_a_stage(tmp_path):
    wt = _load("workflow_trace")
    path = _write(tmp_path, [_assistant("claude-opus-5", 5), _agent("qa-engineer", "claude-sonnet-5")])
    assert [s["kind"] for s in wt.parse(path)["stages"]] == ["agent"]


# --- resilience ------------------------------------------------------------------------


def test_a_corrupt_line_is_skipped_and_counted(tmp_path):
    """The transcript is written by another process while this reads it."""
    wt = _load("workflow_trace")
    path = tmp_path / "s.jsonl"
    path.write_text(
        json.dumps(_agent("qa-engineer", "claude-sonnet-5")) + "\n{not json\n",
        encoding="utf-8",
    )
    trace = wt.parse(path)
    assert trace["ok"] and trace["unreadable_lines"] == 1
    assert len([s for s in trace["stages"] if s["kind"] == "agent"]) == 1


def test_a_missing_transcript_is_a_message_not_a_crash(tmp_path):
    wt = _load("workflow_trace")
    trace = wt.parse(tmp_path / "nope.jsonl")
    assert trace["ok"] is False and trace["error"]
    assert trace["stages"] == []


def test_a_result_missing_every_optional_field_still_yields_a_stage(tmp_path):
    """Defensive by design: the format can change under us."""
    wt = _load("workflow_trace")
    path = _write(tmp_path, [{"type": "user", "toolUseResult": {"agentType": "qa-engineer"}}])
    stage = wt.parse(path)["stages"][0]
    assert stage["agent"] == "qa-engineer"
    assert stage["cost"] is None and stage["tokens"] == 0


def test_no_transcript_directory_yields_no_trace(tmp_path):
    wt = _load("workflow_trace")
    trace = wt.trace_for(tmp_path)
    assert trace["ok"] is False and "no session transcript" in trace["error"]


# --- export ----------------------------------------------------------------------------


def test_the_export_never_carries_message_content(tmp_path):
    """A trace sits on a transcript full of prompts and file contents; an export is a file
    that leaves the machine. This restriction is what makes it safe to attach to a client
    report, which is the only reason to export one."""
    rw = _load("render_workflow")
    wt = _load("workflow_trace")
    secret = "CLIENT-CONFIDENTIAL-STRING"
    path = _write(tmp_path, [
        {"type": "assistant", "timestamp": "t",
         "message": {"model": "claude-opus-5", "content": [{"type": "text", "text": secret}],
                     "usage": {"input_tokens": 1, "output_tokens": 30_000,
                               "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}}},
        _agent("qa-engineer", "claude-sonnet-5"),
    ])
    trace = wt.parse(path)
    out = tmp_path / "out"
    written = rw.export(trace, out, ("md", "json", "csv"))
    assert written
    for produced in written:
        assert secret not in produced.read_text(encoding="utf-8"), f"{produced.name} leaked content"


def test_csv_carries_exactly_the_allowed_columns(tmp_path):
    """An allow-list, so a new transcript field cannot silently start being exported."""
    rw = _load("render_workflow")
    wt = _load("workflow_trace")
    path = _write(tmp_path, [_agent("qa-engineer", "claude-sonnet-5")])
    out = tmp_path / "out"
    rw.export(wt.parse(path), out, ("csv",))
    with (out / "workflow-trace.csv").open(encoding="utf-8") as handle:
        assert next(csv.reader(handle)) == list(rw._COLUMNS)


def test_markdown_marks_measured_and_inferred_apart(tmp_path):
    rw = _load("render_workflow")
    wt = _load("workflow_trace")
    path = _write(tmp_path, [_agent("qa-engineer", "claude-sonnet-5")])
    text = rw.to_markdown(wt.parse(path))
    assert "📊" in text and "🧠" in text
    assert "never a bill" in text


def test_export_of_a_failed_trace_writes_nothing(tmp_path):
    """An empty workflow-trace.md looks like a record of an engagement and is a record of a
    failed read - and unlike a missing file, it gets attached to things and believed."""
    rw = _load("render_workflow")
    out = tmp_path / "out"
    assert rw.export({"ok": False, "stages": []}, out, ("md", "json", "csv")) == []
    assert not out.exists(), "a failed export must not even leave the directory behind"


def test_the_export_defers_to_cost_for_the_session_total(tmp_path):
    """2026-08-25, owner: "why do we need a rate table, we show the cost of the engagement in
    the status bar and /cost". Correct about the TOTAL, and the product has to say so rather
    than quietly competing with an authoritative number. Verified the same day that Claude
    Code records no cost anywhere - no cost/usd/price key in 4,000 transcript records, no
    usage store under ~/.claude - so per-stage apportionment cannot borrow it and needs
    rates of its own."""
    rw = _load("render_workflow")
    wt = _load("workflow_trace")
    path = _write(tmp_path, [_agent("qa-engineer", "claude-sonnet-5")])
    text = rw.to_markdown(wt.parse(path))
    assert "/cost" in text, "the authoritative session total must be named"
    assert "authority" in text
    assert "apportion" in text, "and this table's actual job must be stated"


def test_pricing_works_when_run_as_a_module_not_just_when_imported():
    """2026-08-25: run as `python -m scripts.workflow_trace`, the repo root is on sys.path
    and scripts/ is not, so `import dashboard` failed and EVERY stage priced as unknown -
    while a direct import in a test priced fine, because the test had put scripts/ on the
    path by hand. A test that only exercises the import-shaped path cannot see this."""
    import subprocess

    proc = subprocess.run(
        [sys.executable, "-c",
         "import sys; sys.path=[p for p in sys.path if p.rstrip('/').endswith('virt-survtecb')"
         " or 'scripts' not in p]; "
         "import importlib.util as u; "
         f"s=u.spec_from_file_location('wt', r'{REPO_ROOT}/scripts/workflow_trace.py'); "
         "m=u.module_from_spec(s); s.loader.exec_module(m); "
         "print(m.cost_of({'input_tokens':1000000,'output_tokens':0,"
         "'cache_creation_input_tokens':0,'cache_read_input_tokens':0}, 'claude-opus-5'))"],
        capture_output=True, text=True, cwd=str(REPO_ROOT), timeout=60,
    )
    assert proc.stdout.strip() == "5.0", f"pricing broke outside an import: {proc.stdout!r} {proc.stderr[-300:]!r}"


def test_a_live_model_id_with_suffixes_is_priced():
    """The IDs transcripts actually carry: a context marker and a release date. Neither
    changes the rate, and neither matched the table before this."""
    wt = _load("workflow_trace")
    usage = {"input_tokens": 1_000_000, "output_tokens": 0,
             "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}
    assert wt.cost_of(usage, "claude-opus-5[1m]") == 5.0
    assert wt.cost_of(usage, "claude-haiku-4-5-20251001") == 1.0


def test_an_unchanged_transcript_is_not_reparsed(tmp_path):
    """2026-08-25: the workflow view reported running out of memory. It re-parsed the whole
    transcript on every refresh, twice per frame, at a 2s cadence - on a file that can be
    tens of megabytes. The plan for this feature specified caching on (path, size, mtime);
    the first implementation streamed but did not cache."""
    wt = _load("workflow_trace")
    path = _write(tmp_path, [_agent("qa-engineer", "claude-sonnet-5")])
    first = wt.parse(path)
    assert wt.parse(path) is first, "an unchanged file must return the same object"


def test_a_changed_transcript_is_reparsed(tmp_path):
    """The cache must never hide a live session's progress - that is the whole point of a
    monitor."""
    wt = _load("workflow_trace")
    path = _write(tmp_path, [_agent("qa-engineer", "claude-sonnet-5")])
    before = wt.parse(path)
    assert len([s for s in before["stages"] if s["kind"] == "agent"]) == 1
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(_agent("code-reviewer", "claude-opus-5")) + "\n")
    after = wt.parse(path)
    assert after is not before
    assert len([s for s in after["stages"] if s["kind"] == "agent"]) == 2


def test_a_failed_parse_is_never_cached(tmp_path):
    """Otherwise a transcript that did not exist yet would stay 'missing' after it appears."""
    wt = _load("workflow_trace")
    path = tmp_path / "later.jsonl"
    assert wt.parse(path)["ok"] is False
    _write(tmp_path, [_agent("qa-engineer", "claude-sonnet-5")])
    (tmp_path / "session.jsonl").replace(path)
    assert wt.parse(path)["ok"] is True


def test_the_cache_holds_one_entry_not_a_growing_dict(tmp_path):
    """A cache that grows per file is a leak in a long-lived launcher process."""
    wt = _load("workflow_trace")
    for name in ("a", "b", "c"):
        p = tmp_path / f"{name}.jsonl"
        p.write_text(json.dumps(_agent("qa-engineer", "claude-sonnet-5")) + "\n", encoding="utf-8")
        wt.parse(p)
    assert set(wt._CACHE) == {"key", "trace"}, "one entry, keyed on the file being watched"
