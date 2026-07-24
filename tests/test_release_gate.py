"""Promotion gate (scripts/release_gate.py): version consistency, eval-baseline presence,
deterministic-only escape hatch, and baseline freshness vs prompt commits."""

from __future__ import annotations

import scripts.release_gate as rg


def _repo(tmp_path, version="1.2.3", badge=None, changelog=True, baseline=None):
    (tmp_path / ".claude-plugin").mkdir()
    (tmp_path / ".claude-plugin" / "plugin.json").write_text(
        f'{{"version": "{version}"}}', encoding="utf-8"
    )
    (tmp_path / "README.md").write_text(
        f"![Version](https://img.shields.io/badge/version-{badge or version}-blue)\n",
        encoding="utf-8",
    )
    (tmp_path / "CHANGELOG.md").write_text(
        f"## [{version}] - x\n" if changelog else "# empty\n", encoding="utf-8"
    )
    (tmp_path / "evals").mkdir()
    if baseline is not None:
        (tmp_path / "evals" / f"eval-baseline-{version}.md").write_text(baseline, encoding="utf-8")
    return tmp_path


def test_missing_baseline_fails(tmp_path):
    root = _repo(tmp_path)
    findings = rg.gate(root)
    assert any("no eval baseline record" in f for f in findings)


def test_badge_mismatch_fails(tmp_path):
    root = _repo(tmp_path, badge="9.9.9", baseline="Scope: full\n")
    assert any("version badge" in f for f in rg.gate(root))


def test_missing_changelog_entry_fails(tmp_path):
    root = _repo(tmp_path, changelog=False, baseline="Scope: full\n")
    assert any("CHANGELOG" in f for f in rg.gate(root))


def test_deterministic_only_needs_flag(tmp_path, monkeypatch):
    monkeypatch.setattr(rg, "_git_last_commit_ts", lambda paths, root=None: 100)
    root = _repo(tmp_path, baseline="Scope: deterministic-only\n")
    assert any("deterministic-only" in f for f in rg.gate(root))
    assert rg.gate(root, allow_deterministic=True) == []


def test_fresh_full_baseline_passes(tmp_path, monkeypatch):
    # baseline commit (200) newer than last prompt commit (100) -> fresh.
    monkeypatch.setattr(
        rg,
        "_git_last_commit_ts",
        lambda paths, root=None: 200 if any("eval-baseline" in p for p in paths) else 100,
    )
    root = _repo(tmp_path, baseline="Scope: full\nCases: 12/12 pass\n")
    assert rg.gate(root) == []


def test_stale_baseline_fails(tmp_path, monkeypatch):
    # prompt commit (300) newer than baseline commit (200) -> stale.
    monkeypatch.setattr(
        rg,
        "_git_last_commit_ts",
        lambda paths, root=None: 200 if any("eval-baseline" in p for p in paths) else 300,
    )
    root = _repo(tmp_path, baseline="Scope: full\n")
    assert any("STALE" in f for f in rg.gate(root))


def test_no_git_history_fails_safe(tmp_path, monkeypatch):
    monkeypatch.setattr(rg, "_git_last_commit_ts", lambda paths, root=None: None)
    root = _repo(tmp_path, baseline="Scope: full\n")
    assert any("git history unavailable" in f for f in rg.gate(root))
