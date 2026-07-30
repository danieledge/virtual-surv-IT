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
    # claude gets the find_claude fallback (stale corporate PATH); when even that
    # misses, the bare name survives so the error surfaces at launch, not resolve.
    monkeypatch.setattr(ih, "find_claude", lambda refresh=False: (None, ""))
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
    assert demo_stdout(["git", "-C", "/r", "rev-list", "--count", "HEAD..origin/main"]) == "3"
    assert demo_stdout(["git", "ls-remote", "--heads", "https://x", "main"]) == "ref"
    assert demo_stdout(["claude", "plugin", "install", "x"]) == ""
    manifest = demo_stdout(["git", "-C", "/r", "show", "origin/main:.claude-plugin/plugin.json"])
    assert json.loads(manifest)["version"] == "9.9.9"
    changelog = demo_stdout(["git", "-C", "/r", "show", "origin/main:CHANGELOG.md"])
    assert "## [9.9.9]" in changelog


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


# --- statusline conflict detection refinement (2026-07-30) --------------------------------


def test_merge_statusline_ours_at_old_path_updates_silently(tmp_path):
    from install_helper import merge_statusline, statusline_command

    new_cmd = statusline_command(tmp_path / "new-clone")
    old = {"statusLine": {"type": "command", "command": 'bash "/old/clone/scripts/statusline.sh"'}}
    settings, verdict = merge_statusline(old, new_cmd)
    assert verdict == "ours-moved"
    assert settings["statusLine"]["command"] == new_cmd  # updated in place, no prompt path


def test_merge_statusline_foreign_still_conflicts(tmp_path):
    from install_helper import current_statusline_command, merge_statusline, statusline_command

    foreign = {"statusLine": {"type": "command", "command": "starship prompt"}}
    settings, verdict = merge_statusline(foreign, statusline_command(tmp_path))
    assert verdict == "conflict"
    assert settings["statusLine"]["command"] == "starship prompt"  # untouched
    assert current_statusline_command(settings) == "starship prompt"


# --- Windows hardening (2026-07-30) -------------------------------------------------------


def test_windows_shim_cmdline_survives_spaces_everywhere():
    from install_helper import windows_shim_cmdline

    line = windows_shim_cmdline(
        r"C:\Users\John Smith\AppData\Roaming\npm\claude.CMD",
        ["plugin", "marketplace", "add", r"C:\Users\John Smith\virtual-surv-IT"],
    )
    # /s + one outer quote pair pins cmd.exe's re-parse; both spaced paths stay quoted.
    assert line.startswith('cmd.exe /s /c "') and line.endswith('"')
    assert '"C:\\Users\\John Smith\\AppData\\Roaming\\npm\\claude.CMD"' in line
    assert '"C:\\Users\\John Smith\\virtual-surv-IT"' in line
    assert "plugin marketplace add" in line


def test_run_cmd_routes_batch_shims_via_quoted_string(monkeypatch):
    import install_helper as ih

    seen = {}

    def fake_run(cmd, **kwargs):
        seen["cmd"] = cmd
        return ih.subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(ih.subprocess, "run", fake_run)
    monkeypatch.setattr(ih.shutil, "which", lambda _n: r"C:\np m\claude.CMD")  # uppercase + space
    ih.run_cmd(["claude", "plugin", "list"])
    assert isinstance(seen["cmd"], str)
    assert seen["cmd"].startswith('cmd.exe /s /c "')
    assert '"C:\\np m\\claude.CMD"' in seen["cmd"]


def test_run_cmd_keeps_list_form_for_real_executables(monkeypatch):
    import install_helper as ih

    seen = {}

    def fake_run(cmd, **kwargs):
        seen["cmd"] = cmd
        return ih.subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(ih.subprocess, "run", fake_run)
    monkeypatch.setattr(ih.shutil, "which", lambda _n: "/usr/bin/git")
    ih.run_cmd(["git", "status"])
    assert seen["cmd"] == ["/usr/bin/git", "status"]


class _Cp437Stream(io.StringIO):
    encoding = "cp437"


class _Cp1252Stream(io.StringIO):
    encoding = "cp1252"


def test_glyphs_degrade_per_windows_codepage():
    from install_helper import box_chars, marks, morgan_intro

    # cp437 (legacy US console) carries box drawing but not the check marks or the hat.
    assert box_chars(_Cp437Stream())["tl"] == "┌"
    assert marks(_Cp437Stream())["ok"] == "OK"
    assert not morgan_intro(stream=_Cp437Stream()).startswith("🎩")
    # cp1252 (western Windows) carries none of them.
    assert box_chars(_Cp1252Stream())["tl"] == "+"
    assert marks(_Cp1252Stream())["ok"] == "OK"
    assert not morgan_intro(stream=_Cp1252Stream()).startswith("🎩")


def test_reads_tolerate_utf8_bom_and_crlf(tmp_path):
    from install_helper import changelog_headline, installed_version, load_config

    plug = tmp_path / ".claude-plugin"
    plug.mkdir()
    (plug / "plugin.json").write_text('{"version": "1.0.0"}', encoding="utf-8-sig")
    assert installed_version(tmp_path) == "1.0.0"
    log = tmp_path / "CHANGELOG.md"
    log.write_text("# C\r\n\r\n## [1.0.0] - d - Title\r\n", encoding="utf-8-sig")
    assert changelog_headline(log, "1.0.0") == "[1.0.0] - d - Title"
    cfg = tmp_path / "installer.json"
    cfg.write_text('{"branch": "dev"}', encoding="utf-8-sig")
    assert load_config(cfg) == {"branch": "dev"}


def test_statusline_step_skips_without_bash_on_windows(monkeypatch, tmp_path, capsys):
    import install_helper as ih

    _isolate_home(monkeypatch, tmp_path)
    monkeypatch.setattr(ih.sys, "platform", "win32")
    monkeypatch.setattr(ih.shutil, "which", lambda _n: None)
    inst = ih.Installer(_args(), ih.Style(False), ih.marks(), subset="statusline")
    inst.repo = tmp_path
    inst.statusline_step()
    out = capsys.readouterr().out
    assert "Git Bash" in out
    assert not (tmp_path / "home" / ".claude").exists()  # nothing wired
    assert any(status == "skip" for _n, status, _d in inst.tracker.steps)


def test_looks_like_repo_accepts_worktree_git_file(tmp_path):
    from install_helper import looks_like_repo

    (tmp_path / ".git").write_text("gitdir: /main/.git/worktrees/x\n", encoding="utf-8")
    plug = tmp_path / ".claude-plugin"
    plug.mkdir()
    (plug / "plugin.json").write_text("{}", encoding="utf-8")
    assert looks_like_repo(tmp_path) is True


# --- both-platform hardening (2026-07-30) -------------------------------------------------


def test_save_config_is_atomic_and_best_effort(tmp_path):
    from install_helper import load_config, save_config

    path = tmp_path / "cfg" / "installer.json"
    assert save_config(path, {"a": 1}) is True
    assert load_config(path) == {"a": 1}
    assert list(path.parent.glob("*.tmp")) == []  # temp+rename leaves no litter
    blocker = tmp_path / "plainfile"
    blocker.write_text("x", encoding="utf-8")
    # Parent "directory" is a file: unwritable location degrades to False, no raise.
    assert save_config(blocker / "nested" / "cfg.json", {"a": 1}) is False


def test_persist_warns_when_config_unwritable(monkeypatch, tmp_path, capsys):
    import install_helper as ih

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr(ih, "save_config", lambda *_a, **_k: False)
    inst = ih.Installer(_args(), ih.Style(False), ih.marks())
    inst.repo = tmp_path
    inst.persist()
    out = capsys.readouterr().out
    assert "without saving" in out
    assert not inst.tracker.failed  # a warning (skip), not a failure


def test_keyboard_interrupt_mid_run_prints_summary_and_exits_130(monkeypatch, tmp_path, capsys):
    import install_helper as ih

    _isolate_home(monkeypatch, tmp_path)
    monkeypatch.setattr(ih.shutil, "which", lambda n: "/usr/bin/" + n)

    def boom(argv, cwd=None, timeout=300):
        raise KeyboardInterrupt

    monkeypatch.setattr(ih, "run_cmd", boom)
    rc = ih.main(["--yes", "install"])
    out = capsys.readouterr().out
    assert rc == 130
    assert "Cancelled" in out and "Summary" in out


def test_keyboard_interrupt_at_menu_returns_130(monkeypatch, tmp_path, capsys):
    import install_helper as ih

    _menu_session(monkeypatch, tmp_path, [])

    def interrupt(prompt=""):
        raise KeyboardInterrupt

    monkeypatch.setattr("builtins.input", interrupt)
    rc = ih.main([])
    out = capsys.readouterr().out
    assert rc == 130
    assert "Cancelled" in out


def test_run_enable_project_fails_soft_on_timeout_and_oserror(tmp_path, capsys):
    import subprocess as _sp

    from install_helper import Style, marks, run_enable_project

    def timeout_runner(argv, cwd=None, timeout=300):
        raise _sp.TimeoutExpired(cmd=argv, timeout=timeout)

    assert run_enable_project(tmp_path, Style(False), marks(), runner=timeout_runner) == 1
    assert "enable failed" in capsys.readouterr().out

    def oserror_runner(argv, cwd=None, timeout=300):
        raise OSError("exec format error")

    # A launch-level OSError (blocked, missing, wrong arch) now falls back to the
    # direct enabledPlugins write - same outcome the CLI would have produced.
    assert run_enable_project(tmp_path, Style(False), marks(), runner=oserror_runner) == 0
    out = capsys.readouterr().out
    assert "written directly" in out and "exec format error" in out


def test_statusline_conflict_display_tolerates_bom(monkeypatch, tmp_path, capsys):
    import install_helper as ih

    _isolate_home(monkeypatch, tmp_path)
    claude_dir = tmp_path / "home" / ".claude"
    claude_dir.mkdir(parents=True)
    (claude_dir / "settings.json").write_text(
        '{"statusLine": {"type": "command", "command": "starship prompt"}}',
        encoding="utf-8-sig",  # BOM as a Windows editor would leave it
    )
    inst = ih.Installer(_args(), ih.Style(False), ih.marks(), subset="statusline")
    inst.repo = tmp_path
    inst.statusline_step()  # non-tty confirm declines the replacement by default
    out = capsys.readouterr().out
    assert "starship prompt" in out  # existing command shown, no traceback
    assert "statusLine kept" in out
    written = (claude_dir / "settings.json").read_text(encoding="utf-8-sig")
    assert "starship" in written  # untouched


# --- update preview: pure parsers (2026-07-30) --------------------------------------------


def test_parse_manifest_version_tolerant():
    from install_helper import parse_manifest_version

    assert parse_manifest_version('{"version": "1.2.3"}') == "1.2.3"
    assert parse_manifest_version('\ufeff{"version": "1.2.3"}') == "1.2.3"  # BOM
    assert parse_manifest_version("{broken") is None
    assert parse_manifest_version('["a", "list"]') is None
    assert parse_manifest_version('{"name": "x"}') is None
    assert parse_manifest_version('{"version": ""}') is None
    assert parse_manifest_version(None) is None


def test_list_headlines_between_ranges():
    from install_helper import list_headlines_between

    text = (
        "# Changelog\n\n"
        "## [0.35.0] - d - Newest\n\n"
        "## [0.34.0] - d - Middle\n\n"
        "## [0.33.1] - d - Local\n\n"
        "## [0.33.0] - d - Older\n"
    )
    assert list_headlines_between(text, "0.33.1") == [
        "[0.35.0] - d - Newest",
        "[0.34.0] - d - Middle",
    ]
    # Local version absent from the changelog (or unknown): every headline, no error.
    assert len(list_headlines_between(text, "9.9.9")) == 4
    assert len(list_headlines_between(text, None)) == 4
    assert list_headlines_between(text, "not-semver !") == list_headlines_between(text, None)
    assert list_headlines_between("", "0.33.1") == []
    assert list_headlines_between(None, "0.33.1") == []


def _preview_runner(mapping, default=None):
    default = default if default is not None else _FakeProc(0, stdout="")

    def runner(argv, cwd=None, timeout=300):
        joined = " ".join(str(a) for a in argv)
        for key, result in mapping.items():
            if key in joined:
                if isinstance(result, Exception):
                    raise result
                return result
        return default

    return runner


def test_gather_update_preview_happy_path():
    from install_helper import gather_update_preview

    changelog = "# C\n\n## [0.34.0] - d - New\n\n## [0.33.1] - d - Old\n"
    runner = _preview_runner(
        {
            "rev-list": _FakeProc(0, stdout="4\n"),
            "plugin.json": _FakeProc(0, stdout='{"version": "0.34.0"}'),
            "CHANGELOG.md": _FakeProc(0, stdout=changelog),
        }
    )
    preview = gather_update_preview(Path("/r"), "main", "0.33.1", runner=runner)
    assert preview["behind"] == 4
    assert preview["remote_version"] == "0.34.0"
    assert preview["headlines"] == ["[0.34.0] - d - New"]
    assert preview["notes"] == []


def test_gather_update_preview_degrades_on_git_errors():
    from install_helper import gather_update_preview

    # Shallow clone / detached HEAD / missing remote files: every probe errors.
    runner = _preview_runner({}, default=_FakeProc(128, stderr="fatal: bad revision"))
    preview = gather_update_preview(Path("/r"), "main", "0.33.1", runner=runner)
    assert preview["behind"] is None
    assert preview["remote_version"] is None
    assert preview["headlines"] == []
    assert len(preview["notes"]) == 3  # one clear note per degraded probe


def test_gather_update_preview_degrades_on_garbage_output():
    from install_helper import gather_update_preview

    runner = _preview_runner(
        {
            "rev-list": _FakeProc(0, stdout="not-a-number\n"),
            "plugin.json": _FakeProc(0, stdout="{broken json"),
            "CHANGELOG.md": _FakeProc(0, stdout=""),
        }
    )
    preview = gather_update_preview(Path("/r"), "main", "0.33.1", runner=runner)
    assert preview["behind"] is None and preview["remote_version"] is None
    assert preview["headlines"] == []
    assert len(preview["notes"]) == 3


def test_gather_update_preview_survives_raising_runner():
    import subprocess as _sp

    from install_helper import gather_update_preview

    runner = _preview_runner(
        {
            "rev-list": _sp.TimeoutExpired(cmd="git", timeout=1),
            "plugin.json": OSError("no git"),
            "CHANGELOG.md": _sp.TimeoutExpired(cmd="git", timeout=1),
        }
    )
    preview = gather_update_preview(Path("/r"), "main", None, runner=runner)
    assert preview["behind"] is None and preview["remote_version"] is None
    assert len(preview["notes"]) == 3  # degraded, never raised


# --- update preview: wired into sync + the check menu item (2026-07-30) -------------------


def test_sync_preview_decline_keeps_clone_asis(monkeypatch, tmp_path, capsys):
    import sys as _sys

    import install_helper as ih

    clone = _fake_clone(tmp_path)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    calls = []

    def runner(argv, cwd=None, timeout=300):
        joined = " ".join(str(a) for a in argv)
        calls.append(joined)
        if "rev-list" in joined and "HEAD.." in joined:
            return _FakeProc(0, stdout="2\n")
        if "plugin.json" in joined:
            return _FakeProc(0, stdout='{"version": "10.0.0"}')
        if "CHANGELOG" in joined:
            return _FakeProc(0, stdout="## [10.0.0] - d - Big\n\n## [9.9.9] - d - Cur\n")
        return _FakeProc(0, stdout="")

    monkeypatch.setattr(ih, "run_cmd", runner)
    monkeypatch.setattr(_sys, "stdin", _TtyStdin())
    answers = iter(["n"])  # decline "Shall I bring you up to date?"
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers, ""))
    inst = ih.Installer(_args(), ih.Style(False), ih.marks())
    inst.repo = clone
    inst.branch = "main"
    inst.sync_branch()
    out = capsys.readouterr().out
    assert "9.9.9 -> 10.0.0" in out
    assert "[10.0.0] - d - Big" in out
    assert "[9.9.9]" not in out  # local entry excluded from the preview list
    assert not any("checkout" in c for c in calls)
    assert inst.code_stale is True
    assert not inst.tracker.failed  # declining is a skip, not a failure


def test_sync_preview_up_to_date_says_so(monkeypatch, tmp_path, capsys):
    import install_helper as ih

    clone = _fake_clone(tmp_path)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))

    def runner(argv, cwd=None, timeout=300):
        joined = " ".join(str(a) for a in argv)
        if "rev-list" in joined and "HEAD.." in joined:
            return _FakeProc(0, stdout="0\n")
        return _FakeProc(0, stdout="")

    monkeypatch.setattr(ih, "run_cmd", runner)
    inst = ih.Installer(_args(yes=True), ih.Style(False), ih.marks())
    inst.repo = clone
    inst.branch = "main"
    inst.sync_branch()
    out = capsys.readouterr().out
    assert "Already up to date" in out
    assert "would bring" not in out  # preview skipped entirely


def test_print_update_preview_caps_headlines_at_five(monkeypatch, tmp_path, capsys):
    import install_helper as ih

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    inst = ih.Installer(_args(), ih.Style(False), ih.marks())
    preview = {
        "behind": 9,
        "remote_version": "2.0.0",
        "headlines": [f"[1.0.{i}] - d - t{i}" for i in range(7)],
        "notes": [],
    }
    inst.print_update_preview(preview, "main", "0.9.0")
    out = capsys.readouterr().out
    assert "t4" in out and "t5" not in out
    assert "... and 2 more" in out
    assert "0.9.0 -> 2.0.0" in out


def test_menu_check_for_updates_is_read_only(monkeypatch, tmp_path, capsys):
    import install_helper as ih

    clone = _fake_clone(tmp_path)
    _menu_session(monkeypatch, tmp_path, ["5"])
    cfg_dir = tmp_path / "xdg" / "virt-surv-it"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "installer.json").write_text(
        json.dumps({"repo_path": str(clone), "branch": "main"}), encoding="utf-8"
    )
    calls = []

    def runner(argv, cwd=None, timeout=300):
        joined = " ".join(str(a) for a in argv)
        calls.append(joined)
        if "rev-list" in joined and "HEAD.." in joined:
            return _FakeProc(0, stdout="2\n")
        if "plugin.json" in joined:
            return _FakeProc(0, stdout='{"version": "10.0.0"}')
        if "CHANGELOG" in joined:
            return _FakeProc(0, stdout="## [10.0.0] - d - Big\n## [9.9.9] - d - Cur\n")
        return _FakeProc(0, stdout="")

    monkeypatch.setattr(ih, "run_cmd", runner)
    rc = ih.main([])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Step 2 of 2" in out  # truthful numbering: preflight-lite + check
    assert "10.0.0" in out and "nothing changed" in out
    assert any("fetch" in c for c in calls)
    forbidden = ("checkout", "marketplace", "plugin install", "plugin update", "clone http")
    assert not any(any(word in c for word in forbidden) for c in calls)
    assert not (tmp_path / "home").exists()  # wrote nothing


def test_menu_check_for_updates_fetch_failure_fails_soft(monkeypatch, tmp_path, capsys):
    import install_helper as ih

    clone = _fake_clone(tmp_path)
    _menu_session(monkeypatch, tmp_path, ["5"])
    cfg_dir = tmp_path / "xdg" / "virt-surv-it"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "installer.json").write_text(
        json.dumps({"repo_path": str(clone), "branch": "main"}), encoding="utf-8"
    )

    def runner(argv, cwd=None, timeout=300):
        joined = " ".join(str(a) for a in argv)
        if "fetch" in joined:
            return _FakeProc(128, stderr="fatal: unable to access remote")
        return _FakeProc(0, stdout="")

    monkeypatch.setattr(ih, "run_cmd", runner)
    rc = ih.main([])
    out = capsys.readouterr().out
    assert rc == 0  # informational check: a failed fetch never aborts the process
    assert "check your connection" in out
    assert "Traceback" not in out


def test_menu_check_for_updates_without_clone_fails_soft(monkeypatch, tmp_path, capsys):
    import install_helper as ih

    _menu_session(monkeypatch, tmp_path, ["5"])
    monkeypatch.setattr(ih, "run_cmd", lambda *a, **k: _FakeProc(0, stdout=""))
    monkeypatch.setattr(ih, "__file__", str(tmp_path / "nowhere" / "install_helper.py"))
    rc = ih.main([])
    out = capsys.readouterr().out
    assert rc == 0
    assert "no usable clone" in out and "Traceback" not in out


# ------------------------------------------------------ stale-PATH claude discovery


def _clear_claude_cache():
    import install_helper as ih

    ih._claude_cache = None


def test_find_claude_prefers_live_path(monkeypatch):
    import install_helper as ih

    _clear_claude_cache()
    monkeypatch.setattr(ih.shutil, "which", lambda n: "/usr/bin/claude")
    assert ih.find_claude(refresh=True) == ("/usr/bin/claude", "path")


def test_find_claude_falls_back_to_known_location(monkeypatch, tmp_path):
    """CLI installed to ~/.local/bin but the session PATH is stale: which() misses,
    the documented location is probed and wins."""
    import install_helper as ih

    _clear_claude_cache()
    home = tmp_path / "home"
    binary = home / ".local" / "bin" / ("claude.exe" if ih.sys.platform == "win32" else "claude")
    binary.parent.mkdir(parents=True)
    binary.write_text("", encoding="utf-8")
    monkeypatch.setattr(ih.shutil, "which", lambda n: None)
    monkeypatch.setattr(ih.Path, "home", staticmethod(lambda: home))
    path, how = ih.find_claude(refresh=True)
    assert path == str(binary)
    assert how == "known-location"
    _clear_claude_cache()


def test_find_claude_windows_registry_catches_stale_session(monkeypatch, tmp_path):
    """The corporate case: installed a minute ago, terminal opened an hour ago. The
    registry PATH (what a NEW shell would see) locates it."""
    import install_helper as ih

    _clear_claude_cache()
    stale_dir = tmp_path / "fresh-path-dir"
    stale_dir.mkdir()
    (stale_dir / "claude.cmd").write_text("@echo off\n", encoding="utf-8")
    monkeypatch.setattr(ih.shutil, "which", lambda n: None)
    monkeypatch.setattr(ih.Path, "home", staticmethod(lambda: tmp_path / "nohome"))
    monkeypatch.setattr(ih.sys, "platform", "win32")
    monkeypatch.setattr(ih, "_windows_registry_path_dirs", lambda: [str(stale_dir)])
    monkeypatch.delenv("APPDATA", raising=False)
    path, how = ih.find_claude(refresh=True)
    assert path == str(stale_dir / "claude.cmd")
    assert how == "registry"
    _clear_claude_cache()


def test_find_claude_not_found_never_raises(monkeypatch, tmp_path):
    import install_helper as ih

    _clear_claude_cache()
    monkeypatch.setattr(ih.shutil, "which", lambda n: None)
    monkeypatch.setattr(ih.Path, "home", staticmethod(lambda: tmp_path / "nohome"))
    monkeypatch.setattr(ih, "_windows_registry_path_dirs", lambda: ["Z:\\missing"])
    assert ih.find_claude(refresh=True) == (None, "")
    _clear_claude_cache()


def test_find_claude_memoises_registry_probe(monkeypatch, tmp_path):
    """Repeated launches (every run_cmd resolves argv[0]) must not re-read the registry."""
    import install_helper as ih

    _clear_claude_cache()
    calls = []
    monkeypatch.setattr(ih.shutil, "which", lambda n: None)
    monkeypatch.setattr(ih.Path, "home", staticmethod(lambda: tmp_path / "nohome"))
    monkeypatch.setattr(ih.sys, "platform", "win32")
    monkeypatch.setattr(ih, "_windows_registry_path_dirs", lambda: calls.append(1) or [])
    ih.find_claude(refresh=True)
    ih.find_claude()
    ih.find_claude()
    assert len(calls) == 1
    _clear_claude_cache()


def test_command_argv_uses_find_claude_fallback(monkeypatch):
    """Bare `claude` in an argv resolves to the off-PATH shim, which then routes
    through the cmd /s /c quoted form like any discovered .cmd."""
    import install_helper as ih

    monkeypatch.setattr(ih.shutil, "which", lambda n: None)
    monkeypatch.setattr(
        ih, "find_claude", lambda refresh=False: (r"C:\Users\A B\npm\claude.cmd", "registry")
    )
    assert ih.command_argv("claude") == ["cmd", "/c", r"C:\Users\A B\npm\claude.cmd"]
    # other names keep the plain bare-name fallback
    assert ih.command_argv("git") == ["git"]


def test_find_claude_npm_package_bin_dir(monkeypatch, tmp_path):
    """The reported corporate layout: no shims on PATH, the CLI living only in
    APPDATA\\npm\\node_modules\\@anthropic-ai\\claude-code\\bin."""
    import install_helper as ih

    _clear_claude_cache()
    appdata = tmp_path / "AppData" / "Roaming"
    pkg_bin = appdata / "npm" / "node_modules" / "@anthropic-ai" / "claude-code" / "bin"
    pkg_bin.mkdir(parents=True)
    (pkg_bin / "claude.exe").write_text("", encoding="utf-8")
    monkeypatch.setattr(ih.shutil, "which", lambda n: None)
    monkeypatch.setattr(ih.Path, "home", staticmethod(lambda: tmp_path / "nohome"))
    monkeypatch.setattr(ih.sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", str(appdata))
    path, how = ih.find_claude(refresh=True)
    assert path == str(pkg_bin / "claude.exe")
    assert how == "known-location"
    _clear_claude_cache()


def test_run_cmd_decodes_utf8_with_replacement_not_console_codepage(monkeypatch):
    """Step-4 crash seen live: git's UTF-8 output decoded with cp1252 raises
    UnicodeDecodeError in subprocess's reader thread. run_cmd must pin utf-8 +
    errors=replace on every branch so the decode is total."""
    import install_helper as ih

    seen = []

    def fake_run(*args, **kwargs):
        seen.append(kwargs)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(ih.subprocess, "run", fake_run)
    ih.run_cmd(["git", "fetch", "origin", "main"])
    monkeypatch.setattr(ih.shutil, "which", lambda n: r"C:\npm\claude.cmd")
    ih.run_cmd(["claude", "plugin", "list"])
    assert len(seen) == 2  # plain executable + Windows shim branch
    for kwargs in seen:
        assert kwargs["encoding"] == "utf-8"
        assert kwargs["errors"] == "replace"
        assert "text" not in kwargs


# ------------------------------------------------------ group-policy-safe node launch


def _npm_layout(tmp_path, shim_name="claude.cmd"):
    npm = tmp_path / "npm"
    pkg = npm / "node_modules" / "@anthropic-ai" / "claude-code"
    pkg.mkdir(parents=True)
    (pkg / "cli.js").write_text("// cli\n", encoding="utf-8")
    shim = npm / shim_name
    shim.write_text("@echo off\n", encoding="utf-8")
    return npm, pkg, shim


def test_node_launch_for_rewrites_shim_to_node_cli(monkeypatch, tmp_path):
    """Group policy blocks cmd.exe and %APPDATA% executables; node.exe + cli.js is the
    policy-safe launch. The shim's sibling node_modules locates the package."""
    import install_helper as ih

    npm, pkg, shim = _npm_layout(tmp_path)
    monkeypatch.setattr(ih.shutil, "which", lambda n: "/usr/bin/node" if n == "node" else None)
    assert ih.node_launch_for(str(shim)) == ["/usr/bin/node", str(pkg / "cli.js")]


def test_node_launch_for_walks_up_from_package_bin(monkeypatch, tmp_path):
    import install_helper as ih

    npm, pkg, _ = _npm_layout(tmp_path)
    exe = pkg / "bin" / "claude.exe"
    exe.parent.mkdir()
    exe.write_text("", encoding="utf-8")
    monkeypatch.setattr(ih.sys, "platform", "win32")
    monkeypatch.setattr(ih.shutil, "which", lambda n: "node.exe" if n == "node" else None)
    assert ih.node_launch_for(str(exe)) == ["node.exe", str(pkg / "cli.js")]


def test_node_launch_for_none_without_node_or_package(monkeypatch, tmp_path):
    import install_helper as ih

    npm, pkg, shim = _npm_layout(tmp_path)
    monkeypatch.setattr(ih.shutil, "which", lambda n: None)  # node missing
    assert ih.node_launch_for(str(shim)) is None
    lone = tmp_path / "claude.cmd"  # shim with no package next to it
    lone.write_text("@echo off\n", encoding="utf-8")
    monkeypatch.setattr(ih.shutil, "which", lambda n: "/usr/bin/node" if n == "node" else None)
    assert ih.node_launch_for(str(lone)) is None


def test_command_argv_claude_prefers_node_over_cmd_shim(monkeypatch, tmp_path):
    import install_helper as ih

    npm, pkg, shim = _npm_layout(tmp_path)

    def which(n):
        return {"claude": str(shim), "node": "/usr/bin/node"}.get(n)

    monkeypatch.setattr(ih.shutil, "which", which)
    assert ih.command_argv("claude") == ["/usr/bin/node", str(pkg / "cli.js")]
    # a non-claude .cmd (no node available) still routes through cmd /c
    monkeypatch.setattr(ih.shutil, "which", lambda n: str(shim) if n == "other" else None)
    assert ih.command_argv("other")[0] == "cmd"


def test_claude_via_npm_prefix_queries_npm(monkeypatch, tmp_path):
    """The custom-corporate-prefix case: npm knows where it installs, we ask it."""
    import install_helper as ih

    prefix = tmp_path / "corp-npm"
    prefix.mkdir()
    (prefix / "claude.cmd").write_text("@echo off\n", encoding="utf-8")
    monkeypatch.setattr(ih.sys, "platform", "win32")
    monkeypatch.setattr(ih.shutil, "which", lambda n: "npm.cmd" if "npm" in n else None)
    monkeypatch.setattr(
        ih.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=0, stdout=f"{prefix}\n", stderr=""),
    )
    assert ih._claude_via_npm_prefix() == str(prefix / "claude.cmd")


def test_claude_via_npm_prefix_fails_soft(monkeypatch):
    import install_helper as ih

    monkeypatch.setattr(ih.shutil, "which", lambda n: None)  # no npm at all
    assert ih._claude_via_npm_prefix() is None
    monkeypatch.setattr(ih.shutil, "which", lambda n: "npm")
    monkeypatch.setattr(
        ih.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(OSError("blocked"))
    )
    assert ih._claude_via_npm_prefix() is None


# ------------------------------------------------ direct registration (CLI blocked)


def test_register_plugin_directly_writes_cli_schema(tmp_path):
    """Group-policy boxes: the CLI can't launch, so the helper writes the same JSON
    the CLI would (schema captured from a real install 2026-07-30). Merge-only."""
    from install_helper import MARKETPLACE, PLUGIN_ID, register_plugin_directly

    claude_dir = tmp_path / ".claude"
    (claude_dir / "plugins").mkdir(parents=True)
    (claude_dir / "plugins" / "known_marketplaces.json").write_text(
        json.dumps({"other": {"source": {"source": "github", "repo": "x/y"}}}),
        encoding="utf-8",
    )
    (claude_dir / "settings.json").write_text(
        json.dumps({"enabledPlugins": {"other@other": True}, "model": "opus"}),
        encoding="utf-8",
    )
    repo = tmp_path / "clone"
    repo.mkdir()
    touched = register_plugin_directly(repo, claude_dir, "0.33.1")
    km = json.loads((claude_dir / "plugins" / "known_marketplaces.json").read_text())
    assert km["other"]["source"]["repo"] == "x/y"  # preserved
    assert km[MARKETPLACE]["source"] == {"source": "local", "path": str(repo)}
    assert km[MARKETPLACE]["installLocation"] == str(repo)
    ip = json.loads((claude_dir / "plugins" / "installed_plugins.json").read_text())
    assert ip["version"] == 2
    entry = ip["plugins"][PLUGIN_ID][0]
    assert entry["scope"] == "user" and entry["installPath"] == str(repo)
    assert entry["version"] == "0.33.1"
    st = json.loads((claude_dir / "settings.json").read_text())
    assert st["enabledPlugins"][PLUGIN_ID] is True
    assert st["enabledPlugins"]["other@other"] is True and st["model"] == "opus"
    assert len(touched) == 3
    # pre-existing files got backups
    assert (claude_dir / "settings.json.bak").is_file()


def test_register_plugin_directly_from_empty_claude_dir(tmp_path):
    from install_helper import PLUGIN_ID, register_plugin_directly

    claude_dir = tmp_path / ".claude"
    register_plugin_directly(tmp_path / "clone", claude_dir, None)
    ip = json.loads((claude_dir / "plugins" / "installed_plugins.json").read_text())
    assert ip["plugins"][PLUGIN_ID][0]["version"] == "unknown"


def test_run_enable_project_falls_back_to_direct_write_on_policy_block(tmp_path, capsys):
    """AppLocker refuses the CLI launch (OSError) -> enabledPlugins written straight
    into the project settings, exactly what the CLI would have done."""
    from install_helper import PLUGIN_ID, Style, run_enable_project

    project = tmp_path / "proj"
    project.mkdir()

    def blocked_runner(argv, **kw):
        raise OSError("[WinError 1260] This program is blocked by group policy")

    rc = run_enable_project(
        project, Style(enabled=False), {"ok": "OK", "fail": "X"}, runner=blocked_runner
    )
    assert rc == 0
    settings = json.loads((project / ".claude" / "settings.json").read_text())
    assert settings["enabledPlugins"][PLUGIN_ID] is True
    out = capsys.readouterr().out
    assert "written directly" in out


def test_run_enable_project_policy_text_in_stderr_also_falls_back(tmp_path):
    from install_helper import PLUGIN_ID, Style, run_enable_project

    project = tmp_path / "proj"
    project.mkdir()

    def runner(argv, **kw):
        return _proc(returncode=1, stderr="This program is blocked by group policy\n")

    rc = run_enable_project(project, Style(enabled=False), {"ok": "OK", "fail": "X"}, runner=runner)
    assert rc == 0
    settings = json.loads((project / ".claude" / "settings.json").read_text())
    assert settings["enabledPlugins"][PLUGIN_ID] is True


def test_run_enable_project_ordinary_failure_still_fails(tmp_path):
    from install_helper import Style, run_enable_project

    project = tmp_path / "proj"
    project.mkdir()
    runner = lambda argv, **kw: _proc(returncode=1, stderr="No such plugin\n")  # noqa: E731
    rc = run_enable_project(project, Style(enabled=False), {"ok": "OK", "fail": "X"}, runner=runner)
    assert rc == 1
    assert not (project / ".claude" / "settings.json").exists()


# ------------------------------------------------------ Git Bash off-PATH discovery


def test_find_bash_derives_from_git_root(monkeypatch, tmp_path):
    """Git for Windows puts Git\\cmd on PATH but not Git\\bin - git resolves, bash
    doesn't. bash.exe is found from git's own install root."""
    import install_helper as ih

    git_root = tmp_path / "Git"
    (git_root / "cmd").mkdir(parents=True)
    (git_root / "bin").mkdir()
    git_exe = git_root / "cmd" / "git.exe"
    git_exe.write_text("", encoding="utf-8")
    bash_exe = git_root / "bin" / "bash.exe"
    bash_exe.write_text("", encoding="utf-8")
    monkeypatch.setattr(ih.sys, "platform", "win32")
    monkeypatch.setattr(ih.shutil, "which", lambda n: str(git_exe) if n == "git" else None)
    monkeypatch.setattr(ih, "_windows_registry_path_dirs", lambda: [])
    assert ih.find_bash() == str(bash_exe)


def test_find_bash_prefers_path_and_none_when_absent(monkeypatch, tmp_path):
    import install_helper as ih

    monkeypatch.setattr(ih.shutil, "which", lambda n: "/usr/bin/bash" if n == "bash" else None)
    assert ih.find_bash() == "/usr/bin/bash"
    monkeypatch.setattr(ih.shutil, "which", lambda n: None)
    monkeypatch.setattr(ih.sys, "platform", "win32")
    monkeypatch.setattr(ih, "_windows_registry_path_dirs", lambda: [])
    for var in ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)", "LOCALAPPDATA"):
        monkeypatch.delenv(var, raising=False)
    assert ih.find_bash() is None


def test_statusline_command_quotes_full_bash_path(tmp_path):
    from install_helper import statusline_command

    cmd = statusline_command(tmp_path, r"C:\Program Files\Git\bin\bash.exe")
    assert cmd.startswith('"C:\\Program Files\\Git\\bin\\bash.exe" "')
    assert cmd == statusline_command(tmp_path, r"C:\Program Files\Git\bin\bash.exe")
    # bare bash stays unquoted
    assert statusline_command(tmp_path).startswith('bash "')
