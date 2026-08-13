"""scripts/find_plugin_root.py: replaces a hand-typed, mixed-quote bash preamble in
engage-open.md (2026-08-04, live corp Windows report: "unexpected EOF while looking for
matching '"'" reproducing it) with a tested Python module. Covers both resolution methods
(install registry, filesystem fallback), their priority order, and repo-as-project."""

from __future__ import annotations

import json

from scripts.find_plugin_root import find_plugin_root


def _write_manifest(plugin_dir, name="compliance-surveillance-team@virtual-surv-it"):
    manifest_dir = plugin_dir / ".claude-plugin"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    (manifest_dir / "plugin.json").write_text(json.dumps({"name": name}), encoding="utf-8")


def test_repo_as_project_when_cwd_has_operating_guide(tmp_path):
    cwd = tmp_path / "repo"
    (cwd / "docs").mkdir(parents=True)
    (cwd / "docs" / "team-operating-guide.md").write_text("x", encoding="utf-8")
    home = tmp_path / "home"
    home.mkdir()
    assert find_plugin_root(home, cwd) == ""


def test_registry_resolves_real_world_nested_schema(tmp_path):
    """The real installed_plugins.json nests installPath under plugins.<key>[] - the
    resolver must not assume a flatter shape (schema-agnostic scan, see module docstring)."""
    home = tmp_path / "home"
    plugin_dir = tmp_path / "clone" / "virtual-surv-IT"
    _write_manifest(plugin_dir)
    registry = home / ".claude" / "plugins" / "installed_plugins.json"
    registry.parent.mkdir(parents=True)
    registry.write_text(
        json.dumps(
            {
                "version": 2,
                "plugins": {
                    "some-other-plugin@marketplace": [
                        {"installPath": str(tmp_path / "unrelated"), "scope": "user"}
                    ],
                    "compliance-surveillance-team@virtual-surv-it": [
                        {"installPath": str(plugin_dir), "scope": "user", "version": "0.33.8"}
                    ],
                },
            }
        ),
        encoding="utf-8",
    )
    cwd = tmp_path / "some_other_project"
    cwd.mkdir()
    assert find_plugin_root(home, cwd) == str(plugin_dir)


def test_registry_finds_a_locally_cloned_directory_not_named_after_the_plugin(tmp_path):
    """install_helper.py's own default clone dir is ~/virtual-surv-IT - no
    "compliance-surveillance-team" path segment at all, so only the registry method
    (matched by the manifest's own content) can find it, never the filesystem fallback."""
    home = tmp_path / "home"
    plugin_dir = tmp_path / "virtual-surv-IT"  # deliberately NOT containing the team name
    _write_manifest(plugin_dir)
    registry = home / ".claude" / "plugins" / "installed_plugins.json"
    registry.parent.mkdir(parents=True)
    registry.write_text(
        json.dumps({"plugins": {"x": [{"installPath": str(plugin_dir)}]}}), encoding="utf-8"
    )
    cwd = tmp_path / "some_other_project"
    cwd.mkdir()
    assert find_plugin_root(home, cwd) == str(plugin_dir)


def test_registry_entry_not_matching_plugin_name_is_skipped(tmp_path):
    home = tmp_path / "home"
    other_dir = tmp_path / "some-unrelated-plugin"
    _write_manifest(other_dir, name="some-unrelated-plugin@marketplace")
    registry = home / ".claude" / "plugins" / "installed_plugins.json"
    registry.parent.mkdir(parents=True)
    registry.write_text(
        json.dumps({"plugins": {"x": [{"installPath": str(other_dir)}]}}), encoding="utf-8"
    )
    cwd = tmp_path / "project"
    cwd.mkdir()
    assert find_plugin_root(home, cwd) == ""


def test_missing_or_malformed_registry_falls_through_without_raising(tmp_path):
    home = tmp_path / "home"  # no registry file at all
    cwd = tmp_path / "project"
    cwd.mkdir()
    assert find_plugin_root(home, cwd) == ""

    home2 = tmp_path / "home2"
    registry = home2 / ".claude" / "plugins" / "installed_plugins.json"
    registry.parent.mkdir(parents=True)
    registry.write_text("{not valid json", encoding="utf-8")
    assert find_plugin_root(home2, cwd) == ""


def test_filesystem_fallback_used_when_registry_has_no_match(tmp_path):
    home = tmp_path / "home"
    cache = home / ".claude" / "plugins" / "cache" / "compliance-surveillance-team" / "1.0.0"
    (cache / "docs").mkdir(parents=True)
    (cache / "docs" / "team-operating-guide.md").write_text("x", encoding="utf-8")
    cwd = tmp_path / "project"
    cwd.mkdir()
    assert find_plugin_root(home, cwd) == str(cache)


def test_filesystem_fallback_picks_the_newest_looking_version(tmp_path):
    home = tmp_path / "home"
    base = home / ".claude" / "plugins" / "cache" / "compliance-surveillance-team"
    for version in ("0.9.0", "0.33.8", "0.10.0"):
        d = base / version / "docs"
        d.mkdir(parents=True)
        (d / "team-operating-guide.md").write_text("x", encoding="utf-8")
    cwd = tmp_path / "project"
    cwd.mkdir()
    assert find_plugin_root(home, cwd) == str(base / "0.33.8")


def test_registry_takes_priority_over_filesystem_fallback(tmp_path):
    home = tmp_path / "home"
    registry_dir = tmp_path / "registry-wins"
    _write_manifest(registry_dir)
    registry = home / ".claude" / "plugins" / "installed_plugins.json"
    registry.parent.mkdir(parents=True)
    registry.write_text(
        json.dumps({"plugins": {"x": [{"installPath": str(registry_dir)}]}}), encoding="utf-8"
    )
    # ALSO plant a filesystem-fallback-discoverable copy - registry must win
    cache = (
        home / ".claude" / "plugins" / "cache" / "compliance-surveillance-team" / "9.9.9" / "docs"
    )
    cache.mkdir(parents=True)
    (cache / "team-operating-guide.md").write_text("x", encoding="utf-8")
    cwd = tmp_path / "project"
    cwd.mkdir()
    assert find_plugin_root(home, cwd) == str(registry_dir)


def test_no_install_found_anywhere_returns_empty(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    cwd = tmp_path / "project"
    cwd.mkdir()
    assert find_plugin_root(home, cwd) == ""
