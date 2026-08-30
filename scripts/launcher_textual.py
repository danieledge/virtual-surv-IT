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

import contextlib
import os
import sys
from pathlib import Path

try:
    # The sentinels are launcher_app's, imported rather than restated so the two can
    # never disagree about what "fall through" or "skipped" means.
    from launcher_app import APP_FALLBACK, REQUEST_SKIPPED
except Exception:                       # pragma: no cover - bare clone
    APP_FALLBACK = "__app_fallback__"
    REQUEST_SKIPPED = "__request_skipped__"

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


@contextlib.contextmanager
def _true_terminal_size():
    """Let Textual measure the REAL terminal for as long as it is drawing.

    Textual sizes itself with shutil.get_terminal_size(), which reads COLUMNS/LINES
    from the environment first and otherwise measures `sys.__stdout__`. Neither is
    usable here:

      * The launcher's stdout is a PIPE. The alias captures the decision string with
        `$(...)`, so measuring stdout raises and Textual falls back to its 80x25
        default. Drawn into a 66-column phone pane that wrapped every line, and the
        wrapped remnants read as a second, mangled copy of the screen.
      * COLUMNS/LINES, if exported at all, are whatever they were when some ancestor
        shell last looked, and they OUTRANK the real measurement - including on a
        resize, which would leave the app permanently wrong.

    So for the duration of the run, point the measurement at the tty we already
    require and drop the two variables. Both are restored afterwards. This is
    deliberately dynamic rather than a one-off COLUMNS export: Textual re-measures on
    SIGWINCH, and a pinned value would break resizing to fix sizing.
    """
    tty = None
    for stream in (sys.stderr, sys.stdin):
        try:
            if stream is not None and stream.isatty():
                stream.fileno()
                tty = stream
                break
        except Exception:               # noqa: BLE001 — a stream that cannot answer is a no
            continue
    saved_stdout = sys.__stdout__
    saved_env = {k: os.environ[k] for k in ("COLUMNS", "LINES") if k in os.environ}
    try:
        if tty is not None:
            sys.__stdout__ = tty
            for k in saved_env:
                os.environ.pop(k, None)
        yield
    finally:
        sys.__stdout__ = saved_stdout
        os.environ.update(saved_env)


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
        with _true_terminal_size():
            app.run()
    except Exception:                   # noqa: BLE001 — any failure degrades
        return APP_FALLBACK
    if not getattr(app, "ran", False):
        return APP_FALLBACK             # never drew: let the next tier try
    # It drew. Its answer stands, INCLUDING None - which launcher_app uses for "the
    # human backed out" and _decision_from_pick turns into launch-nothing. Returning
    # the fallback sentinel there instead sent Esc to the next tier, which drew the
    # old menu underneath the one just dismissed.
    return getattr(app, "pick", None)


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


def request_screen(project_dir: Path, mod, output=None):
    """The request for a NEW engagement, rendered in Textual.

    Same contract as launcher_app.request_screen: (request, auto) when text was typed,
    REQUEST_SKIPPED for the plain launch, or None when this tier cannot draw - which is
    what sends the caller down to the prompt_toolkit screen.

    Note the asymmetry, which is the same one the menu had to learn: an EMPTY send and
    an Esc are both REQUEST_SKIPPED (the human chose the plain launch), and only a
    screen that could not run answers None. Returning None for a deliberate skip would
    draw the old composer straight after this one closed.
    """
    widgets = _widgets()
    if widgets is None:
        return None

    # Asked here rather than inside the widget, so the drawing layer keeps knowing
    # nothing about the project's preferences.
    try:
        offered = bool(mod._auto_offered(project_dir))
    except Exception:                   # noqa: BLE001
        offered = False
    try:
        armed = bool(mod._auto_armed(project_dir)) if offered else False
    except Exception:                   # noqa: BLE001
        armed = False

    try:
        app = widgets.RequestApp(project_dir, auto_offered=offered, auto=armed)
        with _true_terminal_size():
            app.run()
    except Exception:                   # noqa: BLE001 — any failure degrades
        return None
    if not getattr(app, "ran", False):
        return None
    return getattr(app, "value", None) or REQUEST_SKIPPED


def settings_screen(project_dir: Path, mod, output=None):
    """The [c] screen, rendered in Textual.

    Same contract as launcher_app.settings_screen: True/False when the screen RAN
    (changed something or not), and None ONLY when it could not run at all. The caller
    falls through on None alone - conflating the two once meant that cancelling this
    screen dropped the user into the numbered editor.
    """
    widgets = _widgets()
    if widgets is None:
        return None
    try:
        if not (mod._editor_rows(project_dir) or []):
            return None                 # no settings to draw is not a settings screen
    except Exception:                   # noqa: BLE001
        return None
    try:
        app = widgets.SettingsApp(project_dir, mod)
        with _true_terminal_size():
            app.run()
    except Exception:                   # noqa: BLE001 — any failure degrades
        return None
    if not getattr(app, "ran", False):
        return None
    return bool(getattr(app, "changed", False))
