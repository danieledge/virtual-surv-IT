"""scripts/armed_check.py - the installer's proof that the guards fire in the target project
(2026-09-13 framework review, step 5.5). Runs the REAL launcher and dispatcher."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from scripts import armed_check  # noqa: E402

pytestmark = pytest.mark.skipif(shutil.which("sh") is None, reason="needs a POSIX sh for the hooks")


def test_the_check_proves_both_guards_in_a_fresh_project(tmp_path):
    (tmp_path / "README.md").write_text("# a project\n", encoding="utf-8")
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "settings.json").write_text(
        json.dumps({"enabledPlugins": {"compliance-surveillance-team@virtual-surv-it": True}}),
        encoding="utf-8",
    )
    results = armed_check.check(REPO, tmp_path)
    assert {label: ok for label, ok, _ in results} == {
        "raw-data read": True,
        "ordinary read": True,
        "execution gate (engaged)": True,
        "execution gate (dormant)": True,
        "plugin enabled": True,
    }, results
    good, line = armed_check.summary(tmp_path, results)
    assert good and line.startswith("guards armed in")


def test_the_check_names_a_project_that_did_not_enable_the_plugin(tmp_path):
    (tmp_path / "README.md").write_text("# a project\n", encoding="utf-8")
    results = armed_check.check(REPO, tmp_path)
    by = {label: (ok, detail) for label, ok, detail in results}
    assert by["raw-data read"][0] and by["execution gate (engaged)"][0]
    assert not by["plugin enabled"][0]
    good, line = armed_check.summary(tmp_path, results)
    assert not good and "GUARDS NOT PROVEN" in line and "plugin enabled" in line
    assert armed_check.main(["--project", str(tmp_path)]) == 1


def test_the_team_repo_itself_counts_as_enabled():
    ok, detail = armed_check.plugin_enabled(REPO, REPO)
    assert ok and "repo-as-project" in detail


def test_a_missing_shell_is_named_with_its_fix_not_reported_as_exit_minus_one(
    tmp_path, monkeypatch
):
    """2026-09-14 live: on the owner's corporate Windows box the installer's armed check
    reported 'raw-data read: exit -1' for every guard. The guards were fine; the prover could
    not start `sh`. The failure must say which, and what to do."""
    monkeypatch.setattr(armed_check, "_find_sh", lambda sh="sh": None)
    (tmp_path / "README.md").write_text("# p\n", encoding="utf-8")
    results = armed_check.check(REPO, tmp_path)
    labels = [label for label, _, _ in results]
    assert labels == ["POSIX shell", "plugin enabled"], results
    shell = results[0]
    assert shell[1] is False
    assert "Git for Windows" in shell[2] and "CLAUDE_CODE_GIT_BASH_PATH" in shell[2]
    assert "exit -1" not in shell[2]
    good, line = armed_check.summary(tmp_path, results)
    assert not good
    assert "Next:" in line and "new terminal" in line


def test_a_launcher_that_cannot_start_is_said_so_in_the_detail(tmp_path, monkeypatch):
    monkeypatch.setattr(armed_check, "_find_sh", lambda sh="sh": "/nonexistent/sh")
    monkeypatch.setattr(armed_check, "_run_guard", lambda *a, **k: -1)
    (tmp_path / "README.md").write_text("# p\n", encoding="utf-8")
    results = armed_check.check(REPO, tmp_path)
    raw = next(r for r in results if r[0] == "raw-data read")
    assert raw[1] is False
    assert "could not be started through /nonexistent/sh" in raw[2]
    good, line = armed_check.summary(tmp_path, results)
    assert not good and "Next: fix the shell" in line


def test_every_failure_summary_ends_with_an_action(tmp_path):
    results = [("raw-data read", False, "exit 0 (want 2: BLOCK)"), ("plugin enabled", True, "x")]
    good, line = armed_check.summary(tmp_path, results)
    assert not good
    assert "Next:" in line and "do not use the team on real data" in line
    only_plugin = [("raw-data read", True, "exit 2"), ("plugin enabled", False, "not enabled")]
    good, line = armed_check.summary(tmp_path, only_plugin)
    assert "Next:" in line and "virt-surv go" in line


def test_find_sh_derives_the_shell_from_git_on_windows(monkeypatch):
    monkeypatch.delenv("CLAUDE_CODE_GIT_BASH_PATH", raising=False)
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    git_exe = r"C:\Users\d\AppData\Local\Programs\Git\cmd\git.exe"
    monkeypatch.setattr(
        armed_check.shutil, "which", lambda name: git_exe if name == "git" else None
    )
    monkeypatch.setattr(armed_check.sys, "platform", "win32")
    target = r"C:\Users\d\AppData\Local\Programs\Git\bin\sh.exe"
    monkeypatch.setattr(armed_check.Path, "is_file", lambda self: str(self) == target)
    assert armed_check._find_sh() == target
