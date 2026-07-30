"""
Tests for the plugin install/update helper (install_helper.py, repo root).

Pure parts only: config round-trip, branch validation, mode auto-detection, dirty-tree
and ahead-commit detection with a mocked runner, step tracking and summary text, and
colour suppression under NO_COLOR / non-tty streams. No test touches the network, git,
pip or the claude CLI - every subprocess boundary is a fake runner or a monkeypatched
`run_cmd`.
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from install_helper import (
    InstallAbort,
    StepTracker,
    Style,
    commits_ahead,
    config_path,
    decide_mode,
    is_dirty,
    load_config,
    parse_args,
    save_config,
    supports_color,
    validate_branch,
)


def _proc(returncode: int = 0, stdout: str = "", stderr: str = "") -> SimpleNamespace:
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


# ------------------------------------------------------------------ config persistence


def test_config_round_trip(tmp_path):
    path = tmp_path / "installer.json"
    cfg = {"repo_path": "/somewhere/virtual-surv-IT", "branch": "dev"}
    save_config(path, cfg)
    assert load_config(path) == cfg


def test_save_config_creates_parent_dirs(tmp_path):
    path = tmp_path / "nested" / "deeper" / "installer.json"
    save_config(path, {"branch": "main"})
    assert json.loads(path.read_text(encoding="utf-8")) == {"branch": "main"}


def test_load_config_missing_file_is_empty(tmp_path):
    assert load_config(tmp_path / "absent.json") == {}


def test_load_config_corrupt_json_is_empty(tmp_path):
    path = tmp_path / "installer.json"
    path.write_text("{not json", encoding="utf-8")
    assert load_config(path) == {}


def test_load_config_non_dict_is_empty(tmp_path):
    path = tmp_path / "installer.json"
    path.write_text('["a", "list"]', encoding="utf-8")
    assert load_config(path) == {}


def test_config_path_honours_xdg(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert config_path() == tmp_path / "virt-surv-it" / "installer.json"


# ------------------------------------------------------------------ branch validation


def test_validate_branch_accepts_channels():
    assert validate_branch("main") == "main"
    assert validate_branch("dev") == "dev"


@pytest.mark.parametrize("bad", ["master", "Main", "feature/x", ""])
def test_validate_branch_rejects_everything_else(bad):
    with pytest.raises(ValueError):
        validate_branch(bad)


def test_parse_args_rejects_unknown_branch():
    with pytest.raises(SystemExit):
        parse_args(["--branch", "master"])


def test_parse_args_defaults():
    args = parse_args([])
    assert args.mode is None
    assert args.branch is None
    assert not args.yes and not args.pip


# ------------------------------------------------------------------ mode auto-detect


def test_decide_mode_explicit_wins(tmp_path):
    assert decide_mode("install", {"repo_path": str(tmp_path)}) == "install"
    assert decide_mode("update", {}) == "update"


def test_decide_mode_update_when_configured_clone_exists(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / ".claude-plugin").mkdir()
    (tmp_path / ".claude-plugin" / "plugin.json").write_text("{}", encoding="utf-8")
    assert decide_mode(None, {"repo_path": str(tmp_path)}) == "update"


def test_decide_mode_install_when_no_valid_clone(tmp_path):
    assert decide_mode(None, {}) == "install"
    assert decide_mode(None, {"repo_path": str(tmp_path / "gone")}) == "install"


# ------------------------------------------------------------------ git state via mocked runner


def test_is_dirty_true_on_porcelain_output():
    runner = lambda argv, **kw: _proc(stdout=" M scripts/foo.py\n?? notes.txt\n")  # noqa: E731
    assert is_dirty(Path("/repo"), runner=runner) is True


def test_is_dirty_false_on_clean_tree():
    runner = lambda argv, **kw: _proc(stdout="\n")  # noqa: E731
    assert is_dirty(Path("/repo"), runner=runner) is False


def test_is_dirty_raises_on_git_failure():
    runner = lambda argv, **kw: _proc(returncode=128, stderr="not a git repository")  # noqa: E731
    with pytest.raises(InstallAbort):
        is_dirty(Path("/repo"), runner=runner)


def test_commits_ahead_parses_count():
    runner = lambda argv, **kw: _proc(stdout="3\n")  # noqa: E731
    assert commits_ahead(Path("/repo"), "main", runner=runner) == 3


def test_commits_ahead_zero_on_lookup_failure():
    runner = lambda argv, **kw: _proc(returncode=1, stderr="unknown revision")  # noqa: E731
    assert commits_ahead(Path("/repo"), "dev", runner=runner) == 0


def test_is_dirty_asks_git_status_porcelain():
    seen = {}

    def runner(argv, **kw):
        seen["argv"] = [str(a) for a in argv]
        return _proc(stdout="")

    is_dirty(Path("/repo"), runner=runner)
    assert seen["argv"][:3] == ["git", "-C", "/repo"]
    assert "--porcelain" in seen["argv"]


# ------------------------------------------------------------------ step tracker + summary


def test_step_tracker_summary_lines_and_failed_flag():
    tracker = StepTracker()
    tracker.record("Preflight checks", "ok")
    tracker.record("Dev requirements", "skip", "pip not available")
    tracker.record("Add marketplace", "fail", "claude CLI missing")
    lines = tracker.summary_lines({"ok": "OK", "fail": "X", "skip": "~"})
    assert lines == [
        "  OK Preflight checks",
        "  ~ Dev requirements  (pip not available)",
        "  X Add marketplace  (claude CLI missing)",
    ]
    assert tracker.failed is True


def test_step_tracker_rejects_unknown_status():
    with pytest.raises(ValueError):
        StepTracker().record("step", "maybe")


def test_step_tracker_not_failed_without_fail_rows():
    tracker = StepTracker()
    tracker.record("a", "ok")
    tracker.record("b", "skip")
    assert tracker.failed is False


# ------------------------------------------------------------------ colour handling


class _Tty(io.StringIO):
    def isatty(self):
        return True


def test_no_color_env_disables_colour():
    assert supports_color(stream=_Tty(), env={"NO_COLOR": "1"}) is False


def test_non_tty_disables_colour():
    assert supports_color(stream=io.StringIO(), env={}) is False


def test_tty_without_no_color_enables_colour():
    assert supports_color(stream=_Tty(), env={}) is True


def test_dumb_terminal_disables_colour():
    assert supports_color(stream=_Tty(), env={"TERM": "dumb"}) is False


def test_style_disabled_returns_plain_text():
    style = Style(enabled=False)
    assert style.green("done") == "done"
    assert style.bold(style.red("x")) == "x"


def test_style_enabled_wraps_with_ansi():
    style = Style(enabled=True)
    assert style.green("done") == "\033[32mdone\033[0m"


# --- --permissions: opt-in, add-only allow-list merge (2026-07-30) ------------------------


def test_merge_allow_into_empty_settings():
    from install_helper import RECOMMENDED_ALLOW, merge_allow

    settings, added = merge_allow({})
    assert settings["permissions"]["allow"] == list(RECOMMENDED_ALLOW)
    assert added == list(RECOMMENDED_ALLOW)


def test_merge_allow_preserves_everything_and_dedupes():
    from install_helper import merge_allow

    existing = {
        "permissions": {
            "deny": ["Read(./secrets/**)"],
            "allow": ["Bash(ruff *)", "Bash(custom-tool *)"],
        },
        "hooks": {"Stop": [{"hooks": []}]},
    }
    settings, added = merge_allow(existing)
    assert settings["permissions"]["deny"] == ["Read(./secrets/**)"]  # untouched
    assert settings["hooks"] == {"Stop": [{"hooks": []}]}  # untouched
    allow = settings["permissions"]["allow"]
    assert allow[0] == "Bash(ruff *)" and allow[1] == "Bash(custom-tool *)"  # order kept
    assert "Bash(ruff *)" not in added  # already present -> not re-added
    assert len(allow) == 2 + len(added)


def test_run_permissions_creates_settings_when_absent(tmp_path, capsys):
    import json as _json

    from install_helper import Style, marks, run_permissions

    rc = run_permissions(tmp_path, Style(False), marks())
    assert rc == 0
    written = _json.loads((tmp_path / ".claude" / "settings.json").read_text(encoding="utf-8"))
    assert "Bash(ruff *)" in written["permissions"]["allow"]
    assert "backed up" not in capsys.readouterr().out  # nothing existed to back up


def test_run_permissions_backs_up_and_is_idempotent(tmp_path, capsys):
    import json as _json

    from install_helper import Style, marks, run_permissions

    claude = tmp_path / ".claude"
    claude.mkdir()
    (claude / "settings.json").write_text(
        '{"permissions": {"deny": ["Read(x)"]}}', encoding="utf-8"
    )
    assert run_permissions(tmp_path, Style(False), marks()) == 0
    out = capsys.readouterr().out
    assert "backed up" in out
    backups = list(claude.glob("settings.json.bak-*"))
    assert len(backups) == 1
    written = _json.loads((claude / "settings.json").read_text(encoding="utf-8"))
    assert written["permissions"]["deny"] == ["Read(x)"]  # preserved
    # Second run: nothing to add, no new backup.
    assert run_permissions(tmp_path, Style(False), marks()) == 0
    assert "already present" in capsys.readouterr().out
    assert len(list(claude.glob("settings.json.bak-*"))) == 1


def test_run_permissions_refuses_unparseable_settings(tmp_path, capsys):
    from install_helper import Style, marks, run_permissions

    claude = tmp_path / ".claude"
    claude.mkdir()
    (claude / "settings.json").write_text("{broken", encoding="utf-8")
    assert run_permissions(tmp_path, Style(False), marks()) == 1
    assert "refusing" in capsys.readouterr().out
    assert (claude / "settings.json").read_text(encoding="utf-8") == "{broken"  # untouched


# --- Windows .cmd shim launch (2026-07-30) ------------------------------------------------


def test_command_argv_routes_cmd_shims_through_shell():
    from install_helper import command_argv

    assert command_argv("claude", resolved=r"C:\Users\d\AppData\Roaming\npm\claude.CMD") == [
        "cmd",
        "/c",
        r"C:\Users\d\AppData\Roaming\npm\claude.CMD",
    ]
    assert command_argv("claude", resolved=r"C:\x\claude.bat")[0:2] == ["cmd", "/c"]


def test_command_argv_plain_executables_untouched():
    from install_helper import command_argv

    assert command_argv("git", resolved="/usr/bin/git") == ["/usr/bin/git"]
    assert command_argv("claude", resolved=r"C:\Program Files\claude\claude.exe") == [
        r"C:\Program Files\claude\claude.exe"
    ]


def test_command_argv_unresolved_falls_back_to_name(monkeypatch):
    import install_helper as ih

    monkeypatch.setattr(ih.shutil, "which", lambda _n: None)
    assert ih.command_argv("claude") == ["claude"]


# --- what's new after install/update (2026-07-30) -----------------------------------------


def test_installed_version_reads_manifest(tmp_path):
    from install_helper import installed_version

    plug = tmp_path / ".claude-plugin"
    plug.mkdir()
    (plug / "plugin.json").write_text('{"version": "0.33.1"}', encoding="utf-8")
    assert installed_version(tmp_path) == "0.33.1"
    assert installed_version(tmp_path / "nowhere") is None


def test_changelog_headline_extracts_the_entry_line(tmp_path):
    from install_helper import changelog_headline

    log = tmp_path / "CHANGELOG.md"
    log.write_text(
        "# Changelog\n\n## [0.33.1] - 2026-07-29 - Platform capability adoption\n\n"
        "### Added\n\n## [0.33.0] - 2026-07-29 - Workflow robustness\n",
        encoding="utf-8",
    )
    assert (
        changelog_headline(log, "0.33.1") == "[0.33.1] - 2026-07-29 - Platform capability adoption"
    )
    assert changelog_headline(log, "0.31.0") is None
    assert changelog_headline(tmp_path / "missing.md", "0.33.1") is None


# --- statusline wired by the helper (2026-07-30) ------------------------------------------


def test_merge_statusline_added_already_conflict(tmp_path):
    from install_helper import merge_statusline, statusline_command

    cmd = statusline_command(tmp_path)
    s, verdict = merge_statusline({}, cmd)
    assert verdict == "added" and s["statusLine"]["command"] == cmd
    s2, verdict = merge_statusline(s, cmd)
    assert verdict == "already"
    s3, verdict = merge_statusline({"statusLine": {"type": "command", "command": "other"}}, cmd)
    assert verdict == "conflict" and s3["statusLine"]["command"] == "other"  # untouched


def test_statusline_command_is_absolute(tmp_path):
    from install_helper import statusline_command

    cmd = statusline_command(tmp_path)
    assert "statusline.sh" in cmd and str(tmp_path.resolve()) in cmd


# --- per-project enablement wired into the helper (2026-07-30) ----------------------------


class _FakeProc:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


def test_run_enable_project_invokes_claude_in_project_cwd(tmp_path, capsys):
    from install_helper import PLUGIN_ID, Style, marks, run_enable_project

    calls = []

    def runner(argv, cwd=None, timeout=300):
        calls.append((argv, cwd))
        return _FakeProc(0)

    rc = run_enable_project(tmp_path, Style(False), marks(), runner=runner)
    assert rc == 0
    argv, cwd = calls[0]
    assert argv == ["claude", "plugin", "enable", "--scope", "project", PLUGIN_ID]
    assert cwd == tmp_path.resolve()
    assert "enabled for" in capsys.readouterr().out


def test_run_enable_project_failure_surfaces(tmp_path, capsys):
    from install_helper import Style, marks, run_enable_project

    rc = run_enable_project(
        tmp_path,
        Style(False),
        marks(),
        runner=lambda *a, **k: _FakeProc(1, stderr="no such plugin"),
    )
    assert rc == 1
    assert "no such plugin" in capsys.readouterr().out


def test_run_enable_project_missing_dir(tmp_path, capsys):
    from install_helper import Style, marks, run_enable_project

    assert run_enable_project(tmp_path / "ghost", Style(False), marks()) == 1


# --- demo mode: the real flow as a dry run (2026-07-30) -----------------------------------


def _isolate_home(monkeypatch, tmp_path):
    """Point every home-derived path at tmp so a demo run can prove it wrote nothing."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))  # Path.home() on Windows


def test_demo_mode_executes_nothing_and_writes_nothing(monkeypatch, tmp_path, capsys):
    import subprocess as _sp

    import install_helper as ih

    def boom(*a, **k):
        raise AssertionError("demo mode must never spawn a subprocess")

    monkeypatch.setattr(_sp, "run", boom)
    _isolate_home(monkeypatch, tmp_path)
    monkeypatch.setattr(ih, "DEFAULT_CLONE_DIR", tmp_path / "clone")
    original_run_cmd = ih.run_cmd
    rc = ih.main(["--demo"])  # non-tty stdin: every prompt takes its default
    out = capsys.readouterr().out
    assert rc == 0
    assert "DEMO MODE" in out and "would run:" in out
    assert "Summon the team" in out and "nothing was executed" in out
    assert not (tmp_path / "xdg").exists()  # no config file created
    assert not (tmp_path / "clone").exists()  # no clone created
    assert not (tmp_path / "home").exists()  # no user settings written
    assert ih.run_cmd is original_run_cmd  # module runner restored after the run


def test_demo_mode_with_yes_is_noninteractive_dry_run(monkeypatch, tmp_path, capsys):
    import subprocess as _sp

    import install_helper as ih

    monkeypatch.setattr(_sp, "run", lambda *a, **k: (_ for _ in ()).throw(AssertionError("ran")))
    _isolate_home(monkeypatch, tmp_path)
    monkeypatch.setattr(ih, "DEFAULT_CLONE_DIR", tmp_path / "clone")
    rc = ih.main(["--demo", "--yes"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "would run:" in out and "nothing was executed" in out
    assert not (tmp_path / "xdg").exists()


def test_demo_stdout_shapes():
    from install_helper import demo_stdout

    assert demo_stdout(["git", "-C", "/r", "status", "--porcelain"]) == ""
    assert demo_stdout(["git", "-C", "/r", "rev-parse", "--short", "HEAD"]) == "abc1234"
    assert demo_stdout(["git", "-C", "/r", "rev-list", "--count", "origin/main..HEAD"]) == "0"
    assert demo_stdout(["git", "ls-remote", "--heads", "https://x", "main"]) == "ref"
    assert demo_stdout(["claude", "plugin", "install", "x"]) == ""


def test_demo_runner_prints_would_run_and_fakes_success(capsys):
    from install_helper import Style, make_demo_runner

    runner = make_demo_runner(Style(False))
    proc = runner(["git", "clone", "https://x", "/dest"])
    out = capsys.readouterr().out
    assert "would run: git clone https://x /dest" in out
    assert proc.returncode == 0 and proc.stderr == ""
    head = runner(["git", "-C", "/dest", "rev-parse", "--short", "HEAD"])
    assert head.stdout == "abc1234"


# --- boxed banner + ruled headers with ASCII fallbacks (2026-07-30) -----------------------


class _AsciiStream(io.StringIO):
    encoding = "ascii"


class _Utf8Stream(io.StringIO):
    encoding = "utf-8"


def test_render_banner_unicode_box():
    from install_helper import Style, render_banner

    rows = render_banner(["Title line", "sub"], Style(False), stream=_Utf8Stream())
    assert rows[0].startswith("┌") and rows[0].endswith("┐")
    assert rows[-1].startswith("└") and rows[-1].endswith("┘")
    assert all(row.startswith("│") and row.endswith("│") for row in rows[1:-1])
    assert len({len(row) for row in rows}) == 1  # every row the same width


def test_render_banner_ascii_fallback():
    from install_helper import Style, render_banner

    rows = render_banner(["Title line", "sub"], Style(False), stream=_AsciiStream())
    assert rows[0].startswith("+-") and rows[0].endswith("+")
    assert all(row.startswith("|") and row.endswith("|") for row in rows[1:-1])


def test_rule_header_pads_to_width_and_names_the_step():
    from install_helper import RULE_WIDTH, Style, rule_header

    line = rule_header(3, 9, "Local clone", Style(False), stream=_AsciiStream())
    assert "Step 3 of 9: Local clone" in line
    assert line.startswith("--")
    assert len(line) == RULE_WIDTH


def test_morgan_intro_marks_ai_identity_with_ascii_fallback():
    from install_helper import morgan_intro

    plain = morgan_intro(stream=_AsciiStream())
    assert plain.startswith("Morgan (PM)") and "AI agent" in plain
    fancy = morgan_intro(stream=_Utf8Stream())
    assert fancy.startswith("🎩 ")


def test_banner_version_line_reads_sibling_manifest(monkeypatch, tmp_path):
    import install_helper as ih

    plug = tmp_path / ".claude-plugin"
    plug.mkdir()
    (plug / "plugin.json").write_text('{"version": "1.2.3"}', encoding="utf-8")
    monkeypatch.setattr(ih, "__file__", str(tmp_path / "install_helper.py"))
    assert "v1.2.3" in ih.banner_version_line()


def test_banner_version_line_falls_back_to_configured_clone(monkeypatch, tmp_path):
    import install_helper as ih

    clone = _fake_clone(tmp_path)  # manifest carries version 9.9.9
    monkeypatch.setattr(ih, "__file__", str(tmp_path / "bare" / "install_helper.py"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    cfg_dir = tmp_path / "xdg" / "virt-surv-it"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "installer.json").write_text(json.dumps({"repo_path": str(clone)}), encoding="utf-8")
    assert "v9.9.9" in ih.banner_version_line()


def test_banner_version_line_never_missing(monkeypatch, tmp_path):
    import install_helper as ih

    # No sibling manifest, no config anywhere: the fixed fallback line, not a crash.
    monkeypatch.setattr(ih, "__file__", str(tmp_path / "bare" / "install_helper.py"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "empty-xdg"))
    line = ih.banner_version_line()
    assert line == "compliance-surveillance-team (version shown after install)"


# --- grouped summary (2026-07-30) ---------------------------------------------------------


def _args(**overrides):
    base = dict(
        mode=None,
        branch=None,
        repo=None,
        yes=False,
        pip=False,
        demo=False,
        enable_project=None,
        statusline=False,
        permissions=None,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_print_summary_groups_by_status(monkeypatch, tmp_path, capsys):
    import install_helper as ih

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    inst = ih.Installer(_args(), ih.Style(False), {"ok": "OK", "fail": "X", "skip": "~"})
    inst.tracker.record("Alpha", "ok")
    inst.tracker.record("Beta", "skip", "why")
    inst.tracker.record("Gamma", "fail", "boom")
    inst.print_summary(aborted=False)
    out = capsys.readouterr().out
    assert out.index("Completed") < out.index("Skipped") < out.index("Failed")
    assert "OK Alpha" in out and "~ Beta" in out and "X Gamma" in out


def test_print_summary_omits_empty_groups(monkeypatch, tmp_path, capsys):
    import install_helper as ih

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    inst = ih.Installer(_args(), ih.Style(False), {"ok": "OK", "fail": "X", "skip": "~"})
    inst.tracker.record("Alpha", "ok")
    inst.print_summary(aborted=False)
    out = capsys.readouterr().out
    assert "Completed" in out
    assert "Skipped" not in out and "Failed" not in out


# --- interactive menu + partial runs (2026-07-30) -----------------------------------------


class _TtyStdin(io.StringIO):
    def isatty(self):
        return True


def _fake_clone(tmp_path):
    clone = tmp_path / "clone"
    (clone / ".git").mkdir(parents=True)
    plug = clone / ".claude-plugin"
    plug.mkdir()
    (plug / "plugin.json").write_text('{"version": "9.9.9"}', encoding="utf-8")
    return clone


def _menu_session(monkeypatch, tmp_path, answers):
    """Fake a tty with scripted answers; exhausted answers return the default."""
    import sys as _sys

    feed = iter(answers)
    monkeypatch.setattr(_sys, "stdin", _TtyStdin())
    monkeypatch.setattr("builtins.input", lambda prompt="": next(feed, ""))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))


def test_menu_setup_only_skips_sync_and_uses_clone_asis(monkeypatch, tmp_path, capsys):
    import install_helper as ih

    clone = _fake_clone(tmp_path)
    _menu_session(monkeypatch, tmp_path, ["2", "", ""])  # option 2, then prompt defaults
    (tmp_path / "xdg" / "virt-surv-it").mkdir(parents=True)
    (tmp_path / "xdg" / "virt-surv-it" / "installer.json").write_text(
        json.dumps({"repo_path": str(clone), "branch": "main"}), encoding="utf-8"
    )
    calls = []

    def runner(argv, cwd=None, timeout=300):
        calls.append([str(a) for a in argv])
        return _FakeProc(0)

    monkeypatch.setattr(ih, "run_cmd", runner)
    rc = ih.main([])
    out = capsys.readouterr().out
    assert rc == 0
    joined = [" ".join(c) for c in calls]
    assert not any("fetch" in c or "checkout" in c or "clone" in c for c in joined)
    assert "Step 2 of 6" in out  # truthful numbering for the shorter plan
    assert "code not updated" in out and "Code not updated" in out
    assert "Summon the team" in out


def test_menu_setup_only_without_clone_fails_cleanly(monkeypatch, tmp_path, capsys):
    import install_helper as ih

    _menu_session(monkeypatch, tmp_path, ["2"])
    monkeypatch.setattr(ih, "run_cmd", lambda *a, **k: _FakeProc(0))
    # The script-root fallback would find the dev repo itself; point it nowhere.
    monkeypatch.setattr(ih, "__file__", str(tmp_path / "nowhere" / "install_helper.py"))
    rc = ih.main([])
    out = capsys.readouterr().out
    assert rc == 1
    assert "run a full install first" in out


def test_menu_quit_runs_nothing(monkeypatch, tmp_path, capsys):
    import install_helper as ih

    _menu_session(monkeypatch, tmp_path, ["q"])
    calls = []
    monkeypatch.setattr(ih, "run_cmd", lambda *a, **k: calls.append(a) or _FakeProc(0))
    rc = ih.main([])
    out = capsys.readouterr().out
    assert rc == 0
    assert calls == []
    assert "nothing changed" in out


def test_full_sync_step_fetches_and_checks_out(monkeypatch, tmp_path):
    """The full plan still syncs - guards the setup subset against regressing the default."""
    import install_helper as ih

    clone = _fake_clone(tmp_path)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    calls = []

    def runner(argv, cwd=None, timeout=300):
        calls.append([str(a) for a in argv])
        return _FakeProc(0, stdout="")

    monkeypatch.setattr(ih, "run_cmd", runner)
    inst = ih.Installer(_args(yes=True), ih.Style(False), ih.marks())
    inst.repo = clone
    inst.branch = "main"
    inst.sync_branch()
    joined = [" ".join(c) for c in calls]
    assert any("fetch origin main" in c for c in joined)
    assert any("checkout -B main origin/main" in c for c in joined)
