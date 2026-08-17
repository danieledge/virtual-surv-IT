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


def test_plugin_project_no_engagements_prints_nothing(tmp_path, monkeypatch, capsys):
    _plugin_enabled_project(tmp_path)
    monkeypatch.chdir(tmp_path)
    mod = _load()
    monkeypatch.setattr(mod, "_refresh_tool_cache", lambda p: None)  # not under test here
    rc = mod.main()
    out = capsys.readouterr()
    assert rc == 0 and out.out == ""


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
