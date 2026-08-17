"""scripts/engage_probe.py: the step-0 open-time probe collapsed from an 18-line bash
compound the model had to reproduce verbatim into one tested script (audit finding
#5/#6/#8, 2026-07-30). Covers the pure computation - version-changed decision, map/changelog
parsing - the pieces where prose reproduction previously stood in for a mechanical check."""

from __future__ import annotations

import json

from scripts.engage_probe import (
    _ascii_safe,
    _cap_section3_rows,
    build_report,
    first_changelog_entry,
    last_team_version,
    map_drift_summary,
    read_machine_defaults,
    read_map,
    read_plugin_version,
    read_team_preferences,
    resolve_preferences,
    run_extensions_show,
    version_changed,
)

MAP_WITH_HISTORY = """# Codebase map

## 3. Engagement history

| Date | Engagement | Team ver | What was delivered | Key artifacts |
|------|-----------|----------|--------------------|---------------|
| 2026-07-01 | first-run | v0.33.0 | initial build | artifacts/x |
| 2026-07-20 | second-run | v0.33.1 | added Y | artifacts/y |

## 4. Open questions & watch items
Nothing here.
"""

MAP_TEMPLATE_ONLY = """# Codebase map

## 3. Engagement history

| Date | Engagement | Team ver | What was delivered | Key artifacts |
|------|-----------|----------|--------------------|---------------|
| <YYYY-MM-DD> | <slug> | <vX.Y.Z> | <one line> | <paths> |

## 4. Open questions & watch items
"""


def test_last_team_version_picks_most_recent_row():
    assert last_team_version(MAP_WITH_HISTORY) == "v0.33.1"


def test_last_team_version_ignores_template_placeholder_rows():
    assert last_team_version(MAP_TEMPLATE_ONLY) == ""


def test_last_team_version_empty_without_section_3():
    assert last_team_version("# Codebase map\n\nno history section\n") == ""


# --- §3 history capping (fable audit, 2026-08-03): one engagement close appends one row,
# forever, and the probe used to print the WHOLE table on every single open regardless of
# how old the project is - unbounded growth in a value paid on every engagement. -------


def _big_history_map(n_rows: int) -> str:
    rows = "\n".join(
        f"| 2026-07-{(i % 28) + 1:02d} | eng-{i} | v0.{i}.0 | delivered {i} | artifacts/eng-{i} |"
        for i in range(1, n_rows + 1)
    )
    return (
        "# Codebase map\n\n## 3. Engagement history\n\n"
        "| Date | Engagement | Team ver | What was delivered | Key artifacts |\n"
        "|------|-----------|----------|--------------------|---------------|\n"
        f"{rows}\n\n## 4. Open questions & watch items\nNothing here.\n"
    )


def test_cap_section3_rows_leaves_a_small_table_untouched(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "codebase-map.md").write_text(MAP_WITH_HISTORY, encoding="utf-8")
    _header, section3 = read_map(tmp_path)
    assert section3.count("| 2026-") == 2  # both rows kept, nothing capped
    assert "omitted" not in section3


def test_cap_section3_rows_pure_function_on_a_hand_built_table():
    section3 = _cap_section3_rows(_big_history_map(9).split("## 3. ", 1)[1])
    assert section3.count("| 2026-") == 5
    assert "4 earlier row(s) omitted" in section3


def test_cap_section3_rows_caps_a_large_table_to_the_last_rows(tmp_path):
    map_text = _big_history_map(20)
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "codebase-map.md").write_text(map_text, encoding="utf-8")
    _header, section3 = read_map(tmp_path)
    assert section3.count("| 2026-") == 5  # capped to the last 5, not all 20
    assert "eng-20" in section3  # the latest row survives
    assert "eng-1 " not in section3 and "eng-1\n" not in section3  # an old row is gone
    assert "15 earlier row(s) omitted" in section3
    # the one thing that actually needs the last row is unaffected by the cap
    assert last_team_version(section3) == "v0.20.0"


def test_version_changed_yes_when_different():
    assert version_changed("v0.34.0", "v0.33.1") == "yes"


def test_version_changed_no_when_identical_strings():
    assert version_changed("0.33.1", "0.33.1") == "no"


def test_version_changed_yes_on_first_engagement_no_prior_record():
    """No prior Team ver on record is 'first engagement' - always changed, never a
    silent 'no change' (the skill's own stated rule)."""
    assert version_changed("0.33.1", "") == "yes"


def test_version_changed_no_when_only_the_v_prefix_differs():
    """`plugin.json`'s version is always bare ('0.33.1'), but
    `docs/templates/codebase-map.md`'s own Team-ver placeholder is `<vX.Y.Z>` - WITH the
    prefix. A row written per the template's own convention must still read as "no change"
    for the same release, not "yes" forever (found 2026-08-03 while testing the
    changelog-gating fix, which depends on "no" ever actually firing)."""
    assert version_changed("0.33.1", "v0.33.1") == "no"
    assert version_changed("v0.33.1", "0.33.1") == "no"  # symmetric, either side prefixed


def test_version_changed_yes_when_different_even_with_v_prefix():
    assert version_changed("0.34.0", "v0.33.1") == "yes"


def test_version_changed_yes_when_plugin_version_unreadable(tmp_path):
    """M5 (2026-08 Fable audit): read_plugin_version() returns "" on any read/parse
    failure of plugin.json (unreadable, missing, corrupt) - an empty plugin_version with
    a real prior team version on record used to fall through to "no" (`plugin_version
    and ...` short-circuits false), silently indistinguishable from a confirmed
    same-version read and suppressing the what's-new banner on a genuine I/O failure
    rather than surfacing it."""
    assert version_changed("", "0.33.1") == "yes"


def test_first_changelog_entry_stops_at_second_release_header(tmp_path):
    root = tmp_path
    (root / "CHANGELOG.md").write_text(
        "# Changelog\n\n## [0.33.2] - 2026-07-30 - Latest\n\n- thing one\n- thing two\n\n"
        "## [0.33.1] - 2026-07-29 - Older\n\n- should not appear\n",
        encoding="utf-8",
    )
    entry = first_changelog_entry(root)
    assert "0.33.2" in entry
    assert "thing one" in entry
    assert "0.33.1" not in entry
    assert "should not appear" not in entry


def test_first_changelog_entry_empty_when_file_missing(tmp_path):
    assert first_changelog_entry(tmp_path) == ""


# --- changelog only printed when VERSION_CHANGED=yes (fable audit, 2026-08-03): the skill's
# own rule is "no -> show nothing", but the probe used to print the (up to 30-line) snippet
# into the transcript regardless, on every single open. ------------------------------------


def test_build_report_omits_changelog_when_version_unchanged(tmp_path):
    (tmp_path / ".claude-plugin").mkdir()
    (tmp_path / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({"version": "0.33.1"}), encoding="utf-8"
    )
    (tmp_path / "CHANGELOG.md").write_text(
        "## [0.33.1] - 2026-07-30 - Test\n\n- a distinctive marker line\n", encoding="utf-8"
    )
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "codebase-map.md").write_text(
        "# Codebase map\n\n## 3. Engagement history\n\n"
        "| Date | Engagement | Team ver | What was delivered | Key artifacts |\n"
        "|------|-----------|----------|--------------------|---------------|\n"
        "| 2026-07-30 | first-run | 0.33.1 | initial | artifacts/x |\n\n"
        "## 4. Open questions & watch items\nNothing here.\n",
        encoding="utf-8",
    )
    out = build_report("", tmp_path)
    assert "VERSION_CHANGED=no" in out
    assert "a distinctive marker line" not in out


def test_build_report_includes_changelog_when_version_changed(tmp_path):
    (tmp_path / ".claude-plugin").mkdir()
    (tmp_path / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({"version": "9.9.9"}), encoding="utf-8"
    )
    (tmp_path / "CHANGELOG.md").write_text(
        "## [9.9.9] - 2026-07-30 - Test\n\n- a distinctive marker line\n", encoding="utf-8"
    )
    out = build_report("", tmp_path)
    assert "VERSION_CHANGED=yes" in out  # no map at all - first engagement
    assert "a distinctive marker line" in out


def test_run_extensions_show_caps_script_output(tmp_path, monkeypatch):
    import scripts.engage_probe as ep

    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "team-extensions.md").write_text("# extensions", encoding="utf-8")
    root = tmp_path

    class _FakeProc:
        stdout = "x" * 5000

    monkeypatch.setattr(ep.subprocess, "run", lambda *a, **k: _FakeProc())
    # extensions.py doesn't need to exist for this path - subprocess.run is faked - but the
    # function checks .is_file() first, so give it a real (empty) file.
    (root / "scripts").mkdir(exist_ok=True)
    (root / "scripts" / "extensions.py").write_text("", encoding="utf-8")
    out = run_extensions_show(root, tmp_path)
    assert len(out) == 2000


def test_read_plugin_version_from_manifest(tmp_path):
    (tmp_path / ".claude-plugin").mkdir()
    (tmp_path / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({"version": "1.2.3"}), encoding="utf-8"
    )
    assert read_plugin_version(tmp_path) == "1.2.3"


def test_read_plugin_version_missing_manifest_is_empty(tmp_path):
    assert read_plugin_version(tmp_path) == ""


def test_read_team_preferences_defaults_when_absent(tmp_path):
    assert read_team_preferences(tmp_path) == {}


def test_read_team_preferences_reads_existing(tmp_path):
    claude = tmp_path / ".claude"
    claude.mkdir()
    (claude / "team-preferences.json").write_text(
        json.dumps({"extra_formats": ["docx"], "regulatory_citations": False}),
        encoding="utf-8",
    )
    prefs = read_team_preferences(tmp_path)
    assert prefs["extra_formats"] == ["docx"]
    assert prefs["regulatory_citations"] is False


# --- machine-default fallback (2026-08-05 user request: "project should default to    ---------
# --- machine default but can be overridden at project level") --------------------------------
# Every test here isolates HOME/XDG_CONFIG_HOME first - a project's ABSENCE of an explicit
# preference must fall back to a FAKE machine config, never the real one on the dev box (a
# real, live pollution incident in install_helper.py's own tests this same session is the
# reason this discipline is now non-negotiable).


def _isolate_home_for_probe(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))


def _write_machine_defaults(tmp_path, **kwargs):
    cfg_dir = tmp_path / "xdg" / "virt-surv-it"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "installer.json").write_text(json.dumps(kwargs), encoding="utf-8")


def test_read_machine_defaults_missing_file_is_empty_dict(tmp_path, monkeypatch):
    _isolate_home_for_probe(monkeypatch, tmp_path)
    assert read_machine_defaults() == {}


def test_read_machine_defaults_reads_existing(tmp_path, monkeypatch):
    _isolate_home_for_probe(monkeypatch, tmp_path)
    _write_machine_defaults(tmp_path, default_docx=True, default_regulatory_citations=False)
    defaults = read_machine_defaults()
    assert defaults["default_docx"] is True
    assert defaults["default_regulatory_citations"] is False


def test_build_report_falls_back_to_machine_default_when_project_unset(tmp_path, monkeypatch):
    """A project with NO team-preferences.json at all (never run Configure/Project
    preferences) must inherit this machine's default, not the hardcoded built-in one."""
    _isolate_home_for_probe(monkeypatch, tmp_path)
    _write_machine_defaults(tmp_path, default_docx=True, default_regulatory_citations=False)
    (tmp_path / ".claude-plugin").mkdir()
    (tmp_path / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({"version": "9.9.9"}), encoding="utf-8"
    )
    out = build_report("", tmp_path)
    assert "EXTRA_FORMATS=docx" in out
    assert "REGULATORY_CITATIONS=off" in out


def test_build_report_project_setting_overrides_machine_default(tmp_path, monkeypatch):
    """A project that HAS explicitly set its own preference (even matching the built-in
    default) must win over this machine's default - project scope always overrides."""
    _isolate_home_for_probe(monkeypatch, tmp_path)
    _write_machine_defaults(tmp_path, default_docx=True, default_regulatory_citations=False)
    (tmp_path / ".claude-plugin").mkdir()
    (tmp_path / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({"version": "9.9.9"}), encoding="utf-8"
    )
    claude = tmp_path / ".claude"
    claude.mkdir()
    (claude / "team-preferences.json").write_text(
        json.dumps({"extra_formats": [], "regulatory_citations": True}), encoding="utf-8"
    )
    out = build_report("", tmp_path)
    assert "EXTRA_FORMATS=" in out and "EXTRA_FORMATS=docx" not in out
    assert "REGULATORY_CITATIONS=on" in out


def test_build_report_falls_back_to_builtin_default_when_no_machine_config_either(
    tmp_path, monkeypatch
):
    """No project preference AND no machine config at all - the original hardcoded
    built-in default (docx off, citations on) still applies."""
    _isolate_home_for_probe(monkeypatch, tmp_path)
    (tmp_path / ".claude-plugin").mkdir()
    (tmp_path / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({"version": "9.9.9"}), encoding="utf-8"
    )
    out = build_report("", tmp_path)
    assert "EXTRA_FORMATS=" in out and "EXTRA_FORMATS=docx" not in out
    assert "REGULATORY_CITATIONS=on" in out


def test_resolve_preferences_returns_dict_matching_build_report(tmp_path, monkeypatch):
    """resolve_preferences() (extracted 2026-08-08 so engagement_state.init can snapshot
    it) must resolve the SAME precedence chain build_report()'s own EXTRA_FORMATS/
    REGULATORY_CITATIONS/etc. lines already prove - here checked as a structured dict
    rather than parsed text, since that's the shape init actually stores."""
    _isolate_home_for_probe(monkeypatch, tmp_path)
    _write_machine_defaults(tmp_path, default_docx=True, default_regulatory_citations=False)
    claude = tmp_path / ".claude"
    claude.mkdir()
    (claude / "team-preferences.json").write_text(
        json.dumps({"large_context_review_split": True}), encoding="utf-8"
    )
    resolved = resolve_preferences(tmp_path)
    assert resolved == {
        "extra_formats": ["docx"],  # machine default (project never set its own)
        "regulatory_citations": False,  # machine default
        "large_context_review_split": True,  # project override
        "parallel_dispatch_via_workflow": True,  # built-in default, no machine tier
        "standards_critique": False,  # built-in default, no machine tier
        "map_skeleton": False,  # built-in default
    }


def test_resolve_preferences_all_builtin_defaults_when_nothing_set(tmp_path, monkeypatch):
    _isolate_home_for_probe(monkeypatch, tmp_path)
    resolved = resolve_preferences(tmp_path)
    assert resolved == {
        "extra_formats": [],
        "regulatory_citations": True,
        "large_context_review_split": False,
        "parallel_dispatch_via_workflow": True,
        "standards_critique": False,
        "map_skeleton": False,
    }


def test_resolve_preferences_standards_critique_project_override(tmp_path, monkeypatch):
    """standards_critique has no machine-wide tier (mirrors parallel_dispatch_via_workflow's
    coverage above) - only an explicit project-level True turns it on."""
    _isolate_home_for_probe(monkeypatch, tmp_path)
    claude = tmp_path / ".claude"
    claude.mkdir()
    (claude / "team-preferences.json").write_text(
        json.dumps({"standards_critique": True}), encoding="utf-8"
    )
    resolved = resolve_preferences(tmp_path)
    assert resolved["standards_critique"] is True


def test_build_report_emits_standards_critique_on_when_set(tmp_path):
    (tmp_path / ".claude-plugin").mkdir()
    (tmp_path / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({"version": "9.9.9"}), encoding="utf-8"
    )
    (tmp_path / "CHANGELOG.md").write_text(
        "## [9.9.9] - 2026-07-30 - Test\n\n- a change\n", encoding="utf-8"
    )
    claude = tmp_path / ".claude"
    claude.mkdir()
    (claude / "team-preferences.json").write_text(
        json.dumps({"standards_critique": True}), encoding="utf-8"
    )
    out = build_report("", tmp_path)
    assert "STANDARDS_CRITIQUE=on" in out


def test_build_report_emits_all_fields_repo_as_project(tmp_path):
    (tmp_path / ".claude-plugin").mkdir()
    (tmp_path / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({"version": "9.9.9"}), encoding="utf-8"
    )
    (tmp_path / "CHANGELOG.md").write_text(
        "## [9.9.9] - 2026-07-30 - Test\n\n- a change\n", encoding="utf-8"
    )
    out = build_report("", tmp_path)
    assert "PLUGIN_ROOT=repo-as-project" in out
    assert "PLUGIN_VERSION=9.9.9" in out
    assert "VERSION_CHANGED=yes" in out  # no map at all - first engagement
    assert "REGULATORY_CITATIONS=on" in out  # default when no preferences file
    assert "LARGE_CONTEXT_REVIEW_SPLIT=off" in out  # default when no preferences file


def test_build_report_emits_large_context_review_split_on_when_set(tmp_path):
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    (claude_dir / "team-preferences.json").write_text(
        json.dumps({"large_context_review_split": True}), encoding="utf-8"
    )
    out = build_report("", tmp_path)
    assert "LARGE_CONTEXT_REVIEW_SPLIT=on" in out


def test_build_report_parallel_dispatch_via_workflow_on_by_default(tmp_path):
    out = build_report("", tmp_path)  # no preferences file at all
    assert "PARALLEL_DISPATCH_VIA_WORKFLOW=on" in out


def test_build_report_parallel_dispatch_via_workflow_off_when_disabled(tmp_path):
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    (claude_dir / "team-preferences.json").write_text(
        json.dumps({"parallel_dispatch_via_workflow": False}), encoding="utf-8"
    )
    out = build_report("", tmp_path)
    assert "PARALLEL_DISPATCH_VIA_WORKFLOW=off" in out


# --------------------------------- MAP_SKELETON (ADR-007 Phase 1 Chunk D, 3-tier precedence)


def test_build_report_map_skeleton_off_by_default(tmp_path):
    (tmp_path / ".claude-plugin").mkdir()
    (tmp_path / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({"version": "9.9.9"}), encoding="utf-8"
    )
    out = build_report("", tmp_path)
    assert "MAP_SKELETON=off" in out


def test_build_report_map_skeleton_on_via_project_preference(tmp_path):
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    (claude_dir / "team-preferences.json").write_text(
        json.dumps({"map_skeleton": True}), encoding="utf-8"
    )
    out = build_report("", tmp_path)
    assert "MAP_SKELETON=on" in out


def test_build_report_map_skeleton_falls_back_to_machine_default(tmp_path, monkeypatch):
    _isolate_home_for_probe(monkeypatch, tmp_path)
    _write_machine_defaults(tmp_path, default_map_skeleton=True)
    (tmp_path / ".claude-plugin").mkdir()
    (tmp_path / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({"version": "9.9.9"}), encoding="utf-8"
    )
    out = build_report("", tmp_path)
    assert "MAP_SKELETON=on" in out


def test_build_report_map_skeleton_project_false_overrides_machine_true(tmp_path, monkeypatch):
    _isolate_home_for_probe(monkeypatch, tmp_path)
    _write_machine_defaults(tmp_path, default_map_skeleton=True)
    (tmp_path / ".claude-plugin").mkdir()
    (tmp_path / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({"version": "9.9.9"}), encoding="utf-8"
    )
    claude = tmp_path / ".claude"
    claude.mkdir()
    (claude / "team-preferences.json").write_text(
        json.dumps({"map_skeleton": False}), encoding="utf-8"
    )
    out = build_report("", tmp_path)
    assert "MAP_SKELETON=off" in out


# --------------------------------------- MAP_DRIFT (open-time, 2026-08-07 user request)
# "wouldn't it make sense to run [the drift check] first and feed that info into the
# agents" - minimal, standalone (root map only) duplicate of check_map()'s MAP-DRIFT
# subset, so it's available at OPEN, not just close.


def _map_with_paths(area="rules", paths="src/x.py", entry="threshold rationale"):
    return (
        "# Codebase Map - Proj\n\n"
        "> **Document control** · Owner `Morgan (PM)` · As-of `2026-07-18` · Anchor `no-vcs`\n\n"
        "## 2. Map entries\n\n"
        "| # | Area | Entry | Basis | As-of | Anchor | Paths |\n"
        "|---|------|-------|-------|-------|--------|-------|\n"
        f"| 1 | {area} | {entry} | 📊 seen in review | 2026-07-18 | no-vcs | {paths} |\n"
    )


def _write_sidecar(map_dir, entries):
    map_dir.mkdir(parents=True, exist_ok=True)
    (map_dir / "codebase-map.fingerprints.json").write_text(
        json.dumps({"generated_by": "test", "entries": entries}), encoding="utf-8"
    )


def test_map_drift_summary_empty_when_toggle_off(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "codebase-map.md").write_text(_map_with_paths(), encoding="utf-8")
    assert map_drift_summary(tmp_path, map_skeleton_on=False) == ""


def test_map_drift_summary_empty_when_no_map(tmp_path):
    assert map_drift_summary(tmp_path, map_skeleton_on=True) == ""


def test_map_drift_summary_empty_when_never_fingerprinted_matches_fingerprint(tmp_path):
    """No sidecar at all still counts as drifted (never fingerprinted), same as
    check_map()'s own MAP-DRIFT precedent."""
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "codebase-map.md").write_text(_map_with_paths(), encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "x.py").write_text("threshold = 1\n", encoding="utf-8")
    summary = map_drift_summary(tmp_path, map_skeleton_on=True)
    assert "1 of 1 area(s): rules" in summary


def test_map_drift_summary_silent_when_fingerprint_matches(tmp_path):
    from scripts.map_fingerprint import compute_fingerprint

    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "codebase-map.md").write_text(_map_with_paths(), encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "x.py").write_text("threshold = 1\n", encoding="utf-8")
    _write_sidecar(
        tmp_path / "docs",
        {
            "rules": {
                "paths": ["src/x.py"],
                "fingerprint": compute_fingerprint(["src/x.py"], tmp_path),
            }
        },
    )
    assert map_drift_summary(tmp_path, map_skeleton_on=True) == ""


def test_map_drift_summary_fires_when_file_changed_since_fingerprinted(tmp_path):
    from scripts.map_fingerprint import compute_fingerprint

    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "codebase-map.md").write_text(_map_with_paths(), encoding="utf-8")
    (tmp_path / "src").mkdir()
    f = tmp_path / "src" / "x.py"
    f.write_text("threshold = 1\n", encoding="utf-8")
    _write_sidecar(
        tmp_path / "docs",
        {
            "rules": {
                "paths": ["src/x.py"],
                "fingerprint": compute_fingerprint(["src/x.py"], tmp_path),
            }
        },
    )
    f.write_text("threshold = 2\n", encoding="utf-8")  # changed AFTER fingerprinting
    summary = map_drift_summary(tmp_path, map_skeleton_on=True)
    assert "1 of 1 area(s): rules" in summary


def test_map_drift_summary_reuses_cached_fingerprint_when_file_unchanged(tmp_path, monkeypatch):
    """M5 (2026-08-14 perf audit): a second call against an UNCHANGED file must not
    re-read or re-hash its content - the (path, mtime, size) shortcut cache must skip
    straight to the cached fingerprint. Proven by counting real
    _compute_fingerprint_probe calls: one on the first (cold-cache) call, ZERO on the
    second."""
    import scripts.engage_probe as ep

    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "codebase-map.md").write_text(_map_with_paths(), encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "x.py").write_text("threshold = 1\n", encoding="utf-8")

    calls = {"n": 0}
    real_compute = ep._compute_fingerprint_probe

    def counting_compute(globs, repo_root):
        calls["n"] += 1
        return real_compute(globs, repo_root)

    monkeypatch.setattr(ep, "_compute_fingerprint_probe", counting_compute)

    ep.map_drift_summary(tmp_path, map_skeleton_on=True)
    assert calls["n"] == 1, "first call (cold cache) must compute for real"

    ep.map_drift_summary(tmp_path, map_skeleton_on=True)
    assert calls["n"] == 1, (
        "second call against an unchanged file must reuse the cached fingerprint, not recompute"
    )


def test_map_drift_summary_cache_produces_the_same_fingerprint_as_a_fresh_compute(tmp_path):
    """Correctness, not just the call count: the cached path's OWN comparison against
    codebase-map.fingerprints.json must behave identically to the uncached path - a
    real DoD-style fixture (sidecar written via scripts.map_fingerprint.compute_fingerprint
    directly) that is silent on the first call must STAY silent on a second call once
    the shortcut cache is warm."""
    from scripts.map_fingerprint import compute_fingerprint

    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "codebase-map.md").write_text(_map_with_paths(), encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "x.py").write_text("threshold = 1\n", encoding="utf-8")
    _write_sidecar(
        tmp_path / "docs",
        {
            "rules": {
                "paths": ["src/x.py"],
                "fingerprint": compute_fingerprint(["src/x.py"], tmp_path),
            }
        },
    )
    assert map_drift_summary(tmp_path, map_skeleton_on=True) == ""
    assert map_drift_summary(tmp_path, map_skeleton_on=True) == ""  # warm-cache path agrees


def test_map_drift_summary_cache_invalidates_on_mtime_change(tmp_path, monkeypatch):
    """The mtime half of the correctness constraint: content that actually changed,
    with a real mtime bump (the ordinary case), must still be detected as drift even
    once the shortcut cache is warm."""
    import scripts.engage_probe as ep

    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "codebase-map.md").write_text(_map_with_paths(), encoding="utf-8")
    (tmp_path / "src").mkdir()
    f = tmp_path / "src" / "x.py"
    f.write_text("threshold = 1\n", encoding="utf-8")

    calls = {"n": 0}
    real_compute = ep._compute_fingerprint_probe

    def counting_compute(globs, repo_root):
        calls["n"] += 1
        return real_compute(globs, repo_root)

    monkeypatch.setattr(ep, "_compute_fingerprint_probe", counting_compute)

    first = ep.map_drift_summary(tmp_path, map_skeleton_on=True)
    assert calls["n"] == 1

    f.write_text("threshold = 2\n", encoding="utf-8")  # real write - mtime moves forward
    second = ep.map_drift_summary(tmp_path, map_skeleton_on=True)
    assert calls["n"] == 2, "a changed file must invalidate the cache and recompute for real"
    assert first == second == "1 of 1 area(s): rules"  # never fingerprinted -> always drifted


def test_map_drift_summary_cache_invalidates_on_size_change_with_unchanged_mtime(
    tmp_path, monkeypatch
):
    """The size half of the correctness constraint, explicitly required by the finding:
    a filesystem that doesn't move mtime on some writes, or a truncated file with an
    unchanged mtime, must still be caught - by the size check, since mtime alone would
    silently miss it. os.utime pins the mtime identical across the edit so only a size
    difference can possibly explain a detected change."""
    import os

    import scripts.engage_probe as ep
    from scripts.map_fingerprint import compute_fingerprint

    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "codebase-map.md").write_text(_map_with_paths(), encoding="utf-8")
    (tmp_path / "src").mkdir()
    f = tmp_path / "src" / "x.py"
    f.write_text("threshold = 100\n", encoding="utf-8")
    _write_sidecar(
        tmp_path / "docs",
        {
            "rules": {
                "paths": ["src/x.py"],
                "fingerprint": compute_fingerprint(["src/x.py"], tmp_path),
            }
        },
    )
    pinned_mtime = f.stat().st_mtime
    assert ep.map_drift_summary(tmp_path, map_skeleton_on=True) == ""  # warms the cache, silent

    f.write_text("t=1\n", encoding="utf-8")  # shorter content, different size
    os.utime(f, (pinned_mtime, pinned_mtime))  # ...but mtime pinned identical to before

    summary = ep.map_drift_summary(tmp_path, map_skeleton_on=True)
    assert "1 of 1 area(s): rules" in summary, (
        "a size change with an unchanged mtime must still invalidate the shortcut cache"
    )


def test_map_drift_summary_empty_when_no_paths_column(tmp_path):
    (tmp_path / "docs").mkdir()
    # Same shape as _good_map (test_check_artifacts.py) - no Paths column at all.
    (tmp_path / "docs" / "codebase-map.md").write_text(
        "# Codebase Map\n\n"
        "> As-of `2026-07-18` · Anchor `no-vcs`\n\n"
        "## 2. Map entries\n\n"
        "| # | Area | Entry | Basis | As-of | Anchor |\n"
        "|---|------|-------|-------|-------|--------|\n"
        "| 1 | rules | threshold rationale | 📊 seen in review | 2026-07-18 | no-vcs |\n",
        encoding="utf-8",
    )
    assert map_drift_summary(tmp_path, map_skeleton_on=True) == ""


def test_build_report_includes_map_drift_line_when_drifted(tmp_path):
    (tmp_path / ".claude-plugin").mkdir()
    (tmp_path / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({"version": "9.9.9"}), encoding="utf-8"
    )
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    (claude_dir / "team-preferences.json").write_text(
        json.dumps({"map_skeleton": True}), encoding="utf-8"
    )
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "codebase-map.md").write_text(_map_with_paths(), encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "x.py").write_text("threshold = 1\n", encoding="utf-8")
    out = build_report("", tmp_path)
    assert "MAP_DRIFT=1 of 1 area(s): rules" in out


def test_build_report_omits_map_drift_line_when_toggle_off(tmp_path):
    """Off means zero added output - no MAP_DRIFT line at all, not an empty one, even
    with a real drift condition sitting on disk."""
    (tmp_path / ".claude-plugin").mkdir()
    (tmp_path / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({"version": "9.9.9"}), encoding="utf-8"
    )
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "codebase-map.md").write_text(_map_with_paths(), encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "x.py").write_text("threshold = 1\n", encoding="utf-8")
    out = build_report("", tmp_path)
    assert "MAP_SKELETON=off" in out
    assert "MAP_DRIFT=" not in out


def test_build_report_omits_map_drift_line_when_nothing_drifted(tmp_path):
    from scripts.map_fingerprint import compute_fingerprint

    (tmp_path / ".claude-plugin").mkdir()
    (tmp_path / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({"version": "9.9.9"}), encoding="utf-8"
    )
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    (claude_dir / "team-preferences.json").write_text(
        json.dumps({"map_skeleton": True}), encoding="utf-8"
    )
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "codebase-map.md").write_text(_map_with_paths(), encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "x.py").write_text("threshold = 1\n", encoding="utf-8")
    _write_sidecar(
        tmp_path / "docs",
        {
            "rules": {
                "paths": ["src/x.py"],
                "fingerprint": compute_fingerprint(["src/x.py"], tmp_path),
            }
        },
    )
    out = build_report("", tmp_path)
    assert "MAP_DRIFT=" not in out


def test_build_report_emits_os_windows(monkeypatch, tmp_path):
    # Live report 2026-08-03: the exec-consent command was given as the `!` form alone on
    # a Windows host, because nothing put "this is Windows" in front of the model as a
    # fact - it had to infer it from context. OS= exists so it never has to.
    import scripts.engage_probe as ep

    monkeypatch.setattr(ep.sys, "platform", "win32")
    out = build_report("", tmp_path)
    assert "OS=Windows" in out


def test_build_report_emits_os_posix(monkeypatch, tmp_path):
    import scripts.engage_probe as ep

    monkeypatch.setattr(ep.sys, "platform", "linux")
    out = build_report("", tmp_path)
    assert "OS=POSIX" in out


def test_build_report_never_raises_on_totally_empty_project(tmp_path):
    out = build_report("", tmp_path)
    assert "PLUGIN_ROOT=repo-as-project" in out
    assert "PLUGIN_VERSION=" in out


def test_build_report_never_embeds_the_operating_guide(tmp_path):
    """Live report 2026-07-31: build_report used to inline up to 400 lines
    (~32KB in this repo) of docs/team-operating-guide.md into its own stdout, large
    enough to trip the harness's own "output too large - written to a file" behavior.
    Pure duplication too - the engage skill already has its own separate, explicit
    "read docs/team-operating-guide.md" instruction (SKILL.md), so the model was
    receiving the same content twice. Report size must stay small regardless of how
    large the real guide file is."""
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "team-operating-guide.md").write_text(
        "UNIQUE-GUIDE-MARKER\n" * 500, encoding="utf-8"
    )
    out = build_report("", tmp_path)
    assert "UNIQUE-GUIDE-MARKER" not in out
    assert len(out) < 5000


def test_git_branch_reports_real_clone(tmp_path):
    import subprocess

    from scripts.engage_probe import git_branch

    subprocess.run(["git", "init", "-q", "-b", "dev", str(tmp_path)], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(tmp_path),
            "-c",
            "user.email=t@t.com",
            "-c",
            "user.name=t",
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            "x",
        ],
        check=True,
    )
    assert git_branch(tmp_path) == "dev"


def test_git_branch_empty_without_git_at_all(tmp_path):
    """The common plugin-cache case: a plain file copy, no .git directory - never guess."""
    from scripts.engage_probe import git_branch

    assert git_branch(tmp_path) == ""


def test_subprocess_calls_never_use_bare_text_true(monkeypatch, tmp_path):
    """Regression pin, live corp report 2026-08-12: plain text=True decodes subprocess
    output using the PARENT's locale-preferred encoding (cp1252 on a plain Windows
    console), whose undefined bytes raise UnicodeDecodeError inside subprocess's own
    reader thread ("Exception in Thread-N (_readerthread)", visible on the console as a
    dangling traceback from threading.py). install_helper.py's run_cmd hit and fixed the
    identical failure mode on 2026-07-30, but git_branch/run_tool_probe/
    run_extensions_show are independent of run_cmd (this script runs standalone without
    importing install_helper - see _find_bash's own docstring) and hadn't been fixed the
    same way - all three must pass encoding="utf-8", errors="replace" instead."""
    from types import SimpleNamespace

    import scripts.engage_probe as ep

    calls = []

    def fake_run(*a, **k):
        calls.append(k)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(ep.subprocess, "run", fake_run)

    (tmp_path / ".git").mkdir()
    ep.git_branch(tmp_path)

    (tmp_path / "scripts").mkdir(exist_ok=True)
    (tmp_path / "scripts" / "check-review-tools.sh").write_text("", encoding="utf-8")
    ep.run_tool_probe(tmp_path, tmp_path)

    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "team-extensions.md").write_text("# x", encoding="utf-8")
    (tmp_path / "scripts" / "extensions.py").write_text("", encoding="utf-8")
    ep.run_extensions_show(tmp_path, tmp_path)

    assert len(calls) == 3  # every candidate above must actually have reached subprocess.run
    for kwargs in calls:
        assert kwargs.get("text") is not True
        assert kwargs.get("encoding") == "utf-8"
        assert kwargs.get("errors") == "replace"


def test_git_branch_empty_on_detached_head(tmp_path, monkeypatch):
    from types import SimpleNamespace

    import scripts.engage_probe as ep

    (tmp_path / ".git").mkdir()
    monkeypatch.setattr(
        ep.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=0, stdout="HEAD\n", stderr=""),
    )
    assert ep.git_branch(tmp_path) == ""


def test_build_report_includes_branch_field(tmp_path):
    out = build_report("", tmp_path)
    assert "BRANCH=" in out


def test_interpreter_name_echoed_when_given(tmp_path, capsys):
    from scripts.engage_probe import main

    import sys as _sys

    old_argv = _sys.argv
    try:
        _sys.argv = [
            "engage_probe.py",
            "--project-dir",
            str(tmp_path),
            "--interpreter-name",
            "python3",
        ]
        main()
    finally:
        _sys.argv = old_argv
    out = capsys.readouterr().out
    assert out.startswith("INTERPRETER=python3\n")


def test_no_interpreter_line_when_flag_omitted(tmp_path, capsys):
    from scripts.engage_probe import main

    import sys as _sys

    old_argv = _sys.argv
    try:
        _sys.argv = ["engage_probe.py", "--project-dir", str(tmp_path)]
        main()
    finally:
        _sys.argv = old_argv
    assert "INTERPRETER=" not in capsys.readouterr().out


# ------------------------------------------------ ASCII-safe stdout (2026-08-04)
# Live corp report: a Windows cp1252 console raised UnicodeDecodeError capturing the
# probe's stdout through Claude Code's Bash tool, even with PYTHONIOENCODING=utf-8 set
# for this process - that env var controls how THIS process encodes ITS OWN stdout,
# not how the downstream shell-capture pipe decodes the bytes back into text. Fix:
# never let a non-ASCII byte leave the process at all.


def test_ascii_safe_substitutes_known_repo_glyphs():
    text = "🎩 Morgan: 📊 observed, 🧠 inferred, next → then, done ✓, missing ✗"
    out = _ascii_safe(text)
    assert (
        out
        == "[Morgan] Morgan: [observed] observed, [inferred] inferred, next -> then, done [x], missing [ ]"
    )
    out.encode("ascii")  # must not raise


def test_ascii_safe_falls_back_to_generic_replace_for_unknown_glyphs():
    # An arbitrary unicode character from a user-edited project file, not in the
    # known-glyph map - must still come out pure ASCII, not raise or pass through.
    out = _ascii_safe("café 中文 \U0001f600")
    out.encode("ascii")  # must not raise
    assert "é" not in out and "中" not in out


def test_build_report_output_is_always_pure_ascii(tmp_path, capsys):
    """End-to-end: even with emoji-laden project files, main()'s actual stdout must be
    encodable as plain ASCII - the exact property the Windows console needs."""
    from scripts.engage_probe import main

    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "codebase-map.md").write_text(
        "# Codebase map\n\n📊 observed: this project uses 🧠 inferred logic\n\n"
        "## 3. History\n\n| Date | Note | Team-ver |\n|---|---|---|\n"
        "| 2026-08-04 | note | v1.0.0 |\n",
        encoding="utf-8",
    )
    (tmp_path / "CHANGELOG.md").write_text(
        "## [1.0.0] - 2026-08-04 - release\n\n🎩 Morgan says hi →\n", encoding="utf-8"
    )

    import sys as _sys

    old_argv = _sys.argv
    try:
        _sys.argv = ["engage_probe.py", "--project-dir", str(tmp_path)]
        main()
    finally:
        _sys.argv = old_argv
    out = capsys.readouterr().out
    out.encode("ascii")  # the property the fix exists to guarantee - must not raise


def test_find_bash_prefers_path(monkeypatch):
    import scripts.engage_probe as ep

    monkeypatch.setattr(ep.shutil, "which", lambda n: "/usr/bin/bash" if n == "bash" else None)
    assert ep._find_bash() == "/usr/bin/bash"


def test_find_bash_falls_back_to_git_root_on_windows(monkeypatch, tmp_path):
    import scripts.engage_probe as ep

    git_root = tmp_path / "Git"
    (git_root / "bin").mkdir(parents=True)
    (git_root / "bin" / "bash.exe").write_text("", encoding="utf-8")
    git_exe = git_root / "cmd" / "git.exe"
    git_exe.parent.mkdir(parents=True)
    git_exe.write_text("", encoding="utf-8")
    monkeypatch.setattr(ep.sys, "platform", "win32")
    monkeypatch.setattr(ep.shutil, "which", lambda n: str(git_exe) if n == "git" else None)
    assert ep._find_bash() == str(git_root / "bin" / "bash.exe")


# ------------------------------------------------------ tool-probe cache fast path (P3)


def test_resolve_root_trusts_an_explicit_plugin_root(tmp_path):
    import scripts.engage_probe as ep

    root, display, trusted = ep.resolve_root(str(tmp_path), tmp_path / "project")
    assert root == tmp_path
    assert display == str(tmp_path)
    assert trusted is True


def test_resolve_root_trusts_repo_as_project_when_manifest_names_the_team(tmp_path):
    """The genuine dogfood case: no --plugin-root, but project_dir's own plugin.json
    identifies it as the team repo - the check the old docstring claimed but the code
    never actually made."""
    import scripts.engage_probe as ep

    plugin_dir = tmp_path / ".claude-plugin"
    plugin_dir.mkdir()
    (plugin_dir / "plugin.json").write_text(
        '{"name": "compliance-surveillance-team"}', encoding="utf-8"
    )
    root, display, trusted = ep.resolve_root("", tmp_path)
    assert root == tmp_path
    assert display == "repo-as-project"
    assert trusted is True


def test_resolve_root_does_not_trust_an_unverified_foreign_project(tmp_path):
    """2026-08-14 Fable-model audit finding (C1): no --plugin-root AND the project
    does not look like the team repo - resolution genuinely failed. root still falls
    back to project_dir (nothing better available for display/version reads), but
    trusted must be False - this is the exact condition run_tool_probe/
    run_extensions_show must refuse to execute anything under root for."""
    import scripts.engage_probe as ep

    root, display, trusted = ep.resolve_root("", tmp_path)
    assert root == tmp_path
    assert display == "repo-as-project"
    assert trusted is False


def test_run_tool_probe_never_executes_an_untrusted_roots_script(tmp_path):
    """The actual fix, proven directly: even though root == project_dir in the
    untrusted-resolution shape (exactly what a failed resolve_root call produces), a
    planted check-review-tools.sh must never run when root_is_trusted is False."""
    import scripts.engage_probe as ep

    marker = tmp_path / "pwned-by-review"
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    planted = scripts_dir / "check-review-tools.sh"
    planted.write_text(f"#!/bin/sh\ntouch {marker}\n", encoding="utf-8")
    planted.chmod(0o755)

    out = ep.run_tool_probe(tmp_path, tmp_path, root_is_trusted=False)
    assert out == ""
    assert not marker.exists()


def test_run_tool_probe_still_works_normally_when_root_is_trusted(tmp_path):
    """Confirms the fix didn't just make this function always refuse - a genuinely
    trusted root (the default, matching every pre-existing caller) still probes."""
    import scripts.engage_probe as ep

    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    real = scripts_dir / "check-review-tools.sh"
    real.write_text("#!/bin/sh\necho real-output\n", encoding="utf-8")
    real.chmod(0o755)

    out = ep.run_tool_probe(tmp_path, tmp_path, root_is_trusted=True)
    assert "real-output" in out


def test_run_extensions_show_never_executes_an_untrusted_roots_script(tmp_path):
    """Same fix, same shape, for extensions.py - a planted scripts/extensions.py must
    never run when root_is_trusted is False, even though the project genuinely has a
    docs/team-extensions.md (the only gate that currently exists on this path)."""
    import scripts.engage_probe as ep

    marker = tmp_path / "pwned-by-extensions"
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "team-extensions.md").write_text("# Extensions\nreal markdown\n", encoding="utf-8")
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    planted = scripts_dir / "extensions.py"
    planted.write_text(
        f"import pathlib; pathlib.Path({str(marker)!r}).touch()\nprint('pwned')\n",
        encoding="utf-8",
    )

    out = ep.run_extensions_show(tmp_path, tmp_path, root_is_trusted=False)
    assert "real markdown" in out
    assert "pwned" not in out
    assert not marker.exists()


def test_run_tool_probe_reads_fresh_cache_without_spawning_bash(monkeypatch, tmp_path):
    """A warm cache must be read directly - no Git Bash spawn at all (live Windows corp
    report 2026-07-31: the subprocess spawn alone cost ~2.2s on every warm /engage, even
    though check-review-tools.sh's own cache-hit branch does no real work)."""
    import subprocess as sp

    import scripts.engage_probe as ep

    (tmp_path / ".claude").mkdir()
    cache = tmp_path / ".claude" / ".tool-availability"
    cache.write_text("=== Review/perf tooling check ===\nChecked: 2026-07-31\n\nbody\n")
    monkeypatch.setattr(
        sp, "run", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not spawn"))
    )
    out = ep.run_tool_probe(tmp_path, tmp_path)
    assert "body" in out
    assert "(cached - from a probe within the last 7 day(s)" in out
    assert "ALLOWLIST:" in out


def test_run_tool_probe_falls_through_on_stale_cache(monkeypatch, tmp_path):
    """A cache past its TTL must fall through to the real script, not serve stale data
    forever."""
    import os as _os
    import time as _time

    import scripts.engage_probe as ep

    (tmp_path / ".claude").mkdir()
    cache = tmp_path / ".claude" / ".tool-availability"
    cache.write_text("stale body\n")
    old = _time.time() - 8 * 86400  # default TTL is 7 days
    _os.utime(cache, (old, old))
    assert ep._read_cached_tool_probe(tmp_path) is None


def test_run_tool_probe_falls_through_when_no_cache(tmp_path):
    import scripts.engage_probe as ep

    assert ep._read_cached_tool_probe(tmp_path) is None


def test_read_cached_tool_probe_honours_ttl_env_override(monkeypatch, tmp_path):
    import os as _os
    import time as _time

    import scripts.engage_probe as ep

    (tmp_path / ".claude").mkdir()
    cache = tmp_path / ".claude" / ".tool-availability"
    cache.write_text("body\n")
    two_days_ago = _time.time() - 2 * 86400
    _os.utime(cache, (two_days_ago, two_days_ago))
    monkeypatch.setenv("CST_TOOLCHECK_TTL_DAYS", "1")
    assert ep._read_cached_tool_probe(tmp_path) is None  # stale under the shorter TTL
    monkeypatch.setenv("CST_TOOLCHECK_TTL_DAYS", "7")
    assert ep._read_cached_tool_probe(tmp_path) is not None  # fresh under the longer TTL


def test_allowlist_line_detects_present_entry(tmp_path):
    import scripts.engage_probe as ep

    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "settings.json").write_text(
        '{"permissions": {"allow": ["Bash(python3 -m scripts.*)"]}}', encoding="utf-8"
    )
    assert ep._allowlist_line(tmp_path) == "ALLOWLIST: present"


def test_allowlist_line_missing_without_settings(tmp_path):
    import scripts.engage_probe as ep

    assert "ALLOWLIST: missing" in ep._allowlist_line(tmp_path)


# --- integrations (2026-08-17, docs/INTEGRATIONS.md) - off by default at every level ------


def _write_prefs(tmp_path, payload: dict) -> None:
    d = tmp_path / ".claude"
    d.mkdir(parents=True, exist_ok=True)
    (d / "team-preferences.json").write_text(json.dumps(payload), encoding="utf-8")


def test_integrations_default_entirely_off_and_line_absent(tmp_path):
    from scripts.engage_probe import integrations_report_line, resolve_integrations

    resolved = resolve_integrations(tmp_path)  # no prefs file at all
    assert resolved["jira"]["enabled"] is False
    assert resolved["pr_comments"]["enabled"] is False
    assert integrations_report_line(resolved) == ""  # absent line = zero context cost


def test_integrations_malformed_block_resolves_off_never_guesses(tmp_path):
    from scripts.engage_probe import integrations_report_line, resolve_integrations

    for bad in ("a string", 42, {"jira": "yes"}, {"jira": {"enabled": "true"}}):
        _write_prefs(tmp_path, {"integrations": bad})
        resolved = resolve_integrations(tmp_path)
        assert resolved["jira"]["enabled"] is False, bad
        assert integrations_report_line(resolved) == "", bad


def test_jira_opt_in_resolves_with_defaults_and_reports(tmp_path):
    from scripts.engage_probe import integrations_report_line, resolve_integrations

    _write_prefs(
        tmp_path,
        {"integrations": {"jira": {"enabled": True, "project_key": "SURV"}}},
    )
    resolved = resolve_integrations(tmp_path)
    jira = resolved["jira"]
    assert jira["enabled"] is True
    assert jira["mirror"] == "close-only"  # live is opt-in on top of opt-in
    assert jira["tool_prefix"] == "mcp__atlassian"
    line = integrations_report_line(resolved)
    assert line.startswith("INTEGRATIONS=jira:on(close-only,key=SURV,")


def test_jira_missing_project_key_is_surfaced_never_silent(tmp_path):
    from scripts.engage_probe import integrations_report_line, resolve_integrations

    _write_prefs(tmp_path, {"integrations": {"jira": {"enabled": True}}})
    assert "key=UNSET" in integrations_report_line(resolve_integrations(tmp_path))


def test_pr_comments_double_gate(tmp_path, monkeypatch):
    """Experimental: config alone must NOT enable it - the launch-env flag is the second
    gate, and configured-but-locked is surfaced, not silently off."""
    from scripts.engage_probe import integrations_report_line, resolve_integrations

    _write_prefs(tmp_path, {"integrations": {"pr_comments": {"enabled": True}}})
    monkeypatch.delenv("CST_ENABLE_PR_COMMENTS", raising=False)
    resolved = resolve_integrations(tmp_path)
    assert resolved["pr_comments"]["enabled"] is False
    assert resolved["pr_comments"]["locked"] is True
    assert "pr-comments:locked" in integrations_report_line(resolved)

    monkeypatch.setenv("CST_ENABLE_PR_COMMENTS", "1")
    resolved = resolve_integrations(tmp_path)
    assert resolved["pr_comments"]["enabled"] is True
    assert "pr-comments:on(EXPERIMENTAL" in integrations_report_line(resolved)


def test_build_report_carries_integrations_line_only_when_on(tmp_path, monkeypatch):
    from scripts.engage_probe import build_report

    monkeypatch.delenv("CST_ENABLE_PR_COMMENTS", raising=False)
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "team-operating-guide.md").write_text("# ops\n", encoding="utf-8")
    out = build_report("", tmp_path)
    assert "INTEGRATIONS=" not in out
    _write_prefs(
        tmp_path,
        {"integrations": {"jira": {"enabled": True, "project_key": "SURV"}}},
    )
    out = build_report("", tmp_path)
    assert "INTEGRATIONS=jira:on(close-only,key=SURV," in out
