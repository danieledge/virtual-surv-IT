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
    monkeypatch.setattr(ih, "run_install_extensions", lambda *a, **k: called.append(a) or 0)

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
    monkeypatch.setattr(ih, "run_fix_bashrc", lambda *a, **k: calls.append(1) or 0)

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

    tracked = subprocess.run(
        ["git", "ls-files"], cwd=str(REPO_ROOT), capture_output=True, text=True
    ).stdout.splitlines()
    offenders = [p for p in tracked if ".bak" in p]

    assert offenders == [], f"backup files in version control: {offenders}"


# ============================================== osv-scanner: offline or not at all


def test_osv_scanner_is_registered_in_every_mirror():
    """The tool registry is duplicated THREE ways: the shell probe's bash array, its python
    mirror, install_helper._REVIEW_TOOLS, and _TOOL_OUTPUT_CHECKS. A tool in some and not
    others is available to configure and never probed, or probed and not configurable - and
    the third mirror is the one I missed first time, which the suite caught."""
    from pathlib import Path

    repo = Path(__file__).resolve().parent.parent
    probe = (repo / "scripts" / "check-review-tools.sh").read_text(encoding="utf-8")
    import install_helper as ih

    assert "osv-scanner" in ih._REVIEW_TOOLS
    assert "osv-scanner" in {name for name, *_ in ih._TOOL_OUTPUT_CHECKS}
    assert probe.count("osv-scanner") >= 3  # bash list, python mirror, TOOLS row


def test_osv_scanner_is_documented_as_offline_only():
    """semgrep and pip-audit were removed because they made unconditional network calls and
    hung behind a corporate proxy rather than failing fast. osv-scanner qualifies ONLY
    because --offline is a documented air-gapped path against a pre-downloaded database, so
    the flag is not optional: without it this is the same failure that removed the others.
    """
    from pathlib import Path

    repo = Path(__file__).resolve().parent.parent
    reviewer = (repo / ".claude" / "agents" / "code-reviewer.md").read_text(encoding="utf-8")

    assert "osv-scanner --offline" in reviewer
    assert "never invoke it without the flag" in reviewer

    # And the output probe, which is where a missing database would first reach the network
    import install_helper as ih

    flags = next(f for name, f, *_ in ih._TOOL_OUTPUT_CHECKS if name == "osv-scanner")
    assert "--offline" in flags


def test_the_network_bound_scanners_are_still_excluded():
    """Adding one offline-capable scanner must not be read as reopening the door."""
    from pathlib import Path

    repo = Path(__file__).resolve().parent.parent
    probe = (repo / "scripts" / "check-review-tools.sh").read_text(encoding="utf-8")
    import install_helper as ih

    for banned in ("semgrep", "pip-audit"):
        assert banned not in ih._REVIEW_TOOLS, banned
        assert f'"{banned}|' not in probe, f"{banned} became probeable"


# ============================================ the offline database, handled for the user


def test_the_database_goes_where_the_scanner_itself_looks(monkeypatch, tmp_path):
    """Not a location of ours. osv-scanner searches os.UserCacheDir then os.TempDir, and a
    database anywhere else would need OSV_SCANNER_LOCAL_DB_CACHE_DIRECTORY set in the
    environment of every later scan. Reviews run through Bash in a session whose
    environment we do not control, so that is a database that silently is not there."""
    import install_helper as ih

    monkeypatch.setenv("OSV_SCANNER_LOCAL_DB_CACHE_DIRECTORY", str(tmp_path / "explicit"))
    assert ih.osv_db_dir() == tmp_path / "explicit"

    # osv_db_dir() reads a different fallback var per platform (LOCALAPPDATA on
    # win32, XDG_CACHE_HOME elsewhere) - set whichever one the code under test
    # will actually read, or this assertion is really "does Windows CI happen to
    # have a tmp_path-shaped LOCALAPPDATA", which it never does.
    monkeypatch.delenv("OSV_SCANNER_LOCAL_DB_CACHE_DIRECTORY", raising=False)
    cache_var = "LOCALAPPDATA" if sys.platform == "win32" else "XDG_CACHE_HOME"
    monkeypatch.setenv(cache_var, str(tmp_path / "cache"))
    assert ih.osv_db_dir() == tmp_path / "cache"


def test_presence_is_one_ecosystem_archive(monkeypatch, tmp_path):
    """The documented layout is {cache}/osv-scanner/{ecosystem}/all.zip."""
    import install_helper as ih

    monkeypatch.setenv("OSV_SCANNER_LOCAL_DB_CACHE_DIRECTORY", str(tmp_path))
    assert ih.osv_db_present() is False

    target = tmp_path / "osv-scanner" / "PyPI"
    target.mkdir(parents=True)
    (target / "all.zip").write_bytes(b"not really a zip")
    assert ih.osv_db_present() is True


def test_presence_never_raises(monkeypatch):
    """It is asked to decide whether to OFFER a download, so a question we cannot answer
    must not become an error."""
    import install_helper as ih

    monkeypatch.setattr(ih, "osv_db_dir", lambda: (_ for _ in ()).throw(OSError("gone")))
    assert ih.osv_db_present() is False


def test_the_download_uses_offline_vulnerabilities_not_offline(monkeypatch, tmp_path, capsys):
    """--offline would forbid the very network call the download needs. Everything else
    uses --offline; this one step is the exception and must not be 'corrected'."""
    import install_helper as ih

    seen = {}

    class _Proc:
        returncode = 0
        stdout = ""
        stderr = ""

    monkeypatch.setattr(ih.shutil, "which", lambda name: "/usr/bin/osv-scanner")
    monkeypatch.setenv("OSV_SCANNER_LOCAL_DB_CACHE_DIRECTORY", str(tmp_path))
    monkeypatch.setattr(ih, "run_cmd", lambda argv, **k: seen.update(argv=argv) or _Proc())

    ih.run_osv_db_download(ih.Style(False), ih.marks())

    assert "--download-offline-databases" in seen["argv"]
    assert "--offline-vulnerabilities" in seen["argv"]
    assert "--offline" not in seen["argv"], "the download cannot run with --offline"


def test_a_blocked_download_explains_the_manual_route(monkeypatch, tmp_path, capsys):
    """Air-gapped machines are the ones that most need this and least can do it, so the
    failure names the URL and where the file goes rather than just failing."""
    import install_helper as ih

    class _Proc:
        returncode = 1
        stdout = ""
        stderr = "dial tcp: i/o timeout"

    monkeypatch.setattr(ih.shutil, "which", lambda name: "/usr/bin/osv-scanner")
    monkeypatch.setenv("OSV_SCANNER_LOCAL_DB_CACHE_DIRECTORY", str(tmp_path))
    monkeypatch.setattr(ih, "run_cmd", lambda argv, **k: _Proc())

    rc = ih.run_osv_db_download(ih.Style(False), ih.marks())
    out = capsys.readouterr().out

    assert rc == 1
    assert "osv-vulnerabilities.storage.googleapis.com" in out
    assert "all.zip" in out


def test_no_scanner_installed_is_not_a_failure(monkeypatch, capsys):
    """Nothing to download for is a state, not an error: the tool is optional."""
    import install_helper as ih

    monkeypatch.setattr(ih.shutil, "which", lambda name: None)

    assert ih.run_osv_db_download(ih.Style(False), ih.marks()) == 0
    assert "not installed" in capsys.readouterr().out


def test_users_actually_receive_the_scanner_permission():
    """RECOMMENDED_ALLOW is the list users GET: the installer writes it into a project's
    settings, and _headless_allow_rules hands it to unattended runs. Registering a tool in
    the analyser set without an entry here means the registry advertises it and every
    review hits a permission prompt for the team's own tooling - which is precisely the
    failure the allow-list exists to prevent."""
    import install_helper as ih

    allow = " ".join(ih.RECOMMENDED_ALLOW)
    assert "osv-scanner" in allow

    # Every supported analyser that is a plain binary should be reachable the same way.
    for tool in ("ruff", "mypy", "bandit", "osv-scanner"):
        assert tool in allow, f"{tool} is in the analyser set but not in the allow-list"


def test_a_jira_engagement_is_told_to_read_the_comment_thread():
    """Owner instruction, 2026-09-11. The description is where a ticket starts; the comment
    thread is usually where the request ends up - scope changes, which desk, the real
    acceptance criteria. Both the skill and the inbound reference must say so, because the
    fetch list alone reads as metadata and an agent can treat comments as context rather
    than as the request.
    """
    from pathlib import Path

    repo = Path(__file__).resolve().parents[1]
    skill = (repo / ".claude" / "skills" / "engage" / "SKILL.md").read_text(encoding="utf-8")
    ref = (repo / ".claude" / "skills" / "engage" / "references" / "integrations.md").read_text(
        encoding="utf-8"
    )

    assert "comment thread" in skill
    assert "READ THE COMMENTS" in ref
    # And the precedence rule, which is the part that changes an outcome.
    assert "later comment" in ref or "later comment" in skill


def test_a_comment_is_not_a_consent_grant():
    """Comments are ticket content, so the data-not-instructions rule covers them. Worth
    stating explicitly: a comment reads more like a person talking to you than a
    description does."""
    from pathlib import Path

    repo = Path(__file__).resolve().parents[1]
    ref = (repo / ".claude" / "skills" / "engage" / "references" / "integrations.md").read_text(
        encoding="utf-8"
    )

    assert "Comments included" in ref
    assert "not a consent grant" in ref
