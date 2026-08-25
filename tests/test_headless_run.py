"""Headless runs: argv construction and stream decoding (2026-08-25).

Fixtures are SHAPED FROM REAL CAPTURES taken from claude 2.1.243 - one success, one billing
failure - rather than from the documentation. Three of the tests below exist only because
the real output disagreed with what the docs implied, and none of them would have been
written from reading alone. The captures themselves are not committed: they carry a session
id, a working directory and a prompt, and a fixture that is shaped like the real thing is
worth as much without any of that.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load():
    if str(REPO_ROOT / "scripts") not in sys.path:
        sys.path.insert(0, str(REPO_ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location(
        "headless_run", REPO_ROOT / "scripts" / "headless_run.py"
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["headless_run"] = mod
    spec.loader.exec_module(mod)
    return mod


SESSION = "38f27013-c5e7-468e-8053-f3b3fe73054b"


def _init():
    return {"type": "system", "subtype": "init", "session_id": SESSION,
            "model": "claude-opus-5[1m]", "claude_code_version": "2.1.243"}


def _result_ok():
    return {
        "type": "result", "subtype": "success", "is_error": False,
        "session_id": SESSION, "result": "ok", "num_turns": 1, "duration_ms": 8734,
        "terminal_reason": "completed", "stop_reason": "end_turn",
        "total_cost_usd": 0.108862,
        "usage": {"input_tokens": 2, "output_tokens": 4,
                  "cache_creation_input_tokens": 10074, "cache_read_input_tokens": 16024},
        "modelUsage": {"claude-opus-5[1m]": {
            "inputTokens": 2, "outputTokens": 4, "cacheReadInputTokens": 16024,
            "cacheCreationInputTokens": 10074, "costUSD": 0.108862,
            "canonicalModel": "claude-opus-5"}},
    }


def _result_failed():
    """A REAL failure shape: subtype says success, is_error says otherwise."""
    return {
        "type": "result", "subtype": "success", "is_error": True,
        "session_id": SESSION, "result": "Credit balance is too low",
        "api_error_status": 400, "num_turns": 1, "duration_ms": 1734,
        "terminal_reason": "api_error", "total_cost_usd": 0, "modelUsage": {},
    }


def _lines(*events):
    return [json.dumps(e) for e in events]


# --- argv -------------------------------------------------------------------------------


def test_the_session_id_is_passed_in_not_discovered():
    """The whole reason this replaces a transcript reader. The caller generates the UUID and
    records it on the engagement, so the run and the engagement are the same thing by
    construction - no matching a session to a pack afterwards by date or newest file."""
    hr = _load()
    argv = hr.build_argv("do the thing", session_id=SESSION)
    assert "--session-id" in argv and argv[argv.index("--session-id") + 1] == SESSION
    assert "--output-format" in argv and "stream-json" in argv
    assert argv[1] == "-p"


def test_a_hard_budget_is_passed_when_asked_for():
    """--max-budget-usd is an ENFORCED ceiling and subagent spend counts toward it - unlike
    the advisory pacing it replaces, which a run could talk itself past."""
    hr = _load()
    argv = hr.build_argv("x", budget_usd=35)
    assert argv[argv.index("--max-budget-usd") + 1] == "35"
    assert "--max-budget-usd" not in hr.build_argv("x")


def test_unattended_defaults_to_dont_ask():
    """Correct here and nowhere else: an unattended run's questions were all answered at the
    pre-flight, so a question it could ask now would be one nobody is there to hear."""
    hr = _load()
    argv = hr.build_argv("x")
    assert argv[argv.index("--permission-mode") + 1] == "dontAsk"


def test_bare_is_refused_outright():
    """--bare is the DOCUMENTED recommendation for scripted calls and it skips hooks, skills,
    plugins and CLAUDE.md - it would run the engagement without the team, silently, leaving a
    run that looks normal and has none of the guardrails the pre-flight authorised. Refusing
    it in code beats a comment nobody reads."""
    hr = _load()
    with pytest.raises(ValueError) as caught:
        hr.build_argv("x", extra=("--bare",))
    assert "without the team" in str(caught.value)


def test_allowed_tools_are_passed_individually():
    hr = _load()
    argv = hr.build_argv("x", allowed_tools=("Read", "Bash(git log *)"))
    assert argv.count("--allowedTools") == 2
    assert "Bash(git log *)" in argv


# --- decoding ---------------------------------------------------------------------------


def test_a_run_reports_its_session_model_and_version(tmp_path):
    hr = _load()
    state = hr.read_stream(_lines(_init()))
    assert state["session_id"] == SESSION
    assert state["model"] == "claude-opus-5[1m]"
    assert state["version"] == "2.1.243"
    assert state["started"] is True and state["finished"] is False


def test_success_is_read_from_is_error_not_subtype():
    """THE trap, and it only shows in real output: a run that failed on a 400 still reports
    subtype "success". Anything keying on subtype calls a failed run a good one."""
    hr = _load()
    failed = hr.read_stream(_lines(_init(), _result_failed()))
    assert failed["ok"] is False
    assert failed["outcome"] == "api_error"
    assert "Credit balance" in failed["message"]

    good = hr.read_stream(_lines(_init(), _result_ok()))
    assert good["ok"] is True and good["outcome"] == "completed"


def test_cost_is_published_per_canonical_model():
    """No rate table. The stream keys usage by the full id and hands us canonicalModel
    alongside, so the suffix normalisation this repo once wrote by hand is published - and
    the published one is the authority."""
    hr = _load()
    state = hr.read_stream(_lines(_init(), _result_ok()))
    assert state["cost_usd"] == 0.108862
    assert set(state["by_model"]) == {"claude-opus-5"}, "keyed by canonical, not the full id"
    assert state["by_model"]["claude-opus-5"]["cost_usd"] == 0.108862
    assert state["by_model"]["claude-opus-5"]["cache_read"] == 16024


def test_a_rate_limit_event_is_a_status_report_not_a_block():
    """Captured live on a run that SUCCEEDED: status "allowed", with utilisation for the
    rolling windows. Treating its presence as "rate limited" flagged every healthy run,
    which is a false alarm that teaches you to ignore the field."""
    hr = _load()
    allowed = {"type": "rate_limit_event", "rate_limit_info": {
        "status": "allowed",
        "unifiedWindows": {"five_hour": {"utilization": 0.08},
                           "seven_day": {"utilization": 0.15}}}}
    state = hr.read_stream(_lines(_init(), allowed))
    assert state["rate_limited"] is False
    assert state["rate_limit_use"] == {"five_hour": 0.08, "seven_day": 0.15}

    blocked = {"type": "rate_limit_event", "rate_limit_info": {"status": "rejected"}}
    assert hr.read_stream(_lines(_init(), blocked))["rate_limited"] is True


def test_subagent_stages_are_tracked_with_their_parent():
    """parent_tool_use_id is what makes the stage tree exact at any nesting depth - the
    thing the deleted transcript reader could never see."""
    hr = _load()
    spawn = {"type": "assistant", "parent_tool_use_id": None, "message": {"content": [
        {"type": "tool_use", "id": "tu_1", "name": "Agent",
         "input": {"subagent_type": "code-reviewer"}}]}}
    nested = {"type": "assistant", "parent_tool_use_id": "tu_1", "message": {"content": [
        {"type": "tool_use", "id": "tu_2", "name": "Agent",
         "input": {"subagent_type": "qa-engineer"}}]}}
    state = hr.read_stream(_lines(_init(), spawn, nested))
    assert [s["agent"] for s in state["stages"]] == ["code-reviewer", "qa-engineer"]
    assert state["stages"][1]["parent"] == "tu_1", "nesting must be recoverable"
    assert state["tool_calls"] == 2


def test_retries_are_surfaced():
    """The difference between "slow" and "stuck", which is the question a watcher of an
    unattended run is actually asking."""
    hr = _load()
    retry = {"type": "system", "subtype": "api_retry", "attempt": 2,
             "error": "overloaded", "error_status": 529, "retry_delay_ms": 1000}
    state = hr.read_stream(_lines(_init(), retry))
    assert state["retries"][0]["error"] == "overloaded"
    assert state["retries"][0]["attempt"] == 2


def test_a_synthetic_error_message_is_not_counted_as_work():
    """A billing failure arrives as an assistant message with model "<synthetic>" and an
    error field. It is not a turn and must not be priced."""
    hr = _load()
    synthetic = {"type": "assistant", "error": "billing_error",
                 "message": {"model": "<synthetic>", "content": []}}
    state = hr.read_stream(_lines(_init(), synthetic))
    assert state["tool_calls"] == 0
    assert state["outcome"] == "billing_error"


def test_a_partial_line_is_counted_and_skipped():
    """The stream is written by another process; a partial write must not end the watching."""
    hr = _load()
    state = hr.read_stream([json.dumps(_init()), '{"type": "resu', json.dumps(_result_ok())])
    assert state["undecodable"] == 1
    assert state["ok"] is True, "the run still completes"


def test_blank_lines_and_junk_never_raise():
    hr = _load()
    state = hr.read_stream(["", "   ", "not json at all", "[]", "null"])
    assert state["events"] >= 0 and state["started"] is False


def test_a_missing_stream_file_yields_an_unstarted_run(tmp_path):
    hr = _load()
    state = hr.read_file(tmp_path / "nope.jsonl")
    assert state["started"] is False and state["finished"] is False


def test_the_summary_says_something_useful_at_each_phase():
    hr = _load()
    assert hr.summary(hr.new_state()) == "not started"
    running = hr.read_stream(_lines(_init()))
    assert "running" in hr.summary(running)
    done = hr.read_stream(_lines(_init(), _result_ok()))
    assert "completed" in hr.summary(done) and "$0.10" in hr.summary(done)
    failed = hr.read_stream(_lines(_init(), _result_failed()))
    assert "FAILED" in hr.summary(failed)
