#!/usr/bin/env python3
"""The Textual rendering tier for the launcher.

A THIRD tier above the existing two, not a replacement and not a fork:

    Textual  ->  prompt_toolkit (launcher_app)  ->  numbered input()

It implements launcher_app's signatures and answers its sentinels, so every call site
works unchanged and any failure degrades to exactly today's behaviour.

WHY A TIER. The launcher's behaviour lives in virt_team_launcher: `run_app` returns a
PICK and `_decision_from_pick` does everything after it - the request composer, Jira,
archive, artifacts, watch, review. A second launcher would have to reimplement all of
that and then be kept in step with it forever; a tier only has to draw. So this file
knows how to render a menu and nothing about what any choice means.

APP_FALLBACK is returned for anything this tier cannot draw, which is the contract the
callers already handle.

Opt out: VIRT_SURV_NO_TEXTUAL=1 skips just this tier; VIRT_SURV_NO_APP=1 skips every
full-screen tier, as it always has.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

try:
    # The sentinel is launcher_app's, imported rather than restated so the two can
    # never disagree about what "fall through" means.
    from launcher_app import APP_FALLBACK
except Exception:                       # pragma: no cover - bare clone
    APP_FALLBACK = "__app_fallback__"

REPO = Path(__file__).resolve().parent.parent


def available() -> bool:
    """Will this tier actually draw?

    Asked BEFORE the launcher prints anything, because the app owns the alternate
    screen: a banner printed in front of it is still in the scrollback after it
    releases, so the new UI arrives bracketed by the old one.
    """
    return _widgets() is not None


def _widgets():
    """The widget module, or None when this tier cannot run here.

    Defensive on purpose: this tier must never be the reason a launch fails, and a
    clone without the vendored Textual is a normal state rather than an error.
    """
    if os.environ.get("VIRT_SURV_NO_APP") or os.environ.get("VIRT_SURV_NO_TEXTUAL"):
        return None
    # A REAL terminal, or nothing. Textual's run() takes over the terminal and waits;
    # with no tty there is nobody to press a key, so it blocks forever. launcher_app's
    # own tier makes the same check before it will draw.
    for stream in (sys.stderr, sys.stdin):
        try:
            if not stream.isatty():
                return None
        except Exception:               # noqa: BLE001 — a stream that cannot answer is a no
            return None
    for p in (str(REPO / "vendor"), str(REPO / "scripts")):
        if p not in sys.path:
            sys.path.insert(0, p)
    try:
        import launcher_tiers
        return launcher_tiers
    except Exception:                   # noqa: BLE001
        return None


def run_app(project_dir: Path, mod, menu: dict, shown: list, jira_on: bool = False,
            output=None):
    """The engagement menu, rendered in Textual.

    Same signature and same return as launcher_app.run_app: a pick tuple
    (("resume", i) / ("new",) / ("jira",) / ("settings",) / ("open",) /
    ("artifacts",) / ("archive",) / ("finished",) / ("watch",) / ("launch",)), or
    APP_FALLBACK when this tier cannot run.
    """
    widgets = _widgets()
    if widgets is None:
        return APP_FALLBACK

    try:
        views = [mod.row_view(r, default_slug=menu.get("default") or "",
                              of_many=len(shown) > 1) for r in shown]
    except Exception:                   # noqa: BLE001
        return APP_FALLBACK

    try:
        app = widgets.MenuApp(project_dir, views, _actions(project_dir, mod, shown,
                                                           jira_on), menu)
        app.run()
    except Exception:                   # noqa: BLE001 — any failure degrades
        return APP_FALLBACK
    pick = getattr(app, "pick", None)
    return APP_FALLBACK if pick is None else pick


def _actions(project_dir: Path, mod, shown: list, jira_on: bool) -> list:
    """(pick, label, hotkey) rows, in launcher_app.run_app's order and conditions.

    The GUARDS are v1's: `watch` only when something is running, `artifacts` and
    `archive` only when there is an open engagement. Offering a key that cannot work
    is worse than not offering it.
    """
    try:
        g = mod.glyphs(mod)
    except Exception:                   # noqa: BLE001
        g = {}

    def label(key, text):
        return f"{g.get(key, '')}{text}"

    out = [(("new",), label("new", "a new engagement"), "n")]
    if jira_on:
        out.append((("jira",), label("jira", "a new engagement from a Jira ticket"), "j"))
    out.append((("settings",), label("settings", "change a project setting"), "c"))
    out.append((("open",), label("open", "open a different project folder"), "o"))
    if shown:
        out.append((("artifacts",), label("archive", "view an engagement's artifacts"), "v"))
        out.append((("archive",), label("archive", "archive engagement(s)"), "a"))
    out.append((("finished",), label("browse", "browse done & archived"), "b"))
    try:
        if mod._running_slug(project_dir):
            out.append((("watch",), label("launch", "watch the engagement running"), "t"))
    except Exception:                   # noqa: BLE001 — a missing option must not cost the menu
        pass
    out.append((("launch",),
                label("launch", "decide inside the session" if shown else "just launch"),
                None))
    return out
