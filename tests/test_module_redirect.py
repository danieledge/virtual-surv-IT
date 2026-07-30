"""The module-form redirect hook (scripts/module_form_redirect.py, 2026-07-30):
`-m scripts.<name>` in plugin mode exits 1 before the script loads; the hook catches
it pre-run and hands the model the bundled path-form command. Convenience redirect,
fail-open by design - it must never block anything it cannot improve."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
HOOK = REPO_ROOT / "scripts" / "module_form_redirect.py"
STAGED = REPO_ROOT / "scripts" / "staged_hooks" / "module_form_redirect.py"


def _run(payload: dict, plugin_root: str = "") -> subprocess.CompletedProcess:
    import os

    env = dict(os.environ)
    env.pop("CLAUDE_PLUGIN_ROOT", None)
    if plugin_root:
        env["CLAUDE_PLUGIN_ROOT"] = plugin_root
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )


def _bash(command: str, cwd: Path) -> dict:
    return {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(cwd)}


def test_staged_and_live_are_byte_synced():
    assert HOOK.read_bytes() == STAGED.read_bytes()


def test_plugin_mode_redirects_with_exact_path(tmp_path):
    root = tmp_path / "plugin"
    (root / "scripts").mkdir(parents=True)
    (root / "scripts" / "engagement_state.py").write_text("", encoding="utf-8")
    project = tmp_path / "project"
    project.mkdir()
    proc = _run(_bash("py -m scripts.engagement_state list", project), plugin_root=str(root))
    assert proc.returncode == 2
    assert str(root / "scripts" / "engagement_state.py") in proc.stderr
    assert "keep the same interpreter" in proc.stderr


def test_repo_as_project_module_form_allowed(tmp_path):
    project = tmp_path / "repo"
    (project / "scripts").mkdir(parents=True)
    (project / "scripts" / "engagement_state.py").write_text("", encoding="utf-8")
    proc = _run(
        _bash("python -m scripts.engagement_state list", project), plugin_root=str(tmp_path)
    )
    assert proc.returncode == 0


def test_fail_open_without_plugin_root_or_bundled_copy(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    # no CLAUDE_PLUGIN_ROOT at all
    assert _run(_bash("py -m scripts.engagement_state list", project)).returncode == 0
    # root set but no such bundled script
    empty_root = tmp_path / "empty"
    (empty_root / "scripts").mkdir(parents=True)
    proc = _run(_bash("py -m scripts.engagement_state list", project), str(empty_root))
    assert proc.returncode == 0


def test_ordinary_commands_and_garbage_stdin_pass(tmp_path):
    assert _run(_bash("git status", tmp_path)).returncode == 0
    proc = subprocess.run(
        [sys.executable, str(HOOK)], input="{not json", capture_output=True, text=True, timeout=30
    )
    assert proc.returncode == 0
