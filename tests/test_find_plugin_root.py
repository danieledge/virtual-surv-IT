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


def _write_probe_script(plugin_dir):
    """Usability (2026-08-17) also requires scripts/engage_probe.py at the root - a
    manifest or marker alone is a PARTIAL install that must fall through to the next
    resolver, not end the search."""
    (plugin_dir / "scripts").mkdir(parents=True, exist_ok=True)
    (plugin_dir / "scripts" / "engage_probe.py").write_text("# stub\n", encoding="utf-8")


def _make_usable(plugin_dir, name="compliance-surveillance-team@virtual-surv-it"):
    _write_manifest(plugin_dir, name)
    _write_probe_script(plugin_dir)


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
    _make_usable(plugin_dir)
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
    _make_usable(plugin_dir)
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
    _make_usable(cache)
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
        _make_usable(base / version)
    cwd = tmp_path / "project"
    cwd.mkdir()
    assert find_plugin_root(home, cwd) == str(base / "0.33.8")


def test_registry_takes_priority_over_filesystem_fallback(tmp_path):
    home = tmp_path / "home"
    registry_dir = tmp_path / "registry-wins"
    _make_usable(registry_dir)
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
    _make_usable(cache.parent)
    cwd = tmp_path / "project"
    cwd.mkdir()
    assert find_plugin_root(home, cwd) == str(registry_dir)


def test_no_install_found_anywhere_returns_empty(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    cwd = tmp_path / "project"
    cwd.mkdir()
    assert find_plugin_root(home, cwd) == ""


# --- 2026-08-17: local-path installs (corp live report - probe died with no root) ---------


def _team_root(tmp_path, name="clone"):
    root = tmp_path / name
    (root / ".claude-plugin").mkdir(parents=True)
    (root / ".claude-plugin" / "plugin.json").write_text(
        '{"name": "compliance-surveillance-team"}', encoding="utf-8"
    )
    # Usability requires the probe script too (2026-08-17): a manifest alone is a
    # PARTIAL install and must fall through, which test_partial_install below pins.
    (root / "scripts").mkdir()
    (root / "scripts" / "engage_probe.py").write_text("# stub\n", encoding="utf-8")
    return root


def test_env_seed_wins_for_local_path_installs(tmp_path, monkeypatch):
    """A local clone sits under neither the plugin cache nor marketplaces, and the
    registry filename drifts across Claude Code versions - CLAUDE_PLUGIN_ROOT (which
    plugin-mode hooks receive directly) is the one signal covering every install shape.
    Validated against the manifest, never trusted bare."""
    from scripts.find_plugin_root import find_plugin_root

    home = tmp_path / "home"
    home.mkdir()
    cwd = tmp_path / "some-client-project"
    cwd.mkdir()
    root = _team_root(tmp_path)
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(root))
    assert find_plugin_root(home, cwd) == str(root)


def test_env_seed_rejected_when_not_the_team_plugin(tmp_path, monkeypatch):
    from scripts.find_plugin_root import find_plugin_root

    home = tmp_path / "home"
    home.mkdir()
    cwd = tmp_path / "proj"
    cwd.mkdir()
    other = tmp_path / "other-plugin"
    (other / ".claude-plugin").mkdir(parents=True)
    (other / ".claude-plugin" / "plugin.json").write_text('{"name": "x"}', encoding="utf-8")
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(other))
    assert find_plugin_root(home, cwd) == ""  # falls through, nothing else to find


def test_registry_alternate_filenames_are_consulted(tmp_path, monkeypatch):
    import json as _json

    from scripts.find_plugin_root import find_plugin_root

    monkeypatch.delenv("CLAUDE_PLUGIN_ROOT", raising=False)
    home = tmp_path / "home"
    (home / ".claude" / "plugins").mkdir(parents=True)
    cwd = tmp_path / "proj"
    cwd.mkdir()
    root = _team_root(tmp_path)
    (home / ".claude" / "plugins" / "config.json").write_text(
        _json.dumps({"plugins": [{"installPath": str(root)}]}), encoding="utf-8"
    )
    assert find_plugin_root(home, cwd) == str(root)


def test_partial_registry_install_falls_through_to_a_usable_copy(tmp_path, monkeypatch):
    """The 2026-08-17 corp finding itself: the registry points at an install whose
    scripts/ is gone (a moved working copy, a broken update) - the OLD behaviour
    committed to it and the bootstrap died with no fallback. A partial candidate now
    falls through, and the healthy filesystem copy is found."""
    import json as _json

    from scripts.find_plugin_root import find_plugin_root

    monkeypatch.delenv("CLAUDE_PLUGIN_ROOT", raising=False)
    home = tmp_path / "home"
    broken = tmp_path / "moved-away"
    _write_manifest(broken)  # manifest only - no scripts/engage_probe.py
    (home / ".claude" / "plugins").mkdir(parents=True)
    (home / ".claude" / "plugins" / "installed_plugins.json").write_text(
        _json.dumps({"plugins": {"x": [{"installPath": str(broken)}]}}), encoding="utf-8"
    )
    healthy = home / ".claude" / "plugins" / "cache" / "compliance-surveillance-team" / "1.0.0"
    (healthy / "docs").mkdir(parents=True)
    (healthy / "docs" / "team-operating-guide.md").write_text("x", encoding="utf-8")
    _make_usable(healthy)
    cwd = tmp_path / "proj"
    cwd.mkdir()
    assert find_plugin_root(home, cwd) == str(healthy)
