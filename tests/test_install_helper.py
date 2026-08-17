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
import subprocess
import sys
from pathlib import Path, PureWindowsPath
from types import SimpleNamespace

import pytest

from install_helper import _relocate_if_running_inside_target_repo as _real_relocate
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


def _timeout_runner(argv, **kw):
    raise subprocess.TimeoutExpired(argv, kw.get("timeout", 5))


def _stub_interpreters(monkeypatch, ih, winner="python3"):
    """Skip the real python3/python/py probe loop - always resolve to `winner` with no
    rejected candidates. Duplicated inline 15x before this helper existed."""
    monkeypatch.setattr(ih, "_check_interpreters", lambda order: ([], winner))


@pytest.fixture(autouse=True)
def _no_real_relocation(monkeypatch):
    """install_helper.py itself lives inside a real git clone (this repo) - without this,
    every test that reaches main()/_main() would trigger a REAL self-relocation subprocess
    spawn (2026-07-30 corp fix). The three tests that actually exercise relocation call
    _real_relocate (captured above, before this patch applies) directly instead."""
    import install_helper as ih

    monkeypatch.setattr(ih, "_relocate_if_running_inside_target_repo", lambda *a, **k: None)


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


def test_install_mode_offers_the_manual_clone_as_default(monkeypatch, tmp_path, capsys):
    """A new user who manually `git clone`d the repo and runs install_helper.py from
    inside it (no separate distributed installer exists) has no configured repo_path yet,
    so decide_mode picks 'install' - which used to always default to DEFAULT_CLONE_DIR,
    ignoring the perfectly good clone the script was already running from. Accepting
    that friendly default silently created a second, orphaned clone. The default must
    now be the script's own directory when that's already a real clone."""
    import install_helper as ih

    manual_clone = _fake_clone(tmp_path)
    monkeypatch.setattr(ih, "__file__", str(manual_clone / "install_helper.py"))
    _isolate_home(monkeypatch, tmp_path)  # no installer.json - "install" mode
    calls = []

    def runner(argv, cwd=None, timeout=300):
        calls.append([str(a) for a in argv])
        return _FakeProc(0)

    monkeypatch.setattr(ih, "run_cmd", runner)
    inst = ih.Installer(_args(yes=True), ih.Style(False), ih.marks())
    assert ih.decide_mode(None, inst.cfg) == "install"
    inst.mode = "install"
    inst.resolve_repo()
    out = capsys.readouterr().out
    assert inst.repo == manual_clone
    assert "Using existing clone" in out
    assert not any(len(c) >= 2 and c[0] == "git" and c[1] == "clone" for c in calls)


def test_install_mode_still_defaults_to_default_clone_dir_when_not_a_clone(
    monkeypatch, tmp_path, capsys
):
    """A genuinely fresh install (script run standalone, not from inside a clone) must
    keep offering DEFAULT_CLONE_DIR - the manual-clone fix must not change this case."""
    import install_helper as ih

    monkeypatch.setattr(ih, "__file__", str(tmp_path / "nowhere" / "install_helper.py"))
    monkeypatch.setattr(ih, "DEFAULT_CLONE_DIR", tmp_path / "default-clone")
    _isolate_home(monkeypatch, tmp_path)
    monkeypatch.setattr(ih, "run_cmd", lambda argv, cwd=None, timeout=300: _FakeProc(0))
    inst = ih.Installer(_args(yes=True), ih.Style(False), ih.marks())
    inst.mode = "install"
    inst.resolve_repo()
    assert inst.repo == tmp_path / "default-clone"


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


# --- --env-tuning: opt-in, upsert env-var merge (2026-08-07) -----------------------------


def test_merge_env_into_empty_settings():
    from install_helper import RECOMMENDED_ENV, merge_env

    settings, added, updated = merge_env({})
    assert settings["env"] == RECOMMENDED_ENV
    assert set(added) == set(RECOMMENDED_ENV)
    assert updated == []


def test_merge_env_preserves_unrelated_vars_updates_stale_ones_adds_missing():
    from install_helper import merge_env

    existing = {
        "env": {
            "MY_OWN_VAR": "keep-me",
            "API_TIMEOUT_MS": "60000",  # stale -> should be corrected
        },
        "permissions": {"allow": ["Bash(ruff *)"]},
    }
    settings, added, updated = merge_env(existing)
    env = settings["env"]
    assert env["MY_OWN_VAR"] == "keep-me"  # untouched
    assert env["API_TIMEOUT_MS"] == "1800000"  # corrected
    assert "API_TIMEOUT_MS" in updated
    assert "MY_OWN_VAR" not in updated and "MY_OWN_VAR" not in added
    assert "MAX_MCP_OUTPUT_TOKENS" in added  # was missing
    assert settings["permissions"] == {"allow": ["Bash(ruff *)"]}  # untouched


def test_merge_env_already_correct_reports_nothing():
    from install_helper import RECOMMENDED_ENV, merge_env

    settings, added, updated = merge_env({"env": dict(RECOMMENDED_ENV)})
    assert added == [] and updated == []
    assert settings["env"] == RECOMMENDED_ENV


def test_run_env_tuning_creates_settings_when_absent(tmp_path, capsys):
    import json as _json

    from install_helper import RECOMMENDED_ENV, Style, marks, run_env_tuning

    rc = run_env_tuning(tmp_path, Style(False), marks())
    assert rc == 0
    written = _json.loads((tmp_path / ".claude" / "settings.json").read_text(encoding="utf-8"))
    assert written["env"] == RECOMMENDED_ENV
    assert "backed up" not in capsys.readouterr().out  # nothing existed to back up


def test_run_env_tuning_backs_up_updates_and_preserves_unrelated(tmp_path, capsys):
    import json as _json

    from install_helper import Style, marks, run_env_tuning

    claude = tmp_path / ".claude"
    claude.mkdir()
    (claude / "settings.json").write_text(
        '{"env": {"MY_OWN_VAR": "keep-me", "API_TIMEOUT_MS": "60000"}, '
        '"permissions": {"deny": ["Read(x)"]}}',
        encoding="utf-8",
    )
    assert run_env_tuning(tmp_path, Style(False), marks()) == 0
    out = capsys.readouterr().out
    assert "backed up" in out
    assert "added" in out and "updated" in out
    backups = list(claude.glob("settings.json.bak-*"))
    assert len(backups) == 1
    written = _json.loads((claude / "settings.json").read_text(encoding="utf-8"))
    assert written["env"]["MY_OWN_VAR"] == "keep-me"  # preserved
    assert written["env"]["API_TIMEOUT_MS"] == "1800000"  # corrected
    assert written["permissions"] == {"deny": ["Read(x)"]}  # preserved
    # Second run: everything already correct, no new backup.
    assert run_env_tuning(tmp_path, Style(False), marks()) == 0
    assert "already set correctly" in capsys.readouterr().out
    assert len(list(claude.glob("settings.json.bak-*"))) == 1


def test_run_env_tuning_refuses_unparseable_settings(tmp_path, capsys):
    from install_helper import Style, marks, run_env_tuning

    claude = tmp_path / ".claude"
    claude.mkdir()
    (claude / "settings.json").write_text("{broken", encoding="utf-8")
    assert run_env_tuning(tmp_path, Style(False), marks()) == 1
    assert "refusing" in capsys.readouterr().out
    assert (claude / "settings.json").read_text(encoding="utf-8") == "{broken"  # untouched


# --- --env-tuning-betas: opt-in gateway-compat workaround (2026-08-07) --------------------


def test_merge_env_with_experimental_betas_entries():
    from install_helper import EXPERIMENTAL_BETAS_ENV, merge_env

    settings, added, updated = merge_env({}, entries=EXPERIMENTAL_BETAS_ENV)
    assert settings["env"] == {"CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS": "1"}
    assert added == ["CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS"]
    assert updated == []


def test_run_env_tuning_betas_creates_settings_when_absent(tmp_path, capsys):
    import json as _json

    from install_helper import EXPERIMENTAL_BETAS_ENV, Style, marks, run_env_tuning_betas

    rc = run_env_tuning_betas(tmp_path, Style(False), marks())
    assert rc == 0
    written = _json.loads((tmp_path / ".claude" / "settings.json").read_text(encoding="utf-8"))
    assert written["env"] == EXPERIMENTAL_BETAS_ENV
    out = capsys.readouterr().out
    assert "beta-fields-workaround" in out


def test_run_env_tuning_betas_does_not_touch_env_tuning_vars(tmp_path):
    """The two toggles are independent - turning on the beta-fields workaround must not
    also silently write the unrelated RECOMMENDED_ENV bundle, and vice versa."""
    import json as _json

    from install_helper import RECOMMENDED_ENV, Style, marks, run_env_tuning_betas

    run_env_tuning_betas(tmp_path, Style(False), marks())
    written = _json.loads((tmp_path / ".claude" / "settings.json").read_text(encoding="utf-8"))
    assert set(written["env"]) == {"CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS"}
    assert not any(k in written["env"] for k in RECOMMENDED_ENV)


def test_run_env_tuning_betas_refuses_unparseable_settings(tmp_path, capsys):
    from install_helper import Style, marks, run_env_tuning_betas

    claude = tmp_path / ".claude"
    claude.mkdir()
    (claude / "settings.json").write_text("{broken", encoding="utf-8")
    assert run_env_tuning_betas(tmp_path, Style(False), marks()) == 1
    assert "refusing" in capsys.readouterr().out
    assert (claude / "settings.json").read_text(encoding="utf-8") == "{broken"  # untouched


def test_run_configure_env_tuning_betas_on_by_default(tmp_path, monkeypatch):
    """2026-08-12 user request, reversing the prior stance: the beta-fields workaround
    (LLM-gateway compatibility) is now recommended ON by default, same as --env-tuning -
    accepting every recommended default under assume_yes applies it."""
    import install_helper as ih

    _isolate_home(monkeypatch, tmp_path)
    monkeypatch.setattr(ih, "run_cmd", lambda *a, **k: _FakeProc(0))
    ih.run_configure(tmp_path, ih.Style(False), ih.marks(), assume_yes=True)
    settings = json.loads((tmp_path / ".claude" / "settings.json").read_text())
    assert settings.get("env", {}).get("CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS") == "1"


# --- run_tool_cache_refresh: run automatically at the end of --configure (2026-08-07) -----


def test_run_tool_cache_refresh_success(tmp_path, monkeypatch, capsys):
    import install_helper as ih

    calls = []

    def fake_run_cmd(argv, cwd=None, **kw):
        calls.append((argv, cwd))
        return _FakeProc(0)

    monkeypatch.setattr(ih, "run_cmd", fake_run_cmd)
    monkeypatch.setattr(ih, "find_bash", lambda: "/usr/bin/bash")
    rc = ih.run_tool_cache_refresh(tmp_path, ih.Style(False), ih.marks())
    assert rc == 0
    assert "refreshed" in capsys.readouterr().out
    (argv, cwd) = calls[0]
    assert argv[0] == "/usr/bin/bash"
    assert argv[-1] == "--refresh"
    assert str(argv[1]).endswith("check-review-tools.sh")
    assert cwd == tmp_path.expanduser().resolve()  # cache lands in the TARGET project


def test_run_tool_cache_refresh_no_bash_is_soft_fail(tmp_path, monkeypatch, capsys):
    import install_helper as ih

    def boom(*a, **k):
        raise AssertionError("must not shell out when bash is unavailable")

    monkeypatch.setattr(ih, "run_cmd", boom)
    monkeypatch.setattr(ih, "find_bash", lambda: None)
    rc = ih.run_tool_cache_refresh(tmp_path, ih.Style(False), ih.marks())
    assert rc == 1
    assert "no bash found" in capsys.readouterr().out


def test_run_tool_cache_refresh_nonzero_exit_reported(tmp_path, monkeypatch, capsys):
    import install_helper as ih

    monkeypatch.setattr(ih, "run_cmd", lambda *a, **k: _FakeProc(3))
    monkeypatch.setattr(ih, "find_bash", lambda: "/usr/bin/bash")
    rc = ih.run_tool_cache_refresh(tmp_path, ih.Style(False), ih.marks())
    assert rc == 1
    assert "exited 3" in capsys.readouterr().out


def test_run_tool_cache_refresh_demo_writes_nothing(tmp_path, monkeypatch, capsys):
    import install_helper as ih

    def boom(*a, **k):
        raise AssertionError("demo mode must never actually shell out")

    monkeypatch.setattr(ih, "run_cmd", boom)
    monkeypatch.setattr(ih, "find_bash", lambda: "/usr/bin/bash")
    rc = ih.run_tool_cache_refresh(tmp_path, ih.Style(False), ih.marks(), demo=True)
    assert rc == 0
    assert "would run" in capsys.readouterr().out


def test_run_configure_always_refreshes_the_tool_cache(tmp_path, monkeypatch):
    """The 2026-08-07 user requirement, verbatim: "always run check-review-tools.sh
    --refresh when configuring the project via virt-surv configure" - no confirm() gate,
    unconditional, every --configure pass."""
    import install_helper as ih

    _isolate_home(monkeypatch, tmp_path)
    calls = []

    def fake_run_cmd(argv, cwd=None, **kw):
        calls.append(argv)
        return _FakeProc(0)

    monkeypatch.setattr(ih, "run_cmd", fake_run_cmd)
    ih.run_configure(tmp_path, ih.Style(False), ih.marks(), assume_yes=True)
    assert any("check-review-tools.sh" in str(a) for call in calls for a in call)


# --- Morgan's model, settings.json write + CLI wrapper (2026-08-03) ----------------------


def test_write_orchestrator_model_creates_settings_when_absent(tmp_path):
    import json as _json

    from install_helper import ORCHESTRATOR_MODEL_IDS, write_orchestrator_model

    ok, msg = write_orchestrator_model(tmp_path, "opus")
    assert ok
    assert f"model -> {ORCHESTRATOR_MODEL_IDS['opus']}" in msg
    written = _json.loads((tmp_path / ".claude" / "settings.json").read_text(encoding="utf-8"))
    assert written["model"] == ORCHESTRATOR_MODEL_IDS["opus"]  # exact ID, never the bare alias


def test_write_orchestrator_model_none_resets_to_documented_default(tmp_path):
    import json as _json

    from install_helper import (
        ORCHESTRATOR_MODEL_DEFAULT,
        ORCHESTRATOR_MODEL_IDS,
        write_orchestrator_model,
    )

    ok, _ = write_orchestrator_model(tmp_path, "opus")
    assert ok
    ok, msg = write_orchestrator_model(tmp_path, None)  # "reset"
    assert ok
    assert ORCHESTRATOR_MODEL_DEFAULT == "sonnet"
    assert f"model -> {ORCHESTRATOR_MODEL_IDS['sonnet']}" in msg
    written = _json.loads((tmp_path / ".claude" / "settings.json").read_text(encoding="utf-8"))
    assert written["model"] == ORCHESTRATOR_MODEL_IDS["sonnet"] == "claude-sonnet-5"


def test_write_orchestrator_model_default_targets_user_settings(monkeypatch, tmp_path):
    import json as _json

    import install_helper as ih

    fake_home_settings = tmp_path / "claude" / "settings.json"
    monkeypatch.setattr(ih, "user_settings_path", lambda: fake_home_settings)
    ok, msg = ih.write_orchestrator_model_default("sonnet")
    assert ok
    assert f"model -> {ih.ORCHESTRATOR_MODEL_IDS['sonnet']}" in msg
    written = _json.loads(fake_home_settings.read_text(encoding="utf-8"))
    assert written["model"] == ih.ORCHESTRATOR_MODEL_IDS["sonnet"]


def test_write_orchestrator_model_default_none_clears_key_rather_than_forcing_opus(
    monkeypatch, tmp_path
):
    """Unlike the per-project write, None at THIS scope means "no opinion", not "opus" -
    a human who never asked for a global override should get Claude Code's own default
    back, not have one silently imposed by a "reset" they didn't ask for at this scope."""
    import json as _json

    import install_helper as ih

    fake_home_settings = tmp_path / "claude" / "settings.json"
    monkeypatch.setattr(ih, "user_settings_path", lambda: fake_home_settings)
    ih.write_orchestrator_model_default("opus")  # writes ORCHESTRATOR_MODEL_IDS["opus"]
    ok, msg = ih.write_orchestrator_model_default(None)
    assert ok
    assert "cleared" in msg
    written = _json.loads(fake_home_settings.read_text(encoding="utf-8"))
    assert "model" not in written


def test_write_orchestrator_model_default_none_on_already_absent_key_is_a_noop(
    monkeypatch, tmp_path
):
    import install_helper as ih

    fake_home_settings = tmp_path / "claude" / "settings.json"
    monkeypatch.setattr(ih, "user_settings_path", lambda: fake_home_settings)
    ok, msg = ih.write_orchestrator_model_default(None)
    assert ok
    assert "no default model was set" in msg


def test_write_orchestrator_model_default_preserves_other_user_settings(monkeypatch, tmp_path):
    import json as _json

    import install_helper as ih

    fake_home_settings = tmp_path / "claude" / "settings.json"
    fake_home_settings.parent.mkdir(parents=True)
    fake_home_settings.write_text('{"statusLine": {"type": "command"}}', encoding="utf-8")
    monkeypatch.setattr(ih, "user_settings_path", lambda: fake_home_settings)
    ok, _ = ih.write_orchestrator_model_default("opus")
    assert ok
    written = _json.loads(fake_home_settings.read_text(encoding="utf-8"))
    assert written["model"] == ih.ORCHESTRATOR_MODEL_IDS["opus"]
    assert written["statusLine"] == {"type": "command"}  # preserved


def test_run_orchestrator_model_default_success(monkeypatch, tmp_path, capsys):
    import install_helper as ih

    fake_home_settings = tmp_path / "claude" / "settings.json"
    monkeypatch.setattr(ih, "user_settings_path", lambda: fake_home_settings)
    rc = ih.run_orchestrator_model_default("opus", ih.Style(False), ih.marks())
    assert rc == 0
    assert f"model -> {ih.ORCHESTRATOR_MODEL_IDS['opus']}" in capsys.readouterr().out


def test_run_orchestrator_model_default_refuses_bad_model_name(tmp_path, capsys):
    from install_helper import Style, marks, run_orchestrator_model_default

    rc = run_orchestrator_model_default("haiku", Style(False), marks())
    assert rc == 1
    assert "must be one of" in capsys.readouterr().out


def test_write_orchestrator_model_merges_and_preserves_other_keys(tmp_path):
    import json as _json

    claude = tmp_path / ".claude"
    claude.mkdir()
    (claude / "settings.json").write_text(
        '{"permissions": {"deny": ["Read(x)"]}, "statusLine": {"type": "command"}}',
        encoding="utf-8",
    )
    from install_helper import ORCHESTRATOR_MODEL_IDS, write_orchestrator_model

    ok, _ = write_orchestrator_model(tmp_path, "sonnet")
    assert ok
    written = _json.loads((claude / "settings.json").read_text(encoding="utf-8"))
    assert written["model"] == ORCHESTRATOR_MODEL_IDS["sonnet"]
    assert written["permissions"]["deny"] == ["Read(x)"]  # preserved
    assert written["statusLine"] == {"type": "command"}  # preserved
    assert (claude / "settings.json.bak").is_file()  # backed up


def test_write_orchestrator_model_refuses_unparseable_settings(tmp_path):
    claude = tmp_path / ".claude"
    claude.mkdir()
    (claude / "settings.json").write_text("{broken", encoding="utf-8")
    from install_helper import write_orchestrator_model

    ok, msg = write_orchestrator_model(tmp_path, "opus")
    assert not ok
    assert "refusing" in msg
    assert (claude / "settings.json").read_text(encoding="utf-8") == "{broken"  # untouched


def test_write_orchestrator_model_rejects_invalid_model_name(tmp_path):
    from install_helper import write_orchestrator_model

    with pytest.raises(ValueError):
        write_orchestrator_model(tmp_path, "haiku")  # not offered for Morgan (yet)


def test_run_orchestrator_model_success_notes_opus_has_no_tested_advantage(tmp_path, capsys):
    from install_helper import ORCHESTRATOR_MODEL_IDS, Style, marks, run_orchestrator_model

    rc = run_orchestrator_model(tmp_path, "opus", Style(False), marks())
    assert rc == 0
    out = capsys.readouterr().out
    assert f"model -> {ORCHESTRATOR_MODEL_IDS['opus']}" in out
    assert "testing to date" in out.lower()
    assert "critical" in out.lower()  # opus remains available for critical/high-stakes work


@pytest.mark.parametrize("model", ["sonnet", None], ids=["sonnet", "reset"])
def test_run_orchestrator_model_prints_no_opus_note(tmp_path, capsys, model):
    from install_helper import Style, marks, run_orchestrator_model

    rc = run_orchestrator_model(tmp_path, model, Style(False), marks())
    assert rc == 0
    assert "testing to date" not in capsys.readouterr().out.lower()


def test_run_orchestrator_model_refuses_bad_directory(tmp_path, capsys):
    from install_helper import Style, marks, run_orchestrator_model

    rc = run_orchestrator_model(tmp_path / "nope", "opus", Style(False), marks())
    assert rc == 1
    assert "not a directory" in capsys.readouterr().out


def test_run_orchestrator_model_refuses_bad_model_name(tmp_path, capsys):
    from install_helper import Style, marks, run_orchestrator_model

    rc = run_orchestrator_model(tmp_path, "haiku", Style(False), marks())
    assert rc == 1
    assert "must be one of" in capsys.readouterr().out


# --- exact model IDs, never the ambiguous "sonnet" alias (2026-08-06) ----------------------
#
# Live finding: Claude Code's generic "sonnet" alias resolves to a DIFFERENT actual model
# depending on API provider (Sonnet 5 direct API, Sonnet 4.6 on Claude Platform on AWS,
# Sonnet 4.5 on Bedrock/other platforms) - a project pinned to the bare alias could silently
# run an older model than intended. Every token this tool writes must resolve to an exact,
# provider-independent model ID.


def test_orchestrator_model_ids_are_exact_never_bare_aliases():
    from install_helper import ORCHESTRATOR_MODEL_IDS, ORCHESTRATOR_MODELS

    assert set(ORCHESTRATOR_MODELS) == {"opus", "sonnet", "sonnet-4-6"}
    assert ORCHESTRATOR_MODEL_IDS == {
        "opus": "claude-opus-5",
        "sonnet": "claude-sonnet-5",
        "sonnet-4-6": "claude-sonnet-4-6",
    }
    # None of the written values collapse back to a bare generic alias.
    for token, exact_id in ORCHESTRATOR_MODEL_IDS.items():
        assert exact_id not in ("opus", "sonnet"), f"{token} must write an exact ID, not an alias"


def test_write_orchestrator_model_sonnet_4_6_writes_exact_id(tmp_path):
    import json as _json

    from install_helper import ORCHESTRATOR_MODEL_IDS, write_orchestrator_model

    ok, msg = write_orchestrator_model(tmp_path, "sonnet-4-6")
    assert ok
    assert f"model -> {ORCHESTRATOR_MODEL_IDS['sonnet-4-6']}" in msg
    written = _json.loads((tmp_path / ".claude" / "settings.json").read_text(encoding="utf-8"))
    assert written["model"] == "claude-sonnet-4-6"


def test_run_orchestrator_model_default_accepts_sonnet_4_6(monkeypatch, tmp_path, capsys):
    import install_helper as ih

    fake_home_settings = tmp_path / "claude" / "settings.json"
    monkeypatch.setattr(ih, "user_settings_path", lambda: fake_home_settings)
    rc = ih.run_orchestrator_model_default("sonnet-4-6", ih.Style(False), ih.marks())
    assert rc == 0
    assert "claude-sonnet-4-6" in capsys.readouterr().out


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


def test_changelog_headline_survives_non_utf8_bytes(tmp_path):
    """Found in review, 2026-08-13: UnicodeDecodeError is NOT an OSError, so a
    CHANGELOG.md with invalid UTF-8 bytes used to crash the installer here (only OSError
    was caught) instead of the documented fail-soft None."""
    from install_helper import changelog_headline

    log = tmp_path / "CHANGELOG.md"
    log.write_bytes(b"## [0.33.1] - \xff\xfe not valid utf-8\n")
    assert changelog_headline(log, "0.33.1") is None


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
    """Fake a tty with scripted answers. Exhausted answers feed "q" (quit), not "" -
    2026-08-04: the top-level menu now loops back after every action instead of exiting
    (user request), so a real terminal's input() blocking-until-typed behaviour is safe,
    but a test fixture that ran out of scripted answers and got "" (a real, repeatable
    default choice on every call, since "" isn't consumed like a real answer would be)
    would loop forever. "q" makes an exhausted fixture behave like a user who's done,
    matching what every EXISTING test's finite answer list already implicitly meant.

    Also points ih.__file__ at a nonexistent "nowhere" directory: the script-root fallback
    in resolve_repo()/decide_mode() would otherwise find the REAL dev clone this test suite
    runs inside, since these tests execute from a real git checkout. Applying this
    unconditionally is a no-op for a test whose menu path never reaches that fallback - it
    used to be duplicated at 10 of 11 call sites by hand (a forgotten copy silently passed
    by accident on ambient repo state instead of failing)."""
    import sys as _sys

    import install_helper as ih

    monkeypatch.setattr(ih, "__file__", str(tmp_path / "nowhere" / "install_helper.py"))
    feed = iter(answers)
    monkeypatch.setattr(_sys, "stdin", _TtyStdin())
    monkeypatch.setattr("builtins.input", lambda prompt="": next(feed, "q"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))


def test_menu_setup_only_skips_sync_and_uses_clone_asis(monkeypatch, tmp_path, capsys):
    import install_helper as ih

    clone = _fake_clone(tmp_path)
    # Advanced submenu (6) -> Environment setup only (1), then prompt defaults
    _menu_session(monkeypatch, tmp_path, ["4", "1", "", ""])
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
    # Whole-token membership, not a raw joined-string search - the fake clone's own path
    # (".../clone") would otherwise false-positive a "clone" substring match.
    git_calls = [c for c in calls if c and c[0] == "git"]
    fetch_calls = [c for c in git_calls if "fetch" in c]
    # The upfront update-check fetches once before the menu (any option); option 2's
    # OWN plan must still never sync - no fetch of its own, no checkout, no clone.
    assert len(fetch_calls) == 1
    assert not any("checkout" in c or "clone" in c for c in git_calls)
    assert "Step 2 of 8" in out  # truthful numbering (+ guard cache + pending-hook-fixes steps)
    assert "code not updated" in out and "Code not updated" in out
    assert "Summon the team" in out


def test_upfront_update_check_prints_before_menu(monkeypatch, tmp_path, capsys):
    """The new-version notice must appear no matter which option the user picks - so it
    has to print BEFORE choose_action's menu, not buried inside a specific option."""
    import install_helper as ih

    clone = _fake_clone(tmp_path)  # local version 9.9.9, per _fake_clone
    _menu_session(monkeypatch, tmp_path, ["q"])
    cfg_dir = tmp_path / "xdg" / "virt-surv-it"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "installer.json").write_text(
        json.dumps({"repo_path": str(clone), "branch": "main"}), encoding="utf-8"
    )

    def runner(argv, cwd=None, timeout=300):
        joined = " ".join(str(a) for a in argv)
        if "plugin.json" in joined:
            return _FakeProc(0, stdout='{"version": "10.0.0"}')
        if "CHANGELOG" in joined:
            return _FakeProc(0, stdout="## [10.0.0] - d - Big new thing\n## [9.9.9] - d - Cur\n")
        return _FakeProc(0, stdout="")

    monkeypatch.setattr(ih, "run_cmd", runner)
    rc = ih.main([])
    out = capsys.readouterr().out
    assert rc == 0
    assert "newer version is available: 9.9.9 -> 10.0.0" in out
    assert "Big new thing" in out
    assert out.index("newer version") < out.index("What can I do for you?")


def test_upfront_update_check_silent_when_current(monkeypatch, tmp_path, capsys):
    """No notice, no noise, when the local clone is already on the latest version -
    routine runs must stay exactly as quiet as before this feature existed."""
    import install_helper as ih

    clone = _fake_clone(tmp_path)  # local version 9.9.9
    _menu_session(monkeypatch, tmp_path, ["q"])
    cfg_dir = tmp_path / "xdg" / "virt-surv-it"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "installer.json").write_text(
        json.dumps({"repo_path": str(clone), "branch": "main"}), encoding="utf-8"
    )
    monkeypatch.setattr(
        ih,
        "run_cmd",
        lambda argv, cwd=None, timeout=300: _FakeProc(
            0, stdout='{"version": "9.9.9"}' if "plugin.json" in " ".join(map(str, argv)) else ""
        ),
    )
    rc = ih.main([])
    out = capsys.readouterr().out
    assert rc == 0
    assert "newer version" not in out


def test_upfront_update_check_fails_soft_on_timeout(monkeypatch, tmp_path, capsys):
    """A slow/dead network must never delay or crash the menu - just skip the notice."""
    import install_helper as ih

    clone = _fake_clone(tmp_path)
    _menu_session(monkeypatch, tmp_path, ["q"])
    cfg_dir = tmp_path / "xdg" / "virt-surv-it"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "installer.json").write_text(
        json.dumps({"repo_path": str(clone), "branch": "main"}), encoding="utf-8"
    )

    def runner(argv, cwd=None, timeout=300):
        raise subprocess.TimeoutExpired(cmd=argv, timeout=timeout)

    monkeypatch.setattr(ih, "run_cmd", runner)
    rc = ih.main([])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Traceback" not in out
    assert "newer version" not in out


def test_menu_setup_only_without_clone_fails_cleanly(monkeypatch, tmp_path, capsys):
    import install_helper as ih

    # "6","1" runs the failing action, then the scripted answers are exhausted -
    # _menu_session feeds "q" from there (2026-08-04: the menu now loops back after
    # every action instead of exiting), so the SESSION still ends via an explicit quit.
    # rc reflects "did the session end cleanly", not "did the last action succeed" - the
    # human already saw the on-screen error; a scripting/CI caller uses the separate
    # --enable-project/--configure flag paths instead, which still propagate their own rc.
    _menu_session(monkeypatch, tmp_path, ["4", "1"])  # Advanced -> Environment setup only
    monkeypatch.setattr(ih, "run_cmd", lambda *a, **k: _FakeProc(0))
    rc = ih.main([])
    out = capsys.readouterr().out
    assert rc == 0
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


def test_menu_quit_after_real_action_does_not_claim_nothing_changed(monkeypatch, tmp_path, capsys):
    """Fable UX review, 2026-08-05: running Configure (a REAL write) then quitting
    printed "nothing changed" - readable as "your configuration was discarded"."""
    import install_helper as ih

    monkeypatch.setattr(ih, "run_configure", lambda *a, **k: 0)
    _menu_session(monkeypatch, tmp_path, ["2", str(tmp_path)])  # Configure, then exhausted -> "q"
    rc = ih.main([])
    out = capsys.readouterr().out
    assert rc == 0
    assert "nothing changed" not in out
    assert "See you next time" in out


def test_menu_quit_after_readonly_diagnostic_still_says_nothing_changed(
    monkeypatch, tmp_path, capsys
):
    """A read-only diagnostic (Diagnostics -> Check for updates) genuinely changes
    nothing - the reassurance must still be accurate after running one."""
    import install_helper as ih

    clone = _fake_full_clone(tmp_path / "clone")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    cfg_dir = tmp_path / "xdg" / "virt-surv-it"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "installer.json").write_text(
        json.dumps({"repo_path": str(clone), "branch": "main"}), encoding="utf-8"
    )
    monkeypatch.setattr(ih, "run_cmd", lambda *a, **k: _FakeProc(0, stdout=""))
    _menu_session(monkeypatch, tmp_path, ["3", "1"])  # Diagnostics -> Check for updates, then "q"
    rc = ih.main([])
    out = capsys.readouterr().out
    assert rc == 0
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


def test_sync_reexecs_when_install_helper_itself_changed(monkeypatch, tmp_path, capsys):
    """A pulled update that changes install_helper.py itself must restart the run on
    the new code - otherwise an installer-level fix never actually takes effect until
    a second, separate invocation."""
    import subprocess as sp

    import install_helper as ih

    clone = _fake_clone(tmp_path)
    (clone / "install_helper.py").write_text("NEW VERSION", encoding="utf-8")
    running_copy = tmp_path / "old_install_helper.py"
    running_copy.write_text("OLD VERSION", encoding="utf-8")
    monkeypatch.setattr(ih, "__file__", str(running_copy))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setattr(ih, "run_cmd", lambda argv, cwd=None, timeout=300: _FakeProc(0, stdout=""))
    spawned = {}

    def fake_run(argv, **kwargs):
        spawned["argv"] = argv
        return _FakeProc(7)

    monkeypatch.setattr(sp, "run", fake_run)
    inst = ih.Installer(_args(yes=True, branch="main"), ih.Style(False), ih.marks())
    inst.repo = clone
    inst.branch = "main"
    with pytest.raises(SystemExit) as exc_info:
        inst.sync_branch()
    assert exc_info.value.code == 7
    assert spawned["argv"][0] == sys.executable
    assert spawned["argv"][1] == str(clone / "install_helper.py")
    assert "--repo" in spawned["argv"] and str(clone) in spawned["argv"]
    assert "--branch" in spawned["argv"] and "main" in spawned["argv"]
    assert "--yes" in spawned["argv"]
    out = capsys.readouterr().out
    assert "restarting with the new version" in out


def test_sync_reexec_passes_resolved_mode_not_args_mode(monkeypatch, tmp_path):
    """Live-caught, 2026-08-04: a user who picks "1) Install or update" from the menu
    (rather than passing a positional install/update arg) has args.mode == None even
    though self.mode was already resolved to a concrete value earlier in run(). The
    OLD code passed args.mode straight through, so the relaunched child ALSO saw
    args.mode=None and landed back on the interactive menu instead of continuing
    straight through the full flow the user was already mid-way through - confusing,
    since nothing on screen explains that new menu options need a full install first.
    The fix threads self.mode (always concrete by the time a re-exec can fire) through
    explicitly."""
    import subprocess as sp

    import install_helper as ih

    clone = _fake_clone(tmp_path)
    (clone / "install_helper.py").write_text("NEW VERSION", encoding="utf-8")
    running_copy = tmp_path / "old_install_helper.py"
    running_copy.write_text("OLD VERSION", encoding="utf-8")
    monkeypatch.setattr(ih, "__file__", str(running_copy))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setattr(ih, "run_cmd", lambda argv, cwd=None, timeout=300: _FakeProc(0, stdout=""))
    spawned = {}
    monkeypatch.setattr(
        sp, "run", lambda argv, **k: spawned.setdefault("argv", argv) and _FakeProc(7)
    )
    # mode=None (as parse_args gives when the user picked from the menu, not a CLI arg) -
    # but self.mode gets resolved to "update" by run() before sync_branch ever executes,
    # exactly as it would on a real menu-driven run.
    inst = ih.Installer(_args(yes=True, branch="main", mode=None), ih.Style(False), ih.marks())
    inst.repo = clone
    inst.branch = "main"
    inst.mode = "update"
    with pytest.raises(SystemExit):
        inst.sync_branch()
    assert "update" in spawned["argv"]
    # The child must therefore skip the interactive menu (args.mode is no longer None)
    # and jump straight into the full flow - proven at the parse_args level:
    reparsed = ih.parse_args(spawned["argv"][2:])
    assert reparsed.mode == "update"


def test_sync_does_not_reexec_when_install_helper_unchanged(monkeypatch, tmp_path):
    """The common case (an update that doesn't touch install_helper.py, or no new
    commits at all) must never spawn a second process."""
    import subprocess as sp

    import install_helper as ih

    clone = _fake_clone(tmp_path)
    content = "SAME VERSION"
    (clone / "install_helper.py").write_text(content, encoding="utf-8")
    running_copy = tmp_path / "running_install_helper.py"
    running_copy.write_text(content, encoding="utf-8")
    monkeypatch.setattr(ih, "__file__", str(running_copy))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setattr(ih, "run_cmd", lambda argv, cwd=None, timeout=300: _FakeProc(0, stdout=""))
    monkeypatch.setattr(
        sp, "run", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not re-exec"))
    )
    inst = ih.Installer(_args(yes=True), ih.Style(False), ih.marks())
    inst.repo = clone
    inst.branch = "main"
    inst.sync_branch()  # no SystemExit, no assertion error


def test_sync_never_reexecs_in_demo_mode(monkeypatch, tmp_path):
    """Demo mode must never spawn a subprocess, full stop - even if a coincidental
    content mismatch would otherwise trigger the re-exec."""
    import subprocess as sp

    import install_helper as ih

    clone = _fake_clone(tmp_path)
    (clone / "install_helper.py").write_text("NEW", encoding="utf-8")
    running_copy = tmp_path / "old.py"
    running_copy.write_text("OLD", encoding="utf-8")
    monkeypatch.setattr(ih, "__file__", str(running_copy))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setattr(ih, "run_cmd", lambda argv, cwd=None, timeout=300: _FakeProc(0, stdout=""))
    monkeypatch.setattr(
        sp, "run", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not re-exec"))
    )
    inst = ih.Installer(_args(yes=True, demo=True), ih.Style(False), ih.marks())
    inst.demo = True
    inst.repo = clone
    inst.branch = "main"
    inst.sync_branch()  # no SystemExit, no assertion error


# --- guard-interpreter cache pre-warm (P1, 2026-07-31 corp report) ------------------------


def _fake_clone_with_guard(tmp_path):
    clone = _fake_clone(tmp_path)
    hooks = clone / ".claude" / "hooks"
    hooks.mkdir(parents=True)
    (hooks / "run-guard.sh").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    (hooks / "guard-raw-data.py").write_text("", encoding="utf-8")
    return clone


def test_prewarm_guard_cache_probes_directly_and_writes_the_cache(monkeypatch, tmp_path):
    """The chosen interpreter is probed as a DIRECT child of this process (not through a
    nested sh + exec chain) and the cache is written by this step itself."""
    import install_helper as ih

    clone = _fake_clone_with_guard(tmp_path)
    monkeypatch.setattr(ih.sys, "platform", "linux")
    monkeypatch.setattr(
        ih.shutil, "which", lambda name: f"/usr/bin/{name}" if name == "python3" else None
    )
    calls = []

    def runner(argv, cwd=None, timeout=300):
        calls.append(argv)
        return _FakeProc(0)

    monkeypatch.setattr(ih, "run_cmd", runner)
    inst = ih.Installer(_args(yes=True), ih.Style(False), ih.marks())
    inst.repo = clone
    inst.prewarm_guard_cache()
    assert inst.tracker.steps[-1][1] == "ok"
    assert "/usr/bin/python3" in inst.tracker.steps[-1][0]
    assert calls == [["/usr/bin/python3", "-c", calls[0][2]]]
    cache = clone / ".claude" / ".guard-interpreter"
    assert cache.read_text(encoding="utf-8") == "/usr/bin/python3"


def test_prewarm_guard_cache_windows_order_tries_python_before_python3(monkeypatch, tmp_path):
    """P2's Windows-aware order, mirrored here: python/py before python3, since python3
    is the likely Store-stub name there."""
    import install_helper as ih

    clone = _fake_clone_with_guard(tmp_path)
    monkeypatch.setattr(ih.sys, "platform", "win32")
    monkeypatch.setattr(ih.shutil, "which", lambda name: f"C:\\{name}.exe")
    tried = []

    def runner(argv, cwd=None, timeout=300):
        tried.append(argv[0])
        return _FakeProc(0)

    monkeypatch.setattr(ih, "run_cmd", runner)
    inst = ih.Installer(_args(yes=True), ih.Style(False), ih.marks())
    inst.repo = clone
    inst.prewarm_guard_cache()
    assert tried[0] == "C:\\python.exe"  # first candidate tried, not python3


def test_prewarm_guard_cache_skips_a_hanging_candidate_and_tries_the_next(monkeypatch, tmp_path):
    """A per-candidate timeout (or any failure) must move on to the next candidate, not
    give up or wait it out - this is the actual fix for the live report: the old design
    (shelling out to run-guard.sh through sh + exec) could hang for MINUTES on Windows
    because killing the direct `sh` child didn't reliably kill an orphaned, still-hung
    python3.exe grandchild. Probing candidates directly makes each one this process's own
    direct child, so a short timeout on a broken candidate reliably falls through."""
    import install_helper as ih

    clone = _fake_clone_with_guard(tmp_path)
    monkeypatch.setattr(ih.sys, "platform", "linux")
    monkeypatch.setattr(ih.shutil, "which", lambda name: f"/usr/bin/{name}")
    order = []

    def runner(argv, cwd=None, timeout=300):
        order.append(argv[0])
        if argv[0] == "/usr/bin/python3":
            raise subprocess.TimeoutExpired(cmd=argv, timeout=timeout)
        return _FakeProc(0)

    monkeypatch.setattr(ih, "run_cmd", runner)
    inst = ih.Installer(_args(yes=True), ih.Style(False), ih.marks())
    inst.repo = clone
    inst.prewarm_guard_cache()
    assert order[0] == "/usr/bin/python3"  # tried first, hung, moved on
    assert inst.tracker.steps[-1][1] == "ok"
    assert "/usr/bin/python" in inst.tracker.steps[-1][0]
    assert "/usr/bin/python3" not in inst.tracker.steps[-1][0]


def test_prewarm_guard_cache_skips_cleanly_when_nothing_works(monkeypatch, tmp_path):
    import install_helper as ih

    clone = _fake_clone_with_guard(tmp_path)
    monkeypatch.setattr(ih.shutil, "which", lambda name: None)
    inst = ih.Installer(_args(yes=True), ih.Style(False), ih.marks())
    inst.repo = clone
    inst.prewarm_guard_cache()
    assert inst.tracker.steps[-1][1] == "skip"
    assert not (clone / ".claude" / ".guard-interpreter").exists()


def test_prewarm_guard_cache_skips_cleanly_without_a_launcher(monkeypatch, tmp_path):
    """A clone predating the guard launcher (or a custom layout without one) must skip,
    not fail - the guard still self-warms on first real use exactly as before."""
    import install_helper as ih

    clone = _fake_clone(tmp_path)  # no .claude/hooks/ at all
    monkeypatch.setattr(
        ih, "run_cmd", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not run"))
    )
    inst = ih.Installer(_args(yes=True), ih.Style(False), ih.marks())
    inst.repo = clone
    inst.prewarm_guard_cache()
    assert inst.tracker.steps[-1][1] == "skip"


def test_prewarm_guard_cache_never_runs_in_demo_mode(monkeypatch, tmp_path):
    import install_helper as ih

    clone = _fake_clone_with_guard(tmp_path)
    monkeypatch.setattr(
        ih, "run_cmd", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not run"))
    )
    inst = ih.Installer(_args(yes=True, demo=True), ih.Style(False), ih.marks())
    inst.demo = True
    inst.repo = clone
    inst.prewarm_guard_cache()  # no assertion error - never reaches run_cmd
    assert inst.tracker.steps[-1][1] == "ok"


# ---- check_pending_hook_fixes: a read-only nudge, never a self-apply (ADR-002 rec 5) ------


def test_pending_hook_fixes_skips_cleanly_without_a_staged_dir(tmp_path):
    import install_helper as ih

    clone = _fake_clone(tmp_path)  # no scripts/staged_hooks/ at all
    inst = ih.Installer(_args(yes=True), ih.Style(False), ih.marks())
    inst.repo = clone
    inst.check_pending_hook_fixes()
    assert inst.tracker.steps[-1][1] == "skip"


def test_pending_hook_fixes_ok_when_staged_matches_live(tmp_path):
    """Staged and live byte-for-byte identical - reported ok, nothing to nudge about."""
    import install_helper as ih

    clone = _fake_clone(tmp_path)
    staged_dir = clone / "scripts" / "staged_hooks"
    staged_dir.mkdir(parents=True)
    (staged_dir / "guard-example.py").write_text("print('hook')\n", encoding="utf-8")
    live_dir = clone / ".claude" / "hooks"
    live_dir.mkdir(parents=True)
    (live_dir / "guard-example.py").write_text("print('hook')\n", encoding="utf-8")
    inst = ih.Installer(_args(yes=True), ih.Style(False), ih.marks())
    inst.repo = clone
    inst.check_pending_hook_fixes()
    assert inst.tracker.steps[-1][1] == "ok"


def test_pending_hook_fixes_flags_a_staged_but_unapplied_fix(tmp_path, capsys):
    """The actual case this exists for: a staged fix (e.g. the daemon launcher) that
    differs from - or is missing from - its live counterpart must be flagged, not
    silently applied, and the human-run command must be printed."""
    import install_helper as ih

    clone = _fake_clone(tmp_path)
    staged_dir = clone / "scripts" / "staged_hooks"
    staged_dir.mkdir(parents=True)
    (staged_dir / "run-guard.sh").write_text("# new daemon-aware launcher\n", encoding="utf-8")
    live_dir = clone / ".claude" / "hooks"
    live_dir.mkdir(parents=True)
    (live_dir / "run-guard.sh").write_text("# old launcher\n", encoding="utf-8")
    # a scripts/ tool staged fix with no live counterpart at all yet
    (staged_dir / "guard_daemon.py").write_text("# daemon\n", encoding="utf-8")
    inst = ih.Installer(_args(yes=True), ih.Style(False), ih.marks())
    inst.repo = clone
    inst.check_pending_hook_fixes()
    assert inst.tracker.steps[-1][1] == "skip"
    out = capsys.readouterr().out
    assert "run-guard.sh" in out
    assert "guard_daemon.py" in out
    assert "apply-outstanding.sh" in out


def test_pending_hook_fixes_skips_a_non_utf8_staged_file_instead_of_crashing(tmp_path):
    """Found in review, 2026-08-13: UnicodeDecodeError is NOT an OSError, so a staged (or
    live) file with invalid UTF-8 bytes used to crash this step instead of being skipped,
    contradicting its own docstring ('any read error on a given file just skips that one
    file')."""
    import install_helper as ih

    clone = _fake_clone(tmp_path)
    staged_dir = clone / "scripts" / "staged_hooks"
    staged_dir.mkdir(parents=True)
    (staged_dir / "guard-example.py").write_bytes(b"print('\xff\xfe not valid utf-8')\n")
    inst = ih.Installer(_args(yes=True), ih.Style(False), ih.marks())
    inst.repo = clone
    inst.check_pending_hook_fixes()  # must not raise
    assert inst.tracker.steps[-1][1] == "ok"  # the bad file was skipped, not flagged pending


def test_pending_hook_fixes_never_writes_anything(tmp_path):
    """The whole point: this step is read-only. A pending fix must never be copied into
    place by install_helper.py itself, no matter how convenient - ADR-002 rec 5's
    boundary must hold regardless of who is nominally driving the installer."""
    import install_helper as ih

    clone = _fake_clone(tmp_path)
    staged_dir = clone / "scripts" / "staged_hooks"
    staged_dir.mkdir(parents=True)
    (staged_dir / "run-guard.sh").write_text("# staged\n", encoding="utf-8")
    live_dir = clone / ".claude" / "hooks"
    live_dir.mkdir(parents=True)
    live_file = live_dir / "run-guard.sh"
    live_file.write_text("# live, unchanged\n", encoding="utf-8")
    inst = ih.Installer(_args(yes=True), ih.Style(False), ih.marks())
    inst.repo = clone
    inst.check_pending_hook_fixes()
    assert live_file.read_text(encoding="utf-8") == "# live, unchanged\n"


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


def test_merge_statusline_bare_substring_lookalike_still_conflicts(tmp_path):
    """Found in review, 2026-08-13: the 'ours-moved' check used to be a naive
    `"statusline.sh" in command` substring test, which false-positives on any unrelated
    script merely NAMED *statusline.sh (not ours, and not under a scripts/ dir) - that
    used to be silently overwritten instead of raising the conflict prompt."""
    from install_helper import current_statusline_command, merge_statusline, statusline_command

    lookalike = {"statusLine": {"type": "command", "command": 'bash "/home/user/my-statusline.sh"'}}
    settings, verdict = merge_statusline(lookalike, statusline_command(tmp_path))
    assert verdict == "conflict"
    assert settings["statusLine"]["command"] == 'bash "/home/user/my-statusline.sh"'
    assert current_statusline_command(settings) == 'bash "/home/user/my-statusline.sh"'


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
    # This test is about statusline_step()'s reaction to "no bash found", not about
    # find_bash()'s own internal search order (shutil.which -> git-root derivation ->
    # well-known install dirs -> a registry PATH re-read - the last stage is real,
    # intentional behaviour that survives Git for Windows' PATH gap, not something to
    # fake out here). Mocking shutil.which alone leaves that registry fallback live, so
    # on a box where it genuinely finds a bash.exe (e.g. a real PortableGit install) this
    # test's "bash absent" premise silently breaks. Mock find_bash directly instead,
    # matching the pattern used elsewhere in this file for the same reason.
    monkeypatch.setattr(ih, "find_bash", lambda: None)
    inst = ih.Installer(_args(), ih.Style(False), ih.marks(), subset="statusline")
    inst.repo = tmp_path
    inst.statusline_step()
    out = capsys.readouterr().out
    assert "Git Bash" in out
    assert not (tmp_path / "home" / ".claude").exists()  # nothing wired
    assert any(status == "skip" for _n, status, _d in inst.tracker.steps)


def test_full_plan_includes_alias_setup_and_machine_defaults_offer(monkeypatch, tmp_path):
    """2026-08-04 user request: the alias should be offered as part of a full install,
    the same way statusline already is - not only reachable as its own menu item.
    2026-08-07: machine_defaults_offer was added after it, as the new last step.
    2026-08-09: dashboard_step was added after THAT, as the new last step (a fresh
    dashboard link right after setup finishes). 2026-08-11: dashboard_step was pulled back
    OUT of the default full-install path and into its own standalone Advanced-submenu
    item (subset="dashboard") - a rebuild is a one-off action a user reaches for, not
    something every install/update should pay for unconditionally. Machine defaults is
    the last step again, as it was before dashboard_step existed. 2026-08-12: an
    onboarding UX audit found quick_setup_choice's own text promising "project
    enablement (permissions, env tuning, the LLM-gateway workaround, docx, Morgan's
    model)" as part of this run, but build_plan never actually called enable_step for
    subset="full" - the promise was never wired up. Fixed by adding it between alias
    setup and machine defaults, matching quick_setup_choice's own listed order.
    2026-08-15 user request: removed again - per-project enablement stays a genuinely
    separate step ('virt-surv configure'/'engage'/'onboard'), not bundled into the
    machine-level full install. quick_setup_choice's own promised-steps text was updated
    in the same change so it stops promising something this flow no longer does - the
    same class of drift the 2026-08-12 fix above closed, just in reverse this time."""
    import install_helper as ih

    inst = ih.Installer(_args(yes=True), ih.Style(False), ih.marks(), subset="full")
    plan = inst.build_plan()
    titles = [t() if callable(t) else t for t, _ in plan]
    assert "Alias setup" in titles
    assert "Enable for a project (optional)" not in titles
    assert "Machine defaults (optional)" in titles
    assert "Dashboard (optional)" not in titles  # no longer part of the default flow
    assert titles[-1] == "Machine defaults (optional)"  # last step
    assert titles.index("Alias setup") == titles.index("Machine defaults (optional)") - 1


def test_dashboard_subset_reaches_dashboard_step_standalone(monkeypatch, tmp_path):
    """The Advanced-submenu path (subset="dashboard") reaches dashboard_step on its own,
    not bundled with anything else - the standalone equivalent of --check-env/--selftest
    for the diagnostics, just for a build action instead of a check. It locates the clone
    first (same as "statusline") so self.repo is set before dashboard_step needs it - a
    live crash (2026-08-14, Windows: TypeError dividing None by "dashboard-ui") traced to
    this plan skipping straight to the build step with self.repo still None."""
    import install_helper as ih

    inst = ih.Installer(_args(yes=True), ih.Style(False), ih.marks(), subset="dashboard")
    plan = inst.build_plan()
    titles = [t() if callable(t) else t for t, _ in plan]
    assert titles == ["Locate existing clone", "Dashboard"]


def test_dashboard_step_skips_cleanly_when_repo_unset(tmp_path, capsys):
    """Live crash (2026-08-14, Windows temp-extraction run): dashboard_step used to
    dereference self.repo unconditionally (`self.repo / "dashboard-ui"`), so a run where
    the clone was never located (self.repo still None, its __init__ default) crashed with
    `TypeError: unsupported operand type(s) for /: 'NoneType' and 'str'` instead of
    reporting a clean skip like every other repo-dependent step in this class."""
    import install_helper as ih

    inst = ih.Installer(_args(yes=True), ih.Style(False), ih.marks(), subset="dashboard")
    assert inst.repo is None
    inst.dashboard_step()  # must not raise
    out = capsys.readouterr().out
    assert "no usable clone found" in out


def test_alias_step_skipped_by_default_on_yes_run(monkeypatch, tmp_path, capsys):
    """--yes must never touch the user's shell rc files unattended - opt-in only, even
    inside the full flow."""
    import install_helper as ih

    calls = []
    monkeypatch.setattr(ih, "run_setup_alias", lambda *a, **k: calls.append(a) or 0)
    inst = ih.Installer(_args(yes=True), ih.Style(False), ih.marks(), subset="full")
    inst.alias_step()
    out = capsys.readouterr().out
    assert calls == []
    assert "skipped" in out


def test_alias_step_declines_when_not_confirmed(monkeypatch, tmp_path, capsys):
    import install_helper as ih

    calls = []
    monkeypatch.setattr(ih, "run_setup_alias", lambda *a, **k: calls.append(a) or 0)
    monkeypatch.setattr(ih, "confirm", lambda *a, **k: False)
    inst = ih.Installer(_args(yes=False), ih.Style(False), ih.marks(), subset="full")
    inst.alias_step()
    assert calls == []


def test_alias_step_runs_setup_alias_when_confirmed(monkeypatch, tmp_path):
    import install_helper as ih

    calls = []
    monkeypatch.setattr(
        ih,
        "run_setup_alias",
        lambda style, mm, assume_yes=False, demo=False, repo_hint=None: (
            calls.append((assume_yes, demo)) or 0
        ),
    )
    monkeypatch.setattr(ih, "confirm", lambda *a, **k: True)
    inst = ih.Installer(_args(yes=False, demo=True), ih.Style(False), ih.marks(), subset="full")
    inst.alias_step()
    assert calls == [(False, True)]


def test_alias_step_auto_enabled_when_quick_defaults_chosen(monkeypatch, tmp_path):
    """2026-08-07 user request: an upfront "go with defaults vs manually configure"
    choice - choosing defaults means the alias step no longer asks "do you want this at
    all", it just does it."""
    import install_helper as ih

    calls = []

    def boom(*a, **k):
        raise AssertionError("must not ask - quick_defaults skips the outer gate")

    monkeypatch.setattr(
        ih,
        "run_setup_alias",
        lambda style, mm, assume_yes=False, demo=False, repo_hint=None: (
            calls.append((assume_yes, demo)) or 0
        ),
    )
    monkeypatch.setattr(ih, "confirm", boom)
    inst = ih.Installer(_args(yes=False, demo=True), ih.Style(False), ih.marks(), subset="full")
    inst.quick_defaults = True
    inst.alias_step()
    assert calls == [(False, True)]


def test_quick_setup_choice_yes_run_skips_question_and_defaults_true():
    import install_helper as ih

    inst = ih.Installer(_args(yes=True), ih.Style(False), ih.marks(), subset="full")
    inst.quick_setup_choice()
    assert inst.quick_defaults is True


def test_detect_claude_launch_command_returns_existing_without_prompting(monkeypatch, tmp_path):
    """Explicit 2026-08-14 user request: never reprompt once known."""
    import install_helper as ih

    cfg_file = tmp_path / "installer.json"
    cfg_file.write_text('{"claude_launch_command": "cc"}', encoding="utf-8")
    monkeypatch.setattr(ih, "config_path", lambda: cfg_file)

    def boom(*a, **k):
        raise AssertionError("must not prompt - the command is already known")

    monkeypatch.setattr(ih, "ask", boom)
    cmd = ih.detect_or_configure_claude_launch_command(ih.Style(False), ih.marks())
    assert cmd == "cc"


def test_detect_claude_launch_command_prompts_and_persists_when_unset(monkeypatch, tmp_path):
    import install_helper as ih

    cfg_file = tmp_path / "installer.json"
    monkeypatch.setattr(ih, "config_path", lambda: cfg_file)
    monkeypatch.setattr(ih.shutil, "which", lambda name: None)
    monkeypatch.setattr(ih, "ask", lambda *a, **k: "cc")
    cmd = ih.detect_or_configure_claude_launch_command(ih.Style(False), ih.marks())
    assert cmd == "cc"
    assert json.loads(cfg_file.read_text())["claude_launch_command"] == "cc"


def test_run_setup_alias_posix_line_has_go_branch(tmp_path, monkeypatch):
    """2026-08-15 user request: one alias, not two - 'go' is a branch inside virt-surv's
    own function body, not a separate alias. The POSIX form must be a real shell function
    (not a plain `alias`, which is pure text substitution with no way to branch on $1)."""
    import install_helper as ih

    home = _isolate_home_for_alias(monkeypatch, tmp_path, bashrc="")
    _stub_interpreters(monkeypatch, ih)
    rc = ih.run_setup_alias(ih.Style(False), ih.marks(), assume_yes=True)
    assert rc == 0
    content = (home / ".bashrc").read_text(encoding="utf-8")
    assert "virt-surv() {" in content
    assert '"$1" = "go"' in content
    assert "virt_team_launcher.py" in content
    # v5: the launch command is NOT baked - the function asks the launcher at every
    # 'go' and word-splits the answer via an unquoted $__vt_c expansion (live report
    # 2026-08-17: a config reset kept launching the old baked value, and a multi-word
    # command was baked as one unresolvable quoted word).
    assert "--launch-command" in content
    assert "$__vt_c ${__vt_d:+" in content  # unquoted on purpose - word-splitting IS the fix
    assert '"claude"' not in content  # nothing config-dependent baked any more
    assert "__vt_c=claude" in content  # only the hard fallback remains
    # The launcher's stdout is the FULL pre-seeded prompt, passed through verbatim as
    # one argument. History: 2026-08-15 the prefix was missing entirely; the fix baked
    # "/engage" into this line - but that bare spelling only exists repo-as-project, so
    # every real plugin install got "unknown command /engage" (live report 2026-08-16).
    # The run-mode-dependent spelling now lives in the launcher's _engage_command; the
    # shell function must never compose any part of the command itself.
    assert '${__vt_d:+"$__vt_d"}' in content
    assert "/engage" not in content


def test_run_setup_alias_powershell_line_has_go_branch(tmp_path, monkeypatch):
    import install_helper as ih

    monkeypatch.setattr(sys, "platform", "win32")
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    monkeypatch.setattr(ih, "detect_or_configure_claude_launch_command", lambda *a, **k: "claude")
    _stub_interpreters(monkeypatch, ih)
    profile = home / "Documents" / "PowerShell" / "Microsoft.PowerShell_profile.ps1"
    monkeypatch.setattr(ih, "_posix_shell_rc_candidates", lambda: [])
    monkeypatch.setattr(ih, "_powershell_profile_candidates", lambda: [("PowerShell 7+", profile)])
    monkeypatch.setattr(ih, "_verify_alias_line", lambda label, path, line, **k: (True, "resolves"))
    rc = ih.run_setup_alias(ih.Style(False), ih.marks(), assume_yes=True)
    assert rc == 0
    content = profile.read_text(encoding="utf-8")
    assert "function virt-surv {" in content
    assert '$args[0] -eq "go"' in content
    assert "virt_team_launcher.py" in content
    # v5: launch command resolved at run time and word-split (see the POSIX twin test).
    assert "--launch-command" in content
    assert "& $__vtCmd[0] @__vtCmdArgs" in content
    assert '& "claude"' not in content
    # Verbatim pass-through, same contract as POSIX - the run-mode-dependent command
    # spelling lives in the launcher, never baked here (2026-08-16 live report).
    assert '"$__vtDecision"' in content
    assert "/engage" not in content


def test_run_go_demo_never_launches(tmp_path, monkeypatch, capsys):
    """demo=True must preview and launch nothing - same contract as every other step."""
    import install_helper as ih

    monkeypatch.setattr(ih, "_resolve_repo_root", lambda hint=None: None)
    # No repo -> scripts_dir falls back to THIS repo's own scripts/ (install_helper.py's
    # real __file__), which genuinely has virt_team_launcher.py - forcing no interpreter
    # keeps this test isolated from a real subprocess spawn against that real script.
    monkeypatch.setattr(ih, "_check_interpreters", lambda names: ([], ""))
    monkeypatch.setattr(ih, "detect_or_configure_claude_launch_command", lambda *a, **k: "claude")

    def boom_exec(*a, **k):
        raise AssertionError("demo must never launch anything")

    monkeypatch.setattr(ih.os, "execvp", boom_exec)
    monkeypatch.setattr(
        ih.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no subprocess"))
    )
    rc = ih._run_go(tmp_path, ih.Style(False), ih.marks(), "🎩 ", demo=True)
    assert rc == 0
    assert "would launch" in capsys.readouterr().out


def test_run_go_prints_instructions_when_launch_command_not_a_real_executable(
    tmp_path, monkeypatch, capsys
):
    """The whole reason 'go' has to live in the shell function, not pure Python: a
    launch command that's a shell alias/function (e.g. 'cc') isn't visible to
    shutil.which and can't be exec'd from this process. Must degrade to printing the
    exact command to type, never crash or silently do nothing."""
    import install_helper as ih

    monkeypatch.setattr(ih, "_resolve_repo_root", lambda hint=None: None)
    monkeypatch.setattr(ih, "_check_interpreters", lambda names: ([], ""))
    monkeypatch.setattr(ih, "detect_or_configure_claude_launch_command", lambda *a, **k: "cc")
    monkeypatch.setattr(ih.shutil, "which", lambda name: None)

    def boom_exec(*a, **k):
        raise AssertionError("must not attempt to exec an unresolvable command")

    monkeypatch.setattr(ih.os, "execvp", boom_exec)
    rc = ih._run_go(tmp_path, ih.Style(False), ih.marks(), "🎩 ", demo=False)
    assert rc == 0
    out = capsys.readouterr().out
    assert "isn't a real executable" in out
    assert "cc" in out


def test_run_go_launches_a_real_executable(tmp_path, monkeypatch, capsys):
    """When the launch command DOES resolve (the common case - 'claude' itself is a
    real binary for most users), go actually launches it - execvp on POSIX."""
    import install_helper as ih

    monkeypatch.setattr(ih, "_resolve_repo_root", lambda hint=None: None)
    monkeypatch.setattr(ih, "_check_interpreters", lambda names: ([], ""))
    monkeypatch.setattr(ih, "detect_or_configure_claude_launch_command", lambda *a, **k: "claude")
    monkeypatch.setattr(ih.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(ih.os, "chdir", lambda p: None)
    calls = []
    monkeypatch.setattr(ih.os, "execvp", lambda cmd, argv: calls.append((cmd, argv)))
    ih._run_go(tmp_path, ih.Style(False), ih.marks(), "🎩 ", demo=False)
    # No meaningful return value to assert here: a REAL os.execvp never returns on
    # success (replaces the process entirely) - what matters is that it was called
    # correctly, which is exactly what the mock captures.
    assert calls == [("/usr/bin/claude", ["claude"])]  # no launcher script -> no decision arg


def test_run_go_passes_the_launcher_decision_through_verbatim(tmp_path, monkeypatch, capsys):
    """The launcher's stdout is the FULL pre-seeded prompt and _run_go must pass it
    through as one argument, composing nothing. Two live reports pin this from both
    sides: 2026-08-15 "missing the engage" (no prefix anywhere - a bare "--new" reached
    claude as a plain message), then 2026-08-16 "unknown command /engage" (the fix
    hardcoded the bare spelling here, which only exists repo-as-project - every real
    plugin install needs /compliance-surveillance-team:engage, so the spelling moved
    into the launcher's own _engage_command, computed per project). Uses a REAL
    subprocess (a fake launcher script) rather than mocking the subprocess call, so the
    actual argv construction downstream of a genuine decision is what's under test."""
    import install_helper as ih

    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "virt_team_launcher.py").write_text(
        "print('/compliance-surveillance-team:engage --new')\n", encoding="utf-8"
    )
    monkeypatch.setattr(ih, "_resolve_repo_root", lambda hint=None: tmp_path)
    monkeypatch.setattr(
        ih, "_check_interpreters", lambda names: ([(sys.executable, "ok", "3.x")], sys.executable)
    )
    monkeypatch.setattr(ih, "detect_or_configure_claude_launch_command", lambda *a, **k: "claude")
    monkeypatch.setattr(ih.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(ih.os, "chdir", lambda p: None)
    calls = []
    monkeypatch.setattr(ih.os, "execvp", lambda cmd, argv: calls.append((cmd, argv)))
    ih._run_go(tmp_path, ih.Style(False), ih.marks(), "🎩 ", demo=False)
    assert calls == [
        ("/usr/bin/claude", ["claude", "/compliance-surveillance-team:engage --new"])
    ]


def test_quick_setup_choice_real_tty_defaults_to_quick(monkeypatch):
    import install_helper as ih

    monkeypatch.setattr("builtins.input", lambda prompt="": "")  # blank = accept default
    monkeypatch.setattr(sys, "stdin", _TtyStdin())
    inst = ih.Installer(_args(yes=False), ih.Style(False), ih.marks(), subset="full")
    inst.quick_setup_choice()
    assert inst.quick_defaults is True


def test_quick_setup_choice_non_tty_defaults_to_manual():
    """Non-tty, non-`--yes` (e.g. piped input, a script): conservative False, so every
    downstream step falls back to its own already-safe non-tty handling."""
    import install_helper as ih

    inst = ih.Installer(_args(yes=False), ih.Style(False), ih.marks(), subset="full")
    inst.quick_setup_choice()
    assert inst.quick_defaults is False


def test_quick_setup_choice_manual_answer_is_respected(monkeypatch):
    import install_helper as ih

    monkeypatch.setattr("builtins.input", lambda prompt="": "n")
    monkeypatch.setattr(sys, "stdin", _TtyStdin())
    inst = ih.Installer(_args(yes=False), ih.Style(False), ih.marks(), subset="full")
    inst.quick_setup_choice()
    assert inst.quick_defaults is False


def test_machine_defaults_offer_skipped_on_yes_run(capsys):
    import install_helper as ih

    inst = ih.Installer(_args(yes=True), ih.Style(False), ih.marks(), subset="full")
    inst.machine_defaults_offer()
    assert "non-interactive" in capsys.readouterr().out


def test_fixbashrc_step_reports_ok_and_does_not_offer_a_fix_when_healthy(monkeypatch, capsys):
    """2026-08-14 user request: 'check if there is an issue with bash then auto apply if
    there is' - a healthy .bashrc must be reported and left alone, never routed into
    run_fix_bashrc at all."""
    import install_helper as ih

    monkeypatch.setattr(ih, "find_bash", lambda: "/bin/bash")
    monkeypatch.setattr(ih, "_check_shell_startup_time", lambda bash_path: ("OK", "0.05s"))
    called = []
    monkeypatch.setattr(ih, "run_fix_bashrc", lambda *a, **k: called.append(1) or 0)
    inst = ih.Installer(_args(yes=True), ih.Style(False), ih.marks(), subset="full")
    inst.fixbashrc_step()
    out = capsys.readouterr().out
    assert "0.05s" in out
    assert not called


def test_fixbashrc_step_applies_automatically_when_an_issue_is_found(monkeypatch, capsys):
    """The other half of the same request: a genuine issue must be fixed without a
    second, separate confirmation round-trip - choosing this menu item IS the consent."""
    import install_helper as ih

    monkeypatch.setattr(ih, "find_bash", lambda: "/bin/bash")
    monkeypatch.setattr(
        ih, "_check_shell_startup_time", lambda bash_path: ("WARN", "4.0s to source ~/.bashrc")
    )
    calls = []

    def fake_fix(style, marks, assume_yes=False, demo=False):
        calls.append((assume_yes, demo))
        return 0

    monkeypatch.setattr(ih, "run_fix_bashrc", fake_fix)
    inst = ih.Installer(_args(yes=True), ih.Style(False), ih.marks(), subset="full")
    inst.fixbashrc_step()
    out = capsys.readouterr().out
    assert "4.0s to source" in out
    assert calls == [(True, False)]  # assume_yes=True - no second confirmation prompt


def test_fixbashrc_step_demo_mode_still_previews_nothing_written(monkeypatch, capsys):
    import install_helper as ih

    monkeypatch.setattr(ih, "find_bash", lambda: "/bin/bash")
    monkeypatch.setattr(ih, "_check_shell_startup_time", lambda bash_path: ("ERROR", "12.0s"))
    calls = []

    def fake_fix(style, marks, assume_yes=False, demo=False):
        calls.append((assume_yes, demo))
        return 0

    monkeypatch.setattr(ih, "run_fix_bashrc", fake_fix)
    inst = ih.Installer(_args(yes=True, demo=True), ih.Style(False), ih.marks(), subset="full")
    inst.fixbashrc_step()
    assert calls == [(True, True)]  # demo propagated through to run_fix_bashrc


def test_machine_defaults_offer_declined_does_not_call_machine_defaults_step(monkeypatch):
    import install_helper as ih

    called = []
    monkeypatch.setattr(ih.Installer, "machine_defaults_step", lambda self: called.append(True))
    monkeypatch.setattr(ih, "confirm", lambda *a, **k: False)
    inst = ih.Installer(_args(yes=False), ih.Style(False), ih.marks(), subset="full")
    inst.machine_defaults_offer()
    assert called == []


def test_machine_defaults_offer_accepted_calls_machine_defaults_step(monkeypatch):
    import install_helper as ih

    called = []
    monkeypatch.setattr(ih.Installer, "machine_defaults_step", lambda self: called.append(True))
    monkeypatch.setattr(ih, "confirm", lambda *a, **k: True)
    inst = ih.Installer(_args(yes=False), ih.Style(False), ih.marks(), subset="full")
    inst.machine_defaults_offer()
    assert called == [True]


def test_dashboard_step_skips_when_dashboard_ui_missing(tmp_path, capsys):
    import install_helper as ih

    inst = ih.Installer(_args(yes=True), ih.Style(False), ih.marks(), subset="full")
    inst.repo = tmp_path  # no dashboard-ui/ subdir created
    inst.dashboard_step()
    out = capsys.readouterr().out
    assert "not present in this checkout" in out


def test_dashboard_step_skips_when_node_missing(monkeypatch, tmp_path, capsys):
    import install_helper as ih

    (tmp_path / "dashboard-ui").mkdir()
    monkeypatch.setattr(ih, "_find_node", lambda: None)
    inst = ih.Installer(_args(yes=True), ih.Style(False), ih.marks(), subset="full")
    inst.repo = tmp_path
    inst.dashboard_step()
    out = capsys.readouterr().out
    assert "Node/npm not found" in out


def test_dashboard_step_builds_and_reports_the_output_path(monkeypatch, tmp_path, capsys):
    import install_helper as ih

    ui_dir = tmp_path / "dashboard-ui"
    (ui_dir / "node_modules").mkdir(parents=True)  # skip npm install
    monkeypatch.setattr(ih, "_find_node", lambda: "/usr/bin/node")
    monkeypatch.setattr(ih.shutil, "which", lambda name: "/usr/bin/npm" if "npm" in name else None)
    calls = []

    def fake_run_cmd(argv, cwd=None, timeout=300):
        calls.append((list(argv), cwd))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(ih, "run_cmd", fake_run_cmd)
    inst = ih.Installer(_args(yes=True), ih.Style(False), ih.marks(), subset="full")
    inst.repo = tmp_path
    inst.dashboard_step()
    out = capsys.readouterr().out
    assert "Dashboard" in out
    assert str(ui_dir / "dist" / "index.html") in out
    # npm install skipped (node_modules already present), only the build ran
    assert len(calls) == 1
    assert calls[0][0][-2:] == ["run", "dashboard"]
    assert calls[0][1] == ui_dir


def test_dashboard_step_never_fatal_on_build_failure(monkeypatch, tmp_path, capsys):
    import install_helper as ih

    ui_dir = tmp_path / "dashboard-ui"
    (ui_dir / "node_modules").mkdir(parents=True)
    monkeypatch.setattr(ih, "_find_node", lambda: "/usr/bin/node")
    monkeypatch.setattr(ih.shutil, "which", lambda name: "/usr/bin/npm" if "npm" in name else None)
    monkeypatch.setattr(ih, "run_cmd", lambda *a, **k: SimpleNamespace(returncode=1))
    inst = ih.Installer(_args(yes=True), ih.Style(False), ih.marks(), subset="full")
    inst.repo = tmp_path
    inst.dashboard_step()  # must not raise InstallAbort
    out = capsys.readouterr().out
    assert "build failed" in out


def test_alias_step_asks_when_manual_configure_chosen(monkeypatch, tmp_path):
    """quick_defaults False (manual walkthrough) restores the ORIGINAL per-step question,
    including its original True-on-a-real-tty default."""
    import install_helper as ih

    monkeypatch.setattr(ih, "confirm", lambda *a, **k: False)
    monkeypatch.setattr(sys, "stdin", _TtyStdin())
    inst = ih.Installer(_args(yes=False, demo=True), ih.Style(False), ih.marks(), subset="full")
    assert inst.quick_defaults is False  # the __init__ default
    calls = []
    monkeypatch.setattr(ih, "run_setup_alias", lambda *a, **k: calls.append(a) or 0)
    inst.alias_step()
    assert calls == []  # confirm() declined -> never called


def test_statusline_step_auto_enabled_when_quick_defaults_chosen(monkeypatch, tmp_path):
    """Same 2026-08-07 request, for the status line."""
    import install_helper as ih

    _isolate_home(monkeypatch, tmp_path)
    monkeypatch.setattr(ih, "find_bash", lambda: "/usr/bin/bash")

    def boom(*a, **k):
        raise AssertionError("must not ask - quick_defaults skips the outer gate")

    monkeypatch.setattr(ih, "confirm", boom)
    inst = ih.Installer(_args(yes=False, demo=True), ih.Style(False), ih.marks(), subset="full")
    inst.repo = tmp_path
    inst.quick_defaults = True
    inst.statusline_step()
    out_ok = any(
        name == "Status line" and status == "ok" for name, status, _d in inst.tracker.steps
    )
    assert out_ok


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


def test_atomic_write_text_leaves_target_untouched_if_replace_fails(tmp_path, monkeypatch):
    """Found in review, 2026-08-13: the settings.json writers (run_permissions,
    _run_env_upsert, statusline_step, _write_model_to_settings_file, _write_json_backup)
    used to write straight to the target path - an interrupted write could leave it
    truncated/corrupt. _atomic_write_text writes to a temp file first and only replaces
    the target in one atomic os.replace call, same pattern as save_config/_write_state -
    if the replace step never happens, the original content must survive untouched."""
    import install_helper as ih

    target = tmp_path / "settings.json"
    target.write_text('{"original": true}', encoding="utf-8")

    def boom(_src, _dst):
        raise OSError("simulated interruption before replace")

    monkeypatch.setattr(ih.os, "replace", boom)
    with pytest.raises(OSError):
        ih._atomic_write_text(target, '{"new": true}')
    assert target.read_text(encoding="utf-8") == '{"original": true}'


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
    _menu_session(monkeypatch, tmp_path, ["3", "1"])  # Diagnostics -> Check for updates
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
    _menu_session(monkeypatch, tmp_path, ["3", "1"])  # Diagnostics -> Check for updates
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

    _menu_session(monkeypatch, tmp_path, ["3", "1"])  # Diagnostics -> Check for updates
    monkeypatch.setattr(ih, "run_cmd", lambda *a, **k: _FakeProc(0, stdout=""))
    rc = ih.main([])
    out = capsys.readouterr().out
    assert rc == 0
    assert "no usable clone" in out and "Traceback" not in out


# ------------------------------------------------------ stale-PATH claude discovery


@pytest.fixture
def _claude_cache_cleared():
    """Clear ih._claude_cache before AND after the test, via yield - not a manual
    end-of-test call, which skips on assertion failure and can leak into whichever test
    runs next in the same process (test-order-dependent flakiness)."""
    import install_helper as ih

    ih._claude_cache = None
    yield
    ih._claude_cache = None


def test_find_claude_prefers_live_path(monkeypatch, _claude_cache_cleared):
    import install_helper as ih

    monkeypatch.setattr(ih.shutil, "which", lambda n: "/usr/bin/claude")
    assert ih.find_claude(refresh=True) == ("/usr/bin/claude", "path")


def test_find_claude_falls_back_to_known_location(monkeypatch, tmp_path, _claude_cache_cleared):
    """CLI installed to ~/.local/bin but the session PATH is stale: which() misses,
    the documented location is probed and wins."""
    import install_helper as ih

    home = tmp_path / "home"
    binary = home / ".local" / "bin" / ("claude.exe" if ih.sys.platform == "win32" else "claude")
    binary.parent.mkdir(parents=True)
    binary.write_text("", encoding="utf-8")
    monkeypatch.setattr(ih.shutil, "which", lambda n: None)
    monkeypatch.setattr(ih.Path, "home", staticmethod(lambda: home))
    path, how = ih.find_claude(refresh=True)
    assert path == str(binary)
    assert how == "known-location"


def test_find_claude_windows_registry_catches_stale_session(
    monkeypatch, tmp_path, _claude_cache_cleared
):
    """The corporate case: installed a minute ago, terminal opened an hour ago. The
    registry PATH (what a NEW shell would see) locates it."""
    import install_helper as ih

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


def test_find_claude_not_found_never_raises(monkeypatch, tmp_path, _claude_cache_cleared):
    import install_helper as ih

    monkeypatch.setattr(ih.shutil, "which", lambda n: None)
    monkeypatch.setattr(ih.Path, "home", staticmethod(lambda: tmp_path / "nohome"))
    monkeypatch.setattr(ih, "_windows_registry_path_dirs", lambda: ["Z:\\missing"])
    assert ih.find_claude(refresh=True) == (None, "")


def test_find_claude_memoises_registry_probe(monkeypatch, tmp_path, _claude_cache_cleared):
    """Repeated launches (every run_cmd resolves argv[0]) must not re-read the registry."""
    import install_helper as ih

    calls = []
    monkeypatch.setattr(ih.shutil, "which", lambda n: None)
    monkeypatch.setattr(ih.Path, "home", staticmethod(lambda: tmp_path / "nohome"))
    monkeypatch.setattr(ih.sys, "platform", "win32")
    monkeypatch.setattr(ih, "_windows_registry_path_dirs", lambda: calls.append(1) or [])
    ih.find_claude(refresh=True)
    ih.find_claude()
    ih.find_claude()
    assert len(calls) == 1


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


def test_find_claude_npm_package_bin_dir(monkeypatch, tmp_path, _claude_cache_cleared):
    """The reported corporate layout: no shims on PATH, the CLI living only in
    APPDATA\\npm\\node_modules\\@anthropic-ai\\claude-code\\bin."""
    import install_helper as ih

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


def test_other_subprocess_call_sites_also_pin_utf8_replace(monkeypatch, tmp_path):
    """Found in review, 2026-08-13: the same cp1252-on-Windows lesson run_cmd already
    applies (see test above) was missing from ~8 other subprocess.run/Popen call sites,
    each using bare text=True - a corporate Windows locale could raise UnicodeDecodeError
    reading a tool's non-cp1252 output (emoji, box-drawing, UTF-8) at any of them. Every
    site fixed must now record encoding='utf-8', errors='replace', and never bare text.
    The one Popen call site (run_daemon_start_diagnostic) is covered separately below."""
    import install_helper as ih

    seen = []

    def fake_run(*args, **kwargs):
        seen.append(kwargs)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(ih.subprocess, "run", fake_run)

    ih.run_list_engagements(tmp_path, ih.Style(False), ih.marks())
    ih.run_archive_engagements(tmp_path, ih.Style(False), ih.marks())
    ih._check_interpreters(["python3"])
    list(ih.probe_analyser_output(tmp_path, only={"ruff"}))
    monkeypatch.setattr(ih.shutil, "which", lambda n: f"/usr/bin/{n}")
    ih._check_repo_py_syntax("/usr/bin/python3", tmp_path)
    monkeypatch.setattr(ih.sys, "platform", "win32")
    ih._powershell_profile_candidates()
    monkeypatch.setattr(ih.sys, "platform", "linux")
    ih._verify_alias_line("bash", tmp_path / ".bashrc", "alias virt-surv='echo hi'")

    assert len(seen) >= 6
    for kwargs in seen:
        assert kwargs.get("encoding") == "utf-8"
        assert kwargs.get("errors") == "replace"
        assert "text" not in kwargs


def test_daemon_foreground_spawn_popen_also_pins_utf8_replace(tmp_path, monkeypatch):
    """Same finding as above, isolated to run_daemon_start_diagnostic's foreground Popen
    call - the one call site using subprocess.Popen directly rather than subprocess.run."""
    import install_helper as ih

    _isolate_home(monkeypatch, tmp_path)
    _make_fake_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "guard_daemon.py").write_text("", encoding="utf-8")

    seen = []

    def fake_popen(*args, **kwargs):
        seen.append(kwargs)
        raise OSError("stop before it actually spawns anything")

    monkeypatch.setattr(ih.subprocess, "Popen", fake_popen)
    ih.run_daemon_start_diagnostic(ih.Style(False), ih.marks(), repo_hint=str(tmp_path))
    assert seen  # the foreground Popen call was reached
    assert seen[0]["encoding"] == "utf-8"
    assert seen[0]["errors"] == "replace"
    assert "text" not in seen[0]


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
    assert km[MARKETPLACE]["source"] == {"source": "directory", "path": str(repo)}
    assert km[MARKETPLACE]["installLocation"] == str(repo)
    ip = json.loads((claude_dir / "plugins" / "installed_plugins.json").read_text())
    assert ip["version"] == 2
    entry = ip["plugins"][PLUGIN_ID][0]
    assert entry["scope"] == "user" and entry["installPath"] == str(repo)
    assert entry["version"] == "0.33.1"
    st = json.loads((claude_dir / "settings.json").read_text())
    assert st["enabledPlugins"][PLUGIN_ID] is True
    assert st["enabledPlugins"]["other@other"] is True and st["model"] == "opus"
    assert st["extraKnownMarketplaces"][MARKETPLACE]["source"] == {
        "source": "directory",
        "path": str(repo),
    }
    assert len(touched) == 3
    # pre-existing files got backups
    assert (claude_dir / "settings.json.bak").is_file()


def test_register_plugin_directly_from_empty_claude_dir(tmp_path):
    from install_helper import PLUGIN_ID, register_plugin_directly

    claude_dir = tmp_path / ".claude"
    register_plugin_directly(tmp_path / "clone", claude_dir, None)
    ip = json.loads((claude_dir / "plugins" / "installed_plugins.json").read_text())
    assert ip["plugins"][PLUGIN_ID][0]["version"] == "unknown"


def test_register_plugin_directly_refuses_unparseable_settings(tmp_path):
    """Found in review, 2026-08-13: unlike run_permissions/_write_model_to_settings_file
    (which both refuse on unparseable JSON rather than clobber it), this call site used
    to read settings.json via _read_json_dict, whose garbage-becomes-{} fallback would
    have silently discarded the file's existing content on write. Must now raise
    InstallAbort and leave every file - including the marketplace/plugin ones - untouched."""
    from install_helper import InstallAbort, register_plugin_directly

    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir(parents=True)
    (claude_dir / "settings.json").write_text("{not valid json", encoding="utf-8")
    with pytest.raises(InstallAbort):
        register_plugin_directly(tmp_path / "clone", claude_dir, None)
    # No partial state: the marketplace/plugin files were never written either.
    assert not (claude_dir / "plugins" / "known_marketplaces.json").exists()
    assert not (claude_dir / "plugins" / "installed_plugins.json").exists()
    # The corrupt settings.json itself is untouched, not overwritten.
    assert (claude_dir / "settings.json").read_text(encoding="utf-8") == "{not valid json"


def _blocked_by_oserror(argv, **kw):
    raise OSError("[WinError 1260] This program is blocked by group policy")


def _blocked_by_policy_stderr(argv, **kw):
    return _proc(returncode=1, stderr="This program is blocked by group policy\n")


@pytest.mark.parametrize(
    "runner", [_blocked_by_oserror, _blocked_by_policy_stderr], ids=["oserror", "stderr-text"]
)
def test_run_enable_project_falls_back_to_direct_write_on_policy_block(tmp_path, capsys, runner):
    """Two distinct entry points into the same fallback: AppLocker refusing the CLI
    launch outright (OSError) vs. the CLI running but reporting the block on stderr -
    both must write enabledPlugins straight into the project settings, exactly what the
    CLI would have done."""
    from install_helper import PLUGIN_ID, Style, run_enable_project

    project = tmp_path / "proj"
    project.mkdir()

    rc = run_enable_project(project, Style(enabled=False), {"ok": "OK", "fail": "X"}, runner=runner)
    assert rc == 0
    settings = json.loads((project / ".claude" / "settings.json").read_text())
    assert settings["enabledPlugins"][PLUGIN_ID] is True
    assert "written directly" in capsys.readouterr().out


def test_run_enable_project_direct_write_refuses_unparseable_settings(tmp_path, capsys):
    """Found in review, 2026-08-13: the group-policy-blocked fallback used to use
    _read_json_dict (garbage-becomes-{}) and would have silently overwritten a corrupt
    project settings.json instead of refusing, unlike run_permissions' identical fallback
    for the same file."""
    from install_helper import Style, run_enable_project

    project = tmp_path / "proj"
    (project / ".claude").mkdir(parents=True)
    (project / ".claude" / "settings.json").write_text("{not valid json", encoding="utf-8")
    rc = run_enable_project(
        project, Style(enabled=False), {"ok": "OK", "fail": "X"}, runner=_blocked_by_oserror
    )
    assert rc == 1
    assert "refusing to touch it" in capsys.readouterr().out
    assert (project / ".claude" / "settings.json").read_text(encoding="utf-8") == "{not valid json"


def test_run_enable_project_ordinary_failure_still_fails(tmp_path):
    from install_helper import Style, run_enable_project

    project = tmp_path / "proj"
    project.mkdir()
    runner = lambda argv, **kw: _proc(returncode=1, stderr="No such plugin\n")  # noqa: E731
    rc = run_enable_project(project, Style(enabled=False), {"ok": "OK", "fail": "X"}, runner=runner)
    assert rc == 1
    assert not (project / ".claude" / "settings.json").exists()


def test_run_enable_project_already_enabled_is_ok_not_fail(tmp_path, capsys):
    """2026-08-07 user report: "already enabled/installed" was being reported as a
    failure - it's the desired end state, informational only."""
    from install_helper import Style, run_enable_project

    project = tmp_path / "proj"
    project.mkdir()
    runner = lambda argv, **kw: _proc(  # noqa: E731
        returncode=1, stderr="Error: plugin is already enabled for this scope\n"
    )
    rc = run_enable_project(project, Style(enabled=False), {"ok": "OK", "fail": "X"}, runner=runner)
    assert rc == 0
    assert "already enabled" in capsys.readouterr().out
    assert not (project / ".claude" / "settings.json").exists()  # nothing needed writing


def test_plugin_step_shows_a_wait_message_before_the_blocking_call(monkeypatch, capsys):
    """Live report, 2026-08-12: the plugin install/update call is fully blocking (up to
    a 300s timeout) with nothing printed in between - reads as hung on a slow network or
    corporate proxy. Must print a wait message BEFORE the blocking call, not after, and
    never in demo mode (nothing there actually blocks)."""
    import install_helper as ih

    monkeypatch.setattr(ih, "run_cmd", lambda *a, **k: _proc(returncode=0))
    inst = ih.Installer(_args(yes=True), ih.Style(False), ih.marks(), subset="full")
    inst.mode = "install"
    inst.plugin()
    assert "can take a moment" in capsys.readouterr().out


def test_plugin_step_never_shows_wait_message_in_demo_mode(monkeypatch, capsys):
    import install_helper as ih

    monkeypatch.setattr(ih, "run_cmd", lambda *a, **k: _proc(returncode=0))
    inst = ih.Installer(_args(yes=True, demo=True), ih.Style(False), ih.marks(), subset="full")
    inst.mode = "install"
    inst.plugin()
    assert "can take a moment" not in capsys.readouterr().out


def test_installer_plugin_step_already_installed_is_ok_not_fail(monkeypatch, tmp_path, capsys):
    """Same 2026-08-07 fix, for the full-run install path: `claude plugin install`
    reporting "already installed" must not abort the whole run via step_fail's fatal
    default (it would otherwise raise InstallAbort and stop everything after it)."""
    import install_helper as ih

    def fake_run_cmd(argv, cwd=None, **kw):
        if "uninstall" in argv:
            return _proc(returncode=1, stderr="not installed\n")
        if "install" in argv:
            return _proc(returncode=1, stderr="Error: plugin is already installed\n")
        return _proc(returncode=0)

    monkeypatch.setattr(ih, "run_cmd", fake_run_cmd)
    inst = ih.Installer(_args(yes=True), ih.Style(False), ih.marks(), subset="full")
    inst.mode = "install"
    inst.plugin()  # must not raise InstallAbort
    assert any(status == "ok" for _name, status, _detail in inst.tracker.steps)
    assert not any(status == "fail" for _name, status, _detail in inst.tracker.steps)
    assert "already installed" in capsys.readouterr().out


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


def test_statusline_script_forces_utf8_python():
    """Windows pipes cp1252-encode Python stdout; without PYTHONUTF8 the emoji render
    raised and every statusline fell to the static no-stats fallback (2026-07-30)."""
    text = (Path(__file__).resolve().parents[1] / "scripts" / "statusline.sh").read_text(
        encoding="utf-8"
    )
    line = next(ln for ln in text.splitlines() if '"$PY_BIN" - "$INPUT"' in ln)
    assert "PYTHONUTF8=1" in line and "PYTHONIOENCODING=utf-8" in line


# ------------------------------------------------ guard-interpreter cache pre-seed


def test_write_guard_interpreter_cache_uses_sys_executable(tmp_path):
    from install_helper import write_guard_interpreter_cache

    write_guard_interpreter_cache(tmp_path)
    cache = tmp_path / ".claude" / ".guard-interpreter"
    assert cache.is_file()
    # The cache is deliberately forward-slash normalized (see the sibling
    # ...normalizes_windows_backslashes test below) - compare against that form, not
    # the raw sys.executable, which is still native-separated on Windows.
    assert cache.read_text(encoding="utf-8") == PureWindowsPath(sys.executable).as_posix()


def test_write_guard_interpreter_cache_normalizes_windows_backslashes(tmp_path, monkeypatch):
    """Live corp-Windows report, 2026-08-12: sys.executable there is backslash-separated
    (e.g. "C:\\Program Files\\PSF\\Python312\\python.EXE"), and every consumer of this
    cache tests it with `command -v "$cached"` under Git Bash/MSYS, where forward-slash
    absolute paths are the reliable form - a cached path was observed still falling
    through to the full discovery loop even after the (separate) word-splitting bug was
    fixed. Platform-independent to test: PureWindowsPath parses the literal string
    regardless of the host OS actually running this test."""
    import install_helper as ih

    monkeypatch.setattr(ih.sys, "executable", r"C:\Program Files\PSF\Python312\python.EXE")
    ih.write_guard_interpreter_cache(tmp_path)
    cache = tmp_path / ".claude" / ".guard-interpreter"
    assert cache.read_text(encoding="utf-8") == "C:/Program Files/PSF/Python312/python.EXE"


def test_write_guard_interpreter_cache_best_effort_on_unwritable_dir(tmp_path, monkeypatch):
    from install_helper import write_guard_interpreter_cache

    def boom(*a, **k):
        raise OSError("read-only filesystem")

    monkeypatch.setattr(Path, "write_text", boom)
    write_guard_interpreter_cache(tmp_path)  # must not raise


def test_run_enable_project_pre_seeds_the_guard_cache(tmp_path):
    from install_helper import Style, run_enable_project

    project = tmp_path / "proj"
    project.mkdir()
    run_enable_project(
        project,
        Style(enabled=False),
        {"ok": "OK", "fail": "X"},
        runner=lambda argv, **kw: _proc(returncode=0),
    )
    cache = project / ".claude" / ".guard-interpreter"
    assert cache.is_file() and cache.read_text(
        encoding="utf-8"
    ) == PureWindowsPath(sys.executable).as_posix()


def test_demo_project_enablement_never_calls_the_real_writer(tmp_path, monkeypatch):
    """Demo mode is a dry run: enable_step must forward demo=True into run_configure
    (2026-08-12: enable_step delegates entirely to run_configure now - see
    test_run_configure_demo_writes_nothing for the guarantee that demo=True itself
    writes nothing; this test only confirms enable_step actually threads the flag
    through rather than silently dropping it)."""
    import install_helper as ih

    calls = []
    monkeypatch.setattr(ih, "run_configure", lambda *a, **k: calls.append(k) or 0)
    monkeypatch.setattr(ih, "confirm", lambda *a, **k: True)
    monkeypatch.setattr(ih, "ask", lambda *a, **k: str(tmp_path))
    inst = ih.Installer(_args(yes=False, demo=True), ih.Style(False), ih.marks(), subset="full")
    inst.enable_step()
    assert calls == [{"assume_yes": False, "demo": True}]


# ------------------------------------------------ team-preferences.json (docx opt-in)


def test_write_team_preferences_creates_file(tmp_path):
    from install_helper import write_team_preferences

    assert write_team_preferences(tmp_path, extra_formats=["docx"]) is True
    prefs = json.loads((tmp_path / ".claude" / "team-preferences.json").read_text())
    assert prefs["extra_formats"] == ["docx"]


def test_write_team_preferences_merges_and_preserves_other_keys(tmp_path):
    from install_helper import write_team_preferences

    target = tmp_path / ".claude" / "team-preferences.json"
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps({"some_other_key": "kept"}), encoding="utf-8")
    write_team_preferences(tmp_path, extra_formats=["docx"])
    prefs = json.loads(target.read_text())
    assert prefs["some_other_key"] == "kept"
    assert prefs["extra_formats"] == ["docx"]


def test_write_team_preferences_parallel_dispatch_via_workflow(tmp_path):
    from install_helper import write_team_preferences

    target = tmp_path / ".claude" / "team-preferences.json"
    write_team_preferences(tmp_path, parallel_dispatch_via_workflow=False)
    assert json.loads(target.read_text())["parallel_dispatch_via_workflow"] is False
    # Omitted argument leaves the key untouched (merge-only contract).
    write_team_preferences(tmp_path, extra_formats=["docx"])
    assert json.loads(target.read_text())["parallel_dispatch_via_workflow"] is False


def test_write_team_preferences_guard_daemon(tmp_path):
    """2026-08-12 user request: guard_daemon should be on by default when configuring a
    project. write_team_preferences itself is neutral (only writes when explicitly
    passed, like every other preference here) - the "on by default" behavior lives in
    run_configure actively passing True, tested separately below."""
    from install_helper import write_team_preferences

    target = tmp_path / ".claude" / "team-preferences.json"
    write_team_preferences(tmp_path, guard_daemon=False)
    assert json.loads(target.read_text())["guard_daemon"] is False
    # Omitted argument leaves the key untouched (merge-only contract) - same as every
    # other preference, guard_daemon included.
    write_team_preferences(tmp_path, extra_formats=["docx"])
    assert json.loads(target.read_text())["guard_daemon"] is False


def test_run_configure_guard_daemon_defaults_on(tmp_path, monkeypatch):
    """The one preference in run_configure's block that defaults True."""
    import install_helper as ih

    _isolate_home(monkeypatch, tmp_path)
    monkeypatch.setattr(ih, "run_cmd", lambda *a, **k: _FakeProc(0))
    rc = ih.run_configure(tmp_path, ih.Style(False), ih.marks(), assume_yes=True)
    assert rc == 0
    prefs = json.loads((tmp_path / ".claude" / "team-preferences.json").read_text())
    assert prefs["guard_daemon"] is True


def test_write_team_preferences_best_effort(tmp_path, monkeypatch):
    from install_helper import write_team_preferences

    monkeypatch.setattr(
        Path, "write_text", lambda *a, **k: (_ for _ in ()).throw(OSError("locked"))
    )
    assert write_team_preferences(tmp_path, extra_formats=["docx"]) is False


# ------------------------------------------------ self-relocation (running the script from inside the clone)


def test_relocates_when_script_lives_inside_a_repo(tmp_path, monkeypatch):
    """The live corp fix: running install_helper.py from inside the clone about to be
    git-checked-out can fail to overwrite the running .py file on Windows. The script
    must copy itself out and re-exec before any sync happens."""
    import install_helper as ih

    fake_repo = tmp_path / "clone"
    (fake_repo / ".claude-plugin").mkdir(parents=True)
    (fake_repo / ".claude-plugin" / "plugin.json").write_text(
        '{"name":"compliance-surveillance-team"}', encoding="utf-8"
    )
    (fake_repo / ".git").mkdir()
    script = fake_repo / "install_helper.py"
    script.write_text("print('child ran')", encoding="utf-8")

    monkeypatch.setattr(ih, "__file__", str(script))
    calls = []

    def fake_run(argv, **kw):
        calls.append(argv)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(ih.subprocess, "run", fake_run)
    args = _args(mode=None, yes=True)
    args.repo = None
    with pytest.raises(SystemExit) as exc:
        _real_relocate(args, ["--yes"])
    assert exc.value.code == 0
    assert len(calls) == 1
    argv = calls[0]
    assert argv[0] == sys.executable
    assert Path(argv[1]).parent != fake_repo  # relocated to somewhere else
    assert Path(argv[1]).read_text(encoding="utf-8") == "print('child ran')"
    assert "--repo" in argv and str(fake_repo) in argv


def test_no_relocation_when_not_inside_a_repo(tmp_path, monkeypatch):
    import install_helper as ih

    script = tmp_path / "install_helper.py"
    script.write_text("", encoding="utf-8")
    monkeypatch.setattr(ih, "__file__", str(script))
    calls = []
    monkeypatch.setattr(ih.subprocess, "run", lambda *a, **k: calls.append(1))
    _real_relocate(_args(mode=None, yes=True), ["--yes"])
    assert calls == []  # ran in place - no repo here to protect


def test_relocation_preserves_explicit_repo_flag(tmp_path, monkeypatch):
    """If the user already passed --repo, do not override it with the script's own dir."""
    import install_helper as ih

    fake_repo = tmp_path / "clone"
    (fake_repo / ".claude-plugin").mkdir(parents=True)
    (fake_repo / ".claude-plugin" / "plugin.json").write_text("{}", encoding="utf-8")
    (fake_repo / ".git").mkdir()
    script = fake_repo / "install_helper.py"
    script.write_text("", encoding="utf-8")
    monkeypatch.setattr(ih, "__file__", str(script))
    calls = []
    monkeypatch.setattr(
        ih.subprocess, "run", lambda argv, **kw: calls.append(argv) or SimpleNamespace(returncode=0)
    )
    args = _args(mode=None, yes=True)
    args.repo = "/somewhere/else"
    with pytest.raises(SystemExit):
        _real_relocate(args, ["--repo", "/somewhere/else"])
    argv = calls[0]
    assert argv.count("--repo") == 1
    assert "/somewhere/else" in argv


# ------------------------------------------------ standalone document-format menu step


def _confirm_by_prompt(answers: dict):
    """A fake `confirm` distinguishing the docx vs citations question by prompt text,
    since format_preferences_step asks both in one pass. Matches each question's OWN
    distinctive wording, not a bare "docx"/"citations" substring - live-caught,
    2026-08-05: the save-as-default question's prompt now restates the resolved summary
    (by design, for clarity - see machine_defaults_step/format_preferences_step), which
    itself CONTAINS the substring "docx", so a naive substring match made
    save_as_default accidentally evaluate True in every test using this fake - writing
    to the REAL ~/.config/virt-surv-it/installer.json, since none of these tests isolate
    HOME/XDG_CONFIG_HOME (fixed there too, defense in depth). Anything that isn't the
    docx or citations question - including save-as-default - returns `default`
    (declines), the safe fallback for a fake that doesn't know how to answer it."""

    def _fn(prompt, default, assume_yes, style=None):
        lowered = prompt.lower()
        if "produce .docx" in lowered:
            return answers.get("docx", default)
        if "cites regulatory obligations" in lowered:
            return answers.get("citations", default)
        return default

    return _fn


def test_format_preferences_step_shows_current_and_writes_on_change(tmp_path, monkeypatch, capsys):
    """Menu option 6: re-runnable any time, independent of project enablement. Both
    preferences are project-wide (team-preferences.json), asked in one pass."""
    import install_helper as ih

    _isolate_home(monkeypatch, tmp_path)
    project = tmp_path / "proj"
    project.mkdir()
    monkeypatch.setattr(ih, "ask", lambda *a, **k: str(project))
    monkeypatch.setattr(
        ih, "confirm", _confirm_by_prompt({"docx": True, "citations": True})
    )  # turn docx on; turn citations on too (both changes from the off-by-default builtin)
    inst = ih.Installer(_args(yes=False), ih.Style(False), ih.marks(), subset="formats")
    inst.format_preferences_step()
    prefs = json.loads((project / ".claude" / "team-preferences.json").read_text())
    assert prefs["extra_formats"] == ["docx"]
    assert prefs["regulatory_citations"] is True
    assert "docx=on" in capsys.readouterr().out


def test_format_preferences_step_can_turn_on_citations(tmp_path, monkeypatch, capsys):
    """2026-08-07: citations defaults to OFF now, so turning it ON is the change case."""
    import install_helper as ih

    _isolate_home(monkeypatch, tmp_path)
    project = tmp_path / "proj"
    project.mkdir()
    monkeypatch.setattr(ih, "ask", lambda *a, **k: str(project))
    monkeypatch.setattr(ih, "confirm", _confirm_by_prompt({"docx": False, "citations": True}))
    inst = ih.Installer(_args(yes=False), ih.Style(False), ih.marks(), subset="formats")
    inst.format_preferences_step()
    prefs = json.loads((project / ".claude" / "team-preferences.json").read_text())
    assert prefs["regulatory_citations"] is True
    assert "citations=on" in capsys.readouterr().out


def test_format_preferences_step_no_write_when_unchanged(tmp_path, monkeypatch):
    import install_helper as ih

    _isolate_home(monkeypatch, tmp_path)
    project = tmp_path / "proj"
    project.mkdir()
    monkeypatch.setattr(ih, "ask", lambda *a, **k: str(project))
    # matches the current defaults: docx off, citations off (2026-08-07)
    monkeypatch.setattr(ih, "confirm", _confirm_by_prompt({"docx": False, "citations": False}))
    inst = ih.Installer(_args(yes=False), ih.Style(False), ih.marks(), subset="formats")
    inst.format_preferences_step()
    assert not (project / ".claude" / "team-preferences.json").exists()


def test_format_preferences_step_can_turn_docx_off_again(tmp_path, monkeypatch):
    import install_helper as ih
    from install_helper import write_team_preferences

    _isolate_home(monkeypatch, tmp_path)
    project = tmp_path / "proj"
    project.mkdir()
    write_team_preferences(project, extra_formats=["docx"])
    monkeypatch.setattr(ih, "ask", lambda *a, **k: str(project))
    monkeypatch.setattr(ih, "confirm", _confirm_by_prompt({"docx": False, "citations": True}))
    inst = ih.Installer(_args(yes=False), ih.Style(False), ih.marks(), subset="formats")
    inst.format_preferences_step()
    prefs = json.loads((project / ".claude" / "team-preferences.json").read_text())
    assert prefs["extra_formats"] == []


def test_format_preferences_step_demo_never_writes(tmp_path, monkeypatch):
    import install_helper as ih

    _isolate_home(monkeypatch, tmp_path)
    project = tmp_path / "proj"
    project.mkdir()
    monkeypatch.setattr(ih, "ask", lambda *a, **k: str(project))
    monkeypatch.setattr(ih, "confirm", _confirm_by_prompt({"docx": True, "citations": False}))
    args = _args(yes=False)
    args.demo = True
    inst = ih.Installer(args, ih.Style(False), ih.marks(), subset="formats")
    inst.format_preferences_step()
    assert not (project / ".claude" / "team-preferences.json").exists()


# --- machine_defaults_step: view/edit this machine's defaults directly, no project ------------
# (2026-08-05 user request: "let's just have a clearer view and edit of the machine's
# defaults too" / "Morgan's model too should be machine default"). EVERY test here isolates
# HOME/XDG_CONFIG_HOME via _isolate_home FIRST, before touching anything - the exact
# discipline that was missing from the format_preferences_step tests above and caused a
# real, live pollution of ~/.config/virt-surv-it/installer.json on the dev machine.


def _confirm_by_prompt_machine(answers: dict):
    """Like _confirm_by_prompt, but for machine_defaults_step's OWN question wording -
    a separate fake, not reused, so a match here can never accidentally leak into the
    project-scoped format_preferences_step tests or vice versa."""

    def _fn(prompt, default, assume_yes, style=None):
        lowered = prompt.lower()
        if "produce .docx by default for new projects" in lowered:
            return answers.get("docx", default)
        if "new projects cite regulatory obligations" in lowered:
            return answers.get("citations", default)
        if "refresh the 'virt-surv' shell alias" in lowered:
            # Default False here (the REAL default is True): a test that doesn't opt in
            # must never fall through into a real run_setup_alias call.
            return answers.get("refresh_alias", False)
        return default

    return _fn


def test_machine_defaults_step_writes_on_change(tmp_path, monkeypatch, capsys):
    import install_helper as ih

    _isolate_home(monkeypatch, tmp_path)
    monkeypatch.setattr(
        ih, "confirm", _confirm_by_prompt_machine({"docx": True, "citations": True})
    )
    monkeypatch.setattr(ih, "ask", lambda *a, **k: "")  # blank = leave model unchanged
    inst = ih.Installer(_args(yes=False), ih.Style(False), ih.marks(), subset="machinedefaults")
    inst.machine_defaults_step()
    saved = json.loads((tmp_path / "xdg" / "virt-surv-it" / "installer.json").read_text())
    assert saved["default_docx"] is True
    assert saved["default_regulatory_citations"] is True
    assert "docx=on" in capsys.readouterr().out


def test_machine_defaults_step_unchanged_writes_nothing(tmp_path, monkeypatch):
    import install_helper as ih

    _isolate_home(monkeypatch, tmp_path)
    monkeypatch.setattr(
        ih, "confirm", _confirm_by_prompt_machine({"docx": False, "citations": False})
    )
    monkeypatch.setattr(ih, "ask", lambda *a, **k: "")
    inst = ih.Installer(_args(yes=False), ih.Style(False), ih.marks(), subset="machinedefaults")
    inst.machine_defaults_step()
    assert not (tmp_path / "xdg" / "virt-surv-it" / "installer.json").exists()


def test_machine_defaults_step_demo_writes_nothing(tmp_path, monkeypatch):
    import install_helper as ih

    _isolate_home(monkeypatch, tmp_path)
    monkeypatch.setattr(
        ih, "confirm", _confirm_by_prompt_machine({"docx": True, "citations": True})
    )
    monkeypatch.setattr(ih, "ask", lambda *a, **k: "opus")
    args = _args(yes=False)
    args.demo = True
    inst = ih.Installer(args, ih.Style(False), ih.marks(), subset="machinedefaults")
    inst.machine_defaults_step()
    assert not (tmp_path / "xdg").exists()
    assert not (tmp_path / "home" / ".claude").exists()


def test_machine_defaults_step_sets_model_default(tmp_path, monkeypatch):
    import install_helper as ih

    _isolate_home(monkeypatch, tmp_path)
    monkeypatch.setattr(
        ih, "confirm", _confirm_by_prompt_machine({"docx": False, "citations": True})
    )
    monkeypatch.setattr(ih, "ask", lambda *a, **k: "opus")
    inst = ih.Installer(_args(yes=False), ih.Style(False), ih.marks(), subset="machinedefaults")
    inst.machine_defaults_step()
    settings = json.loads((tmp_path / "home" / ".claude" / "settings.json").read_text())
    assert settings["model"] == ih.ORCHESTRATOR_MODEL_IDS["opus"]


def test_machine_defaults_step_sets_go_launch_command(tmp_path, monkeypatch, capsys):
    import install_helper as ih

    _isolate_home(monkeypatch, tmp_path)
    monkeypatch.setattr(
        ih, "confirm", _confirm_by_prompt_machine({"docx": False, "citations": False})
    )

    def _ask(prompt, default, assume_yes, style=None):
        if "launch command" in prompt.lower():
            return "cc"
        return ""  # leave model unchanged

    monkeypatch.setattr(ih, "ask", _ask)
    inst = ih.Installer(_args(yes=False), ih.Style(False), ih.marks(), subset="machinedefaults")
    inst.machine_defaults_step()
    saved = json.loads((tmp_path / "xdg" / "virt-surv-it" / "installer.json").read_text())
    assert saved["claude_launch_command"] == "cc"
    assert "'virt-surv go' launch command=cc" in capsys.readouterr().out


def test_machine_defaults_step_blank_launch_command_leaves_unchanged(tmp_path, monkeypatch):
    """Same 'blank to leave unchanged' contract as the model field - an already-set
    launch command must survive an unrelated machine-defaults edit untouched."""
    import install_helper as ih

    _isolate_home(monkeypatch, tmp_path)
    cfg_dir = tmp_path / "xdg" / "virt-surv-it"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "installer.json").write_text(
        json.dumps({"claude_launch_command": "cc"}), encoding="utf-8"
    )
    monkeypatch.setattr(
        ih, "confirm", _confirm_by_prompt_machine({"docx": True, "citations": False})
    )
    monkeypatch.setattr(ih, "ask", lambda *a, **k: "")
    inst = ih.Installer(_args(yes=False), ih.Style(False), ih.marks(), subset="machinedefaults")
    inst.machine_defaults_step()
    saved = json.loads((cfg_dir / "installer.json").read_text())
    assert saved["claude_launch_command"] == "cc"  # unchanged, not cleared


def test_machine_defaults_step_offers_alias_refresh_when_launch_command_changes(
    tmp_path, monkeypatch
):
    """Live report (2026-08-16): "it doesn't seem to stick" - a pre-v5 installed alias
    has the command baked in, so a config change alone did nothing for it. The step
    still offers the setup-alias refresh (which carries such an install to v5, where
    the command is resolved at run time), and accepting it must actually run it."""
    import install_helper as ih

    _isolate_home(monkeypatch, tmp_path)
    monkeypatch.setattr(
        ih,
        "confirm",
        _confirm_by_prompt_machine({"docx": False, "citations": False, "refresh_alias": True}),
    )

    def _ask(prompt, default, assume_yes, style=None):
        if "launch command" in prompt.lower():
            return "cc"
        return ""  # leave model unchanged

    monkeypatch.setattr(ih, "ask", _ask)
    calls = []
    monkeypatch.setattr(ih, "run_setup_alias", lambda *a, **k: calls.append(k) or 0)
    inst = ih.Installer(_args(yes=False), ih.Style(False), ih.marks(), subset="machinedefaults")
    inst.machine_defaults_step()
    assert calls == [{"assume_yes": True}]


def test_machine_defaults_step_no_alias_refresh_when_launch_command_unchanged(
    tmp_path, monkeypatch
):
    """The refresh offer is scoped to an actual launch-command change - an unrelated
    machine-defaults edit must never route through setup-alias."""
    import install_helper as ih

    _isolate_home(monkeypatch, tmp_path)
    monkeypatch.setattr(
        ih,
        "confirm",
        _confirm_by_prompt_machine({"docx": True, "citations": False, "refresh_alias": True}),
    )
    monkeypatch.setattr(ih, "ask", lambda *a, **k: "")  # blank everywhere - launch unchanged
    calls = []
    monkeypatch.setattr(ih, "run_setup_alias", lambda *a, **k: calls.append(k) or 0)
    inst = ih.Installer(_args(yes=False), ih.Style(False), ih.marks(), subset="machinedefaults")
    inst.machine_defaults_step()
    assert calls == []


def test_machine_defaults_step_invalid_model_input_leaves_unchanged(tmp_path, monkeypatch, capsys):
    import install_helper as ih

    _isolate_home(monkeypatch, tmp_path)
    monkeypatch.setattr(
        ih, "confirm", _confirm_by_prompt_machine({"docx": False, "citations": True})
    )
    monkeypatch.setattr(ih, "ask", lambda *a, **k: "gibberish")
    inst = ih.Installer(_args(yes=False), ih.Style(False), ih.marks(), subset="machinedefaults")
    inst.machine_defaults_step()
    assert not (tmp_path / "home" / ".claude" / "settings.json").exists()
    assert "expected opus/sonnet/sonnet-4-6/default" in capsys.readouterr().out


def test_menu_option_4_maps_to_advanced_submenu():
    from install_helper import _ADVANCED_ACTIONS, MENU_ACTIONS

    assert MENU_ACTIONS["4"] == "advanced"
    assert _ADVANCED_ACTIONS["3"] == "formats"
    assert _ADVANCED_ACTIONS["5"] == "demo"
    assert _ADVANCED_ACTIONS["10"] == "aliasmanage"


def test_write_team_preferences_regulatory_citations_flag(tmp_path):
    from install_helper import write_team_preferences

    write_team_preferences(tmp_path, regulatory_citations=False)
    prefs = json.loads((tmp_path / ".claude" / "team-preferences.json").read_text())
    assert prefs["regulatory_citations"] is False
    assert "extra_formats" not in prefs  # omitted arg leaves the other key untouched


def test_write_team_preferences_standards_critique_flag(tmp_path):
    """standards_critique: opposite default from regulatory_citations (off, not on, when
    absent) - same merge-only, no-machine-wide-tier mechanism as large_context_review_split."""
    from install_helper import write_team_preferences

    write_team_preferences(tmp_path, standards_critique=True)
    prefs = json.loads((tmp_path / ".claude" / "team-preferences.json").read_text())
    assert prefs["standards_critique"] is True
    assert "regulatory_citations" not in prefs  # omitted arg leaves the other key untouched


def test_write_team_preferences_omitted_args_preserve_existing(tmp_path):
    from install_helper import write_team_preferences

    write_team_preferences(tmp_path, extra_formats=["docx"], regulatory_citations=False)
    write_team_preferences(tmp_path, extra_formats=["docx"])  # citations arg omitted this time
    prefs = json.loads((tmp_path / ".claude" / "team-preferences.json").read_text())
    assert prefs["regulatory_citations"] is False  # untouched by the second call
    assert prefs["extra_formats"] == ["docx"]


def test_write_team_preferences_statusline_show_map_flag(tmp_path):
    from install_helper import write_team_preferences

    write_team_preferences(tmp_path, statusline_show_map=True)
    prefs = json.loads((tmp_path / ".claude" / "team-preferences.json").read_text())
    assert prefs["statusline_show_map"] is True
    assert "extra_formats" not in prefs  # omitted arg leaves the other key untouched


def test_machine_defaults_step_sets_statusline_show_map_default(tmp_path, monkeypatch):
    import install_helper as ih

    _isolate_home(monkeypatch, tmp_path)

    def _fake_confirm(prompt, default, assume_yes, style=None):
        if "statusline" in prompt.lower():
            return True  # the one field this test flips - forces the write path
        return default  # everything else stays at its current (unchanged) value

    monkeypatch.setattr(ih, "confirm", _fake_confirm)
    monkeypatch.setattr(ih, "ask", lambda *a, **k: "")
    inst = ih.Installer(_args(yes=False), ih.Style(False), ih.marks(), subset="machinedefaults")
    inst.machine_defaults_step()
    cfg = json.loads((ih.config_path()).read_text())
    assert cfg["default_statusline_show_map"] is True


# --- analyser output cleanliness check (2026-08-04) ---------------------------------------


def test_diagnostics_submenu_option_2_maps_to_toolcheck():
    from install_helper import _DIAGNOSTICS_ACTIONS

    assert _DIAGNOSTICS_ACTIONS["2"] == "toolcheck"


def test_probe_analyser_output_skips_missing_tools(tmp_path, monkeypatch):
    import install_helper as ih

    monkeypatch.setattr(ih.shutil, "which", lambda name: None)
    results = list(ih.probe_analyser_output(tmp_path, runner=lambda *a, **k: _proc(0)))
    assert results
    assert all(status == "SKIP" for _, status, _ in results)
    assert all("not installed" in detail for _, _, detail in results)


def test_probe_analyser_output_is_a_generator_that_streams_results(tmp_path, monkeypatch):
    """The whole point of this design (live report, 2026-08-04: batching all results
    before printing anything looked exactly like a hang) - pin that it's actually lazy,
    not just iterable."""
    import inspect

    import install_helper as ih

    monkeypatch.setattr(ih.shutil, "which", lambda name: f"/usr/bin/{name}")
    gen = ih.probe_analyser_output(tmp_path, runner=lambda *a, **k: _proc(0, stdout=""))
    assert inspect.isgenerator(gen)


def test_probe_analyser_output_fixtures_are_lf_only(tmp_path, monkeypatch):
    """Live report, 2026-08-04: shfmt came back NOISY (393 bytes) on the trivial fixture
    on a real Windows box. Root cause: Path.write_text's default newline translation
    turns every \\n into \\r\\n on Windows, and shfmt -d's diff is byte-sensitive enough to
    report that as "the whole file would change". Reading the fixtures back in BINARY
    mode (no newline translation on read) proves the bytes on disk are LF-only regardless
    of what platform this test itself runs on - the fix forces newline="\\n" on write."""
    import install_helper as ih

    monkeypatch.setattr(ih.shutil, "which", lambda name: None)  # SKIP every tool - just
    list(ih.probe_analyser_output(tmp_path))  # need the fixture-writing side effect
    for name in ("probe.py", "probe.sql", "probe.sh"):
        raw = (tmp_path / name).read_bytes()
        assert b"\r\n" not in raw, f"{name} contains CRLF - would break shfmt -d on Windows"
        assert b"\n" in raw


@pytest.mark.parametrize(
    "runner,expected_status,detail_substrings",
    [
        pytest.param(lambda *a, **k: _proc(0, stdout=""), "OK", (), id="clean"),
        pytest.param(
            # Fable UX review, 2026-08-05: a tool that crashed at startup (a short
            # traceback, no ANSI, under the 200-byte NOISY threshold) used to be reported
            # "OK: clean" - the opposite of true. Nonzero exit is always anomalous here,
            # regardless of output length.
            lambda *a, **k: _proc(1, stderr="ModuleNotFoundError: x"),
            "ERROR",
            ("exit 1", "crashed"),
            id="crash",
        ),
        pytest.param(
            lambda *a, **k: _proc(0, stdout="\x1b[31merror\x1b[0m"),
            "NOISY",
            ("ANSI escape",),
            id="leaked-ansi",
        ),
        pytest.param(
            # "gitleaks\n" * 60 - well over the 200-byte threshold, no ANSI involved.
            lambda *a, **k: _proc(0, stdout="gitleaks\n" * 60),
            "NOISY",
            ("bytes on a trivial clean file",),
            id="verbose-clean",
        ),
        pytest.param(_timeout_runner, "ERROR", ("timed out",), id="timeout"),
    ],
)
def test_probe_analyser_output_statuses(
    tmp_path, monkeypatch, runner, expected_status, detail_substrings
):
    import install_helper as ih

    monkeypatch.setattr(ih.shutil, "which", lambda name: f"/usr/bin/{name}")
    results = list(ih.probe_analyser_output(tmp_path, runner=runner))
    assert all(status == expected_status for _, status, _ in results)
    for substr in detail_substrings:
        assert all(substr in detail for _, _, detail in results)


def test_probe_analyser_output_no_longer_names_semgrep_or_pip_audit():
    """Both removed entirely (2026-08-04): repeated live corp-proxy hangs from network
    calls neither could reliably avoid, even after their own suppression-flag fixes (a
    local semgrep rule file, a bounded pip-audit --timeout) - see code-reviewer.md for
    the full removal rationale. Neither name should appear in the checks list at all, so
    neither is ever invoked even if installed."""
    import install_helper as ih

    checked_names = {name for name, *_ in ih._TOOL_OUTPUT_CHECKS}
    assert "semgrep" not in checked_names
    assert "pip-audit" not in checked_names


def test_run_tool_check_reports_ok_when_all_clean(capsys, monkeypatch):
    import install_helper as ih
    from install_helper import Style, marks, run_tool_check

    monkeypatch.setattr(
        ih,
        "probe_analyser_output",
        lambda tmpdir, runner=None: [("ruff", "OK", "clean"), ("bandit", "SKIP", "not installed")],
    )
    rc = run_tool_check(Style(False), marks())
    out = capsys.readouterr().out
    assert rc == 0
    assert "ruff: clean" in out
    assert "not installed" in out
    assert "All installed analysers came back clean" in out


def test_run_tool_check_reports_failure_when_something_noisy(capsys, monkeypatch):
    import install_helper as ih
    from install_helper import Style, marks, run_tool_check

    monkeypatch.setattr(
        ih,
        "probe_analyser_output",
        lambda tmpdir, runner=None: [
            ("bandit", "NOISY", "ANSI escape codes leaked through the flags")
        ],
    )
    rc = run_tool_check(Style(False), marks())
    out = capsys.readouterr().out
    assert rc == 1
    assert "bandit: NOISY" in out
    assert "did not come back clean" in out


def test_check_tools_cli_flag_dispatches(monkeypatch):
    import install_helper as ih

    called = []
    monkeypatch.setattr(ih, "run_tool_check", lambda style, mm: called.append(1) or 0)
    rc = ih._main(["--check-tools"])
    assert rc == 0
    assert called == [1]


# --- comprehensive environment check (2026-08-04) ------------------------------------------


def test_diagnostics_submenu_option_3_maps_to_envcheck():
    from install_helper import _DIAGNOSTICS_ACTIONS

    assert _DIAGNOSTICS_ACTIONS["3"] == "envcheck"


def test_check_env_cli_flag_dispatches(monkeypatch):
    import install_helper as ih

    called = []
    monkeypatch.setattr(
        ih, "run_env_check", lambda style, mm, repo_hint=None: called.append(1) or 0
    )
    rc = ih._main(["--check-env"])
    assert rc == 0
    assert called == [1]


def test_version_flag_prints_and_exits(capsys):
    """Fable UX review, 2026-08-05: no --version existed at all."""
    import install_helper as ih

    with pytest.raises(SystemExit) as exc_info:
        ih.parse_args(["--version"])
    assert exc_info.value.code == 0
    out = capsys.readouterr().out
    assert "compliance-surveillance-team" in out


# --- --model validation (fable UX review, 2026-08-05) ------------------------------------------


def test_model_flag_alone_is_an_error_not_a_silent_full_install(monkeypatch):
    """--model opus with neither --model-project nor --model-default used to be
    silently discarded and fall through to a real full install."""
    import install_helper as ih

    def boom(*a, **k):
        raise AssertionError("Installer must never be constructed - the flag is invalid")

    monkeypatch.setattr(ih, "Installer", boom)
    rc = ih._main(["--model", "opus"])
    assert rc == 1


def test_model_project_without_model_is_an_error_not_a_silent_reset(monkeypatch, tmp_path):
    """--model-project DIR without --model used to silently write "sonnet" (the same
    as an explicit --model default) - a real, unrequested reset of an existing choice."""
    import install_helper as ih

    called = []
    monkeypatch.setattr(
        ih, "run_orchestrator_model", lambda *a, **k: called.append(1) or (True, "x")
    )
    rc = ih._main(["--model-project", str(tmp_path)])
    assert rc == 1
    assert called == []


def test_model_default_without_model_is_an_error(monkeypatch):
    import install_helper as ih

    called = []
    monkeypatch.setattr(ih, "run_orchestrator_model_default", lambda *a, **k: called.append(1) or 0)
    rc = ih._main(["--model-default"])
    assert rc == 1
    assert called == []


def test_model_project_with_model_still_works(monkeypatch, tmp_path):
    import install_helper as ih

    called = []
    monkeypatch.setattr(
        ih,
        "run_orchestrator_model",
        lambda project, wanted, style, mm: called.append(wanted) or 0,
    )
    rc = ih._main(["--model-project", str(tmp_path), "--model", "opus"])
    assert rc == 0
    assert called == ["opus"]


# --- --demo gap in the scripting-path flags (found in review, 2026-08-13) -----------------


def test_demo_permissions_env_tuning_enable_project_write_nothing(monkeypatch, tmp_path):
    """--demo combined with --permissions/--env-tuning/--env-tuning-betas/--enable-project
    used to be silently ignored - the real write functions ran anyway, breaking --demo's
    'nothing executed or written' promise for exactly these four scripting-path flags."""
    import install_helper as ih

    called = []
    monkeypatch.setattr(ih, "run_permissions", lambda *a, **k: called.append("permissions") or 0)
    monkeypatch.setattr(ih, "run_env_tuning", lambda *a, **k: called.append("env_tuning") or 0)
    monkeypatch.setattr(
        ih, "run_env_tuning_betas", lambda *a, **k: called.append("env_tuning_betas") or 0
    )
    monkeypatch.setattr(
        ih, "run_enable_project", lambda *a, **k: called.append("enable_project") or 0
    )
    rc = ih._main(
        [
            "--demo",
            "--permissions",
            str(tmp_path),
            "--env-tuning",
            str(tmp_path),
            "--env-tuning-betas",
            str(tmp_path),
            "--enable-project",
            str(tmp_path),
        ]
    )
    assert rc == 0
    assert called == []


def test_demo_model_project_and_model_default_write_nothing(monkeypatch, tmp_path):
    """Same --demo gap as above, for --model-project/--model-default: the real
    orchestrator-model writers ran even under --demo."""
    import install_helper as ih

    called = []
    monkeypatch.setattr(
        ih, "run_orchestrator_model", lambda *a, **k: called.append("model_project") or (True, "x")
    )
    monkeypatch.setattr(
        ih,
        "run_orchestrator_model_default",
        lambda *a, **k: called.append("model_default") or (True, "x"),
    )
    rc = ih._main(
        ["--demo", "--model-project", str(tmp_path), "--model-default", "--model", "opus"]
    )
    assert rc == 0
    assert called == []


def test_check_interpreters_finds_the_first_working_one(monkeypatch):
    import install_helper as ih

    monkeypatch.setattr(
        ih.shutil, "which", lambda name: f"/usr/bin/{name}" if name == "python3" else None
    )
    monkeypatch.setattr(ih.subprocess, "run", lambda argv, **kw: _proc(0, stdout="3.12.3\n"))
    rows, winner = ih._check_interpreters(["python3", "python", "py"])
    assert winner == "python3"
    statuses = {name: status for name, status, _ in rows}
    assert statuses == {"python3": "OK", "python": "SKIP", "py": "SKIP"}


def test_check_interpreters_flags_a_version_below_the_floor(monkeypatch):
    import install_helper as ih

    monkeypatch.setattr(ih.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(ih.subprocess, "run", lambda argv, **kw: _proc(0, stdout="3.7.0\n"))
    rows, winner = ih._check_interpreters(["python3"])
    assert winner == ""
    assert rows[0][1] == "ERROR"
    assert "below the 3.9 floor" in rows[0][2]


def test_check_interpreters_handles_a_crash(monkeypatch):
    import install_helper as ih

    monkeypatch.setattr(ih.shutil, "which", lambda name: f"/usr/bin/{name}")

    def boom(argv, **kw):
        raise OSError("permission denied")

    monkeypatch.setattr(ih.subprocess, "run", boom)
    rows, winner = ih._check_interpreters(["python3"])
    assert winner == ""
    assert rows[0][1] == "ERROR"
    assert "permission denied" in rows[0][2]


def test_check_encoding_roundtrip_skips_without_an_interpreter():
    from install_helper import _check_encoding_roundtrip

    status, detail = _check_encoding_roundtrip("")
    assert status == "SKIP"


def test_check_encoding_roundtrip_ok(monkeypatch):
    import install_helper as ih

    monkeypatch.setattr(
        ih.subprocess, "run", lambda argv, **kw: _proc(0, stdout="🎩 test ✓\n".encode("utf-8"))
    )
    status, detail = ih._check_encoding_roundtrip("python3")
    assert status == "OK"


def test_check_encoding_roundtrip_detects_bad_bytes(monkeypatch):
    import install_helper as ih

    monkeypatch.setattr(
        ih.subprocess, "run", lambda argv, **kw: _proc(0, stdout=b"\xff\xfe not utf-8")
    )
    status, detail = ih._check_encoding_roundtrip("python3")
    assert status == "ERROR"
    assert "not valid UTF-8" in detail


# --- _check_shell_startup_time (2026-08-14 live report: slow .bashrc -> snapshot timeout) -----


def test_check_shell_startup_time_skips_without_bash():
    from install_helper import _check_shell_startup_time

    status, detail = _check_shell_startup_time(None)
    assert status == "SKIP"


def test_check_shell_startup_time_skips_without_bashrc(tmp_path, monkeypatch):
    import install_helper as ih

    monkeypatch.setattr(ih.Path, "home", lambda: tmp_path)  # no .bashrc created here
    status, detail = ih._check_shell_startup_time("/bin/bash")
    assert status == "SKIP"


def test_check_shell_startup_time_ok(tmp_path, monkeypatch):
    import install_helper as ih

    (tmp_path / ".bashrc").write_text("# fast\n", encoding="utf-8")
    monkeypatch.setattr(ih.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(ih.subprocess, "run", lambda argv, **kw: _proc(0))
    times = iter([100.0, 100.5])
    monkeypatch.setattr(ih.time, "monotonic", lambda: next(times))
    status, detail = ih._check_shell_startup_time("/bin/bash")
    assert status == "OK"
    assert "0.50s" in detail


def test_check_shell_startup_time_warns_when_slow(tmp_path, monkeypatch):
    import install_helper as ih

    (tmp_path / ".bashrc").write_text("# slow\n", encoding="utf-8")
    monkeypatch.setattr(ih.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(ih.subprocess, "run", lambda argv, **kw: _proc(0))
    times = iter([100.0, 104.0])  # 4s elapsed
    monkeypatch.setattr(ih.time, "monotonic", lambda: next(times))
    status, detail = ih._check_shell_startup_time("/bin/bash")
    assert status == "WARN"
    assert "4.0s" in detail
    assert "$- == *i*" in detail


def test_check_shell_startup_time_errors_at_or_past_claude_codes_own_timeout(tmp_path, monkeypatch):
    """10s is not an arbitrary threshold - it's the same figure the live corp-Windows debug
    log named as Claude Code's own shell-snapshot execution timeout."""
    import install_helper as ih

    (tmp_path / ".bashrc").write_text("# very slow\n", encoding="utf-8")
    monkeypatch.setattr(ih.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(ih.subprocess, "run", lambda argv, **kw: _proc(0))
    times = iter([100.0, 111.0])  # 11s elapsed
    monkeypatch.setattr(ih.time, "monotonic", lambda: next(times))
    status, detail = ih._check_shell_startup_time("/bin/bash")
    assert status == "ERROR"
    assert "shell-snapshot timeout" in detail


def test_check_shell_startup_time_errors_on_real_timeout(tmp_path, monkeypatch):
    import install_helper as ih

    (tmp_path / ".bashrc").write_text("# hangs\n", encoding="utf-8")
    monkeypatch.setattr(ih.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(ih.subprocess, "run", _timeout_runner)
    status, detail = ih._check_shell_startup_time("/bin/bash")
    assert status == "ERROR"


# --- _resolve_repo_root (2026-08-04 live report: relocated-session diagnostics/alias) ---------


def _fake_full_clone(root):
    """Distinct from _fake_clone(tmp_path) (line ~909) - this one takes the target root
    directly (not tmp_path/"clone") and also creates scripts/, needed for
    _bootstrap_only_hint's own real-clone signal."""
    root.mkdir()
    (root / ".git").mkdir()
    (root / ".claude-plugin").mkdir()
    (root / ".claude-plugin" / "plugin.json").write_text("{}", encoding="utf-8")
    (root / "install_helper.py").write_text("# clone copy\n", encoding="utf-8")
    (root / "scripts").mkdir()  # _bootstrap_only_hint's own signal of "a real clone"
    return root


def test_resolve_repo_root_prefers_hint_over_relocated_file(tmp_path, monkeypatch):
    """_relocate_if_running_inside_target_repo re-execs from a temp copy and passes the
    REAL clone through as --repo (args.repo) - __file__ itself is wrong for the rest of
    that session. This is the exact bug: without the hint, a diagnostic run post-
    relocation would misreport "not installed yet" even mid-install."""
    import install_helper as ih

    clone = _fake_full_clone(tmp_path / "clone")
    relocated = tmp_path / "relocated-temp" / "install_helper.py"
    relocated.parent.mkdir()
    relocated.write_text("# relocated temp copy\n", encoding="utf-8")
    monkeypatch.setattr(ih, "__file__", str(relocated))
    assert ih._resolve_repo_root(str(clone)) == clone.resolve()


def test_resolve_repo_root_falls_back_to_installer_config(tmp_path, monkeypatch):
    import install_helper as ih

    clone = _fake_full_clone(tmp_path / "clone")
    relocated = tmp_path / "relocated-temp" / "install_helper.py"
    relocated.parent.mkdir()
    relocated.write_text("# relocated temp copy\n", encoding="utf-8")
    monkeypatch.setattr(ih, "__file__", str(relocated))
    xdg = tmp_path / "xdg"
    (xdg / "virt-surv-it").mkdir(parents=True)
    (xdg / "virt-surv-it" / "installer.json").write_text(
        json.dumps({"repo_path": str(clone)}), encoding="utf-8"
    )
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))
    assert ih._resolve_repo_root(None) == clone.resolve()  # no hint - config still saves it


def test_resolve_repo_root_none_when_nothing_looks_like_a_repo(tmp_path, monkeypatch):
    import install_helper as ih

    relocated = tmp_path / "relocated-temp" / "install_helper.py"
    relocated.parent.mkdir()
    relocated.write_text("# relocated temp copy\n", encoding="utf-8")
    monkeypatch.setattr(ih, "__file__", str(relocated))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "no-such-xdg"))
    assert ih._resolve_repo_root(None) is None
    assert ih._resolve_repo_root(str(tmp_path / "not-a-repo-either")) is None


def test_run_setup_alias_uses_repo_hint_over_relocated_file(tmp_path, monkeypatch):
    import install_helper as ih

    home = _isolate_home_for_alias(monkeypatch, tmp_path, bashrc="")
    clone = _fake_full_clone(tmp_path / "clone")
    relocated = tmp_path / "relocated-temp" / "install_helper.py"
    relocated.parent.mkdir()
    relocated.write_text("# relocated temp copy\n", encoding="utf-8")
    monkeypatch.setattr(ih, "__file__", str(relocated))
    _stub_interpreters(monkeypatch, ih)

    rc = ih.run_setup_alias(ih.Style(False), ih.marks(), assume_yes=True, repo_hint=str(clone))
    assert rc == 0
    content = (home / ".bashrc").read_text(encoding="utf-8")
    assert str(clone) in content
    assert "relocated-temp" not in content


def test_run_env_check_uses_repo_hint_over_relocated_file(tmp_path, monkeypatch, capsys):
    """End-to-end: run_env_check itself, not just the helper, must pass the hinted
    (real clone) repo_root down to its sub-checks - not __file__'s relocated parent."""
    import install_helper as ih

    clone = _fake_full_clone(tmp_path / "clone")
    relocated = tmp_path / "relocated-temp" / "install_helper.py"
    relocated.parent.mkdir()
    relocated.write_text("# relocated temp copy\n", encoding="utf-8")
    monkeypatch.setattr(ih, "__file__", str(relocated))
    monkeypatch.setattr(ih, "_check_interpreters", lambda order: ([], ""))
    monkeypatch.setattr(ih, "find_bash", lambda: None)
    monkeypatch.setattr(ih, "_check_runtime_dependencies", lambda: [])
    monkeypatch.setattr(ih, "_check_encoding_roundtrip", lambda interp: ("SKIP", "no interpreter"))
    monkeypatch.setattr(ih, "_check_guard_hooks", lambda interp, root, tmp: [])
    monkeypatch.setattr(ih, "probe_analyser_output", lambda tmp, runner=None: iter([]))
    ih.run_env_check(ih.Style(False), ih.marks(), repo_hint=str(clone))
    out = capsys.readouterr().out
    # The real bug: without the hint this would print "not installed yet" (bootstrap-only
    # SKIP) even though a real clone is right there via args.repo.
    assert "not installed yet" not in out


def test_check_plugin_root_bootstrap_repo_as_project(tmp_path, monkeypatch):
    import install_helper as ih

    monkeypatch.chdir(tmp_path)
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "team-operating-guide.md").write_text("x", encoding="utf-8")
    status, detail = ih._check_plugin_root_bootstrap(Path(__file__).resolve().parents[1])
    assert status == "OK"
    assert "repo-as-project" in detail


def test_check_plugin_root_bootstrap_warns_when_nothing_found(tmp_path, monkeypatch):
    import install_helper as ih

    monkeypatch.chdir(tmp_path)  # no docs/team-operating-guide.md here
    monkeypatch.setattr(ih.Path, "home", staticmethod(lambda: tmp_path / "empty-home"))
    status, detail = ih._check_plugin_root_bootstrap(Path(__file__).resolve().parents[1])
    assert status == "WARN"


# --- bootstrap-only hint, repo script syntax, runtime deps (2026-08-04 live reports) ----------


def test_bootstrap_only_hint_present_for_full_clone():
    from install_helper import _bootstrap_only_hint

    assert _bootstrap_only_hint(Path(__file__).resolve().parents[1]) is None


def test_bootstrap_only_hint_explains_missing_scripts_dir(tmp_path):
    from install_helper import _bootstrap_only_hint

    hint = _bootstrap_only_hint(tmp_path)
    assert hint is not None
    assert "not installed yet" in hint
    assert "bootstrap" in hint


def test_check_plugin_root_bootstrap_uses_clear_hint_not_raw_importerror(tmp_path):
    """Live report, 2026-08-04: a Windows user ran --check-env from the curl-bootstrap
    temp dir (no scripts/ yet) and got a raw 'No module named scripts.find_plugin_root'
    ImportError instead of a legible reason."""
    from install_helper import _check_plugin_root_bootstrap

    status, detail = _check_plugin_root_bootstrap(tmp_path)
    assert status == "SKIP"
    assert "not installed yet" in detail
    assert "ImportError" not in detail
    assert "No module named" not in detail


def test_check_guard_hooks_uses_clear_hint_for_bootstrap_only_copy(tmp_path):
    from install_helper import _check_guard_hooks

    rows = _check_guard_hooks("python3", tmp_path, tmp_path)
    assert len(rows) == 1
    assert rows[0][1] == "SKIP"
    assert "not installed yet" in rows[0][2]


def test_check_repo_py_syntax_clean_on_real_repo():
    from install_helper import _check_repo_py_syntax

    rows = _check_repo_py_syntax("python3", Path(__file__).resolve().parents[1])
    assert len(rows) == 1
    assert rows[0][1] == "OK"
    assert "compile cleanly" in rows[0][2]


def test_check_repo_py_syntax_reports_a_broken_file(tmp_path):
    from install_helper import _check_repo_py_syntax

    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "broken.py").write_text("def f(:\n    pass\n", encoding="utf-8")
    (tmp_path / "scripts" / "fine.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    rows = _check_repo_py_syntax("python3", tmp_path)
    assert rows[0] == ("repo script syntax", "ERROR", "1/2 file(s) fail to compile")
    assert any("broken.py" in label for label, *_ in rows[1:])


def test_check_repo_py_syntax_skips_without_interpreter(tmp_path):
    from install_helper import _check_repo_py_syntax

    rows = _check_repo_py_syntax("", tmp_path)
    assert rows == [("repo script syntax", "SKIP", "no working interpreter found")]


def test_check_repo_py_syntax_skips_bootstrap_only_copy(tmp_path):
    from install_helper import _check_repo_py_syntax

    rows = _check_repo_py_syntax("python3", tmp_path)
    assert len(rows) == 1
    assert rows[0][1] == "SKIP"
    assert "not installed yet" in rows[0][2]


def test_check_runtime_dependencies_reports_git_and_claude(monkeypatch):
    import install_helper as ih

    monkeypatch.setattr(
        ih.shutil, "which", lambda name: f"/usr/bin/{name}" if name == "git" else None
    )
    monkeypatch.setattr(ih, "find_claude", lambda refresh=True: ("/usr/local/bin/claude", "path"))
    rows = ih._check_runtime_dependencies()
    assert ("git", "OK", "found") in rows
    assert any(label == "claude CLI" and status == "OK" for label, status, _ in rows)


def test_check_runtime_dependencies_errors_when_git_missing(monkeypatch):
    import install_helper as ih

    monkeypatch.setattr(ih.shutil, "which", lambda name: None)
    monkeypatch.setattr(ih, "find_claude", lambda refresh=True: (None, None))
    rows = ih._check_runtime_dependencies()
    assert any(label == "git" and status == "ERROR" for label, status, _ in rows)
    assert any(label == "claude CLI" and status == "ERROR" for label, status, _ in rows)


def test_check_guard_hooks_skips_without_interpreter(tmp_path):
    from install_helper import _check_guard_hooks

    rows = _check_guard_hooks("", Path(__file__).resolve().parents[1], tmp_path)
    assert len(rows) == 1
    assert rows[0][1] == "SKIP"


def test_check_guard_hooks_clean_passthrough(tmp_path, monkeypatch):
    import install_helper as ih

    monkeypatch.setattr(ih.subprocess, "run", lambda argv, **kw: _proc(0))
    rows = ih._check_guard_hooks("python3", Path(__file__).resolve().parents[1], tmp_path)
    assert rows
    assert all(status == "OK" for _, status, _ in rows)


def test_check_guard_hooks_distinguishes_crash_from_a_real_block(tmp_path, monkeypatch):
    import install_helper as ih

    monkeypatch.setattr(
        ih.subprocess,
        "run",
        lambda argv, **kw: _proc(2, stderr="guard_raw_data crashed unexpectedly; failing closed."),
    )
    rows = ih._check_guard_hooks("python3", Path(__file__).resolve().parents[1], tmp_path)
    dispatcher_rows = [r for r in rows if "locked-menu" not in r[0]]
    assert all(status == "ERROR" for _, status, _ in dispatcher_rows)
    assert all("crashed" in detail for _, _, detail in dispatcher_rows)


def test_run_env_check_aggregates_and_reports_clean(capsys, monkeypatch):
    import install_helper as ih
    from install_helper import Style, marks, run_env_check

    monkeypatch.setattr(
        ih, "_check_interpreters", lambda order: ([("python3", "OK", "Python 3.12")], "python3")
    )
    monkeypatch.setattr(ih, "find_bash", lambda: "/usr/bin/bash")
    monkeypatch.setattr(ih, "_check_encoding_roundtrip", lambda interp: ("OK", "clean"))
    monkeypatch.setattr(ih, "_check_plugin_root_bootstrap", lambda root: ("OK", "resolves"))
    monkeypatch.setattr(
        ih, "_check_guard_hooks", lambda interp, root, tmp: [("Bash", "OK", "clean")]
    )
    monkeypatch.setattr(
        ih, "probe_analyser_output", lambda tmp, runner=None: iter([("ruff", "OK", "clean")])
    )
    rc = run_env_check(Style(False), marks())
    out = capsys.readouterr().out
    assert rc == 0
    assert "Environment looks clean." in out


def test_run_env_check_aggregates_and_reports_issues(capsys, monkeypatch):
    import install_helper as ih
    from install_helper import Style, marks, run_env_check

    monkeypatch.setattr(
        ih, "_check_interpreters", lambda order: ([("python3", "ERROR", "broken")], "")
    )
    monkeypatch.setattr(ih, "find_bash", lambda: None)
    monkeypatch.setattr(ih, "_check_encoding_roundtrip", lambda interp: ("SKIP", "no interpreter"))
    monkeypatch.setattr(ih, "_check_plugin_root_bootstrap", lambda root: ("WARN", "nothing found"))
    monkeypatch.setattr(
        ih, "_check_guard_hooks", lambda interp, root, tmp: [("Bash", "SKIP", "no interpreter")]
    )
    monkeypatch.setattr(ih, "probe_analyser_output", lambda tmp, runner=None: iter([]))
    rc = run_env_check(Style(False), marks())
    out = capsys.readouterr().out
    assert rc == 1
    assert "1 issue(s) found" in out


# ============================================================================================
# install_helper UX overhaul (2026-08-04 user request): --configure, archive/list bridge,
# the 'virt-surv' alias, and the reorganised grouped menu.
# ============================================================================================

# --- ask_and_set_model (extracted from the Installer method of the same name) --------------


def test_ask_and_set_model_project_scope(tmp_path, monkeypatch):
    import install_helper as ih

    monkeypatch.setattr("builtins.input", lambda prompt="": "")  # scope=project, model=default
    ok, message = ih.ask_and_set_model(tmp_path, ih.Style(False), assume_yes=False)
    assert ok
    settings = json.loads((tmp_path / ".claude" / "settings.json").read_text())
    assert settings["model"] == ih.ORCHESTRATOR_MODEL_IDS[ih.ORCHESTRATOR_MODEL_DEFAULT]


def test_ask_and_set_model_rejects_bad_input(tmp_path, monkeypatch):
    import install_helper as ih

    monkeypatch.setattr(sys, "stdin", _TtyStdin())  # confirm()/ask() short-circuit to
    # their own default when stdin isn't a real tty - needed for scripted input() to
    # actually be consumed rather than silently ignored.
    answers = iter(["", "not-a-model"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    ok, message = ih.ask_and_set_model(tmp_path, ih.Style(False), assume_yes=False)
    assert not ok
    assert "expected opus/sonnet/sonnet-4-6/default" in message


def test_ask_and_set_model_demo_mode_writes_nothing(tmp_path, monkeypatch):
    import install_helper as ih

    monkeypatch.setattr("builtins.input", lambda prompt="": "")
    ok, message = ih.ask_and_set_model(tmp_path, ih.Style(False), assume_yes=False, demo=True)
    assert ok
    assert "would set" in message


def test_ask_and_set_model_offer_global_scope_false_skips_that_question(tmp_path, monkeypatch):
    """Fable UX review, 2026-08-05: Advanced menu's "Morgan's model (per project only)"
    asked the global-scope question anyway, contradicting its own label. With
    offer_global_scope=False the question must never even be asked (consumes only the
    model-choice answer, never a global-scope answer) and must always write per-project."""
    import install_helper as ih

    monkeypatch.setattr(sys, "stdin", _TtyStdin())
    answers = iter(["opus"])  # if the scope question were ALSO asked, this would be
    # consumed by it instead and the model picker would hit StopIteration.
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    ok, message = ih.ask_and_set_model(
        tmp_path, ih.Style(False), assume_yes=False, offer_global_scope=False
    )
    assert ok
    settings = json.loads((tmp_path / ".claude" / "settings.json").read_text())
    assert settings["model"] == ih.ORCHESTRATOR_MODEL_IDS["opus"]  # written per-project


def test_model_step_never_offers_global_scope(monkeypatch, tmp_path):
    """Installer.model_step (Advanced -> "Morgan's model (per project only)") must call
    ask_and_set_model with offer_global_scope=False - a coverage gap found while fixing
    the fable UX review's finding #11 (no prior test exercised model_step at all)."""
    import install_helper as ih

    project = tmp_path / "proj"
    project.mkdir()
    monkeypatch.setattr(ih, "ask", lambda *a, **k: str(project))
    calls = []
    monkeypatch.setattr(
        ih,
        "ask_and_set_model",
        lambda proj, style, assume_yes, demo, **kw: calls.append(kw) or (True, "ok"),
    )
    inst = ih.Installer(_args(yes=False), ih.Style(False), ih.marks(), subset="model")
    inst.model_step()
    assert calls == [{"offer_global_scope": False}]
    assert not (tmp_path / ".claude").exists()


# --- run_configure ---------------------------------------------------------------------------


def test_run_configure_model_call_never_offers_global_scope(tmp_path, monkeypatch):
    """run_configure's own "Set Morgan's model for this project?" call had the identical
    bug test_model_step_never_offers_global_scope was written for (2026-08-12 onboarding
    UX audit: not caught when model_step was fixed) - must pass offer_global_scope=False
    too, or a project-scoped question silently offers to change the global default."""
    import install_helper as ih

    _isolate_home(monkeypatch, tmp_path)
    monkeypatch.setattr(ih, "run_cmd", lambda *a, **k: _FakeProc(0))
    calls = []
    monkeypatch.setattr(
        ih,
        "ask_and_set_model",
        lambda proj, style, assume_yes, demo, **kw: calls.append(kw) or (True, "ok"),
    )
    rc = ih.run_configure(tmp_path, ih.Style(False), ih.marks(), assume_yes=True)
    assert rc == 0
    assert calls == [{"offer_global_scope": False}]


def test_run_configure_happy_path_yes(tmp_path, monkeypatch, capsys):
    import install_helper as ih

    _isolate_home(monkeypatch, tmp_path)
    monkeypatch.setattr(ih, "run_cmd", lambda *a, **k: _FakeProc(0))
    rc = ih.run_configure(tmp_path, ih.Style(False), ih.marks(), assume_yes=True)
    out = capsys.readouterr().out
    assert rc == 0
    # run_enable_project's exit-0 path assumes the (mocked) claude CLI did its own job -
    # it only writes enabledPlugins directly in the CLI-blocked fallback path (see
    # test_run_enable_project_invokes_claude_in_project_cwd, which checks the same
    # printed confirmation rather than settings.json content for this exact scenario).
    assert "enabled for" in out
    settings = json.loads((tmp_path / ".claude" / "settings.json").read_text())
    assert "permissions" in settings  # --yes defaults the permissions confirm to True
    # 2026-08-12 user request: "recommended should set the model to sonnet" - the
    # recommended-defaults path now explicitly pins it rather than leaving `model` unset.
    assert settings["model"] == ih.ORCHESTRATOR_MODEL_IDS["sonnet"]
    prefs = json.loads((tmp_path / ".claude" / "team-preferences.json").read_text())
    assert prefs == {
        "extra_formats": [],
        "regulatory_citations": False,
        "large_context_review_split": False,  # 2026-08-12: default flipped off
        "parallel_dispatch_via_workflow": True,
        "standards_critique": False,  # pre-existing gap in this assertion, caught now -
        # run_configure has passed this explicitly since standards_critique was added
        # earlier this session; this test's dict just never got updated to match
        "map_skeleton": True,
        "statusline_show_map": False,
        "guard_daemon": True,  # 2026-08-12 user request: on by default
    }
    assert "Configuration complete" in out


def test_run_configure_manual_walkthrough_leaves_model_unset_when_declined(tmp_path, monkeypatch):
    """The manual walkthrough (assume_yes False, "n" to recommended settings) must stay
    opt-in for the model question - only the recommended-defaults path auto-pins sonnet
    (see test_run_configure_happy_path_yes); declining here should leave `model` absent
    from settings.json entirely, same as before 2026-08-12."""
    import install_helper as ih

    _isolate_home(monkeypatch, tmp_path)
    monkeypatch.setattr(ih, "run_cmd", lambda *a, **k: _FakeProc(0))
    monkeypatch.setattr(sys, "stdin", _TtyStdin())
    # "n" to recommended settings, then "" (accept every default) all the way through -
    # 4 leading confirms + 8 preference confirms (guard_daemon added 2026-08-12) +
    # review-tools override + "" declines the final "set Morgan's model?" question
    # (default False).
    answers = iter(["n", "", "", "", "", "", "", "", "", "", "", "", "", ""])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    rc = ih.run_configure(tmp_path, ih.Style(False), ih.marks(), assume_yes=False)
    assert rc == 0
    settings = json.loads((tmp_path / ".claude" / "settings.json").read_text())
    assert "model" not in settings


def test_run_configure_not_a_directory():
    import install_helper as ih

    rc = ih.run_configure(Path("/no/such/dir"), ih.Style(False), ih.marks(), assume_yes=True)
    assert rc == 1


def test_run_configure_shows_step_progress_headers(tmp_path, monkeypatch, capsys):
    """2026-08-12 onboarding UX audit: this flow had no progress indicator at all, unlike
    every Installer-driven flow's "Step N of M" headers - fixed by reusing rule_header
    for the same 7 sections every run always has, real or --demo."""
    import install_helper as ih

    _isolate_home(monkeypatch, tmp_path)
    monkeypatch.setattr(ih, "run_cmd", lambda *a, **k: _FakeProc(0))
    ih.run_configure(tmp_path, ih.Style(False), ih.marks(), assume_yes=True)
    out = capsys.readouterr().out
    for n, title in enumerate(
        [
            "Enable the plugin",
            "Permission allow-list",
            "API/env tuning",
            "LLM-gateway workaround",
            "Project preferences",
            "Refreshing the analyser-availability cache",
            "Morgan's model",
        ],
        start=1,
    ):
        assert f"Step {n} of 7: {title}" in out


def test_run_configure_declined_answer_gets_immediate_feedback(tmp_path, monkeypatch):
    """2026-08-12 onboarding UX audit: declining permissions/env-tuning/betas/model
    produced no output at all until the closing summary table - fixed with an immediate
    skip mark + '(declined)' right where the question was asked."""
    import install_helper as ih

    _isolate_home(monkeypatch, tmp_path)
    monkeypatch.setattr(ih, "run_cmd", lambda *a, **k: _FakeProc(0))
    monkeypatch.setattr(ih, "confirm", lambda *a, **k: False)
    lines = []
    monkeypatch.setattr("builtins.print", lambda *a, **k: lines.append(" ".join(str(x) for x in a)))
    ih.run_configure(tmp_path, ih.Style(False), ih.marks(), assume_yes=False)
    out = "\n".join(lines)
    assert "Permission allow-list" in out and "(declined)" in out
    assert "API/env tuning" in out
    assert "LLM-gateway workaround" in out
    assert "Morgan's model" in out


def test_run_configure_recommended_settings_is_a_one_click_fast_path(tmp_path, monkeypatch, capsys):
    """2026-08-05 user request: "option to go with recommended settings as a one click
    option ... gets the user quickly up and running". Accepting it (blank = the default,
    Yes) must consume exactly ONE answer and apply every default without asking anything
    else - functionally identical to assume_yes=True from here on."""
    import install_helper as ih

    _isolate_home(monkeypatch, tmp_path)
    monkeypatch.setattr(ih, "run_cmd", lambda *a, **k: _FakeProc(0))
    monkeypatch.setattr(sys, "stdin", _TtyStdin())
    answers = iter([""])  # blank = Yes to "use recommended settings?" - nothing else asked
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    rc = ih.run_configure(tmp_path, ih.Style(False), ih.marks(), assume_yes=False)
    out = capsys.readouterr().out
    assert rc == 0
    assert "Configuration complete" in out
    settings = json.loads((tmp_path / ".claude" / "settings.json").read_text())
    assert "permissions" in settings  # recommended settings includes the allow-list


def test_run_configure_already_yes_skips_the_recommended_settings_question(tmp_path, monkeypatch):
    """assume_yes=True (e.g. from --yes) must not ALSO ask "use recommended settings?"
    - that would be asking a question nobody can see/answer on a scripted run."""
    import install_helper as ih

    _isolate_home(monkeypatch, tmp_path)
    monkeypatch.setattr(ih, "run_cmd", lambda *a, **k: _FakeProc(0))
    called = []
    monkeypatch.setattr(ih, "confirm", lambda prompt, *a, **k: called.append(prompt) or True)
    ih.run_configure(tmp_path, ih.Style(False), ih.marks(), assume_yes=True)
    assert not any("recommended settings" in p.lower() for p in called)


def test_project_preference_defaults_falls_back_to_machine_default(tmp_path):
    """2026-08-05 user request: "sensible defaults" must respect a machine-level
    override - e.g. ruff disabled at machine level must stay disabled by default for a
    brand-new project (empty `existing`), never silently re-enabled."""
    from install_helper import _project_preference_defaults

    machine_defaults = {
        "default_docx": True,
        "default_regulatory_citations": False,
        "default_review_tools": {"ruff": "off"},
        "default_map_skeleton": True,
        "default_statusline_show_map": True,
    }
    docx, citations, review_tools, map_skeleton, statusline_show_map = _project_preference_defaults(
        {}, machine_defaults
    )
    assert docx is True
    assert citations is False
    assert review_tools == {"ruff": "off"}
    assert map_skeleton is True
    assert statusline_show_map is True


def test_project_preference_defaults_project_choice_overrides_machine(tmp_path):
    """A project that has ALREADY made its own explicit choice (key present, even if it
    happens to match the built-in default) always wins over the machine default -
    "can be overridden in the project's settings"."""
    from install_helper import _project_preference_defaults

    existing = {
        "extra_formats": ["docx"],
        "regulatory_citations": True,
        "review_tools": {},
        "map_skeleton": False,
        "statusline_show_map": False,
    }
    machine_defaults = {
        "default_docx": False,
        "default_regulatory_citations": False,
        "default_review_tools": {"ruff": "off"},
        "default_map_skeleton": True,
        "default_statusline_show_map": True,
    }
    docx, citations, review_tools, map_skeleton, statusline_show_map = _project_preference_defaults(
        existing, machine_defaults
    )
    assert docx is True  # project's own "docx on" wins over machine's "off"
    assert citations is True  # project's own "on" wins over machine's "off"
    assert review_tools == {}  # project's own explicit "all auto" wins over machine's override
    assert map_skeleton is False  # project's own explicit "off" wins even though it's falsy
    assert statusline_show_map is False  # same, for the statusline preference


def test_project_preference_defaults_no_machine_config_uses_builtin(tmp_path):
    """No project setting AND no machine config at all - the built-in CONFIGURE-recommended
    default (docx off, citations off, review-tools all auto, map_skeleton on - 2026-08-07)
    applies."""
    from install_helper import _project_preference_defaults

    docx, citations, review_tools, map_skeleton, statusline_show_map = _project_preference_defaults(
        {}, {}
    )
    assert docx is False
    assert citations is False
    assert review_tools == {}
    assert map_skeleton is True
    assert statusline_show_map is False


def test_run_configure_declines_permissions_when_not_assume_yes(tmp_path, monkeypatch):
    import install_helper as ih

    _isolate_home(monkeypatch, tmp_path)
    monkeypatch.setattr(ih, "run_cmd", lambda *a, **k: _FakeProc(0))
    monkeypatch.setattr(sys, "stdin", _TtyStdin())  # see test_ask_and_set_model_rejects_bad_input
    # "n" to "use recommended settings?" (walk through each choice instead), "no" to the
    # permissions question, "no" to the env-tuning question, "no" to the beta-fields-
    # workaround question (keeps "nothing creates the file" true below), "" (accept
    # defaults) to the eight preference prompts (docx, citations, review-split,
    # workflow-dispatch, standards-critique, map-skeleton, statusline-map, guard_daemon -
    # added 2026-08-12), "" (no change) to the review-tools override prompt, "" to the
    # model prompt (declines - default is False).
    answers = iter(["n", "n", "n", "n", "", "", "", "", "", "", "", "", "", ""])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    rc = ih.run_configure(tmp_path, ih.Style(False), ih.marks(), assume_yes=False)
    assert rc == 0
    # The mocked exit-0 "claude plugin enable" doesn't itself write settings.json (that's
    # only the CLI-blocked fallback path) - permissions declined means nothing ever
    # creates the file at all here, which is itself the point being verified.
    settings_path = tmp_path / ".claude" / "settings.json"
    if settings_path.is_file():
        assert "permissions" not in json.loads(settings_path.read_text())


# --- archive / list-engagements bridge -------------------------------------------------------


def test_run_list_engagements_bridges_with_cwd_scoped_to_target(tmp_path, monkeypatch):
    import install_helper as ih

    calls = []

    def fake_run(argv, cwd=None, **kw):
        calls.append((argv, cwd))
        return _proc(0, stdout="no engagements found")

    monkeypatch.setattr(ih.subprocess, "run", fake_run)
    rc = ih.run_list_engagements(tmp_path, ih.Style(False), ih.marks())
    assert rc == 0
    (argv, cwd) = calls[0]
    assert argv[1:] == [
        str(Path(ih.__file__).resolve().parent / "scripts" / "engagement_state.py"),
        "list",
    ]
    assert cwd == tmp_path.resolve()


def test_run_list_engagements_not_a_directory():
    import install_helper as ih

    assert ih.run_list_engagements(Path("/no/such/dir"), ih.Style(False), ih.marks()) == 1


def test_run_archive_engagements_uses_all_closed_flag(tmp_path, monkeypatch):
    import install_helper as ih

    calls = []

    def fake_run(argv, cwd=None, **kw):
        calls.append(argv)
        return _proc(0, stdout="nothing to archive")

    monkeypatch.setattr(ih.subprocess, "run", fake_run)
    rc = ih.run_archive_engagements(tmp_path, ih.Style(False), ih.marks())
    assert rc == 0
    assert "archive" in calls[0] and "--all-closed" in calls[0]


def test_run_archive_engagements_surfaces_nonzero_exit(tmp_path, monkeypatch):
    import install_helper as ih

    monkeypatch.setattr(ih.subprocess, "run", lambda *a, **k: _proc(1, stderr="boom"))
    rc = ih.run_archive_engagements(tmp_path, ih.Style(False), ih.marks())
    assert rc == 1


def test_run_manage_engagements_lists_then_declines_archive(tmp_path, monkeypatch):
    import install_helper as ih

    monkeypatch.setattr(ih.subprocess, "run", lambda *a, **k: _proc(0, stdout="ok"))
    monkeypatch.setattr("builtins.input", lambda prompt="": "n")
    rc = ih.run_manage_engagements(tmp_path, ih.Style(False), ih.marks(), assume_yes=False)
    assert rc == 0


def test_run_manage_engagements_stops_early_if_list_fails(tmp_path, monkeypatch):
    import install_helper as ih

    monkeypatch.setattr(ih.subprocess, "run", lambda *a, **k: _proc(1, stderr="boom"))
    rc = ih.run_manage_engagements(tmp_path, ih.Style(False), ih.marks())
    assert rc == 1  # never reaches the archive confirm


# --- alias setup -------------------------------------------------------------------------------


def _isolate_home_for_alias(monkeypatch, tmp_path, bashrc=None):
    """bashrc=None (default): no .bashrc/.zshrc created at all. bashrc="<text>": write
    that text to .bashrc - most callers just want an empty file (bashrc="").

    Also stubs detect_or_configure_claude_launch_command to a fixed 'claude', no prompt,
    no real config I/O - 2026-08-15: run_setup_alias started calling it unconditionally
    (needed to bake the launch command into the new 'go' branch), so every existing
    caller of this helper picks up a safe default for free rather than needing an
    individual update at each of the ~19 call sites."""
    import install_helper as ih

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    monkeypatch.setattr(ih, "detect_or_configure_claude_launch_command", lambda *a, **k: "claude")
    if bashrc is not None:
        (home / ".bashrc").write_text(bashrc, encoding="utf-8")
    return home


def test_setup_alias_writes_bashrc(tmp_path, monkeypatch):
    """2026-08-15: virt-surv's POSIX form is now a shell FUNCTION, not a plain `alias` -
    a `go` subcommand needs real conditional logic (branch on $1), which a text-substitution
    alias can never express. `type`/`Get-Command` (what _verify_alias_line checks) resolve
    a function exactly like an alias, so verification itself is unaffected."""
    import install_helper as ih

    home = _isolate_home_for_alias(monkeypatch, tmp_path, bashrc="")
    _stub_interpreters(monkeypatch, ih)
    monkeypatch.setattr(ih, "detect_or_configure_claude_launch_command", lambda *a, **k: "claude")
    rc = ih.run_setup_alias(ih.Style(False), ih.marks(), assume_yes=True)
    assert rc == 0
    content = (home / ".bashrc").read_text(encoding="utf-8")
    assert "virt-surv() {" in content
    assert '"$1" = "go"' in content  # the go-branch, the whole reason this is a function now
    assert "python3" in content


def test_setup_alias_uses_configured_clone_not_bootstrap_temp_path(tmp_path, monkeypatch):
    """Live report, 2026-08-04: --setup-alias run from the curl-bootstrap temp extraction
    (before the full clone exists) baked that TEMP path into the alias, breaking it the
    moment the temp dir was cleaned up - and clobbered a previously-correct alias on
    re-run. Fix: prefer installer.json's repo_path when __file__'s own parent isn't a
    real repo."""
    import install_helper as ih

    home = _isolate_home_for_alias(monkeypatch, tmp_path, bashrc="")

    clone = tmp_path / "clone"
    clone.mkdir()
    (clone / ".git").mkdir()
    (clone / ".claude-plugin").mkdir()
    (clone / ".claude-plugin" / "plugin.json").write_text("{}", encoding="utf-8")
    (clone / "install_helper.py").write_text("# real clone copy\n", encoding="utf-8")

    xdg = tmp_path / "xdg"
    (xdg / "virt-surv-it").mkdir(parents=True)
    (xdg / "virt-surv-it" / "installer.json").write_text(
        json.dumps({"repo_path": str(clone)}), encoding="utf-8"
    )
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))

    boot_copy = tmp_path / "boot" / "install_helper.py"
    boot_copy.parent.mkdir()
    boot_copy.write_text("# bootstrap temp copy\n", encoding="utf-8")
    monkeypatch.setattr(ih, "__file__", str(boot_copy))
    _stub_interpreters(monkeypatch, ih)

    rc = ih.run_setup_alias(ih.Style(False), ih.marks(), assume_yes=True)
    assert rc == 0
    content = (home / ".bashrc").read_text(encoding="utf-8")
    assert str(clone) in content
    assert "boot" not in content  # the temp path must never land in the alias


def test_setup_alias_warns_when_no_real_clone_found_anywhere(tmp_path, monkeypatch, capsys):
    """No installer.json, no configured repo_path, __file__ itself isn't a real repo -
    the alias still gets written (best effort against the only path we have) but with a
    clear warning, not silently."""
    import install_helper as ih

    _isolate_home_for_alias(monkeypatch, tmp_path, bashrc="")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "no-such-xdg"))

    boot_copy = tmp_path / "boot" / "install_helper.py"
    boot_copy.parent.mkdir()
    boot_copy.write_text("# bootstrap temp copy\n", encoding="utf-8")
    monkeypatch.setattr(ih, "__file__", str(boot_copy))
    _stub_interpreters(monkeypatch, ih)

    rc = ih.run_setup_alias(ih.Style(False), ih.marks(), assume_yes=True)
    out = capsys.readouterr().out
    assert rc == 0
    assert "no real clone found" in out


def test_setup_alias_defaults_to_no_when_no_real_clone_found(tmp_path, monkeypatch):
    """Fable UX review, 2026-08-05: the "Add it?" confirm defaulted to Yes regardless -
    pressing Enter after the "may be temporary" warning wrote exactly what it warned
    against. Blank input must now decline when no real clone was found."""
    import install_helper as ih

    home = _isolate_home_for_alias(monkeypatch, tmp_path, bashrc="")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "no-such-xdg"))
    boot_copy = tmp_path / "boot" / "install_helper.py"
    boot_copy.parent.mkdir()
    boot_copy.write_text("# bootstrap temp copy\n", encoding="utf-8")
    monkeypatch.setattr(ih, "__file__", str(boot_copy))
    _stub_interpreters(monkeypatch, ih)
    monkeypatch.setattr(sys, "stdin", _TtyStdin())
    monkeypatch.setattr("builtins.input", lambda prompt="": "")  # blank = the default
    rc = ih.run_setup_alias(ih.Style(False), ih.marks(), assume_yes=False)
    assert rc == 0
    assert (home / ".bashrc").read_text(encoding="utf-8") == ""  # declined, nothing written


def test_setup_alias_idempotent_skip(tmp_path, monkeypatch, capsys):
    """A genuinely current alias - the EXACT line this run would write, already present
    (here: written by a first run moments earlier) - is skipped, not duplicated.
    Staleness is exact-line now, not any structural signature: see _ALIAS_VERSION's
    comment for the two shape-signature failures, and the 2026-08-16 launch-command
    report for why "current shape" was still too weak (a rebaked VALUE must upgrade
    too, not just a changed template)."""
    import install_helper as ih

    home = _isolate_home_for_alias(monkeypatch, tmp_path, bashrc="")
    _stub_interpreters(monkeypatch, ih)
    assert ih.run_setup_alias(ih.Style(False), ih.marks(), assume_yes=True) == 0
    rc = ih.run_setup_alias(ih.Style(False), ih.marks(), assume_yes=True)
    out = capsys.readouterr().out
    assert rc == 0
    assert "already exists, skipped" in out
    content = (home / ".bashrc").read_text(encoding="utf-8")
    # Not duplicated - count FUNCTION DEFINITIONS, not the bare marker string (the
    # version stamp itself contains "virt-surv", so a bare count would double).
    assert content.count("virt-surv() {") == 1


def test_setup_alias_line_is_launch_command_independent(tmp_path, monkeypatch, capsys):
    """v5 inverts the 2026-08-16 fix one step further: the launch command is no longer
    IN the line at all (the launcher answers --launch-command at run time), so a config
    change alone must leave a current alias exactly as it is - no upgrade churn, and
    the change is live on the next 'go' with no profile reload (2026-08-17 live
    report: even a config RESET kept launching the old baked value)."""
    import install_helper as ih

    home = _isolate_home_for_alias(monkeypatch, tmp_path, bashrc="")
    _stub_interpreters(monkeypatch, ih)
    assert ih.run_setup_alias(ih.Style(False), ih.marks(), assume_yes=True) == 0
    monkeypatch.setattr(ih, "detect_or_configure_claude_launch_command", lambda *a, **k: "cc")
    rc = ih.run_setup_alias(ih.Style(False), ih.marks(), assume_yes=True)
    out = capsys.readouterr().out
    assert rc == 0
    assert "already exists, skipped" in out
    content = (home / ".bashrc").read_text(encoding="utf-8")
    assert content.count("virt-surv() {") == 1  # identical line - never re-appended
    assert '"cc"' not in content  # and no command value anywhere in it


def test_setup_alias_upgrades_a_pre_go_alias_instead_of_skipping(tmp_path, monkeypatch, capsys):
    """Live report (2026-08-15): an alias written before the 'go' branch existed used to
    hit the plain "already exists, skipped" path forever - re-running setup could never
    upgrade it, leaving 'go' silently unreachable via the shell (falls through to
    _run_go's own direct-invocation path instead, confusingly reporting the launch
    command "isn't a real executable" for a perfectly valid shell alias/function).
    Old-shape (pre-go) content must now trigger an upgrade instead: append the new
    definition, never edit the old line's text (may be user-customised)."""
    import install_helper as ih

    home = _isolate_home_for_alias(monkeypatch, tmp_path, bashrc="alias virt-surv='already here'\n")
    _stub_interpreters(monkeypatch, ih)
    rc = ih.run_setup_alias(ih.Style(False), ih.marks(), assume_yes=True)
    out = capsys.readouterr().out
    assert rc == 0
    assert "out of date" in out
    content = (home / ".bashrc").read_text(encoding="utf-8")
    assert "alias virt-surv='already here'" in content  # old line untouched, not deleted
    assert "unalias virt-surv 2>/dev/null" in content  # neutralises the OLD alias's shadowing
    assert "virt-surv() {" in content
    assert '"$1" = "go"' in content  # the new definition, appended below


def test_setup_alias_upgrades_a_go_era_alias_missing_the_engage_prefix(
    tmp_path, monkeypatch, capsys
):
    """Live Windows report (2026-08-16): a profile written between the 'go' fix and the
    '/engage'-prefix fix (f53e907) still passed a bare "--new" to claude, which errors
    with "unknown option '--new'" - and the old 'go'-signature staleness check judged
    that alias CURRENT, so re-running setup skipped it forever and the shipped fix
    could never reach the machine. Any entry without the current version stamp must now
    upgrade instead."""
    import install_helper as ih

    go_era_line = (
        'virt-surv() { if [ "$1" = "go" ]; then shift; local __vt_d; '
        '__vt_d="$("python3" "/old/scripts/virt_team_launcher.py")"; '
        '"claude" ${__vt_d:+"$__vt_d"} "$@"; '
        'else "python3" "/old/install_helper.py" "$@"; fi; }\n'
    )
    home = _isolate_home_for_alias(monkeypatch, tmp_path, bashrc=go_era_line)
    _stub_interpreters(monkeypatch, ih)
    rc = ih.run_setup_alias(ih.Style(False), ih.marks(), assume_yes=True)
    out = capsys.readouterr().out
    assert rc == 0
    assert "out of date" in out
    content = (home / ".bashrc").read_text(encoding="utf-8")
    assert '${__vt_d:+"$__vt_d"}' in content  # the new pass-through definition
    assert ih._ALIAS_STAMP in content  # and the stamp that marks it current


def test_setup_alias_upgrade_removes_old_stamped_definitions(tmp_path, monkeypatch, capsys):
    """Live report (2026-08-17): append-only upgrades left 5 dead virt-surv definitions
    in a corp PowerShell profile, one still baking the abandoned 'cc --debug' launch
    command - dead weight that runs again if the newest line ever fails to load. Old
    STAMPED definitions are provably machine-written, so an upgrade now removes them
    (with their '# Added by' comment), previewed line by line."""
    import install_helper as ih

    old = (
        "# Added by install_helper.py --setup-alias (2026-08-04)\n"
        'virt-surv() { if [ "$1" = "go" ]; then "cc --debug" stale; fi; } '
        "# virt-surv-alias-v4\n"
    )
    home = _isolate_home_for_alias(monkeypatch, tmp_path, bashrc="echo unrelated\n\n" + old)
    _stub_interpreters(monkeypatch, ih)
    rc = ih.run_setup_alias(ih.Style(False), ih.marks(), assume_yes=True)
    out = capsys.readouterr().out
    assert rc == 0
    assert "would remove" in out
    assert "removed 1 outdated definition(s)" in out
    content = (home / ".bashrc").read_text(encoding="utf-8")
    assert "cc --debug" not in content  # the stale baked line is GONE, not shadowed
    assert "virt-surv-alias-v4" not in content
    assert content.count("virt-surv() {") == 1  # exactly the new definition
    assert content.count("# Added by install_helper.py") == 1  # old comment went with it
    assert "echo unrelated" in content  # everything else untouched
    # and no unalias prefix: no unstamped marker content remained to shadow the function
    assert "unalias" not in content


def test_setup_alias_upgrade_keeps_unstamped_marker_lines(tmp_path, monkeypatch, capsys):
    """The other tier: an UNSTAMPED line mentioning virt-surv may be user-written or
    customised - indistinguishable from a pre-stamp-era install - so it is never
    removed; the new definition is appended after it with the unalias guard."""
    import install_helper as ih

    custom = "alias virt-surv='my customised thing'\n"
    home = _isolate_home_for_alias(monkeypatch, tmp_path, bashrc=custom)
    _stub_interpreters(monkeypatch, ih)
    rc = ih.run_setup_alias(ih.Style(False), ih.marks(), assume_yes=True)
    out = capsys.readouterr().out
    assert rc == 0
    assert "stays untouched" in out
    content = (home / ".bashrc").read_text(encoding="utf-8")
    assert "alias virt-surv='my customised thing'" in content
    assert "unalias virt-surv 2>/dev/null" in content  # old alias must not shadow the function
    assert ih._ALIAS_STAMP in content


def test_setup_alias_upgrade_demo_removes_nothing(tmp_path, monkeypatch, capsys):
    import install_helper as ih

    old = (
        "# Added by install_helper.py --setup-alias (2026-08-04)\n"
        "virt-surv() { stale; } # virt-surv-alias-v4\n"
    )
    home = _isolate_home_for_alias(monkeypatch, tmp_path, bashrc=old)
    _stub_interpreters(monkeypatch, ih)
    rc = ih.run_setup_alias(ih.Style(False), ih.marks(), assume_yes=True, demo=True)
    out = capsys.readouterr().out
    assert rc == 0
    assert "would remove" in out
    assert (home / ".bashrc").read_text(encoding="utf-8") == old  # untouched


def test_setup_alias_written_lines_carry_the_version_stamp(tmp_path, monkeypatch):
    """The stamp IS the upgrade mechanism: a freshly written line without it would be
    judged stale and re-appended on every future setup run. It must also be a comment
    in the target shell (leading '#'), never executable text."""
    import install_helper as ih

    assert ih._ALIAS_STAMP.startswith("# ")
    home = _isolate_home_for_alias(monkeypatch, tmp_path, bashrc="")
    _stub_interpreters(monkeypatch, ih)
    rc = ih.run_setup_alias(ih.Style(False), ih.marks(), assume_yes=True)
    assert rc == 0
    content = (home / ".bashrc").read_text(encoding="utf-8")
    assert ih._ALIAS_STAMP in content


def test_setup_alias_no_interpreter_found(tmp_path, monkeypatch):
    import install_helper as ih

    _isolate_home_for_alias(monkeypatch, tmp_path)
    monkeypatch.setattr(
        ih, "_check_interpreters", lambda order: ([("python3", "SKIP", "not on PATH")], "")
    )
    rc = ih.run_setup_alias(ih.Style(False), ih.marks(), assume_yes=True)
    assert rc == 1


def test_setup_alias_no_shell_config_found(tmp_path, monkeypatch):
    import install_helper as ih

    _isolate_home_for_alias(monkeypatch, tmp_path)  # no .bashrc/.zshrc created
    _stub_interpreters(monkeypatch, ih)
    monkeypatch.setattr(ih.sys, "platform", "linux")
    rc = ih.run_setup_alias(ih.Style(False), ih.marks(), assume_yes=True)
    assert rc == 1


def test_setup_alias_declined_is_not_an_error(tmp_path, monkeypatch):
    import install_helper as ih

    home = _isolate_home_for_alias(monkeypatch, tmp_path, bashrc="")
    _stub_interpreters(monkeypatch, ih)
    monkeypatch.setattr(sys, "stdin", _TtyStdin())  # see test_ask_and_set_model_rejects_bad_input
    monkeypatch.setattr("builtins.input", lambda prompt="": "n")
    rc = ih.run_setup_alias(ih.Style(False), ih.marks(), assume_yes=False)  # confirm() -> declined
    assert rc == 0  # declining is a choice, not a failure
    assert "virt-surv" not in (home / ".bashrc").read_text(encoding="utf-8")


def test_setup_alias_write_error_is_reported(tmp_path, monkeypatch):
    import install_helper as ih

    _isolate_home_for_alias(monkeypatch, tmp_path, bashrc="")
    _stub_interpreters(monkeypatch, ih)

    real_open = Path.open

    def boom_open(self, mode="r", *a, **kw):
        if "a" in mode:
            raise OSError("disk full")
        return real_open(self, mode, *a, **kw)

    monkeypatch.setattr(Path, "open", boom_open)
    rc = ih.run_setup_alias(ih.Style(False), ih.marks(), assume_yes=True)
    assert rc == 1


# --- alias verification (2026-08-04 user request: "harden ... include test of the alias") -----


def test_verify_alias_line_posix_success():
    import install_helper as ih

    ok, note = ih._verify_alias_line(
        "bash", Path("/fake/.bashrc"), f"alias {ih._ALIAS_MARKER}='echo hi'"
    )
    assert ok is True
    assert "resolves cleanly" in note


def test_verify_alias_line_posix_catches_bad_syntax():
    """expand_aliases quirk aside, a genuinely broken line (unbalanced quote) must be
    caught, not silently reported as working."""
    import install_helper as ih

    ok, note = ih._verify_alias_line(
        "bash", Path("/fake/.bashrc"), f"alias {ih._ALIAS_MARKER}='echo \"unbalanced"
    )
    assert ok is False
    assert "does not resolve cleanly" in note


def test_verify_alias_line_missing_shell_is_not_a_failure(monkeypatch):
    import install_helper as ih

    monkeypatch.setattr(ih, "find_bash", lambda: None)
    ok, note = ih._verify_alias_line("bash", Path("/fake/.bashrc"), "alias x='y'")
    assert ok is True
    assert "could not verify" in note


def test_setup_alias_write_error_from_verification_sets_had_error(tmp_path, monkeypatch):
    """A write that succeeds but verifies as broken must still surface as rc=1 - the
    whole point of hardening is not silently claiming success on a non-working alias."""
    import install_helper as ih

    home = _isolate_home_for_alias(monkeypatch, tmp_path, bashrc="")
    _stub_interpreters(monkeypatch, ih)
    monkeypatch.setattr(
        ih, "_verify_alias_line", lambda label, rc_path, line: (False, "simulated broken alias")
    )
    rc = ih.run_setup_alias(ih.Style(False), ih.marks(), assume_yes=True)
    assert rc == 1
    # The file write itself still succeeded - verification failing doesn't undo it.
    assert "virt-surv() {" in (home / ".bashrc").read_text(encoding="utf-8")


def test_powershell_profile_candidates_windows_only(tmp_path, monkeypatch):
    import install_helper as ih

    monkeypatch.setattr(ih.sys, "platform", "linux")
    assert ih._powershell_profile_candidates() == []

    monkeypatch.setattr(ih.sys, "platform", "win32")
    home = tmp_path / "winhome"
    (home / "Documents").mkdir(parents=True)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    # Neither binary "found" on this (real Linux) test host - exercises the static-guess
    # FALLBACK path, not the live $PROFILE query (that needs a real Windows shutil.which,
    # which crashes under a faked sys.platform on Linux - a test-harness limitation, not
    # a product one; the query path itself is covered by
    # test_powershell_profile_candidates_prefers_live_profile_query below).
    monkeypatch.setattr(ih.shutil, "which", lambda name: None)
    candidates = ih._powershell_profile_candidates()
    # BOTH versions offered (live-verified 2026-08-04): Windows PowerShell 5.1 (built into
    # every Windows machine) and PowerShell 7+ (separate install) use DIFFERENT profile
    # paths - offering only one would silently miss whichever version a user actually has.
    assert len(candidates) == 2
    labels = {label for label, _ in candidates}
    assert labels == {"PowerShell 5.1", "PowerShell 7+"}
    paths = {p for _, p in candidates}
    assert any("WindowsPowerShell" in p.parts for p in paths)
    assert any(p.parent.name == "PowerShell" for p in paths)  # not WindowsPowerShell
    for p in paths:
        assert p.name == "Microsoft.PowerShell_profile.ps1"


def test_powershell_profile_candidates_prefers_live_profile_query(tmp_path, monkeypatch):
    """Live report, 2026-08-04: a corporate machine with folder redirection has
    "Documents" resolve to a NETWORK path, so the static Documents-based guess writes
    somewhere PowerShell never reads $PROFILE from. Querying each host's OWN $PROFILE
    must win over the static guess whenever the query succeeds."""
    import install_helper as ih

    monkeypatch.setattr(ih.sys, "platform", "win32")
    home = tmp_path / "winhome"
    (home / "Documents").mkdir(parents=True)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    monkeypatch.setattr(
        ih.shutil, "which", lambda name: f"C:\\{name}" if name.endswith(".exe") else None
    )
    redirected = r"\\corp-server\redirected\daniel\Documents\WindowsPowerShell\Microsoft.PowerShell_profile.ps1"

    def fake_run(argv, capture_output=True, timeout=None, **kw):
        # Both powershell.exe and pwsh.exe get queried - return the SAME redirected path
        # for simplicity; the point under test is that the query result wins, not that
        # the two hosts differ.
        return _proc(0, stdout=redirected + "\n")

    monkeypatch.setattr(ih.subprocess, "run", fake_run)
    candidates = ih._powershell_profile_candidates()
    assert len(candidates) == 2
    for _, path in candidates:
        assert str(path) == redirected
        # The static local-Documents guess must NOT be what got used.
        assert "winhome" not in str(path)


def test_powershell_profile_candidates_falls_back_when_query_fails(tmp_path, monkeypatch):
    """The binary is found, but the query itself errors (timeout, non-zero exit, empty
    output) - must fall back to the static guess, never drop the candidate outright."""
    import install_helper as ih

    monkeypatch.setattr(ih.sys, "platform", "win32")
    home = tmp_path / "winhome"
    (home / "Documents").mkdir(parents=True)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    monkeypatch.setattr(
        ih.shutil, "which", lambda name: f"C:\\{name}" if name.endswith(".exe") else None
    )
    monkeypatch.setattr(ih.subprocess, "run", lambda *a, **k: _proc(1, stdout=""))
    candidates = ih._powershell_profile_candidates()
    assert len(candidates) == 2
    for _, path in candidates:
        assert "winhome" in str(path)  # fell back to the static Documents-based guess


def test_setup_alias_writes_both_powershell_profiles(tmp_path, monkeypatch):
    """Both PS 5.1 and PS7+ profiles get offered and written - see
    test_powershell_profile_candidates_windows_only for why both matter."""
    import install_helper as ih

    monkeypatch.setattr(ih.sys, "platform", "win32")
    home = tmp_path / "winhome"
    (home / "Documents").mkdir(parents=True)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    monkeypatch.setattr(ih.shutil, "which", lambda name: None)  # see the sibling test above
    monkeypatch.setattr(ih, "_check_interpreters", lambda order: ([], "py"))
    rc = ih.run_setup_alias(ih.Style(False), ih.marks(), assume_yes=True)
    assert rc == 0
    for sub in ("WindowsPowerShell", "PowerShell"):
        profile = home / "Documents" / sub / "Microsoft.PowerShell_profile.ps1"
        content = profile.read_text(encoding="utf-8")
        assert "function virt-surv" in content
        assert "@args" in content


# --- folder-subcommand dispatch ('virt-surv configure', etc.) -------------------------------


def test_dispatch_folder_subcommand_not_a_match_returns_none():
    import install_helper as ih

    assert ih._dispatch_folder_subcommand([]) is None
    assert ih._dispatch_folder_subcommand(["install"]) is None
    assert ih._dispatch_folder_subcommand(["--configure"]) is None


def test_dispatch_folder_subcommand_rejects_unknown_flag(monkeypatch, capsys):
    """Fable UX review, 2026-08-05: 'configure --branch dev' silently treated
    '--branch' as the target directory ("not a directory: <cwd>/--branch")."""
    import install_helper as ih

    monkeypatch.setattr(ih, "run_configure", lambda *a, **k: 0)
    rc = ih._dispatch_folder_subcommand(["configure", "--branch", "dev"])
    out = capsys.readouterr().out
    assert rc == 1
    assert "unknown option '--branch'" in out


def test_dispatch_folder_subcommand_configure_routes_correctly(tmp_path, monkeypatch):
    import install_helper as ih

    called = []
    monkeypatch.setattr(
        ih,
        "run_configure",
        lambda target, style, mm, assume_yes=False, demo=False: called.append(target) or 0,
    )
    rc = ih._dispatch_folder_subcommand(["configure", str(tmp_path)])
    assert rc == 0
    assert called == [Path(tmp_path)]


def test_dispatch_folder_subcommand_configure_defaults_to_cwd(monkeypatch):
    import install_helper as ih

    called = []
    monkeypatch.setattr(
        ih,
        "run_configure",
        lambda target, style, mm, assume_yes=False, demo=False: called.append(target) or 0,
    )
    ih._dispatch_folder_subcommand(["configure"])
    assert called == [Path(".")]


def test_dispatch_folder_subcommand_parses_demo_and_yes_flags(monkeypatch, tmp_path):
    """Live-tested gap, 2026-08-04: this dispatcher bypasses parse_args() entirely, so a
    trailing --demo was previously silently dropped instead of honoured or erroring."""
    import install_helper as ih

    calls = []
    monkeypatch.setattr(
        ih,
        "run_configure",
        lambda target, style, mm, assume_yes=False, demo=False: (
            calls.append((target, assume_yes, demo)) or 0
        ),
    )
    ih._dispatch_folder_subcommand(["configure", str(tmp_path), "--demo", "--yes"])
    assert calls == [(Path(tmp_path), True, True)]
    # flag order shouldn't matter, and the path can come before or after the flags
    calls.clear()
    ih._dispatch_folder_subcommand(["configure", "--demo", str(tmp_path)])
    assert calls == [(Path(tmp_path), False, True)]


def test_dispatch_folder_subcommand_archive_and_list(monkeypatch, tmp_path):
    import install_helper as ih

    monkeypatch.setattr(ih, "run_archive_engagements", lambda target, style, mm, demo=False: 0)
    monkeypatch.setattr(ih, "run_list_engagements", lambda target, style, mm: 0)
    assert ih._dispatch_folder_subcommand(["archive", str(tmp_path)]) == 0
    assert ih._dispatch_folder_subcommand(["list-engagements", str(tmp_path)]) == 0


def test_dispatch_folder_subcommand_setup_alias(monkeypatch):
    import install_helper as ih

    monkeypatch.setattr(ih, "run_setup_alias", lambda style, mm, assume_yes=False, demo=False: 0)
    assert ih._dispatch_folder_subcommand(["setup-alias"]) == 0


def test_dispatch_folder_subcommand_engage_always_assume_yes(tmp_path, monkeypatch):
    """2026-08-07 user request: 'virt-surv engage' applies every default with zero
    prompts - assume_yes must be True even when --yes was NOT passed, unlike 'configure'
    which only assumes yes when told to."""
    import install_helper as ih

    calls = []
    monkeypatch.setattr(
        ih,
        "run_configure",
        lambda target, style, mm, assume_yes=False, demo=False: (
            calls.append((target, assume_yes, demo)) or 0
        ),
    )
    rc = ih._dispatch_folder_subcommand(["engage", str(tmp_path)])
    assert rc == 0
    assert calls == [(Path(tmp_path), True, False)]


def test_dispatch_folder_subcommand_engage_prints_ready_message_on_success(
    tmp_path, monkeypatch, capsys
):
    import install_helper as ih

    monkeypatch.setattr(
        ih, "run_configure", lambda target, style, mm, assume_yes=False, demo=False: 0
    )
    rc = ih._dispatch_folder_subcommand(["engage", str(tmp_path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "ready to launch" in out.lower()
    assert "Morgan" in out


def test_dispatch_folder_subcommand_engage_no_ready_message_on_failure(
    tmp_path, monkeypatch, capsys
):
    import install_helper as ih

    monkeypatch.setattr(
        ih, "run_configure", lambda target, style, mm, assume_yes=False, demo=False: 1
    )
    rc = ih._dispatch_folder_subcommand(["engage", str(tmp_path)])
    assert rc == 1
    assert "ready to launch" not in capsys.readouterr().out.lower()


def test_dispatch_folder_subcommand_engage_demo_never_prints_ready_message(
    tmp_path, monkeypatch, capsys
):
    import install_helper as ih

    monkeypatch.setattr(
        ih, "run_configure", lambda target, style, mm, assume_yes=False, demo=False: 0
    )
    rc = ih._dispatch_folder_subcommand(["engage", str(tmp_path), "--demo"])
    assert rc == 0
    assert "ready to launch" not in capsys.readouterr().out.lower()


def test_dispatch_folder_subcommand_onboard_is_identical_to_engage(tmp_path, monkeypatch, capsys):
    """2026-08-07 user request: 'onboard' does exactly the same thing as 'engage' - same
    code path, same behaviour, just a different name for a different mental model."""
    import install_helper as ih

    calls = []
    monkeypatch.setattr(
        ih,
        "run_configure",
        lambda target, style, mm, assume_yes=False, demo=False: (
            calls.append((target, assume_yes, demo)) or 0
        ),
    )
    rc = ih._dispatch_folder_subcommand(["onboard", str(tmp_path)])
    assert rc == 0
    assert calls == [(Path(tmp_path), True, False)]
    out = capsys.readouterr().out
    assert "ready to launch" in out.lower()
    assert "Morgan" in out


def test_project_root_warning_none_for_ordinary_project(tmp_path):
    from install_helper import _project_root_warning

    project = tmp_path / "my-project"
    project.mkdir()
    assert _project_root_warning(project) is None


def test_project_root_warning_flags_home_directory(monkeypatch, tmp_path):
    from install_helper import _project_root_warning

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    warning = _project_root_warning(tmp_path)
    assert warning is not None
    assert "HOME" in warning


def test_project_root_warning_flags_filesystem_root():
    from install_helper import _project_root_warning

    root = Path(Path(".").resolve().anchor)
    warning = _project_root_warning(root)
    assert warning is not None
    assert "filesystem root" in warning


def test_dispatch_engage_prints_warning_for_home_directory(monkeypatch, tmp_path, capsys):
    import install_helper as ih

    monkeypatch.setattr(
        ih, "run_configure", lambda target, style, mm, assume_yes=False, demo=False: 0
    )
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    rc = ih._dispatch_folder_subcommand(["engage", str(tmp_path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "HOME directory" in out
    assert "Ctrl-C" in out


def test_dispatch_engage_no_warning_for_ordinary_project(tmp_path, monkeypatch, capsys):
    import install_helper as ih

    project = tmp_path / "my-project"
    project.mkdir()
    monkeypatch.setattr(
        ih, "run_configure", lambda target, style, mm, assume_yes=False, demo=False: 0
    )
    rc = ih._dispatch_folder_subcommand(["engage", str(project)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Ctrl-C" not in out
    assert "Setting up" in out and str(project.resolve()) in out


def test_dispatch_engage_ready_message_names_the_resolved_folder(tmp_path, monkeypatch, capsys):
    """2026-08-07 user request: "tell them to launch claude from the same place"."""
    import install_helper as ih

    project = tmp_path / "my-project"
    project.mkdir()
    monkeypatch.setattr(
        ih, "run_configure", lambda target, style, mm, assume_yes=False, demo=False: 0
    )
    rc = ih._dispatch_folder_subcommand(["engage", str(project)])
    assert rc == 0
    out = capsys.readouterr().out
    assert f"run `claude` from {project.resolve()}" in out


def test_main_dispatches_folder_subcommand_before_argparse(monkeypatch):
    """Confirms main() checks the folder-subcommand form BEFORE falling through to the
    normal parse_args()-based flow, which would reject 'configure' as an invalid mode."""
    import install_helper as ih

    monkeypatch.setattr(ih, "run_configure", lambda *a, **k: 0)
    assert ih.main(["configure"]) == 0


# --- reorganised menu / submenus --------------------------------------------------------------


def test_top_level_menu_actions_are_the_expected_four():
    """2026-08-17 restructure: manage-engagements retired (folder subcommands carry it),
    alias moved under Advanced as the two-option manager."""
    from install_helper import MENU_ACTIONS

    assert MENU_ACTIONS == {
        "1": "full",
        "2": "configure",
        "3": "diagnostics",
        "4": "advanced",
        "q": "quit",
    }


def test_diagnostics_submenu_full_mapping():
    from install_helper import _DIAGNOSTICS_ACTIONS

    assert _DIAGNOSTICS_ACTIONS == {
        "1": "check",
        "2": "toolcheck",
        "3": "envcheck",
        "4": "selftest",
        "5": "hooklatency",
        "6": "adr014smoke",
        "7": "daemonstart",
        "b": "back",
    }


def test_advanced_submenu_full_mapping():
    from install_helper import _ADVANCED_ACTIONS

    assert _ADVANCED_ACTIONS == {
        "1": "setup",
        "2": "statusline",
        "3": "formats",
        "4": "model",
        "5": "demo",
        "6": "machinedefaults",
        "7": "dashboard",
        "8": "fixbashrc",
        "9": "cleanplugincache",
        "10": "aliasmanage",
        "b": "back",
    }


def test_choose_submenu_divider_row_not_selectable_and_not_counted_in_error_range(
    monkeypatch, capsys
):
    """2026-08-12 onboarding UX audit: Diagnostics mixed everyday checks with internal/
    prototype items with no visual grouping - fixed with a divider row (empty-string
    key). Must render as plain text (no numbered prefix), never match an answer, and
    the "1-N or b" error hint must count real choices only, not the divider itself."""
    import install_helper as ih

    # "" (the divider row's own key) is never a valid answer, matching every other
    # invalid input - but empty input is ALSO how "back" is spelled (a bare Enter), so
    # use a genuinely out-of-range answer ("9") to exercise the retry/error path
    # without also exiting the menu.
    answers = iter(["9", "1"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    options = (
        ("1", "Real choice one"),
        ("", "-- a divider --"),
        ("2", "Real choice two"),
        ("b", "Back"),
    )
    actions = {"1": "one", "2": "two", "b": "back"}
    result = ih._choose_submenu(ih.Style(False), "Test menu", options, actions)
    out = capsys.readouterr().out
    assert "1) Real choice one" in out
    assert "-- a divider --" in out and ")-- a divider --" not in out  # no numbered prefix
    assert "1-2 or b, please." in out  # 2 real choices, divider excluded from the count
    assert result == "one"


def test_choose_action_diagnostics_then_back_redraws_top_menu(monkeypatch):
    """'b' at the submenu must return to the top-level menu, not exit choose_action -
    verified by picking Diagnostics, backing out, then picking a real top-level action."""
    import install_helper as ih

    answers = iter(["3", "b", "1"])  # Diagnostics -> back -> Install/update (full)
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    assert ih.choose_action(ih.Style(False)) == "full"


def test_choose_action_resolves_through_diagnostics_submenu(monkeypatch):
    import install_helper as ih

    answers = iter(["3", "2"])  # Diagnostics -> Check analyser output cleanliness
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    assert ih.choose_action(ih.Style(False)) == "toolcheck"


def test_choose_action_resolves_through_advanced_submenu(monkeypatch):
    import install_helper as ih

    answers = iter(["4", "4"])  # Advanced -> Morgan's model only
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    assert ih.choose_action(ih.Style(False)) == "model"


def test_choose_action_configure_direct_and_aliasmanage_via_advanced(monkeypatch):
    import install_helper as ih

    monkeypatch.setattr("builtins.input", lambda prompt="": "2")
    assert ih.choose_action(ih.Style(False)) == "configure"

    answers = iter(["4", "10"])  # Advanced -> Manage the alias
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    assert ih.choose_action(ih.Style(False)) == "aliasmanage"


def test_run_alias_manage_register_path_delegates_to_setup_alias(monkeypatch, capsys):
    import install_helper as ih

    calls = []
    monkeypatch.setattr(ih, "run_setup_alias", lambda *a, **k: calls.append(a) or 0)
    monkeypatch.setattr("builtins.input", lambda prompt="": "")  # blank = register (default)
    assert ih.run_alias_manage(ih.Style(False), ih.marks()) == 0
    assert len(calls) == 1


def test_run_alias_manage_change_command_saves_and_offers_refresh(tmp_path, monkeypatch, capsys):
    import json as _json

    import install_helper as ih

    xdg = tmp_path / "xdg"
    (xdg / "virt-surv-it").mkdir(parents=True)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))
    refreshed = []
    monkeypatch.setattr(ih, "run_setup_alias", lambda *a, **k: refreshed.append(k) or 0)
    answers = iter(["2"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers, ""))
    monkeypatch.setattr(ih, "ask", lambda *a, **k: "cc")
    monkeypatch.setattr(ih, "confirm", lambda *a, **k: True)
    assert ih.run_alias_manage(ih.Style(False), ih.marks()) == 0
    saved = _json.loads((xdg / "virt-surv-it" / "installer.json").read_text())
    assert saved["claude_launch_command"] == "cc"
    assert refreshed == [{"assume_yes": True}]


# --- demo mode must cover every new command (live report, 2026-08-04) -----------------------
# The original run_configure/run_setup_alias/run_archive_engagements had NO demo support at
# all - `install_helper.py configure /dir --demo --yes` silently wrote real files to disk,
# and `--demo` on its own skipped the interactive menu entirely (so none of these newer
# options could even be reached in a preview). Both fixed; pinned here so they can't regress.


def test_run_configure_demo_writes_nothing(tmp_path, monkeypatch, capsys):
    import install_helper as ih

    _isolate_home(monkeypatch, tmp_path)
    monkeypatch.setattr(ih, "run_cmd", lambda *a, **k: _FakeProc(0))
    rc = ih.run_configure(tmp_path, ih.Style(False), ih.marks(), assume_yes=True, demo=True)
    out = capsys.readouterr().out
    assert rc == 0
    assert "DEMO" in out
    assert "would" in out
    # The actual guarantee: nothing on disk at all, not even the directories.
    assert not (tmp_path / ".claude").exists()


def test_run_setup_alias_demo_writes_nothing(tmp_path, monkeypatch):
    import install_helper as ih

    home = _isolate_home_for_alias(monkeypatch, tmp_path, bashrc="")
    _stub_interpreters(monkeypatch, ih)
    rc = ih.run_setup_alias(ih.Style(False), ih.marks(), assume_yes=True, demo=True)
    assert rc == 0
    assert (home / ".bashrc").read_text(encoding="utf-8") == ""  # untouched


# --- run_clean_plugin_cache (2026-08-14: live report - a stale 0.22.0 install left behind) -----


def _make_fake_plugin_install(base: Path) -> None:
    """A directory that looks like a genuine cached install of this plugin to BOTH
    discovery paths: the docs/team-operating-guide.md marker _plugin_cache_version_dirs
    scans for, and the .claude-plugin/plugin.json manifest _active_plugin_install_path
    reads to confirm a registry installPath is really this plugin."""
    (base / "docs").mkdir(parents=True, exist_ok=True)
    (base / "docs" / "team-operating-guide.md").write_text("# guide\n", encoding="utf-8")
    (base / ".claude-plugin").mkdir(parents=True, exist_ok=True)
    (base / ".claude-plugin" / "plugin.json").write_text(
        '{"name": "compliance-surveillance-team"}', encoding="utf-8"
    )


def test_plugin_cache_version_dirs_finds_installs_under_cache_and_marketplaces(tmp_path):
    import install_helper as ih

    old = (
        tmp_path
        / ".claude"
        / "plugins"
        / "cache"
        / "mkt"
        / "compliance-surveillance-team"
        / "0.22.0"
    )
    new = (
        tmp_path
        / ".claude"
        / "plugins"
        / "marketplaces"
        / "mkt"
        / "compliance-surveillance-team"
        / "0.33.62"
    )
    _make_fake_plugin_install(old)
    _make_fake_plugin_install(new)
    found = ih._plugin_cache_version_dirs(tmp_path)
    assert set(found) == {old, new}


def test_plugin_cache_version_dirs_ignores_unrelated_plugins(tmp_path):
    import install_helper as ih

    unrelated = tmp_path / ".claude" / "plugins" / "cache" / "mkt" / "some-other-plugin" / "1.0.0"
    (unrelated / "docs").mkdir(parents=True)
    (unrelated / "docs" / "team-operating-guide.md").write_text("# guide\n", encoding="utf-8")
    assert ih._plugin_cache_version_dirs(tmp_path) == []


def test_active_plugin_install_path_reads_the_registry(tmp_path):
    import install_helper as ih

    active = tmp_path / "plugins" / "compliance-surveillance-team" / "0.33.62"
    _make_fake_plugin_install(active)
    registry = tmp_path / ".claude" / "plugins" / "installed_plugins.json"
    registry.parent.mkdir(parents=True)
    registry.write_text(
        json.dumps({"marketplaces": [{"installPath": str(active)}]}), encoding="utf-8"
    )
    assert ih._active_plugin_install_path(tmp_path) == active


def test_active_plugin_install_path_none_when_registry_missing(tmp_path):
    import install_helper as ih

    assert ih._active_plugin_install_path(tmp_path) is None


def test_run_clean_plugin_cache_removes_stale_keeps_active(tmp_path, monkeypatch, capsys):
    import install_helper as ih

    monkeypatch.setattr(ih.Path, "home", staticmethod(lambda: tmp_path))
    old = (
        tmp_path
        / ".claude"
        / "plugins"
        / "cache"
        / "mkt"
        / "compliance-surveillance-team"
        / "0.22.0"
    )
    active = (
        tmp_path
        / ".claude"
        / "plugins"
        / "cache"
        / "mkt"
        / "compliance-surveillance-team"
        / "0.33.62"
    )
    _make_fake_plugin_install(old)
    _make_fake_plugin_install(active)
    registry = tmp_path / ".claude" / "plugins" / "installed_plugins.json"
    registry.write_text(json.dumps({"installPath": str(active)}), encoding="utf-8")

    rc = ih.run_clean_plugin_cache(ih.Style(False), ih.marks(), assume_yes=True)
    out = capsys.readouterr().out
    assert rc == 0
    assert not old.exists()  # stale install actually removed
    assert active.is_dir()  # active install untouched
    assert "ACTIVE - kept" in out


def test_run_clean_plugin_cache_demo_removes_nothing(tmp_path, monkeypatch):
    import install_helper as ih

    monkeypatch.setattr(ih.Path, "home", staticmethod(lambda: tmp_path))
    old = (
        tmp_path
        / ".claude"
        / "plugins"
        / "cache"
        / "mkt"
        / "compliance-surveillance-team"
        / "0.22.0"
    )
    active = (
        tmp_path
        / ".claude"
        / "plugins"
        / "cache"
        / "mkt"
        / "compliance-surveillance-team"
        / "0.33.62"
    )
    _make_fake_plugin_install(old)
    _make_fake_plugin_install(active)
    registry = tmp_path / ".claude" / "plugins" / "installed_plugins.json"
    registry.write_text(json.dumps({"installPath": str(active)}), encoding="utf-8")

    rc = ih.run_clean_plugin_cache(ih.Style(False), ih.marks(), assume_yes=True, demo=True)
    assert rc == 0
    assert old.is_dir()  # nothing removed in demo mode
    assert active.is_dir()


def test_run_clean_plugin_cache_falls_back_to_newest_when_registry_missing(tmp_path, monkeypatch):
    """No active install confirmed (registry missing) - keeps the newest-LOOKING version
    as a conservative guess rather than refusing outright or removing everything."""
    import install_helper as ih

    monkeypatch.setattr(ih.Path, "home", staticmethod(lambda: tmp_path))
    old = (
        tmp_path
        / ".claude"
        / "plugins"
        / "cache"
        / "mkt"
        / "compliance-surveillance-team"
        / "0.22.0"
    )
    newer = (
        tmp_path
        / ".claude"
        / "plugins"
        / "cache"
        / "mkt"
        / "compliance-surveillance-team"
        / "0.33.62"
    )
    _make_fake_plugin_install(old)
    _make_fake_plugin_install(newer)
    # No installed_plugins.json at all.

    rc = ih.run_clean_plugin_cache(ih.Style(False), ih.marks(), assume_yes=True)
    assert rc == 0
    assert not old.exists()
    assert newer.is_dir()


def test_run_clean_plugin_cache_declined_removes_nothing(tmp_path, monkeypatch):
    import install_helper as ih

    monkeypatch.setattr(ih.Path, "home", staticmethod(lambda: tmp_path))
    old = (
        tmp_path
        / ".claude"
        / "plugins"
        / "cache"
        / "mkt"
        / "compliance-surveillance-team"
        / "0.22.0"
    )
    active = (
        tmp_path
        / ".claude"
        / "plugins"
        / "cache"
        / "mkt"
        / "compliance-surveillance-team"
        / "0.33.62"
    )
    _make_fake_plugin_install(old)
    _make_fake_plugin_install(active)
    registry = tmp_path / ".claude" / "plugins" / "installed_plugins.json"
    registry.write_text(json.dumps({"installPath": str(active)}), encoding="utf-8")
    monkeypatch.setattr(ih, "confirm", lambda *a, **k: False)

    rc = ih.run_clean_plugin_cache(ih.Style(False), ih.marks(), assume_yes=False)
    assert rc == 0
    assert old.is_dir()  # declined - nothing removed


def test_run_clean_plugin_cache_nothing_found(tmp_path, monkeypatch, capsys):
    import install_helper as ih

    monkeypatch.setattr(ih.Path, "home", staticmethod(lambda: tmp_path))
    rc = ih.run_clean_plugin_cache(ih.Style(False), ih.marks(), assume_yes=True)
    assert rc == 0
    assert "nothing to clean" in capsys.readouterr().out


# --- run_fix_bashrc (2026-08-14: consent-gated counterpart to _check_shell_startup_time) -------


def test_run_fix_bashrc_no_file(tmp_path, monkeypatch):
    import install_helper as ih

    _isolate_home_for_alias(monkeypatch, tmp_path)  # bashrc=None: no file at all
    rc = ih.run_fix_bashrc(ih.Style(False), ih.marks(), assume_yes=True)
    assert rc == 1


def test_run_fix_bashrc_writes_guard_at_the_top(tmp_path, monkeypatch):
    import install_helper as ih

    home = _isolate_home_for_alias(monkeypatch, tmp_path, bashrc="export FOO=bar\n")
    rc = ih.run_fix_bashrc(ih.Style(False), ih.marks(), assume_yes=True)
    assert rc == 0
    content = (home / ".bashrc").read_text(encoding="utf-8")
    assert content.index("$- == *i*") < content.index("export FOO=bar")  # guard comes first
    assert "export FOO=bar" in content  # existing content preserved, not clobbered


def test_run_fix_bashrc_backs_up_existing_file(tmp_path, monkeypatch):
    import install_helper as ih

    home = _isolate_home_for_alias(monkeypatch, tmp_path, bashrc="export FOO=bar\n")
    rc = ih.run_fix_bashrc(ih.Style(False), ih.marks(), assume_yes=True)
    assert rc == 0
    today = ih.datetime.now().strftime("%Y-%m-%d")
    backup = home / f".bashrc.bak-{today}"
    assert backup.is_file()
    assert backup.read_text(encoding="utf-8") == "export FOO=bar\n"


def test_run_fix_bashrc_idempotent_skip(tmp_path, monkeypatch, capsys):
    import install_helper as ih

    home = _isolate_home_for_alias(
        monkeypatch, tmp_path, bashrc=ih._BASHRC_GUARD_MARKER + "\nexport FOO=bar\n"
    )
    rc = ih.run_fix_bashrc(ih.Style(False), ih.marks(), assume_yes=True)
    assert rc == 0
    assert "already present, skipped" in capsys.readouterr().out
    assert not (home / f".bashrc.bak-{ih.datetime.now().strftime('%Y-%m-%d')}").exists()


def test_run_fix_bashrc_declined_is_not_an_error(tmp_path, monkeypatch):
    import install_helper as ih

    home = _isolate_home_for_alias(monkeypatch, tmp_path, bashrc="export FOO=bar\n")
    monkeypatch.setattr(ih, "confirm", lambda *a, **k: False)
    rc = ih.run_fix_bashrc(ih.Style(False), ih.marks(), assume_yes=False)
    assert rc == 0
    assert (home / ".bashrc").read_text(encoding="utf-8") == "export FOO=bar\n"  # untouched


def test_run_fix_bashrc_demo_writes_nothing(tmp_path, monkeypatch):
    import install_helper as ih

    home = _isolate_home_for_alias(monkeypatch, tmp_path, bashrc="export FOO=bar\n")
    rc = ih.run_fix_bashrc(ih.Style(False), ih.marks(), assume_yes=True, demo=True)
    assert rc == 0
    assert (home / ".bashrc").read_text(encoding="utf-8") == "export FOO=bar\n"  # untouched


def test_run_fix_bashrc_write_error_is_reported(tmp_path, monkeypatch):
    import install_helper as ih

    _isolate_home_for_alias(monkeypatch, tmp_path, bashrc="export FOO=bar\n")

    def boom(path, text):
        raise OSError("disk full")

    monkeypatch.setattr(ih, "_atomic_write_text", boom)
    rc = ih.run_fix_bashrc(ih.Style(False), ih.marks(), assume_yes=True)
    assert rc == 1


def test_run_archive_engagements_demo_skips_real_call(tmp_path, monkeypatch):
    import install_helper as ih

    def boom(*a, **k):
        raise AssertionError("demo mode must never actually invoke engagement_state.py")

    monkeypatch.setattr(ih.subprocess, "run", boom)
    rc = ih.run_archive_engagements(tmp_path, ih.Style(False), ih.marks(), demo=True)
    assert rc == 0


def test_run_manage_engagements_demo_threads_through_to_archive(tmp_path, monkeypatch):
    import install_helper as ih

    monkeypatch.setattr(ih.subprocess, "run", lambda *a, **k: _proc(0, stdout="ok"))
    monkeypatch.setattr("builtins.input", lambda prompt="": "")  # accept default (declines)
    called = []
    monkeypatch.setattr(
        ih,
        "run_archive_engagements",
        lambda target, style, mm, demo=False: called.append(demo) or 0,
    )
    monkeypatch.setattr("builtins.input", lambda prompt="": "y")
    monkeypatch.setattr(sys, "stdin", _TtyStdin())
    ih.run_manage_engagements(tmp_path, ih.Style(False), ih.marks(), assume_yes=False, demo=True)
    assert called == [True]


def test_demo_flag_still_shows_interactive_menu(monkeypatch, tmp_path, capsys):
    """The core UX fix: --demo used to skip choose_action() entirely and jump straight to
    a fixed full-flow preview - none of the menu options (including the newer ones) could
    be reached at all. Now the menu shows regardless, and demo stays true throughout."""
    import install_helper as ih

    _menu_session(monkeypatch, tmp_path, ["2", str(tmp_path)])  # Configure -> this dir
    monkeypatch.setattr(ih, "_relocate_if_running_inside_target_repo", lambda *a, **k: None)
    rc = ih.main(["--demo"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "DEMO" in out
    assert not (tmp_path / ".claude").exists()  # nothing written


def test_dispatch_folder_subcommand_configure_demo_flag_writes_nothing(tmp_path, monkeypatch):
    """End-to-end through the REAL positional-subcommand path, not a mocked run_configure -
    the exact live-reported scenario (2026-08-04)."""
    import install_helper as ih

    monkeypatch.setattr(ih, "run_cmd", lambda *a, **k: _FakeProc(0))
    rc = ih._dispatch_folder_subcommand(["configure", str(tmp_path), "--demo", "--yes"])
    assert rc == 0
    assert not (tmp_path / ".claude").exists()


# --- menu loops back after every action instead of exiting (user request, 2026-08-04) --------


def test_menu_loops_back_and_runs_a_second_action_before_quit(monkeypatch, tmp_path, capsys):
    """The core UX fix: run TWO different actions in one session, not just the first."""
    import install_helper as ih

    calls = []
    monkeypatch.setattr(
        ih,
        "run_setup_alias",
        lambda style, mm, assume_yes=False, demo=False, repo_hint=None: calls.append("alias") or 0,
    )
    monkeypatch.setattr(
        ih,
        "run_configure",
        lambda target, style, mm, assume_yes=False, demo=False: calls.append("configure") or 0,
    )
    monkeypatch.setattr(
        ih,
        "run_alias_manage",
        lambda style, mm, assume_yes=False, demo=False, repo_hint=None: calls.append("alias") or 0,
    )
    # 4,10 = Advanced -> Manage the alias, loop back, 2 = Configure, answer the
    # directory prompt, loop back again, then exhausted answers feed "q".
    _menu_session(monkeypatch, tmp_path, ["4", "10", "2", str(tmp_path)])
    rc = ih.main([])
    assert rc == 0
    assert calls == ["alias", "configure"]  # BOTH ran, in order, in one session


def test_menu_shows_again_after_an_action_completes(monkeypatch, tmp_path, capsys):
    """Direct evidence the menu re-renders: 'What can I do for you?' appears more than
    once in one session's output."""
    import install_helper as ih

    monkeypatch.setattr(
        ih,
        "run_alias_manage",
        lambda style, mm, assume_yes=False, demo=False, repo_hint=None: 0,
    )
    _menu_session(monkeypatch, tmp_path, ["4", "10"])  # Advanced -> alias, exhausted -> "q"
    ih.main([])
    out = capsys.readouterr().out
    assert out.count("What can I do for you?") == 2  # once before "4", once before "q"


def test_invalid_menu_choice_reprompts_without_redrawing_menu(monkeypatch, tmp_path, capsys):
    """2026-08-04 user request: "don't reprint entire menu, just the item that the user
    is on" - a fat-fingered entry must get a short error + re-ask, not the whole
    six-line option list again."""
    import install_helper as ih

    _menu_session(monkeypatch, tmp_path, ["9", "x", "q"])
    ih.main([])
    out = capsys.readouterr().out
    assert out.count("What can I do for you?") == 1  # drawn once, not once per bad keystroke
    assert out.count("1-4 or q, please.") == 2  # one error per invalid attempt


# --- --demo must cover the WHOLE menu session, every action, not just one path ---------------


def test_demo_flag_protects_every_action_in_one_session(monkeypatch, tmp_path, capsys):
    """User request, 2026-08-04: "I should be able to run the entire menu system in demo
    mode" - --demo must stay true for EVERY action picked in the session, not just the
    first one or a hardcoded subset. Runs two DIFFERENT kinds of actions (the free-
    function 'configure' path, and an Installer-subset path) in one --demo session and
    checks demo threaded through both, including the run_cmd swap around the Installer
    path. Fakes Installer itself rather than answering its interior confirm() prompts -
    that wiring is already covered by the dedicated Installer/format_preferences_step
    tests; this test is only about the menu loop's own demo plumbing."""
    import install_helper as ih

    def sentinel_runner(*a, **k):
        return _FakeProc(0)

    monkeypatch.setattr(ih, "make_demo_runner", lambda style: sentinel_runner)
    installer_calls = []

    class _FakeInstaller:
        def __init__(self, args, style, mm, subset="full"):
            installer_calls.append((subset, args.demo, ih.run_cmd is sentinel_runner))

        def run(self):
            return 0

    monkeypatch.setattr(ih, "Installer", _FakeInstaller)
    configure_calls = []
    monkeypatch.setattr(
        ih,
        "run_configure",
        lambda target, style, mm, assume_yes=False, demo=False: configure_calls.append(demo) or 0,
    )
    # "2" = Configure (free-function path), directory prompt, loop back,
    # "4","3" = Advanced -> Project preferences (Installer subset "formats"), loop back, "q".
    _menu_session(monkeypatch, tmp_path, ["2", str(tmp_path), "4", "3", "q"])
    rc = ih.main(["--demo"])
    assert rc == 0
    assert configure_calls == [True]  # demo threaded to the free-function path
    # demo threaded to the Installer path, AND run_cmd was swapped to the demo runner
    # for the duration of that construction+run.
    assert installer_calls == [("formats", True, True)]


def test_demo_menu_selection_is_one_shot_not_sticky(monkeypatch, tmp_path):
    """Picking "Demo" from the Advanced submenu previews the full flow ONCE - it must
    NOT leave args.demo permanently true for whatever the user picks next in the same
    session (that would be a confusing silent side effect)."""
    import install_helper as ih

    def sentinel_runner(*a, **k):
        return _FakeProc(0)

    monkeypatch.setattr(ih, "make_demo_runner", lambda style: sentinel_runner)

    class _FakeInstaller:
        def __init__(self, args, style, mm, subset="full"):
            pass

        def run(self):
            return 0

    monkeypatch.setattr(ih, "Installer", _FakeInstaller)
    called_demo_values = []
    monkeypatch.setattr(
        ih,
        "run_configure",
        lambda target, style, mm, assume_yes=False, demo=False: (
            called_demo_values.append(demo) or 0
        ),
    )
    # 4,5 = Advanced -> Demo (one-shot full-flow preview via the FakeInstaller), loop
    # back, 2 = Configure, directory prompt, loop back, then exhausted -> "q".
    _menu_session(monkeypatch, tmp_path, ["4", "5", "2", str(tmp_path)])
    ih.main([])
    # run_configure must have been called with demo=False - the earlier "Demo" menu pick
    # must not have left args.demo stuck true.
    assert called_demo_values == [False]
    assert ih.run_cmd is not sentinel_runner  # restored after the one-shot preview


# --- review-tool on/off/auto config (2026-08-04) ----------------------------------------------


def test_review_tools_matches_tool_output_checks():
    """_REVIEW_TOOLS and _TOOL_OUTPUT_CHECKS must name exactly the same seven tools -
    check-review-tools.sh's own REVIEW_TOOLS array is checked separately (bash, not
    importable here) but documents the same invariant."""
    import install_helper as ih

    checked_names = {name for name, *_ in ih._TOOL_OUTPUT_CHECKS}
    assert set(ih._REVIEW_TOOLS) == checked_names


def test_parse_review_tool_overrides_basic():
    import install_helper as ih

    overrides, rejected = ih._parse_review_tool_overrides("mypy=off,black=on")
    assert overrides == {"mypy": "off", "black": "on"}
    assert rejected == []


def test_parse_review_tool_overrides_ignores_unknown_tool_and_state():
    """Fable UX review, 2026-08-05: unknown/malformed chunks must be reported back
    (`rejected`), not just quietly excluded from `overrides` - a typo or an
    intentionally-unsupported name like 'semgrep' used to vanish with zero feedback."""
    import install_helper as ih

    overrides, rejected = ih._parse_review_tool_overrides("notarealtool=off, mypy=maybe, black=on")
    assert overrides == {"black": "on"}
    assert rejected == ["notarealtool=off", "mypy=maybe"]


def test_parse_review_tool_overrides_blank_is_empty():
    import install_helper as ih

    assert ih._parse_review_tool_overrides("") == ({}, [])
    assert ih._parse_review_tool_overrides("   ") == ({}, [])


def test_write_team_preferences_review_tools_stores_only_non_auto(tmp_path):
    from install_helper import write_team_preferences

    write_team_preferences(tmp_path, review_tools={"mypy": "off", "ruff": "auto", "black": "on"})
    prefs = json.loads((tmp_path / ".claude" / "team-preferences.json").read_text())
    assert prefs["review_tools"] == {"black": "on", "mypy": "off"}  # "auto" never stored


def test_write_team_preferences_review_tools_empty_removes_key(tmp_path):
    from install_helper import write_team_preferences

    write_team_preferences(tmp_path, review_tools={"mypy": "off"})
    write_team_preferences(tmp_path, review_tools={})
    prefs = json.loads((tmp_path / ".claude" / "team-preferences.json").read_text())
    assert "review_tools" not in prefs


def test_write_team_preferences_review_tools_merge_only(tmp_path):
    """review_tools passed as None (the default) leaves an existing override untouched -
    same merge-only contract as extra_formats/regulatory_citations."""
    from install_helper import write_team_preferences

    write_team_preferences(tmp_path, review_tools={"mypy": "off"})
    write_team_preferences(tmp_path, regulatory_citations=False)
    prefs = json.loads((tmp_path / ".claude" / "team-preferences.json").read_text())
    assert prefs["review_tools"] == {"mypy": "off"}
    assert prefs["regulatory_citations"] is False


def test_ask_review_tool_overrides_merges_onto_current(monkeypatch):
    import install_helper as ih

    monkeypatch.setattr(sys, "stdin", _TtyStdin())
    monkeypatch.setattr("builtins.input", lambda prompt="": "mypy=off,ruff=auto")
    result = ih._ask_review_tool_overrides(
        ih.Style(False), False, {"ruff": "off", "gitleaks": "on"}
    )
    # mypy=off added, ruff=auto CLEARS the existing "off" override, gitleaks untouched.
    assert result == {"gitleaks": "on", "mypy": "off"}


def test_ask_review_tool_overrides_warns_on_rejected_chunk(monkeypatch, capsys):
    """Fable UX review, 2026-08-05: 'mypy=off, semgrep=on' silently applied only
    mypy=off with no mention of semgrep - readable as "I turned semgrep on"."""
    import install_helper as ih

    monkeypatch.setattr(sys, "stdin", _TtyStdin())
    monkeypatch.setattr("builtins.input", lambda prompt="": "mypy=off,semgrep=on")
    result = ih._ask_review_tool_overrides(ih.Style(False), False, {})
    out = capsys.readouterr().out
    assert result == {"mypy": "off"}
    assert "semgrep=on" in out
    assert "ignored" in out.lower()


def test_format_review_tools_matches_input_syntax():
    """Fable UX review, 2026-08-05: summary lines showed Python's dict repr
    (review-tools={'mypy': 'off'}) instead of the same syntax the prompt accepts."""
    from install_helper import _format_review_tools

    assert _format_review_tools({}) == "(all auto)"
    assert _format_review_tools({"mypy": "off"}) == "mypy=off"
    assert _format_review_tools({"mypy": "off", "black": "on"}) == "mypy=off,black=on"


def test_ask_review_tool_overrides_blank_leaves_current_unchanged(monkeypatch):
    import install_helper as ih

    monkeypatch.setattr(sys, "stdin", _TtyStdin())
    monkeypatch.setattr("builtins.input", lambda prompt="": "")
    result = ih._ask_review_tool_overrides(ih.Style(False), False, {"black": "on"})
    assert result == {"black": "on"}


def test_validate_forced_on_tools_downgrades_noisy_and_error(monkeypatch):
    """The core safety mechanism: a tool whose live probe comes back NOISY or ERROR
    (including a timeout - the exact semgrep/pip-audit shape) is downgraded back to
    "auto" instead of silently honoured as "on"."""
    import install_helper as ih

    def fake_probe(tmpdir, runner=None, only=None):
        yield ("ruff", "OK", "clean")
        yield ("mypy", "NOISY", "leaked ANSI")
        yield ("bandit", "ERROR", "timed out (20s) - likely blocked network access")

    monkeypatch.setattr(ih, "probe_analyser_output", fake_probe)
    result = ih._validate_forced_on_tools(
        ih.Style(False), ih.marks(), {"ruff": "on", "mypy": "on", "bandit": "on"}
    )
    assert result == {"ruff": "on"}  # mypy/bandit downgraded (removed -> falls back to auto)


def test_validate_forced_on_tools_leaves_skip_as_on(monkeypatch):
    """SKIP (not installed yet) is a real choice the human just made - no different from
    any other tool being missing under "auto" - so it stays "on", not silently reset."""
    import install_helper as ih

    def fake_probe(tmpdir, runner=None, only=None):
        yield ("sqlfluff", "SKIP", "not installed")

    monkeypatch.setattr(ih, "probe_analyser_output", fake_probe)
    result = ih._validate_forced_on_tools(ih.Style(False), ih.marks(), {"sqlfluff": "on"})
    assert result == {"sqlfluff": "on"}


def test_validate_forced_on_tools_ignores_tools_not_forced_on():
    import install_helper as ih

    result = ih._validate_forced_on_tools(
        ih.Style(False), ih.marks(), {"ruff": "off", "mypy": "auto"}
    )
    assert result == {"ruff": "off", "mypy": "auto"}


def test_run_configure_writes_review_tool_overrides(tmp_path, monkeypatch):
    import install_helper as ih

    _isolate_home(monkeypatch, tmp_path)
    monkeypatch.setattr(ih, "run_cmd", lambda *a, **k: _FakeProc(0))
    monkeypatch.setattr(sys, "stdin", _TtyStdin())
    # "n" to "use recommended settings?" (blank there would default to Yes and skip
    # every prompt below via assume_yes, defeating this test), "" enable-permissions
    # default(Y), "" env-tuning default(Y), "" beta-fields-workaround default(Y), ""
    # docx, "" citations, "" split, "" workflow-dispatch, "" standards-critique, ""
    # map-skeleton, "" statusline-map, "" guard_daemon (added 2026-08-12), "mypy=off"
    # review-tools override, "" model.
    answers = iter(["n", "", "", "", "", "", "", "", "", "", "", "", "mypy=off", ""])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    rc = ih.run_configure(tmp_path, ih.Style(False), ih.marks(), assume_yes=False)
    assert rc == 0
    prefs = json.loads((tmp_path / ".claude" / "team-preferences.json").read_text())
    assert prefs["review_tools"] == {"mypy": "off"}


def test_run_configure_forced_on_tool_gets_live_validated(tmp_path, monkeypatch):
    import install_helper as ih

    _isolate_home(monkeypatch, tmp_path)
    monkeypatch.setattr(ih, "run_cmd", lambda *a, **k: _FakeProc(0))
    monkeypatch.setattr(sys, "stdin", _TtyStdin())

    def fake_probe(tmpdir, runner=None, only=None):
        yield ("mypy", "ERROR", "timed out (20s) - likely blocked network access")

    monkeypatch.setattr(ih, "probe_analyser_output", fake_probe)
    # "n" to "use recommended settings?" first (blank there would default to Yes and
    # skip every prompt below via assume_yes, defeating this test). Then "" enable-
    # permissions, "" env-tuning, "" beta-fields-workaround, "" docx, "" citations, ""
    # split, "" workflow-dispatch, "" standards-critique, "" map-skeleton, ""
    # statusline-map, "" guard_daemon (added 2026-08-12), "mypy=on" review-tools
    # override, "" model.
    answers = iter(["n", "", "", "", "", "", "", "", "", "", "", "", "mypy=on", ""])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    rc = ih.run_configure(tmp_path, ih.Style(False), ih.marks(), assume_yes=False)
    assert rc == 0
    prefs = json.loads((tmp_path / ".claude" / "team-preferences.json").read_text())
    # mypy=on was downgraded by the failed live probe - never written as "on".
    assert prefs.get("review_tools", {}).get("mypy") != "on"


def test_format_preferences_step_review_tools_save_as_default(tmp_path, monkeypatch):
    """save_as_default now also persists review_tools to the installer-wide config, same
    mechanism as default_docx/default_regulatory_citations."""
    import install_helper as ih

    project = tmp_path / "proj"
    project.mkdir()
    monkeypatch.setattr(ih, "ask", lambda *a, **k: str(project))
    monkeypatch.setattr(ih, "confirm", _confirm_by_prompt({"docx": False, "citations": True}))
    monkeypatch.setattr(ih, "_ask_review_tool_overrides", lambda *a, **k: {"gitleaks": "off"})
    cfg_home = tmp_path / "xdg"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(cfg_home))

    def _fake_confirm_save_default(prompt, default, assume_yes, style=None):
        if "this machine's default" in prompt.lower():
            return True
        return _confirm_by_prompt({"docx": False, "citations": True})(
            prompt, default, assume_yes, style
        )

    monkeypatch.setattr(ih, "confirm", _fake_confirm_save_default)
    inst = ih.Installer(_args(yes=False), ih.Style(False), ih.marks(), subset="formats")
    inst.format_preferences_step()
    saved = json.loads((cfg_home / "virt-surv-it" / "installer.json").read_text())
    assert saved["default_review_tools"] == {"gitleaks": "off"}


# --- --selftest: mechanical smoke test of a "review this code" engagement ---------------------


def test_selftest_findings_pack_is_schema_valid(tmp_path):
    """The synthetic pack must actually satisfy docs/review/findings-schema.json - proves
    render_findings.py's real validate-then-render path, not a shortcut."""
    from scripts.findings_pack_io import write_pack
    from scripts.validate_findings import load_and_validate
    import install_helper as ih

    pack = ih._selftest_findings_pack("selftest-demo")
    pack_path = tmp_path / "pack.jsonl"
    write_pack(pack_path, pack)
    assert load_and_validate(pack_path) == []


def test_diagnostics_menu_includes_selftest():
    from install_helper import _DIAGNOSTICS_ACTIONS

    assert _DIAGNOSTICS_ACTIONS["4"] == "selftest"


def test_build_plan_selftest_subset():
    import install_helper as ih

    inst = ih.Installer(_args(yes=True), ih.Style(False), ih.marks(), subset="selftest")
    plan = inst.build_plan()
    assert len(plan) == 1
    assert plan[0][0] == "Self-test"
    assert plan[0][1] == inst.selftest_step


def test_selftest_cli_flag_dispatches(monkeypatch):
    import install_helper as ih

    called = []
    monkeypatch.setattr(
        ih, "run_selftest", lambda style, mm, repo_hint=None: called.append(repo_hint) or 0
    )
    rc = ih._main(["--selftest", "--repo", "/some/repo"])
    assert rc == 0
    assert called == ["/some/repo"]


def test_selftest_step_passes_repo_hint(monkeypatch):
    import install_helper as ih

    called = []
    monkeypatch.setattr(
        ih, "run_selftest", lambda style, mm, repo_hint=None: called.append(repo_hint) or 0
    )
    inst = ih.Installer(_args(yes=True, repo="/hinted/repo"), ih.Style(False), ih.marks())
    inst.selftest_step()
    assert called == ["/hinted/repo"]


def test_selftest_probe_bandit_crash_distinct_from_missed(monkeypatch, tmp_path):
    """Fable UX review, 2026-08-05: bandit crashing (a nonzero exit that's neither of
    its own two normal outcomes, 0=clean/1=issues-found) used to be reported
    identically to bandit running fine and simply missing the planted issue."""
    import install_helper as ih

    monkeypatch.setattr(
        ih.shutil, "which", lambda name: "/usr/bin/bandit" if name == "bandit" else None
    )
    monkeypatch.setattr(
        ih.subprocess, "run", lambda *a, **k: _proc(2, stderr="ModuleNotFoundError: no ast")
    )
    rows = [
        r for r in ih._selftest_engagement_probe(tmp_path, "python3") if r[0].startswith("bandit")
    ]
    assert rows[0][1] == "ERROR"
    assert "crashed" in rows[0][2] and "exit 2" in rows[0][2]


def test_selftest_probe_bandit_ran_but_missed_the_issue(monkeypatch, tmp_path):
    """Exit 0 (bandit's own "clean" outcome) with the planted issue absent means bandit
    genuinely ran and missed it - a real config problem, not a crash."""
    import install_helper as ih

    monkeypatch.setattr(
        ih.shutil, "which", lambda name: "/usr/bin/bandit" if name == "bandit" else None
    )
    monkeypatch.setattr(
        ih.subprocess, "run", lambda *a, **k: _proc(0, stdout="No issues identified.")
    )
    rows = [
        r for r in ih._selftest_engagement_probe(tmp_path, "python3") if r[0].startswith("bandit")
    ]
    assert rows[0][1] == "ERROR"
    assert "may be off" in rows[0][2]
    assert "crashed" not in rows[0][2]


def test_run_selftest_all_ok_returns_zero_and_writes_no_bundle(monkeypatch, tmp_path, capsys):
    import install_helper as ih

    monkeypatch.chdir(tmp_path)
    _stub_interpreters(monkeypatch, ih)
    monkeypatch.setattr(
        ih, "_check_guard_hooks", lambda interp, root, tmp: [("guard", "OK", "clean")]
    )
    monkeypatch.setattr(
        ih, "_check_repo_py_syntax", lambda interp, root: [("syntax", "OK", "clean")]
    )
    monkeypatch.setattr(ih, "_check_runtime_dependencies", lambda: [("git", "OK", "found")])
    monkeypatch.setattr(ih.shutil, "which", lambda name: None)  # bandit -> SKIP

    def fake_run(argv, cwd=None, capture_output=True, timeout=None, **kw):
        if "set-status" in argv and "closed" in argv:
            return _proc(1, stdout="", stderr="CLOSE-REFUSED: simulated")
        return _proc(0, stdout="", stderr="")

    monkeypatch.setattr(ih.subprocess, "run", fake_run)
    rc = ih.run_selftest(ih.Style(False), ih.marks())
    out = capsys.readouterr().out
    assert rc == 0
    assert "Self-test passed" in out
    assert not list(tmp_path.glob("virt-surv-selftest-*.txt"))


def test_run_selftest_failure_writes_debug_bundle(monkeypatch, tmp_path, capsys):
    import install_helper as ih

    monkeypatch.chdir(tmp_path)
    _stub_interpreters(monkeypatch, ih)
    monkeypatch.setattr(
        ih,
        "_check_guard_hooks",
        lambda interp, root, tmp: [("Bash (guard test)", "ERROR", "simulated failure")],
    )
    monkeypatch.setattr(
        ih, "_check_repo_py_syntax", lambda interp, root: [("syntax", "OK", "clean")]
    )
    monkeypatch.setattr(ih, "_check_runtime_dependencies", lambda: [("git", "OK", "found")])
    monkeypatch.setattr(ih.shutil, "which", lambda name: None)

    def fake_run(argv, cwd=None, capture_output=True, timeout=None, **kw):
        if "set-status" in argv and "closed" in argv:
            return _proc(1, stdout="", stderr="CLOSE-REFUSED: simulated")
        return _proc(0, stdout="", stderr="")

    monkeypatch.setattr(ih.subprocess, "run", fake_run)
    rc = ih.run_selftest(ih.Style(False), ih.marks())
    out = capsys.readouterr().out
    assert rc == 1
    assert "issue(s) found" in out
    bundles = list(tmp_path.glob("virt-surv-selftest-*.txt"))
    assert len(bundles) == 1
    content = bundles[0].read_text(encoding="utf-8")
    assert "simulated failure" in content
    assert "Bash (guard test)" in content
    assert "Python:" in content and "Platform:" in content


def test_run_selftest_close_gate_error_when_not_refused(monkeypatch, tmp_path, capsys):
    """If set-status closed unexpectedly SUCCEEDS (or fails for a different reason), that
    is itself a failure - the whole point is proving the gate has real teeth."""
    import install_helper as ih

    monkeypatch.chdir(tmp_path)
    _stub_interpreters(monkeypatch, ih)
    monkeypatch.setattr(ih, "_check_guard_hooks", lambda interp, root, tmp: [])
    monkeypatch.setattr(ih, "_check_repo_py_syntax", lambda interp, root: [])
    monkeypatch.setattr(ih, "_check_runtime_dependencies", lambda: [])
    monkeypatch.setattr(ih.shutil, "which", lambda name: None)
    monkeypatch.setattr(ih.subprocess, "run", lambda *a, **k: _proc(0, stdout="", stderr=""))
    rc = ih.run_selftest(ih.Style(False), ih.marks())
    out = capsys.readouterr().out
    assert rc == 1
    assert "expected a CLOSE-REFUSED block" in out


def test_selftest_end_to_end_real_scripts(tmp_path, monkeypatch):
    """No mocking of engagement_state.py/render_findings.py/bandit - the real thing,
    against this actual repo clone. The strongest proof the mechanism works, matching
    how it will actually run for a user hitting --selftest for real."""
    import shutil as _shutil

    import install_helper as ih

    if _shutil.which("bandit") is None:
        pytest.skip("bandit not installed in this environment")
    monkeypatch.chdir(tmp_path)
    rc = ih.run_selftest(ih.Style(False), ih.marks())
    assert rc == 0
    assert not list(tmp_path.glob("virt-surv-selftest-*.txt"))


# --- comprehensive check folds in the synthetic engagement; a clean summary (2026-08-04) ------


def test_print_diagnostic_summary_groups_by_status(capsys):
    import install_helper as ih

    rows = [
        ("ruff", "OK", "clean"),
        ("mypy", "OK", "clean"),
        ("pwsh", "WARN", "not on PATH"),
        ("sqlfluff", "SKIP", "not installed"),
        ("bandit", "ERROR", "timed out"),
    ]
    ih._print_diagnostic_summary(ih.Style(False), ih.marks(), rows)
    out = capsys.readouterr().out
    assert "Passed (2)" in out
    assert "Warnings (1)" in out
    assert "Skipped (1)" in out
    assert "Failed (1)" in out
    # Order within a group is preserved, not resorted alphabetically.
    passed_block = out.split("Passed (2)")[1].split("Warnings")[0]
    assert passed_block.index("ruff") < passed_block.index("mypy")


def test_print_diagnostic_summary_omits_empty_groups(capsys):
    import install_helper as ih

    ih._print_diagnostic_summary(ih.Style(False), ih.marks(), [("ruff", "OK", "clean")])
    out = capsys.readouterr().out
    assert "Passed (1)" in out
    assert "Warnings" not in out
    assert "Skipped" not in out
    assert "Failed" not in out


def test_run_env_check_folds_in_synthetic_engagement(monkeypatch, tmp_path, capsys):
    """2026-08-04 user request: "the comprehensive test should execute the synthetic
    test so it's really is comprehensive" - --check-env's own section must call the
    SAME _selftest_engagement_probe --selftest uses, not a separate/lesser copy."""
    import install_helper as ih

    monkeypatch.chdir(tmp_path)
    _stub_interpreters(monkeypatch, ih)
    monkeypatch.setattr(ih, "find_bash", lambda: None)
    monkeypatch.setattr(ih, "_check_runtime_dependencies", lambda: [])
    monkeypatch.setattr(ih, "_check_encoding_roundtrip", lambda interp: ("SKIP", "no interpreter"))
    monkeypatch.setattr(ih, "_check_guard_hooks", lambda interp, root, tmp: [])
    monkeypatch.setattr(ih, "probe_analyser_output", lambda tmp, runner=None: iter([]))
    probed = []
    monkeypatch.setattr(
        ih,
        "_selftest_engagement_probe",
        lambda root, interp: iter([probed.append(1) or ("lifecycle probe", "OK", "clean", None)]),
    )
    rc = ih.run_env_check(ih.Style(False), ih.marks())
    out = capsys.readouterr().out
    assert rc == 0
    assert probed == [1]
    assert "Synthetic engagement" in out
    assert "lifecycle probe" in out
    assert "Summary" in out  # the new scoreboard is present too


# --- hook-latency diagnostic (feeds the ADR-014 daemon decision) ---


def test_fmt_latency_stats_empty_list():
    import install_helper as ih

    assert ih._fmt_latency_stats([]) == "no successful samples"


def test_fmt_latency_stats_all_failed():
    import install_helper as ih

    assert ih._fmt_latency_stats([None, None]) == "no successful samples (2 failed/timed out)"


def test_fmt_latency_stats_mixed_reports_min_median_max_and_dropped_count():
    import install_helper as ih

    detail = ih._fmt_latency_stats([0.1, 0.2, 0.3, None])
    assert "min=100ms" in detail
    assert "median=200ms" in detail
    assert "max=300ms" in detail
    assert "n=3" in detail
    assert "1 failed/timed out" in detail


def test_trend_verdict_skips_with_too_few_samples():
    import install_helper as ih

    status, detail = ih._trend_verdict([0.1, 0.2])
    assert status == "SKIP"
    assert "not enough" in detail


def test_trend_verdict_detects_one_time_cache_pattern():
    """First call much slower than the rest -> consistent with a one-time AV/EDR trust
    cache, NOT per-process scanning - status OK (a cheaper fix than the daemon may exist)."""
    import install_helper as ih

    status, detail = ih._trend_verdict([0.5, 0.05, 0.04, 0.06, 0.05])
    assert status == "OK"
    assert "trust/scan cache" in detail
    assert "ADR-014" in detail


def test_trend_verdict_detects_flat_per_process_pattern():
    """No meaningful drop-off -> consistent with per-process scanning regardless of
    repetition - status WARN (the signal the daemon proposal is actually aimed at)."""
    import install_helper as ih

    status, detail = ih._trend_verdict([0.5, 0.48, 0.51, 0.49, 0.5])
    assert status == "WARN"
    assert "no meaningful drop-off" in detail
    assert "daemon proposal" in detail


def test_resolve_sh_env_var_points_directly_at_sh(monkeypatch, tmp_path):
    import install_helper as ih

    sh = tmp_path / "sh.exe"
    sh.write_text("", encoding="utf-8")
    monkeypatch.setenv("CLAUDE_CODE_GIT_BASH_PATH", str(sh))
    assert ih._resolve_sh() == str(sh)


def test_resolve_sh_env_var_points_at_bash_exe_finds_sibling_sh(monkeypatch, tmp_path):
    """CLAUDE_CODE_GIT_BASH_PATH conventionally names bash.exe/git-bash.exe, not sh -
    sh.exe normally lives alongside it in the same directory."""
    import install_helper as ih

    bash = tmp_path / "bash.exe"
    bash.write_text("", encoding="utf-8")
    sh = tmp_path / "sh.exe"
    sh.write_text("", encoding="utf-8")
    monkeypatch.setenv("CLAUDE_CODE_GIT_BASH_PATH", str(bash))
    assert ih._resolve_sh() == str(sh)


def test_resolve_sh_env_var_points_at_directory_finds_sh_inside(monkeypatch, tmp_path):
    import install_helper as ih

    sh = tmp_path / "sh.exe"
    sh.write_text("", encoding="utf-8")
    monkeypatch.setenv("CLAUDE_CODE_GIT_BASH_PATH", str(tmp_path))
    assert ih._resolve_sh() == str(sh)


def test_resolve_sh_env_var_points_at_directory_finds_sh_in_bin_subdir(monkeypatch, tmp_path):
    import install_helper as ih

    bindir = tmp_path / "bin"
    bindir.mkdir()
    sh = bindir / "sh.exe"
    sh.write_text("", encoding="utf-8")
    monkeypatch.setenv("CLAUDE_CODE_GIT_BASH_PATH", str(tmp_path))
    assert ih._resolve_sh() == str(sh)


def test_resolve_sh_falls_back_to_which_when_no_env_var(monkeypatch):
    import install_helper as ih

    monkeypatch.delenv("CLAUDE_CODE_GIT_BASH_PATH", raising=False)
    monkeypatch.setattr(ih.shutil, "which", lambda name: "/usr/bin/sh" if name == "sh" else None)
    assert ih._resolve_sh() == "/usr/bin/sh"


def test_resolve_sh_windows_fallback_paths_when_which_fails(monkeypatch):
    """2026-08-11 live corp report: a PowerShell session has no `sh` on PATH at all even
    with Git Bash installed - this is the fallback that closes that specific gap."""
    import install_helper as ih

    monkeypatch.delenv("CLAUDE_CODE_GIT_BASH_PATH", raising=False)
    monkeypatch.setattr(ih.shutil, "which", lambda name: None)
    monkeypatch.setattr(ih.sys, "platform", "win32")
    target = r"C:\Program Files\Git\usr\bin\sh.exe"
    monkeypatch.setattr(ih.Path, "is_file", lambda self: str(self) == target)
    assert ih._resolve_sh() == target


def test_resolve_sh_returns_none_when_nothing_resolves(monkeypatch):
    import install_helper as ih

    monkeypatch.delenv("CLAUDE_CODE_GIT_BASH_PATH", raising=False)
    monkeypatch.setattr(ih.shutil, "which", lambda name: None)
    monkeypatch.setattr(ih.sys, "platform", "linux")
    assert ih._resolve_sh() is None


def test_measure_repeated_returns_n_samples_all_successful(monkeypatch):
    import install_helper as ih

    monkeypatch.setattr(ih.subprocess, "run", lambda argv, **kw: _proc(0))
    samples = ih._measure_repeated(lambda: (["true"], {}), n=5)
    assert len(samples) == 5
    assert all(s is not None and s >= 0 for s in samples)


def test_measure_repeated_records_none_on_timeout(monkeypatch):
    import install_helper as ih

    monkeypatch.setattr(ih.subprocess, "run", _timeout_runner)
    samples = ih._measure_repeated(lambda: (["true"], {}), n=3)
    assert samples == [None, None, None]


def test_measure_concurrent_returns_n_samples_and_a_total(monkeypatch):
    import install_helper as ih

    monkeypatch.setattr(ih.subprocess, "run", lambda argv, **kw: _proc(0))
    samples, total = ih._measure_concurrent(lambda: (["true"], {}), n=6)
    assert len(samples) == 6
    assert all(s is not None for s in samples)
    assert total >= 0


def test_run_adr014_smoke_test_returns_none_when_spike_absent(tmp_path, monkeypatch):
    """A repo checkout without docs/internal/adr-014-spike/ (predates it, or the spike
    was removed) must SKIP, not error - same "absent prerequisite" posture as every
    other diagnostic in this file. tmp_path must actually satisfy looks_like_repo()
    (.git + .claude-plugin/plugin.json) - otherwise _resolve_repo_root rejects it as a
    candidate entirely and falls through to its own __file__-parent fallback, which is
    unconditionally a real repo (THIS checkout) with the spike genuinely present -
    silently testing the wrong repo instead of skipping. _isolate_home also needed:
    without it, the load_config(...).get("repo_path") candidate in between can still
    point at this machine's real clone if it has ever been configured here."""
    import install_helper as ih

    _isolate_home(monkeypatch, tmp_path)
    (tmp_path / ".git").mkdir()
    (tmp_path / ".claude-plugin").mkdir()
    (tmp_path / ".claude-plugin" / "plugin.json").write_text("{}", encoding="utf-8")
    assert ih.run_adr014_smoke_test(ih.Style(False), ih.marks(), repo_hint=str(tmp_path)) is None


def test_run_adr014_smoke_test_relays_captured_output_and_exit_code(monkeypatch, tmp_path, capsys):
    """Confirms the wrapper actually calls run_cmd (demo-mode-safe, not a raw subprocess
    call) and prints what it captured - does not re-test the spike's own smoke_test.py
    logic, which is covered separately."""
    import install_helper as ih

    spike_dir = tmp_path / "docs" / "internal" / "adr-014-spike"
    spike_dir.mkdir(parents=True)
    (spike_dir / "smoke_test.py").write_text("", encoding="utf-8")
    monkeypatch.setattr(
        ih,
        "run_cmd",
        lambda argv, cwd=None, timeout=300: _proc(1, stdout="3 passed, 1 failed.", stderr=""),
    )
    rc = ih.run_adr014_smoke_test(ih.Style(False), ih.marks(), repo_hint=str(tmp_path))
    out = capsys.readouterr().out
    assert rc == 1
    assert "3 passed, 1 failed." in out


def _make_fake_repo(tmp_path):
    """_resolve_repo_root only accepts a repo_hint that satisfies looks_like_repo() -
    without these markers, a bare tmp_path is silently REJECTED and resolution falls
    through to __file__'s own parent (THIS real checkout), which would make every test
    below run against the real project instead of the fake one it just built."""
    (tmp_path / ".git").mkdir()
    (tmp_path / ".claude-plugin").mkdir()
    (tmp_path / ".claude-plugin" / "plugin.json").write_text("{}", encoding="utf-8")


def test_run_daemon_start_diagnostic_errors_when_guard_daemon_missing(
    tmp_path, monkeypatch, capsys
):
    """No scripts/guard_daemon.py at all - must report ERROR and return 1 immediately,
    never attempt to spawn anything."""
    import install_helper as ih

    _isolate_home(monkeypatch, tmp_path)
    _make_fake_repo(tmp_path)
    rc = ih.run_daemon_start_diagnostic(ih.Style(False), ih.marks(), repo_hint=str(tmp_path))
    out = capsys.readouterr().out
    assert rc == 1
    assert "guard_daemon.py present" in out
    assert "not found" in out


def test_run_daemon_start_diagnostic_surfaces_popen_exception(tmp_path, monkeypatch, capsys):
    """The entire point of this diagnostic: a Popen failure that production's own
    _start_daemon_detached() would silently swallow must be visible here, with the
    actual exception detail, not just 'no port file, no clue why'."""
    import install_helper as ih

    _isolate_home(monkeypatch, tmp_path)
    _make_fake_repo(tmp_path)
    monkeypatch.chdir(tmp_path)  # the debug bundle writes to Path.cwd() - keep it in tmp_path
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "guard_daemon.py").write_text("", encoding="utf-8")

    def boom(*a, **k):
        raise OSError(13, "Permission denied")

    monkeypatch.setattr(ih.subprocess, "Popen", boom)
    rc = ih.run_daemon_start_diagnostic(ih.Style(False), ih.marks(), repo_hint=str(tmp_path))
    out = capsys.readouterr().out
    assert rc == 1
    assert "foreground daemon spawn" in out
    assert "detached daemon spawn" in out
    assert "Permission denied" in out
    # The detached-path failure must be called out as the actual production code path,
    # not just another generic error line - that's the framing that makes this useful.
    assert "THIS is the production" in out


def test_run_daemon_start_diagnostic_survives_non_utf8_team_preferences(
    tmp_path, monkeypatch, capsys
):
    """Found in review, 2026-08-13: UnicodeDecodeError is NOT an OSError, so a
    team-preferences.json with invalid UTF-8 bytes used to crash this diagnostic (only
    OSError was caught) instead of reporting it as unreadable and carrying on."""
    import install_helper as ih

    _isolate_home(monkeypatch, tmp_path)
    _make_fake_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "guard_daemon.py").write_text("", encoding="utf-8")
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    (claude_dir / "team-preferences.json").write_bytes(b'{"guard_daemon": \xff\xfe true}')

    def boom(*a, **k):
        raise OSError(13, "Permission denied")

    monkeypatch.setattr(ih.subprocess, "Popen", boom)
    # Must not raise UnicodeDecodeError.
    rc = ih.run_daemon_start_diagnostic(ih.Style(False), ih.marks(), repo_hint=str(tmp_path))
    out = capsys.readouterr().out
    assert rc == 1
    assert "team-preferences.json readable" in out


def test_run_daemon_start_diagnostic_full_success_against_a_real_stub_daemon(
    tmp_path, monkeypatch, capsys
):
    """End-to-end against a minimal but REAL stub daemon (a real subprocess, a real
    socket, a real port file) - proves the diagnostic's own polling/connect/report
    mechanics work correctly, without depending on the full production guard_daemon.py's
    complexity. Both checks (foreground + detached) must report OK, and a genuine
    request/response round-trip must succeed."""
    import install_helper as ih

    _isolate_home(monkeypatch, tmp_path)
    _make_fake_repo(tmp_path)
    monkeypatch.chdir(tmp_path)  # the debug bundle writes to Path.cwd() - keep it in tmp_path
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    stub = scripts_dir / "guard_daemon.py"
    stub.write_text(
        "import json, socket, sys, threading, time\n"
        "from pathlib import Path\n"
        "module_root, state_root = sys.argv[1], sys.argv[2]\n"
        "srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)\n"
        "srv.bind(('127.0.0.1', 0))\n"
        "srv.listen(5)\n"
        "port = srv.getsockname()[1]\n"
        "port_dir = Path(state_root) / '.claude'\n"
        "port_dir.mkdir(parents=True, exist_ok=True)\n"
        "(port_dir / '.guard-daemon-port').write_text(f'{port}\\ntesttoken\\n')\n"
        "def serve():\n"
        "    conn, _ = srv.accept()\n"
        "    raw = conn.makefile('r').readline()\n"
        "    req = json.loads(raw)\n"
        "    resp = {'exit_code': 0, 'stderr': ''} if req.get('token') == 'testtoken' "
        "else {'exit_code': 0, 'stderr': 'unauthorized'}\n"
        "    conn.sendall((json.dumps(resp) + '\\n').encode())\n"
        "    conn.close()\n"
        "t = threading.Thread(target=serve, daemon=True)\n"
        "t.start()\n"
        "time.sleep(3)\n",
        encoding="utf-8",
    )

    rc = ih.run_daemon_start_diagnostic(ih.Style(False), ih.marks(), repo_hint=str(tmp_path))
    out = capsys.readouterr().out
    assert rc == 0
    assert "foreground daemon spawn: port file appeared" in out
    assert "foreground daemon responds" in out
    assert "'exit_code': 0" in out
    assert "detached daemon spawn: port file appeared" in out


def test_run_hook_latency_diagnostic_no_interpreter_skips_and_returns_1(monkeypatch, capsys):
    import install_helper as ih

    monkeypatch.setattr(ih, "_check_interpreters", lambda order: ([], ""))
    rc = ih.run_hook_latency_diagnostic(ih.Style(False), ih.marks())
    out = capsys.readouterr().out
    assert rc == 1
    assert "no working interpreter found" in out


def test_run_hook_latency_diagnostic_missing_launcher_skips_guard_sections(
    monkeypatch, tmp_path, capsys
):
    """No .claude/hooks/run-guard.sh in this repo root -> the guard-launcher and fan-out
    sections SKIP cleanly rather than erroring - the bare cold-start + trend sections
    still run, since they only need an interpreter, not the launcher."""
    import install_helper as ih

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CLAUDE_CODE_GIT_BASH_PATH", raising=False)
    _stub_interpreters(monkeypatch, ih, winner="python3")
    monkeypatch.setattr(ih.subprocess, "run", lambda argv, **kw: _proc(0))
    monkeypatch.setattr(ih.shutil, "which", lambda name: None)  # no sh, no powershell
    rc = ih.run_hook_latency_diagnostic(ih.Style(False), ih.marks(), repo_hint=str(tmp_path))
    out = capsys.readouterr().out
    assert rc == 0  # SKIP is not a failure
    assert "real guard-launcher cost" in out
    assert "can't measure the real path" in out
    assert list(tmp_path.glob("virt-surv-hook-latency-*.txt"))  # always written


def test_run_hook_latency_diagnostic_always_writes_data_file_even_when_clean(
    monkeypatch, tmp_path, capsys
):
    """Unlike run_selftest's failure-only bundle, this one writes every time - the numbers
    are the point here, not just catching errors."""
    import install_helper as ih

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CLAUDE_CODE_GIT_BASH_PATH", raising=False)
    _stub_interpreters(monkeypatch, ih, winner="python3")
    monkeypatch.setattr(ih.subprocess, "run", lambda argv, **kw: _proc(0))
    monkeypatch.setattr(ih.shutil, "which", lambda name: None)
    ih.run_hook_latency_diagnostic(ih.Style(False), ih.marks(), repo_hint=str(tmp_path))
    files = list(tmp_path.glob("virt-surv-hook-latency-*.txt"))
    assert len(files) == 1
    content = files[0].read_text(encoding="utf-8")
    assert "hook-latency diagnostic" in content
    assert "ADR-014" in content


def test_run_hook_latency_diagnostic_measures_real_launcher_when_present(
    monkeypatch, tmp_path, capsys
):
    """With a resolvable sh and a present run-guard.sh/dispatcher, the guard-launcher and
    concurrent fan-out sections actually run (not just SKIP) - confirms the wiring reaches
    the real-path branch, not just the missing-launcher fallback tested above."""
    import install_helper as ih

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CLAUDE_CODE_GIT_BASH_PATH", raising=False)
    hooks_dir = tmp_path / ".claude" / "hooks"
    hooks_dir.mkdir(parents=True)
    (hooks_dir / "run-guard.sh").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "bash_hook_dispatcher.py").write_text("", encoding="utf-8")
    (tmp_path / "README.md").write_text("x", encoding="utf-8")

    _stub_interpreters(monkeypatch, ih, winner="python3")
    monkeypatch.setattr(ih.subprocess, "run", lambda argv, **kw: _proc(0))
    monkeypatch.setattr(ih.shutil, "which", lambda name: "/bin/sh" if name == "sh" else None)
    rc = ih.run_hook_latency_diagnostic(ih.Style(False), ih.marks(), repo_hint=str(tmp_path))
    out = capsys.readouterr().out
    assert rc == 0
    assert "Real guard-launcher end to end" in out
    assert "Concurrent fan-out simulation" in out
    assert "guard overhead beyond bare interpreter" in out


# --- enable_step delegates to run_configure (2026-08-12 consolidation) ---
#
# An onboarding UX audit found enable_step had grown its own ~180-line copy of
# run_configure's permissions/env-tuning/betas/docx/model questions - divergent wording
# from run_configure, six of its thirteen preferences never asked here at all, and a
# model-scope bug already fixed at the OTHER "set the model" call site (model_step,
# 2026-08-05) reproduced here. Fixed by making enable_step delegate entirely to
# run_configure once the target directory is known - so these tests now verify the
# DELEGATION (what enable_step calls run_configure with, under which conditions), not
# run_configure's own internal question flow, which is already covered by its own
# extensive test suite above.


def test_enable_step_declining_never_calls_run_configure(tmp_path, monkeypatch):
    import install_helper as ih

    calls = []
    monkeypatch.setattr(ih, "run_configure", lambda *a, **k: calls.append((a, k)) or 0)
    monkeypatch.setattr(ih, "confirm", lambda *a, **k: False)
    inst = ih.Installer(_args(yes=False), ih.Style(False), ih.marks(), subset="full")
    inst.enable_step()
    assert calls == []


def test_enable_step_delegates_to_run_configure_with_the_chosen_directory(tmp_path, monkeypatch):
    """The "which directory?" prompt's answer must reach run_configure unchanged."""
    import install_helper as ih

    calls = []
    monkeypatch.setattr(ih, "run_configure", lambda *a, **k: calls.append(a) or 0)
    monkeypatch.setattr(ih, "confirm", lambda *a, **k: True)
    monkeypatch.setattr(ih, "ask", lambda *a, **k: str(tmp_path / "proj"))
    inst = ih.Installer(_args(yes=False), ih.Style(False), ih.marks(), subset="full")
    inst.enable_step()
    assert len(calls) == 1
    target = calls[0][0]
    assert target == Path(str(tmp_path / "proj"))


def test_enable_step_passes_quick_defaults_as_assume_yes_on_full_subset(tmp_path, monkeypatch):
    """'Go with the recommended defaults' (quick_setup_choice) must reach run_configure
    as assume_yes=True, so its own quick-defaults gate applies every default with zero
    further questions - the same behavior the old inline implementation hand-replicated
    per collaborator, now delegated to the one place that already implements it."""
    import install_helper as ih

    calls = []
    monkeypatch.setattr(ih, "run_configure", lambda *a, **k: calls.append(k) or 0)
    monkeypatch.setattr(ih, "confirm", lambda *a, **k: True)
    monkeypatch.setattr(ih, "ask", lambda *a, **k: str(tmp_path))
    inst = ih.Installer(_args(yes=False), ih.Style(False), ih.marks(), subset="full")
    inst.quick_defaults = True
    inst.enable_step()
    assert calls == [{"assume_yes": True, "demo": False}]


def test_enable_step_does_not_pass_assume_yes_when_not_quick_defaults(tmp_path, monkeypatch):
    """Manually walking through project enablement (quick_defaults False) must leave
    run_configure to ask its own questions interactively."""
    import install_helper as ih

    calls = []
    monkeypatch.setattr(ih, "run_configure", lambda *a, **k: calls.append(k) or 0)
    monkeypatch.setattr(ih, "confirm", lambda *a, **k: True)
    monkeypatch.setattr(ih, "ask", lambda *a, **k: str(tmp_path))
    inst = ih.Installer(_args(yes=False), ih.Style(False), ih.marks(), subset="full")
    inst.quick_defaults = False
    inst.enable_step()
    assert calls == [{"assume_yes": False, "demo": False}]


def test_enable_step_quick_defaults_does_not_affect_the_standalone_enable_subset(
    tmp_path, monkeypatch
):
    """quick_defaults only ever gets set True via quick_setup_choice, which is part of the
    'full' install/update flow - the standalone menu 'enable' subset never runs it.
    Belt-and-braces: even if something set it True out of band, the subset != 'full'
    guard must still force assume_yes=False through to run_configure."""
    import install_helper as ih

    calls = []
    monkeypatch.setattr(ih, "run_configure", lambda *a, **k: calls.append(k) or 0)
    monkeypatch.setattr(ih, "ask", lambda *a, **k: str(tmp_path))
    inst = ih.Installer(_args(yes=False), ih.Style(False), ih.marks(), subset="enable")
    inst.quick_defaults = True  # out-of-band - should not happen in practice, tested anyway
    inst.enable_step()
    assert calls == [{"assume_yes": False, "demo": False}]


# --- cleaner registry cross-reference (2026-08-17 corp debug session, finding 2) ----------


def test_clean_plugin_cache_surfaces_and_removes_ghost_registry_installs(
    tmp_path, monkeypatch, capsys
):
    """A PARTIAL install (no operating-guide marker) is invisible to the marker scan but
    the registry keeps pointing at it, breaking every probe with no cleanup path. The
    cleaner now cross-references registry installPath values: on-disk-but-markerless
    ghosts attributable to this plugin join the removable set."""
    import install_helper as ih

    monkeypatch.setattr(ih.Path, "home", staticmethod(lambda: tmp_path))
    active = (
        tmp_path / ".claude" / "plugins" / "cache" / "mkt" / "compliance-surveillance-team" / "1.0"
    )
    _make_fake_plugin_install(active)
    ghost = tmp_path / "old-virtual-surv-IT-copy"
    (ghost / ".claude-plugin").mkdir(parents=True)
    (ghost / ".claude-plugin" / "plugin.json").write_text(
        '{"name": "compliance-surveillance-team"}', encoding="utf-8"
    )  # manifest yes, marker no = ghost
    registry = tmp_path / ".claude" / "plugins" / "installed_plugins.json"
    registry.parent.mkdir(parents=True, exist_ok=True)
    registry.write_text(
        json.dumps(
            {"plugins": [{"installPath": str(active)}, {"installPath": str(ghost)}]}
        ),
        encoding="utf-8",
    )
    rc = ih.run_clean_plugin_cache(ih.Style(False), ih.marks(), assume_yes=True)
    out = capsys.readouterr().out
    assert rc == 0
    assert "ghost" in out
    assert not ghost.exists()  # removed
    assert active.exists()  # active never touched


def test_clean_plugin_cache_keeps_an_active_but_partial_install(tmp_path, monkeypatch, capsys):
    """The registry's ACTIVE entry can itself be partial - it is still what Claude Code
    is configured to use, so it is kept and flagged for repair, never deleted."""
    import install_helper as ih

    monkeypatch.setattr(ih.Path, "home", staticmethod(lambda: tmp_path))
    ghost = tmp_path / "virtual-surv-IT"
    (ghost / ".claude-plugin").mkdir(parents=True)
    (ghost / ".claude-plugin" / "plugin.json").write_text(
        '{"name": "compliance-surveillance-team"}', encoding="utf-8"
    )
    registry = tmp_path / ".claude" / "plugins" / "installed_plugins.json"
    registry.parent.mkdir(parents=True)
    registry.write_text(json.dumps({"plugins": [{"installPath": str(ghost)}]}), encoding="utf-8")
    rc = ih.run_clean_plugin_cache(ih.Style(False), ih.marks(), assume_yes=True)
    out = capsys.readouterr().out
    assert rc == 0
    assert "PARTIAL" in out and "repair" in out
    assert ghost.exists()


def test_clean_plugin_cache_reports_stale_registry_entries_without_touching_registry(
    tmp_path, monkeypatch, capsys
):
    import install_helper as ih

    monkeypatch.setattr(ih.Path, "home", staticmethod(lambda: tmp_path))
    gone = tmp_path / "moved-away-virtual-surv-IT"
    registry = tmp_path / ".claude" / "plugins" / "installed_plugins.json"
    registry.parent.mkdir(parents=True)
    registry.write_text(json.dumps({"plugins": [{"installPath": str(gone)}]}), encoding="utf-8")
    before = registry.read_text(encoding="utf-8")
    rc = ih.run_clean_plugin_cache(ih.Style(False), ih.marks(), assume_yes=True)
    out = capsys.readouterr().out
    assert rc == 0
    assert "does not exist" in out and "reinstall" in out
    assert registry.read_text(encoding="utf-8") == before  # report-only, never edited


def test_clean_plugin_cache_never_offers_unattributable_dirs(tmp_path, monkeypatch, capsys):
    """A registry path with no manifest and no recognisable token could belong to ANY
    plugin - it must never join the removable set."""
    import install_helper as ih

    monkeypatch.setattr(ih.Path, "home", staticmethod(lambda: tmp_path))
    active = (
        tmp_path / ".claude" / "plugins" / "cache" / "mkt" / "compliance-surveillance-team" / "1.0"
    )
    _make_fake_plugin_install(active)
    other = tmp_path / "some-other-plugin"
    other.mkdir()
    registry = tmp_path / ".claude" / "plugins" / "installed_plugins.json"
    registry.parent.mkdir(parents=True, exist_ok=True)
    registry.write_text(
        json.dumps({"plugins": [{"installPath": str(active)}, {"installPath": str(other)}]}),
        encoding="utf-8",
    )
    rc = ih.run_clean_plugin_cache(ih.Style(False), ih.marks(), assume_yes=True)
    assert rc == 0
    assert other.exists()  # untouched, unmentioned as removable
