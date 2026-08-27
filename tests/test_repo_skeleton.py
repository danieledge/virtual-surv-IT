"""Tests for scripts/repo_skeleton.py - deterministic first-contact codebase orientation
(ADR-007 Phase 1). Chunk A: inventory, tiered symbol extraction, token-budgeted output.
Chunk B: PageRank, Mermaid, churn.
"""

from __future__ import annotations

import json
import subprocess
import time

import pytest
import scripts.repo_skeleton as rs
from pathlib import Path
from scripts.repo_skeleton import (
    build_reference_graph,
    build_skeleton,
    extract_symbols,
    git_churn,
    inventory,
    mtime_churn,
    pagerank,
    render_mermaid,
    write_fingerprints,
    _current_head_sha,
    _estimate_tokens,
    _os_walk_files,
    _parse_map_paths_column,
    _python_import_modules,
    _symbols_ast_python,
    _symbols_ctags,
    _symbols_floor,
    _symbols_tree_sitter,
    _TIER_AST,
    _TIER_CTAGS,
    _TIER_FLOOR,
)


def _git(root, *args):
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


def _init_repo(root):
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "T")


# --------------------------------------------------------------------------- inventory


def test_inventory_git_repo_lists_tracked_and_untracked_not_ignored(tmp_path):
    _init_repo(tmp_path)
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / ".gitignore").write_text("ignored.py\n", encoding="utf-8")
    (tmp_path / "ignored.py").write_text("y = 2\n", encoding="utf-8")
    (tmp_path / "untracked.py").write_text("z = 3\n", encoding="utf-8")
    _git(tmp_path, "add", "a.py", ".gitignore")

    files = inventory(tmp_path)
    assert "a.py" in files
    assert ".gitignore" in files
    assert "untracked.py" in files
    assert "ignored.py" not in files  # respects .gitignore via git ls-files --exclude-standard


def test_inventory_os_walk_fallback_when_no_git_repo(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "m.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "m.cpython-312.pyc").write_bytes(b"\x00")

    files = inventory(tmp_path)
    assert "src/m.py" in files
    assert not any("__pycache__" in f for f in files)


def test_os_walk_fallback_excludes_node_modules_without_descending(tmp_path):
    """The exclusion must stop os.walk from DESCENDING, not just filter the listing -
    otherwise a huge node_modules still gets stat'd file-by-file for nothing."""
    nm = tmp_path / "node_modules" / "pkg"
    nm.mkdir(parents=True)
    (nm / "index.js").write_text("", encoding="utf-8")
    (tmp_path / "app.js").write_text("", encoding="utf-8")

    files = _os_walk_files(tmp_path)
    assert "app.js" in files
    assert not any("node_modules" in f for f in files)


def test_inventory_is_sorted_and_deterministic(tmp_path):
    _init_repo(tmp_path)
    for name in ("z.py", "a.py", "m.py"):
        (tmp_path / name).write_text("", encoding="utf-8")
    _git(tmp_path, "add", "-A")

    files = inventory(tmp_path)
    assert files == sorted(files)


def test_inventory_falls_back_when_git_unavailable(tmp_path, monkeypatch):
    import scripts.repo_skeleton as rs

    monkeypatch.setattr(rs, "_git_ls_files", lambda root: None)
    (tmp_path / "x.py").write_text("", encoding="utf-8")
    assert inventory(tmp_path) == ["x.py"]


# --------------------------------------------------------------------------- symbol extraction


def test_ast_extracts_top_level_defs_and_classes(tmp_path):
    f = tmp_path / "m.py"
    f.write_text(
        "def foo():\n    pass\n\n\nclass Bar:\n    def method(self):\n        pass\n",
        encoding="utf-8",
    )
    symbols = _symbols_ast_python(f)
    assert symbols == ["foo", "Bar", "method"]


def test_ast_returns_none_on_syntax_error(tmp_path):
    f = tmp_path / "broken.py"
    f.write_text("def (:\n", encoding="utf-8")
    assert _symbols_ast_python(f) is None


def test_floor_extracts_markdown_headings(tmp_path):
    f = tmp_path / "doc.md"
    f.write_text("# Title\n\nSome text.\n\n## Section\n", encoding="utf-8")
    assert _symbols_floor(f) == ["Title", "Section"]


def test_floor_non_markdown_file_yields_no_symbols(tmp_path):
    f = tmp_path / "data.json"
    f.write_text('{"a": 1}', encoding="utf-8")
    assert _symbols_floor(f) == []


def test_tree_sitter_probe_never_crashes_when_absent(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def _blocked(name, *a, **k):
        if name == "tree_sitter":
            raise ImportError("no tree_sitter")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", _blocked)
    assert _symbols_tree_sitter(None) is None


def test_ctags_probe_never_crashes_when_absent(monkeypatch):
    import scripts.repo_skeleton as rs

    monkeypatch.setattr(rs.shutil, "which", lambda name: None)
    assert _symbols_ctags(None) is None


def test_ctags_probe_fails_soft_on_timeout(tmp_path, monkeypatch):
    import scripts.repo_skeleton as rs

    monkeypatch.setattr(rs.shutil, "which", lambda name: "/usr/bin/ctags")

    def _boom(*a, **k):
        raise subprocess.TimeoutExpired(["ctags"], 10)

    monkeypatch.setattr(rs.subprocess, "run", _boom)
    assert _symbols_ctags(tmp_path / "x.py") is None


def test_extract_symbols_dispatches_to_ast_tier_for_python(tmp_path, monkeypatch):
    # Silence the two tiers ABOVE ast, so this tests dispatch rather than what happens to
    # be installed on the host (tree-sitter became a real tier on 2026-08-26).
    monkeypatch.setattr(rs, "_symbols_tree_sitter", lambda path: None)
    monkeypatch.setattr(rs, "_symbols_ctags", lambda path: None)
    f = tmp_path / "m.py"
    f.write_text("def foo():\n    pass\n", encoding="utf-8")
    symbols, tier = extract_symbols(f)
    assert tier == _TIER_AST
    assert symbols == ["foo"]


def test_extract_symbols_falls_to_floor_for_non_python(tmp_path):
    f = tmp_path / "doc.md"
    f.write_text("# Title\n", encoding="utf-8")
    symbols, tier = extract_symbols(f)
    assert tier == _TIER_FLOOR
    assert symbols == ["Title"]


def test_extract_symbols_tier_order_ctags_before_ast(tmp_path, monkeypatch):
    """A .py file with ctags actually available should use the ctags tier, not ast -
    ctags is ranked above ast in the fallback order."""
    import scripts.repo_skeleton as rs

    f = tmp_path / "m.py"
    f.write_text("def foo():\n    pass\n", encoding="utf-8")
    monkeypatch.setattr(rs, "_symbols_tree_sitter", lambda path: None)
    monkeypatch.setattr(rs, "_symbols_ctags", lambda path: ["from_ctags"])
    symbols, tier = extract_symbols(f)
    assert tier == _TIER_CTAGS
    assert symbols == ["from_ctags"]


# --------------------------------------------------------------------------- token budget


def test_estimate_tokens_is_chars_over_four():
    assert _estimate_tokens("x" * 400) == 100


def test_build_skeleton_stays_full_detail_under_budget(tmp_path):
    _init_repo(tmp_path)
    (tmp_path / "a.py").write_text("def foo():\n    pass\n", encoding="utf-8")
    _git(tmp_path, "add", "-A")

    out = build_skeleton(tmp_path, budget_tokens=6000)
    assert "## a.py" in out
    assert "foo" in out
    assert "omitted" not in out


def test_build_skeleton_switches_to_compact_tier_and_notes_omissions(tmp_path):
    _init_repo(tmp_path)
    for i in range(30):
        (tmp_path / f"m{i:02d}.py").write_text(
            f"def f{i}():\n    pass\n\n\ndef g{i}():\n    pass\n", encoding="utf-8"
        )
    _git(tmp_path, "add", "-A")

    out = build_skeleton(tmp_path, budget_tokens=120)
    assert "more lower-ranked file" in out
    assert "omitted" in out


def test_build_skeleton_output_is_deterministic_across_runs(tmp_path):
    _init_repo(tmp_path)
    for name in ("b.py", "a.py", "c.md"):
        (tmp_path / name).write_text("def x():\n    pass\n", encoding="utf-8")
    _git(tmp_path, "add", "-A")

    first = build_skeleton(tmp_path, budget_tokens=6000)
    second = build_skeleton(tmp_path, budget_tokens=6000)
    assert first == second


def test_build_skeleton_ranks_drive_emission_order(tmp_path):
    _init_repo(tmp_path)
    (tmp_path / "low.py").write_text("def a():\n    pass\n", encoding="utf-8")
    (tmp_path / "high.py").write_text("def b():\n    pass\n", encoding="utf-8")
    _git(tmp_path, "add", "-A")

    out = build_skeleton(tmp_path, budget_tokens=6000, ranks={"high.py": 1.0, "low.py": 0.0})
    assert out.index("## high.py") < out.index("## low.py")


# --------------------------------------------------------------------------- reference graph


def test_python_import_modules_extracts_absolute_imports(tmp_path):
    f = tmp_path / "m.py"
    f.write_text("import os\nimport pkg.sub\nfrom pkg.other import thing\n", encoding="utf-8")
    assert _python_import_modules(f) == {"os", "pkg.sub", "pkg.other"}


def test_python_import_modules_skips_relative_imports(tmp_path):
    f = tmp_path / "m.py"
    f.write_text("from . import sibling\nfrom .pkg import thing\n", encoding="utf-8")
    assert _python_import_modules(f) == set()


def test_build_reference_graph_resolves_absolute_package_imports(tmp_path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "pkg" / "a.py").write_text("import pkg.b\n", encoding="utf-8")
    (tmp_path / "pkg" / "b.py").write_text("x = 1\n", encoding="utf-8")

    files = ["pkg/__init__.py", "pkg/a.py", "pkg/b.py"]
    graph = build_reference_graph(tmp_path, files)
    assert "pkg/b.py" in graph["pkg/a.py"]


def test_build_reference_graph_resolves_from_import_of_a_symbol(tmp_path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "pkg" / "a.py").write_text("from pkg.b import thing\n", encoding="utf-8")
    (tmp_path / "pkg" / "b.py").write_text("thing = 1\n", encoding="utf-8")

    files = ["pkg/__init__.py", "pkg/a.py", "pkg/b.py"]
    graph = build_reference_graph(tmp_path, files)
    assert "pkg/b.py" in graph["pkg/a.py"]


def test_build_reference_graph_non_python_files_have_no_edges(tmp_path):
    (tmp_path / "notes.md").write_text("# hi\n", encoding="utf-8")
    graph = build_reference_graph(tmp_path, ["notes.md"])
    assert graph == {"notes.md": set()}


# --------------------------------------------------------------------------- pagerank


def test_pagerank_empty_graph_is_empty():
    assert pagerank({}) == {}


def test_pagerank_scores_sum_to_approximately_one():
    graph = {"a.py": {"b.py"}, "b.py": {"c.py"}, "c.py": {"a.py"}}
    scores = pagerank(graph)
    assert scores.keys() == {"a.py", "b.py", "c.py"}
    assert abs(sum(scores.values()) - 1.0) < 1e-6


def test_pagerank_more_incoming_edges_ranks_higher():
    # a.py and b.py both point at c.py; nothing points at a.py or b.py.
    graph = {"a.py": {"c.py"}, "b.py": {"c.py"}, "c.py": set()}
    scores = pagerank(graph)
    assert scores["c.py"] > scores["a.py"]
    assert scores["c.py"] > scores["b.py"]


def test_pagerank_cyclic_graph_terminates_and_stays_bounded():
    graph = {f"n{i}.py": {f"n{(i + 1) % 20}.py"} for i in range(20)}
    started = time.monotonic()
    scores = pagerank(graph)
    assert time.monotonic() - started < 5  # doesn't hang
    assert all(0 <= v <= 1 for v in scores.values())


def test_pagerank_dangling_node_leaks_score_instead_of_vanishing():
    # b.py has no outgoing edges (dangling) - its score must still be redistributed, not lost.
    graph = {"a.py": {"b.py"}, "b.py": set()}
    scores = pagerank(graph)
    assert abs(sum(scores.values()) - 1.0) < 1e-6


# --------------------------------------------------------------------------- mermaid


def test_render_mermaid_empty_graph_has_no_nodes():
    out = render_mermaid({})
    assert out.strip() == "graph TD"


def test_render_mermaid_isolated_node_is_not_drawn():
    out = render_mermaid({"lonely.py": set()})
    assert "lonely" not in out


def test_render_mermaid_connected_nodes_and_edges():
    out = render_mermaid({"a.py": {"b.py"}})
    assert 'a_py["a.py"]' in out
    assert 'b_py["b.py"]' in out
    assert "a_py --> b_py" in out


def test_render_mermaid_deterministic_across_dict_insertion_order_permutations():
    graph_1 = {"a.py": {"b.py", "c.py"}, "b.py": {"c.py"}}
    graph_2 = {"b.py": {"c.py"}, "a.py": {"c.py", "b.py"}}
    assert render_mermaid(graph_1) == render_mermaid(graph_2)


# --------------------------------------------------------------------------- churn


def test_git_churn_counts_commits_per_file(tmp_path):
    _init_repo(tmp_path)
    f = tmp_path / "a.py"
    f.write_text("v1\n", encoding="utf-8")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "v1")
    f.write_text("v2\n", encoding="utf-8")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "v2")

    churn = git_churn(tmp_path, ["a.py"])
    assert churn == {"a.py": 2}


def test_git_churn_none_when_no_git_repo(tmp_path):
    assert git_churn(tmp_path, ["a.py"]) is None


def test_git_churn_uses_one_batched_subprocess_call(tmp_path, monkeypatch):
    import scripts.repo_skeleton as rs

    _init_repo(tmp_path)
    for name in ("a.py", "b.py", "c.py"):
        (tmp_path / name).write_text("x\n", encoding="utf-8")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "initial")

    calls = []
    real_run = rs.subprocess.run

    def _counting_run(*a, **k):
        calls.append(1)
        return real_run(*a, **k)

    monkeypatch.setattr(rs.subprocess, "run", _counting_run)
    git_churn(tmp_path, ["a.py", "b.py", "c.py"])
    assert len(calls) == 1


def test_mtime_churn_falls_back_when_no_git(tmp_path):
    f = tmp_path / "a.py"
    f.write_text("x\n", encoding="utf-8")
    churn = mtime_churn(tmp_path, ["a.py"])
    assert "a.py" in churn
    assert churn["a.py"] > 0


def test_mtime_churn_skips_missing_files(tmp_path):
    assert mtime_churn(tmp_path, ["missing.py"]) == {}


# --------------------------------------------------------------------------- churn display


def test_build_skeleton_shows_measured_churn(tmp_path):
    _init_repo(tmp_path)
    (tmp_path / "a.py").write_text("def x():\n    pass\n", encoding="utf-8")
    _git(tmp_path, "add", "-A")

    out = build_skeleton(tmp_path, budget_tokens=6000, churn={"a.py": 3}, churn_measured=True)
    assert "3 commits" in out
    assert "measured" in out


def test_build_skeleton_shows_inferred_mtime_churn(tmp_path):
    _init_repo(tmp_path)
    (tmp_path / "a.py").write_text("def x():\n    pass\n", encoding="utf-8")
    _git(tmp_path, "add", "-A")

    out = build_skeleton(
        tmp_path, budget_tokens=6000, churn={"a.py": time.time()}, churn_measured=False
    )
    assert "inferred" in out


# --------------------------------------------------------------------------- mermaid in skeleton


def test_build_skeleton_appends_mermaid_section_when_graph_has_edges(tmp_path):
    _init_repo(tmp_path)
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    _git(tmp_path, "add", "-A")

    out = build_skeleton(
        tmp_path, budget_tokens=6000, mermaid_graph={"a.py": {"b.py"}, "b.py": set()}
    )
    assert "## Dependency graph" in out
    assert "```mermaid" in out


def test_build_skeleton_omits_mermaid_section_when_graph_is_empty(tmp_path):
    _init_repo(tmp_path)
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    _git(tmp_path, "add", "-A")

    out = build_skeleton(tmp_path, budget_tokens=6000, mermaid_graph={"a.py": set()})
    assert "## Dependency graph" not in out


# --------------------------------------------------------------------------- drift-stamp writer

_MAP_WITH_PATHS = """# Codebase Map - Test

| # | Area | Entry | Basis | As-of | Anchor | Paths |
|---|------|-------|-------|-------|--------|-------|
| 1 | detection rules | Fact one | 📊 seen | 2026-08-06 | `abc123` | src/rules.py |
| 2 | config | Fact two | 🧠 assumed | 2026-08-06 | `abc123` | src/config.py, src/settings.py |
"""

_MAP_WITHOUT_PATHS = """# Codebase Map - Test

| # | Area | Entry | Basis | As-of | Anchor |
|---|------|-------|-------|-------|--------|
| 1 | detection rules | Fact one | 📊 seen | 2026-08-06 | `abc123` |
"""


def test_parse_map_paths_column_extracts_area_to_globs(tmp_path):
    m = tmp_path / "map.md"
    m.write_text(_MAP_WITH_PATHS, encoding="utf-8")
    result = _parse_map_paths_column(m)
    assert result == {
        "detection rules": ["src/rules.py"],
        "config": ["src/config.py", "src/settings.py"],
    }


def test_parse_map_paths_column_missing_column_is_empty_not_an_error(tmp_path):
    m = tmp_path / "map.md"
    m.write_text(_MAP_WITHOUT_PATHS, encoding="utf-8")
    assert _parse_map_paths_column(m) == {}


def test_parse_map_paths_column_missing_file_is_empty(tmp_path):
    assert _parse_map_paths_column(tmp_path / "nonexistent.md") == {}


def test_current_head_sha_no_vcs_when_not_a_git_repo(tmp_path):
    assert _current_head_sha(tmp_path) == "no-vcs"


def test_current_head_sha_resolves_in_a_real_repo(tmp_path):
    subprocess.run(["git", "-C", str(tmp_path), "init", "-q"], check=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.email", "t@example.com"], check=True
    )
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "T"], check=True)
    (tmp_path / "a.py").write_text("x", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-qm", "init"], check=True)
    sha = _current_head_sha(tmp_path)
    assert sha != "no-vcs"
    assert len(sha) == 40


def test_write_fingerprints_writes_sidecar_with_entries(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "rules.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "src" / "config.py").write_text("y = 2\n", encoding="utf-8")
    (tmp_path / "src" / "settings.py").write_text("z = 3\n", encoding="utf-8")
    m = tmp_path / "map.md"
    m.write_text(_MAP_WITH_PATHS, encoding="utf-8")

    payload = write_fingerprints(m)
    assert set(payload["entries"]) == {"detection rules", "config"}
    assert payload["entries"]["detection rules"]["files_hashed"] == 1
    assert payload["entries"]["config"]["files_hashed"] == 2
    assert "areas" not in payload  # dropped 2026-08-06 - unused scaffolding, never read
    assert payload["generated_by"] == "repo_skeleton"

    sidecar = tmp_path / "codebase-map.fingerprints.json"
    assert sidecar.is_file()
    on_disk = json.loads(sidecar.read_text(encoding="utf-8"))
    assert on_disk == payload


def test_write_fingerprints_no_paths_column_writes_empty_entries(tmp_path):
    m = tmp_path / "map.md"
    m.write_text(_MAP_WITHOUT_PATHS, encoding="utf-8")
    payload = write_fingerprints(m)
    assert payload["entries"] == {}


def test_write_fingerprints_fingerprint_changes_when_covered_file_changes(tmp_path):
    (tmp_path / "src").mkdir()
    f = tmp_path / "src" / "rules.py"
    f.write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "src" / "config.py").write_text("y\n", encoding="utf-8")
    (tmp_path / "src" / "settings.py").write_text("z\n", encoding="utf-8")
    m = tmp_path / "map.md"
    m.write_text(_MAP_WITH_PATHS, encoding="utf-8")

    before = write_fingerprints(m)["entries"]["detection rules"]["fingerprint"]
    f.write_text("x = 2\n", encoding="utf-8")
    after = write_fingerprints(m)["entries"]["detection rules"]["fingerprint"]
    assert before != after


# --- bugs found live building Chunk E (2026-08-06): sidecar location vs glob-resolution root
# were silently conflated as "map_path.parent", correct only when the map sits at the
# project root - wrong for the documented default location (docs/codebase-map.md), where the
# map's own directory and the project root differ. ------------------------------------------


def test_write_fingerprints_globs_resolve_against_project_dir_not_map_parent(tmp_path):
    """The map lives in docs/ but its Paths globs (src/*.py) are relative to the PROJECT
    root, not to docs/ - this must hash the real files, not silently find nothing."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "rules.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "src" / "config.py").write_text("y\n", encoding="utf-8")
    (tmp_path / "src" / "settings.py").write_text("z\n", encoding="utf-8")
    docs = tmp_path / "docs"
    docs.mkdir()
    m = docs / "codebase-map.md"
    m.write_text(_MAP_WITH_PATHS, encoding="utf-8")

    payload = write_fingerprints(m, project_dir=tmp_path)
    assert payload["entries"]["detection rules"]["files_hashed"] == 1
    assert payload["entries"]["config"]["files_hashed"] == 2


def test_write_fingerprints_sidecar_lives_next_to_map_not_at_project_dir(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "rules.py").write_text("x\n", encoding="utf-8")
    (tmp_path / "src" / "config.py").write_text("y\n", encoding="utf-8")
    (tmp_path / "src" / "settings.py").write_text("z\n", encoding="utf-8")
    docs = tmp_path / "docs"
    docs.mkdir()
    m = docs / "codebase-map.md"
    m.write_text(_MAP_WITH_PATHS, encoding="utf-8")

    write_fingerprints(m, project_dir=tmp_path)
    assert (docs / "codebase-map.fingerprints.json").is_file()
    assert not (tmp_path / "codebase-map.fingerprints.json").is_file()


def test_write_fingerprints_merges_instead_of_overwriting_a_shared_sidecar(tmp_path):
    """Two area files in the same directory share one sidecar (docs/codebase-map.d/
    codebase-map.fingerprints.json) - fingerprinting the second must not erase the first's
    already-recorded entries."""
    area_dir = tmp_path / "docs" / "codebase-map.d"
    area_dir.mkdir(parents=True)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "rules.py").write_text("x\n", encoding="utf-8")
    (tmp_path / "src" / "config.py").write_text("y\n", encoding="utf-8")
    (tmp_path / "src" / "settings.py").write_text("z\n", encoding="utf-8")

    area_a = area_dir / "area-a.md"
    area_a.write_text(_MAP_WITH_PATHS, encoding="utf-8")
    write_fingerprints(area_a, project_dir=tmp_path)

    area_b = area_dir / "area-b.md"
    area_b.write_text(
        "# Codebase Map - B\n\n"
        "| # | Area | Entry | Basis | As-of | Anchor | Paths |\n"
        "|---|------|-------|-------|-------|--------|-------|\n"
        "| 1 | other area | Fact | 📊 seen | 2026-08-06 | `abc123` | src/rules.py |\n",
        encoding="utf-8",
    )
    write_fingerprints(area_b, project_dir=tmp_path)

    sidecar = json.loads((area_dir / "codebase-map.fingerprints.json").read_text(encoding="utf-8"))
    assert set(sidecar["entries"]) == {"detection rules", "config", "other area"}


def test_write_fingerprints_plugin_mode_import_does_not_crash(tmp_path, monkeypatch):
    """The dual-mode loader must work even when `scripts` isn't importable as a package -
    the exact invocation form /map-codebase uses in a plugin install (direct file path, no
    package context). Simulated by breaking the package-import branch."""
    import builtins

    real_import = builtins.__import__

    def _no_scripts_package(name, *a, **k):
        if name == "scripts" or name.startswith("scripts."):
            raise ImportError(f"simulated: {name} not importable as a package")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", _no_scripts_package)
    m = tmp_path / "map.md"
    m.write_text(_MAP_WITHOUT_PATHS, encoding="utf-8")
    payload = write_fingerprints(m)  # must not raise ModuleNotFoundError
    assert payload["entries"] == {}


# ------------------------------------------------ --slice (2026-08-26 exploration audit)


def test_python_symbol_ranges_are_exact_and_include_decorators(tmp_path):
    """Ranges come free from the AST walk repo_skeleton already does - they were simply
    being discarded. Decorators count as part of the symbol: a slice that omits the
    decorator hides what actually applies to the function."""
    src = tmp_path / "m.py"
    src.write_text(
        "import functools\n"
        "\n"
        "\n"
        "@functools.cache\n"
        "def decorated(a):\n"
        "    return a\n"
        "\n"
        "\n"
        "class Thing:\n"
        "    def method(self):\n"
        "        return 1\n",
        encoding="utf-8",
    )
    ranges = rs.python_symbol_ranges(src)
    assert ranges["decorated"] == (4, 6), "the decorator line must be inside the range"
    assert ranges["Thing"][0] == 9
    assert ranges["method"] == (10, 11)


def test_slice_returns_one_symbol_not_the_file(tmp_path):
    """The reason this exists: a review that needed one function out of a 2,800-line file
    was reading the whole file - about 31,700 tokens to obtain roughly 340."""
    src = tmp_path / "m.py"
    body = "\n".join(f"# filler {i}" for i in range(500))
    src.write_text(f"{body}\n\n\ndef wanted():\n    return 'here'\n", encoding="utf-8")
    text, tier = rs.slice_symbol(src, "wanted")
    assert tier == "ast"
    assert text == "def wanted():\n    return 'here'"
    assert "filler" not in text
    assert len(text) < len(src.read_text(encoding="utf-8")) / 50


def test_slice_is_best_effort_on_non_python_and_says_so(tmp_path, monkeypatch):
    """The tier travels with the output - the same honesty contract the symbol tiers carry.
    'ast' is exact; 'regex' located the declaration and inferred the end."""
    # Force the regex path: with tree-sitter installed the slice would be exact, and the
    # point of THIS test is the best-effort tier and its honest label.
    monkeypatch.setattr(rs, "_ts_symbols_and_ranges", lambda path: None)
    src = tmp_path / "Score.scala"
    src.write_text(
        "package a.b\n"
        "\n"
        "class RuleAScorer extends Pipeline.ScoreStep {\n"
        '  final lazy val segments = Set("RETAIL")\n'
        "  override def segment(x: Txn): String = {\n"
        '    "HIGH"\n'
        "  }\n"
        "}\n"
        "\n"
        "class Other extends Pipeline.ScoreStep {\n"
        '  override def segment(x: Txn): String = "LOW"\n'
        "}\n",
        encoding="utf-8",
    )
    text, tier = rs.slice_symbol(src, "RuleAScorer")
    assert tier == "regex"
    assert "final lazy val segments" in text
    assert "class Other" not in text, "the slice must stop at the closing brace"


def test_slice_returns_none_for_an_unknown_symbol(tmp_path):
    src = tmp_path / "m.py"
    src.write_text("def a():\n    pass\n", encoding="utf-8")
    assert rs.slice_symbol(src, "nonexistent") is None


def test_slice_cli_reports_the_tier_and_exits_nonzero_when_not_found(tmp_path, capsys):
    src = tmp_path / "m.py"
    src.write_text("def wanted():\n    return 2\n", encoding="utf-8")
    assert rs.main(["repo_skeleton", "--slice", f"{src}:wanted", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "[ast]" in out and "def wanted():" in out
    assert rs.main(["repo_skeleton", "--slice", f"{src}:missing", str(tmp_path)]) == 1


def test_slice_splits_on_the_last_colon_so_windows_paths_work(tmp_path):
    """`C:/x/y.py:symbol` must split on the symbol colon, not the drive-letter one."""
    src = tmp_path / "m.py"
    src.write_text("def s():\n    pass\n", encoding="utf-8")
    spec = f"{src}:s"
    target, _, symbol = spec.rpartition(":")
    assert symbol == "s" and target == str(src)


# ------------------------------------- tree-sitter tier (2026-08-26, no longer a stub)


_HAS_TS = rs._ts_parser(Path("x.py")) is not None


def test_the_tier_is_absent_safe_and_that_is_the_normal_case():
    """The property that matters most, and the one that holds on THIS box: tree-sitter is a
    SOFT probe. Not installed - or installed and refusing to load, which is the locked-down
    case - must be indistinguishable from before the tier existed. Never an exception, never
    a partial result, just a fall-through to the next tier."""
    assert rs._ts_parser(Path("nope.unknownext")) is None, "unknown language must be None"
    assert rs._symbols_tree_sitter(Path("nope.unknownext")) is None
    # A file that does not exist must not raise either.
    assert rs._ts_symbols_and_ranges(Path("does-not-exist.py")) is None


def test_python_still_resolves_without_tree_sitter(tmp_path):
    """Python has a stdlib floor, so it must never depend on the probe."""
    src = tmp_path / "m.py"
    src.write_text("def a():\n    return 1\n", encoding="utf-8")
    symbols, tier = rs.extract_symbols(src)
    assert "a" in symbols
    assert tier in ("tree-sitter", "ast"), f"unexpected tier {tier!r}"


@pytest.mark.skipif(not _HAS_TS, reason="tree-sitter not installed on this host")
def test_tree_sitter_gives_exact_symbols_and_ranges_for_scala(tmp_path):
    """The case the tier exists for. Surveillance estates are Java/Scala/C#/SQL, and before
    this the skeleton gave those languages regex approximations at best."""
    src = tmp_path / "Score.scala"
    src.write_text(
        "package a.b\n"
        "\n"
        "class RuleA extends Pipeline.ScoreStep {\n"
        "  override def segment(x: Txn): String = {\n"
        '    "HIGH"\n'
        "  }\n"
        "}\n",
        encoding="utf-8",
    )
    found = rs._ts_symbols_and_ranges(src)
    assert found is not None
    names, ranges = found
    assert "RuleA" in names and "segment" in names
    start, end = ranges["segment"]
    assert start == 4 and end == 6, f"expected exact range, got {(start, end)}"


@pytest.mark.skipif(not _HAS_TS, reason="tree-sitter not installed on this host")
def test_slice_prefers_tree_sitter_over_the_regex_guess(tmp_path):
    src = tmp_path / "Score.scala"
    src.write_text(
        "class A {\n  def m(): Int = {\n    1\n  }\n}\n",
        encoding="utf-8",
    )
    text, tier = rs.slice_symbol(src, "m")
    assert tier == "tree-sitter", "the exact tier must win when it is available"
    assert "def m()" in text


def test_the_symbol_cap_applies_to_the_tree_sitter_tier_too():
    """Orientation must stay bounded whichever tier answers - a huge generated file must
    not become the expensive step."""
    assert rs._REGEX_MAX_SYMBOLS > 0
    source = "\n".join(f"def f{i}():\n    pass\n" for i in range(rs._REGEX_MAX_SYMBOLS * 3))
    import tempfile

    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as fh:
        fh.write(source)
        path = Path(fh.name)
    try:
        found = rs._ts_symbols_and_ranges(path)
        if found is not None:
            assert len(found[0]) <= rs._REGEX_MAX_SYMBOLS
    finally:
        path.unlink(missing_ok=True)


# ------------------- per-language grammar coverage (2026-08-27 alignment review)


# The review found the tier advertised five languages and delivered two: `.cs` was mapped to
# "c_sharp" where the pack calls it "csharp" (so every C# file fell through forever), SQL's
# node types were copied from a different grammar and matched nothing, and Kotlin's function
# names were found and then dropped because its identifier node is `simple_identifier`.
# All three degraded quietly, which is the right posture and exactly why nothing surfaced
# them. The two languages that DID work were the two with tests. Hence one per language.
_GRAMMAR_CASES = [
    (
        ".sql",
        b"CREATE TABLE my_table (a int);\nCREATE VIEW my_view AS SELECT 1;",
        {"my_table", "my_view"},
    ),
    # Kotlin expects A/m/n but NOT B, and that is a measured cross-version difference
    # rather than an oversight: pack 0.x parses `object B {}` as `object_declaration`, while
    # 1.x parses it as an infix_expression wrapping an object_literal - not a declaration at
    # all, so no name to take. We are unpinned, so the test asserts what BOTH versions
    # deliver. Do not "fix" this by adding a node type; 1.x does not emit one.
    (".kt", b"class A { fun m(): Int = 1 }\nobject B { fun n() {} }", {"A", "m", "n"}),
    (
        ".scala",
        b"object O { def d = 1 }\ntrait T\nenum E { case A }\ngiven g: Int = 1",
        {"O", "d", "T", "E", "g"},
    ),
    (".cs", b"class A { void M(){} }\nstruct S {}\nnamespace N {}", {"A", "M", "S", "N"}),
    (".java", b"public class A { void m() {} }\n@interface Ann {}", {"A", "m", "Ann"}),
    (".ts", b"export class C {}\nexport function f() {}\nexport interface I {}", {"C", "f", "I"}),
]


@pytest.mark.skipif(not _HAS_TS, reason="tree-sitter not installed on this host")
@pytest.mark.parametrize("suffix,source,expected", _GRAMMAR_CASES)
def test_each_advertised_language_actually_extracts(tmp_path, suffix, source, expected):
    """The install messaging promises 'exact symbols and line ranges for Java, Scala, C#,
    SQL, TypeScript'. Each of those must produce symbols, or the promise is false and the
    failure is invisible."""
    src = tmp_path / f"sample{suffix}"
    src.write_bytes(source)
    found = rs._ts_symbols_and_ranges(src)
    assert found is not None, f"{suffix} produced no symbols at all"
    names = set(found[0])
    missing = expected - names
    assert not missing, f"{suffix} missed {sorted(missing)}; got {sorted(names)}"
    for name in expected & names:
        start, end = found[1][name]
        assert 1 <= start <= end, f"{suffix}:{name} has a nonsense range {(start, end)}"


def test_the_language_map_uses_names_the_pack_recognises():
    """`c_sharp` vs `csharp` cost C# the tier entirely, silently, because an unknown grammar
    name is indistinguishable from 'not installed'. Pin the spelling even where the library
    is absent - this is a table lookup, not a probe."""
    assert rs._TS_LANGS[".cs"] == "csharp"
    assert rs._TS_LANGS[".kt"] == "kotlin"
    assert rs._TS_LANGS[".scala"] == "scala"
    assert rs._TS_LANGS[".sql"] == "sql"


def test_sql_declaration_types_match_the_shipped_grammar():
    """These were the suffixed names from a different SQL grammar, so SQL matched nothing."""
    for node_type in ("create_table", "create_view", "create_function", "create_procedure"):
        assert node_type in rs._TS_DECL_TYPES
    assert "create_table_statement" not in rs._TS_DECL_TYPES, "the wrong grammar's names"


# ------------- the runtime must never reach the network (2026-08-27, unpinned)


def test_a_bundling_build_is_never_gated_by_the_cache_check(monkeypatch):
    """On a pack version that ships grammars in the wheel there is no cache and no download
    - the question does not arise, and answering "unavailable" would silently disable a
    perfectly working tier. ImportError on cache_dir IS that version."""
    import builtins

    real_import = builtins.__import__

    def no_cache_dir(name, *args, **kwargs):
        if name == "tree_sitter_language_pack" and args and args[2] == ("cache_dir",):
            raise ImportError("no cache_dir on this version")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_cache_dir)
    assert rs._ts_grammar_available("python") is True


def test_an_uncached_grammar_is_refused_rather_than_downloaded(monkeypatch):
    """THE safety property, and the reason the pin could be dropped.

    From pack 1.0 grammars are fetched on demand, so a plain get_parser() on an uncached
    language performs a network call - which on a corporate proxy hangs rather than fails,
    at whatever moment the first parse happens. That moment is engagement open. The runtime
    therefore refuses: an un-warmed language costs accuracy, never a hang.

    Verified end to end as well as here: with pack 1.15.8, a cold cache and the network
    black-holed, extract_symbols returned the regex tier in under a second and wrote nothing
    to the cache."""
    monkeypatch.setattr(rs, "_ts_grammar_available", lambda lang: False)
    rs._probe_cache.pop("tree_sitter:python", None)
    try:
        assert rs._ts_parser(Path("x.py")) is None, "an uncached grammar must not be built"
        assert rs._probe_cache.get("tree_sitter:python") is False, "and the refusal is cached"
    finally:
        rs._probe_cache.pop("tree_sitter:python", None)


@pytest.mark.skipif(not _HAS_TS, reason="tree-sitter not installed on this host")
def test_a_cached_grammar_is_allowed(monkeypatch, tmp_path):
    """The other half: a warmed language must still reach the parser."""
    libs = tmp_path / "libs"
    libs.mkdir()
    (libs / "libtree_sitter_c_sharp.so").write_bytes(b"")
    monkeypatch.setattr("tree_sitter_language_pack.cache_dir", lambda: str(libs), raising=False)
    assert rs._ts_grammar_available("csharp") is True


def test_the_cache_check_maps_the_names_that_differ():
    """The pack's API calls it `csharp` and caches it as `c_sharp`. Getting that wrong makes
    a warmed grammar look absent, which silently costs the tier for C# - the same class of
    bug as the original `c_sharp`/`csharp` mix-up, one layer down."""
    assert rs._TS_CACHE_ALIASES["csharp"] == "c_sharp"


@pytest.mark.skipif(not _HAS_TS, reason="tree-sitter not installed on this host")
def test_an_unreadable_cache_dir_does_not_disable_a_working_tier(monkeypatch):
    """This gates a capability, so an unfamiliar layout must fail toward AVAILABLE. Guessing
    "unavailable" would turn a cosmetic surprise into a silently degraded review."""
    import tree_sitter_language_pack  # noqa: F401  (skipped below if absent)

    monkeypatch.setattr(
        "tree_sitter_language_pack.cache_dir",
        lambda: (_ for _ in ()).throw(RuntimeError("x")),
        raising=False,
    )
    assert rs._ts_grammar_available("python") is True
