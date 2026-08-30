#!/usr/bin/env python3
"""The launcher's Textual tier.

A third rendering tier above launcher_app, not a second launcher. It returns the same
PICK launcher_app.run_app returns, and virt_team_launcher._decision_from_pick does
everything after it - so the request composer, Jira, archive, artifacts, watch and
review all stay in one place and only the drawing moves.

These tests pin the things that make that true: the contract, the fall-through, the
picks, and the guards.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
for _p in (REPO / "vendor", REPO, REPO / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

UNDER_PYTEST = "pytest" in sys.modules
FAILED: list[str] = []


def check(name, got, want):
    if got != want:
        FAILED.append(f"{name}: got {got!r}, want {want!r}")
        print(f"  FAIL  {name:<58} got={got!r}")
        if UNDER_PYTEST:
            raise AssertionError(f"{name}: got {got!r}, want {want!r}")


def test_answers_launcher_apps_contract():
    """Same sentinel, same entry point, and it falls through when it cannot draw."""
    import launcher_app
    import launcher_textual

    check("same fallback sentinel", launcher_textual.APP_FALLBACK,
          launcher_app.APP_FALLBACK)
    check("implements run_app", callable(launcher_textual.run_app), True)

    import inspect
    check("takes launcher_app's arguments",
          list(inspect.signature(launcher_textual.run_app).parameters),
          list(inspect.signature(launcher_app.run_app).parameters))

    # No tty means no Textual: run() takes the terminal and waits for a keypress
    # nobody can make, which would hang any non-interactive caller.
    check("no tty falls through", launcher_textual.run_app(REPO, None, {}, []),
          launcher_app.APP_FALLBACK)
    check("available() says no without a tty", launcher_textual.available(), False)

    for var in ("VIRT_SURV_NO_TEXTUAL", "VIRT_SURV_NO_APP"):
        os.environ[var] = "1"
        try:
            check(f"{var} opts out", launcher_textual.run_app(REPO, None, {}, []),
                  launcher_app.APP_FALLBACK)
        finally:
            del os.environ[var]


def test_wired_above_the_other_tiers():
    src = (REPO / "scripts" / "virt_team_launcher.py").read_text(encoding="utf-8")
    i_textual = src.find("from launcher_textual import run_app as run_textual")
    i_ptk = src.find("from launcher_app import APP_FALLBACK, run_app")
    check("the Textual tier is wired in", i_textual > 0, True)
    check("it runs BEFORE the prompt_toolkit tier", i_textual < i_ptk, True)
    check("both feed the same _decision_from_pick",
          src.count("_decision_from_pick(") >= 3, True)

    # The banner must stand down for this tier only: the app owns the alternate screen,
    # so a banner in front of it is still in the scrollback when it releases.
    check("the banner is gated", "if not _textual_available():" in src, True)


def test_picks_match_launcher_app_exactly():
    """The picks are v1's, or _decision_from_pick cannot act on them."""
    import launcher_textual
    import virt_team_launcher as L
    from launcher_tiers import MenuApp

    views = [{"title": "spoofing-review", "lines": [], "mark": "●"}]
    actions = launcher_textual._actions(Path("/tmp/p"), L, views, jira_on=True)
    check("actions are built in launcher_app's order",
          [a[0][0] for a in actions],
          ["new", "jira", "settings", "open", "artifacts", "archive", "finished",
           "launch"])

    async def pick_for(key):
        app = MenuApp(Path("/tmp/p"), views, actions, {})
        async with app.run_test(size=(96, 26)) as p:
            await p.pause()
            await p.press(key)
            await p.pause()
        return app.pick

    async def run():
        for key, want in (("n", ("new",)), ("j", ("jira",)), ("c", ("settings",)),
                          ("o", ("open",)), ("b", ("finished",)), ("a", ("archive",)),
                          ("v", ("artifacts",))):
            check(f"[{key}] returns launcher_app's pick", await pick_for(key), want)
        check("enter on a row resumes it", await pick_for("enter"), ("resume", 0))

    asyncio.run(run())


def test_guards_match_launcher_app():
    """Offering a key that cannot work is worse than not offering it."""
    import launcher_textual
    import virt_team_launcher as L

    empty = [a[0][0] for a in launcher_textual._actions(Path("/tmp/p"), L, [], False)]
    check("no artifacts with nothing open", "artifacts" in empty, False)
    check("no archive with nothing open", "archive" in empty, False)
    check("no jira row when not offered", "jira" in empty, False)
    check("new and launch are always offered",
          ("new" in empty and "launch" in empty), True)


def test_menu_renders_at_both_widths():
    """Under 76 columns the detail pane is dropped, not shrunk - two panes at phone
    width clipped every label and lost whole rows."""
    from launcher_tiers import NARROW, MenuApp

    async def run():
        views = [{"title": "spoofing-review", "lines": [("status", "open")],
                  "mark": "●", "recommended": True}]
        actions = [(("new",), "a new engagement", "n"), (("launch",), "just launch", None)]
        for width, want_narrow in ((100, False), (62, True)):
            app = MenuApp(Path("/tmp/p"), views, actions, {})
            async with app.run_test(size=(width, 26)) as p:
                await p.pause()
                check(f"@{width} narrow={want_narrow}", app.narrow, width < NARROW)
                body = app.query_one("#rows")
                text = getattr(body, "content", "")
                text = text.plain if hasattr(text, "plain") else str(text)
                check(f"@{width} lists the engagement",
                      "spoofing-review" in text, True)
                check(f"@{width} lists the action", "a new engagement" in text, True)

    asyncio.run(run())


def test_cancel_is_not_a_fallback():
    """Esc must mean "launch nothing", not "this tier cannot run".

    launcher_app returns None for a user backing out and APP_FALLBACK for a tier that
    cannot draw; _decision_from_pick turns the first into _ABORT. Returning the
    sentinel for Esc sent it to the next tier, which drew the OLD menu on top of the
    one just dismissed - reported as "when I quit it shows the old interface".
    """
    import launcher_app
    from launcher_tiers import MenuApp

    async def run():
        actions = [(("new",), "a new engagement", "n")]
        for key in ("escape", "q"):
            app = MenuApp(Path("/tmp/p"), [], actions, {})
            async with app.run_test(size=(96, 26)) as p:
                await p.pause()
                await p.press(key)
                await p.pause()
            check(f"{key} drew before leaving", app.ran, True)
            check(f"{key} is a cancel, not a pick", app.pick, None)

    asyncio.run(run())

    # And the adapter must pass that None through rather than the sentinel.
    import inspect

    import launcher_textual
    src = inspect.getsource(launcher_textual.run_app)
    check("a screen that never ran falls through", 'if not getattr(app, "ran"' in src, True)
    check("a cancel is returned as-is",
          "return getattr(app, \"pick\", None)" in src, True)
    check("cancel is no longer mapped to the sentinel",
          "APP_FALLBACK if pick is None" in src, False)


def test_a_broken_tier_costs_nothing():
    """Any failure degrades to the tier below, never breaks the launch."""
    import launcher_app
    import launcher_textual

    class Boom:
        def row_view(self, *a, **k):
            raise RuntimeError("no")

    # A mod that cannot build views must fall through, not raise.
    check("a raising mod falls through",
          launcher_textual.run_app(REPO, Boom(), {}, [{"slug": "x"}]),
          launcher_app.APP_FALLBACK)


if __name__ == "__main__":
    for fn in (test_answers_launcher_apps_contract, test_wired_above_the_other_tiers,
               test_picks_match_launcher_app_exactly, test_guards_match_launcher_app,
               test_menu_renders_at_both_widths, test_cancel_is_not_a_fallback,
               test_a_broken_tier_costs_nothing):
        print(f"\n{fn.__name__}")
        fn()
    print()
    if FAILED:
        print(f"{len(FAILED)} FAILED")
        for f in FAILED:
            print("  - " + f)
        raise SystemExit(1)
    print("all passed")
