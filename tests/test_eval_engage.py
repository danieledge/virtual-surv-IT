"""Unit tests for the live-/engage eval driver's pure layers (scripts/eval_engage.py).

The driver was the largest untested file in the repo, and the 2026-08-01 eval-harness audit
found the damage that hides there: the judge scored deliverables it never read, and the
numbers never survived a run. These tests pin the parts that decide WHAT the judge sees and
WHAT gets recorded - reply parsing, the artifact listing (bodies + truncation), transcript
capture including subagent output, report assembly, and the verdict block the release gate
parses. The Agent SDK network path is deliberately out of scope.
"""

from __future__ import annotations

import json

import pytest

import scripts.eval_engage as ee
import scripts.release_gate as rg


# --- _extract_json ----------------------------------------------------------------------
def test_extract_json_plain_object():
    assert ee._extract_json('{"findings": [1, 2]}') == {"findings": [1, 2]}


def test_extract_json_strips_code_fences():
    reply = '```json\n{"pass": true, "weighted_score": 0.8}\n```'
    assert ee._extract_json(reply)["weighted_score"] == 0.8


def test_extract_json_tolerates_surrounding_prose():
    reply = 'Here is the result:\n{"answers": {"Q?": "A"}}\nHope that helps.'
    assert ee._extract_json(reply)["answers"] == {"Q?": "A"}


def test_extract_json_raises_without_an_object():
    with pytest.raises(ValueError, match="no JSON object"):
        ee._extract_json("the model refused")


def test_extract_json_raises_on_malformed_object():
    with pytest.raises(ValueError):
        ee._extract_json('{"unterminated": ')


# --- _artifact_listing ------------------------------------------------------------------
def _sandbox(tmp_path, files: dict[str, str]):
    for rel, body in files.items():
        path = tmp_path / "artifacts" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
    (tmp_path / "artifacts").mkdir(exist_ok=True)
    return tmp_path


def test_listing_without_artifacts_dir(tmp_path):
    assert ee._artifact_listing(tmp_path) == "(no artifacts/ directory)"


def test_listing_empty_artifacts_dir(tmp_path):
    (tmp_path / "artifacts").mkdir()
    assert ee._artifact_listing(tmp_path) == "(empty)"


def test_listing_inlines_deliverable_bodies(tmp_path):
    sandbox = _sandbox(
        tmp_path,
        {
            "pack/START-HERE.md": "# Index\nStatus: closed\n",
            "pack/summary-email.txt": "Hi,\nDelivered.\nMorgan\n",
        },
    )
    listing = ee._artifact_listing(sandbox)
    # Paths still listed...
    assert "artifacts/pack/START-HERE.md" in listing
    # ...and the judge can now actually read them.
    assert "Status: closed" in listing
    assert "Delivered." in listing
    assert "[... truncated" not in listing  # both files fit under the caps


def test_listing_leaves_non_text_artifacts_path_only(tmp_path):
    sandbox = _sandbox(tmp_path, {"pack/spec.md": "body text", "pack/spec.html": "<h1>html</h1>"})
    listing = ee._artifact_listing(sandbox)
    assert "artifacts/pack/spec.html" in listing
    assert "<h1>html</h1>" not in listing
    assert "body text" in listing


def test_listing_truncates_a_long_file_and_says_so(tmp_path):
    sandbox = _sandbox(tmp_path, {"pack/long.md": "x" * 500})
    listing = ee._artifact_listing(sandbox, body_cap=100, total_cap=1_000)
    assert "[... truncated: 100 of 500 chars shown ...]" in listing
    assert "x" * 101 not in listing


def test_listing_stops_at_the_total_cap_and_reports_the_omission(tmp_path):
    sandbox = _sandbox(tmp_path, {f"pack/{i}.md": f"body-{i} " + "y" * 100 for i in range(1, 5)})
    listing = ee._artifact_listing(sandbox, body_cap=100, total_cap=200)
    assert "body-1" in listing and "body-2" in listing
    assert "body-3" not in listing and "body-4" not in listing
    assert "2 further text deliverable(s) omitted" in listing
    # The omitted files are still NAMED - the judge sees that they exist.
    assert "artifacts/pack/3.md" in listing


def test_listing_total_cap_bounds_the_whole_body_section(tmp_path):
    sandbox = _sandbox(tmp_path, {f"pack/{i}.md": "z" * 5_000 for i in range(6)})
    listing = ee._artifact_listing(sandbox, body_cap=1_000, total_cap=2_500)
    assert listing.count("z") <= 2_500


def test_listing_survives_an_unreadable_file(tmp_path, monkeypatch):
    sandbox = _sandbox(tmp_path, {"pack/ok.md": "fine"})

    real_read_text = ee.Path.read_text

    def boom(self, *args, **kwargs):
        if self.name == "ok.md":
            raise OSError("permission denied")
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(ee.Path, "read_text", boom)
    assert "unreadable: permission denied" in ee._artifact_listing(sandbox)


def test_listing_default_caps_are_bounded():
    # The point of the caps is bounded prompt growth; a regression to "no cap" is a
    # token-cost incident, not a style nit.
    assert 0 < ee._ARTIFACT_BODY_CAP <= ee._ARTIFACT_LISTING_CAP <= 100_000


# --- transcript capture -----------------------------------------------------------------
class _Text:
    def __init__(self, text):
        self.text = text


class _Tool:
    def __init__(self, name, **input_):
        self.name = name
        self.input = input_


class _Msg:
    def __init__(self, *content):
        self.content = list(content)


def _lines(message, from_subagent, **kw):
    return ee._transcript_lines(message, _Text, _Tool, from_subagent, **kw)


def test_transcript_keeps_pm_text_verbatim():
    assert _lines(_Msg(_Text("Morgan here.")), False) == ["Morgan here."]


def test_transcript_tags_subagent_output():
    out = "".join(_lines(_Msg(_Text("qa-engineer: 3 defects found")), True))
    assert "[subagent]" in out and "3 defects found" in out


def test_transcript_caps_subagent_text():
    out = "".join(_lines(_Msg(_Text("w" * 500)), True, subagent_cap=50))
    assert "subagent output truncated at 50 chars" in out
    assert out.count("w") == 50


def test_transcript_records_tool_calls_but_not_gate_questions():
    out = "".join(
        _lines(_Msg(_Tool("Task", subagent_type="qa-engineer"), _Tool("AskUserQuestion")), False)
    )
    assert "[tool] Task qa-engineer" in out
    assert "AskUserQuestion" not in out


# --- report assembly + verdict block ----------------------------------------------------
def _result(case, passed, recall=1.0, judge=0.9, missed=None, traps=None):
    return {
        "case": case,
        "passed": passed,
        "deterministic": {
            "recall": recall,
            "must_find_missed": missed or [],
            "false_positive_traps_triggered": traps or [],
        },
        "judge": {"weighted_score": judge, "pass": passed},
        "gates_answered": 4,
        "cost_usd": 1.25,
        "num_turns": 40,
    }


def test_report_tabulates_every_case(tmp_path):
    results = [
        _result("process-light-engagement", True),
        _result("process-full-lifecycle", False, recall=0.5, judge=0.4, missed=["LIFE-2"]),
    ]
    text = ee._write_report(tmp_path, results).read_text(encoding="utf-8")
    assert "| process-light-engagement | PASS | 1.0" in text
    assert "| process-full-lifecycle | FAIL | 0.5" in text
    assert "LIFE-2" in text
    assert "**1/2 passed.**" in text


def test_report_embeds_a_draft_verdict_block(tmp_path):
    text = ee._write_report(tmp_path, [_result("a", True), _result("b", False)]).read_text(
        encoding="utf-8"
    )
    assert "```eval-verdict" in text
    assert "unadjudicated_failures: 1" in text


def test_verdict_block_is_a_fail_until_adjudicated():
    block = ee.verdict_block([_result("a", True), _result("b", False)], "20260801T000000Z")
    fields = rg.parse_verdict(block)
    assert fields["verdict"] == "fail"
    assert fields["cases_total"] == "2"
    assert fields["cases_passed_raw"] == "1"
    assert fields["unadjudicated_failures"] == "1"
    assert fields["runs"] == "20260801T000000Z"


def test_verdict_block_clean_sweep_claims_pass():
    block = ee.verdict_block([_result("a", True), _result("b", True)], "20260801T000000Z")
    assert rg.parse_verdict(block)["verdict"] == "pass"
    # ...and the gate's own checker accepts it (round-trip: emitter -> parser -> rules).
    assert rg._verdict_findings("eval-baseline-x.md", block) == []


def test_emitted_verdict_block_fails_the_gate_checker_while_unadjudicated():
    block = ee.verdict_block([_result("a", True), _result("b", False)], "20260801T000000Z")
    findings = rg._verdict_findings("eval-baseline-x.md", block)
    assert any("UNADJUDICATED" in f for f in findings)


# --- the tracked results log ------------------------------------------------------------
def test_result_record_flattens_the_score_shape():
    row = ee.result_record(_result("process-extensions", True, judge=0.91), "20260801T010203Z")
    assert row["run_id"] == "20260801T010203Z"
    assert row["case"] == "process-extensions"
    assert row["mode"] == "run"
    assert row["recall"] == 1.0
    assert row["judge_score"] == 0.91
    assert row["passed"] is True
    assert row["version"]  # stamped so a trend line can be split by release


def test_append_result_is_append_only_and_deduped(tmp_path):
    log = tmp_path / "results.jsonl"
    first = ee.result_record(_result("a", True), "R1")
    assert ee.append_result(first, log) is True
    assert ee.append_result(ee.result_record(_result("a", False), "R1"), log) is False
    assert ee.append_result(ee.result_record(_result("a", True), "R2"), log) is True
    rows = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert [r["run_id"] for r in rows] == ["R1", "R2"]
    assert rows[0]["passed"] is True  # the re-record did NOT overwrite the original


def test_read_results_skips_a_corrupt_line(tmp_path):
    log = tmp_path / "results.jsonl"
    log.write_text('{"run_id": "R1"}\nnot json\n\n{"run_id": "R2"}\n', encoding="utf-8")
    assert [r["run_id"] for r in ee.read_results(log)] == ["R1", "R2"]


def test_record_run_dir_backfills_runs_and_rescores(tmp_path):
    runs = tmp_path / "runs"
    case_dir = runs / "20260801T000000Z" / "process-light-engagement"
    case_dir.mkdir(parents=True)
    (case_dir / "score.json").write_text(
        json.dumps(_result("process-light-engagement", False)), encoding="utf-8"
    )
    (case_dir / "score-rescore.json").write_text(
        json.dumps(_result("process-light-engagement", True)), encoding="utf-8"
    )
    log = tmp_path / "results.jsonl"
    assert ee.record_run_dir(runs, log) == 2
    assert ee.record_run_dir(runs, log) == 0  # idempotent - safe to re-point at the same tree
    modes = sorted(r["mode"] for r in ee.read_results(log))
    assert modes == ["rescore", "run"]
    assert all(r["run_id"] == "20260801T000000Z" for r in ee.read_results(log))


def test_backfill_does_not_stamp_todays_version_on_an_old_run(tmp_path):
    # A pruned sandbox means the version under test is unrecoverable - recording the
    # CURRENT version there would invent provenance for a month-old row.
    runs = tmp_path / "runs"
    pruned = runs / "20260725T000000Z" / "old-case"
    pruned.mkdir(parents=True)
    (pruned / "score.json").write_text(json.dumps(_result("old-case", True)), encoding="utf-8")
    kept = runs / "20260726T000000Z" / "kept-case"
    (kept / "sandbox" / ".claude-plugin").mkdir(parents=True)
    (kept / "sandbox" / ".claude-plugin" / "plugin.json").write_text(
        '{"version": "0.29.0"}', encoding="utf-8"
    )
    (kept / "score.json").write_text(json.dumps(_result("kept-case", True)), encoding="utf-8")

    log = tmp_path / "results.jsonl"
    ee.record_run_dir(runs, log)
    versions = {r["case"]: r["version"] for r in ee.read_results(log)}
    assert versions == {"old-case": "unknown", "kept-case": "0.29.0"}


def test_record_run_dir_ignores_unreadable_scores(tmp_path):
    runs = tmp_path / "runs"
    case_dir = runs / "20260801T000000Z" / "broken"
    case_dir.mkdir(parents=True)
    (case_dir / "score.json").write_text("{ not json", encoding="utf-8")
    assert ee.record_run_dir(runs, tmp_path / "results.jsonl") == 0


# --------------------------------------------------------------- outcome classification


def test_run_outcome_separates_dead_runs_from_bad_answers():
    """A timeout or session error means the team never got to answer.

    Calling that a FAIL states something the evidence does not support. The 2026-08-01 audit
    measured 17/49 (35%) raw passes and found 13 of the 32 "failures" were runs that died -
    three on a confirmed API 529 after exhausting all ten retries. That single conflation is
    what made the headline number unreadable.
    """
    assert ee.run_outcome({"passed": True}) == "pass"
    assert ee.run_outcome({"passed": False}) == "fail"
    assert ee.run_outcome({"passed": False, "timed_out": True}) == "unscorable"
    assert ee.run_outcome({"passed": False, "session_error": True}) == "unscorable"
    # A dead run is unscorable even if the scorer happened to mark it passed before the
    # timeout/error was folded in - the run still produced no gradeable end state.
    assert ee.run_outcome({"passed": True, "timed_out": True}) == "unscorable"


def test_result_record_carries_outcome():
    rec = ee.result_record(_result("c", False), "20260801T000000Z", version="0.33.5")
    assert rec["outcome"] == "fail"
    dead = _result("c", False)
    dead["session_error"] = True
    assert ee.result_record(dead, "20260801T000000Z", version="0.33.5")["outcome"] == "unscorable"


def test_summarise_results_excludes_dead_runs_from_the_pass_rate():
    rows = [
        {"passed": True, "outcome": "pass"},
        {"passed": True, "outcome": "pass"},
        {"passed": False, "outcome": "fail"},
        {"passed": False, "outcome": "unscorable", "session_error": True},
        {"passed": False, "outcome": "unscorable", "timed_out": True},
    ]
    s = ee.summarise_results(rows)
    assert s["total"] == 5
    assert s["scorable"] == 3
    assert s["unscorable"] == 2
    assert s["passed"] == 2
    # 2/3 over scorable runs, not 2/5 over everything.
    assert s["pass_rate_scorable"] == pytest.approx(0.667, abs=0.001)
    assert s["pass_rate_all"] == pytest.approx(0.4, abs=0.001)


def test_summarise_results_derives_outcome_for_legacy_rows():
    """Rows written before the field existed must classify identically, or the trend breaks
    at the point the field was introduced."""
    rows = [
        {"passed": True},
        {"passed": False},
        {"passed": False, "timed_out": True},
    ]
    s = ee.summarise_results(rows)
    assert (s["scorable"], s["unscorable"], s["passed"]) == (2, 1, 1)


def test_summarise_results_handles_empty():
    s = ee.summarise_results([])
    assert s["total"] == 0 and s["pass_rate_scorable"] is None


# --------------------------------------------------------------- per-case wall clock


def test_case_timeout_precedence():
    """CLI override wins, else the manifest, else the default.

    One global number cannot fit this corpus: short review cases finish in minutes while a full
    lifecycle engagement legitimately runs past 110, so a budget generous for the former killed
    the latter mid-close. Four SUCCESSFUL runs exceeded the old 2400s default.
    """
    assert ee.case_timeout({}, None) == ee.DEFAULT_TIMEOUT_S
    assert ee.case_timeout({"timeout_s": 9300}, None) == 9300
    # An explicit --timeout is a human capping the run and must beat the manifest.
    assert ee.case_timeout({"timeout_s": 9300}, 600) == 600
    # 0 means "no wall clock" and must survive both layers rather than being treated as unset.
    assert ee.case_timeout({}, 0) == 0
    assert ee.case_timeout({"timeout_s": 0}, None) == 0


def test_case_timeout_ignores_unusable_values():
    """A typo must fall back to the default, never to 'no wall clock' - that would turn a
    hung case into an unbounded spend."""
    for bad in ("soon", None, -1, [], {}):
        assert ee.case_timeout({"timeout_s": bad}, None) == ee.DEFAULT_TIMEOUT_S


def test_long_cases_declare_a_timeout_above_the_default():
    """The cases measured running past the default carry their own budget.

    Guards against someone trimming a manifest back and silently reintroducing the timeouts
    that produced unscorable runs.
    """
    import yaml

    expected = {
        "process-full-lifecycle",
        "process-light-engagement",
        "injection-extensions",
        "process-company-allowlist",
        "process-two-engagements",
    }
    root = ee.REPO_ROOT / "evals" / "cases"
    for case in sorted(expected):
        manifest = yaml.safe_load((root / case / "expected.yaml").read_text(encoding="utf-8"))
        declared = manifest.get("timeout_s")
        assert isinstance(declared, int) and declared > ee.DEFAULT_TIMEOUT_S, (
            f"{case}: expected a per-case timeout_s above the {ee.DEFAULT_TIMEOUT_S}s default, "
            f"got {declared!r}"
        )
