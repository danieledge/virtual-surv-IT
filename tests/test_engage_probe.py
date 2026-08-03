"""scripts/engage_probe.py: the step-0 open-time probe collapsed from an 18-line bash
compound the model had to reproduce verbatim into one tested script (audit finding
#5/#6/#8, 2026-07-30). Covers the pure computation - version-changed decision, map/changelog
parsing - the pieces where prose reproduction previously stood in for a mechanical check."""

from __future__ import annotations

import json

from scripts.engage_probe import (
    _cap_section3_rows,
    build_report,
    first_changelog_entry,
    last_team_version,
    read_map,
    read_plugin_version,
    read_team_preferences,
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
