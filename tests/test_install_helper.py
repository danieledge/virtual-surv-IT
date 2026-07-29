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
