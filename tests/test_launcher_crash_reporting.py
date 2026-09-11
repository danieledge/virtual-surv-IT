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


# --- the unattended pre-flight was the one adapter still swallowing (2026-09-11) ---------------
#
# Live report: the human filled in the unattended gate and armed it, no `.auto-pending.json`
# was written, and the session launched ATTENDED. Cancelling cannot produce that - it returns
# "__again__" and starts nothing - so the screen drew and then failed on the way out, and the
# bare `except Exception: return None` turned that into "this tier could not draw". Upstream
# that means an ordinary run. A crash became an attended engagement, in silence.


class _Widgets:
    """Stands in for the vendored Textual widgets module."""

    def __init__(self, app):
        self._app = app

    def PreflightApp(self, *a, **k):  # noqa: N802 - mirrors the real class name
        return self._app


def _preflight(monkeypatch, tmp_path, app, run=None):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.delenv("VIRT_SURV_DEBUG", raising=False)
    import launcher_textual

    monkeypatch.setattr(launcher_textual, "_widgets", lambda: _Widgets(app))
    monkeypatch.setattr(launcher_textual, "_true_terminal_size", _null_context)
    return launcher_textual.auto_preflight_screen(tmp_path, None, "SURV-9")


class _null_context:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_a_preflight_that_dies_after_drawing_is_reported(monkeypatch, tmp_path, capsys):
    class _App:
        ran = True

        def run(self):
            raise RuntimeError("driver died on exit")

    assert _preflight(monkeypatch, tmp_path, _App()) is None  # the degrade itself stays
    err = capsys.readouterr().err
    assert "driver died on exit" in err
    # The human SAW the screen, so the record has to agree with them about that.
    assert "after drawing" in err


def test_a_preflight_that_never_drew_says_so_instead(monkeypatch, tmp_path, capsys):
    class _App:
        ran = False

        def run(self):
            raise RuntimeError("no terminal")

    assert _preflight(monkeypatch, tmp_path, _App()) is None
    err = capsys.readouterr().err
    assert "no draw" in err and "after drawing" not in err


def test_a_preflight_that_crashed_mid_handler_is_not_read_as_an_answer(
    monkeypatch, tmp_path, capsys
):
    """`crashed` is set by the app itself; the state left behind is not a human's choice."""

    class _App:
        ran = True
        confirmed = True
        crashed = RuntimeError("died mid-handler")
        state = {}

        def run(self):
            return None

    assert _preflight(monkeypatch, tmp_path, _App()) is None
    assert "died mid-handler" in capsys.readouterr().err


def test_a_confirmed_preflight_whose_answers_fail_is_reported(monkeypatch, tmp_path, capsys):
    """Confirmed means a human authorised it. Losing that silently is the worst outcome."""

    class _App:
        ran = True
        confirmed = True
        state = {}  # missing every key the answers builder indexes

        def run(self):
            return None

    assert _preflight(monkeypatch, tmp_path, _App()) is None
    assert "unattended pre-flight answers" in capsys.readouterr().err


# --- the prompt_toolkit tier had the same hole, and it is the one PLUGIN installs use ------------
#
# Found on the Windows test VM, 2026-09-11. The installed plugin there (0.37.0) ships
# prompt_toolkit and has NO vendor/textual and no scripts/launcher_textual.py at all - so
# instrumenting only the Textual adapter would have left the renderer that was actually
# drawing the gate as silent as before. Same shape, same cost: a crash returns None, the
# caller reads None as "could not draw", and an authorised unattended run becomes an
# ordinary attended one.


def _vendor_on_path():
    """The vendored prompt_toolkit, without which auto_preflight_screen takes its
    "this tier is unavailable" return before it reaches anything worth testing."""
    vendor = str(REPO_ROOT / "vendor")
    if vendor not in sys.path:
        sys.path.insert(0, vendor)


def _ptk_preflight(monkeypatch, tmp_path, boom=None, drew=True):
    _vendor_on_path()
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.delenv("VIRT_SURV_DEBUG", raising=False)
    import launcher_app
    import virt_team_launcher as vtl

    monkeypatch.setattr(vtl, "_ptk_ui", lambda: True)

    def _screen(mod, **kw):
        if drew:
            kw["body_fn"]()  # the screen appearing is _body being called
        if boom is not None:
            raise boom
        return None

    monkeypatch.setattr(launcher_app, "screen", _screen)
    return launcher_app.auto_preflight_screen(tmp_path, vtl, "SURV-9")


def test_a_ptk_preflight_that_dies_after_drawing_is_reported(monkeypatch, tmp_path, capsys):
    out = _ptk_preflight(monkeypatch, tmp_path, boom=RuntimeError("console went away"))
    assert out is None  # the degrade stays
    err = capsys.readouterr().err
    assert "console went away" in err
    assert "prompt_toolkit" in err and "after drawing" in err


def test_a_ptk_preflight_that_never_drew_is_recorded_differently(monkeypatch, tmp_path, capsys):
    """NoConsoleScreenBufferError fires before the first render - seen for real on Windows
    when stderr is not a console screen buffer. The human saw no screen, so nor should the
    log say one appeared."""
    out = _ptk_preflight(monkeypatch, tmp_path, boom=RuntimeError("no console"), drew=False)
    assert out is None
    err = capsys.readouterr().err
    assert "no draw" in err and "after drawing" not in err


def test_a_confirmed_ptk_preflight_whose_answers_fail_is_reported(monkeypatch, tmp_path, capsys):
    """Confirmed means a human authorised it; dropping that in silence is the worst case."""
    _vendor_on_path()
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.delenv("VIRT_SURV_DEBUG", raising=False)
    import launcher_app
    import virt_team_launcher as vtl

    monkeypatch.setattr(vtl, "_ptk_ui", lambda: True)

    def _screen(mod, **kw):
        kw["body_fn"]()
        return None

    monkeypatch.setattr(launcher_app, "screen", _screen)
    real = launcher_app._preflight_model

    def _broken():
        model = real()
        model["answers"] = lambda state: (_ for _ in ()).throw(KeyError("on_budget"))
        model["state"]["confirmed"] = True
        return model

    monkeypatch.setattr(launcher_app, "_preflight_model", _broken)
    assert launcher_app.auto_preflight_screen(tmp_path, vtl, "SURV-9") is None
    assert "unattended pre-flight answers" in capsys.readouterr().err


def test_reporting_a_screen_crash_never_raises(monkeypatch, tmp_path):
    """It sits on a degrade path; it must not become the thing that breaks it."""
    import launcher_app

    class _Mod:
        @staticmethod
        def _report_crash(where, exc=None):
            raise RuntimeError("the reporter itself is broken")

    launcher_app._report_screen_crash(_Mod(), "somewhere", ValueError("x"))
