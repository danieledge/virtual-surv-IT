"""`virt-surv go`'s decision engine (scripts/virt_team_launcher.py).

Runs OUTSIDE Claude Code entirely, before a session starts - moves the resume-vs-new
decision (observed unreliable when left to the model's own AskUserQuestion menu) and the
tool-inventory cache refresh (a machine-level fact, not a per-engagement one) out of the
LLM pipeline. Output contract is load-bearing: interactive text goes to stderr, ONLY the
final decision string goes to stdout - a shell caller captures stdout via command
substitution and must never see the interactive transcript mixed in.
"""

from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location(
        "virt_team_launcher", REPO_ROOT / "scripts" / "virt_team_launcher.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _plugin_enabled_project(tmp_path: Path) -> Path:
    """Live bug fix (2026-08-15): the real marker is .claude/team-preferences.json (or
    docs/team-operating-guide.md in repo-as-project mode) - .claude/hooks/run-guard.sh
    only exists for developers working inside the plugin's own repo, never for a normal
    user project with the plugin installed via marketplace (hooks resolve through
    CLAUDE_PLUGIN_ROOT there, nothing copied locally). The old fixture used the wrong
    marker and so did the code it was testing."""
    (tmp_path / ".claude").mkdir(parents=True)
    (tmp_path / ".claude" / "team-preferences.json").write_text("{}", encoding="utf-8")
    return tmp_path


def _ws(project: Path, slug: str, status: str = "in_progress", title: str = "", opened: str = ""):
    art = project / "artifacts" / slug
    art.mkdir(parents=True, exist_ok=True)
    state = {"schema": 2, "status": status, "engagement": {"slug": slug, "title": title}}
    if opened:
        state["engagement"]["opened"] = opened
    (art / "engagement-state.json").write_text(json.dumps(state), encoding="utf-8")


def _flat_ws(project: Path, slug: str, status: str = "in_progress", title: str = ""):
    """A FLAT-layout pack: the state file sits directly in artifacts/, no per-slug
    subfolder - the pre-ADR-008 single-engagement shape resume_menu() still supports
    and reports with dir "(flat)"."""
    art = project / "artifacts"
    art.mkdir(parents=True, exist_ok=True)
    state = {"schema": 2, "status": status, "engagement": {"slug": slug, "title": title}}
    (art / "engagement-state.json").write_text(json.dumps(state), encoding="utf-8")


def test_non_plugin_project_is_silent_on_stdout_but_explains_on_stderr(
    tmp_path, monkeypatch, capsys
):
    """No team-preferences.json/team-operating-guide.md at all - an unrelated project on
    the same machine must do zero real work and never touch stdout (the decision-capture
    contract), but DOES explain itself on stderr now (2026-08-15 live report: a silent
    skip was indistinguishable from a wrong-directory mistake, with no way to tell)."""
    monkeypatch.chdir(tmp_path)
    mod = _load()
    rc = mod.main()
    out = capsys.readouterr()
    assert rc == 0
    assert out.out == ""
    assert "doesn't look like a configured project" in out.err


def test_repo_as_project_marker_also_detected(tmp_path, monkeypatch, capsys):
    """The OTHER valid marker - docs/team-operating-guide.md - must also be recognised,
    not just .claude/team-preferences.json. Covers developers working inside the
    plugin's own repo (repo-as-project mode)."""
    (tmp_path / "docs").mkdir(parents=True)
    (tmp_path / "docs" / "team-operating-guide.md").write_text("# ops\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    mod = _load()
    monkeypatch.setattr(mod, "_refresh_tool_cache", lambda p: None)
    rc = mod.main()
    out = capsys.readouterr()
    assert rc == 0
    assert "doesn't look like a configured project" not in out.err


def test_plugin_project_no_engagements_still_pauses_with_menu(tmp_path, monkeypatch, capsys):
    """Zero open engagements used to skip the pause entirely; the menu now always shows
    (2026-08-17 user preference) so [n]/[c] stay reachable. Non-interactive callers are
    unchanged: no usable stdin -> the same plain launch as before, stdout empty."""
    _plugin_enabled_project(tmp_path)
    monkeypatch.chdir(tmp_path)
    mod = _load()
    monkeypatch.setattr(mod, "_refresh_tool_cache", lambda p: None)  # not under test here
    rc = mod.main()  # pytest's captured stdin is unreadable -> EOF path -> plain launch
    out = capsys.readouterr()
    assert rc == 0 and out.out == ""
    assert "none open" in out.err
    assert "[n]" in out.err and "start new" in out.err
    assert "[a]" not in out.err  # nothing to archive - option hidden


def test_empty_menu_n_starts_new_and_enter_launches_plain(tmp_path, monkeypatch, capsys):
    project = _plugin_enabled_project(tmp_path)
    monkeypatch.chdir(project)
    mod = _load()
    monkeypatch.setattr(mod, "_refresh_tool_cache", lambda p: None)
    monkeypatch.setattr("builtins.input", lambda prompt="": "n")
    rc = mod.main()
    out = capsys.readouterr()
    assert rc == 0
    assert out.out.strip() == "/compliance-surveillance-team:engage --new"
    monkeypatch.setattr("builtins.input", lambda prompt="": "")
    rc = mod.main()
    out = capsys.readouterr()
    assert rc == 0
    assert out.out == ""  # Enter = just launch
    assert "just launch" in out.err


def test_decision_goes_to_stdout_menu_goes_to_stderr(tmp_path, monkeypatch, capsys):
    project = _plugin_enabled_project(tmp_path)
    _ws(project, "dashboard-demo", title="Dashboard demo")
    monkeypatch.chdir(project)
    mod = _load()
    monkeypatch.setattr(mod, "_refresh_tool_cache", lambda p: None)
    monkeypatch.setattr("builtins.input", lambda prompt="": "1")
    rc = mod.main()
    out = capsys.readouterr()
    assert rc == 0
    # The fixture marks the project via team-preferences.json = a PLUGIN install, so
    # the pre-seeded prompt must use the namespaced command spelling (2026-08-16 live
    # report: bare /engage is an unknown command in a plugin-mode session).
    assert out.out.strip() == "/compliance-surveillance-team:engage --resume dashboard-demo"
    assert "dashboard-demo" in out.err  # the menu itself is on stderr
    assert "--resume" not in out.err  # the decision string itself never leaks onto stderr


def test_real_input_prompt_never_leaks_onto_stdout(tmp_path, monkeypatch, capsys):
    """Live bug (2026-08-15): builtins.input(prompt) writes `prompt` to STDOUT
    unconditionally - CPython's own behaviour, not something file=stderr elsewhere in
    this function can override. The EARLIER version of this test mocked out
    `builtins.input` entirely (a lambda that never touches any stream), which is exactly
    why it never caught this - the real builtin has to actually run, with a real stdin,
    for the leak to be observable at all. A shell capturing stdout via $(...) got
    "Choice: --new" mashed into one corrupted argument instead of a clean "--new"."""
    import io

    project = _plugin_enabled_project(tmp_path)
    _ws(project, "existing-thing")
    monkeypatch.chdir(project)
    mod = _load()
    monkeypatch.setattr(mod, "_refresh_tool_cache", lambda p: None)
    monkeypatch.setattr("sys.stdin", io.StringIO("n\n"))  # real input(), real stdin
    rc = mod.main()
    out = capsys.readouterr()
    assert rc == 0
    # Exactly the decision, nothing prepended by input()'s leak
    assert out.out.strip() == "/compliance-surveillance-team:engage --new"
    assert "Choice:" not in out.out  # the prompt text itself must never reach stdout
    assert "Choice:" in out.err  # it's still shown to the human, just on the right stream


def test_flat_layout_resume_emits_the_real_slug_not_the_flat_label(tmp_path, monkeypatch, capsys):
    """Live finding (2026-08-16): resume_menu() reports a flat-layout pack with dir
    "(flat)" - a display label, not a resumable identifier - and the decision used to
    prefer dir over slug unconditionally, so choosing that row emitted literally
    `--resume (flat)`. The engage skill's validation can only reject that and fall back
    to asking in-session: safe, but the pre-made decision was silently lost exactly
    where this script exists to make it. The real slug must be emitted instead, and the
    menu row must show it too (a human asked to pick from "(flat)" learns nothing)."""
    project = _plugin_enabled_project(tmp_path)
    _flat_ws(project, "legacy-flat", title="Legacy flat engagement")
    monkeypatch.chdir(project)
    mod = _load()
    monkeypatch.setattr(mod, "_refresh_tool_cache", lambda p: None)
    monkeypatch.setattr("builtins.input", lambda prompt="": "1")
    rc = mod.main()
    out = capsys.readouterr()
    assert rc == 0
    assert out.out.strip() == "/compliance-surveillance-team:engage --resume legacy-flat"
    assert "(flat)" not in out.out
    assert "legacy-flat" in out.err  # the menu names the engagement, not the layout


def test_choosing_new_returns_new_flag(tmp_path, monkeypatch, capsys):
    project = _plugin_enabled_project(tmp_path)
    _ws(project, "existing-thing")
    monkeypatch.chdir(project)
    mod = _load()
    monkeypatch.setattr(mod, "_refresh_tool_cache", lambda p: None)
    monkeypatch.setattr("builtins.input", lambda prompt="": "n")
    out = _run(mod)
    assert out.strip() == "/compliance-surveillance-team:engage --new"


def test_repo_as_project_mode_emits_bare_engage(tmp_path, monkeypatch, capsys):
    """The OTHER run mode: the plugin's own repo opened as the project (marked by the
    operating guide being present locally) loads skills unnamespaced, so the pre-seeded
    prompt must use bare /engage there - the namespaced spelling would be equally
    unknown in that mode. Same marker file _plugin_enabled keys on."""
    (tmp_path / "docs").mkdir(parents=True)
    (tmp_path / "docs" / "team-operating-guide.md").write_text("# ops\n", encoding="utf-8")
    _ws(tmp_path, "repo-side-work")
    monkeypatch.chdir(tmp_path)
    mod = _load()
    monkeypatch.setattr(mod, "_refresh_tool_cache", lambda p: None)
    monkeypatch.setattr("builtins.input", lambda prompt="": "1")
    out = _run(mod)
    assert out.strip() == "/engage --resume repo-side-work"


def test_empty_choice_defers_to_session(tmp_path, monkeypatch, capsys):
    project = _plugin_enabled_project(tmp_path)
    _ws(project, "existing-thing")
    monkeypatch.chdir(project)
    mod = _load()
    monkeypatch.setattr(mod, "_refresh_tool_cache", lambda p: None)
    monkeypatch.setattr("builtins.input", lambda prompt="": "")
    out = _run(mod)
    assert out.strip() == ""


def test_out_of_range_choice_falls_back_safely(tmp_path, monkeypatch, capsys):
    project = _plugin_enabled_project(tmp_path)
    _ws(project, "existing-thing")
    monkeypatch.chdir(project)
    mod = _load()
    monkeypatch.setattr(mod, "_refresh_tool_cache", lambda p: None)
    monkeypatch.setattr("builtins.input", lambda prompt="": "99")
    out = _run(mod)
    assert out.strip() == ""  # never crashes, never guesses - defers to the session


def test_garbage_choice_falls_back_safely(tmp_path, monkeypatch, capsys):
    project = _plugin_enabled_project(tmp_path)
    _ws(project, "existing-thing")
    monkeypatch.chdir(project)
    mod = _load()
    monkeypatch.setattr(mod, "_refresh_tool_cache", lambda p: None)
    monkeypatch.setattr("builtins.input", lambda prompt="": "banana")
    out = _run(mod)
    assert out.strip() == ""


def test_no_tty_fails_open_to_plain_launch(tmp_path, monkeypatch, capsys):
    """input() raising EOFError (no stdin attached, e.g. a non-interactive caller) must
    degrade to an empty decision, never a crash - this script's own robustness must never
    be load-bearing for actually launching claude."""
    project = _plugin_enabled_project(tmp_path)
    _ws(project, "existing-thing")
    monkeypatch.chdir(project)
    mod = _load()
    monkeypatch.setattr(mod, "_refresh_tool_cache", lambda p: None)

    def _raise(prompt=""):
        raise EOFError

    monkeypatch.setattr("builtins.input", _raise)
    out = _run(mod)
    assert out.strip() == ""


def test_resume_menu_failure_fails_open(tmp_path, monkeypatch, capsys):
    project = _plugin_enabled_project(tmp_path)
    monkeypatch.chdir(project)
    mod = _load()
    monkeypatch.setattr(mod, "_refresh_tool_cache", lambda p: None)

    def _boom(root, max_shown=3):
        raise RuntimeError("synthetic")

    # patch at the call site's own module attribute path used inside _resume_decision
    import engagement_state as es_mod

    monkeypatch.setattr(es_mod, "resume_menu", _boom)
    rc = mod.main()
    out = capsys.readouterr()
    assert rc == 0 and out.out == ""


def test_tool_cache_refresh_failure_does_not_block_the_menu(tmp_path, monkeypatch, capsys):
    """_refresh_tool_cache raising must not prevent the resume-menu part from still
    working - the two are independent best-effort pieces of the same launcher."""
    project = _plugin_enabled_project(tmp_path)
    _ws(project, "existing-thing")
    monkeypatch.chdir(project)
    mod = _load()

    def _boom(p):
        raise RuntimeError("synthetic")

    monkeypatch.setattr(mod, "_refresh_tool_cache", _boom)
    monkeypatch.setattr("builtins.input", lambda prompt="": "n")
    out = _run(mod)
    assert out.strip() == "/compliance-surveillance-team:engage --new"


def _run(mod) -> str:
    """Run main() and return captured stdout as a string (pytest's capsys isn't
    available as a plain helper param here, so callers use capsys directly in most
    tests; this one is only used where the test doesn't otherwise need capsys)."""
    import contextlib

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        mod.main()
    return buf.getvalue()


# --- project-defaults table + first-time setup offer (2026-08-17 user request) ------------


def test_configured_project_prints_defaults_table_on_stderr_only(tmp_path, monkeypatch, capsys):
    project = _plugin_enabled_project(tmp_path)
    _ws(project, "existing-thing")
    monkeypatch.chdir(project)
    mod = _load()
    monkeypatch.setattr(mod, "_refresh_tool_cache", lambda p: None)
    monkeypatch.setattr("builtins.input", lambda prompt="": "n")
    rc = mod.main()
    out = capsys.readouterr()
    assert rc == 0
    assert "Project defaults" in out.err
    assert "regulatory citations" in out.err
    assert "jira integration" in out.err
    # stdout stays EXACTLY the decision - the table must never leak into the capture
    assert "Project defaults" not in out.out
    assert out.out.strip() == "/compliance-surveillance-team:engage --new"


def test_first_time_setup_offer_accepted_runs_configure_with_stdout_redirected(
    tmp_path, monkeypatch, capsys
):
    """Accepting the offer runs install_helper configure against the project, with the
    setup's stdout pointed at OUR stderr - the caller's $(...) capture must only ever
    see the decision."""
    monkeypatch.chdir(tmp_path)  # no markers = unconfigured
    mod = _load()
    calls = []

    def fake_run(argv, stdout=None, stderr=None):
        calls.append((argv, stdout, stderr))
        # configure "succeeds" and writes the marker
        (tmp_path / ".claude").mkdir(exist_ok=True)
        (tmp_path / ".claude" / "team-preferences.json").write_text("{}", encoding="utf-8")

        class P:
            returncode = 0

        return P()

    import subprocess as sp

    monkeypatch.setattr(sp, "run", fake_run)
    monkeypatch.setattr(mod, "_refresh_tool_cache", lambda p: None)
    monkeypatch.setattr("builtins.input", lambda prompt="": "")  # blank = the Y default
    rc = mod.main()
    out = capsys.readouterr()
    assert rc == 0
    assert len(calls) == 1
    argv, stdout, stderr = calls[0]
    assert argv[1].endswith("install_helper.py")
    assert argv[2] == "configure" and argv[3] == str(tmp_path)
    assert stdout is not None  # redirected, never inherited stdout
    assert "Setup complete" in out.err
    assert "Project defaults" in out.err  # configured now - table shows on the same run
    assert "install_helper" not in out.out  # stdout purity


def test_first_time_setup_offer_declined_falls_back_to_explained_plain_launch(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)
    mod = _load()
    monkeypatch.setattr("builtins.input", lambda prompt="": "n")
    rc = mod.main()
    out = capsys.readouterr()
    assert rc == 0
    assert out.out == ""
    assert "doesn't look like a configured project" in out.err


# --- new-recommended-defaults propagation at go (2026-08-17 user request) -----------------


def test_go_applies_new_recommended_defaults_for_opted_in_projects(tmp_path, monkeypatch, capsys):
    """A project that took env tuning before a plugin update gains the update's NEW keys
    at the next go - add-only, told to the user on stderr."""
    project = _plugin_enabled_project(tmp_path)
    (project / ".claude" / "settings.json").write_text(
        json.dumps({"env": {"API_TIMEOUT_MS": "999", "CLAUDE_CODE_RETRY_WATCHDOG": "1"}}),
        encoding="utf-8",
    )
    monkeypatch.chdir(project)
    mod = _load()
    monkeypatch.setattr(mod, "_refresh_tool_cache", lambda p: None)
    rc = mod.main()
    out = capsys.readouterr()
    assert rc == 0
    assert "Applied new recommended default(s)" in out.err
    assert "ENABLE_PROMPT_CACHING_1H" in out.err
    saved = json.loads((project / ".claude" / "settings.json").read_text(encoding="utf-8"))
    assert saved["env"]["ENABLE_PROMPT_CACHING_1H"] == "1"
    assert saved["env"]["API_TIMEOUT_MS"] == "999"  # existing values NEVER corrected here
    assert "Applied new" not in out.out  # stdout purity


def test_go_leaves_projects_that_declined_tuning_alone(tmp_path, monkeypatch, capsys):
    project = _plugin_enabled_project(tmp_path)
    (project / ".claude" / "settings.json").write_text(
        json.dumps({"env": {"MY_OWN_VAR": "x"}}), encoding="utf-8"
    )
    monkeypatch.chdir(project)
    mod = _load()
    monkeypatch.setattr(mod, "_refresh_tool_cache", lambda p: None)
    rc = mod.main()
    out = capsys.readouterr()
    assert rc == 0
    assert "Applied new" not in out.err
    saved = json.loads((project / ".claude" / "settings.json").read_text(encoding="utf-8"))
    assert "ENABLE_PROMPT_CACHING_1H" not in saved.get("env", {})


# --- inline config editor + archive on the go screen (2026-08-17 user requests) -----------


def test_config_editor_toggles_and_restores_machine_defaults(tmp_path, monkeypatch, capsys):
    project = _plugin_enabled_project(tmp_path)
    mod = _load()
    # toggle citations (item 2) off, then restore defaults, then done
    answers = iter(["2", "d", "b"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    mod._config_editor(project)
    prefs = json.loads((project / ".claude" / "team-preferences.json").read_text())
    # 'd' removed the project-level choices again - machine defaults resume
    assert "regulatory_citations" not in prefs
    out = capsys.readouterr()
    assert "Project settings" in out.err
    assert out.out == ""  # stdout purity


def test_config_editor_single_toggle_persists(tmp_path, monkeypatch, capsys):
    project = _plugin_enabled_project(tmp_path)
    mod = _load()
    answers = iter(["2", "b"])  # toggle citations (default on -> off), done
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    mod._config_editor(project)
    prefs = json.loads((project / ".claude" / "team-preferences.json").read_text())
    assert prefs["regulatory_citations"] is False
    # unrelated keys survive the rewrite
    assert prefs == {"regulatory_citations": False} or "guard_daemon" not in prefs


def test_menu_c_edits_then_reasks_and_returns_decision(tmp_path, monkeypatch, capsys):
    project = _plugin_enabled_project(tmp_path)
    _ws(project, "thing")
    monkeypatch.chdir(project)
    mod = _load()
    monkeypatch.setattr(mod, "_refresh_tool_cache", lambda p: None)
    answers = iter(["c", "b", "n"])  # settings -> done -> start new
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    rc = mod.main()
    out = capsys.readouterr()
    assert rc == 0
    assert out.out.strip() == "/compliance-surveillance-team:engage --new"
    assert "Project settings" in out.err
    # Backing out unchanged stays quiet - no table reprint (the 2026-08-17
    # duplicate-table complaint); a CHANGED exit refreshes it (see the next test).
    assert "-> no changes" in out.err
    assert out.err.count("Project defaults") == 1


def test_menu_c_with_a_change_refreshes_the_table(tmp_path, monkeypatch, capsys):
    """2026-08-18 user report: delta lines under the stale launch-time table made a
    successful change look ignored - a changed exit reprints the table in its current
    state, so the new value (and any newly unlocked menu item) is visibly real."""
    project = _plugin_enabled_project(tmp_path)
    _ws(project, "thing")
    monkeypatch.chdir(project)
    mod = _load()
    monkeypatch.setattr(mod, "_refresh_tool_cache", lambda p: None)
    answers = iter(["c", "8", "b", "n"])  # enable jira, done, start new
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    rc = mod.main()
    out = capsys.readouterr()
    assert rc == 0
    assert out.err.count("Project defaults") == 2  # launch-time + refreshed
    assert "-> jira integration (beta): on" in out.err
    # the refreshed table carries the new state, and the re-rendered menu unlocks [j]
    assert "on (key UNSET)" in out.err or "jira integration" in out.err
    assert "[j]" in out.err
    assert out.out.strip() == "/compliance-surveillance-team:engage --new"


def test_menu_a_archives_and_falls_through_to_plain_when_empty(tmp_path, monkeypatch, capsys):
    """Archive the only engagement via [a] all - the recomputed menu is empty, so the
    launcher falls through to a plain launch (empty decision)."""
    import scripts.engagement_state as es

    project = _plugin_enabled_project(tmp_path)
    art = project / "artifacts"
    assert es.main(["--dir", str(art / "old"), "init", "--title", "Old", "--slug", "old"]) == 0
    capsys.readouterr()  # drain the SETUP's own init output - the assertion below is
    # about the LAUNCHER's stdout purity, not the fixture's
    monkeypatch.chdir(project)
    mod = _load()
    monkeypatch.setattr(mod, "_refresh_tool_cache", lambda p: None)
    answers = iter(["a", "all"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    rc = mod.main()
    out = capsys.readouterr()
    assert rc == 0
    assert out.out == ""  # nothing left to resume - plain launch
    assert "archived" in out.err
    assert (art / "old" / ".archive").is_file()


def test_archive_all_covers_every_open_pack_not_just_the_shown_cap(
    tmp_path, monkeypatch, capsys
):
    """Live report (2026-08-17: "after archiving it's still showing items as open") -
    the resume menu shows at most 3 rows ("+N more not shown"), and [a] 'all' archived
    only those, so the overflow packs came straight back as open. 'all' means ALL open."""
    import scripts.engagement_state as es

    project = _plugin_enabled_project(tmp_path)
    art = project / "artifacts"
    slugs = [f"pack-{i}" for i in range(5)]
    for slug in slugs:
        assert (
            es.main(["--dir", str(art / slug), "init", "--title", slug, "--slug", slug]) == 0
        )
    capsys.readouterr()  # drain fixture output
    monkeypatch.chdir(project)
    mod = _load()
    monkeypatch.setattr(mod, "_refresh_tool_cache", lambda p: None)
    answers = iter(["a", "all"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    rc = mod.main()
    out = capsys.readouterr()
    assert rc == 0
    assert out.out == ""  # everything archived - plain launch, stdout stays pure
    for slug in slugs:
        assert (art / slug / ".archive").is_file(), f"{slug} left open"


# --- --launch-command mode (alias v5, 2026-08-17) ------------------------------------------


def test_launch_command_mode_prints_configured_command(tmp_path, monkeypatch, capsys):
    """The v5 shell alias asks the launcher for the launch command at every 'go' - so a
    config change (or reset) is live immediately, with no alias refresh and no profile
    reload (live report: a reset config kept launching the old baked 'cc --debug')."""
    import sys as _sys

    cfg_dir = tmp_path / "cfg" / "virt-surv-it"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "installer.json").write_text(
        json.dumps({"claude_launch_command": "cc --resume"}), encoding="utf-8"
    )
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    mod = _load()
    monkeypatch.setattr(_sys, "argv", ["virt_team_launcher.py", "--launch-command"])
    rc = mod.main()
    out = capsys.readouterr()
    assert rc == 0
    assert out.out == "cc --resume\n"  # stdout is ONLY the command
    assert out.err == ""


def test_launch_command_mode_defaults_to_claude(tmp_path, monkeypatch, capsys):
    import sys as _sys

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "empty"))
    mod = _load()
    monkeypatch.setattr(_sys, "argv", ["virt_team_launcher.py", "--launch-command"])
    rc = mod.main()
    out = capsys.readouterr()
    assert rc == 0
    assert out.out == "claude\n"
    assert out.err == ""


def test_heal_runs_once_and_upgrades_a_stale_alias(tmp_path, monkeypatch, capsys):
    """The 2026-08-17 "it should self-resolve" requirement: a go on a machine whose
    profile still carries an old baked definition upgrades it automatically, marks the
    check in the installer config, and explains the one-terminal-reload limit."""
    home = tmp_path / "home"
    home.mkdir()
    (home / ".bashrc").write_text(
        "# Added by install_helper.py --setup-alias (2026-08-04)\n"
        'virt-surv() { "cc --debug" stale; } # virt-surv-alias-v4\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    mod = _load()
    mod._heal_stale_alias_once()
    out = capsys.readouterr()
    assert "auto-updated an out-of-date 'virt-surv' alias" in out.err
    assert "open a new terminal" in out.err
    assert out.out == ""  # stdout stays the decision channel even here
    content = (home / ".bashrc").read_text(encoding="utf-8")
    assert "cc --debug" not in content
    assert "virt-surv-alias-v5" in content
    cfg = json.loads(
        (tmp_path / "xdg" / "virt-surv-it" / "installer.json").read_text(encoding="utf-8")
    )
    assert cfg["alias_heal_checked"] == mod._EXPECTED_ALIAS_VERSION
    # second run: the mark short-circuits - no message, no rewrite
    before = content
    mod._heal_stale_alias_once()
    out = capsys.readouterr()
    assert "auto-updated" not in out.err
    assert (home / ".bashrc").read_text(encoding="utf-8") == before


def test_heal_never_installs_the_alias_anywhere_new(tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"
    home.mkdir()
    (home / ".bashrc").write_text("# plain rc, alias never installed\n", encoding="utf-8")
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    mod = _load()
    mod._heal_stale_alias_once()
    out = capsys.readouterr()
    assert "auto-updated" not in out.err
    assert (home / ".bashrc").read_text(encoding="utf-8") == "# plain rc, alias never installed\n"
    # still marked checked - the scan itself doesn't repeat every go
    cfg = json.loads(
        (tmp_path / "xdg" / "virt-surv-it" / "installer.json").read_text(encoding="utf-8")
    )
    assert cfg["alias_heal_checked"] == mod._EXPECTED_ALIAS_VERSION


def test_heal_version_constant_matches_install_helper():
    """_EXPECTED_ALIAS_VERSION exists so the every-go check is a cheap JSON read with
    no install_helper exec; this pin is the price - bump both together."""
    spec = importlib.util.spec_from_file_location("ih_sync", REPO_ROOT / "install_helper.py")
    ih = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ih)
    mod = _load()
    assert mod._EXPECTED_ALIAS_VERSION == ih._ALIAS_VERSION


def test_heal_is_wired_to_the_real_entry_point_only():
    """The heal must fire on every real 'go' (the __main__ block) but never on module
    import - tests and in-process callers reach main() directly, and a test run must
    not touch the developer's actual shell rc."""
    source = (REPO_ROOT / "scripts" / "virt_team_launcher.py").read_text(encoding="utf-8")
    main_block = source.split('if __name__ == "__main__":', 1)[1]
    assert "_heal_stale_alias_once()" in main_block
    body = source.split('if __name__ == "__main__":', 1)[0]
    assert "def main" in body and "_heal_stale_alias_once()" not in body.split("def main", 1)[1]


def test_go_prewarms_the_guard_interpreter_cache(tmp_path, monkeypatch, capsys):
    """A cold .guard-interpreter cache makes the first /engage fall back to the big
    inline probe heredoc (live report 2026-08-17); go seeds it so even a first engage
    gets the zero-tool-call prefetch. An existing value is never overwritten."""
    import sys as _sys

    project = _plugin_enabled_project(tmp_path)
    monkeypatch.chdir(project)
    mod = _load()
    monkeypatch.setattr(mod, "_refresh_tool_cache", lambda p: None)
    assert mod.main() == 0
    cache = project / ".claude" / ".guard-interpreter"
    assert cache.read_text(encoding="utf-8").strip() == Path(_sys.executable).as_posix()
    cache.write_text("my-own-python\n", encoding="utf-8")
    assert mod.main() == 0
    assert cache.read_text(encoding="utf-8") == "my-own-python\n"  # run-guard's value wins
    capsys.readouterr()


def test_config_editor_row8_toggles_the_jira_integration(tmp_path, monkeypatch, capsys):
    """2026-08-18 user report: the [c] editor was missing table rows like the Jira
    integration. Row 8 toggles integrations.jira.enabled in place, preserving the rest
    of the block (project_key survives an off/on cycle)."""
    project = _plugin_enabled_project(tmp_path)
    prefs_path = project / ".claude" / "team-preferences.json"
    prefs_path.write_text(
        json.dumps({"integrations": {"jira": {"enabled": True, "project_key": "SURV"}}}),
        encoding="utf-8",
    )
    mod = _load()
    answers = iter(["8", "b"])  # toggle off, done
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    mod._config_editor(project)
    prefs = json.loads(prefs_path.read_text(encoding="utf-8"))
    assert prefs["integrations"]["jira"]["enabled"] is False
    assert prefs["integrations"]["jira"]["project_key"] == "SURV"  # preserved for re-enable
    answers = iter(["8", "b"])  # back on
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    mod._config_editor(project)
    prefs = json.loads(prefs_path.read_text(encoding="utf-8"))
    assert prefs["integrations"]["jira"]["enabled"] is True
    assert prefs["integrations"]["jira"]["project_key"] == "SURV"
    assert capsys.readouterr().out == ""  # stdout purity


def test_config_editor_jira_enable_without_key_says_where_to_set_it(
    tmp_path, monkeypatch, capsys
):
    project = _plugin_enabled_project(tmp_path)
    mod = _load()
    answers = iter(["8", "b"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    mod._config_editor(project)
    prefs = json.loads(
        (project / ".claude" / "team-preferences.json").read_text(encoding="utf-8")
    )
    assert prefs["integrations"]["jira"]["enabled"] is True
    err = capsys.readouterr().err
    assert "no project key" in err and "INTEGRATIONS.md" in err
    rows = mod._editor_rows(project)
    assert rows[-1][1] == "on (key UNSET)"


# --- plugin cache-lag check at go (2026-08-18 user request) --------------------------------


def _fake_installed_plugin(tmp_path: Path, version: str) -> Path:
    home = tmp_path / "home"
    cache = home / ".claude" / "plugins" / "cache" / "team"
    (cache / ".claude-plugin").mkdir(parents=True, exist_ok=True)
    (cache / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({"name": "compliance-surveillance-team", "version": version}),
        encoding="utf-8",
    )
    (home / ".claude" / "plugins").mkdir(parents=True, exist_ok=True)
    (home / ".claude" / "plugins" / "installed_plugins.json").write_text(
        json.dumps({"plugins": [{"installPath": str(cache)}]}), encoding="utf-8"
    )
    return home


def test_cache_lag_is_warned_with_the_fix_named(tmp_path, monkeypatch, capsys):
    """The banner shows the CLONE version but a plugin-mode session loads the installed
    cache - when they differ, go says so and names the fix (non-tty path: no prompt)."""
    project = _plugin_enabled_project(tmp_path)
    home = _fake_installed_plugin(tmp_path, "0.0.1")
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    mod = _load()
    mod._check_plugin_cache_lag(project)
    err = capsys.readouterr().err
    assert "installed plugin is v0.0.1" in err
    assert "claude plugin update compliance-surveillance-team" in err


def test_cache_lag_silent_when_versions_agree_or_repo_as_project(tmp_path, monkeypatch, capsys):
    project = _plugin_enabled_project(tmp_path)
    mod = _load()
    home = _fake_installed_plugin(tmp_path, mod._plugin_version())
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    mod._check_plugin_cache_lag(project)
    assert "installed plugin" not in capsys.readouterr().err
    # repo-as-project: no cache involved, silent even when a stale install exists
    (project / "docs").mkdir(exist_ok=True)
    (project / "docs" / "team-operating-guide.md").write_text("# ops\n", encoding="utf-8")
    home2 = _fake_installed_plugin(tmp_path, "0.0.1")
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home2))
    mod._check_plugin_cache_lag(project)
    assert "installed plugin" not in capsys.readouterr().err


# --- [j] new engagement from a Jira (beta, 2026-08-18 user request) ------------------------


def _jira_enabled_project(tmp_path: Path) -> Path:
    project = _plugin_enabled_project(tmp_path)
    (project / ".claude" / "team-preferences.json").write_text(
        json.dumps(
            {"integrations": {"jira": {"enabled": True, "project_key": "SURV"}}}
        ),
        encoding="utf-8",
    )
    return project


def test_jira_option_hidden_without_the_integration(tmp_path, monkeypatch, capsys):
    """Off by default at every level (docs/INTEGRATIONS.md): no opt-in, no [j] item."""
    project = _plugin_enabled_project(tmp_path)
    monkeypatch.chdir(project)
    mod = _load()
    monkeypatch.setattr(mod, "_refresh_tool_cache", lambda p: None)
    monkeypatch.setattr("builtins.input", lambda prompt="": "")
    rc = mod.main()
    out = capsys.readouterr()
    assert rc == 0
    assert "[j]" not in out.err


def test_jira_url_becomes_a_preseeded_decision(tmp_path, monkeypatch, capsys):
    """[j] + a pasted issue URL pre-seeds '/... --new --jira <url>' - the launcher never
    talks to Jira; the session fetches the ticket and delivers back to it."""
    project = _jira_enabled_project(tmp_path)
    monkeypatch.chdir(project)
    mod = _load()
    monkeypatch.setattr(mod, "_refresh_tool_cache", lambda p: None)
    answers = iter(["j", "https://jira.corp.example/browse/SURV-123"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    rc = mod.main()
    out = capsys.readouterr()
    assert rc == 0
    assert (
        out.out.strip()
        == "/compliance-surveillance-team:engage --new --jira https://jira.corp.example/browse/SURV-123"
    )
    assert "(beta)" in out.err
    assert "SURV-123" in out.err  # the extracted key is confirmed on stderr


def test_jira_bare_key_and_invalid_input(tmp_path, monkeypatch, capsys):
    project = _jira_enabled_project(tmp_path)
    monkeypatch.chdir(project)
    mod = _load()
    monkeypatch.setattr(mod, "_refresh_tool_cache", lambda p: None)
    answers = iter(["j", "surv-42"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    rc = mod.main()
    out = capsys.readouterr()
    assert rc == 0
    assert out.out.strip() == "/compliance-surveillance-team:engage --new --jira SURV-42"
    # invalid input returns to the menu, then Enter = plain launch
    answers = iter(["j", "not a ticket", ""])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    rc = mod.main()
    out = capsys.readouterr()
    assert rc == 0
    assert out.out == ""
    assert "no issue key found" in out.err


# --- prompt_toolkit tier (2026-08-17 user request: arrows/mouse/in-place toggles) ----------


def _pt_session(monkeypatch, keys: str):
    """Headless prompt_toolkit driving: forces the pt tier past the tty gate, neuters
    the stderr output binding, and returns a context manager feeding `keys`."""
    import contextlib
    import sys as _sys

    monkeypatch.setenv("VIRT_SURV_FORCE_PTK", "1")
    vend = str(REPO_ROOT / "vendor")
    if vend not in _sys.path:
        _sys.path.insert(0, vend)
    from prompt_toolkit.application import create_app_session
    from prompt_toolkit.input.defaults import create_pipe_input
    from prompt_toolkit.output import DummyOutput

    @contextlib.contextmanager
    def _ctx():
        with create_pipe_input() as pipe:
            pipe.send_text(keys)
            with create_app_session(input=pipe, output=DummyOutput()):
                yield

    return _ctx()


def test_ptk_tier_is_gated_on_a_real_tty():
    """Under pytest stdin is not a tty, so without the force flag the pt tier must stay
    out of the way - that is what keeps every numbered-input test above meaningful."""
    mod = _load()
    assert mod._ptk_ui() is None


def test_pt_menu_enter_resumes_first_engagement(tmp_path, monkeypatch, capsys):
    project = _plugin_enabled_project(tmp_path)
    _ws(project, "dashboard-demo", title="Dashboard demo")
    monkeypatch.chdir(project)
    mod = _load()
    monkeypatch.setattr(mod, "_refresh_tool_cache", lambda p: None)
    monkeypatch.setattr(mod, "_pt_io", lambda: {})
    with _pt_session(monkeypatch, "\r"):  # Enter on the first (resume) row
        rc = mod.main()
    out = capsys.readouterr()
    assert rc == 0
    assert out.out.strip() == "/compliance-surveillance-team:engage --resume dashboard-demo"


def test_pt_menu_hotkey_n_starts_new(tmp_path, monkeypatch, capsys):
    project = _plugin_enabled_project(tmp_path)
    monkeypatch.chdir(project)
    mod = _load()
    monkeypatch.setattr(mod, "_refresh_tool_cache", lambda p: None)
    monkeypatch.setattr(mod, "_pt_io", lambda: {})
    with _pt_session(monkeypatch, "n"):
        rc = mod.main()
    out = capsys.readouterr()
    assert rc == 0
    assert out.out.strip() == "/compliance-surveillance-team:engage --new"


def test_pt_editor_space_toggles_and_persists(tmp_path, monkeypatch, capsys):
    """The in-place toggle: space flips the highlighted row (docx export, row 1) and
    the write is the same _editor_apply the numbered tier uses."""
    project = _plugin_enabled_project(tmp_path)
    mod = _load()
    monkeypatch.setattr(mod, "_pt_io", lambda: {})
    with _pt_session(monkeypatch, " b"):  # toggle row 1, then done
        mod._config_editor(project)
    prefs = json.loads(
        (project / ".claude" / "team-preferences.json").read_text(encoding="utf-8")
    )
    assert "docx" in prefs.get("extra_formats", [])
    assert capsys.readouterr().out == ""  # stdout purity holds in the pt tier too


def test_pt_failure_falls_back_to_numbered_menu(tmp_path, monkeypatch, capsys):
    """Live Windows report (2026-08-17): when prompt_toolkit's console layer refuses to
    run (captured-stdout invocation), the failure was read as 'user pressed Esc' and go
    launched plainly with no menu at all. A widget-start failure must fall back to the
    numbered input() tier, never skip the pause."""
    project = _plugin_enabled_project(tmp_path)
    _ws(project, "dashboard-demo", title="Dashboard demo")
    monkeypatch.chdir(project)
    mod = _load()
    monkeypatch.setattr(mod, "_refresh_tool_cache", lambda p: None)
    monkeypatch.setenv("VIRT_SURV_FORCE_PTK", "1")  # pt tier engages...
    monkeypatch.setattr(mod, "_pt_pick", lambda *a, **k: mod._PT_FAILED)  # ...and dies
    monkeypatch.setattr("builtins.input", lambda prompt="": "1")
    rc = mod.main()
    out = capsys.readouterr()
    assert rc == 0
    assert out.out.strip() == "/compliance-surveillance-team:engage --resume dashboard-demo"
    assert "[n]" in out.err  # the numbered menu actually rendered


def test_rich_ui_loads_from_vendor_tree():
    """The go TUI uses vendored rich CORE only (2026-08-17): Console/Table/Panel/Rule
    need neither pygments nor markdown-it, so those are deliberately NOT vendored. This
    pins both halves: rich imports from vendor/, and the heavy deps stayed out."""
    mod = _load()
    assert mod._rich_ui() is not None, "vendor/rich missing or rich core grew a hard dep"
    assert (REPO_ROOT / "vendor" / "rich").is_dir()
    assert not (REPO_ROOT / "vendor" / "pygments").exists()
    assert not (REPO_ROOT / "vendor" / "markdown_it").exists()


def test_banner_and_defaults_render_without_rich(tmp_path, monkeypatch, capsys):
    """A broken/absent vendor tree costs looks only: the plain-_Ink fallback renders the
    same information."""
    project = _plugin_enabled_project(tmp_path)
    monkeypatch.chdir(project)
    mod = _load()
    monkeypatch.setattr(mod, "_rich_ui", lambda: None)
    monkeypatch.setattr(mod, "_refresh_tool_cache", lambda p: None)
    rc = mod.main()
    out = capsys.readouterr()
    assert rc == 0
    assert "Virtual Surv-IT" in out.err
    assert "Project defaults" in out.err
    assert "env tuning (1h cache TTL)" in out.err
    assert out.out == ""


def test_banner_carries_the_morgan_persona(tmp_path, monkeypatch, capsys):
    """2026-08-17 user request: Morgan is visible from the go screen - with the
    mandatory AI-identity attribution, on both render paths."""
    project = _plugin_enabled_project(tmp_path)
    mod = _load()
    mod._print_banner(project)
    rich_err = capsys.readouterr().err
    assert "Morgan (PM) here" in rich_err
    assert "AI agent with Virtual Surveillance IT" in rich_err
    monkeypatch.setattr(mod, "_rich_ui", lambda: None)
    mod._print_banner(project)
    plain_err = capsys.readouterr().err
    assert "Morgan (PM) here" in plain_err
    assert "AI agent with Virtual Surveillance IT" in plain_err


def test_launch_command_config_path_matches_install_helper(tmp_path, monkeypatch):
    """The launcher mirrors install_helper's config_path()/load_config() derivation
    instead of importing that whole file per 'go' - this pins the two together so a
    future config relocation can't silently split them."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    spec = importlib.util.spec_from_file_location("ih_cfg", REPO_ROOT / "install_helper.py")
    ih = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ih)
    cfg_path = ih.config_path()
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(json.dumps({"claude_launch_command": "cc"}), encoding="utf-8")
    mod = _load()
    assert mod._configured_launch_command() == "cc"


# --- env-tuning row in the [c] settings editor (2026-08-17 user report) --------------------


def test_config_editor_env_toggle_on_applies_recommended_set(tmp_path, monkeypatch, capsys):
    """"ttl setting is missing on the choice c menu" - item [7] applies the recommended
    env bundle add-only, same contract as the go-time propagation."""
    project = _plugin_enabled_project(tmp_path)
    mod = _load()
    answers = iter(["7", "b"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    mod._config_editor(project)
    saved = json.loads((project / ".claude" / "settings.json").read_text(encoding="utf-8"))
    assert saved["env"]["ENABLE_PROMPT_CACHING_1H"] == "1"
    assert saved["env"]["API_TIMEOUT_MS"] == "1800000"
    out = capsys.readouterr()
    assert "env tuning" in out.err
    assert out.out == ""  # stdout purity


def test_config_editor_env_toggle_off_keeps_custom_tuned_values(tmp_path, monkeypatch, capsys):
    """OFF removes only keys still AT their recommended value - a custom-tuned timeout
    survives and the user is told, never a silent drop."""
    project = _plugin_enabled_project(tmp_path)
    (project / ".claude" / "settings.json").write_text(
        json.dumps(
            {"env": {"ENABLE_PROMPT_CACHING_1H": "1", "API_TIMEOUT_MS": "999"}, "other": True}
        ),
        encoding="utf-8",
    )
    mod = _load()
    answers = iter(["7", "b"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    mod._config_editor(project)
    saved = json.loads((project / ".claude" / "settings.json").read_text(encoding="utf-8"))
    assert "ENABLE_PROMPT_CACHING_1H" not in saved["env"]  # was at recommended - removed
    assert saved["env"]["API_TIMEOUT_MS"] == "999"  # custom-tuned - kept
    assert saved["other"] is True  # unrelated settings survive the rewrite
    out = capsys.readouterr()
    assert "kept custom-tuned" in out.err
    assert out.out == ""
