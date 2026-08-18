"""The acting-session stamp (artifacts/.team-session.json) behind hook dormancy scoping.

Live report (2026-08-16): a pure-dormant "hello" session in a project holding another
session's leftover OPEN engagement got the DoD stop gate's full fix-list and was pulled
into working that engagement - the engagement-scoped hooks keyed on disk state alone, so
one abandoned pack gated every later session in the project. The fix has two halves:

  * engagement_state stamps the calling session's id (CLAUDE_CODE_SESSION_ID, exposed by
    Claude Code to Bash tool commands) into artifacts/.team-session.json on every
    mutating command plus set-active - THIS file's subject;
  * the staged hooks (dod_stop_gate, persona_anchor, todo_panel_nudge) arm only when
    their payload's session_id matches the stamp - pinned in the staged-hook test files.

User decision on the fail direction: fully silent. A missing stamp or a mismatch means
dormant; open engagements still surface at the front doors (the /engage resume menu,
virt-surv go, the statusline).
"""

from __future__ import annotations

from pathlib import Path

from scripts.engagement_state import (
    TEAM_SESSION_MARKER,
    main as es_main,
    read_team_session,
    stamp_team_session,
)

_SID = "sess-abc123"


def _init(art: Path, slug: str) -> Path:
    assert es_main(["--dir", str(art / slug), "init", "--title", slug, "--slug", slug]) == 0
    return art / slug


def test_mutating_command_stamps_the_calling_session(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", _SID)
    art = tmp_path / "artifacts"
    _init(art, "one")
    assert read_team_session(art) == _SID


def test_workspace_mutation_stamps_at_the_artifacts_root_not_the_pack(tmp_path, monkeypatch):
    """The hooks read project_root/artifacts/.team-session.json - a stamp inside the
    workspace subfolder would never be seen."""
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", _SID)
    art = tmp_path / "artifacts"
    ws = _init(art, "one")
    assert es_main(["--dir", str(ws), "set-phase", "delivery"]) == 0
    assert (art / TEAM_SESSION_MARKER).is_file()
    assert not (ws / TEAM_SESSION_MARKER).exists()


def test_set_active_stamps_too(tmp_path, monkeypatch):
    """set-active is how a RESUMED session claims its workspace - it must count as the
    session engaging, or a resume that mutates nothing else stays wrongly dormant."""
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", _SID)
    art = tmp_path / "artifacts"
    _init(art, "one")
    (art / TEAM_SESSION_MARKER).unlink()
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sess-resumer")
    monkeypatch.chdir(tmp_path)
    assert es_main(["set-active", "one"]) == 0
    assert read_team_session(art) == "sess-resumer"


def test_no_env_var_leaves_an_existing_stamp_untouched(tmp_path, monkeypatch):
    """A human running the CLI from a plain terminal (or an older Claude Code with no
    session env var) must neither claim the engaged-session slot nor clear it - session
    ids are unique, so a stale stamp can only ever match the session that wrote it."""
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", _SID)
    art = tmp_path / "artifacts"
    ws = _init(art, "one")
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID")
    assert es_main(["--dir", str(ws), "set-phase", "delivery"]) == 0
    assert read_team_session(art) == _SID  # untouched, not cleared or overwritten


def test_no_env_var_and_no_stamp_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    art = tmp_path / "artifacts"
    _init(art, "one")
    assert not (art / TEAM_SESSION_MARKER).exists()
    assert read_team_session(art) is None


def test_read_only_commands_do_not_stamp(tmp_path, monkeypatch):
    """A dormant session that merely INSPECTED state (list/show/validate) must stay
    dormant - only acting on the engagement layer claims the session."""
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    art = tmp_path / "artifacts"
    _init(art, "one")
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sess-onlooker")
    monkeypatch.chdir(tmp_path)
    assert es_main(["list"]) == 0
    assert es_main(["--slug", "one", "show"]) == 0
    assert read_team_session(art) is None


def test_unreadable_stamp_reads_as_none(tmp_path):
    art = tmp_path / "artifacts"
    art.mkdir()
    (art / TEAM_SESSION_MARKER).write_text("not json{{{", encoding="utf-8")
    assert read_team_session(art) is None


def test_stamp_helper_is_advisory_never_raises(tmp_path, monkeypatch):
    """A stamp failure must never fail the state mutation it rides on."""
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", _SID)
    blocker = tmp_path / "artifacts"
    blocker.write_text("a file where the directory should be", encoding="utf-8")
    stamp_team_session(blocker)  # mkdir/write fails inside - must not raise
