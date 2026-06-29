"""Tests for the plugin-manifest validator (scripts/validate_manifest.py)."""

from __future__ import annotations

from scripts.validate_manifest import _check


def test_repo_manifest_is_valid():
    """The shipped plugin.json must validate clean. Also a regression guard: re-adding the
    auto-loaded hooks/hooks.json to plugin.json (the 0.7.2 duplicate-hook bug) makes _check
    return a problem, so this test fails."""
    problems = _check()
    assert problems == [], f"manifest problems: {problems}"
