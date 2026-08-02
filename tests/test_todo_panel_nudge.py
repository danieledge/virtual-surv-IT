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

import scripts.todo_panel_nudge as nudge


def _run(monkeypatch, capsys, payload: dict):
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    rc = nudge.main()
    return rc, capsys.readouterr().out


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
