"""Deliberately break the launcher's world and check it degrades rather than dies.

Every case here is something a real machine does: a locked-down corporate box with no
`claude` on PATH, a stale interpreter, a config directory that is not writable, a
half-written state file, a terminal that reports nonsense for its width. The launcher's
whole design is "degrade, never break the launch", and until now almost nothing tested that
claim under an environment that was actually hostile.

The rule these pin: a broken environment produces a DEGRADED result and a message, never a
traceback and never a hang.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
for _p in (REPO_ROOT / "vendor", REPO_ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


# ============================================================ the tools are not installed


def test_claude_missing_is_reported_not_crashed(monkeypatch, tmp_path):
    import preflight

    monkeypatch.setattr(preflight.shutil, "which", lambda name: None)
    report = preflight.preflight(tmp_path)

    assert report.ok("claude_on_path") is False
    assert "cannot be found" in report.result("claude_on_path").check.sentence


def test_git_missing_leaves_git_questions_undetermined_not_false(monkeypatch, tmp_path):
    """A missing git must not be reported as "your tree is dirty" or "no upstream": those
    are answers, and we do not have them."""
    import preflight

    monkeypatch.setattr(preflight.shutil, "which", lambda name: None)
    report = preflight.preflight(tmp_path)

    for name in ("git_repo", "clean_tree", "upstream"):
        result = report.result(name)
        assert result.ok is True, name  # undetermined never blocks
        assert result.undetermined, name


def test_git_that_hangs_or_dies_is_survived(monkeypatch, tmp_path):
    """A corporate antivirus can make any subprocess hang. _run has a timeout; this pins
    that the timeout resolves to a state rather than an exception."""
    import subprocess

    import preflight

    def timeout(*_a, **_k):
        raise subprocess.TimeoutExpired(cmd="git", timeout=5)

    monkeypatch.setattr(preflight.shutil, "which", lambda name: "/usr/bin/git")
    monkeypatch.setattr(preflight.subprocess, "run", timeout)
    report = preflight.preflight(tmp_path)

    assert report.ok("clean_tree") is True
    assert report.result("clean_tree").undetermined


def test_git_returning_garbage_does_not_become_a_true_answer(monkeypatch, tmp_path):
    import preflight

    class _Done:
        returncode = 0
        stdout = "\x00\xff not a boolean"
        stderr = ""

    monkeypatch.setattr(preflight.shutil, "which", lambda name: "/usr/bin/git")
    monkeypatch.setattr(preflight.subprocess, "run", lambda *_a, **_k: _Done())

    assert preflight.preflight(tmp_path).ok("git_repo") is False


def test_a_project_directory_that_does_not_exist(tmp_path):
    """The wrapper can hand us a path that has since been deleted."""
    import preflight

    gone = tmp_path / "deleted"
    report = preflight.preflight(gone)

    for check in preflight.CHECKS:
        report.ok(check.name)  # must not raise for any check


# ====================================================== the crash reporter's own world


def test_crash_log_directory_is_a_file(monkeypatch, tmp_path, capsys):
    """XDG_CONFIG_HOME pointing at a regular file. Reporting must still reach the user."""
    import virt_team_launcher as vtl

    wedged = tmp_path / "not-a-dir"
    wedged.write_text("x", encoding="utf-8")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(wedged))
    monkeypatch.delenv("VIRT_SURV_DEBUG", raising=False)

    vtl._report_crash("a wedged config home", RuntimeError("boom"))

    err = capsys.readouterr().err
    assert "a wedged config home" in err
    assert "could not write" in err


def test_crash_reporting_survives_a_hostile_exception(monkeypatch, tmp_path, capsys):
    """An exception whose __str__ raises. Reporting must not become the failure."""
    import virt_team_launcher as vtl

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.delenv("VIRT_SURV_DEBUG", raising=False)

    class _Nasty(Exception):
        def __str__(self):
            raise ValueError("even my message is broken")

    vtl._report_crash("a hostile exception", _Nasty())  # must not raise
    assert "a hostile exception" in capsys.readouterr().err


def test_crash_reporting_accepts_system_exit(monkeypatch, tmp_path, capsys):
    """SystemExit is not an Exception, and the menu handlers now catch it, so the sink has
    to render it like anything else."""
    import virt_team_launcher as vtl

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.delenv("VIRT_SURV_DEBUG", raising=False)

    vtl._report_crash("a helper that called sys.exit", SystemExit(2))

    assert "SystemExit" in capsys.readouterr().err


def test_crash_reporting_with_no_exception_at_all(monkeypatch, tmp_path, capsys):
    import virt_team_launcher as vtl

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.delenv("VIRT_SURV_DEBUG", raising=False)

    vtl._report_crash("somewhere", None)

    assert "unknown error" in capsys.readouterr().err


# ============================================================== preferences files that lie


def test_corrupt_preferences_read_as_absent_not_as_a_crash(tmp_path):
    import virt_team_launcher as vtl

    prefs = tmp_path / ".claude"
    prefs.mkdir()
    (prefs / "team-preferences.json").write_text("{not json at all", encoding="utf-8")

    assert vtl.jira_project_key(tmp_path) == ""
    assert vtl._jira_needs_key(tmp_path) is False


def test_preferences_that_is_a_directory(tmp_path):
    import virt_team_launcher as vtl

    (tmp_path / ".claude" / "team-preferences.json").mkdir(parents=True)

    assert vtl.jira_project_key(tmp_path) == ""


def test_preferences_holding_the_wrong_types(tmp_path):
    """`integrations` as a list, `jira` as a string: a hand-edited file can be anything."""
    import virt_team_launcher as vtl
    from engage_probe import resolve_integrations

    prefs = tmp_path / ".claude"
    prefs.mkdir()
    for payload in ('{"integrations": []}', '{"integrations": {"jira": "on"}}', "[]", "null"):
        (prefs / "team-preferences.json").write_text(payload, encoding="utf-8")
        assert vtl.jira_project_key(tmp_path) == "", payload
        assert resolve_integrations(tmp_path)["jira"]["enabled"] is False, payload


def test_path_resolver_failing_falls_back_rather_than_raising(monkeypatch, tmp_path):
    """_team_prefs_path resolves through vsit_paths; a bare clone may not have it."""
    import virt_team_launcher as vtl

    def broken():
        raise ImportError("no vsit_paths here")

    monkeypatch.setattr(vtl, "_vsit_paths", broken)
    resolved = vtl._team_prefs_path(tmp_path)

    assert resolved == tmp_path / ".claude" / "team-preferences.json"


# ==================================================== snapshots the monitor may be handed


def test_monitor_rows_survives_every_shape_of_broken_snapshot():
    """_monitor_read resolves every failure to a displayable state, so the row builder is
    handed half-written and empty packs routinely."""
    import launcher_app as la

    hostile = [
        {},
        {"state": None},
        {"state": {}},
        {"state": "a string where a dict belongs"},
        {"state": {"outstanding": "not a list"}},
        {"state": {"status": None, "phase": None}},
        {"state": {"auto": True, "budget": None}},
        {"state": {"auto": True, "budget": {"hard_cap_usd": None}}},
        {"headless": None},
        {"headless": {"finished": True, "ok": False}},
        {"headless": {"live": True, "started": False}},
        {"artifacts": "lots"},
    ]
    for snap in hostile:
        rows = la.monitor_rows(snap, "some-slug")
        assert isinstance(rows, list), snap
        for row in rows:
            assert len(row) == 2, snap
            assert isinstance(row[0], str), snap


def test_monitor_rows_never_omits_the_identity_rows():
    """Whatever else is missing, the user must be able to see WHICH engagement this is."""
    import launcher_app as la

    labels = [label for label, _ in la.monitor_rows({}, "the-slug")]
    assert "slug" in labels
    assert "status" in labels


# =========================================================== terminals that report nonsense


def test_banner_renders_at_absurd_widths():
    import brand_banner

    for width in (0, 1, 5, 39, 40, 64, 65, 80, 100000, -20):
        rows = brand_banner.render(width)
        assert rows, width
        for row in rows:
            assert "\n" not in row, width  # nothing wraps itself


def test_banner_is_pure_ascii_at_every_tier():
    """A cp1252 console raises outright on some UTF-8 sequences, so the printed banner is
    ASCII by construction and a test pins it."""
    import brand_banner

    for width in (0, 44, 46, 66, 200):
        for row in brand_banner.render(width):
            row.encode("ascii")  # must not raise


def test_debug_flag_handling_is_inert_on_hostile_argv(monkeypatch, tmp_path):
    import virt_team_launcher as vtl

    monkeypatch.delenv("VIRT_SURV_DEBUG", raising=False)
    for argv in ([], ["virt-surv"], ["virt-surv", "--debugging"], ["--debug"]):
        assert vtl._consume_debug_flag(list(argv)) == list(argv), argv
        assert vtl.os.environ.get("VIRT_SURV_DEBUG") is None, argv


# ================================================================== handoffs and key input


def test_a_corrupt_auto_handoff_still_marks_the_run_unattended(tmp_path):
    """Losing the budget is a smaller error than losing the flag that makes the AUTO gates
    fire, so an unreadable handoff resolves to auto rather than to nothing."""
    import engagement_state as es

    handoff = tmp_path / ".claude" / es.AUTO_HANDOFF
    handoff.parent.mkdir(parents=True)
    handoff.write_text("{ truncated", encoding="utf-8")

    consumed = es._consume_auto_handoff(tmp_path)

    assert consumed.get("auto") is True
    assert not handoff.exists()  # consumed even when unreadable, so it cannot linger


def test_jira_key_input_rejects_hostile_strings(tmp_path):
    import virt_team_launcher as vtl

    for bad in ("", "   ", "-", "1", "A", "A_B", "../etc", "SURV-1", "a b", "\x00", "é"):
        note = vtl.set_jira_project_key(tmp_path, bad)
        assert vtl.jira_project_key(tmp_path) == "", f"{bad!r} was stored"
        if bad.strip():
            assert "not a Jira project key" in note, bad


# ================================================ the tier plumbing under a dead terminal
#
# `_widgets()` returning None is the normal state on a pipe, in CI, on a clone with no
# vendored Textual, and whenever VIRT_SURV_NO_TEXTUAL is set. Every adapter has to answer
# "I could not draw" in the shape its caller expects, and NEVER with something the caller
# will read as a decision the user made.


def _no_textual(monkeypatch):
    monkeypatch.setenv("VIRT_SURV_NO_TEXTUAL", "1")


def test_no_terminal_means_could_not_draw_never_a_choice(monkeypatch, tmp_path):
    import launcher_app
    import launcher_textual as lt
    import virt_team_launcher as vtl

    _no_textual(monkeypatch)

    # run_app: the sentinel its caller tests for, so the next tier gets a turn
    assert lt.run_app(tmp_path, vtl, {}, [], False) == launcher_app.APP_FALLBACK

    # request composer: None, NOT the skip value - skipping would launch a session
    # without the request the user typed, looking entirely deliberate
    assert lt.request_screen(tmp_path, vtl) is None

    # every remaining adapter: None means "not drawn", and no adapter may invent a value
    for call in (
        lambda: lt.settings_screen(tmp_path, vtl),
        lambda: lt.setup_screen(tmp_path, vtl),
        lambda: lt.artifacts_screen(tmp_path, vtl, "slug"),
        lambda: lt.browse_screen(tmp_path, vtl),
        lambda: lt.auto_preflight_screen(tmp_path, vtl, "SURV-1"),
        lambda: lt.jira_screen(tmp_path, vtl),
        lambda: lt.monitor_screen(tmp_path, vtl, "slug"),
    ):
        assert call() is None


def test_slug_picker_cancel_and_unavailable_are_both_empty(monkeypatch, tmp_path):
    """They ARE the same answer for this screen, and the caller must not treat "" as a
    slug: that is what opened someone else's artifacts on Esc."""
    import launcher_textual as lt
    import virt_team_launcher as vtl

    _no_textual(monkeypatch)
    assert lt.slug_picker_screen(tmp_path, vtl, []) == ""
    assert lt.slug_picker_screen(tmp_path, vtl, [{"slug": "a"}, {"slug": "b"}]) == ""


def test_a_crashed_app_reports_even_when_the_sink_is_unreachable(monkeypatch, capsys):
    """_crashed imports the launcher to report. If that import fails, it must still tell
    the caller the app crashed, because the alternative is reading a half-built pick as a
    user choice."""
    import launcher_textual as lt

    real_import = __import__

    def no_launcher(name, *args, **kwargs):
        if name == "virt_team_launcher":
            raise ImportError("gone")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", no_launcher)

    class _Crashed:
        pick = "new"
        crashed = RuntimeError("died")

    assert isinstance(lt._crashed(_Crashed(), "the menu"), RuntimeError)


def test_the_textual_monitor_degrades_when_the_shared_model_will_not_import(monkeypatch):
    """The monitor reads its rows from launcher_app. A clone that cannot import it should
    show an unknown status, not stop repainting."""
    import launcher_tiers

    # Works normally
    rows = launcher_tiers.shared_monitor_rows({"state": {"status": "open"}}, "s")
    assert ("status", "open") in rows

    real_import = __import__

    def no_launcher_app(name, *args, **kwargs):
        if name == "launcher_app":
            raise ImportError("not in this clone")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", no_launcher_app)
    monkeypatch.delitem(sys.modules, "launcher_app", raising=False)

    assert launcher_tiers.shared_monitor_rows({}, "s") == [("status", "unknown")]


# ============================================================ preflight on a hostile disk


def test_unwritable_config_blocks_the_actions_that_need_to_write(monkeypatch, tmp_path):
    import preflight

    monkeypatch.setattr(preflight.os, "access", lambda *_a, **_k: False)
    report = preflight.preflight(tmp_path)

    assert report.ok("config_writable") is False
    assert report.blocks("headless") is True
    assert "not writable" in report.why_unavailable("headless")


def test_home_resolution_failing_does_not_block_configure(monkeypatch, tmp_path):
    import preflight

    def broken(_cls):
        raise OSError("no home")

    monkeypatch.setattr(preflight.Path, "home", classmethod(broken))
    report = preflight.preflight(tmp_path)

    assert report.ok("not_home_dir") is True
    assert report.result("not_home_dir").undetermined
