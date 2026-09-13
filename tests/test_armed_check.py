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
