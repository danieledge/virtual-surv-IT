"""The 2026-09-10 coverage audit: fixes to the surface outside `virt-surv go`.

Two earlier reviews were scoped to the launcher TUI, so roughly 77 of the ~90 entry points
and menu options had never been examined: every argparse flag, all eight positional
subcommands, and the diagnostics, advanced, extensions, alias and model submenus. These pin
what that audit found and what was changed.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


# ============================================================== --demo must not write


def test_demo_does_not_install_an_org_extensions_contract(monkeypatch, capsys, tmp_path):
    """--extensions landed in 2026-08-27, AFTER the pass that gated its six neighbours, so
    it inherited exactly the bug that pass fixed: --demo wrote for real."""
    import install_helper as ih

    called = []
    monkeypatch.setattr(
        ih, "run_install_extensions", lambda *a, **k: called.append(a) or 0
    )

    contract = tmp_path / "team-extensions.md"
    contract.write_text("# Team extensions\n", encoding="utf-8")

    rc = ih._main(["--demo", "--extensions", str(contract)])

    assert rc == 0
    assert called == [], "demo performed the real install"
    assert "would install" in capsys.readouterr().out


# ================================================ extensions read from the right place


def test_extensions_script_runs_from_the_clone_and_reads_the_users_project(monkeypatch, tmp_path):
    """Options 1 and 4 ran `-m scripts.extensions` with no cwd, so from a project folder
    the import failed ("no extensions resolved" plus a traceback tail) and from the clone
    root it resolved the CLONE's contract while the row promised this directory's."""
    import install_helper as ih

    seen = {}

    class _Proc:
        stdout = "ok"
        stderr = ""

    def fake_run(argv, cwd=None, timeout=None):
        seen["argv"] = argv
        seen["cwd"] = cwd
        seen["project"] = ih.os.environ.get("CLAUDE_PROJECT_DIR")
        return _Proc()

    monkeypatch.setattr(ih, "run_cmd", fake_run)
    monkeypatch.chdir(tmp_path)

    ih._run_team_script(["extensions", "show"], ih.Style(False))

    assert seen["cwd"] is not None, "no cwd: the module import would fail from a project"
    assert (Path(seen["cwd"]) / "scripts" / "extensions.py").is_file()
    assert seen["project"] == str(tmp_path), "the user's project must be the project tier"


def test_the_project_env_var_is_restored_afterwards(monkeypatch, tmp_path):
    """It is set around one call, not leaked into the rest of the session."""
    import install_helper as ih

    class _Proc:
        stdout = ""
        stderr = ""

    monkeypatch.setattr(ih, "run_cmd", lambda *a, **k: _Proc())
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.chdir(tmp_path)

    ih._run_team_script(["extensions", "check"], ih.Style(False))

    assert ih.os.environ.get("CLAUDE_PROJECT_DIR") is None




# NOT UNIT-TESTED HERE, deliberately: `_run_go` in install_helper.py.
#
# Two behaviours were fixed in it on 2026-09-10 - it now honours the launcher's exit 97
# ("launch nothing", so Esc no longer opens a session from this path) and no longer imposes
# a 120-second timeout on an interactive menu (someone who paused to think got an empty
# decision and a session with no prompt).
#
# Both were left untested after three attempts, each of which reached the REAL `claude`
# binary and spent credit: the function probes interpreters, checks for updates, resolves a
# launch command and then launches, and stubbing subprocess.run plus run_cmd plus
# check_for_update_upfront still was not enough to contain it. A test that invokes the
# product under test for real is a false result and somebody's money, and a partially
# stubbed one proves nothing about the code anyway.
#
# What would make it testable is splitting the decision from the launch: a
# `_go_decision(...) -> str | None` that returns None for "launch nothing" and a caller
# that acts on it. That is the right shape and a bigger change than this pass. Until then
# this path is covered by the fix being small and by hand-checking, and that is stated
# rather than papered over with a source-inspection assertion.


# ====================================================== an unmeasurable bash is not slow


def test_bashrc_is_not_edited_when_the_probe_could_not_run_bash(monkeypatch, capsys):
    import install_helper as ih

    monkeypatch.setattr(ih, "find_bash", lambda: "/bin/bash")
    monkeypatch.setattr(
        ih,
        "_check_shell_startup_time",
        lambda bash_path: ("ERROR", "failed to launch /bin/bash: [Errno 2]"),
    )
    calls = []
    monkeypatch.setattr(
        ih, "run_fix_bashrc", lambda *a, **k: calls.append(1) or 0
    )

    inst = ih.Installer(_surface_args(ih), ih.Style(False), ih.marks(), subset="full")
    inst.fixbashrc_step()

    assert calls == [], "edited ~/.bashrc on a probe failure"
    assert "could not run bash" in capsys.readouterr().out


def test_a_genuinely_slow_bashrc_is_still_fixed(monkeypatch):
    """ERROR carries BOTH meanings, so the guard has to be narrow: 10s or slower is the
    case the whole step exists for."""
    import install_helper as ih

    monkeypatch.setattr(ih, "find_bash", lambda: "/bin/bash")
    monkeypatch.setattr(
        ih,
        "_check_shell_startup_time",
        lambda bash_path: ("ERROR", "12.0s to source ~/.bashrc non-interactively - run ..."),
    )
    calls = []
    monkeypatch.setattr(ih, "run_fix_bashrc", lambda *a, **k: calls.append(1) or 0)

    inst = ih.Installer(_surface_args(ih), ih.Style(False), ih.marks(), subset="full")
    inst.fixbashrc_step()

    assert calls == [1]


def _surface_args(ih):
    import argparse

    ns = argparse.Namespace()
    for name, value in (
        ("yes", True),
        ("demo", False),
        ("repo", None),
        ("branch", None),
        ("pip", False),
        ("statusline", False),
        ("model", None),
    ):
        setattr(ns, name, value)
    return ns


# ============================================================== help documents the surface


def test_the_epilog_names_every_positional_subcommand():
    """Five of the eight were dispatched but undocumented, so the only way to learn they
    existed was to read the dispatcher."""
    import install_helper as ih

    source = Path(ih.__file__).read_text(encoding="utf-8")
    start = source.index('description="Install or update')
    epilog = source[start : start + 1200]

    for subcommand in ("go", "engage", "configure", "onboard", "archive", "evidence"):
        assert subcommand in epilog, subcommand


# ================================================ a clone the tool dirtied must still update


def test_the_tools_own_config_is_reset_rather_than_blocking_an_update():
    """User report, 2026-09-10: "the stash question ... they haven't intentionally written
    anything to the plugin directory".

    They had not. `.claude/settings.json` and `.claude/team-preferences.json` are TRACKED
    and the tool writes them itself - configure, a model change, any settings toggle - so
    the clone went dirty on its own and the next update refused over edits that were never
    the user's. These files are the shipped defaults, so an update takes the incoming
    version.
    """
    import install_helper as ih

    assert ".claude/settings.json" in ih._SELF_OWNED_CONFIG
    assert ".claude/team-preferences.json" in ih._SELF_OWNED_CONFIG
    # Narrow on purpose: everything else in the tree belongs to the user and is stashed
    # and restored, never discarded.
    assert len(ih._SELF_OWNED_CONFIG) == 2


def test_settings_backups_are_ignored_so_they_cannot_dirty_a_clone():
    """Each settings write drops a dated settings.json.bak-<date> beside its target. None
    of those shapes were ignored, so every configure run also left untracked files."""
    import subprocess

    for candidate in (
        ".claude/settings.json.bak",
        ".claude/settings.json.bak-2026-09-10",
        ".claude/settings.json.bak-2026-09-10.2",
    ):
        done = subprocess.run(
            ["git", "check-ignore", "-q", candidate],
            cwd=str(REPO_ROOT),
            capture_output=True,
        )
        assert done.returncode == 0, f"{candidate} is not ignored"


def test_no_backup_file_is_tracked_in_the_repo():
    """A .bak is a backup by definition and never belongs in the history."""
    import subprocess

    tracked = subprocess.run(
        ["git", "ls-files"], cwd=str(REPO_ROOT), capture_output=True, text=True
    ).stdout.splitlines()
    offenders = [p for p in tracked if ".bak" in p]

    assert offenders == [], f"backup files in version control: {offenders}"
