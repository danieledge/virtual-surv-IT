"""Tests for scripts/dlp_guard.py (T-1, 2026-09-12 test-quality audit).

Before this file, dlp_guard.py had zero unit tests - only a CI end-to-end invocation gated
on the DLP_BLOCKLIST secret (unavailable on fork PRs). These pin the mechanism independent
of that secret: digesting, the exclusion list, token-boundary matching, --rehash, --check,
and the "no blocklist configured yet" no-op fallback.

Every fixture here uses SYNTHETIC placeholder terms ("acme", "acme.com", "jsmith" etc.) -
never anything from this repository's own (gitignored, never-committed) blocklist - so
these tests carry no risk of being the leak the module exists to prevent.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

import scripts.dlp_guard as dg


def _git(root, *args):
    subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,  # nosec B603 B607
    )


def _git_repo(tmp_path):
    """A throwaway git repo so scannable_files() has something real to ask `git` about."""
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "test@example.invalid")
    _git(root, "config", "user.name", "Test")
    return root


# ------------------------------------------------------------------ digest


def test_digest_is_sha256_of_the_lowercased_stripped_term():
    import hashlib

    assert dg.digest("Acme") == hashlib.sha256(b"acme").hexdigest()
    assert dg.digest("  acme  ") == dg.digest("acme")
    assert dg.digest("ACME") == dg.digest("acme")


# ------------------------------------------------------------------ blocklist loading


def test_blocklist_path_prefers_the_env_override(tmp_path, monkeypatch):
    explicit = tmp_path / "somewhere" / "blocklist.txt"
    monkeypatch.setenv("DLP_BLOCKLIST", str(explicit))
    assert dg.blocklist_path(tmp_path) == explicit


def test_blocklist_path_falls_back_to_the_gitignored_local_file(tmp_path, monkeypatch):
    monkeypatch.delenv("DLP_BLOCKLIST", raising=False)
    assert dg.blocklist_path(tmp_path) == tmp_path / dg.BLOCKLIST


def test_missing_blocklist_file_loads_as_empty(tmp_path, monkeypatch):
    monkeypatch.delenv("DLP_BLOCKLIST", raising=False)
    assert dg.load_blocklist(tmp_path) == set()


def test_load_blocklist_keeps_only_well_formed_hex64_lines(tmp_path, monkeypatch):
    monkeypatch.delenv("DLP_BLOCKLIST", raising=False)
    good = dg.digest("acme")
    (tmp_path / dg.BLOCKLIST).write_text(
        "\n".join(
            [
                "# a comment line",
                "",
                good,
                good + "  # trailing comment stripped first",
                "not-hex-at-all",
                "deadbeef",  # right alphabet, wrong length
                "g" * 64,  # right length, not hex
            ]
        ),
        encoding="utf-8",
    )
    loaded = dg.load_blocklist(tmp_path)
    assert loaded == {good}


# ------------------------------------------------------------------ tokenising / scanning


def test_tokens_splits_on_non_alphanumeric_runs_and_lowercases():
    assert list(dg.tokens("ACME_KEY acme.com a@acme.co.uk")) == [
        "acme",
        "key",
        "acme",
        "com",
        "a",
        "acme",
        "co",
        "uk",
    ]


def test_scan_matches_every_documented_shape(tmp_path):
    blocked = {dg.digest("acme")}
    f = tmp_path / "notes.txt"
    f.write_text(
        "\n".join(["ACME_KEY=1", "acme.com", "a@acme.co.uk", "C:\\Users\\acme"]),
        encoding="utf-8",
    )
    hits = dg.scan_file(f, blocked, tmp_path)
    assert len(hits) == 4
    assert all(prefix == dg.digest("acme")[:8] for _lineno, prefix in hits)
    assert [lineno for lineno, _prefix in hits] == [1, 2, 3, 4]


def test_scan_does_not_match_a_term_buried_in_a_larger_token(tmp_path):
    """A hashed list cannot do substring search - this is the documented, deliberate trade."""
    blocked = {dg.digest("acme")}
    f = tmp_path / "notes.txt"
    f.write_text("xacmex\n", encoding="utf-8")
    assert dg.scan_file(f, blocked, tmp_path) == []


def test_scan_never_returns_the_term_itself(tmp_path):
    blocked = {dg.digest("acme")}
    f = tmp_path / "notes.txt"
    f.write_text("acme\n", encoding="utf-8")
    hits = dg.scan_file(f, blocked, tmp_path)
    assert hits == [(1, dg.digest("acme")[:8])]
    for _lineno, prefix in hits:
        assert "acme" not in prefix


@pytest.mark.parametrize("suffix", sorted(dg.SKIP_SUFFIXES))
def test_binary_suffixes_are_never_scanned(tmp_path, suffix):
    blocked = {dg.digest("acme")}
    f = tmp_path / f"asset{suffix}"
    f.write_bytes(b"acme")
    assert dg.scan_file(f, blocked, tmp_path) == []


def test_the_blocklist_and_keyword_files_are_never_scanned(tmp_path):
    blocked = {dg.digest("acme")}
    for name in (dg.BLOCKLIST, dg.KEYWORDS_LOCAL):
        f = tmp_path / name
        f.write_text("acme\n", encoding="utf-8")
        assert dg.scan_file(f, blocked, tmp_path) == []


def test_scan_is_clean_when_nothing_is_blocked(tmp_path):
    f = tmp_path / "notes.txt"
    f.write_text("acme\n", encoding="utf-8")
    assert dg.scan_file(f, set(), tmp_path) == []


# ------------------------------------------------------------------ scannable_files


def test_scannable_files_includes_tracked_and_addable_but_not_ignored(tmp_path):
    root = _git_repo(tmp_path)
    (root / "tracked.txt").write_text("tracked", encoding="utf-8")
    _git(root, "add", "tracked.txt")
    _git(root, "commit", "-q", "-m", "add tracked file")

    (root / "untracked.txt").write_text("untracked", encoding="utf-8")
    (root / ".gitignore").write_text("ignored.txt\n", encoding="utf-8")
    _git(root, "add", ".gitignore")
    _git(root, "commit", "-q", "-m", "add gitignore")
    (root / "ignored.txt").write_text("ignored", encoding="utf-8")

    names = {p.name for p in dg.scannable_files(root)}
    assert "tracked.txt" in names
    assert "untracked.txt" in names
    assert ".gitignore" in names
    assert "ignored.txt" not in names


# ------------------------------------------------------------------ rehash


def test_rehash_writes_digests_never_the_plaintext_term(tmp_path):
    (tmp_path / dg.KEYWORDS_LOCAL).write_text(
        "# a comment\nAcme\n\nacme.co.uk  # trailing note\n", encoding="utf-8"
    )
    code = dg.rehash(tmp_path)
    assert code == 0
    written = (tmp_path / dg.BLOCKLIST).read_text(encoding="utf-8")
    assert "acme" not in written.lower()  # the plaintext term never appears
    assert dg.digest("acme") in written
    assert dg.digest("acme.co.uk") in written


def test_rehash_is_idempotent_on_duplicate_terms(tmp_path):
    (tmp_path / dg.KEYWORDS_LOCAL).write_text("acme\nAcme\nACME\n", encoding="utf-8")
    dg.rehash(tmp_path)
    written = (tmp_path / dg.BLOCKLIST).read_text(encoding="utf-8")
    assert written.count(dg.digest("acme")) == 1


def test_rehash_without_a_keywords_file_is_a_misconfiguration(tmp_path, capsys):
    code = dg.rehash(tmp_path)
    assert code == 2
    assert "not found" in capsys.readouterr().err


def test_rehash_with_only_comments_is_a_misconfiguration(tmp_path, capsys):
    (tmp_path / dg.KEYWORDS_LOCAL).write_text("# nothing but comments\n\n", encoding="utf-8")
    code = dg.rehash(tmp_path)
    assert code == 2
    assert "no terms" in capsys.readouterr().err


# ------------------------------------------------------------------ main(): --check


def _run_main(args, cwd, monkeypatch):
    # Deterministic regardless of ambient environment: the DLP_BLOCKLIST secret is only
    # ever injected into the dedicated CI `dlp-terms` job, never the general test job -
    # but a stray export in a developer's own shell must not leak into these fixtures.
    monkeypatch.delenv("DLP_BLOCKLIST", raising=False)
    monkeypatch.setattr(sys, "argv", ["dlp_guard.py", *args])
    monkeypatch.chdir(cwd)
    return dg.main()


def test_check_reports_blocked_for_a_configured_term(tmp_path, monkeypatch, capsys):
    (tmp_path / dg.KEYWORDS_LOCAL).write_text("acme\n", encoding="utf-8")
    dg.rehash(tmp_path)
    capsys.readouterr()  # discard rehash's own "wrote ... term(s)" line
    code = _run_main(["--check", "acme"], tmp_path, monkeypatch)
    assert code == 0
    assert capsys.readouterr().out.strip() == "blocked"


def test_check_reports_not_blocked_for_an_unconfigured_term(tmp_path, monkeypatch, capsys):
    (tmp_path / dg.KEYWORDS_LOCAL).write_text("acme\n", encoding="utf-8")
    dg.rehash(tmp_path)
    capsys.readouterr()
    code = _run_main(["--check", "totally-different-term"], tmp_path, monkeypatch)
    assert code == 0
    assert capsys.readouterr().out.strip() == "not blocked"


def test_check_never_prints_the_terms_it_was_asked_about(tmp_path, monkeypatch, capsys):
    """--check TERM's own docstring promises this "prints no terms"."""
    (tmp_path / dg.KEYWORDS_LOCAL).write_text("some-blocked-term\n", encoding="utf-8")
    dg.rehash(tmp_path)
    capsys.readouterr()
    _run_main(["--check", "some-blocked-term"], tmp_path, monkeypatch)
    out = capsys.readouterr().out
    assert "some-blocked-term" not in out


# ------------------------------------------------------------------ main(): the no-op fallback


def test_no_blocklist_configured_is_a_noop_not_a_failure(tmp_path, monkeypatch):
    """The repo must stay clonable and committable before anyone has a local keyword file -
    scanning obviously-blockable-shaped content must still exit 0 with nothing configured."""
    monkeypatch.delenv("DLP_BLOCKLIST", raising=False)
    f = tmp_path / "notes.txt"
    f.write_text("anything at all\n", encoding="utf-8")
    code = _run_main([str(f)], tmp_path, monkeypatch)
    assert code == 0


# ------------------------------------------------------------------ main(): scanning files


def test_main_blocks_and_reports_file_and_line_but_not_the_term(tmp_path, monkeypatch, capsys):
    (tmp_path / dg.KEYWORDS_LOCAL).write_text("acme\n", encoding="utf-8")
    dg.rehash(tmp_path)
    f = tmp_path / "leak.txt"
    f.write_text("hello\nACME\n", encoding="utf-8")

    code = _run_main([str(f)], tmp_path, monkeypatch)
    err = capsys.readouterr().err
    assert code == 1
    assert "acme" not in err.lower()
    assert "leak.txt:2" in err
    assert dg.digest("acme")[:8] in err


def test_main_is_clean_when_no_blocked_terms_appear(tmp_path, monkeypatch):
    (tmp_path / dg.KEYWORDS_LOCAL).write_text("acme\n", encoding="utf-8")
    dg.rehash(tmp_path)
    f = tmp_path / "clean.txt"
    f.write_text("nothing of interest here\n", encoding="utf-8")

    code = _run_main([str(f)], tmp_path, monkeypatch)
    assert code == 0


def test_main_all_flag_scans_via_scannable_files(tmp_path, monkeypatch):
    root = _git_repo(tmp_path)
    (root / dg.KEYWORDS_LOCAL).write_text("acme\n", encoding="utf-8")
    dg.rehash(root)
    leak = root / "leak.txt"
    leak.write_text("acme\n", encoding="utf-8")
    _git(root, "add", "leak.txt")
    _git(root, "commit", "-q", "-m", "add leak")

    code = _run_main(["--all"], root, monkeypatch)
    assert code == 1
