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


# ============================== 2026-09-12 safety-hook audit: W-4 / H-13 (re-stamp on resume)
#
# A --resume or a compaction gives the continuing work a NEW session id, and both
# session-scoped gates key on the acting-session stamp. Without a re-stamp, resuming an
# engagement disarmed the execution gate and the consent guard's engaged tier for the rest of
# that engagement - the session that most needs them, having just lost its context.


def test_a_session_the_stamp_never_knew_is_not_armed_by_a_resume(tmp_path):
    """The first version stamped ANY resuming session while a pack was live, and a plain
    session that compacted in a project with an open engagement woke up with the execution
    gate armed against it (2026-09-12, the day it shipped). No stamp, or a stamp naming
    only other sessions: nothing is written."""
    mod = _load()
    engagements = tmp_path / "artifacts"
    engagements.mkdir()
    mod._restamp(engagements, "never-engaged")
    assert not (engagements / ".team-session.json").exists()
    (engagements / ".team-session.json").write_text(
        json.dumps({"session": "first", "stamped": "2026-09-12"}), encoding="utf-8"
    )
    mod._restamp(engagements, "never-engaged")
    data = json.loads((engagements / ".team-session.json").read_text(encoding="utf-8"))
    assert data == {"session": "first", "stamped": "2026-09-12"}


def test_a_resume_refreshes_a_session_the_stamp_knows_and_keeps_the_others(tmp_path):
    """Refresh, never replace: the resuming session moves to the newest slot with a fresh
    timestamp, and a second session engaged in the same project stays armed."""
    mod = _load()
    engagements = tmp_path / "artifacts"
    engagements.mkdir()
    (engagements / ".team-session.json").write_text(
        json.dumps(
            {
                "session": "first",
                "stamped": "2026-09-12",
                "sessions": [{"id": "second", "stamped_at": "2026-09-12T10:00:00"}],
            }
        ),
        encoding="utf-8",
    )
    mod._restamp(engagements, "first")
    data = json.loads((engagements / ".team-session.json").read_text(encoding="utf-8"))
    ids = [e["id"] for e in data["sessions"]]
    assert ids == ["second", "first"]
    assert data["session_id"] == "first"
    assert data["sessions"][-1]["stamped_at"] != ""


def test_the_stamped_session_list_is_capped(tmp_path):
    """An abandoned session id must not arm the gate forever, and the file must not grow."""
    mod = _load()
    engagements = tmp_path / "artifacts"
    engagements.mkdir()
    (engagements / ".team-session.json").write_text(
        json.dumps(
            {
                "session": "session-0",
                "sessions": [{"id": f"session-{i}", "stamped_at": ""} for i in range(20)],
            }
        ),
        encoding="utf-8",
    )
    mod._restamp(engagements, "session-3")
    data = json.loads((engagements / ".team-session.json").read_text(encoding="utf-8"))
    assert len(data["sessions"]) == mod._MAX_STAMPED_SESSIONS
    assert data["sessions"][-1]["id"] == "session-3"


def test_a_dormant_session_start_stamps_nothing(tmp_path, monkeypatch, capsys):
    """Dormancy-exact by construction: no live pack, no output AND no stamp."""
    (tmp_path / "artifacts").mkdir(parents=True)
    rc, out = _run(
        monkeypatch,
        capsys,
        {"source": "resume", "cwd": str(tmp_path), "session_id": "s1"},
        tmp_path,
    )
    assert rc == 0 and out == ""
    assert not (tmp_path / "artifacts" / ".team-session.json").exists()


def test_a_live_engagement_resume_arms_the_gates_for_the_new_session(tmp_path, monkeypatch, capsys):
    """The end-to-end shape of W-4: a resume into a live pack re-stamps, so the gates the
    engagement was running under are still armed for the session that continues it."""
    _ws(tmp_path, "audit")
    rc, out = _run(monkeypatch, capsys, {"source": "resume", "session_id": "resumed-1"}, tmp_path)
    assert rc == 0 and "engagement-resume-brief" in out
    data = json.loads((tmp_path / "artifacts" / ".team-session.json").read_text(encoding="utf-8"))
    assert data["session_id"] == "resumed-1"
