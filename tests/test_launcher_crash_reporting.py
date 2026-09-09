"""A launcher crash must name itself.

Live report, 2026-09-09: "tried an option, it fell out of the TUI, presumably some error,
but no way to see what it was." Three catch-alls sat between a menu pick and the shell and
none of them recorded anything. The degrades are all correct and all stay; these pin that
they now speak.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))


def _launcher(monkeypatch, tmp_path):
    """The launcher with its crash log pointed at a scratch directory."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.delenv("VIRT_SURV_DEBUG", raising=False)
    import virt_team_launcher as vtl

    return vtl


def test_the_traceback_reaches_a_file_and_the_user_is_told_where(monkeypatch, tmp_path, capsys):
    vtl = _launcher(monkeypatch, tmp_path)

    try:
        raise ValueError("the option blew up")
    except ValueError as exc:
        vtl._report_crash("the engagement menu", exc)

    log = vtl._crash_log_path()
    assert log.is_file()
    body = log.read_text(encoding="utf-8")
    assert "ValueError: the option blew up" in body
    assert "Traceback" in body  # the whole thing, not just the label
    assert "the engagement menu" in body

    err = capsys.readouterr().err
    assert "the engagement menu" in err
    assert "ValueError: the option blew up" in err
    assert str(log) in err  # the user can find it without being told separately


def test_stdout_stays_clean_because_it_carries_the_launch_decision(monkeypatch, tmp_path, capsys):
    vtl = _launcher(monkeypatch, tmp_path)
    vtl._report_crash("somewhere", RuntimeError("boom"))
    assert capsys.readouterr().out == ""


def test_reporting_never_raises_even_when_the_log_cannot_be_written(monkeypatch, tmp_path, capsys):
    """A reporting path that can fail turns a degraded launch into a dead one."""
    vtl = _launcher(monkeypatch, tmp_path)
    blocked = tmp_path / "blocked"
    blocked.write_text("not a directory", encoding="utf-8")
    monkeypatch.setattr(vtl, "_crash_log_path", lambda: blocked / "sub" / "crash.log")

    vtl._report_crash("a wedged path", RuntimeError("boom"))  # must not raise

    err = capsys.readouterr().err
    assert "a wedged path" in err
    assert "could not write" in err


def test_debug_env_re_raises_after_reporting(monkeypatch, tmp_path):
    """The degrade is the default; the flag is for someone diagnosing it."""
    vtl = _launcher(monkeypatch, tmp_path)
    monkeypatch.setenv("VIRT_SURV_DEBUG", "1")

    original = RuntimeError("boom")
    try:
        vtl._report_crash("a step", original)
    except RuntimeError as raised:
        assert raised is original
    else:
        raise AssertionError("VIRT_SURV_DEBUG=1 should re-raise")


def test_debug_flag_is_the_discoverable_form_of_the_env_var(monkeypatch, tmp_path):
    """`virt-surv --debug go`, because nobody discovers an environment variable."""
    vtl = _launcher(monkeypatch, tmp_path)

    left = vtl._consume_debug_flag(["virt-surv", "--debug", "go"])

    assert vtl.os.environ.get("VIRT_SURV_DEBUG") == "1"
    assert left == ["virt-surv", "go"]  # stripped, never mistaken for a target

    # and it is inert when absent, rather than arming debug for every run.
    # Cleared directly, NOT via monkeypatch.delenv: delenv records the value it finds and
    # restores it at teardown, so deleting a "1" this test had just set would have put the
    # "1" back and armed debug mode for every test after this file. _launcher's delenv at
    # setup is the one that owns the restore, and it recorded "absent".
    vtl.os.environ.pop("VIRT_SURV_DEBUG", None)
    assert vtl._consume_debug_flag(["virt-surv", "go"]) == ["virt-surv", "go"]
    assert vtl.os.environ.get("VIRT_SURV_DEBUG") is None


def test_a_crashed_app_is_not_read_as_a_choice(monkeypatch, tmp_path, capsys):
    """A crashed composer used to launch a session with the typed request dropped, and a
    crashed menu read as Esc. `crashed` is what makes them distinguishable."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.delenv("VIRT_SURV_DEBUG", raising=False)
    import launcher_textual

    class _Fine:
        pick = "new"

    class _Crashed:
        pick = "new"
        crashed = RuntimeError("died mid-handler")

    assert launcher_textual._crashed(_Fine(), "the menu") is None
    exc = launcher_textual._crashed(_Crashed(), "the menu")
    assert isinstance(exc, RuntimeError)
    assert "died mid-handler" in capsys.readouterr().err
