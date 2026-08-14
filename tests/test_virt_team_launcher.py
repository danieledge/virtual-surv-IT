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
    assert out.out.strip() == "--resume dashboard-demo"
    assert "dashboard-demo" in out.err  # the menu itself is on stderr
    assert "--resume" not in out.err  # the decision string itself never leaks onto stderr


def test_choosing_new_returns_new_flag(tmp_path, monkeypatch, capsys):
    project = _plugin_enabled_project(tmp_path)
    _ws(project, "existing-thing")
    monkeypatch.chdir(project)
    mod = _load()
    monkeypatch.setattr(mod, "_refresh_tool_cache", lambda p: None)
    monkeypatch.setattr("builtins.input", lambda prompt="": "n")
    out = _run(mod)
    assert out.strip() == "--new"


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
    assert out.strip() == "--new"


def _run(mod) -> str:
    """Run main() and return captured stdout as a string (pytest's capsys isn't
    available as a plain helper param here, so callers use capsys directly in most
    tests; this one is only used where the test doesn't otherwise need capsys)."""
    import contextlib

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        mod.main()
    return buf.getvalue()
