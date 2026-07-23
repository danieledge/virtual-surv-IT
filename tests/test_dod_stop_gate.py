"""Behaviour tests for the warn-first DoD Stop-hook backstop (scripts/dod_stop_gate.py, finding #6).

Pins the four branches so the hook stays low-noise and loop-safe:
  * `stop_hook_active` -> no-op (never loops the model);
  * no living index -> silent (never nags legacy/dormant artifacts folders);
  * ✅ closed index -> silent;
  * ⏳/⛔ open index with a DoD finding -> exactly one `block` nudge.
"""

from __future__ import annotations

import io
import json

import scripts.dod_stop_gate as gate


def _run(monkeypatch, capsys, payload: dict):
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    rc = gate.main()
    return rc, capsys.readouterr().out


def test_stop_hook_active_is_noop(monkeypatch, capsys):
    rc, out = _run(monkeypatch, capsys, {"stop_hook_active": True})
    assert rc == 0
    assert out == ""


def test_no_start_here_is_silent(tmp_path, monkeypatch, capsys):
    (tmp_path / "artifacts").mkdir()
    rc, out = _run(monkeypatch, capsys, {"cwd": str(tmp_path)})
    assert rc == 0
    assert out == ""


def test_closed_engagement_is_silent(tmp_path, monkeypatch, capsys):
    art = tmp_path / "artifacts"
    art.mkdir()
    (art / "START-HERE.md").write_text("Status: ✅ closed\n", encoding="utf-8")
    rc, out = _run(monkeypatch, capsys, {"cwd": str(tmp_path)})
    assert rc == 0
    assert out == ""


def test_open_engagement_with_findings_nudges_once(tmp_path, monkeypatch, capsys):
    art = tmp_path / "artifacts"
    art.mkdir()
    (art / "START-HERE.md").write_text("Status: ⏳ in progress\n", encoding="utf-8")
    # A deliverable .md with no rendered .html sibling -> a MISSING-HTML finding from check_artifacts.
    (art / "review-pass-1.md").write_text("# interim\n", encoding="utf-8")

    rc, out = _run(monkeypatch, capsys, {"cwd": str(tmp_path)})
    assert rc == 0
    decision = json.loads(out)
    assert decision["decision"] == "block"
    assert "DoD backstop" in decision["reason"]


def test_open_but_clean_does_not_nudge(tmp_path, monkeypatch, capsys):
    art = tmp_path / "artifacts"
    art.mkdir()
    # Open engagement, but the only artifact is START-HERE itself with its .html sibling and it
    # lists itself - check_artifacts should be satisfied, so no nudge.
    (art / "START-HERE.md").write_text(
        "Status: ⏳ in progress\n\n- [START-HERE](START-HERE.md)\n", encoding="utf-8"
    )
    (art / "START-HERE.html").write_text("<p>ok</p>\n", encoding="utf-8")
    rc, out = _run(monkeypatch, capsys, {"cwd": str(tmp_path)})
    assert rc == 0
    # May legitimately be silent (clean) - assert we did not hard-error and produced no block.
    assert out == "" or json.loads(out).get("decision") != "block"
