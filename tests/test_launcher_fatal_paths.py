"""The two crash paths in the Textual tier, neither of which had a test.

`_fatal_error` handles a crash inside a HANDLER. `_ensure_plain_traceback` handles the
driver, which `_fatal_error` never sees. Both exist because pygments is deliberately not
vendored, and both were written from reasoning rather than from a failing test.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
for _p in (REPO_ROOT / "vendor", REPO_ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


class _FakeApp:
    """Enough of a Textual App for _fatal_error, without a running loop.

    Called unbound below, so this pins the method's own logic rather than Textual's.
    """

    def __init__(self, exc):
        self._exception = exc
        self._exit_renderables: list = []
        self.exited_with = "not called"

    def bell(self) -> None:
        pass

    def exit(self, return_code=0) -> None:
        self.exited_with = return_code


def test_the_traceback_is_rendered_as_plain_text_not_via_pygments():
    """rich.traceback would import pygments, which is not vendored, so the one moment the
    cause matters used to surface as ModuleNotFoundError instead."""
    import launcher_tiers

    try:
        raise ValueError("the option blew up")
    except ValueError as exc:
        app = _FakeApp(exc)
        launcher_tiers.TierApp._fatal_error(app)

    assert len(app._exit_renderables) == 1
    rendered = app._exit_renderables[0]
    assert "ValueError: the option blew up" in rendered
    assert "Traceback (most recent call last)" in rendered


def test_a_crash_records_itself_and_exits_non_zero():
    """`crashed` is what stops an adapter reading a half-built pick as a user choice, and
    plain exit() resets Textual's return code back to 0."""
    import launcher_tiers

    exc = RuntimeError("died mid-handler")
    app = _FakeApp(exc)
    launcher_tiers.TierApp._fatal_error(app)

    assert app.crashed is exc
    assert app.exited_with == 1


def test_it_still_reports_when_there_is_no_exception_to_format():
    """Textual can panic with nothing on _exception; reporting must not depend on it."""
    import launcher_tiers

    app = _FakeApp(None)
    launcher_tiers.TierApp._fatal_error(app)

    assert app._exit_renderables == ["virt-surv stopped unexpectedly."]
    assert isinstance(app.crashed, RuntimeError)  # something, so the adapters still see it
    assert app.exited_with == 1


def test_rich_traceback_is_importable_without_pygments(monkeypatch):
    """The driver's failure handler does `import rich.traceback` INSIDE its own except. If
    that raises, the input thread dies without calling panic and the screen freezes."""
    import launcher_tiers

    # _ensure_plain_traceback also sets the attribute on the real `rich` package, which
    # monkeypatch cannot see because the function does it internally. Restore it by hand,
    # or every later test holding the rich module gets this shim.
    import rich

    had_attr = hasattr(rich, "traceback")
    previous = getattr(rich, "traceback", None)

    def _restore():
        if had_attr:
            rich.traceback = previous
        elif hasattr(rich, "traceback"):
            del rich.traceback

    # Simulate the user's machine: no pygments, and rich.traceback not yet imported.
    monkeypatch.delitem(sys.modules, "rich.traceback", raising=False)
    monkeypatch.delitem(sys.modules, "pygments", raising=False)
    real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __import__

    def no_pygments(name, *args, **kwargs):
        if name == "pygments" or name.startswith("pygments."):
            raise ModuleNotFoundError("No module named 'pygments'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", no_pygments)

    launcher_tiers._ensure_plain_traceback()

    import rich.traceback  # the import the driver makes; must not raise

    try:
        raise ValueError("driver died")
    except ValueError:
        rendered = str(rich.traceback.Traceback())

    assert "ValueError: driver died" in rendered
    _restore()
