"""Persona re-anchor hook (scripts/persona_anchor.py, ADR-005): fires only while an engagement
is live (open/blocked START-HERE), silent when dormant or closed, and stays tiny."""

from __future__ import annotations

import io
import json

import scripts.persona_anchor as pa


def _run(monkeypatch, capsys, payload: dict):
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    rc = pa.main()
    return rc, capsys.readouterr().out


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


def test_anchor_stays_tiny():
    # The design constraint: a per-turn injection must be pointers, not a rules reload.
    assert len(pa._ANCHOR.splitlines()) <= 12
    assert len(pa._ANCHOR) < 1200
