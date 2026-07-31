"""resume_menu() (scripts/engagement_state.py, `list --menu`): the engage skill's step 0b
resume-vs-new menu, computed rather than left for the model to re-derive from `list`'s
text output (audit finding #1, 2026-07-30). Two dated-today live defects motivated this:
a menu offering only one open engagement when several existed, and a session folding a
new engagement's artifacts into the wrong open pack."""

from __future__ import annotations

from scripts.engagement_state import main, resume_menu


def _init_workspaced(monkeypatch, project_dir, slug, title=None):
    """Real workspaced init (no --dir): this is the ONLY path that writes the ACTIVE
    marker, so resume_menu's default-tracking tests need it, not the flat --dir form
    most other tests use."""
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project_dir))
    assert main(["init", "--title", title or slug, "--slug", slug]) == 0


def test_empty_project_has_no_open_engagements_and_no_default(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    menu = resume_menu(tmp_path / "artifacts")
    assert menu == {"open": [], "shown": [], "more": 0, "archived": 0, "default": None}


def test_single_open_engagement_is_the_default(tmp_path, monkeypatch):
    _init_workspaced(monkeypatch, tmp_path, "only-one")
    menu = resume_menu(tmp_path / "artifacts")
    assert [r["slug"] for r in menu["shown"]] == ["only-one"]
    assert menu["default"] == "only-one"
    assert menu["more"] == 0


def test_default_follows_the_active_marker_not_just_recency(tmp_path, monkeypatch):
    """The live defect this closes: the menu/default must reflect which engagement is
    genuinely ACTIVE, not silently pick something else."""
    _init_workspaced(monkeypatch, tmp_path, "first")
    _init_workspaced(monkeypatch, tmp_path, "second")
    menu = resume_menu(tmp_path / "artifacts")
    assert menu["default"] == "second"  # the newest init is ACTIVE
    # explicit set-active on the OLDER one flips the default
    assert main(["set-active", "first"]) == 0
    menu = resume_menu(tmp_path / "artifacts")
    assert menu["default"] == "first"


def test_more_than_three_open_reports_the_overflow_count(tmp_path, monkeypatch):
    for i in range(5):
        _init_workspaced(monkeypatch, tmp_path, f"eng-{i}")
    menu = resume_menu(tmp_path / "artifacts")
    assert len(menu["open"]) == 5
    assert len(menu["shown"]) == 3
    assert menu["more"] == 2


def test_closed_engagement_excluded_from_open_list(tmp_path, monkeypatch):
    _init_workspaced(monkeypatch, tmp_path, "will-close")
    pack = tmp_path / "artifacts" / "will-close"
    (pack / "engagement-summary-will-close.txt").write_text(
        "Hi,\n\nDone.\n\n\U0001f916 Morgan\nPM & Orchestrator - Virtual Surveillance IT (AI agent)\n",
        encoding="utf-8",
    )
    assert (
        main(
            [
                "--dir",
                str(pack),
                "add-artifact",
                "engagement-summary-will-close.txt",
                "--title",
                "Email",
                "--final",
            ]
        )
        == 0
    )
    assert main(["--dir", str(pack), "set-team", "Ana (analysis)"]) == 0
    assert main(["--dir", str(pack), "finalise-artifacts"]) == 0
    assert main(["--dir", str(pack), "set-status", "closed", "--verdict", "done"]) == 0
    menu = resume_menu(tmp_path / "artifacts")
    assert menu["open"] == []
    assert menu["default"] is None


def test_archived_engagement_excluded_and_counted_separately(tmp_path, monkeypatch):
    _init_workspaced(monkeypatch, tmp_path, "keep-open")
    _init_workspaced(monkeypatch, tmp_path, "to-archive")
    assert main(["archive", "to-archive", "--force"]) == 0
    menu = resume_menu(tmp_path / "artifacts")
    assert [r["slug"] for r in menu["open"]] == ["keep-open"]
    assert menu["archived"] == 1


def test_cli_menu_flag_emits_valid_json(tmp_path, monkeypatch, capsys):
    import json

    _init_workspaced(monkeypatch, tmp_path, "solo")
    capsys.readouterr()  # drain init's own "wrote ..." lines first
    assert main(["list", "--menu"]) == 0
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["default"] == "solo"


def test_max_shown_is_configurable():
    """The question tool's own 4-option ceiling (leaving room for 'start new') is why
    this defaults to 3, not hardcoded - callers can ask for a different cap."""
    from pathlib import Path

    assert resume_menu(Path("/nonexistent"), max_shown=1)["shown"] == []
