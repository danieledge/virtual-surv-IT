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

    # The class must be applied from on_mount, not only from on_resize. A resize event
    # is not guaranteed for the INITIAL size and over mosh/tmux can arrive late or not
    # at all; without this the app laid out for a wide terminal inside a narrow one,
    # content wrapped at the left margin, and the wrapped remnants read as a second,
    # mangled copy of the screen ("IO is mangled", 2026-08-30).
    import inspect

    from launcher_tiers import MenuApp, TierApp
    check("width is applied at mount",
          "_apply_width" in inspect.getsource(MenuApp.on_mount), True)
    check("width is applied on resize",
          "_apply_width" in inspect.getsource(TierApp.on_resize), True)
    check("_apply_width reads the CURRENT size, not just the event",
          "self.size" in inspect.getsource(TierApp._apply_width), True)


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


def test_it_measures_the_real_terminal():
    """The size must come from the tty, not from a piped stdout or a stale COLUMNS.

    The alias captures the decision with `$(...)`, so stdout is a PIPE. Textual sizes
    itself with shutil.get_terminal_size(), which measures sys.__stdout__ - measuring
    a pipe raises, so Textual fell back to its 80x25 default and drew a two-pane
    layout into a 66-column phone pane, wrapping every line ("IO is mangled",
    2026-08-30).
    """
    import fcntl
    import shutil
    import struct
    import termios

    import launcher_textual

    master, slave = os.openpty()
    try:
        # A terminal that is definitively NOT Textual's 80x25 default.
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 30, 66, 0, 0))
        tty = os.fdopen(slave, "w")
        r, w = os.pipe()                        # stdout, as the alias leaves it
        piped = os.fdopen(w, "w")

        real_err, real_out = sys.stderr, sys.__stdout__
        saved_cols = os.environ.get("COLUMNS")
        try:
            sys.stderr = tty
            sys.__stdout__ = piped
            os.environ["COLUMNS"] = "80"        # stale, and it outranks the real size
            check("a pipe measures as Textual's default",
                  shutil.get_terminal_size((80, 25)).columns, 80)
            with launcher_textual._true_terminal_size():
                check("inside, it measures the tty",
                      shutil.get_terminal_size((80, 25)).columns, 66)
                check("inside, COLUMNS cannot outrank it",
                      os.environ.get("COLUMNS"), None)
            check("COLUMNS is put back", os.environ.get("COLUMNS"), "80")
            check("sys.__stdout__ is put back", sys.__stdout__ is piped, True)
        finally:
            sys.stderr, sys.__stdout__ = real_err, real_out
            if saved_cols is None:
                os.environ.pop("COLUMNS", None)
            else:
                os.environ["COLUMNS"] = saved_cols
            for f in (tty, piped):
                try:
                    f.close()
                except Exception:
                    pass
            os.close(r)
    finally:
        try:
            os.close(master)
        except Exception:
            pass

    # And it must actually be used, or the measurement changes nothing.
    import inspect
    check("run_app draws inside it",
          "with _true_terminal_size():" in inspect.getsource(launcher_textual.run_app),
          True)


def test_the_composer_matches_launcher_app():
    """The request composer: same contract, same key map.

    Every binding here is a recorded bug in the prompt_toolkit screen, so they are
    pinned rather than described - Enter that sent silently discarded everything after
    the first line, and a `q` that quit destroyed what was being written.
    """
    import inspect

    import launcher_app
    import launcher_textual
    from launcher_tiers import RequestApp

    check("same signature as launcher_app's",
          list(inspect.signature(launcher_textual.request_screen).parameters),
          list(inspect.signature(launcher_app.request_screen).parameters))
    check("no tty cannot draw", launcher_textual.request_screen(REPO, None), None)

    async def send(keys, offered=True, armed=False):
        app = RequestApp(Path("/tmp/p"), auto_offered=offered, auto=armed)
        async with app.run_test(size=(66, 30)) as p_:
            await p_.pause()
            for k in keys:
                await p_.press(k)
            await p_.pause()
        return app.value

    async def run():
        typed = list("look at spoofing") + ["enter"] + list("in june")
        check("ctrl-d sends, enter is a line break",
              await send(typed + ["ctrl+d"]), ("look at spoofing in june", False))
        check("an empty send is a plain launch", await send(["ctrl+d"]), None)
        check("esc is a plain launch", await send(list("hi") + ["escape"]), None)
        check("ctrl-u clears", await send(list("hi") + ["ctrl+u"] + list("bye")
                                          + ["ctrl+d"]), ("bye", False))
        check("ctrl-t arms unattended",
              await send(list("go") + ["ctrl+t", "ctrl+d"]), ("go", True))
        check("ctrl-t does nothing when not offered",
              await send(list("go") + ["ctrl+t", "ctrl+d"], offered=False), ("go", False))
        check("t is text, not a shortcut", await send(list("test") + ["ctrl+d"]),
              ("test", False))
        # `q` quits the MENU and types on the COMPOSER. Textual merges BINDINGS up the
        # MRO, so a subclass cannot take a binding away - the base must not have it.
        check("q is text, not quit", await send(list("q") + ["ctrl+d"]), ("q", False))
        check("backspace deletes", await send(list("abcd") + ["backspace", "ctrl+d"]),
              ("abc", False))

    asyncio.run(run())

    # Textual MERGES BINDINGS up the MRO, and a binding fires even when a handler has
    # already consumed the key - so a base-class binding is one no screen can remove or
    # override. Two bugs came from that: quit-on-q ended the composer instead of typing
    # a q, and quit-on-Esc closed the settings screen when Esc meant "cancel the edit".
    # Every screen handles its own exits, so there must be no bindings anywhere.
    from launcher_tiers import MenuApp, RequestApp, SettingsApp, TierApp
    for cls in (TierApp, MenuApp, RequestApp, SettingsApp):
        check(f"{cls.__name__} declares no bindings", list(cls.BINDINGS), [])

    # And it must be reached BEFORE the prompt_toolkit composer.
    src = (REPO / "scripts" / "virt_team_launcher.py").read_text(encoding="utf-8")
    i_textual = src.find("from launcher_textual import request_screen as request_textual")
    i_ptk = src.find("from launcher_app import request_screen")
    check("the Textual composer is wired in", i_textual > 0, True)
    check("it runs before the prompt_toolkit one", i_textual < i_ptk, True)


def _scratch_project():
    import tempfile
    d = Path(tempfile.mkdtemp(prefix="vs-tier-"))
    (d / ".git").mkdir(parents=True, exist_ok=True)
    return d


def test_the_settings_screen_matches_launcher_app():
    """The [c] screen: same contract, and the row you are looking at is the row that
    changes.

    That last one is not obvious and has bitten before: the screen is GROUPED, so the
    highlighted row's index is not the dispatch index, and when it was assumed to be,
    position 3 showed one setting while the toggle changed another. No test noticed,
    because none asserted it - so this one does.
    """
    import inspect
    import json
    import shutil

    import launcher_app
    import launcher_textual
    import virt_team_launcher as L
    from launcher_tiers import SettingsApp

    check("same signature as launcher_app's",
          list(inspect.signature(launcher_textual.settings_screen).parameters),
          list(inspect.signature(launcher_app.settings_screen).parameters))
    check("no tty cannot draw", launcher_textual.settings_screen(REPO, L), None)

    async def drive(keys, moves=0):
        d = _scratch_project()
        app = SettingsApp(d, L)
        async with app.run_test(size=(90, 30)) as p_:
            await p_.pause()
            for _ in range(moves):
                await p_.press("down")
            looking_at = app.rows[app.cursor][0]
            for k in keys:
                await p_.press(k)
            await p_.pause()
        f = d / ".claude" / "team-preferences.json"
        wrote = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
        note = app.notes[-1] if app.notes else ""
        shutil.rmtree(d, ignore_errors=True)
        return app.changed, app.ran, wrote, looking_at, note

    async def run():
        changed, ran, wrote, _at, _n = await drive(["escape"])
        check("esc ran and changed nothing", (ran, changed, wrote), (True, False, {}))
        changed, _r, wrote, _at, _n = await drive(["enter", "escape"])
        check("toggling row 0 writes it", (changed, wrote),
              (True, {"extra_formats": ["docx"]}))
        changed, _r, wrote, at, note = await drive(["enter", "escape"], moves=2)
        check("toggling row 2 writes THAT row", (changed, wrote),
              (True, {"evidence_room": True}))
        check("and the note names the row the cursor was on",
              note.startswith(at + ":"), True)
        _c, ran, _w, _at, _n = await drive(["q"])
        check("q leaves the screen", ran, True)

    asyncio.run(run())

    # The Jira key is asked for HERE, in place. Enabling Jira with no key used to name
    # the gap and leave the fix in a JSON file.
    async def jira():
        d = _scratch_project()
        app = SettingsApp(d, L)
        keys = L._editor_keys(d)
        at = keys.index(L._JIRA_KEY)
        async with app.run_test(size=(90, 30)) as p_:
            await p_.pause()
            for _ in range(at):
                await p_.press("down")
            await p_.press("enter")
            await p_.pause()
            check("enabling jira asks for the key", app.editing is not None, True)
            for ch in "surv1":
                await p_.press(ch)
            check("the key is upper-cased as typed", app.editing, "SURV1")
            await p_.press("backspace")
            await p_.press("enter")
            await p_.pause()
            check("the key is saved", L.jira_project_key(d), "SURV")
            await p_.press("e")
            await p_.pause()
            check("e re-opens the key without toggling jira off",
                  app.editing is not None, True)
            await p_.press("escape")
            await p_.pause()
            # Esc means "cancel the edit", NOT "close the screen". A base-class Esc
            # binding used to do both, because a binding fires even when a handler has
            # consumed the key.
            check("esc cancels the edit", app.editing, None)
            check("and leaves the screen open", app.is_running, True)
        shutil.rmtree(d, ignore_errors=True)

    asyncio.run(jira())


def test_the_list_follows_the_cursor():
    """Every row must be reachable and VISIBLE.

    The list pane scrolls and nothing was moving it, so past the bottom of the pane the
    screen looked frozen - the selection was still moving, just where it could not be
    seen. Worse, the pane is focusable and Textual gives keys to the focused widget
    first, so each Down scrolled the pane a line BEFORE the app moved the cursor.
    """
    import shutil

    import virt_team_launcher as L
    from launcher_tiers import SettingsApp

    async def run():
        d = _scratch_project()
        app = SettingsApp(d, L)
        offscreen = []
        async with app.run_test(size=(104, 26)) as p_:
            await p_.pause()
            for n in range(len(app.rows)):
                if n:
                    await p_.press("down")
                    await p_.pause()
                panel = app.query_one("#panel")
                top, height = panel.scroll_offset.y, panel.content_size.height
                y = at = 0
                for i in range(len(app.rows)):
                    if i < len(app.titles) and app.titles[i]:
                        y += 2 if i else 1
                    if i == app.cursor:
                        at = y
                    y += 1
                if not top <= at < top + height:
                    offscreen.append(app.rows[app.cursor][0])
        shutil.rmtree(d, ignore_errors=True)
        check("no row is selected off-screen", offscreen, [])

    asyncio.run(run())


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
               test_it_measures_the_real_terminal,
               test_the_composer_matches_launcher_app,
               test_the_settings_screen_matches_launcher_app,
               test_the_list_follows_the_cursor,
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
