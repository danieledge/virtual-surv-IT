"""Tests for scripts/repo_skeleton.py - deterministic first-contact codebase orientation
(ADR-007 Phase 1). Chunk A: inventory, tiered symbol extraction, token-budgeted output.
Chunk B: PageRank, Mermaid, churn.
"""

from __future__ import annotations

import subprocess
import time

import pytest

from scripts.repo_skeleton import (
    build_reference_graph,
    build_skeleton,
    extract_symbols,
    git_churn,
    inventory,
    mtime_churn,
    pagerank,
    render_mermaid,
    _estimate_tokens,
    _os_walk_files,
    _python_import_modules,
    _symbols_ast_python,
    _symbols_ctags,
    _symbols_floor,
    _symbols_tree_sitter,
    _TIER_AST,
    _TIER_CTAGS,
    _TIER_FLOOR,
    _TIER_TREE_SITTER,
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


def test_extract_symbols_dispatches_to_ast_tier_for_python(tmp_path):
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
