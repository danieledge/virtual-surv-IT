"""Promotion gate (scripts/release_gate.py): version consistency, eval-baseline presence,
deterministic-only escape hatch, the machine-readable verdict block (slice floor, results-log
corroboration, multi-block rejection), and baseline freshness vs prompt commits AND the
working tree."""

from __future__ import annotations

import json

import scripts.release_gate as rg

_RUN = "20260801T190159Z"
# Six cases, all passing raw - the smallest slice the gate accepts (rg._MIN_SLICE_CASES).
_CASES = [f"process-case-{n}" for n in range(6)]

_CLEAN_VERDICT = (
    "```eval-verdict\n"
    "verdict: pass\n"
    "cases_total: 6\n"
    "cases_passed_raw: 6\n"
    "cases_adjudicated_pass: 0\n"
    "unadjudicated_failures: 0\n"
    f"runs: {_RUN}\n"
    "```\n"
)


def _results_log(passed=len(_CASES), run=_RUN, total=len(_CASES)):
    """One results.jsonl row per case, the first `passed` of `total` recorded as raw passes."""
    return (
        "\n".join(
            json.dumps({"run_id": run, "case": case, "mode": "run", "passed": index < passed})
            for index, case in enumerate(_CASES[:total])
        )
        + "\n"
    )


def _log_matching(verdict):
    """A results log that corroborates whatever `verdict` declares (the honest-baseline case)."""
    fields = rg.parse_verdict(verdict or "") or {}
    total, passed = fields.get("cases_total", ""), fields.get("cases_passed_raw", "")
    if not (total.isdigit() and passed.isdigit()):
        return _results_log()
    return _results_log(passed=int(passed), total=int(total))


def _repo(
    tmp_path,
    version="1.2.3",
    badge=None,
    changelog=True,
    baseline=None,
    verdict=_CLEAN_VERDICT,
    results=None,
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
    (tmp_path / "evals" / "results.jsonl").write_text(
        _log_matching(verdict) if results is None else results, encoding="utf-8"
    )
    if baseline is not None:
        (tmp_path / "evals" / f"eval-baseline-{version}.md").write_text(
            baseline + (verdict or ""), encoding="utf-8"
        )
    return tmp_path


def _clean_tree(monkeypatch):
    """No uncommitted prompt edits (the tmp repos are not git repos at all)."""
    monkeypatch.setattr(rg, "_git_dirty_paths", lambda paths, root=None: [])


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
    _clean_tree(monkeypatch)
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
    _clean_tree(monkeypatch)
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
    _clean_tree(monkeypatch)


def _verdict(**over):
    fields = {
        "verdict": "pass-with-adjudication",
        "cases_total": 6,
        "cases_passed_raw": 1,
        "cases_adjudicated_pass": 5,
        "unadjudicated_failures": 0,
        "runs": _RUN,
    }
    fields.update(over)
    body = "\n".join(f"{k}: {v}" for k, v in fields.items())
    return f"```eval-verdict\n# drafted by scripts.eval_engage\n{body}\n```\n"


def test_parse_verdict_reads_fields_and_ignores_comments():
    fields = rg.parse_verdict("prose\n" + _verdict() + "\nmore prose\n")
    assert fields["verdict"] == "pass-with-adjudication"
    assert fields["cases_total"] == "6"
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
        verdict=_verdict(cases_adjudicated_pass=3, unadjudicated_failures=2),
    )
    assert any("UNADJUDICATED" in f for f in rg.gate(root))


def test_declared_fail_fails(tmp_path, monkeypatch):
    _fresh(monkeypatch)
    root = _repo(
        tmp_path,
        baseline="Scope: full\n",
        verdict=_verdict(verdict="fail"),
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


# --- the verdict must be corroborated, not self-reported (2026-08-01 review) --------------
def test_one_case_slice_cannot_promote(tmp_path, monkeypatch):
    # The degenerate claim the gate used to accept: one case, passed, verdict pass.
    _fresh(monkeypatch)
    root = _repo(
        tmp_path,
        baseline="Scope: full\n",
        verdict=_verdict(verdict="pass", cases_total=1, cases_passed_raw=1, cases_adjudicated_pass=0),
    )
    assert any("stands on 1 case(s)" in f for f in rg.gate(root))


def test_narrow_slice_promotes_only_with_the_explicit_flag(tmp_path, monkeypatch):
    _fresh(monkeypatch)
    verdict = _verdict(verdict="pass", cases_total=2, cases_passed_raw=2, cases_adjudicated_pass=0)
    root = _repo(tmp_path, baseline="Scope: full\n", verdict=verdict)
    assert any("--min-cases" in f for f in rg.gate(root))
    assert rg.gate(root, min_cases=2) == []


def test_min_cases_flag_parsing():
    assert rg.parse_min_cases(["--allow-deterministic"]) == (None, None)
    assert rg.parse_min_cases(["--min-cases", "3"]) == (3, None)
    assert rg.parse_min_cases(["--min-cases=4"]) == (4, None)
    value, error = rg.parse_min_cases(["--min-cases", "lots"])
    assert value is None and "whole number" in error


def test_verdict_without_runs_is_self_reported(tmp_path, monkeypatch):
    _fresh(monkeypatch)
    root = _repo(tmp_path, baseline="Scope: full\n", verdict=_verdict(runs=""))
    assert any("names no 'runs:'" in f for f in rg.gate(root))


def test_deterministic_only_baseline_needs_no_runs(tmp_path, monkeypatch):
    # A pytest + scorer record has no live runs to cite; the slice floor still applies.
    _fresh(monkeypatch)
    root = _repo(
        tmp_path, baseline="Scope: deterministic-only\n", verdict=_verdict(runs="")
    )
    assert rg.gate(root, allow_deterministic=True) == []


def test_unrecorded_run_id_fails(tmp_path, monkeypatch):
    _fresh(monkeypatch)
    root = _repo(
        tmp_path,
        baseline="Scope: full\n",
        verdict=_verdict(runs="20260101T000000Z"),
        results=_results_log(passed=1),
    )
    assert any("no rows in" in f for f in rg.gate(root))


def test_inflated_case_count_fails(tmp_path, monkeypatch):
    # Block claims 6 cases; the log records 4 for the cited run.
    _fresh(monkeypatch)
    root = _repo(
        tmp_path,
        baseline="Scope: full\n",
        verdict=_verdict(),
        results=_results_log(passed=1, total=4),
    )
    assert any("record 4 distinct case(s)" in f for f in rg.gate(root))


def test_inflated_raw_pass_count_fails(tmp_path, monkeypatch):
    _fresh(monkeypatch)
    root = _repo(
        tmp_path,
        baseline="Scope: full\n",
        verdict=_verdict(verdict="pass", cases_passed_raw=6, cases_adjudicated_pass=0),
        results=_results_log(passed=2),
    )
    assert any("passing raw" in f for f in rg.gate(root))


def test_missing_results_log_blocks_a_run_citing_baseline(tmp_path, monkeypatch):
    _fresh(monkeypatch)
    root = _repo(tmp_path, baseline="Scope: full\n")
    (root / "evals" / "results.jsonl").unlink()
    assert any("missing or unreadable" in f for f in rg.gate(root))


def test_corrupt_results_log_is_reported(tmp_path, monkeypatch):
    _fresh(monkeypatch)
    root = _repo(tmp_path, baseline="Scope: full\n", results=_results_log() + "not json\n")
    assert any("unparseable" in f for f in rg.gate(root))


def test_a_case_passing_in_any_cited_run_counts_once(tmp_path, monkeypatch):
    # Rerun of one case in a second cited run: still 6 distinct cases, 2 raw passes.
    _fresh(monkeypatch)
    rerun = json.dumps(
        {"run_id": "20260801T204756Z", "case": _CASES[1], "mode": "run", "passed": True}
    )
    root = _repo(
        tmp_path,
        baseline="Scope: full\n",
        verdict=_verdict(cases_passed_raw=2, cases_adjudicated_pass=4, runs=f"{_RUN}, 20260801T204756Z"),
        results=_results_log(passed=1) + rerun + "\n",
    )
    assert rg.gate(root) == []


def test_two_verdict_blocks_are_rejected(tmp_path, monkeypatch):
    # report.md tells the human to paste its drafted block, so a leftover raw draft above the
    # adjudicated one is a realistic accident - the gate refuses to pick a claim.
    _fresh(monkeypatch)
    draft = _verdict(verdict="fail", cases_passed_raw=1, cases_adjudicated_pass=0,
                     unadjudicated_failures=5)
    root = _repo(tmp_path, baseline="Scope: full\n", verdict=draft + "\nprose\n" + _verdict())
    findings = rg.gate(root)
    assert any("more than one" in f for f in findings)


# --- freshness the commit log cannot see -------------------------------------------------
def test_uncommitted_prompt_edit_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(
        rg,
        "_git_last_commit_ts",
        lambda paths, root=None: 200 if any("eval-baseline" in p for p in paths) else 100,
    )
    monkeypatch.setattr(
        rg, "_git_dirty_paths", lambda paths, root=None: [".claude/agents/code-reviewer.md"]
    )
    root = _repo(tmp_path, baseline="Scope: full\n")
    assert any("UNCOMMITTED prompt changes" in f for f in rg.gate(root))


def test_unavailable_git_status_fails_safe(tmp_path, monkeypatch):
    monkeypatch.setattr(
        rg,
        "_git_last_commit_ts",
        lambda paths, root=None: 200 if any("eval-baseline" in p for p in paths) else 100,
    )
    monkeypatch.setattr(rg, "_git_dirty_paths", lambda paths, root=None: None)
    root = _repo(tmp_path, baseline="Scope: full\n")
    assert any("git status" in f for f in rg.gate(root))


def test_git_dirty_paths_reads_porcelain(tmp_path, monkeypatch):
    class _Done:
        returncode = 0
        stdout = " M .claude/agents/code-reviewer.md\n?? .claude/skills/new/SKILL.md\nR  a -> b\n"

    monkeypatch.setattr(rg.subprocess, "run", lambda *a, **k: _Done())
    assert rg._git_dirty_paths([".claude"], tmp_path) == [
        ".claude/agents/code-reviewer.md",
        ".claude/skills/new/SKILL.md",
        "b",
    ]


def test_git_dirty_paths_against_a_real_repo(tmp_path):
    # The porcelain parse is only worth as much as the real git output it sees.
    import subprocess

    git = ["git", "-C", str(tmp_path), "-c", "user.email=t@t.com", "-c", "user.name=t"]
    subprocess.run(["git", "init", "-q", "-b", "dev", str(tmp_path)], check=True)
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "settings.json").write_text("{}\n", encoding="utf-8")
    subprocess.run([*git, "add", "-A"], check=True)
    subprocess.run([*git, "commit", "-qm", "init"], check=True)
    assert rg._git_dirty_paths([".claude"], tmp_path) == []

    (tmp_path / ".claude" / "settings.json").write_text('{"hooks": {}}\n', encoding="utf-8")
    (tmp_path / ".claude" / "agents").mkdir()
    (tmp_path / ".claude" / "agents" / "new.md").write_text("x\n", encoding="utf-8")
    assert rg._git_dirty_paths([".claude"], tmp_path) == [
        ".claude/agents/new.md",
        ".claude/settings.json",
    ]


def test_git_dirty_paths_none_when_git_unavailable(tmp_path, monkeypatch):
    def _boom(*args, **kwargs):
        raise OSError("no git")

    monkeypatch.setattr(rg.subprocess, "run", _boom)
    assert rg._git_dirty_paths([".claude"], tmp_path) is None


def test_hooks_settings_and_scope_age_a_baseline():
    # The guard hooks and the settings that arm them ARE behaviour under eval (injection and
    # consent cases); scope-and-stack supplies the jurisdictions every deliverable cites.
    for path in (
        ".claude/hooks",
        ".claude/settings.json",
        "docs/scope-and-stack.md",
        "docs/coding-standards.md",
        "docs/templates",
    ):
        assert path in rg._PROMPT_PATHS


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
