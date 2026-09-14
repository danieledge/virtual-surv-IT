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
import os
import pathlib

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
    # The Mode column was added with plugin mode (2026-09-13); a result dict without one is a
    # repo-as-project run, which is what every case was before the flag existed.
    assert "| process-light-engagement | repo | PASS | 1.0" in text
    assert "| process-full-lifecycle | repo | FAIL | 0.5" in text
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
    # 2026-09-13 (step 3.9): a cap hit is neither a dead session nor a bad answer.
    assert (
        ee.run_outcome({"passed": False, "session_error": True, "error": "error_max_turns"})
        == "capped"
    )
    assert ee.run_outcome({"passed": False, "error": "error_max_budget_usd"}) == "capped"
    assert ee.run_outcome({"passed": False, "spend_capped": True}) == "capped"
    summary = ee.summarise_results(
        [{"passed": False, "error": "error_max_turns"}, {"passed": True}]
    )
    assert summary["capped"] == 1 and summary.get("passed", summary.get("passed_count", 1)) in (
        1,
        [True],
    )
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


def test_orchestrator_model_is_pinned_by_default():
    """The team session must pin the ORCHESTRATOR's tier, not inherit the SDK default.

    setting_sources=["project"] already gives each SUBAGENT its model: frontmatter, but until
    the 2026-08-01 audit nothing set the model for Morgan herself, so the top-level session
    silently ran on whatever the SDK defaulted to while the operating guide requires opus. The
    judge scores largely from the PM's own narration, so a cheaper orchestrator depresses the
    result in a way indistinguishable from a real regression.
    """
    import inspect

    sig = inspect.signature(ee.run_engage_session)
    assert sig.parameters["team_model"].default == "opus"
    src = inspect.getsource(ee.run_engage_session)
    assert "model=team_model" in src, "ClaudeAgentOptions must receive the pinned team model"


# --------------------------------------------------------------- gate exchanges as evidence


def test_gate_findings_carry_the_teams_own_wording(tmp_path):
    """Escalation was structurally unscorable before this.

    A case testing "pause and ask the user rather than deciding alone" recorded the question in
    gates.json, which the scorer never read: scoring ran over findings.json, whose titles are
    the NORMALIZER's paraphrase. So the behaviour was judged on someone else's summary of it.

    Found live on 2026-08-01 by process-gate-selfcorrect, which fired the question tool naming
    an evidence contradiction and refusing to resolve it alone - the exact behaviour under test,
    with the manifest's own keyword in the question - and scored recall 0.5 and FAIL because no
    paraphrased title carried the wording.
    """
    (tmp_path / "gates.json").write_text(
        json.dumps(
            {
                "consent_granted": False,
                "exchanges": [
                    {
                        "question": "NC-1's rationale is contradicted by the evidence - "
                        "I can't resolve that myself, how should it be disposed?",
                        "header": "NC-1",
                        "answer": "Reopen NC-1",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    out = ee.gate_findings(tmp_path)
    assert len(out) == 1
    title = out[0]["title"]
    # The team's OWN words must survive into the scored evidence, verbatim.
    assert "I can't resolve that myself" in title
    assert "NC-1" in title
    assert "Reopen NC-1" in title
    assert out[0]["kind"] == "behaviour"


def test_gate_findings_tolerate_missing_or_empty(tmp_path):
    assert ee.gate_findings(tmp_path) == []  # no gates.json at all
    (tmp_path / "gates.json").write_text("{ not json", encoding="utf-8")
    assert ee.gate_findings(tmp_path) == []
    (tmp_path / "gates.json").write_text(json.dumps({"exchanges": []}), encoding="utf-8")
    assert ee.gate_findings(tmp_path) == []
    # An exchange with no question text contributes nothing rather than an empty finding.
    (tmp_path / "gates.json").write_text(
        json.dumps({"exchanges": [{"question": "   ", "answer": "x"}]}), encoding="utf-8"
    )
    assert ee.gate_findings(tmp_path) == []


def test_gate_findings_records_every_exchange(tmp_path):
    (tmp_path / "gates.json").write_text(
        json.dumps(
            {"exchanges": [{"question": "first?"}, {"question": "second?", "answer": "yes"}]}
        ),
        encoding="utf-8",
    )
    out = ee.gate_findings(tmp_path)
    assert len(out) == 2
    assert "first?" in out[0]["title"] and "second?" in out[1]["title"]


# --------------------------------------------------------------- raw evidence for the scorer


def test_raw_evidence_carries_artifact_bodies_and_pm_prose(tmp_path):
    """The scorer matched only the NORMALIZER's paraphrase, so behaviour it reworded vanished.

    Measured on run 20260801T190159Z: three must-find items were performed with the manifest's
    own keywords verbatim in the delivered artifacts, yet scored as missed. The paraphrase had
    rewritten "🧠 Inferred" as "Declined to answer", and no occurrence of the keyword survived.
    """
    art = tmp_path / "artifacts" / "eng"
    art.mkdir(parents=True)
    (art / "delivery-report.md").write_text(
        "# Report\n\n> Document control - Status `Final - pending human sign-off`\n",
        encoding="utf-8",
    )
    (art / "engagement-summary-eng.txt").write_text(
        "Hi,\nAll harmonised to one authoritative set of numbers.\n", encoding="utf-8"
    )
    out = ee.raw_evidence_findings(tmp_path, "Morgan: tagging this 🧠 inferred, assumption stated.")
    blob = " ".join(f["title"] for f in out).lower()
    assert "pending human sign-off" in blob
    assert "authoritative" in blob
    assert "inferred" in blob  # PM prose reaches the evidence too
    # Source kinds are distinct so the scorer can tell the team TALKING from the team having
    # DONE something: a promise in prose must not satisfy a spec asserting completed work.
    kinds = {f["kind"] for f in out}
    assert kinds <= {"prose", "artifact"}
    assert "artifact" in kinds and "prose" in kinds
    # Raw chunks deliberately carry NO location. eval_score folds location into the keyword
    # haystack, so a path would let a spec match on a filename the harness seeded rather than
    # on content the team wrote - a false-pass vector found in review on 2026-08-01.
    assert all(f["location"] == "" for f in out)


def test_raw_evidence_chunks_so_mention_guards_stay_local(tmp_path):
    """Chunking is load-bearing, not cosmetic.

    eval_score applies exclude_keywords to the whole haystack, so dumping a file into ONE
    finding would let a single stray "outstanding" veto an unrelated planted match. Line-level
    chunks keep the guard local: the line claiming work is outstanding is vetoed, the line
    evidencing the work still matches.
    """
    art = tmp_path / "artifacts"
    art.mkdir(parents=True)
    (art / "notes.md").write_text(
        "The summary email was written and signed.\nThe RTM is still outstanding.\n",
        encoding="utf-8",
    )
    out = ee.raw_evidence_findings(tmp_path, "")
    titles = [f["title"] for f in out]
    assert any("summary email was written" in t for t in titles)
    assert any("still outstanding" in t for t in titles)
    # The two statements must NOT share a finding, or the guard would veto both together.
    assert not any("written" in t and "outstanding" in t for t in titles)


def test_raw_evidence_is_bounded_and_tolerant(tmp_path):
    """A huge artifact set must not explode findings.json, and unreadable input must not raise."""
    art = tmp_path / "artifacts"
    art.mkdir(parents=True)
    (art / "big.md").write_text("\n".join(f"line {i} of evidence" for i in range(5000)), "utf-8")
    out = ee.raw_evidence_findings(tmp_path, "\n".join(f"pm line {i}" for i in range(5000)))
    assert len(out) <= 600
    assert ee.raw_evidence_findings(tmp_path / "missing", "") == []
    # Separator-only and blank lines contribute nothing.
    (art / "rule.md").write_text("---\n\n| --- | --- |\n", encoding="utf-8")
    assert not any(
        set(f["title"]) <= {"-", "|", " "} for f in ee.raw_evidence_findings(tmp_path, "")
    )


# --------------------------------------------------------------- false-pass guards


def _seed(tmp_path):
    art = tmp_path / "artifacts"
    art.mkdir(parents=True)
    (art / "delivery-report.md").write_text(
        "Document control - Status `Final - pending human sign-off`\n"
        "Fixed: C1, C2 reconciled to one authoritative set of numbers.\n",
        encoding="utf-8",
    )
    return ee.fixture_baseline(tmp_path)


def test_seeded_fixtures_are_not_scored_as_the_teams_work(tmp_path):
    """THE false-pass hole. A case may seed a realistic drifted pack as its INPUT; scoring it
    let the harness match a planted must-find against text the harness itself wrote.

    Measured 2026-08-01: process-close-reconciliation with fixtures only and an EMPTY transcript
    scored passed=True, recall 0.8, zero must-finds missed. A run that did literally nothing
    passed. This is the direction that matters most: a harness which passes bad work is worse
    than one which fails good work.
    """
    baseline = _seed(tmp_path)
    assert baseline, "fixtures should have been baselined"
    # Team does nothing: no new file, no prose.
    assert ee.raw_evidence_findings(tmp_path, "", baseline) == []


def test_team_written_and_team_modified_files_are_still_scored(tmp_path):
    """The exclusion must not blind the scorer to real work (that was the ORIGINAL bug)."""
    baseline = _seed(tmp_path)
    # A brand-new artifact.
    (tmp_path / "artifacts" / "summary.txt").write_text("authoritative set agreed\n", "utf-8")
    blob = " ".join(f["title"] for f in ee.raw_evidence_findings(tmp_path, "", baseline)).lower()
    assert "authoritative set agreed" in blob
    # A seeded file the team EDITED is the team's work from that point on.
    (tmp_path / "artifacts" / "delivery-report.md").write_text("now corrected\n", encoding="utf-8")
    blob2 = " ".join(f["title"] for f in ee.raw_evidence_findings(tmp_path, "", baseline)).lower()
    assert "now corrected" in blob2


def test_raw_findings_carry_no_location(tmp_path):
    """eval_score folds location into the keyword haystack, so a path would let a spec match on
    a FILENAME the harness seeded rather than on content the team wrote."""
    baseline = _seed(tmp_path)
    (tmp_path / "artifacts" / "rtm.md").write_text("traceability row added\n", encoding="utf-8")
    assert all(f["location"] == "" for f in ee.raw_evidence_findings(tmp_path, "x", baseline))


def test_transcript_prose_is_never_crowded_out_by_artifacts(tmp_path):
    """Chunking prose last under a shared cap meant an artifact-heavy run recorded ZERO
    transcript chunks, silently reinstating the blindness this function exists to remove."""
    art = tmp_path / "artifacts"
    art.mkdir(parents=True)
    for i in range(6):
        (art / f"doc{i}.md").write_text(
            "\n".join(f"artifact line {j}" for j in range(200)), "utf-8"
        )
    out = ee.raw_evidence_findings(tmp_path, "\n".join(f"pm prose {i}" for i in range(300)), {})
    assert any("pm prose" in f["title"] for f in out), "PM prose was crowded out entirely"


def test_usage_attribution_splits_main_and_subagent_output():
    """Track D (token plan, 2026-08-18): the attribution block folds the usage series into
    main-loop vs subagent output shares and per-model totals; the last result entry wins,
    same rule the session capture applies to cost."""
    from scripts.eval_engage import usage_attribution

    series = [
        {
            "type": "assistant",
            "from_subagent": False,
            "model": "sonnet-x",
            "usage": {"output_tokens": 100},
        },
        {
            "type": "assistant",
            "from_subagent": True,
            "model": "haiku-y",
            "usage": {"output_tokens": 40},
        },
        {
            "type": "assistant",
            "from_subagent": True,
            "model": "sonnet-x",
            "usage": {"output_tokens": 60},
        },
        {
            "type": "result",
            "total_cost_usd": 1.0,
            "num_turns": 3,
            "usage": {
                "input_tokens": 5,
                "output_tokens": 200,
                "cache_read_input_tokens": 7,
                "cache_creation_input_tokens": 9,
            },
            "model_usage": {"sonnet-x": {"outputTokens": 160}},
        },
        {
            "type": "result",
            "total_cost_usd": 2.5,
            "num_turns": 4,
            "usage": {
                "input_tokens": 6,
                "output_tokens": 210,
                "cache_read_input_tokens": 8,
                "cache_creation_input_tokens": 10,
            },
            "model_usage": {"sonnet-x": {"outputTokens": 170}},
        },
    ]
    att = usage_attribution(series)
    assert att["total_cost_usd"] == 2.5 and att["num_turns"] == 4  # last result wins
    assert att["output_split"]["main_loop"] == {"messages": 1, "output_tokens": 100}
    assert att["output_split"]["subagents"] == {"messages": 2, "output_tokens": 100}
    assert att["per_model_stream"]["sonnet-x"] == {"messages": 2, "output_tokens": 160}
    assert att["per_model_stream"]["haiku-y"] == {"messages": 1, "output_tokens": 40}
    assert att["totals"]["output_tokens"] == 210
    assert att["per_model_result"]["sonnet-x"]["outputTokens"] == 170


def test_usage_attribution_empty_series_is_safe():
    from scripts.eval_engage import usage_attribution

    att = usage_attribution([])
    assert att["total_cost_usd"] is None
    assert att["output_split"]["main_loop"]["output_tokens"] == 0


# --- plugin mode (2026-09-13) -----------------------------------------------------------
#
# The layout builder is the part of plugin mode that can be wrong without anyone noticing: a
# registry key with the wrong shape, a cache copy that still carries evals/, a HOME that is not
# actually isolated, a client project the fixture quietly polluted. All of that is checkable
# without spending a session, which is what these tests do. The launch OPTION is pinned too -
# --plugin-dir is what the SDK emits for plugins=[{"type": "local", ...}], and a rename there
# would otherwise only show up as a live run that silently loads no plugin.


def _mini_plugin_source(tmp_path):
    """A tiny stand-in for the repo: enough structure to assert the copy rules on."""
    src = tmp_path / "src"
    (src / ".claude-plugin").mkdir(parents=True)
    (src / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({"name": "compliance-surveillance-team", "version": "9.9.9"}), encoding="utf-8"
    )
    (src / "hooks").mkdir()
    (src / "hooks" / "hooks.json").write_text('{"hooks": {}}', encoding="utf-8")
    (src / "scripts").mkdir()
    (src / "scripts" / "engage_probe.py").write_text("# probe\n", encoding="utf-8")
    (src / "evals" / "cases").mkdir(parents=True)
    (src / "evals" / "cases" / "expected.yaml").write_text("case: secret\n", encoding="utf-8")
    (src / "docs" / "assets").mkdir(parents=True)
    (src / "docs" / "assets" / "big.png").write_bytes(b"0" * 10)
    (src / "docs" / "guide.md").write_text("# guide\n", encoding="utf-8")
    (src / "node_modules").mkdir()
    (src / "node_modules" / "junk.js").write_text("junk", encoding="utf-8")
    return src


def _layout(tmp_path, **kw):
    return ee.build_plugin_layout(tmp_path / "run", source_root=_mini_plugin_source(tmp_path), **kw)


def test_plugin_layout_puts_the_cache_copy_where_an_install_does(tmp_path):
    layout = _layout(tmp_path)
    assert layout.version == "9.9.9"
    assert layout.cache_dir == (
        layout.config_dir / "plugins" / "cache" / ee.PLUGIN_MARKETPLACE / ee.PLUGIN_NAME / "9.9.9"
    )
    assert (layout.cache_dir / "hooks" / "hooks.json").is_file()
    assert (layout.cache_dir / ".claude-plugin" / "plugin.json").is_file()


def test_plugin_layout_registry_has_the_v2_shape(tmp_path):
    layout = _layout(tmp_path)
    registry = json.loads(layout.registry_file.read_text(encoding="utf-8"))
    assert registry["version"] == 2
    key = f"{ee.PLUGIN_NAME}@{ee.PLUGIN_MARKETPLACE}"
    entry = registry["plugins"][key][0]
    assert entry["scope"] == "local"
    assert entry["projectPath"] == str(layout.project)
    assert entry["installPath"] == str(layout.cache_dir)
    assert entry["version"] == "9.9.9"
    assert entry["installedAt"].endswith("Z")


def test_plugin_layout_marketplace_points_at_the_repo_copy(tmp_path):
    layout = _layout(tmp_path)
    markets = json.loads(layout.marketplaces_file.read_text(encoding="utf-8"))
    entry = markets[ee.PLUGIN_MARKETPLACE]
    # A directory source, never github/git: a run that reached the network would not be
    # testing the copy on disk.
    assert entry["source"] == {"source": "directory", "path": str(layout.marketplace_dir)}
    assert entry["installLocation"] == str(layout.marketplace_dir)
    assert (layout.marketplace_dir / "hooks" / "hooks.json").is_file()


def test_plugin_cache_copy_excludes_the_ground_truth_and_the_bulk(tmp_path):
    """evals/ is the load-bearing exclusion: blindness has to be structural, as in the repo
    sandbox. node_modules and docs/assets are bulk, not secrecy."""
    layout = _layout(tmp_path)
    for copy in (layout.cache_dir, layout.marketplace_dir):
        assert not (copy / "evals").exists()
        assert not (copy / "node_modules").exists()
        assert not (copy / "docs" / "assets").exists()
        assert (copy / "docs" / "guide.md").is_file()


def test_plugin_client_project_holds_only_what_go_leaves_until_a_fixture_lands(tmp_path):
    """The client project starts the way `virt-surv go` leaves a fresh one: nothing but the
    guard's warmed interpreter cache under VSIT/local (first live run, 2026-09-13: without it
    the prefetch hook is silent by design and the missing-injection tripwire fired on a
    correct open). No workspace, no probe cache, no code."""
    layout = _layout(tmp_path)
    assert layout.project.is_dir()
    assert [p.name for p in layout.project.iterdir()] == ["VSIT"]
    cache = ee._vsit_paths().local_file("guard_interpreter", layout.project)
    assert cache.is_file() and cache.read_text(encoding="utf-8").strip()
    assert not any(p for p in (layout.project / "VSIT").rglob("*") if p.name.startswith("engage"))

    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()
    (fixtures / "alert_threshold_check.py").write_text("x = 1\n", encoding="utf-8")
    ee.overlay_fixtures(fixtures, layout.project)
    assert sorted(p.name for p in layout.project.iterdir()) == ["VSIT", "alert_threshold_check.py"]


def test_plugin_layout_never_writes_outside_its_own_root(tmp_path):
    layout = _layout(tmp_path)
    for path in (layout.home, layout.project, layout.cache_dir, layout.registry_file):
        assert str(path).startswith(str(layout.root))


def test_plugin_session_env_isolates_home_on_posix(tmp_path):
    """A POSIX-shaped home by construction, like the Windows-shaped test below: on a real
    Windows host tmp_path carries a drive letter, so HOMEDRIVE is rightly set there."""
    layout = _layout(tmp_path)
    layout.home = pathlib.PurePosixPath("/runs/r1/home")
    env = layout.session_env()
    assert env["HOME"] == "/runs/r1/home"
    assert env["USERPROFILE"] == "/runs/r1/home"  # set on POSIX too, so a fake is never real
    assert env["CLAUDE_CONFIG_DIR"] == str(layout.config_dir)
    assert "HOMEDRIVE" not in env  # no drive letter on a POSIX path


def test_plugin_session_env_carries_homedrive_for_a_windows_shaped_home(tmp_path):
    """A Windows shell derives `~` from HOMEDRIVE/HOMEPATH, so a throwaway home that sets only
    HOME/USERPROFILE would still resolve `~` to the real profile."""
    layout = _layout(tmp_path)
    layout.home = pathlib.PureWindowsPath(r"C:\runs\r1\home")
    env = layout.session_env()
    assert env["HOMEDRIVE"] == "C:"
    assert env["HOMEPATH"] == "\\runs\\r1\\home"
    assert env["USERPROFILE"] == r"C:\runs\r1\home"


def test_plugin_layout_writes_trust_into_the_throwaway_home_only(tmp_path):
    layout = _layout(tmp_path)
    ee.ensure_workspace_trust(layout.project, layout.claude_json_files)
    for cfg in layout.claude_json_files:
        data = json.loads(cfg.read_text(encoding="utf-8"))
        assert data["projects"][str(layout.project)]["hasTrustDialogAccepted"] is True
    ee.drop_workspace_trust(layout.project, layout.claude_json_files)
    for cfg in layout.claude_json_files:
        assert json.loads(cfg.read_text(encoding="utf-8"))["projects"] == {}


def test_auth_seeding_copies_credentials_and_nothing_else(tmp_path):
    layout = _layout(tmp_path)
    real_config = tmp_path / "realhome" / ".claude"
    real_config.mkdir(parents=True)
    (real_config / ".credentials.json").write_text('{"token": "x"}', encoding="utf-8")
    real_cfg = tmp_path / "realhome" / ".claude.json"
    real_cfg.write_text(
        json.dumps(
            {
                "userID": "u1",
                "oauthAccount": {"emailAddress": "a@b"},
                "projects": {"/somewhere/private": {"hasTrustDialogAccepted": True}},
                "installedPlugins": ["something-else"],
            }
        ),
        encoding="utf-8",
    )
    seeded = ee.seed_session_auth(layout, real_config, real_cfg)
    assert ".credentials.json" in seeded and "userID" in seeded
    carried = json.loads(layout.claude_json_files[0].read_text(encoding="utf-8"))
    assert carried["userID"] == "u1"
    # The developer's own projects and plugin registry must NOT cross over - inheriting them
    # is what would hide the defects plugin mode exists to find.
    assert "projects" not in carried and "installedPlugins" not in carried


def test_windows_unnameable_files_are_skipped_on_every_platform(tmp_path, monkeypatch):
    assert ee.windows_nameable("normal.py")
    assert not ee.windows_nameable("aux")
    assert not ee.windows_nameable("COM1.txt")
    assert not ee.windows_nameable("what?.md")
    assert not ee.windows_nameable("trailing.")
    src = tmp_path / "src"
    src.mkdir()
    (src / "keep.md").write_text("k", encoding="utf-8")
    if os.name != "nt":
        # Windows itself refuses to create this name ("a:" reads as a drive), so the
        # copytree branch can only meet it on a POSIX source tree.
        (src / "a:b.md").write_text("x", encoding="utf-8")
    ee.copy_plugin_tree(src, tmp_path / "dst")
    assert [p.name for p in (tmp_path / "dst").iterdir()] == ["keep.md"]
    # The tracked-files branch (a git checkout) skips by NAME before it touches the disk,
    # so the skip itself is exercised on every platform, Windows included.
    monkeypatch.setattr(ee, "_tracked_files", lambda source: ["keep.md", "a:b.md", "aux/x.md"])
    ee.copy_plugin_tree(src, tmp_path / "dst2")
    assert [p.name for p in (tmp_path / "dst2").iterdir()] == ["keep.md"]


def test_long_path_note_reports_the_worst_case_only_when_there_is_one(tmp_path):
    root = tmp_path / "r"
    root.mkdir()
    (root / "short.md").write_text("x", encoding="utf-8")
    assert ee.long_path_note(root, limit=4000) == ""
    note = ee.long_path_note(root, limit=1)
    assert "MAX_PATH" in note and "short.md" in note and "Windows" in note


def test_probe_cache_variant_writes_what_go_would_have(tmp_path):
    layout = _layout(tmp_path, probe_cache=True)
    import scripts.vsit_paths as vsit_paths

    cache = vsit_paths.local_file("engage_probe", layout.project)
    payload = json.loads(cache.read_text(encoding="utf-8"))
    assert payload["plugin_version"] == "9.9.9"
    assert "PLUGIN_ROOT=" in payload["report"]
    assert payload["prefs_mtime"] == 0  # a preferences-less client project stamps 0, not -1
    # The cached report is served to the session verbatim, so the interpreter in it must be
    # the one the SESSION sees - never this driver's repo venv, which has no user-site
    # Markdown/bleach and would make render_html "impossible" inside the run.
    venv = os.environ.get("VIRTUAL_ENV")
    if venv:
        assert not payload["interpreter"].startswith(venv)


def test_case_mode_defaults_to_repo_and_honours_the_manifest_and_the_flag():
    assert ee.case_mode({}) == "repo"
    assert ee.case_mode({"mode": "plugin"}) == "plugin"
    assert ee.case_mode({"mode": "repo"}, force_plugin=True) == "plugin"
    assert ee.case_mode({"mode": "nonsense"}) == "repo"


def test_launch_command_passes_plugin_dir_and_the_hook_event_flag(tmp_path):
    cmd = ee.launch_command(tmp_path / "proj", tmp_path / "cache", cli="/bin/claude")
    assert cmd[0] == "/bin/claude"
    # The exact option the SDK emits for plugins=[{"type": "local", "path": ...}]
    # (claude_agent_sdk/_internal/transport/subprocess_cli.py, read 2026-09-13).
    assert "--plugin-dir" in cmd
    assert cmd[cmd.index("--plugin-dir") + 1] == str(tmp_path / "cache")
    assert "--include-hook-events" in cmd
    assert "--setting-sources=project" in cmd


def test_launch_command_omits_plugin_dir_in_repo_mode(tmp_path):
    assert "--plugin-dir" not in ee.launch_command(tmp_path, None, cli="/bin/claude")


class _FakeShutil:
    """Stands in for the shutil the resolver reaches for. Patched on the module, never on the
    real shutil: the layout builder needs the genuine copytree in the same test session."""

    def __init__(self, table):
        self._table = table

    def which(self, name):
        return self._table.get(name)


def test_cli_resolution_prefers_a_native_exe_on_windows(monkeypatch):
    """shutil.which on Windows can hand back npm's claude.cmd shim, which CreateProcess
    refuses to spawn - the SDK prefers a native claude.exe, and so must the dry run."""
    monkeypatch.setattr(ee, "_bundled_cli", lambda windows: None)
    monkeypatch.setattr(
        ee,
        "shutil",
        _FakeShutil({"claude": r"C:\npm\claude.cmd", "claude.exe": r"C:\bin\claude.exe"}),
    )
    assert ee.resolve_cli_path(windows=True) == r"C:\bin\claude.exe"


def test_cli_resolution_takes_the_path_hit_on_posix(monkeypatch):
    monkeypatch.setattr(ee, "_bundled_cli", lambda windows: None)
    monkeypatch.setattr(ee, "shutil", _FakeShutil({"claude": "/usr/local/bin/claude"}))
    assert ee.resolve_cli_path(windows=False) == "/usr/local/bin/claude"


def test_cli_resolution_prefers_the_sdks_bundled_binary(monkeypatch):
    """The SDK's own first search step - a bundled CLI wins over anything on PATH."""
    monkeypatch.setattr(ee, "_bundled_cli", lambda windows: "/sdk/_bundled/claude")
    assert ee.resolve_cli_path(windows=False) == "/sdk/_bundled/claude"


def test_dry_run_report_names_the_layout_and_launches_nothing(tmp_path):
    layout = _layout(tmp_path)
    report = ee.describe_dry_run(
        "process-plugin-mode-open",
        layout.project,
        layout.cache_dir,
        layout.session_env(),
        "/engage",
        "opus",
        extra_notes=["MAX_PATH note: nothing to report"],
    )
    assert str(layout.project) in report
    assert "--plugin-dir" in report
    assert f"HOME={layout.home}" in report
    assert "MAX_PATH note" in report
    assert "Nothing was launched" in report


# --- structured event capture -----------------------------------------------------------
class _ToolUse:
    def __init__(self, tid, name, data):
        self.id, self.name, self.input = tid, name, data


class _ToolResult:
    def __init__(self, tid, content, is_error):
        self.tool_use_id, self.content, self.is_error = tid, content, is_error


class _Hook:
    hook_event_name = "UserPromptSubmit"
    subtype = "hook_response"
    data = {"output": "<persona-anchor>x</persona-anchor>", "exit_code": 0}


def test_event_entry_records_tool_calls_structurally():
    msg = _Msg(_ToolUse("t1", "Read", {"file_path": "/x/y.md"}))
    entry = ee.event_entry(msg, "AssistantMessage")
    assert entry["tools"] == [{"id": "t1", "name": "Read", "input": {"file_path": "/x/y.md"}}]
    assert entry["repr"]  # the repr stays: everything that ever read it still can


def test_event_entry_records_tool_results_structurally():
    msg = _Msg(_ToolResult("t1", [{"type": "text", "text": "File does not exist."}], True))
    entry = ee.event_entry(msg, "UserMessage")
    assert entry["tool_results"][0]["tool_use_id"] == "t1"
    assert entry["tool_results"][0]["is_error"] is True
    assert "does not exist" in entry["tool_results"][0]["text"]


def test_event_entry_records_hook_payloads():
    entry = ee.event_entry(_Hook(), "HookEventMessage")
    assert entry["hook"]["event"] == "UserPromptSubmit"
    assert "<persona-anchor>" in entry["hook"]["output"]


def test_captured_events_feed_the_tripwires_end_to_end(tmp_path):
    """The whole chain: capture -> events.jsonl -> tripwire context -> a firing tripwire."""
    out_dir = tmp_path / "case"
    out_dir.mkdir()
    entries = [
        ee.event_entry(
            _Msg(_ToolUse("t1", "Read", {"file_path": "/plug/references/x.md"})),
            "AssistantMessage",
        ),
        ee.event_entry(_Msg(_ToolResult("t1", "File does not exist.", True)), "UserMessage"),
    ]
    (out_dir / "events.jsonl").write_text(
        "\n".join(json.dumps(e) for e in entries), encoding="utf-8"
    )
    (out_dir / "run-meta.json").write_text(
        json.dumps(
            {
                "mode": "plugin",
                "project_root": "/proj",
                "plugin_root": "/plug",
                "workflow": "/engage",
            }
        ),
        encoding="utf-8",
    )
    ctx = ee.tripwire_context(out_dir, tmp_path, "", {"workflow": "/engage"})
    assert ctx.plugin_root == "/plug" and ctx.expects_engaged_open is True
    ids = [h["id"] for h in ee.scan_tripwires(ctx, {})]
    assert "plugin-path-guess" in ids


def test_rescore_finds_a_plugin_runs_client_project(tmp_path):
    """--rescore assumed `<case>/sandbox`; a plugin-mode run's project is inside the layout,
    so rescoring one against the old path would score every artifact as missing."""
    out_dir = tmp_path / "case"
    out_dir.mkdir()
    assert ee.rescore_project_root(out_dir) == out_dir / "sandbox"
    (out_dir / "run-meta.json").write_text(
        json.dumps({"mode": "plugin", "project_root": str(out_dir / "plugin" / "proj")}),
        encoding="utf-8",
    )
    assert ee.rescore_project_root(out_dir) == out_dir / "plugin" / "proj"


def test_tripwire_context_falls_back_to_the_sandbox_without_run_meta(tmp_path):
    ctx = ee.tripwire_context(tmp_path, tmp_path / "sandbox", "", {"workflow": "/engage-light"})
    assert ctx.project_root == str(tmp_path / "sandbox")
    assert ctx.plugin_root == str(tmp_path / "sandbox")  # repo-as-project: the two are one
    assert ctx.expects_engaged_open is True


# ------------------------------------------------- 2026-09-13: a session dead at the spend cap


def test_case_budget_precedence_matches_case_timeout():
    assert ee.case_budget({"max_budget_usd": 20}, None) == 20.0
    assert ee.case_budget({"max_budget_usd": 20}, 5.0) == 5.0
    assert ee.case_budget({}, None) is None
    assert ee.case_budget({"max_budget_usd": "lots"}, None) is None
    assert ee.case_budget({"max_budget_usd": 0}, None) is None


def test_a_session_that_died_at_the_cap_is_described_as_capped_not_crashed():
    """Rerun of process-blocked-not-done: the SDK said only 'Command failed with exit code 1
    ... Check stderr output for details' and the cost sat at $5.02 against a $5 cap."""
    cap = ee.SessionCapture(cost_usd=5.02, cli_stderr=["something unrelated\n"])
    text = ee.describe_session_death(RuntimeError("Command failed with exit code 1"), cap, 5.0)
    assert cap.spend_capped and text.startswith("spend cap reached ($5.02 against a $5.0 cap)")
    assert "cli stderr: something unrelated" in text
    plain = ee.SessionCapture(cost_usd=0.4)
    text = ee.describe_session_death(RuntimeError("stream dropped"), plain, 5.0)
    assert not plain.spend_capped and text == "RuntimeError: stream dropped"


def test_sandbox_copy_leaves_the_checkout_daemon_state_behind(tmp_path, monkeypatch):
    """Rerun of process-blocked-not-done (2026-09-13): the sandbox inherited this checkout's
    daemon port file and token, its first hook calls were answered by this checkout's daemon
    with nothing, and the /engage open carried no probe injection."""
    src = tmp_path / "src"
    (src / ".claude").mkdir(parents=True)
    (src / ".claude" / ".guard-daemon-port").write_text("1234\nabc\n")
    (src / ".claude" / ".guard-daemon-start-backoff").write_text("1")
    (src / ".claude" / ".guard-interpreter").write_text("/usr/bin/python3\n")
    (src / "README.md").write_text("x")
    monkeypatch.setattr(ee, "REPO_ROOT", src)
    dest = tmp_path / "sandbox"
    ee.build_sandbox(dest)
    assert not (dest / ".claude" / ".guard-daemon-port").exists()
    assert not (dest / ".claude" / ".guard-daemon-start-backoff").exists()
    assert (dest / ".claude" / ".guard-interpreter").exists()
    tgt = tmp_path / "target"
    ee.build_target_sandbox(src, tgt, {})
    assert not (tgt / ".claude" / ".guard-daemon-port").exists()


def test_the_sandbox_copies_without_rsync_where_there_is_none(tmp_path, monkeypatch):
    """The Windows VM and the Windows runner have no rsync (2026-09-14). Same excludes,
    same reading of them: a bare name anywhere in the tree, a slashed one at that path."""
    src = tmp_path / "src"
    (src / ".claude").mkdir(parents=True)
    (src / ".claude" / ".guard-daemon-port").write_text("1234\nabc\n")
    (src / ".claude" / ".guard-interpreter").write_text("/usr/bin/python3\n")
    (src / "sub" / "__pycache__").mkdir(parents=True)
    (src / "sub" / "__pycache__" / "a.pyc").write_text("x")
    (src / "sub" / "keep.py").write_text("x")
    (src / "README.md").write_text("x")
    monkeypatch.setattr(ee.shutil, "which", lambda name, *a, **k: None)
    monkeypatch.setattr(ee, "REPO_ROOT", src)
    dest = tmp_path / "sandbox"
    ee.build_sandbox(dest)
    copied = sorted(
        p.relative_to(dest).as_posix()
        for p in dest.rglob("*")
        if p.is_file() and not p.relative_to(dest).as_posix().startswith(".git/")
    )
    assert copied == [".claude/.guard-interpreter", "README.md", "sub/keep.py"]
    tgt = tmp_path / "target"
    ee.build_target_sandbox(src, tgt, {"x": 1})
    assert not (tgt / ".claude" / ".guard-daemon-port").exists()
    assert (tgt / "sub" / "keep.py").is_file() and not (tgt / "sub" / "__pycache__").exists()


# ------------------------------------------------- 2026-09-13: plugin commands are namespaced


def test_plugin_mode_sends_the_namespaced_front_door(tmp_path):
    (tmp_path / ".claude-plugin").mkdir()
    (tmp_path / ".claude-plugin" / "plugin.json").write_text('{"name": "team-x"}')
    assert ee.namespaced_command("/engage", tmp_path) == "/team-x:engage"
    assert ee.namespaced_command("/engage-light now", tmp_path) == "/team-x:engage-light now"
    assert ee.namespaced_command("/team-x:engage", tmp_path) == "/team-x:engage"
    assert ee.namespaced_command("/engage", tmp_path / "nowhere") == "/engage"
    for cmd in ("/engage", "/team-x:engage", "/engage-light x"):
        assert ee._ENGAGE_OPEN_RE.match(cmd), cmd
    assert not ee._ENGAGE_OPEN_RE.match("/handover")


def test_an_unknown_command_reply_is_a_front_door_failure_not_a_zero_recall():
    reason = ee.front_door_missing("Unknown command: /engage", 0)
    assert reason.startswith("front door not loaded") and "/engage" in reason
    assert ee.front_door_missing("🎩 Morgan here", 12) == ""
    assert ee.front_door_missing("Unknown command: /engage", 3) == ""


def test_case_max_turns_precedence():
    d = ee._DEFAULT_MAX_TURNS
    assert ee.case_max_turns({"max_turns": 140}, d) == 140
    assert ee.case_max_turns({"max_turns": 140}, 20) == 20  # explicit CLI cap wins
    assert ee.case_max_turns({}, d) == d
    assert ee.case_max_turns({"max_turns": "lots"}, d) == d
    assert ee.case_max_turns({"max_turns": 0}, d) == d


# ------------------------------------------------ 2026-09-13 framework review, step 5.1


def test_rescore_of_a_relocated_golden_run_falls_back_to_its_sandbox_subset(tmp_path):
    """A golden run under evals/golden-runs/<case>/ carries its project subset at
    <case>/sandbox; the absolute path run-meta recorded (a temp dir, a pruned run) is gone."""
    out_dir = tmp_path / "process-plugin-mode-open"
    (out_dir / "sandbox").mkdir(parents=True)
    (out_dir / "run-meta.json").write_text(
        json.dumps({"mode": "plugin", "project_root": "/tmp/vsit-eval-gone-xyz/proj"}),
        encoding="utf-8",
    )
    assert ee.rescore_project_root(out_dir) == out_dir / "sandbox"
    # A recorded root that still exists wins, as before.
    live = tmp_path / "live-proj"
    live.mkdir()
    (out_dir / "run-meta.json").write_text(
        json.dumps({"mode": "plugin", "project_root": str(live)}), encoding="utf-8"
    )
    assert ee.rescore_project_root(out_dir) == live


def test_replay_scores_without_contacting_a_model(tmp_path, monkeypatch, capsys):
    """--rescore --replay re-runs the deterministic layers and the scorer over the saved
    normalizer findings; neither the normalizer nor the judge may be called."""
    import asyncio
    import types

    out_dir = tmp_path / "process-blocked-not-done"
    sandbox = out_dir / "sandbox"
    sandbox.mkdir(parents=True)
    (out_dir / "events.jsonl").write_text("", encoding="utf-8")
    (out_dir / "findings.json").write_text(
        json.dumps(
            {
                "findings": [
                    {
                        "title": "the blocked state was recorded",
                        "severity": "warning",
                        "layer": "normalizer",
                    },
                    {"title": "stale from a probe", "severity": "info"},
                ]
            }
        ),
        encoding="utf-8",
    )

    async def _no_model(*a, **k):
        raise AssertionError("a replay must not call a model")

    monkeypatch.setattr(ee, "normalize", _no_model)
    monkeypatch.setattr(ee, "judge", _no_model)
    manifest = {
        "workflow": "/engage",
        "judge": "none",
        "rubric": "process-discipline-probe",
        "planted": [
            {
                "id": "P-1",
                "keywords": ["blocked state"],
                "min_severity": "warning",
                "must_find": True,
            }
        ],
        "forbidden": [],
        "pass": {"require_all_must_find": True, "forbid_all": True},
    }
    args = types.SimpleNamespace(skip_judge=False, aux_model="sonnet", replay=True)
    result = asyncio.run(
        ee.score_run(
            "process-blocked-not-done", out_dir, sandbox, "transcript text", manifest, "", args
        )
    )
    assert result["passed"] is True
    titles = [
        f.get("title") for f in json.loads((out_dir / "findings.json").read_text())["findings"]
    ]
    assert "the blocked state was recorded" in titles
    assert "stale from a probe" not in titles, "only normalizer-layer findings are carried over"
