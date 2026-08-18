"""Staged project-root anchoring for the DoD stop gate and persona anchor
(scripts/staged_hooks/, human-installed via scripts/apply-project-anchor.sh).

Regression under test (2026-07-25): a shell cwd that wandered into a kept eval sandbox
(evals/runs/<ts>/<case>/sandbox, which legitimately contains its own open START-HERE) made
both hooks adopt that foreign engagement - the stop gate nudged about frozen evidence and the
persona anchor summoned Morgan into a session that never engaged the team. The staged copies
anchor on CLAUDE_PROJECT_DIR (the session's project root) instead of the hook-input cwd, so:

  * project root without an engagement + wandered cwd -> SILENT (the fix);
  * project root WITH a live engagement -> fires regardless of where cwd wandered;
  * no CLAUDE_PROJECT_DIR (older harness) -> falls back to cwd, byte-for-byte the old
    behaviour, so installing the patch can never widen the hooks' reach.

The eval-sandbox sessions themselves keep both hooks fully armed: there, CLAUDE_PROJECT_DIR
IS the sandbox, and the fidelity of the orchestration evals depends on that.
"""

from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load(name: str):
    spec = importlib.util.spec_from_file_location(
        f"staged_{name}", REPO_ROOT / "scripts" / "staged_hooks" / f"{name}.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# Session scoping (second regression pinned here, 2026-08-16 live report): a pure-dormant
# "hello" session in a project holding another session's leftover OPEN pack got the stop
# gate's full fix-list and a re-summoned Morgan - the hooks keyed on disk state alone.
# The staged copies arm only when the payload's session_id matches the acting-session
# stamp engagement_state writes to artifacts/.team-session.json; every ARMING fixture
# below therefore stamps the session, and the dormant-session tests pin the silence.
_SID = "sess-staged-anchor"


def _stamp(root: Path, sid: str = _SID) -> None:
    (root / "artifacts" / ".team-session.json").write_text(
        json.dumps({"session": sid}), encoding="utf-8"
    )


def _open_engagement(root: Path) -> None:
    art = root / "artifacts"
    art.mkdir(parents=True, exist_ok=True)
    (art / "START-HERE.md").write_text("Status: ⏳ in progress\n", encoding="utf-8")
    _stamp(root)


def _run_persona(monkeypatch, capsys, payload: dict, project: Path | None):
    pa = _load("persona_anchor")
    if project is None:
        monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    else:
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project))
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    rc = pa.main()
    return rc, capsys.readouterr().out


def test_persona_silent_when_cwd_wanders_into_foreign_engagement(tmp_path, monkeypatch, capsys):
    project = tmp_path / "project"
    project.mkdir()
    sandbox = tmp_path / "evals" / "runs" / "x" / "case" / "sandbox"
    _open_engagement(sandbox)
    rc, out = _run_persona(monkeypatch, capsys, {"session_id": _SID, "cwd": str(sandbox)}, project)
    assert rc == 0 and out == ""


def test_persona_fires_from_project_even_when_cwd_elsewhere(tmp_path, monkeypatch, capsys):
    project = tmp_path / "project"
    _open_engagement(project)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    rc, out = _run_persona(monkeypatch, capsys, {"session_id": _SID, "cwd": str(elsewhere)}, project)
    assert rc == 0 and "persona-anchor" in out


def test_persona_falls_back_to_cwd_without_project_env(tmp_path, monkeypatch, capsys):
    _open_engagement(tmp_path)
    rc, out = _run_persona(monkeypatch, capsys, {"session_id": _SID, "cwd": str(tmp_path)}, None)
    assert rc == 0 and "persona-anchor" in out


def test_stop_gate_silent_when_cwd_wanders_into_foreign_engagement(tmp_path, monkeypatch, capsys):
    gate = _load("dod_stop_gate")
    project = tmp_path / "project"
    project.mkdir()
    sandbox = tmp_path / "evals" / "runs" / "x" / "case" / "sandbox"
    _open_engagement(sandbox)
    # The sandbox even carries a flaggable defect - the gate must not look at it at all.
    (sandbox / "artifacts" / "review-pass-1.md").write_text("# interim\n", encoding="utf-8")
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project))
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"session_id": _SID, "cwd": str(sandbox)})))
    assert gate.main() == 0
    assert capsys.readouterr().out == ""


def test_stop_gate_fires_on_project_engagement_when_cwd_elsewhere(tmp_path, monkeypatch, capsys):
    gate = _load("dod_stop_gate")
    project = tmp_path / "project"
    _open_engagement(project)
    # A deliverable .md with no .html sibling -> MISSING-HTML -> the gate nudges.
    (project / "artifacts" / "review-pass-1.md").write_text("# interim\n", encoding="utf-8")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project))
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"session_id": _SID, "cwd": str(elsewhere)})))
    rc = gate.main()
    out = capsys.readouterr().out
    assert rc == 0
    decision = json.loads(out)
    assert decision["decision"] == "block" and "DoD backstop" in decision["reason"]


# --- session scoping: a session that never engaged stays genuinely dormant ----------------


def test_persona_silent_in_session_that_never_engaged(tmp_path, monkeypatch, capsys):
    """The 2026-08-16 live report, persona half: an open pack left by ANOTHER session
    (stamp holds that session's id) must not re-summon Morgan into a fresh session."""
    _open_engagement(tmp_path)
    _stamp(tmp_path, sid="sess-somebody-else")
    rc, out = _run_persona(
        monkeypatch, capsys, {"session_id": "sess-hello-only", "cwd": str(tmp_path)}, tmp_path
    )
    assert rc == 0 and out == ""


def test_persona_silent_when_no_session_ever_stamped(tmp_path, monkeypatch, capsys):
    """No stamp at all (pack predates the fix, or was made outside Claude Code): fully
    silent, the user-chosen fail direction - the front doors surface open engagements."""
    _open_engagement(tmp_path)
    (tmp_path / "artifacts" / ".team-session.json").unlink()
    rc, out = _run_persona(
        monkeypatch, capsys, {"session_id": "sess-hello-only", "cwd": str(tmp_path)}, tmp_path
    )
    assert rc == 0 and out == ""


def test_stop_gate_silent_in_session_that_never_engaged(tmp_path, monkeypatch, capsys):
    """The 2026-08-16 live report itself: a pure "hello" session got the full DoD
    fix-list for another session's abandoned engagement and started working it."""
    gate = _load("dod_stop_gate")
    _open_engagement(tmp_path)
    (tmp_path / "artifacts" / "review-pass-1.md").write_text("# interim\n", encoding="utf-8")
    _stamp(tmp_path, sid="sess-somebody-else")
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    monkeypatch.setattr(
        "sys.stdin",
        io.StringIO(json.dumps({"session_id": "sess-hello-only", "cwd": str(tmp_path)})),
    )
    assert gate.main() == 0
    assert capsys.readouterr().out == ""


def test_stop_gate_silent_without_payload_session_id(tmp_path, monkeypatch, capsys):
    """No session_id in the hook payload (older Claude Code): silence, never a guess -
    arming requires a POSITIVE match, per the fully-dormant decision."""
    gate = _load("dod_stop_gate")
    _open_engagement(tmp_path)
    (tmp_path / "artifacts" / "review-pass-1.md").write_text("# interim\n", encoding="utf-8")
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"cwd": str(tmp_path)})))
    assert gate.main() == 0
    assert capsys.readouterr().out == ""
