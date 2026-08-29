"""Behaviour tests for the task-panel Stop-hook nudge (scripts/todo_panel_nudge.py).

A live audit (2026-07-30) found ZERO genuine TodoWrite tool calls across every kept eval
transcript, despite the operating guide claiming delivery-phase engagements track gates
there. This hook cannot verify TodoWrite compliance (unobservable, model-only tool) - it
can only nudge once at the right structural moment (phase reaches delivery) and
self-suppress once Morgan logs the marker it asks for, without ever writing state itself.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import scripts.todo_panel_nudge as nudge


def _run_bare(monkeypatch, capsys, payload: dict):
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    rc = nudge.main()
    return rc, capsys.readouterr().out


# Session scoping (2026-08-16): the STAGED hook arms only when the payload's session_id
# matches the acting-session stamp in artifacts/.team-session.json. The live copy under
# test here ignores both until the staged fix is applied, so adding them now is inert -
# and it keeps this whole suite green the moment the human runs the apply script.
_SID = "sess-live-suite"


def _stamped_run(run_fn, monkeypatch, capsys, payload: dict):
    payload.setdefault("session_id", _SID)
    cwd = payload.get("cwd")
    if cwd:
        art = Path(cwd) / "artifacts"
        if art.is_dir():
            (art / ".team-session.json").write_text(json.dumps({"session": _SID}), encoding="utf-8")
    return run_fn(monkeypatch, capsys, payload)


def _run(monkeypatch, capsys, payload: dict):
    return _stamped_run(_run_bare, monkeypatch, capsys, payload)


def _state(phase="delivery", status="in_progress", log=None):
    return {"schema": 2, "status": status, "phase": phase, "log": log or []}


def test_stop_hook_active_is_noop(monkeypatch, capsys):
    rc, out = _run(monkeypatch, capsys, {"stop_hook_active": True})
    assert rc == 0
    assert out == ""


def test_no_artifacts_dir_is_silent(tmp_path, monkeypatch, capsys):
    rc, out = _run(monkeypatch, capsys, {"cwd": str(tmp_path)})
    assert rc == 0 and out == ""


def test_no_engagement_state_is_silent(tmp_path, monkeypatch, capsys):
    (tmp_path / "artifacts").mkdir()
    rc, out = _run(monkeypatch, capsys, {"cwd": str(tmp_path)})
    assert rc == 0 and out == ""


def test_early_phase_is_silent(tmp_path, monkeypatch, capsys):
    """'open'/'classify'/'plan' - the plan isn't agreed yet, nothing to seed."""
    art = tmp_path / "artifacts"
    art.mkdir()
    (art / "engagement-state.json").write_text(json.dumps(_state(phase="plan")), encoding="utf-8")
    rc, out = _run(monkeypatch, capsys, {"cwd": str(tmp_path)})
    assert rc == 0 and out == ""


def test_delivery_phase_nudges(tmp_path, monkeypatch, capsys):
    art = tmp_path / "artifacts"
    art.mkdir()
    (art / "engagement-state.json").write_text(
        json.dumps(_state(phase="delivery")), encoding="utf-8"
    )
    rc, out = _run(monkeypatch, capsys, {"cwd": str(tmp_path)})
    assert rc == 0
    data = json.loads(out)
    assert data["decision"] == "block"
    assert "task-list" in data["reason"] or "todo" in data["reason"].lower()


def test_close_phase_still_nudges_if_never_seeded(tmp_path, monkeypatch, capsys):
    """Even at close, if the marker was never logged, still nudge - better late than
    the panel having never appeared at all."""
    art = tmp_path / "artifacts"
    art.mkdir()
    (art / "engagement-state.json").write_text(
        json.dumps(_state(phase="close", status="closing")), encoding="utf-8"
    )
    rc, out = _run(monkeypatch, capsys, {"cwd": str(tmp_path)})
    data = json.loads(out)
    assert data["decision"] == "block"


def test_marker_logged_self_suppresses(tmp_path, monkeypatch, capsys):
    """The self-suppression mechanism: once Morgan logs the marker the nudge asks for,
    silent for the rest of the engagement - without the hook ever writing state."""
    art = tmp_path / "artifacts"
    art.mkdir()
    (art / "engagement-state.json").write_text(
        json.dumps(_state(phase="delivery", log=["2026-07-30: todo-panel-seeded"])),
        encoding="utf-8",
    )
    rc, out = _run(monkeypatch, capsys, {"cwd": str(tmp_path)})
    assert rc == 0 and out == ""


def test_marker_logged_stays_silent_through_close(tmp_path, monkeypatch, capsys):
    art = tmp_path / "artifacts"
    art.mkdir()
    (art / "engagement-state.json").write_text(
        json.dumps(_state(phase="close", status="closing", log=["todo-panel-seeded"])),
        encoding="utf-8",
    )
    rc, out = _run(monkeypatch, capsys, {"cwd": str(tmp_path)})
    assert rc == 0 and out == ""


def test_closed_pack_is_silent(tmp_path, monkeypatch, capsys):
    """A ✅ closed pack is no longer gated at all - matches dod_stop_gate.py's semantics."""
    art = tmp_path / "artifacts"
    art.mkdir()
    (art / "engagement-state.json").write_text(
        json.dumps(_state(phase="close", status="closed")), encoding="utf-8"
    )
    rc, out = _run(monkeypatch, capsys, {"cwd": str(tmp_path)})
    assert rc == 0 and out == ""


def test_workspace_blocked_is_silent(tmp_path, monkeypatch, capsys):
    """A ⛔ BLOCKED *workspace* is parked (dod_stop_gate.py's own semantics: workspaces
    gate only on open/closing) - inherited verbatim from the shared pack_status parser."""
    art = tmp_path / "artifacts" / "eng"
    art.mkdir(parents=True)
    (art / "engagement-state.json").write_text(
        json.dumps(_state(phase="delivery", status="blocked")), encoding="utf-8"
    )
    rc, out = _run(monkeypatch, capsys, {"cwd": str(tmp_path)})
    assert rc == 0 and out == ""


def test_flat_pack_blocked_still_nudges(tmp_path, monkeypatch, capsys):
    art = tmp_path / "artifacts"
    art.mkdir()
    (art / "engagement-state.json").write_text(
        json.dumps(_state(phase="delivery", status="blocked")), encoding="utf-8"
    )
    rc, out = _run(monkeypatch, capsys, {"cwd": str(tmp_path)})
    data = json.loads(out)
    assert data["decision"] == "block"


def test_unreadable_state_fails_open(tmp_path, monkeypatch, capsys):
    art = tmp_path / "artifacts"
    art.mkdir()
    (art / "engagement-state.json").write_text("{broken", encoding="utf-8")
    rc, out = _run(monkeypatch, capsys, {"cwd": str(tmp_path)})
    assert rc == 0 and out == ""


def test_garbage_stdin_never_crashes(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO("{not json"))
    rc = nudge.main()
    assert rc == 0


def test_staged_and_live_match_when_installed():
    """HARD FAILURE, never a skip - see tests/test_hooks_in_sync.py for why (audit 2026-08-01:
    a skipping sync test hid a live guard that was missing three allow-list entries)."""
    from pathlib import Path

    repo = Path(__file__).resolve().parents[1]
    live = repo / "scripts" / "todo_panel_nudge.py"
    staged = repo / "scripts" / "staged_hooks" / "todo_panel_nudge.py"
    assert live.is_file(), f"live hook missing at {live} - it is not installed"
    assert live.read_bytes() == staged.read_bytes(), (
        "staged todo-panel nudge not yet applied - run: bash scripts/apply-todo-panel-nudge.sh"
    )


def _load_staged_nudge():
    """Loads scripts/staged_hooks/todo_panel_nudge.py directly (importlib, by path)
    rather than importing scripts.todo_panel_nudge - the M3 fix below is staged, not
    yet human-applied to the live copy (test_staged_and_live_match_when_installed
    above correctly flags that as pending), so testing the live import would test
    unfixed code. Same pattern as test_dod_stop_gate.py's own _load_staged_gate()."""
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "scripts" / "staged_hooks" / "todo_panel_nudge.py"
    spec = importlib.util.spec_from_file_location("staged_todo_panel_nudge", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_load_checker_does_not_grow_sys_path_on_repeat_calls(tmp_path):
    """M3 (2026-08-14 daemon-safety audit): same bug class already fixed in
    persona_anchor.py's own _load_checker, missed here (and in dod_stop_gate.py,
    covered by its own identical test) - this hook is re-exec'd fresh per Stop event
    INSIDE the daemon when daemon-served, so an unconditional sys.path.insert would
    grow the daemon's process-global sys.path without bound over its life. Calling
    _load_checker twice with the SAME project_root must not add a second entry."""
    import sys

    staged = _load_staged_nudge()
    project_root = tmp_path
    before = list(sys.path)
    staged._load_checker(project_root)
    after_first = list(sys.path)
    staged._load_checker(project_root)
    after_second = list(sys.path)

    added_by_first = [p for p in after_first if p not in before]
    assert len(added_by_first) <= 1  # at most the one, deliberate insert
    assert after_second == after_first, (
        "a second call with the same project_root grew sys.path again - the dedup "
        "check did not hold"
    )
