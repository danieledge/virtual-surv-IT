#!/usr/bin/env python3
"""The Textual tier for `virt-surv go`.

It is a THIRD rendering tier above the existing two, not a second launcher: it returns
the same PICK launcher_app.run_app returns, and virt_team_launcher._decision_from_pick
does everything after it. That is what makes parity structural - the request composer,
Jira, archive, artifacts, watch and review all stay in v1, and only the drawing moves.
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


def test_tier_answers_the_same_contract():
    import launcher_app
    import launcher_textual

    check("same fallback sentinel", launcher_textual.APP_FALLBACK,
          launcher_app.APP_FALLBACK)
    check("same entry point name", hasattr(launcher_textual, "run_app"), True)

    # Opting out must land on exactly today's behaviour.
    os.environ["VIRT_SURV_NO_TEXTUAL"] = "1"
    try:
        check("VIRT_SURV_NO_TEXTUAL falls through",
              launcher_textual.run_app(REPO, None, {}, []), launcher_app.APP_FALLBACK)
    finally:
        del os.environ["VIRT_SURV_NO_TEXTUAL"]

    # No tty means no Textual: run() would take the terminal and wait for a keypress
    # nobody can make. This hung the whole suite when the tier was first wired in.
    check("no tty falls through", launcher_textual.run_app(REPO, None, {}, []),
          launcher_app.APP_FALLBACK)

    os.environ["VIRT_SURV_NO_APP"] = "1"
    try:
        check("VIRT_SURV_NO_APP still opts out of everything",
              launcher_textual.run_app(REPO, None, {}, []), launcher_app.APP_FALLBACK)
    finally:
        del os.environ["VIRT_SURV_NO_APP"]


def test_tier_is_wired_above_the_others():
    src = (REPO / "scripts" / "virt_team_launcher.py").read_text(encoding="utf-8")
    i_textual = src.find("from launcher_textual import run_app")
    i_ptk = src.find("from launcher_app import APP_FALLBACK, run_app")
    check("the Textual tier is wired in", i_textual > 0, True)
    check("it runs BEFORE the prompt_toolkit tier", i_textual < i_ptk, True)
    check("both feed the same _decision_from_pick",
          src.count("_decision_from_pick(") >= 3, True)


def test_picks_match_v1_exactly():
    """The picks are v1's, or _decision_from_pick cannot act on them."""
    import launcher_textual
    import virt_team_launcher as L
    from virt_surv2.ui import LauncherTierApp

    views = [{"title": "spoofing-review", "lines": [], "row": {"slug": "s"}}]
    actions = launcher_textual._actions(Path("/tmp/p"), L, views, jira_on=True)
    check("actions are built in v1's order",
          [a[0][0] for a in actions],
          ["new", "jira", "settings", "open", "artifacts", "archive", "finished",
           "launch"])

    async def pick_for(key):
        app = LauncherTierApp(Path("/tmp/p"), views, actions, {})
        async with app.run_test(size=(96, 26)) as p:
            await p.pause()
            await p.press(key)
            await p.pause()
        return app.pick

    async def run():
        for key, want in (("n", ("new",)), ("j", ("jira",)), ("c", ("settings",)),
                          ("o", ("open",)), ("b", ("finished",)), ("a", ("archive",)),
                          ("v", ("artifacts",))):
            check(f"[{key}] returns v1's pick", await pick_for(key), want)
        check("enter on a row resumes it", await pick_for("enter"), ("resume", 0))

    asyncio.run(run())


def test_guards_match_v1():
    """artifacts/archive only with something open, watch only with something running -
    offering a key that cannot work is the defect this tier exists to avoid."""
    import launcher_textual
    import virt_team_launcher as L

    empty = [a[0][0] for a in launcher_textual._actions(Path("/tmp/p"), L, [], False)]
    check("no artifacts with nothing open", "artifacts" in empty, False)
    check("no archive with nothing open", "archive" in empty, False)
    check("no jira row when not offered", "jira" in empty, False)
    check("new and launch are always there",
          ("new" in empty and "launch" in empty), True)


if __name__ == "__main__":
    for fn in (test_tier_answers_the_same_contract, test_tier_is_wired_above_the_others,
               test_picks_match_v1_exactly, test_guards_match_v1):
        print(f"\n{fn.__name__}")
        fn()
    print()
    if FAILED:
        print(f"{len(FAILED)} FAILED")
        for f in FAILED:
            print("  - " + f)
        raise SystemExit(1)
    print("all passed")
