"""`virt-surv go`'s decision engine (scripts/virt_team_launcher.py).

Runs OUTSIDE Claude Code entirely, before a session starts - moves the resume-vs-new
decision (observed unreliable when left to the model's own AskUserQuestion menu) and the
tool-inventory cache refresh (a machine-level fact, not a per-engagement one) out of the
LLM pipeline. Output contract is load-bearing: interactive text goes to stderr, ONLY the
final decision string goes to stdout - a shell caller captures stdout via command
substitution and must never see the interactive transcript mixed in.
"""

from __future__ import annotations

import ast
import importlib.util
import io
import json
import sys
from pathlib import Path

import scripts.vsit_paths as _vsit


def _screen_position(mod, project, label):
    """The 1-based position a label occupies ON THE GROUPED SCREEN.

    Tests that simulate typing a number must compute it the way the editor resolves a
    keystroke, not from the old `len(_TOGGLE_PREFS) + N` arithmetic - which was the
    dispatch index, and stopped being the screen position when the screen was grouped
    (2026-08-28)."""
    labels = [row[0] for row in mod._editor_rows(project)]
    return labels.index(label) + 1


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
    art = _vsit.engagements_dir(project) / slug
    art.mkdir(parents=True, exist_ok=True)
    state = {"schema": 2, "status": status, "engagement": {"slug": slug, "title": title}}
    if opened:
        state["engagement"]["opened"] = opened
    (art / "engagement-state.json").write_text(json.dumps(state), encoding="utf-8")


def _flat_ws(project: Path, slug: str, status: str = "in_progress", title: str = ""):
    """A FLAT-layout pack: the state file sits directly in artifacts/, no per-slug
    subfolder - the pre-ADR-008 single-engagement shape resume_menu() still supports
    and reports with dir "(flat)"."""
    art = _vsit.engagements_dir(project)
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
    assert "Not a configured project" in out.err


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
    assert "Not a configured project" not in out.err


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
    assert "no open engagements" in out.err  # wording clarified 2026-08-20
    assert "[n]" in out.err and "a new engagement" in out.err
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
    # NOT the defaults table: `go` stopped printing it on 2026-08-28. What must survive
    # is the banner above and the menu below, which is what this test is really pinning.
    assert "Project defaults" not in out.err
    assert "at defaults" not in out.err
    assert "press [c] to change" not in out.err, (
        "the removed line's one actionable instruction could not be followed here - "
        "`go` prints and launches, so [c] was never pressable at that moment"
    )
    # stdout stays EXACTLY the decision - nothing cosmetic may leak into the capture
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
    # No defaults table follows any more (2026-08-28) - "Setup complete" is the signal
    # that the same run picked the new configuration up.
    assert "Project defaults" not in out.err
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
    assert "Not a configured project" in out.err


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
    # Backing out unchanged stays quiet - no table reprint (the 2026-08-17
    # duplicate-table complaint); a CHANGED exit refreshes it (see the next test).
    assert "-> no changes" in out.err
    # And nothing above it either: `go` stopped printing the table at launch on
    # 2026-08-28, so an unchanged visit to [c] now shows the table zero times.
    assert out.err.count("Project defaults") == 0


def test_menu_c_with_a_change_refreshes_the_table(tmp_path, monkeypatch, capsys):
    """2026-08-18 user report: delta lines under the stale launch-time table made a
    successful change look ignored - a changed exit reprints the table in its current
    state, so the new value (and any newly unlocked menu item) is visibly real."""
    project = _plugin_enabled_project(tmp_path)
    _ws(project, "thing")
    monkeypatch.chdir(project)
    mod = _load()
    monkeypatch.setattr(mod, "_refresh_tool_cache", lambda p: None)
    _mod = _load()
    # jira on -> the project-key prompt (skipped) -> done -> new. Enabling Jira asks for
    # the key now (2026-08-28), so there is one more answer to give than there was.
    answers = iter(["c", str(_screen_position(_mod, tmp_path, "jira write-back")), "", "b", "n"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    rc = mod.main()
    out = capsys.readouterr()
    assert rc == 0
    # The editor's own refresh is the ONLY place the table appears now: `go` stopped
    # printing it at launch (owner decision 2026-08-28) - it ended "(press [c] to
    # change)" at a moment when [c] could not be pressed. This test is about the refresh
    # after an edit, so it asserts the delta line, which is the thing that was missing.
    assert "-> jira write-back: on" in out.err
    assert "-> jira write-back: on" in out.err
    # the refreshed table carries the new state, and the re-rendered menu unlocks [j]
    assert "on (key UNSET)" in out.err or "jira write-back" in out.err
    assert "[j]" in out.err
    assert out.out.strip() == "/compliance-surveillance-team:engage --new"


def test_menu_a_archives_and_falls_through_to_plain_when_empty(tmp_path, monkeypatch, capsys):
    """Archive the only engagement via [a] all - the recomputed menu is empty, so the
    launcher falls through to a plain launch (empty decision)."""
    import scripts.engagement_state as es

    project = _plugin_enabled_project(tmp_path)
    art = _vsit.engagements_dir(project)
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


def test_archive_all_covers_every_open_pack_not_just_the_shown_cap(tmp_path, monkeypatch, capsys):
    """Live report (2026-08-17: "after archiving it's still showing items as open") -
    the resume menu shows at most 3 rows ("+N more not shown"), and [a] 'all' archived
    only those, so the overflow packs came straight back as open. 'all' means ALL open."""
    import scripts.engagement_state as es

    project = _plugin_enabled_project(tmp_path)
    art = _vsit.engagements_dir(project)
    slugs = [f"pack-{i}" for i in range(5)]
    for slug in slugs:
        assert es.main(["--dir", str(art / slug), "init", "--title", slug, "--slug", slug]) == 0
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
    # Derived, not hardcoded: this asserted "v5" literally and so broke on the v6 bump
    # (2026-08-19) even though the behaviour under test - stale definition replaced by
    # the CURRENT one - was working exactly as intended.
    assert f"virt-surv-alias-v{mod._EXPECTED_ALIAS_VERSION}" in content
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
    cache = _vsit.local_file("guard_interpreter", project)
    assert cache.read_text(encoding="utf-8").strip() == Path(_sys.executable).as_posix()
    cache.write_text("my-own-python\n", encoding="utf-8")
    assert mod.main() == 0
    assert cache.read_text(encoding="utf-8") == "my-own-python\n"  # run-guard's value wins
    capsys.readouterr()


def _editor_rows_idx(mod, project=None):
    """(env_row, jira_row) as SCREEN POSITIONS, which is what a typed number means.

    Hardcoded '8'/'9' here broke the moment a toggle was added (2026-08-19,
    evidence_room) - "the tests were pressing a different button than they claimed to".
    The arithmetic that replaced it, len(_TOGGLE_PREFS) + N, broke the same way when the
    screen was grouped (2026-08-28): it computes the DISPATCH index, and display order
    stopped being dispatch order. Now derived from the rendered rows, which cannot drift
    from what a user is actually looking at."""
    if project is None:  # legacy callers that only need the dispatch indices
        n = len(mod._TOGGLE_PREFS)
        return n + 1, n + 2
    labels = [row[0] for row in mod._editor_rows(project)]
    return labels.index(mod._ENV_ROW_LABEL) + 1, labels.index(mod._JIRA_ROW_LABEL) + 1


def test_config_editor_jira_row_toggles_the_jira_integration(tmp_path, monkeypatch, capsys):
    """2026-08-18 user report: the [c] editor was missing table rows like the Jira
    integration. The jira row toggles integrations.jira.enabled in place, preserving the rest
    of the block (project_key survives an off/on cycle)."""
    project = _plugin_enabled_project(tmp_path)
    prefs_path = project / ".claude" / "team-preferences.json"
    prefs_path.write_text(
        json.dumps({"integrations": {"jira": {"enabled": True, "project_key": "SURV"}}}),
        encoding="utf-8",
    )
    mod = _load()
    _env_i, jira_i = _editor_rows_idx(mod, project)
    answers = iter([str(jira_i), "b"])  # toggle off, done
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    mod._config_editor(project)
    prefs = json.loads(prefs_path.read_text(encoding="utf-8"))
    assert prefs["integrations"]["jira"]["enabled"] is False
    assert prefs["integrations"]["jira"]["project_key"] == "SURV"  # preserved for re-enable
    answers = iter([str(jira_i), "b"])  # back on
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    mod._config_editor(project)
    prefs = json.loads(prefs_path.read_text(encoding="utf-8"))
    assert prefs["integrations"]["jira"]["enabled"] is True
    assert prefs["integrations"]["jira"]["project_key"] == "SURV"
    assert capsys.readouterr().out == ""  # stdout purity


def test_config_editor_jira_enable_ASKS_for_the_key(tmp_path, monkeypatch, capsys):
    """Enabling Jira with no project key used to print a note telling you to go and edit
    team-preferences.json - from the screen whose whole job is editing settings. It asks
    now (user question, 2026-08-28: "on key UNSET how is the key set?")."""
    project = _plugin_enabled_project(tmp_path)
    mod = _load()
    answers = iter([str(_editor_rows_idx(mod, project)[1]), "surv", "b"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    mod._config_editor(project)
    prefs = json.loads((project / ".claude" / "team-preferences.json").read_text(encoding="utf-8"))
    assert prefs["integrations"]["jira"]["enabled"] is True
    # Upper-cased on the way in: Jira project keys are uppercase, and nobody should have
    # to know that to type one.
    assert prefs["integrations"]["jira"]["project_key"] == "SURV"
    # By LABEL, not position: the jira row stopped being last when the choice rows
    # (qa depth / jira mirror) were appended after it on 2026-08-20.
    jira_row = next(r for r in mod._editor_rows(project) if r[0] == mod._JIRA_ROW_LABEL)
    assert jira_row[1] == "on (SURV)"


def test_declining_the_key_prompt_still_says_where_to_set_it(tmp_path, monkeypatch, capsys):
    """Pressing Enter past the prompt is allowed - the note is the fallback it always
    was, not a dead end, so nothing is worse than before for someone who does not have
    the key to hand."""
    project = _plugin_enabled_project(tmp_path)
    mod = _load()
    answers = iter([str(_editor_rows_idx(mod, project)[1]), "", "b"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    mod._config_editor(project)
    err = capsys.readouterr().err
    assert "no project key" in err and "INTEGRATIONS.md" in err
    jira_row = next(r for r in mod._editor_rows(project) if r[0] == mod._JIRA_ROW_LABEL)
    assert jira_row[1] == "on (key UNSET)"


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
        json.dumps({"integrations": {"jira": {"enabled": True, "project_key": "SURV"}}}),
        encoding="utf-8",
    )
    return project


def test_jira_option_is_offered_but_outward_actions_stay_gated(tmp_path, monkeypatch, capsys):
    """2026-08-20 user decision: [j] is available ALWAYS. It is only an affordance - the
    launcher never talks to Jira, it collects a ticket ref and pre-seeds the prompt - so
    offering it costs nothing. What stays off by default is the OUTWARD half (issue
    creation, progress comments), which is what docs/INTEGRATIONS.md's "off by default"
    promise is actually about. This test previously asserted the item was hidden."""
    project = _plugin_enabled_project(tmp_path)
    monkeypatch.chdir(project)
    mod = _load()
    monkeypatch.setattr(mod, "_refresh_tool_cache", lambda p: None)
    monkeypatch.setattr("builtins.input", lambda prompt="": "")
    rc = mod.main()
    out = capsys.readouterr()
    assert rc == 0
    assert "[j]" in out.err, "the option must be offered even unconfigured"
    assert mod._jira_enabled(project) is False, "outward actions must stay gated"


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
    assert "treated as data, never instructions" in out.err  # de-beta'd 2026-08-19
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


def test_config_editor_prefers_the_app_screen_and_falls_back_to_numbered(
    tmp_path, monkeypatch, capsys
):
    """Tier choice lives in ONE function now.

    There used to be three tiers: the launcher_app settings screen, a _pt_config_editor
    in between, and the numbered loop. The middle one had drifted from both - no group
    headings, no explanation pane, and no Jira-key prompt, so switching Jira on there
    produced "on (key UNSET)" with nothing in the launcher able to fix it (2026-08-28 UX
    review). It is gone, and _config_editor is the only thing that picks a tier, so every
    [c] entry point makes that decision the same way.

    Both halves asserted here: the app screen is tried, and a screen that cannot run
    falls through rather than leaving the user with no editor at all."""
    project = _plugin_enabled_project(tmp_path)
    mod = _load()

    tried = []
    import launcher_app

    monkeypatch.setattr(
        launcher_app, "settings_screen", lambda p, m, **k: (tried.append("app"), False)[1]
    )
    monkeypatch.setattr("builtins.input", lambda prompt="": "b")
    mod._config_editor(project)
    assert tried == ["app"], "the app screen must be tried first"
    assert "Project settings" not in capsys.readouterr().err, "and must not also fall back"

    # A screen that cannot run (None) hands over to the numbered tier.
    monkeypatch.setattr(
        launcher_app, "settings_screen", lambda p, m, **k: (tried.append("app"), None)[1]
    )
    answers = iter([str(_screen_position(mod, project, "docx export")), "b"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    mod._config_editor(project)
    prefs = json.loads((project / ".claude" / "team-preferences.json").read_text(encoding="utf-8"))
    assert "docx" in prefs.get("extra_formats", [])
    assert capsys.readouterr().out == ""  # stdout purity holds in both tiers


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
    assert "Virtual Surveillance IT" in out.err  # the brand banner: VSIT, expanded
    assert "human controlled" in out.err  # lowercased with the 2026-08-28 redesign
    assert "Project defaults" not in out.err  # dropped from `go` on 2026-08-28
    assert out.out == ""


def test_banner_carries_the_morgan_persona(tmp_path, monkeypatch, capsys):
    """2026-08-17 user request: Morgan is visible from the go screen - with the
    mandatory AI-identity attribution, on both render paths."""
    project = _plugin_enabled_project(tmp_path)
    mod = _load()
    mod._print_banner(project)
    rich_err = capsys.readouterr().err
    assert "Morgan (PM)" in rich_err
    assert "AI agent with Virtual Surveillance IT" in rich_err
    monkeypatch.setattr(mod, "_rich_ui", lambda: None)
    mod._print_banner(project)
    plain_err = capsys.readouterr().err
    assert "Morgan (PM)" in plain_err
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
    """ "ttl setting is missing on the choice c menu" - item [7] applies the recommended
    env bundle add-only, same contract as the go-time propagation."""
    project = _plugin_enabled_project(tmp_path)
    mod = _load()
    answers = iter([str(_editor_rows_idx(mod, project)[0]), "b"])
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
    answers = iter([str(_editor_rows_idx(mod, project)[0]), "b"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    mod._config_editor(project)
    saved = json.loads((project / ".claude" / "settings.json").read_text(encoding="utf-8"))
    assert "ENABLE_PROMPT_CACHING_1H" not in saved["env"]  # was at recommended - removed
    assert saved["env"]["API_TIMEOUT_MS"] == "999"  # custom-tuned - kept
    assert saved["other"] is True  # unrelated settings survive the rewrite
    out = capsys.readouterr()
    assert "kept custom-tuned" in out.err
    assert out.out == ""


# --- _write_probe_cache on a COLD project (2026-08-19) ------------------------------
# The go-written probe cache had no direct test at all: every existing launcher test
# runs without a tty, and the writer returns early on `not sys.stdin.isatty()`, so the
# whole function was silently never exercised. A brand-new project folder is exactly
# where the cache matters most (no .guard-interpreter, no .tool-availability, so the
# in-session probe would run the analyser sweep cold), which is what these pin.


class _TtyStdin(io.StringIO):
    def isatty(self):
        return True


def _cold_project(tmp_path):
    project = tmp_path / "cold"
    (project / ".claude").mkdir(parents=True)
    (project / ".claude" / "team-preferences.json").write_text("{}", encoding="utf-8")
    return project


def test_write_probe_cache_runs_on_a_brand_new_project(tmp_path, monkeypatch, capsys):
    """A new folder gets a full cache: the report, the interpreter (kept as its own key -
    build_report does not emit INTERPRETER=, the prefetch hook composes that line from
    this field) and every invalidation-fingerprint field."""
    mod = _load()
    project = _cold_project(tmp_path)
    monkeypatch.setattr(sys, "stdin", _TtyStdin())
    mod._write_probe_cache(project)
    cache = _vsit.local_file("engage_probe", project)
    assert cache.is_file(), "no probe cache written for a cold project"
    data = json.loads(cache.read_text(encoding="utf-8"))
    assert data["report"], "cached report is empty"
    assert data["interpreter"], "interpreter must be stored separately from the report"
    for field in ("computed_at_epoch", "prefs_mtime", "plugin_version", "git_branch", "git_head"):
        assert field in data, f"fingerprint field {field} missing - the hook validates it"


def test_write_probe_cache_declines_without_a_tty(tmp_path, monkeypatch):
    """Scripted/piped callers write nothing - the writer is an interactive-launch
    accelerator, and a CI run must not leave a cache behind."""
    mod = _load()
    project = _cold_project(tmp_path)
    monkeypatch.setattr(sys, "stdin", io.StringIO())  # isatty() is False
    mod._write_probe_cache(project)
    assert not _vsit.local_file("engage_probe", project).exists()


def test_write_probe_cache_honours_the_probe_cache_preference(tmp_path, monkeypatch):
    """probe_cache: false is the documented off switch ([c] item 7) - the live probe
    becomes the only path, so nothing may be written."""
    mod = _load()
    project = _cold_project(tmp_path)
    (project / ".claude" / "team-preferences.json").write_text(
        json.dumps({"probe_cache": False}), encoding="utf-8"
    )
    monkeypatch.setattr(sys, "stdin", _TtyStdin())
    mod._write_probe_cache(project)
    assert not _vsit.local_file("engage_probe", project).exists()


def test_greeting_rotates_by_time_of_day():
    """2026-08-19 user request: rotate morning/afternoon/evening/late. Hour is injected
    so the bands are pinned without freezing the clock (and so the boundaries are
    actually asserted, not assumed)."""
    mod = _load()
    cases = {
        5: "Good morning",
        7: "Good morning",
        11: "Good morning",
        12: "Good afternoon",
        17: "Good afternoon",
        18: "Good evening",
        21: "Good evening",
        22: "Working late",
        23: "Working late",
        0: "Working late",
        4: "Working late",
    }
    for hour, expected in cases.items():
        assert mod._greeting(hour) == expected, f"hour {hour}"


def test_greeting_covers_every_hour_with_no_gaps():
    mod = _load()
    assert all(mod._greeting(h) for h in range(24)), "an hour fell through every band"


def test_morgan_line_keeps_the_ai_identity_attribution():
    """The greeting is cosmetic; the AI-identity attribution is not (CLAUDE.md §6) - it
    must survive in both the full and the narrow-terminal short form."""
    mod = _load()
    line = mod._morgan_line()
    assert "Morgan" in line and "AI agent" in line and "Virtual Surveillance IT" in line


# --- backing out, and switching project (2026-08-20 user requests) ----------------------------


def test_escape_returns_to_the_terminal_instead_of_launching():
    """2026-08-20 user report: "when exiting the tui it launches claude code, it
    shouldn't". Esc (pick None) used to share the empty decision with "just launch", so
    backing out still started a session. Only the explicit launch row does that now."""
    mod = _load()
    assert mod._decision_from_pick(None, Path("."), None, {}, []) == mod._ABORT
    assert mod._decision_from_pick(("launch",), Path("."), None, {}, []) == ""


def test_abort_writes_nothing_to_stdout_and_exits_with_the_wrapper_code(
    tmp_path, monkeypatch, capsys
):
    """The wrapper skips the launch on this exit code, so it has to be the code AND a
    clean stdout - a stray character would become the session's opening prompt."""
    mod = _load()
    project = _plugin_enabled_project(tmp_path)
    monkeypatch.chdir(project)
    monkeypatch.setattr(mod, "_resume_decision", lambda _d: mod._ABORT)
    for name in (
        "_print_banner",
        "_check_plugin_cache_lag",
        "_print_project_defaults",
        "_prewarm_guard_interpreter",
        "_write_probe_cache",
        "_refresh_tool_cache",
    ):
        monkeypatch.setattr(mod, name, lambda *a, **k: None)
    rc = mod.main()
    assert rc == mod._ABORT_EXIT_CODE == 97
    assert capsys.readouterr().out == ""


def test_choosing_a_new_folder_yields_the_chdir_sentinel(tmp_path, monkeypatch):
    mod = _load()
    target = tmp_path / "other"
    target.mkdir()
    monkeypatch.setattr(mod, "_browse_decision", lambda _d: target)
    out = mod._decision_from_pick(("open",), tmp_path, None, {}, [])
    assert out == mod._CHDIR_PREFIX + str(target)


def test_choosing_the_same_folder_just_reshows_the_menu(tmp_path, monkeypatch):
    """Picking the folder you are already in is a no-op, not a pointless restart."""
    mod = _load()
    monkeypatch.setattr(mod, "_browse_decision", lambda _d: tmp_path)
    assert mod._decision_from_pick(("open",), tmp_path, None, {}, []) == "__again__"


def test_the_cd_request_reaches_the_shell_handshake_file(tmp_path, monkeypatch):
    """A launcher cannot move its parent's cwd, so the folder switch travels to the shell
    through this file. No env var (an un-healed older wrapper) must report False rather
    than pretending it worked."""
    mod = _load()
    handshake = tmp_path / "cd-request"
    monkeypatch.setenv("VIRT_SURV_CD_FILE", str(handshake))
    assert mod._write_cd_request(tmp_path) is True
    assert handshake.read_text(encoding="utf-8") == str(tmp_path.resolve())
    monkeypatch.delenv("VIRT_SURV_CD_FILE")
    assert mod._write_cd_request(tmp_path) is False


# --- the five launcher gaps closed 2026-08-20 -------------------------------------------------


def _prefs(project):
    return json.loads((project / ".claude" / "team-preferences.json").read_text(encoding="utf-8"))


def test_qa_depth_is_reachable_from_the_settings_editor(tmp_path):
    """The editor was boolean-only, so the four-value setting with the largest effect on
    cost and assurance could not be changed from the launcher at all."""
    mod = _load()
    project = _plugin_enabled_project(tmp_path)
    qa_i = len(mod._TOGGLE_PREFS) + 3
    labels = [r[0] for r in mod._editor_rows(project)]
    assert "qa depth" in labels and "jira mirror" in labels
    mod._editor_apply(project, qa_i)
    assert _prefs(project)["qa_depth"] == "quick", "first press must move OFF the default"
    for expected in ("deep", "audit", "auto"):
        mod._editor_apply(project, qa_i)
        assert _prefs(project)["qa_depth"] == expected


def test_choice_rows_cycle_and_never_silently_reduce_qa(tmp_path):
    """Deliberately no "none": QA's existence and independence are not tierable."""
    mod = _load()
    values = dict((key, vals) for _l, key, vals, _d in mod._CHOICE_PREFS)
    assert "none" not in values["qa_depth"] and "off" not in values["qa_depth"]


def test_jira_mirror_writes_into_the_nested_integrations_block(tmp_path):
    mod = _load()
    project = _plugin_enabled_project(tmp_path)
    mirror_i = len(mod._TOGGLE_PREFS) + 4
    mod._editor_apply(project, mirror_i)
    assert _prefs(project)["integrations"]["jira"]["mirror"] == "live"


def test_restore_defaults_drops_qa_depth_but_not_the_integrations_block(tmp_path):
    """'d' means "drop my project choices", not "dismantle the tracker config"."""
    mod = _load()
    project = _plugin_enabled_project(tmp_path)
    mod._editor_apply(project, len(mod._TOGGLE_PREFS) + 3)  # qa depth
    mod._editor_apply(project, len(mod._TOGGLE_PREFS) + 4)  # mirror
    mod._editor_apply(project, "d")
    prefs = _prefs(project)
    assert "qa_depth" not in prefs
    assert prefs["integrations"]["jira"]["mirror"] == "live"


def test_the_menu_no_longer_caps_the_engagement_list(tmp_path):
    """The cap used to be applied when BUILDING the menu, so '+2 more not shown' was
    unreachable from every tier. It is now a per-tier display choice."""
    mod = _load()
    project = _plugin_enabled_project(tmp_path)
    for i in range(7):
        _ws(project, f"eng-{i}", opened=f"2026-08-{10 + i:02d}")
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "engagement_state", REPO_ROOT / "scripts" / "engagement_state.py"
    )
    es = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(es)
    menu = es.resume_menu(_vsit.engagements_dir(project), max_shown=mod._FULL_MENU)
    assert len(menu["shown"]) == 7 and menu["more"] == 0


def test_show_all_is_a_sentinel_the_loop_handles_not_a_decision():
    mod = _load()
    assert mod._decision_from_pick((mod._SHOW_ALL,), Path("."), None, {}, []) == mod._SHOW_ALL


def test_recent_projects_round_trip_and_drop_missing_folders(tmp_path, monkeypatch):
    mod = _load()
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    live = tmp_path / "live-project"
    live.mkdir()
    gone = tmp_path / "gone"
    gone.mkdir()
    mod._remember_project(gone)
    mod._remember_project(live)
    assert mod._recent_projects()[0] == live.resolve(), "most recent must come first"
    gone.rmdir()
    # Dropped on READ, not pruned on write: an unmounted share should return when it does.
    assert live.resolve() in mod._recent_projects()
    assert gone.resolve() not in mod._recent_projects()
    raw = json.loads((tmp_path / "cfg" / "virt-surv-it" / "installer.json").read_text())
    assert str(gone.resolve()) in raw["recent_projects"]


def test_recent_projects_never_grow_without_bound(tmp_path, monkeypatch):
    mod = _load()
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    for i in range(20):
        d = tmp_path / f"p{i}"
        d.mkdir()
        mod._remember_project(d)
    raw = json.loads((tmp_path / "cfg" / "virt-surv-it" / "installer.json").read_text())
    assert len(raw["recent_projects"]) <= mod._RECENT_LIMIT


def test_artifacts_prefer_rendered_html_over_its_markdown_twin(tmp_path):
    """Listing both is noise: the .html IS the shareable artifact."""
    mod = _load()
    ws = _vsit.engagements_dir(tmp_path) / "demo"
    ws.mkdir(parents=True)
    for name in ("START-HERE.md", "START-HERE.html", "notes.md", "delivery-report.html"):
        (ws / name).write_text("x", encoding="utf-8")
    names = [label for label, _p in mod._engagement_artifacts(tmp_path, "demo")]
    assert "START-HERE.html" in names
    assert "START-HERE.md" not in names, "the md twin should be suppressed"
    assert "notes.md" in names, "an md with no rendered twin must still be listed"
    assert names[0] == "START-HERE.html", "START-HERE is the index and should rank first"


def test_artifacts_of_a_missing_workspace_is_empty_not_an_error(tmp_path):
    mod = _load()
    assert mod._engagement_artifacts(tmp_path, "nope") == []


def test_menu_b_reviews_a_finished_engagement_stdout_pure(tmp_path, monkeypatch, capsys):
    """[b] browse done & archived -> pick one -> stdout carries exactly the --review
    decision and nothing else. The slug is deliberately NOT in the resume menu's open
    list (it is archived), which is the whole point of the separate flag."""
    import scripts.engagement_state as es

    project = _plugin_enabled_project(tmp_path)
    art = _vsit.engagements_dir(project)
    assert es.main(["--dir", str(art / "old"), "init", "--title", "Old", "--slug", "old"]) == 0
    assert es.main(["--dir", str(art), "archive", "old", "--force"]) == 0
    capsys.readouterr()  # drain fixture output
    monkeypatch.chdir(project)
    mod = _load()
    monkeypatch.setattr(mod, "_refresh_tool_cache", lambda p: None)
    answers = iter(["b", "1"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    rc = mod.main()
    out = capsys.readouterr()
    assert rc == 0
    assert out.out.strip().endswith("--review old")
    assert out.out.count("\n") <= 1  # one decision line, nothing else
    assert "Done & archived" in out.err or "done or archived" in out.err


def test_menu_b_backing_out_returns_to_the_menu_not_a_launch(tmp_path, monkeypatch, capsys):
    """[b] then back must re-ask (the '__again__' loop), then an empty choice is the
    documented plain launch - and stdout stays empty throughout."""
    import scripts.engagement_state as es

    project = _plugin_enabled_project(tmp_path)
    art = _vsit.engagements_dir(project)
    assert es.main(["--dir", str(art / "old"), "init", "--title", "Old", "--slug", "old"]) == 0
    assert es.main(["--dir", str(art), "archive", "old", "--force"]) == 0
    capsys.readouterr()
    monkeypatch.chdir(project)
    mod = _load()
    monkeypatch.setattr(mod, "_refresh_tool_cache", lambda p: None)
    answers = iter(["b", "b", ""])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    rc = mod.main()
    out = capsys.readouterr()
    assert rc == 0
    assert out.out == ""


# --- Esc overruled by an out-of-date shell wrapper (2026-08-25 user report) -----------------
#
# "when pressing escape on the TUI it should drop to terminal, instead it falls through and
# launches claude". The launcher's own side was already right - Esc -> _ABORT -> exit 97 with
# clean stdout - and the existing tests above proved that by stubbing _resume_decision. What
# none of them touched was the half that actually decides the outcome: the SHELL wrapper, whose
# `-ne 97` check only exists from alias v7. A pre-v7 function already loaded in the calling
# shell ignores the code, and no child process can change its parent's loaded functions.
#
# VIRT_SURV_CD_FILE is the tell. The cd handshake and the exit-code check shipped in the same
# version, so the env var's absence during a `go` means the wrapper will ignore the abort.


def test_a_v7_wrapper_is_left_alone(tmp_path, monkeypatch, capsys):
    """The env var is present, so the abort will be honoured - say nothing."""
    mod = _load()
    monkeypatch.setenv("VIRT_SURV_CD_FILE", str(tmp_path / "cd"))
    mod._warn_if_abort_will_be_ignored()
    assert capsys.readouterr().err == ""


def test_a_direct_run_with_no_wrapper_installed_says_nothing(tmp_path, monkeypatch, capsys):
    """Developers and this suite run the launcher directly. Warning them about a shell
    function they never installed would be noise, and worse, wrong."""
    mod = _load()
    monkeypatch.delenv("VIRT_SURV_CD_FILE", raising=False)
    monkeypatch.setattr(mod, "_alias_installed_anywhere", lambda: False)
    mod._warn_if_abort_will_be_ignored()
    assert capsys.readouterr().err == ""


def test_a_stale_wrapper_is_named_and_the_fix_is_given(tmp_path, monkeypatch, capsys):
    """The reported case. Silence here is the worst outcome: the user pressed Esc, a session
    opened anyway, and nothing explained why."""
    mod = _load()
    monkeypatch.delenv("VIRT_SURV_CD_FILE", raising=False)
    monkeypatch.setattr(mod, "_alias_installed_anywhere", lambda: True)
    healed = []
    monkeypatch.setattr(mod, "_heal_stale_alias_once", lambda force=False: healed.append(force))
    mod._warn_if_abort_will_be_ignored()
    err = capsys.readouterr().err
    assert "predates Esc-to-exit" in err
    assert "source ~/.bashrc" in err and "$PROFILE" in err
    assert healed == [True], "the rc file must be healed before we claim it is up to date"


def test_the_heal_stamp_does_not_block_a_forced_heal(tmp_path, monkeypatch):
    """The stamp records that a heal RAN, which is not the same as this terminal being
    current - so the abort path must be able to force past it."""
    mod = _load()
    cfg = tmp_path / "installer.json"
    cfg.write_text(
        json.dumps({"alias_heal_checked": mod._EXPECTED_ALIAS_VERSION}), encoding="utf-8"
    )
    monkeypatch.setattr(mod, "_installer_config_path", lambda: cfg)
    ran = []
    import types

    fake = types.SimpleNamespace(heal_stale_aliases=lambda: ran.append(1) or [], _ALIAS_VERSION=7)
    monkeypatch.setitem(sys.modules, "install_helper_heal", fake)
    mod._heal_stale_alias_once()  # stamped: must no-op
    assert ran == []


def test_alias_detection_reads_real_rc_files(tmp_path, monkeypatch):
    """Detection must key on a real installed wrapper, not on an env var alone."""
    mod = _load()
    monkeypatch.setattr(mod.Path, "home", staticmethod(lambda: tmp_path))
    assert mod._alias_installed_anywhere() is False
    (tmp_path / ".bashrc").write_text("export FOO=1\n", encoding="utf-8")
    assert mod._alias_installed_anywhere() is False
    (tmp_path / ".bashrc").write_text(
        "virt-surv() { :; } # virt-surv-it-alias-v6\n", encoding="utf-8"
    )
    assert mod._alias_installed_anywhere() is True


def test_the_nudge_separates_modified_from_untracked(tmp_path, monkeypatch):
    """Live report: "virt-surv go said 21 uncommitted files here - where is that coming
    from?" It was `git status --porcelain` counted whole, which includes UNTRACKED files.

    Lumping them together overstates the case badly: on a real project the untracked half
    is usually build output, caches and scratch that no review wants. A modified file has a
    diff to review; an untracked one has no baseline to compare against, so the offer is
    honestly weaker and now says so."""
    mod = _load()

    def _fake(argv, **kwargs):
        class _P:
            returncode = 0
            stdout = " M src/a.py\n?? build/x.o\n?? build/y.o\n"
            stderr = ""

        return _P()

    monkeypatch.setattr(mod.subprocess, "run", _fake)
    line = mod._suggestion_line(tmp_path, {"shown": []})
    assert "1 modified" in line
    assert "+2 untracked" in line
    assert "21 uncommitted" not in line


def test_untracked_only_does_not_claim_there_is_a_diff(tmp_path, monkeypatch):
    """No baseline to compare against, so "a new engagement can review the changes" would
    be a claim the situation does not support."""
    mod = _load()

    def _fake(argv, **kwargs):
        class _P:
            returncode = 0
            stdout = "?? a.txt\n?? b.txt\n"
            stderr = ""

        return _P()

    monkeypatch.setattr(mod.subprocess, "run", _fake)
    line = mod._suggestion_line(tmp_path, {"shown": []})
    assert "2 untracked" in line
    assert "review" not in line


def test_a_clean_tree_says_nothing(tmp_path, monkeypatch):
    """Silent by default - a nudge on every launch is noise with extra steps."""
    mod = _load()

    def _fake(argv, **kwargs):
        class _P:
            returncode = 0
            stdout = ""
            stderr = ""

        return _P()

    monkeypatch.setattr(mod.subprocess, "run", _fake)
    assert mod._suggestion_line(tmp_path, {"shown": []}) == ""


def test_progress_is_silent_when_stderr_is_not_a_tty(monkeypatch, capsys):
    """A \\r into a pipe or a CI log produces one unreadable smeared line, and every test
    that captures this launcher's stderr would have to strip it."""
    mod = _load()
    monkeypatch.setattr(mod.sys.stderr, "isatty", lambda: False, raising=False)
    mod._progress("doing a slow thing...")
    mod._progress_done()
    assert capsys.readouterr().err == ""


def test_progress_overwrites_rather_than_accumulating(monkeypatch):
    """Live report: "there's text displayed before it's done - needs a loading / progress."
    The banner and defaults table print instantly, then five cache-warming steps run in
    silence; on a corporate box run_tool_probe alone spawns ~17 AV-scanned processes, so
    the user got a finished-looking screen and a dead terminal.

    Carriage return, not newline: the point is one replaced line, not a log nobody asked
    for."""
    mod = _load()
    written = []

    class _Tty:
        @staticmethod
        def isatty():
            return True

        @staticmethod
        def write(text):
            written.append(text)

        @staticmethod
        def flush():
            return None

    monkeypatch.setattr(mod.sys, "stderr", _Tty)
    mod._progress("first step...")
    mod._progress("second step...")
    joined = "".join(written)
    assert joined.count("\n") == 0, "progress must not accumulate lines"
    assert joined.count("\r") == 2, "each update replaces the previous one"
    assert "first step" in joined and "second step" in joined


def test_progress_done_wipes_the_line(monkeypatch):
    """The menu starts where the status line was, so it must be cleared - not just
    overwritten by something shorter, which would leave the tail of the old label."""
    mod = _load()
    written = []

    class _Tty:
        @staticmethod
        def isatty():
            return True

        @staticmethod
        def write(text):
            written.append(text)

        @staticmethod
        def flush():
            return None

    monkeypatch.setattr(mod.sys, "stderr", _Tty)
    mod._progress("a rather long status label that must be fully erased...")
    mod._progress_done()
    # Erase-to-end-of-line, not a run of spaces. Padding only covers the columns it
    # counts, so anything already on screen past that point survived - which is how the
    # probe's own message ended up spliced onto the progress line (2026-08-28).
    assert written[-1] == "\r\x1b[K"
    assert all(line.endswith("\x1b[K") for line in written)


def test_the_slow_steps_all_announce_themselves():
    """A silent step is the bug. If a cache-warming call is added later without a label,
    this fails and says so."""
    source = (REPO_ROOT / "scripts" / "virt_team_launcher.py").read_text(encoding="utf-8")
    for call in (
        "_write_probe_cache(project_dir)",
        "_refresh_tool_cache(project_dir)",
        "_prewarm_guard_interpreter(project_dir)",
    ):
        index = source.index(call)
        preceding = source[max(0, index - 200) : index]
        assert "_progress(" in preceding, f"{call} runs without telling the user"


# ---------------- update availability at go (2026-08-28 owner request) ----------------


def _mini_repo(tmp_path, behind=0):
    """A clone with an upstream, optionally `behind` commits back."""
    import subprocess as sp

    origin, clone = tmp_path / "origin.git", tmp_path / "clone"
    sp.run(["git", "init", "-q", "--bare", str(origin)], check=True)
    sp.run(["git", "clone", "-q", str(origin), str(clone)], check=True)
    cfg = ["-c", "user.email=t@t", "-c", "user.name=t"]
    (clone / "a.txt").write_text("a", encoding="utf-8")
    sp.run(["git", "-C", str(clone), "add", "-A"], check=True)
    sp.run(["git", "-C", str(clone), *cfg, "commit", "-qm", "one"], check=True)
    branch = sp.run(
        ["git", "-C", str(clone), "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    sp.run(["git", "-C", str(clone), "push", "-q", "origin", branch], check=True)
    sp.run(
        ["git", "-C", str(clone), "branch", "-q", f"--set-upstream-to=origin/{branch}"],
        check=True,
    )
    for n in range(behind):
        other = tmp_path / f"other{n}"
        sp.run(["git", "clone", "-q", str(origin), str(other)], check=True)
        (other / f"b{n}.txt").write_text("b", encoding="utf-8")
        sp.run(["git", "-C", str(other), "add", "-A"], check=True)
        sp.run(["git", "-C", str(other), *cfg, "commit", "-qm", f"up{n}"], check=True)
        sp.run(["git", "-C", str(other), "push", "-q", "origin", branch], check=True)
    sp.run(["git", "-C", str(clone), "fetch", "-q", "origin"], check=True)
    return clone


def test_it_reports_how_far_behind_upstream_the_clone_is(tmp_path):
    mod = _load()
    assert mod._commits_behind_upstream(_mini_repo(tmp_path, behind=2)) == 2


def test_a_level_clone_reports_nothing_to_do(tmp_path):
    mod = _load()
    assert mod._commits_behind_upstream(_mini_repo(tmp_path, behind=0)) == 0


def test_the_check_never_touches_the_network(tmp_path, monkeypatch):
    """It runs on the `go` path, where this project's history is a catalogue of what a
    network call costs: the probe cache exists because in-session probing takes minutes on
    a corporate box, and pip-audit and semgrep were dropped outright for hanging on a corp
    proxy rather than failing fast.

    So the ANSWER comes from local refs only; freshness comes from a detached background
    fetch that serves the NEXT launch."""
    mod = _load()
    clone = _mini_repo(tmp_path, behind=1)
    seen = []
    real = mod.subprocess.run

    def _watch(argv, **kwargs):
        seen.append(list(argv))
        return real(argv, **kwargs)

    monkeypatch.setattr(mod.subprocess, "run", _watch)
    assert mod._commits_behind_upstream(clone) == 1
    assert not any("fetch" in a for argv in seen for a in argv), "no fetch on the answer path"


def test_no_upstream_configured_is_not_an_update_offer(tmp_path):
    """A clone with no tracking branch has nothing to compare against - saying "0 behind"
    is the honest answer, not an error and not an offer."""
    import subprocess as sp

    mod = _load()
    solo = tmp_path / "solo"
    solo.mkdir()
    sp.run(["git", "init", "-q", str(solo)], check=True)
    assert mod._commits_behind_upstream(solo) == 0


def test_a_broken_repo_never_raises(tmp_path):
    """This is cosmetic tier: an unreadable repo costs the offer, never the launch."""
    mod = _load()
    assert mod._commits_behind_upstream(tmp_path / "does-not-exist") == 0


def test_the_background_refresh_is_ttl_gated(tmp_path, monkeypatch):
    """Repeat launches must not each spawn a fetch."""
    mod = _load()
    clone = _mini_repo(tmp_path, behind=0)
    spawned = []
    monkeypatch.setattr(mod.subprocess, "Popen", lambda *a, **k: spawned.append(a) or None)
    mod._refresh_remote_refs_in_background(clone)  # FETCH_HEAD is fresh from _mini_repo
    assert spawned == [], "a fresh FETCH_HEAD must not trigger another fetch"


# ---------------- the grouped configuration screen (2026-08-28) ----------------


def _fresh_project(tmp_path):
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "team-preferences.json").write_text("{}", encoding="utf-8")
    return tmp_path


def test_toggling_a_row_changes_THAT_row(tmp_path):
    """THE test that was missing, and its absence let a live bug ship for one commit.

    Grouping reordered the screen while dispatch was still positional, so position 3 showed
    "evidence room at close" while the toggle changed "large-context review split". Every
    existing test passed, because none of them asserted the row a user is looking at is the
    row that changes. This one does, for every row on the screen."""
    mod = _load()
    project = _fresh_project(tmp_path)
    keys = mod._editor_keys(project)
    assert keys and all(keys), "every row must resolve to a key"
    for position, key in enumerate(keys):
        before = mod._editor_rows(project)
        mod._editor_apply_key(project, key)
        after = mod._editor_rows(project)
        moved = [i for i, (b, a) in enumerate(zip(before, after)) if b[1] != a[1]]
        assert moved == [position], (
            f"toggling row {position + 1} ({before[position][0]!r}) changed rows "
            f"{[m + 1 for m in moved]}"
        )


def test_related_settings_sit_together(tmp_path):
    """The user-visible point of the grouping. Jira write-back and jira mirror were rows 16
    and 18, with an unrelated row between them, which is why the Jira settings read as
    incoherent - asked 2026-08-28, and already logged once on 2026-08-20."""
    mod = _load()
    layout = mod._editor_layout(_fresh_project(tmp_path))
    labels = [label for _title, label, _v, _o in layout]
    assert abs(labels.index("jira write-back") - labels.index("jira mirror")) == 1


def test_every_row_lands_in_a_named_group(tmp_path):
    """A setting missing from _SETTING_GROUPS still appears, under "Other" - so adding one
    can never make it invisible - but "Other" is a signal that the table needs updating,
    not a resting place."""
    mod = _load()
    layout = mod._editor_layout(_fresh_project(tmp_path))
    titles = set()
    current = ""
    for title, _label, _v, _o in layout:
        current = title or current
        titles.add(current)
    assert "Other" not in titles, "a setting is missing from _SETTING_GROUPS"


def test_the_layout_carries_every_row_exactly_once(tmp_path):
    mod = _load()
    project = _fresh_project(tmp_path)
    rows = mod._editor_rows(project)
    layout = mod._editor_layout(project)
    assert len(layout) == len(rows)
    assert [label for _t, label, _v, _o in layout] == [label for label, _v, _o in rows]


def test_group_headers_appear_once_per_group(tmp_path):
    """A header on every row would be noise; a header only on the first row of each group
    is what makes the screen scannable."""
    mod = _load()
    layout = mod._editor_layout(_fresh_project(tmp_path))
    headers = [title for title, _l, _v, _o in layout if title]
    assert len(headers) == len(set(headers)), "a group header repeated"
    assert len(headers) >= 5, "the screen should be grouped, not one long list"


def test_a_toggle_goes_BOTH_ways(tmp_path):
    """Pressing a toggle twice must return it to where it started.

    test_toggling_a_row_changes_THAT_row pins WHICH row moves, and passed throughout - so
    it did not catch that the row moved only one way. _editor_apply read the current state
    as rows[action-1], positional, while _editor_rows had become grouped; the state it
    inverted therefore belonged to some other row, and when that row was on, `not current`
    was False every time. Every press wrote off. Live report 2026-08-28: "I can turn off
    but not on."

    Starting from a MIXED state on purpose - with everything off, the misread row is off
    too and the wrong answer and the right one agree."""
    mod = _load()
    project = tmp_path
    (project / ".claude").mkdir()
    # extra_formats stores a LIST of formats, not a bool, so it is seeded in its own shape.
    prefs = {
        label_key: True
        for _label, label_key in mod._TOGGLE_PREFS[::2]
        if label_key != "extra_formats"
    }
    prefs["extra_formats"] = ["docx"]
    (project / ".claude" / "team-preferences.json").write_text(json.dumps(prefs), encoding="utf-8")
    # A two-state row returns after 2 presses; a choice row cycles, so it returns after
    # one full lap of its values. Same property either way: a row you can change is a row
    # you can change back.
    lap = {key: len(values) for _label, key, values, _default in mod._CHOICE_PREFS}
    for position, key in enumerate(mod._editor_keys(project)):
        start = mod._editor_rows(project)[position]
        mod._editor_apply_key(project, key)
        once = mod._editor_rows(project)[position]
        assert once[1] != start[1], f"{start[0]!r} did not change when toggled"
        for _ in range(lap.get(key, 2) - 1):
            mod._editor_apply_key(project, key)
        back = mod._editor_rows(project)[position]
        assert back[2] == start[2], (
            f"{start[0]!r} would not go back: {start[1]} -> {once[1]} -> {back[1]}"
        )


def test_the_app_screens_are_reachable_when_this_module_is_not_registered():
    """A trapdoor thirteen call sites shared.

    Every launcher_app screen is invoked as `screen(project_dir, sys.modules[__name__])`
    inside a `try/except Exception`. That lookup raises KeyError whenever this file is
    loaded without being registered in sys.modules - which is exactly what a harness using
    importlib.util.module_from_spec does. The exception was swallowed, so the screen was
    never reached and a fallback ran, looking indistinguishable from a console that could
    not host the app.

    Found by wiring the settings screen into _config_editor and watching it take the
    numbered path for no visible reason (2026-08-28)."""
    mod = _load()  # loads WITHOUT registering, on purpose - that is the condition
    # Force the unregistered condition rather than assuming it: in a full-suite run
    # another test may have registered a DIFFERENT object under this name, and then
    # _this_module() would answer with that one and the test would prove nothing.
    saved = sys.modules.pop(mod.__name__, None)
    try:
        handle = mod._this_module()
        _assert_module_handle_works(mod, handle)
    finally:
        if saved is not None:
            sys.modules[mod.__name__] = saved


def _assert_module_handle_works(mod, handle):
    # The handle has to answer for the attributes launcher_app actually asks it for.
    for attribute in ("_can_encode", "_morgan_line", "_plugin_version", "_git_branch"):
        assert hasattr(handle, attribute), f"screens need {attribute} off this handle"

    # And it must stay LIVE, not a snapshot: a monkeypatched attribute has to be visible
    # through it, or tests would pass against a frozen copy of the module.
    original = mod._plugin_version
    try:
        mod._plugin_version = lambda: "9.9.9"
        assert handle._plugin_version() == "9.9.9"
    finally:
        mod._plugin_version = original


def test_no_background_probe_can_reach_the_terminal():
    """Why a terminal stopped echoing after virt-surv exited.

    capture_output routes stdout and stderr away but leaves stdin attached, and git asks
    for credentials on /dev/tty regardless of stdin - turning ECHO OFF to read a password.
    With our output captured that prompt is invisible: the terminal simply stops echoing,
    and the user meets it after the tool has already exited, with nothing on screen to say
    why (live report 2026-08-29).

    Both halves are asserted because either alone leaves the bug: stdin=DEVNULL stops a
    child eating keystrokes meant for the shell, and GIT_TERMINAL_PROMPT=0 stops git going
    around stdin to the tty, which is the half that actually restores echo.

    The two INTERACTIVE children are excluded by name - they are handed the user's own
    terminal on purpose, and silencing them would break the thing they exist to do."""
    source = (REPO_ROOT / "scripts" / "virt_team_launcher.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    interactive = {"_offer_update_if_behind", "_offer_first_time_setup"}

    owner = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for line in range(node.lineno, (node.end_lineno or node.lineno) + 1):
                owner.setdefault(line, node.name)

    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if getattr(getattr(func, "value", None), "id", None) != "subprocess":
            continue
        if getattr(func, "attr", None) not in ("run", "Popen"):
            continue
        function = owner.get(node.lineno, "<module>")
        if function in interactive:
            continue
        keywords = {kw.arg for kw in node.keywords}
        has_stdin = "stdin" in keywords or None in keywords  # None => **kwargs splat
        if not has_stdin:
            offenders.append(f"{node.lineno}: {function}")

    assert not offenders, (
        "these spawn a child that can still read the terminal - pass **_quiet_kwargs():\n"
        + "\n".join(f"  {o}" for o in offenders)
    )
    assert "GIT_TERMINAL_PROMPT" in source, "stdin alone does not stop git prompting on the tty"


def test_the_interactive_children_are_left_alone():
    """The update and first-time-setup runs hand the user their own terminal on purpose.
    Silencing those would break the thing they exist to do, so the guard above excludes
    them by name rather than by pattern - and this pins that they still exist."""
    mod = _load()
    assert hasattr(mod, "_offer_update_if_behind")
    assert hasattr(mod, "_offer_first_time_setup")
    assert mod._quiet_kwargs()["stdin"] is not None
    env = mod._no_prompt_env()
    assert env["GIT_TERMINAL_PROMPT"] == "0"
