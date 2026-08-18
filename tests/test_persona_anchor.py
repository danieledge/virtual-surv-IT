"""Persona re-anchor hook (scripts/persona_anchor.py, ADR-005): fires only while an engagement
is live (open/blocked START-HERE), silent when dormant or closed, and stays tiny."""

from __future__ import annotations

import io
import json
from pathlib import Path

import scripts.persona_anchor as pa


def _run_bare(monkeypatch, capsys, payload: dict):
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    rc = pa.main()
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
            (art / ".team-session.json").write_text(
                json.dumps({"session": _SID}), encoding="utf-8"
            )
    return run_fn(monkeypatch, capsys, payload)


def _run(monkeypatch, capsys, payload: dict):
    return _stamped_run(_run_bare, monkeypatch, capsys, payload)


def test_dormant_no_start_here_is_silent(tmp_path, monkeypatch, capsys):
    rc, out = _run(monkeypatch, capsys, {"cwd": str(tmp_path)})
    assert rc == 0 and out == ""


def test_open_engagement_anchors(tmp_path, monkeypatch, capsys):
    art = tmp_path / "artifacts"
    art.mkdir()
    (art / "START-HERE.md").write_text("Status: ⏳ in progress\n", encoding="utf-8")
    rc, out = _run(monkeypatch, capsys, {"cwd": str(tmp_path)})
    assert rc == 0
    assert "persona-anchor" in out and "Morgan" in out and "AskUserQuestion" in out


def test_blocked_engagement_anchors(tmp_path, monkeypatch, capsys):
    art = tmp_path / "artifacts"
    art.mkdir()
    (art / "START-HERE.md").write_text("Status: ⛔ blocked - awaiting input\n", encoding="utf-8")
    _, out = _run(monkeypatch, capsys, {"cwd": str(tmp_path)})
    assert "persona-anchor" in out


def test_closed_engagement_is_silent(tmp_path, monkeypatch, capsys):
    art = tmp_path / "artifacts"
    art.mkdir()
    (art / "START-HERE.md").write_text("Status: ✅ closed\n", encoding="utf-8")
    _, out = _run(monkeypatch, capsys, {"cwd": str(tmp_path)})
    assert out == ""


def test_bad_stdin_fails_open(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO("not json"))
    assert pa.main() == 0
    assert capsys.readouterr().out == ""


def test_short_anchor_stays_tiny():
    # The design constraint: the STEADY-STATE per-turn injection (2026-08-03 shrink -
    # _ANCHOR_SHORT fires on every prompt once seeded) must be pointers, not a rules reload.
    assert len(pa._ANCHOR_SHORT.splitlines()) <= 8
    assert len(pa._ANCHOR_SHORT) < 500


def test_full_anchor_stays_bounded():
    # _ANCHOR fires only ONCE per engagement (before the seeded marker downgrades later
    # turns to the short form) - generous but still bounded, not an unchecked rules reload.
    assert len(pa._ANCHOR.splitlines()) <= 20
    assert len(pa._ANCHOR) < 1500


# --------------------------------------------- machine-readable state first (ADR-006)


def _state(art, status):
    art.mkdir(exist_ok=True)
    (art / "engagement-state.json").write_text(
        json.dumps({"schema": 1, "status": status}), encoding="utf-8"
    )


def test_state_open_anchors_even_without_render(tmp_path, monkeypatch, capsys):
    _state(tmp_path / "artifacts", "in_progress")
    _, out = _run(monkeypatch, capsys, {"cwd": str(tmp_path)})
    assert "persona-anchor" in out


def test_state_closed_wins_over_stale_open_render(tmp_path, monkeypatch, capsys):
    art = tmp_path / "artifacts"
    _state(art, "closed")
    (art / "START-HERE.md").write_text("Status: ⏳ in progress\n", encoding="utf-8")
    _, out = _run(monkeypatch, capsys, {"cwd": str(tmp_path)})
    assert out == ""  # the state is authoritative


def test_invalid_state_falls_back_to_emoji_sniff(tmp_path, monkeypatch, capsys):
    art = tmp_path / "artifacts"
    art.mkdir()
    (art / "engagement-state.json").write_text("{broken", encoding="utf-8")
    (art / "START-HERE.md").write_text("Status: ⛔ blocked\n", encoding="utf-8")
    _, out = _run(monkeypatch, capsys, {"cwd": str(tmp_path)})
    assert "persona-anchor" in out


def test_multi_workspace_anchor_lists_open_engagements(tmp_path, monkeypatch, capsys):
    art = tmp_path / "artifacts"
    for slug, status in (("audit", "blocked"), ("scoping", "in_progress")):
        (art / slug).mkdir(parents=True)
        (art / slug / "engagement-state.json").write_text(
            json.dumps({"schema": 2, "status": status}), encoding="utf-8"
        )
    _, out = _run(monkeypatch, capsys, {"cwd": str(tmp_path)})
    assert "persona-anchor" in out
    assert "audit ⛔" in out and "scoping ⏳" in out and "ACTIVE" in out


def test_all_workspaces_closed_is_silent(tmp_path, monkeypatch, capsys):
    art = tmp_path / "artifacts"
    (art / "done").mkdir(parents=True)
    (art / "done" / "engagement-state.json").write_text(
        json.dumps({"schema": 2, "status": "closed"}), encoding="utf-8"
    )
    _, out = _run(monkeypatch, capsys, {"cwd": str(tmp_path)})
    assert out == ""


def test_load_checker_does_not_grow_sys_path_on_repeat_calls(tmp_path, monkeypatch):
    """2026-08-14 daemon-safety fix: this hook used to run once per prompt in its own
    fresh process, where an unconditional sys.path.insert was harmless (it died with
    the process every time). Serving it from a long-lived daemon changes that -
    without the dedup, every call would grow sys.path by one more entry for the same
    project_root. Calling _load_checker twice with the SAME project_root must not
    add a second entry."""
    import sys

    project_root = tmp_path
    before = list(sys.path)
    pa._load_checker(project_root)
    after_first = list(sys.path)
    pa._load_checker(project_root)
    after_second = list(sys.path)

    added_by_first = [p for p in after_first if p not in before]
    assert len(added_by_first) <= 1  # at most the one, deliberate insert
    assert after_second == after_first, (
        "a second call with the same project_root grew sys.path again - the dedup "
        "check did not hold"
    )
