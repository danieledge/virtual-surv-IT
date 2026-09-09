"""The preflight table: what the launcher knows before it starts an action.

Built after the 2026-09-10 walkthrough found that nearly every user-facing defect was an
action discovering a precondition halfway through, with each rendering tier inventing its
own way of telling the user, or not telling them.

These run without a terminal, which is the point: the table is testable in a way the
screens that consume it are not.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))

import preflight  # noqa: E402


# ---------------------------------------------------------------- the contract itself


def test_every_check_has_a_predicate_and_a_sentence_for_a_person():
    """A check with no predicate is dead; a sentence naming an internal is useless."""
    for check in preflight.CHECKS:
        assert check.name in preflight._PREDICATES, check.name
        assert check.sentence.endswith("."), check.name
        assert len(check.sentence) > 30, check.name
        assert check.severity in (preflight.BLOCKS, preflight.WARNS), check.name
        # No internals: a person cannot act on an env-var name or a function.
        for internal in ("VIRT_SURV", "None", "()", "_"):
            assert internal not in check.sentence, f"{check.name}: {internal}"


def test_every_action_requires_only_declared_checks():
    for action, names in preflight.REQUIRES.items():
        for name in names:
            assert name in preflight._PREDICATES, f"{action} wants unknown check {name}"


def test_a_check_that_raises_warns_rather_than_blocks(monkeypatch, tmp_path):
    """Rule 1. Refusing to launch because a git call threw would be worse than the thing
    being checked for."""

    def explode(_project_dir):
        raise OSError("the filesystem went away")

    monkeypatch.setitem(preflight._PREDICATES, "clean_tree", explode)
    report = preflight.preflight(tmp_path)

    result = report.result("clean_tree")
    assert result.ok is True
    assert result.undetermined
    assert "OSError" in result.detail


def test_results_are_evaluated_once(monkeypatch, tmp_path):
    """The menu asks the same questions on every repaint and some answers cost a
    subprocess."""
    calls = []

    def counting(_project_dir):
        calls.append(1)
        return True, ""

    monkeypatch.setitem(preflight._PREDICATES, "git", counting)
    report = preflight.preflight(tmp_path)
    for _ in range(5):
        report.ok("git")

    assert len(calls) == 1


# ------------------------------------------------------------------ the actual answers


def test_a_non_repo_fails_git_repo(tmp_path):
    assert preflight.preflight(tmp_path).ok("git_repo") is False


def test_this_repo_passes_the_checks_that_describe_it():
    report = preflight.preflight(REPO_ROOT)
    assert report.ok("git") is True
    assert report.ok("git_repo") is True
    assert report.ok("project_configured") is True
    assert report.ok("not_home_dir") is True


def test_home_directory_warns_but_does_not_block(monkeypatch, tmp_path):
    monkeypatch.setattr(preflight.Path, "home", classmethod(lambda _cls: tmp_path))
    report = preflight.preflight(tmp_path)

    assert report.ok("not_home_dir") is False
    assert report.blocks("configure") is False  # WARNS never blocks
    assert "home directory" in report.why_unavailable("configure")


def test_wrapper_check_is_silent_when_not_launched_through_the_wrapper(monkeypatch, tmp_path):
    """A direct `python virt_team_launcher.py` is not the failure this describes, and
    saying so would be noise on every developer run."""
    monkeypatch.delenv("VIRT_SURV_CD_FILE", raising=False)
    monkeypatch.delenv("VIRT_SURV_VIA_WRAPPER", raising=False)

    assert preflight.preflight(tmp_path).ok("wrapper_current") is True


def test_wrapper_check_fires_for_an_old_wrapper(monkeypatch, tmp_path):
    """VIRT_SURV_CD_FILE is exported by v7 and nothing else, so its absence UNDER the
    wrapper means the exit code is about to be ignored and Esc will launch anyway."""
    monkeypatch.delenv("VIRT_SURV_CD_FILE", raising=False)
    monkeypatch.setenv("VIRT_SURV_VIA_WRAPPER", "1")
    report = preflight.preflight(tmp_path)

    assert report.ok("wrapper_current") is False
    assert report.blocks("new_window") is True
    assert "second session" in report.why_unavailable("new_window")


# ----------------------------------------------------- one answer to "why can I not do this"


def test_why_unavailable_is_empty_when_nothing_is_wrong(monkeypatch, tmp_path):
    for name in preflight.REQUIRES["update"]:
        monkeypatch.setitem(preflight._PREDICATES, name, lambda _d: (True, ""))

    assert preflight.preflight(tmp_path).why_unavailable("update") == ""


def test_why_unavailable_reports_the_blocking_failure_before_a_warning(monkeypatch, tmp_path):
    """A dimmed row shows ONE sentence, so it must be the one that matters."""
    monkeypatch.setitem(preflight._PREDICATES, "not_home_dir", lambda _d: (False, ""))
    monkeypatch.setitem(preflight._PREDICATES, "config_writable", lambda _d: (False, ""))
    report = preflight.preflight(tmp_path)

    assert "not writable" in report.why_unavailable("configure")  # BLOCKS wins over WARNS


def test_update_explains_a_dirty_tree_rather_than_promising_a_stash(monkeypatch, tmp_path):
    """The live defect this check exists for: the update screen said uncommitted changes
    "are stashed and restored", and the run it started refused to touch a dirty tree."""
    monkeypatch.setitem(preflight._PREDICATES, "git", lambda _d: (True, ""))
    monkeypatch.setitem(preflight._PREDICATES, "git_repo", lambda _d: (True, ""))
    monkeypatch.setitem(preflight._PREDICATES, "upstream", lambda _d: (True, ""))
    monkeypatch.setitem(preflight._PREDICATES, "clean_tree", lambda _d: (False, "3 changed files"))
    report = preflight.preflight(tmp_path)

    assert report.blocks("update") is True
    assert "commit or stash first" in report.why_unavailable("update")
    assert report.result("clean_tree").detail == "3 changed files"


def test_an_unknown_action_requires_nothing_and_blocks_nothing(tmp_path):
    """Callers pass action names; a typo must not silently disable a menu row."""
    report = preflight.preflight(tmp_path)
    assert report.blocks("no-such-action") is False
    assert report.why_unavailable("no-such-action") == ""
