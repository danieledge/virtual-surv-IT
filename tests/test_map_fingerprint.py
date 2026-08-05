"""Tests for scripts/map_fingerprint.py (ADR-007 Phase 1 Chunk C - drift stamps)."""

from __future__ import annotations

from scripts.map_fingerprint import compute_fingerprint, resolve_globs


def test_resolve_globs_matches_a_single_file(tmp_path):
    (tmp_path / "a.py").write_text("x", encoding="utf-8")
    assert resolve_globs(["a.py"], tmp_path) == ["a.py"]


def test_resolve_globs_recursive_pattern(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("x", encoding="utf-8")
    (tmp_path / "src" / "sub").mkdir()
    (tmp_path / "src" / "sub" / "b.py").write_text("y", encoding="utf-8")
    assert resolve_globs(["src/**"], tmp_path) == ["src/a.py", "src/sub/b.py"]


def test_resolve_globs_multiple_patterns_deduplicated_and_sorted(tmp_path):
    (tmp_path / "a.py").write_text("x", encoding="utf-8")
    (tmp_path / "b.py").write_text("y", encoding="utf-8")
    assert resolve_globs(["a.py", "b.py", "a.py"], tmp_path) == ["a.py", "b.py"]


def test_resolve_globs_no_match_is_empty_not_an_error(tmp_path):
    assert resolve_globs(["nonexistent.py"], tmp_path) == []


def test_resolve_globs_bare_double_star_matches_files_not_just_directories(tmp_path):
    """Stdlib pathlib's own `Path.glob("**")` only matches directories - a bare `**` glob
    hand-written by a PM ("everything under src") would silently match zero files without
    this normalisation. Also covers a top-level bare "**"."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("x", encoding="utf-8")
    assert resolve_globs(["src/**"], tmp_path) == ["src/a.py"]
    assert resolve_globs(["**"], tmp_path) == ["src/a.py"]


def test_resolve_globs_only_matches_files_not_directories(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("x", encoding="utf-8")
    assert resolve_globs(["src"], tmp_path) == []  # "src" itself is a dir, not a file
    assert resolve_globs(["src/*"], tmp_path) == ["src/a.py"]


def test_compute_fingerprint_stable_with_no_file_changes(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    first = compute_fingerprint(["a.py"], tmp_path)
    second = compute_fingerprint(["a.py"], tmp_path)
    assert first == second
    assert first.startswith("sha256:")


def test_compute_fingerprint_changes_when_a_covered_file_changes(tmp_path):
    f = tmp_path / "a.py"
    f.write_text("x = 1\n", encoding="utf-8")
    before = compute_fingerprint(["a.py"], tmp_path)
    f.write_text("x = 2\n", encoding="utf-8")
    after = compute_fingerprint(["a.py"], tmp_path)
    assert before != after


def test_compute_fingerprint_changes_when_a_file_is_added(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    before = compute_fingerprint(["*.py"], tmp_path)
    (tmp_path / "b.py").write_text("y = 2\n", encoding="utf-8")
    after = compute_fingerprint(["*.py"], tmp_path)
    assert before != after


def test_compute_fingerprint_changes_on_rename_even_with_identical_content(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    before = compute_fingerprint(["*.py"], tmp_path)
    (tmp_path / "a.py").rename(tmp_path / "b.py")
    after = compute_fingerprint(["*.py"], tmp_path)
    assert before != after


def test_compute_fingerprint_empty_match_is_still_a_valid_stable_value(tmp_path):
    first = compute_fingerprint(["nonexistent.py"], tmp_path)
    second = compute_fingerprint(["nonexistent.py"], tmp_path)
    assert first == second
    assert first.startswith("sha256:")
