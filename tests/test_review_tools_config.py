"""On/off/auto review-tool config (scripts/check-review-tools.sh, 2026-08-04): the seven
officially supported analysers (ruff/mypy/bandit/gitleaks/sqlfluff/black/shfmt) can be forced
on/off per project (.claude/team-preferences.json "review_tools"), per machine
(~/.config/virt-surv-it/installer.json "default_review_tools"), or killed centrally
(CST_NO_EXTERNAL_TOOLS=1) - proven live against a real corp-proxy-shaped failure mode
(semgrep/pip-audit) this mechanism exists to prevent a recurrence of.

Always run with --refresh: these tests intentionally probe different project/machine config
each time, and the analyser-table cache (unrelated to this config) would otherwise serve a
stale table across tests sharing a tmp_path lineage."""

from __future__ import annotations

import json
import pathlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "check-review-tools.sh"

pytestmark = pytest.mark.skipif(
    sys.platform == "win32" or shutil.which("bash") is None, reason="needs bash"
)


def _run(cwd: Path, env: dict | None = None) -> str:
    full_env = {"PATH": __import__("os").environ.get("PATH", "")}
    if env:
        full_env.update(env)
    proc = subprocess.run(
        ["bash", str(SCRIPT), "--refresh"],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=60,
        env=full_env,
    )
    assert proc.returncode == 0
    return proc.stdout


def _minimal_path() -> str:
    """A minimal but PORTABLE PATH: enough to run the script, not enough to find the tools.

    This was hardcoded to "/usr/bin:/bin", which is where Debian and Ubuntu keep python3 and
    not where the official python images keep it (/usr/local/bin). In a container the script
    could not run its own python step, so the output differed and the assertion failed for a
    reason unrelated to tool detection (2026-08-25). The intent - stated in the comments here
    - was always "enough for bash and python3", so derive it from where they actually are.
    """
    import shutil

    dirs = []
    for tool in ("bash", "python3"):
        found = shutil.which(tool)
        if found:
            parent = str(pathlib.Path(found).resolve().parent)
            if parent not in dirs:
                dirs.append(parent)
    for fallback in ("/usr/bin", "/bin"):
        if fallback not in dirs:
            dirs.append(fallback)
    return os.pathsep.join(dirs)


def _write_project_config(cwd: Path, review_tools: dict) -> None:
    claude = cwd / ".claude"
    claude.mkdir(parents=True, exist_ok=True)
    (claude / "team-preferences.json").write_text(
        json.dumps({"review_tools": review_tools}), encoding="utf-8"
    )


def test_off_tool_is_not_probed_and_reported_disabled(tmp_path):
    _write_project_config(tmp_path, {"mypy": "off"})
    out = _run(tmp_path)
    assert "Disabled by config" in out
    assert "mypy" in out.split("Disabled by config")[1].split("Artifact renderers")[0]
    # A disabled tool must not also show up in Installed, even if it happens to be on PATH.
    installed_block = out.split("Installed")[1].split("Missing")[0]
    assert "mypy" not in installed_block


def test_on_tool_missing_is_reported_as_required_missing(tmp_path):
    # A minimal PATH (just enough for bash/python3/coreutils to run the script itself)
    # rather than the real environment's PATH - reproducible regardless of what happens
    # to be pip-installed on the machine running these tests, unlike relying on "sqlfluff
    # just isn't installed here" which could silently stop testing anything.
    _write_project_config(tmp_path, {"sqlfluff": "on"})
    out = _run(tmp_path, env={"PATH": _minimal_path()})
    assert "Required by config but not installed" in out
    assert "sqlfluff" in out
    assert "config requires this tool 'on'" in out


def test_kill_switch_disables_all_seven_regardless_of_config(tmp_path):
    _write_project_config(tmp_path, {"mypy": "on"})  # would otherwise be required
    out = _run(tmp_path, env={"CST_NO_EXTERNAL_TOOLS": "1"})
    assert "CST_NO_EXTERNAL_TOOLS is set" in out
    assert "Required by config but not installed" not in out
    disabled_block = out.split("Disabled by config")[1].split("CST_NO_EXTERNAL_TOOLS is set")[0]
    for tool in ("ruff", "mypy", "bandit", "gitleaks", "sqlfluff", "black", "shfmt"):
        assert tool in disabled_block


def test_installer_wide_default_applies_without_project_override(tmp_path):
    home = tmp_path / "home"
    (home / ".config" / "virt-surv-it").mkdir(parents=True)
    (home / ".config" / "virt-surv-it" / "installer.json").write_text(
        json.dumps({"default_review_tools": {"black": "off"}}), encoding="utf-8"
    )
    project = tmp_path / "project"
    project.mkdir()
    out = _run(project, env={"HOME": str(home), "XDG_CONFIG_HOME": str(home / ".config")})
    assert "Disabled by config" in out
    assert "black" in out.split("Disabled by config")[1].split("Artifact renderers")[0]


def test_project_override_wins_over_installer_wide_default(tmp_path):
    home = tmp_path / "home"
    (home / ".config" / "virt-surv-it").mkdir(parents=True)
    (home / ".config" / "virt-surv-it" / "installer.json").write_text(
        json.dumps({"default_review_tools": {"black": "off"}}), encoding="utf-8"
    )
    project = tmp_path / "project"
    _write_project_config(project, {"black": "auto"})
    out = _run(project, env={"HOME": str(home), "XDG_CONFIG_HOME": str(home / ".config")})
    # The project explicitly says "auto" for black - that must win over the machine
    # default of "off", so black is probed normally (present or in ordinary Missing).
    disabled_section = out.split("Disabled by config")[1] if "Disabled by config" in out else ""
    assert "black" not in disabled_section.split("Artifact renderers")[0]


def test_auto_tool_unaffected_by_config(tmp_path):
    """No config at all - every supported tool behaves exactly as before this feature."""
    out = _run(tmp_path)
    assert "Disabled by config" not in out
    assert "Required by config but not installed" not in out
