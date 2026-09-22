"""Behaviour tests for the "this looks ready to close" Stop-hook nudge
(scripts/engagement_readiness_nudge.py, 2026-09-22).

dod_stop_gate.py already runs the mechanical DoD check at every turn-end while an
engagement is open, but it only ever speaks when it finds a defect - a long-running,
fully-clean engagement produces total silence forever, with nothing ever suggesting the
engagement IS done. This hook closes that specific gap: one-time, self-suppressing, and
requires three independent signals (delivery/close phase, empty outstanding list, a clean
check_artifacts pass) before it says anything."""

from __future__ import annotations

import io
import json
from pathlib import Path

import scripts.engagement_readiness_nudge as nudge
from scripts.engagement_state import main as es_main

_SID = "sess-live-suite"


def _run_bare(monkeypatch, capsys, payload: dict):
    capsys.readouterr()  # drain any setup noise (e.g. engagement_state's own "wrote ..." prints)
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    rc = nudge.main()
    return rc, capsys.readouterr().out


def _run(monkeypatch, capsys, payload: dict):
    payload.setdefault("session_id", _SID)
    cwd = payload.get("cwd")
    if cwd:
        art = Path(cwd) / "artifacts"
        if art.is_dir():
            (art / ".team-session.json").write_text(
                json.dumps({"session_id": _SID}), encoding="utf-8"
            )
    return _run_bare(monkeypatch, capsys, payload)


def _clean_pack(art: Path, phase: str | None = None, status: str | None = None) -> None:
    """A fully valid, check()-clean pack via the real CLI (a hand-built state dict is
    missing schema fields check_state() validates - engagement_state.init is the only
    reliable way to get one). Writes the brief so the index has something listed."""
    assert es_main(["--dir", str(art), "init", "--title", "T", "--slug", "t"]) == 0
    (art / "engagement-brief.md").write_text("# Brief\n", encoding="utf-8")
    (art / "engagement-brief.html").write_text("x", encoding="utf-8")
    assert (
        es_main(
            [
                "--dir",
                str(art),
                "add-artifact",
                "engagement-brief.md",
                "--title",
                "Brief",
            ]
        )
        == 0
    )
    # init seeds two default outstanding items ("independent QA", "DoD check_artifacts") -
    # clear both so a "phase reached, nothing outstanding" test fixture is actually clean,
    # not accidentally still carrying init's own defaults.
    assert es_main(["--dir", str(art), "resolve-outstanding", "independent QA"]) == 0
    assert es_main(["--dir", str(art), "resolve-outstanding", "DoD check_artifacts"]) == 0
    if phase:
        assert es_main(["--dir", str(art), "set-phase", phase]) == 0
    if status == "blocked":
        # set-status blocked requires a non-empty outstanding list (a blocked engagement
        # must record what it's waiting on) - add one back just for this transition.
        assert es_main(["--dir", str(art), "add-outstanding", "waiting on the user"]) == 0
        assert es_main(["--dir", str(art), "set-status", "blocked"]) == 0
    elif status == "closing":
        assert es_main(["--dir", str(art), "set-status", "closing"]) == 0


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
    art = tmp_path / "artifacts"
    _clean_pack(art, phase="plan")
    rc, out = _run(monkeypatch, capsys, {"cwd": str(tmp_path)})
    assert rc == 0 and out == ""


def test_outstanding_items_stay_silent(tmp_path, monkeypatch, capsys):
    art = tmp_path / "artifacts"
    _clean_pack(art, phase="delivery")
    assert es_main(["--dir", str(art), "add-outstanding", "waiting on the user"]) == 0
    rc, out = _run(monkeypatch, capsys, {"cwd": str(tmp_path)})
    assert rc == 0 and out == ""


def test_dirty_pack_stays_silent(tmp_path, monkeypatch, capsys):
    """A real DoD finding (here: an unlisted artifact -> STALE-INDEX) means NOT ready,
    even at delivery phase with nothing outstanding - dod_stop_gate.py owns that signal."""
    art = tmp_path / "artifacts"
    _clean_pack(art, phase="delivery")
    (art / "stray.md").write_text("# Stray\n", encoding="utf-8")  # not listed in the index
    rc, out = _run(monkeypatch, capsys, {"cwd": str(tmp_path)})
    assert rc == 0 and out == ""


def test_clean_delivery_phase_nudges(tmp_path, monkeypatch, capsys):
    art = tmp_path / "artifacts"
    _clean_pack(art, phase="delivery")
    rc, out = _run(monkeypatch, capsys, {"cwd": str(tmp_path)})
    assert rc == 0
    data = json.loads(out)
    assert data["decision"] == "block"
    assert "ready to close" in data["reason"].lower()
    assert "readiness-nudged" in data["reason"]


def test_clean_close_phase_nudges_too(tmp_path, monkeypatch, capsys):
    art = tmp_path / "artifacts"
    _clean_pack(art, phase="close")
    rc, out = _run(monkeypatch, capsys, {"cwd": str(tmp_path)})
    data = json.loads(out)
    assert data["decision"] == "block"


def test_marker_logged_self_suppresses(tmp_path, monkeypatch, capsys):
    art = tmp_path / "artifacts"
    _clean_pack(art, phase="delivery")
    assert es_main(["--dir", str(art), "log-note", "readiness-nudged"]) == 0
    rc, out = _run(monkeypatch, capsys, {"cwd": str(tmp_path)})
    assert rc == 0 and out == ""


def test_closing_status_is_silent(tmp_path, monkeypatch, capsys):
    """A close already under way needs no nudge to start one."""
    art = tmp_path / "artifacts"
    _clean_pack(art, phase="delivery", status="closing")
    rc, out = _run(monkeypatch, capsys, {"cwd": str(tmp_path)})
    assert rc == 0 and out == ""


def test_blocked_status_is_silent(tmp_path, monkeypatch, capsys):
    """A paused engagement is truthfully parked - nudging 'looks done' there would be
    confusing, not helpful."""
    art = tmp_path / "artifacts"
    _clean_pack(art, phase="delivery", status="blocked")
    rc, out = _run(monkeypatch, capsys, {"cwd": str(tmp_path)})
    assert rc == 0 and out == ""


def test_unreadable_state_fails_open(tmp_path, monkeypatch, capsys):
    art = tmp_path / "artifacts"
    _clean_pack(art, phase="delivery")
    (art / "engagement-state.json").write_text("not json", encoding="utf-8")
    rc, out = _run(monkeypatch, capsys, {"cwd": str(tmp_path)})
    assert rc == 0 and out == ""


def test_garbage_stdin_never_crashes(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO("not json"))
    assert nudge.main() == 0


def test_wrong_session_stays_silent(tmp_path, monkeypatch, capsys):
    """A pack driven by another session must not nudge a session that never drove it."""
    art = tmp_path / "artifacts"
    _clean_pack(art, phase="delivery")
    (art / ".team-session.json").write_text(
        json.dumps({"session_id": "someone-else"}), encoding="utf-8"
    )
    rc, out = _run_bare(monkeypatch, capsys, {"cwd": str(tmp_path), "session_id": _SID})
    assert rc == 0 and out == ""
