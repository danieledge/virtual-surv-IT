"""The compaction/resume brief (scripts/staged_hooks/session_resume_brief.py, ADR-011,
human-installed via scripts/apply-session-brief.sh).

The seam it closes: right after a compaction or --resume, the model continues on a
summarised transcript with no instruction to re-read the disk state 0.33.0 made
authoritative. The brief points it at the state file and forbids re-asking recorded
answers. Dormancy-exact: zero output unless an engagement pack is live; fails open.
"""

from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location(
        "staged_session_brief", REPO_ROOT / "scripts" / "staged_hooks" / "session_resume_brief.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run(monkeypatch, capsys, payload: dict, project: Path) -> tuple[int, str]:
    mod = _load()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project))
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    rc = mod.main()
    return rc, capsys.readouterr().out


def _ws(project: Path, slug: str, status: str = "in_progress", phase: str = "delivery"):
    art = project / "artifacts" / slug
    art.mkdir(parents=True, exist_ok=True)
    (art / "engagement-state.json").write_text(
        json.dumps({"schema": 2, "status": status, "phase": phase}), encoding="utf-8"
    )


def test_dormant_session_gets_zero_context(tmp_path, monkeypatch, capsys):
    rc, out = _run(monkeypatch, capsys, {"source": "compact", "cwd": str(tmp_path)}, tmp_path)
    assert rc == 0 and out == ""


def test_closed_engagements_stay_silent(tmp_path, monkeypatch, capsys):
    _ws(tmp_path, "done", status="closed")
    rc, out = _run(monkeypatch, capsys, {"source": "compact"}, tmp_path)
    assert rc == 0 and out == ""


def test_startup_and_clear_sources_never_fire(tmp_path, monkeypatch, capsys):
    _ws(tmp_path, "audit")
    for source in ("startup", "clear", None):
        rc, out = _run(monkeypatch, capsys, {"source": source}, tmp_path)
        assert rc == 0 and out == "", source


def test_compact_mid_engagement_briefs_state_first(tmp_path, monkeypatch, capsys):
    _ws(tmp_path, "audit", status="closing", phase="close")
    rc, out = _run(monkeypatch, capsys, {"source": "compact"}, tmp_path)
    assert rc == 0
    assert "engagement-resume-brief" in out
    assert "audit" in out and "closing" in out and "close" in out
    assert "engagement-state.json" in out and "NOT re-asked" in out
    assert "declined" in out  # the consent ruling survives the compaction


def test_resume_picks_active_marker(tmp_path, monkeypatch, capsys):
    _ws(tmp_path, "audit")
    _ws(tmp_path, "scoping")
    (tmp_path / "artifacts" / ".active-engagement.json").write_text(
        json.dumps({"slug": "scoping"}), encoding="utf-8"
    )
    rc, out = _run(monkeypatch, capsys, {"source": "resume"}, tmp_path)
    assert "MID-ENGAGEMENT: scoping" in out
    assert "audit" in out  # named as parked


def test_legacy_flat_index_sniff_still_briefs(tmp_path, monkeypatch, capsys):
    art = tmp_path / "artifacts"
    art.mkdir()
    (art / "START-HERE.md").write_text("Status: ⏳ in progress\n", encoding="utf-8")
    rc, out = _run(monkeypatch, capsys, {"source": "compact"}, tmp_path)
    assert rc == 0 and "engagement-resume-brief" in out


def test_bad_stdin_fails_open(monkeypatch, capsys):
    mod = _load()
    monkeypatch.setattr("sys.stdin", io.StringIO("{broken"))
    assert mod.main() == 0
    assert capsys.readouterr().out == ""
