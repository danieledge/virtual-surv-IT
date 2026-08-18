"""Vendored/third-party code and virtualenvs must never be swept into a review's scope
(live finding, 2026-08-10 Fable desk-review of the deep-review flow, confirmed against real
counts: vendor/ is 269 tracked files, 61% of all tracked Python lines). Nothing in the review
flow itself excluded them, and the analysers don't respect .gitignore, so pyproject.toml now
carries explicit excludes for ruff/bandit/mypy.

These are behavioral checks (the tools actually run), not just "the config key exists" -
ruff's `exclude`/`extend-exclude` alone do NOT cover an explicitly-passed path (only its own
discovery walk); that gap was found live here too (`ruff check vendor/` found 878 errors
until `force-exclude = true` was added) and is exactly what the first ruff test pins."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
VENDOR = REPO_ROOT / "vendor"

pytestmark = pytest.mark.skipif(not VENDOR.is_dir(), reason="vendor/ not present in this checkout")


@pytest.mark.skipif(shutil.which("ruff") is None, reason="ruff not installed")
def test_ruff_excludes_vendor_even_when_explicitly_targeted():
    """force-exclude is what makes this work - exclude/extend-exclude alone only apply to
    ruff's own discovery walk, not an explicitly-passed path (confirmed live: this exact
    invocation found 878 errors before force-exclude was added)."""
    proc = subprocess.run(
        ["ruff", "check", "vendor/"], cwd=REPO_ROOT, capture_output=True, text=True, timeout=60
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "error" not in proc.stdout.lower() or "no python files found" in proc.stdout.lower()


@pytest.mark.skipif(shutil.which("ruff") is None, reason="ruff not installed")
def test_ruff_whole_repo_scan_still_skips_vendor():
    proc = subprocess.run(
        ["ruff", "check", "."], cwd=REPO_ROOT, capture_output=True, text=True, timeout=120
    )
    assert "vendor/" not in proc.stdout


@pytest.mark.skipif(shutil.which("bandit") is None, reason="bandit not installed")
def test_bandit_excludes_vendor_even_when_explicitly_targeted():
    proc = subprocess.run(
        ["bandit", "-c", "pyproject.toml", "-r", "vendor/", "-q"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert "vendor/" not in proc.stdout


def test_pyproject_declares_the_three_excludes():
    """Belt-and-braces static check alongside the behavioral ones above - if a future edit
    strips the config keys entirely, this fails even on a box without ruff/bandit installed
    to run the real checks."""
    try:
        import tomllib
    except ModuleNotFoundError:  # pragma: no cover - Python < 3.11
        pytest.skip("tomllib not available (needs Python >= 3.11)")
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    ruff = data.get("tool", {}).get("ruff", {})
    assert "vendor" in ruff.get("extend-exclude", [])
    assert ruff.get("force-exclude") is True
    bandit = data.get("tool", {}).get("bandit", {})
    assert "vendor" in bandit.get("exclude_dirs", [])
    mypy = data.get("tool", {}).get("mypy", {})
    assert "vendor" in mypy.get("exclude", "")
