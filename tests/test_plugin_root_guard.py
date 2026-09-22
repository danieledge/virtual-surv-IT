"""plugin_root_guard.py (2026-09-20): keeps an engaged plugin-mode session out of the
plugin's OWN installed tree - incident log #19 (a `cd` there silently flips mode detection
to repo-as-project) and #20 (a deliverable written there vanishes on the next update or
corrupts the shared install). Both were "prose fix only" in the incident log; this is the
mechanical half."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
HOOK = REPO_ROOT / "scripts" / "plugin_root_guard.py"


def _run(payload: dict, plugin_root: str = "", cwd: Path | None = None) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env.pop("CLAUDE_PLUGIN_ROOT", None)
    env.pop("CLAUDE_PROJECT_DIR", None)
    if plugin_root:
        env["CLAUDE_PLUGIN_ROOT"] = plugin_root
    if cwd is not None:
        env["CLAUDE_PROJECT_DIR"] = str(cwd)
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )


def _stamp(root: Path, session_id: str) -> None:
    engagements = root / "VSIT" / "engagements"
    engagements.mkdir(parents=True, exist_ok=True)
    (engagements / ".team-session.json").write_text(
        json.dumps({"session_id": session_id}), encoding="utf-8"
    )


def _bash(command: str, session_id: str = "s1") -> dict:
    return {"tool_name": "Bash", "tool_input": {"command": command}, "session_id": session_id}


def _write(path: str, session_id: str = "s1", tool: str = "Write") -> dict:
    return {"tool_name": tool, "tool_input": {"file_path": path}, "session_id": session_id}


def test_cd_into_plugin_root_is_blocked_in_engaged_plugin_mode(tmp_path):
    plugin = tmp_path / "plugin"
    (plugin / "scripts").mkdir(parents=True)
    project = tmp_path / "project"
    project.mkdir()
    _stamp(project, "s1")
    result = _run(_bash(f'cd "{plugin}"'), plugin_root=str(plugin), cwd=project)
    assert result.returncode == 2
    assert "plugin-root guard" in result.stderr
    assert "#19" in result.stderr


def test_cd_into_plugin_subdir_is_blocked(tmp_path):
    plugin = tmp_path / "plugin"
    (plugin / "scripts").mkdir(parents=True)
    project = tmp_path / "project"
    project.mkdir()
    _stamp(project, "s1")
    result = _run(_bash(f'cd "{plugin / "scripts"}" && ls'), plugin_root=str(plugin), cwd=project)
    assert result.returncode == 2


def test_cd_redirects_once_per_target_per_session(tmp_path):
    plugin = tmp_path / "plugin"
    (plugin / "scripts").mkdir(parents=True)
    project = tmp_path / "project"
    project.mkdir()
    _stamp(project, "s1")
    first = _run(_bash(f'cd "{plugin}"'), plugin_root=str(plugin), cwd=project)
    second = _run(_bash(f'cd "{plugin}"'), plugin_root=str(plugin), cwd=project)
    assert first.returncode == 2
    assert second.returncode == 0


def test_cd_into_the_working_project_itself_is_untouched(tmp_path):
    plugin = tmp_path / "plugin"
    (plugin / "scripts").mkdir(parents=True)
    project = tmp_path / "project"
    (project / "subdir").mkdir(parents=True)
    _stamp(project, "s1")
    result = _run(_bash(f'cd "{project / "subdir"}"'), plugin_root=str(plugin), cwd=project)
    assert result.returncode == 0


def test_repo_as_project_is_never_flagged(tmp_path):
    # CLAUDE_PLUGIN_ROOT happens to equal the working project (repo-as-project): cd-ing
    # around inside it is completely normal and must never be redirected.
    project = tmp_path / "team-repo"
    project.mkdir()
    _stamp(project, "s1")
    result = _run(_bash(f'cd "{project}"'), plugin_root=str(project), cwd=project)
    assert result.returncode == 0


def test_dormant_session_is_never_flagged(tmp_path):
    plugin = tmp_path / "plugin"
    (plugin / "scripts").mkdir(parents=True)
    project = tmp_path / "project"
    project.mkdir()
    # No stamp written - team never invoked this session.
    result = _run(_bash(f'cd "{plugin}"'), plugin_root=str(plugin), cwd=project)
    assert result.returncode == 0


def test_write_into_plugin_root_is_blocked(tmp_path):
    plugin = tmp_path / "plugin"
    (plugin / "scripts").mkdir(parents=True)
    project = tmp_path / "project"
    project.mkdir()
    _stamp(project, "s1")
    result = _run(_write(str(plugin / "scripts" / "oops.py")), plugin_root=str(plugin), cwd=project)
    assert result.returncode == 2
    assert "#20" in result.stderr


def test_write_into_plugin_root_blocks_every_time_not_just_once(tmp_path):
    plugin = tmp_path / "plugin"
    (plugin / "scripts").mkdir(parents=True)
    project = tmp_path / "project"
    project.mkdir()
    _stamp(project, "s1")
    target = str(plugin / "scripts" / "oops.py")
    first = _run(_write(target), plugin_root=str(plugin), cwd=project)
    second = _run(_write(target), plugin_root=str(plugin), cwd=project)
    assert first.returncode == 2
    assert second.returncode == 2


def test_edit_into_plugin_root_is_also_blocked(tmp_path):
    plugin = tmp_path / "plugin"
    (plugin / "scripts").mkdir(parents=True)
    project = tmp_path / "project"
    project.mkdir()
    _stamp(project, "s1")
    result = _run(
        _write(str(plugin / "scripts" / "existing.py"), tool="Edit"), plugin_root=str(plugin), cwd=project
    )
    assert result.returncode == 2


def test_write_into_the_working_project_is_untouched(tmp_path):
    plugin = tmp_path / "plugin"
    (plugin / "scripts").mkdir(parents=True)
    project = tmp_path / "project"
    project.mkdir()
    _stamp(project, "s1")
    result = _run(
        _write(str(project / "VSIT" / "engagements" / "demo" / "delivery-report.md")),
        plugin_root=str(plugin),
        cwd=project,
    )
    assert result.returncode == 0


def test_malformed_stdin_allows_and_never_raises():
    result = subprocess.run(
        [sys.executable, str(HOOK)],
        input="not json",
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0


def test_unrelated_tool_is_untouched(tmp_path):
    plugin = tmp_path / "plugin"
    (plugin / "scripts").mkdir(parents=True)
    project = tmp_path / "project"
    project.mkdir()
    _stamp(project, "s1")
    result = _run(
        {"tool_name": "Read", "tool_input": {"file_path": str(plugin / "scripts" / "x.py")}, "session_id": "s1"},
        plugin_root=str(plugin),
        cwd=project,
    )
    assert result.returncode == 0
