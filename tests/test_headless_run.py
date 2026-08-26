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
import os
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


def test_unattended_can_actually_write_its_artifacts():
    """dontAsk was the first choice and it was wrong in a way that looked like success: it
    denies everything outside the allow rules, so a run could not Write or run Bash at all.
    It read a few files, produced nothing, finished in under two minutes and reported ok
    (live report 2026-08-26: "it says finished too quickly, no artifacts"; confirmed by
    reading permission_denials off a real run - Write DENIED, Bash DENIED, terminal_reason
    "completed").

    An unattended engagement's entire output is files. A mode that forbids writing them does
    not make the run safe, it makes it pointless - and silently so."""
    hr = _load()
    argv = hr.build_argv("x")
    assert argv[argv.index("--permission-mode") + 1] == "acceptEdits"
    assert "dontAsk" not in argv


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


# --- supervision ---------------------------------------------------------------------------
#
# The child writes its stream to a FILE rather than a pipe we hold. That one choice is what
# makes an unattended run survivable: nobody owns the process, so the launcher can be closed,
# crash, or catch a stray Esc, and the run continues and stays readable. Verified live
# 2026-08-25 with a real `claude -p`: a run started by one process was re-attached to, in
# full, by a completely different process after the first had exited.
#
# These tests use a stand-in child so the suite never spends API credit.


def _project(tmp_path: Path) -> Path:
    (tmp_path / ".claude").mkdir(parents=True, exist_ok=True)
    return tmp_path


def _fake_claude(tmp_path: Path, lines: list, sleep: float = 0.0) -> Path:
    """A script that behaves like `claude -p --output-format stream-json` enough to supervise."""
    body = [
        "import sys, time, json",
        f"time.sleep({sleep})",
    ]
    for line in lines:
        body.append(f"print({json.dumps(json.dumps(line))}, flush=True)")
    path = tmp_path / "fake_claude.py"
    path.write_text("\n".join(body) + "\n", encoding="utf-8")
    return path


def _fake_argv(hr, monkeypatch, script: Path):
    """Point build_argv's executable at the stand-in, keeping every other flag real."""
    real = hr.build_argv

    def patched(prompt, **kw):
        kw["claude"] = sys.executable
        argv = real(prompt, **kw)
        return [argv[0], str(script)] + argv[1:]

    monkeypatch.setattr(hr, "build_argv", patched)


def test_a_started_run_records_where_to_find_it(tmp_path, monkeypatch):
    hr = _load()
    project = _project(tmp_path)
    _fake_argv(hr, monkeypatch, _fake_claude(tmp_path, [_init(), _result_ok()]))
    record = hr.start(project, "do the thing", slug="alpha", budget_usd=35)
    assert record["session_id"] and record["slug"] == "alpha"
    assert Path(record["stream"]).exists()
    assert (hr.run_dir(project) / f"{record['session_id']}.run.json").is_file()


def test_the_prompt_is_never_written_to_the_run_record(tmp_path, monkeypatch):
    """It is the human's request, it can carry anything, and this file sits in the project.
    The engagement pack is where a request belongs."""
    hr = _load()
    project = _project(tmp_path)
    _fake_argv(hr, monkeypatch, _fake_claude(tmp_path, [_init()]))
    secret = "CLIENT-CONFIDENTIAL-REQUEST-TEXT"
    record = hr.start(project, secret)
    written = (hr.run_dir(project) / f"{record['session_id']}.run.json").read_text("utf-8")
    assert secret not in written
    assert secret not in json.dumps(record)


def test_a_run_is_readable_by_a_process_that_did_not_start_it(tmp_path, monkeypatch):
    """The whole point. Reading goes through the recorded path, not through a handle - so
    "I accidentally closed the launcher" stops being a way to lose a run."""
    hr = _load()
    project = _project(tmp_path)
    _fake_argv(hr, monkeypatch, _fake_claude(tmp_path, [_init(), _result_ok()]))
    started = hr.start(project, "x", slug="alpha")
    _wait_finished(hr, started)

    # A fresh module instance, holding nothing from the start.
    other = _load()
    found = other.latest(project, slug="alpha")
    assert found is not None and found["session_id"] == started["session_id"]
    state = other.status(found)
    assert state["finished"] is True and state["ok"] is True
    assert state["cost_usd"] == 0.108862


def _wait_finished(hr, record, timeout=20.0):
    import time as _t

    deadline = _t.time() + timeout
    while _t.time() < deadline:
        state = hr.status(record)
        if state["finished"]:
            return state
        _t.sleep(0.2)
    raise AssertionError(f"run did not finish: {hr.summary(hr.status(record))}")


def test_liveness_is_judged_from_the_stream_not_the_pid(tmp_path, monkeypatch):
    """A pid check lies after reuse and behaves differently on every platform. A result event
    means finished; that is true whoever is asking and whenever."""
    hr = _load()
    project = _project(tmp_path)
    _fake_argv(hr, monkeypatch, _fake_claude(tmp_path, [_init(), _result_ok()]))
    record = hr.start(project, "x")
    state = _wait_finished(hr, record)
    assert state["live"] is False
    record_with_dead_pid = dict(record, pid=999999)
    assert hr.status(record_with_dead_pid)["finished"] is True


def test_a_silent_run_is_eventually_reported_as_gone(tmp_path, monkeypatch):
    """Killed, or the machine slept: no result and nothing written for a long time."""
    hr = _load()
    project = _project(tmp_path)
    _fake_argv(hr, monkeypatch, _fake_claude(tmp_path, [_init()]))
    record = hr.start(project, "x")
    import time as _t
    _t.sleep(0.6)
    assert hr.status(record)["live"] is True
    monkeypatch.setattr(hr, "_STALE_AFTER", 0.0)
    state = hr.status(record)
    assert state["live"] is False
    assert "gone" in state["outcome"]


def test_runs_are_listed_newest_first_and_filtered_by_engagement(tmp_path, monkeypatch):
    hr = _load()
    project = _project(tmp_path)
    _fake_argv(hr, monkeypatch, _fake_claude(tmp_path, [_init()]))
    first = hr.start(project, "x", slug="alpha")
    import time as _t
    _t.sleep(0.05)
    second = hr.start(project, "y", slug="beta")
    assert hr.latest(project)["session_id"] == second["session_id"]
    assert hr.latest(project, slug="alpha")["session_id"] == first["session_id"]
    assert hr.latest(project, slug="nothing-here") is None


def test_stopping_something_already_gone_is_not_an_error(tmp_path):
    hr = _load()
    assert hr.stop({"pid": None}) is False
    assert hr.stop_and_wait({"pid": None}, timeout=0.1) is True


def test_is_alive_treats_unknown_as_alive():
    """Only ever used to decide whether to ESCALATE a stop. Guessing "dead" there would leave
    a real process running while reporting it handled."""
    hr = _load()
    assert hr.is_alive(999999) is False
    assert hr.is_alive(os.getpid()) is True
    assert hr.is_alive("not a pid") is False


def test_a_stop_waits_for_the_process_to_actually_go(tmp_path, monkeypatch):
    """Measured live: the CLI ends its turn and writes a result promptly, then takes
    appreciably longer to exit - about a minute in one case. Checking at six seconds said
    "still alive", which would lead someone to escalate needlessly or to conclude that
    stopping does not work at all."""
    source = (REPO_ROOT / "scripts" / "headless_run.py").read_text(encoding="utf-8")
    body = source.split("def stop_and_wait", 1)[1].split("\ndef ", 1)[0]
    assert "hard=True" in body, "it must escalate to SIGTERM"
    assert "is_alive" in body, "and confirm the process actually went"



# --- the launcher's headless path (2026-08-25) ----------------------------------------------


def _launcher():
    if str(REPO_ROOT / "scripts") not in sys.path:
        sys.path.insert(0, str(REPO_ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location(
        "virt_team_launcher", REPO_ROOT / "scripts" / "virt_team_launcher.py"
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["virt_team_launcher"] = mod
    spec.loader.exec_module(mod)
    return mod


def _pending(tmp_path: Path, **over) -> dict:
    payload = {"ref": "x", "slug": "alpha", "auto": True, "run_mode": "headless",
               "engagement_usd": 35, "on_budget": "stop", "hard_cap_usd": 35,
               "session_id": SESSION}
    payload.update(over)
    (tmp_path / ".claude").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".claude" / ".auto-pending.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )
    return payload


def test_a_headless_run_uses_the_session_id_chosen_before_it_started(tmp_path, monkeypatch):
    """The correlation problem solved by construction. The launcher picks the UUID, the pack
    records it, and the CLI is told to use it - nothing is matched afterwards by date or by
    whichever transcript was touched last."""
    hr = _load()
    launcher = _launcher()
    project = _project(tmp_path)
    seen = {}
    monkeypatch.setattr(
        launcher, "_configured_launch_command", lambda: "claude", raising=False
    )
    monkeypatch.setattr(launcher, "_watch_after_launch", lambda p, s: None)
    monkeypatch.setattr(hr, "start", lambda *a, **k: seen.update(k) or {
        "session_id": k.get("session_id") or "generated"})
    monkeypatch.setitem(sys.modules, "headless_run", hr)
    assert launcher._start_headless(project, "/engage --new --auto", _pending(tmp_path)) is True
    assert seen["session_id"] == SESSION
    assert seen["budget_usd"] == 35.0, "the ENFORCED cap is what reaches --max-budget-usd"
    assert seen["slug"] == "alpha"


def test_only_the_enforced_cap_becomes_a_budget_flag(tmp_path, monkeypatch):
    """An advisory ceiling must NOT be passed as --max-budget-usd: that would silently turn
    a threshold into a wall, which is the opposite of what the human chose."""
    hr = _load()
    launcher = _launcher()
    project = _project(tmp_path)
    seen = {}
    monkeypatch.setattr(launcher, "_configured_launch_command", lambda: "claude", raising=False)
    monkeypatch.setattr(launcher, "_watch_after_launch", lambda p, s: None)
    monkeypatch.setattr(hr, "start", lambda *a, **k: seen.update(k) or {"session_id": "s"})
    monkeypatch.setitem(sys.modules, "headless_run", hr)
    advisory = _pending(tmp_path, on_budget="continue", hard_cap_usd=None)
    launcher._start_headless(project, "/engage --new --auto", advisory)
    assert seen["budget_usd"] is None


def test_a_headless_start_that_fails_falls_back_rather_than_losing_the_run(
    tmp_path, monkeypatch, capsys
):
    """The human authorised this run at the pre-flight. A launcher that quietly declined to
    start it is the worst outcome available, and one this repo has already shipped once."""
    hr = _load()
    launcher = _launcher()
    project = _project(tmp_path)

    def _boom(*a, **k):
        raise OSError("no claude here")

    monkeypatch.setattr(launcher, "_configured_launch_command", lambda: "claude", raising=False)
    monkeypatch.setattr(hr, "start", _boom)
    monkeypatch.setitem(sys.modules, "headless_run", hr)
    assert launcher._start_headless(project, "/engage --new --auto", _pending(tmp_path)) is False
    assert "opening a session instead" in capsys.readouterr().err


def test_a_windowed_run_never_takes_the_headless_path(tmp_path, monkeypatch):
    launcher = _launcher()
    project = _project(tmp_path)
    called = []
    monkeypatch.setattr(launcher, "_start_headless", lambda *a: called.append(a) or True)
    monkeypatch.setattr(launcher, "_launch_in_window", lambda *a: False)
    monkeypatch.setattr(launcher, "_new_window_wanted", lambda p: False)
    monkeypatch.setattr(launcher, "_resume_decision", lambda d: "/engage --new --auto")
    for name in ("_print_banner", "_check_plugin_cache_lag", "_print_project_defaults",
                 "_prewarm_guard_interpreter", "_write_probe_cache", "_refresh_tool_cache",
                 "_heal_stale_alias_once", "_clear_request_handoff"):
        if hasattr(launcher, name):
            monkeypatch.setattr(launcher, name, lambda *a, **k: None)
    _pending(tmp_path, run_mode="window")
    monkeypatch.chdir(project)
    assert launcher.main() == 0
    assert called == [], "window mode must not start a headless process"


def test_the_pack_records_the_session_and_the_two_budget_promises(tmp_path):
    """Verified end to end against the real init command: session id, run mode, the advisory
    ceiling and the enforced cap all land on the pack, and the one-shot handoff is consumed."""
    state = _load_state()
    project = _project(tmp_path)
    _pending(tmp_path)
    handoff = state._consume_auto_handoff(project)
    assert handoff["session_id"] == SESSION
    assert handoff["run_mode"] == "headless"
    assert handoff["hard_cap_usd"] == 35
    assert not (project / ".claude" / ".auto-pending.json").exists()


def _load_state():
    spec = importlib.util.spec_from_file_location(
        "engagement_state", REPO_ROOT / "scripts" / "engagement_state.py"
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["engagement_state"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_a_blocked_run_is_not_reported_as_a_clean_finish():
    """The false green this fix exists for. A run refused its tools comes back with
    is_error False and terminal_reason "completed" - it succeeded at doing nothing. The
    denials have to be surfaced, or "finished" and "was stopped from working" look
    identical."""
    hr = _load()
    blocked = dict(_result_ok())
    blocked["permission_denials"] = [
        {"tool_name": "Write", "tool_use_id": "t1"},
        {"tool_name": "Bash", "tool_use_id": "t2"},
    ]
    state = hr.read_stream(_lines(_init(), blocked))
    assert state["denials"] == ["Write", "Bash"]
    summary = hr.summary(state)
    assert "BLOCKED" in summary and "2 tool call(s) refused" in summary


def test_a_clean_run_says_nothing_about_denials():
    hr = _load()
    state = hr.read_stream(_lines(_init(), _result_ok()))
    assert state["denials"] == []
    assert "BLOCKED" not in hr.summary(state)


def test_the_launcher_passes_the_teams_own_tool_rules(tmp_path, monkeypatch):
    """acceptEdits covers file writes and ordinary filesystem commands, not `python -m
    scripts.render_html`. The team's tooling needs the same Bash rules the installer already
    merges into a project's settings - so an unattended run may do exactly what an attended
    one was already permitted to, and no more."""
    hr = _load()
    launcher = _launcher()
    project = _project(tmp_path)
    seen = {}
    monkeypatch.setattr(launcher, "_configured_launch_command", lambda: "claude", raising=False)
    monkeypatch.setattr(launcher, "_watch_after_launch", lambda p, s: None)
    monkeypatch.setattr(hr, "start", lambda *a, **k: seen.update(k) or {"session_id": "s"})
    monkeypatch.setitem(sys.modules, "headless_run", hr)
    launcher._start_headless(project, "/engage --new --auto", _pending(tmp_path))

    import install_helper

    assert seen["allowed_tools"] == tuple(install_helper.RECOMMENDED_ALLOW)
    assert any("scripts" in rule for rule in seen["allowed_tools"])
