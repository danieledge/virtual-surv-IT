"""Promotion gate (scripts/release_gate.py): version consistency, eval-baseline presence,
deterministic-only escape hatch, the machine-readable verdict block, and baseline freshness
vs prompt commits."""

from __future__ import annotations

import scripts.release_gate as rg

_CLEAN_VERDICT = (
    "```eval-verdict\n"
    "verdict: pass\n"
    "cases_total: 3\n"
    "cases_passed_raw: 3\n"
    "cases_adjudicated_pass: 0\n"
    "unadjudicated_failures: 0\n"
    "```\n"
)


def _repo(
    tmp_path, version="1.2.3", badge=None, changelog=True, baseline=None, verdict=_CLEAN_VERDICT
):
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
        (tmp_path / "evals" / f"eval-baseline-{version}.md").write_text(
            baseline + (verdict or ""), encoding="utf-8"
        )
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


# --- the machine-readable verdict block (2026-08-01 audit) ------------------------------
def _fresh(monkeypatch):
    monkeypatch.setattr(
        rg,
        "_git_last_commit_ts",
        lambda paths, root=None: 200 if any("eval-baseline" in p for p in paths) else 100,
    )


def _verdict(**over):
    fields = {
        "verdict": "pass-with-adjudication",
        "cases_total": 3,
        "cases_passed_raw": 1,
        "cases_adjudicated_pass": 2,
        "unadjudicated_failures": 0,
    }
    fields.update(over)
    body = "\n".join(f"{k}: {v}" for k, v in fields.items())
    return f"```eval-verdict\n# drafted by scripts.eval_engage\n{body}\n```\n"


def test_parse_verdict_reads_fields_and_ignores_comments():
    fields = rg.parse_verdict("prose\n" + _verdict() + "\nmore prose\n")
    assert fields["verdict"] == "pass-with-adjudication"
    assert fields["cases_total"] == "3"
    assert "#" not in "".join(fields)


def test_parse_verdict_absent_is_none():
    assert rg.parse_verdict("# baseline\n\nNo clean-pass claim is made.\n") is None


def test_parse_verdict_takes_the_first_block_only():
    fields = rg.parse_verdict(_verdict() + _verdict(verdict="pass", cases_passed_raw=3))
    assert fields["verdict"] == "pass-with-adjudication"


def test_baseline_without_verdict_block_fails(tmp_path, monkeypatch):
    _fresh(monkeypatch)
    # The 0.33.1 shape: a prose record that explicitly declines to claim a pass.
    root = _repo(
        tmp_path,
        baseline="Scope: full\n\n**No clean-pass claim is made for this baseline.**\n",
        verdict="",
    )
    assert any("no machine-readable" in f for f in rg.gate(root))


def test_adjudicated_verdict_passes(tmp_path, monkeypatch):
    _fresh(monkeypatch)
    root = _repo(tmp_path, baseline="Scope: full\n", verdict=_verdict())
    assert rg.gate(root) == []


def test_unadjudicated_failures_fail(tmp_path, monkeypatch):
    _fresh(monkeypatch)
    root = _repo(
        tmp_path,
        baseline="Scope: full\n",
        verdict=_verdict(cases_adjudicated_pass=0, unadjudicated_failures=2),
    )
    assert any("UNADJUDICATED" in f for f in rg.gate(root))


def test_declared_fail_fails(tmp_path, monkeypatch):
    _fresh(monkeypatch)
    root = _repo(
        tmp_path,
        baseline="Scope: full\n",
        verdict=_verdict(verdict="fail", cases_adjudicated_pass=2),
    )
    assert any("declares 'verdict: fail'" in f for f in rg.gate(root))


def test_counts_must_add_up(tmp_path, monkeypatch):
    _fresh(monkeypatch)
    root = _repo(tmp_path, baseline="Scope: full\n", verdict=_verdict(cases_total=9))
    assert any("do not add up" in f for f in rg.gate(root))


def test_clean_pass_claim_needs_clean_raw_pass(tmp_path, monkeypatch):
    _fresh(monkeypatch)
    root = _repo(tmp_path, baseline="Scope: full\n", verdict=_verdict(verdict="pass"))
    assert any("passed RAW" in f for f in rg.gate(root))


def test_non_numeric_and_unknown_verdict_flagged(tmp_path, monkeypatch):
    _fresh(monkeypatch)
    root = _repo(
        tmp_path,
        baseline="Scope: full\n",
        verdict=_verdict(verdict="probably fine", cases_total="most"),
    )
    findings = rg.gate(root)
    assert any("is not one of" in f for f in findings)
    assert any("not a whole number" in f for f in findings)


def test_deterministic_only_still_needs_a_verdict(tmp_path, monkeypatch):
    _fresh(monkeypatch)
    root = _repo(tmp_path, baseline="Scope: deterministic-only\n", verdict="")
    assert any("no machine-readable" in f for f in rg.gate(root, allow_deterministic=True))


def test_standing_instruction_docs_age_a_baseline():
    # A DoD / house-rules / ways-of-working / review-method edit steers the team exactly as
    # a skill edit does; before 2026-08-01 none of them aged a baseline.
    for path in (
        "docs/DEFINITION-OF-DONE.md",
        "docs/house-rules.md",
        "docs/WAYS-OF-WORKING.md",
        "docs/code-review-method.md",
    ):
        assert path in rg._PROMPT_PATHS
