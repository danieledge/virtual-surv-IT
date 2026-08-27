"""The single source of truth for where the team's files live (VSIT layout migration).

Every location the team writes to was previously constructed inline at the point of use -
39 sites building `<project>/artifacts` alone. This module makes the layout a property of
one file, so moving a location is a change here rather than an edit everywhere.

The property these tests exist to protect is the FALLBACK ORDER. A resolver that returned
the new path unconditionally would silently orphan every existing engagement pack on
upgrade: the files would still be on disk and nothing would be able to find them. So the
question each resolver answers is "where IS it", not "where should it be".
"""

from __future__ import annotations

import scripts.vsit_paths as vp


# ------------------------------------------------------------------ fresh project


def test_a_fresh_project_gets_the_new_layout(tmp_path):
    """Neither location present: the new one wins, so nothing has to be migrated before the
    team can be used at all."""
    assert vp.engagements_dir(tmp_path) == tmp_path / "VSIT" / "engagements"
    assert vp.shared_dir(tmp_path) == tmp_path / "VSIT" / "shared"
    assert vp.config_dir(tmp_path) == tmp_path / "VSIT" / "config"
    assert vp.local_dir(tmp_path) == tmp_path / "VSIT" / "local"
    assert vp.is_legacy_layout(tmp_path) is False


def test_reports_has_no_legacy_location(tmp_path):
    """Project-level deliverables previously landed loose at the root of artifacts/, which
    is exactly how they became indistinguishable from engagement packs. There is nothing to
    fall back to, and inventing one would recreate the confusion."""
    (tmp_path / "artifacts").mkdir()
    assert vp.reports_dir(tmp_path) == tmp_path / "VSIT" / "reports"


# ------------------------------------------------------------------ legacy project


def test_an_existing_artifacts_folder_still_resolves(tmp_path):
    """THE regression this file exists to prevent. A project upgrading the plugin must keep
    finding its own engagement packs."""
    (tmp_path / "artifacts" / "eng-001").mkdir(parents=True)
    assert vp.engagements_dir(tmp_path) == tmp_path / "artifacts"
    assert vp.engagement_dir("eng-001", tmp_path) == tmp_path / "artifacts" / "eng-001"
    assert vp.is_legacy_layout(tmp_path) is True


def test_legacy_preferences_keep_resolving(tmp_path):
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "team-preferences.json").write_text("{}", encoding="utf-8")
    assert vp.config_dir(tmp_path) == tmp_path / ".claude"


def test_legacy_caches_keep_resolving(tmp_path):
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / ".tool-availability").write_text("x", encoding="utf-8")
    assert vp.local_dir(tmp_path) == tmp_path / ".claude"


# ------------------------------------------------------------------ the docs/ narrowing


def test_a_bare_docs_folder_is_not_claimed_as_ours(tmp_path):
    """`docs/` belongs to the HOST project. Almost every repository has one; very few have
    our map in it. Falling back on the folder's mere existence would have the team writing
    its files into someone else's documentation directory - which is the behaviour this
    whole migration exists to stop."""
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "architecture.md").write_text("theirs", encoding="utf-8")
    assert vp.shared_dir(tmp_path) == tmp_path / "VSIT" / "shared"


def test_docs_is_claimed_only_when_our_map_is_actually_there(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "codebase-map.md").write_text("# map", encoding="utf-8")
    assert vp.shared_dir(tmp_path) == tmp_path / "docs"
    assert vp.map_file(tmp_path) == tmp_path / "docs" / "codebase-map.md"
    assert vp.is_legacy_layout(tmp_path) is True


def test_the_uppercase_legacy_map_name_is_honoured(tmp_path):
    """Both spellings shipped; a project carrying either must keep working."""
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "CODEBASE-MAP.md").write_text("# map", encoding="utf-8")
    assert vp.shared_dir(tmp_path) == tmp_path / "docs"
    assert vp.map_file(tmp_path) == tmp_path / "docs" / "CODEBASE-MAP.md"


def test_the_new_map_is_named_for_its_folder(tmp_path):
    """In VSIT/shared/ the file is map.md - the folder already says what it maps, so
    repeating it in the filename was only ever needed when it lived among a project's own
    documentation."""
    (tmp_path / "VSIT" / "shared").mkdir(parents=True)
    assert vp.map_file(tmp_path) == tmp_path / "VSIT" / "shared" / "map.md"


# ------------------------------------------------------------------ precedence


def test_the_new_layout_wins_when_both_exist(tmp_path):
    """During migration both may be present. The new one is authoritative, or a
    half-migrated project would keep writing to the old place forever."""
    (tmp_path / "artifacts").mkdir()
    (tmp_path / "VSIT" / "engagements").mkdir(parents=True)
    assert vp.engagements_dir(tmp_path) == tmp_path / "VSIT" / "engagements"
    assert vp.is_legacy_layout(tmp_path) is False


# ------------------------------------------------------------------ project root


def test_the_project_root_honours_the_harness_before_cwd(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    assert vp.project_root() == tmp_path


def test_an_explicit_argument_beats_the_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", "/somewhere/else")
    assert vp.project_root(tmp_path) == tmp_path


def test_the_root_never_walks_ancestors(tmp_path, monkeypatch):
    """A 2026-08-14 audit found the old ancestor-walk resolving a project at
    /home/user/artifacts/myproject to /home/user/artifacts - outside the project entirely,
    with every pack written there. Walking above an authoritative root can only escape it."""
    nested = tmp_path / "artifacts" / "myproject"
    nested.mkdir(parents=True)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(nested))
    assert vp.project_root() == nested
    assert vp.engagements_dir() == nested / "VSIT" / "engagements"
