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
except Exception:  # pragma: no cover - bare clone
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
        except Exception:  # noqa: BLE001 — a stream that cannot answer is a no
            return None
    for p in (str(REPO / "vendor"), str(REPO / "scripts")):
        if p not in sys.path:
            sys.path.insert(0, p)
    try:
        import launcher_tiers

        return launcher_tiers
    except Exception:  # noqa: BLE001
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
        except Exception:  # noqa: BLE001 — a stream that cannot answer is a no
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


def run_app(project_dir: Path, mod, menu: dict, shown: list, jira_on: bool = False, output=None):
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
        views = [
            mod.row_view(r, default_slug=menu.get("default") or "", of_many=len(shown) > 1)
            for r in shown
        ]
    except Exception:  # noqa: BLE001
        return APP_FALLBACK

    try:
        app = widgets.MenuApp(project_dir, views, _actions(project_dir, mod, shown, jira_on), menu)
        with _true_terminal_size():
            app.run()
    except Exception:  # noqa: BLE001 — any failure degrades
        return APP_FALLBACK
    if not getattr(app, "ran", False):
        return APP_FALLBACK  # never drew: let the next tier try
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
    except Exception:  # noqa: BLE001
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
    except Exception:  # noqa: BLE001 — a missing option must not cost the menu
        pass
    out.append(
        (
            ("launch",),
            label("launch", "decide inside the session" if shown else "just launch"),
            None,
        )
    )
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
    except Exception:  # noqa: BLE001
        offered = False
    try:
        armed = bool(mod._auto_armed(project_dir)) if offered else False
    except Exception:  # noqa: BLE001
        armed = False

    try:
        app = widgets.RequestApp(project_dir, auto_offered=offered, auto=armed)
        with _true_terminal_size():
            app.run()
    except Exception:  # noqa: BLE001 — any failure degrades
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
            return None  # no settings to draw is not a settings screen
    except Exception:  # noqa: BLE001
        return None
    try:
        app = widgets.SettingsApp(project_dir, mod)
        with _true_terminal_size():
            app.run()
    except Exception:  # noqa: BLE001 — any failure degrades
        return None
    if not getattr(app, "ran", False):
        return None
    return bool(getattr(app, "changed", False))


def chooser_screen(options, ih, *, title: str, actions=None, repo=None, output=None):
    """One installer menu as a full-screen picker, rendered in Textual.

    Same contract as installer_app.chooser_screen: the chosen key, "" for back/Esc, or
    None when the screen could not run at all - the caller then prints its numbered
    menu exactly as before. The None-vs-"" distinction is not decoration: a cancel is a
    decision, not an unavailability, and conflating the two once dumped someone into an
    old numbered editor after they had cancelled.

    The ROWS come from installer_app's own `_rows`, deliberately. It splits each label
    from its explanation and looks up what the key touches outside the repo - using the
    caller's own key->action table, because the same key means different things in
    different menus ("1" is a full install at the top level and environment-setup-only
    under Advanced). Rebuilding any of that here is how the two tiers would come to
    disagree about what an option does, on the screen where that matters most.
    """
    widgets = _widgets()
    if widgets is None:
        return None
    try:
        import installer_app

        rows = installer_app._rows(options, ih, actions)
        marker_kind = installer_app._marker_kind
    except Exception:  # noqa: BLE001
        return None
    if not rows:
        return None

    try:
        app = widgets.ChooserApp(Path(repo) if repo else Path.cwd(), rows, title, marker_kind)
        with _true_terminal_size():
            app.run()
    except Exception:  # noqa: BLE001 — any failure degrades
        return None
    if not getattr(app, "ran", False):
        return None
    return getattr(app, "picked", "")


def setup_screen(project_dir: Path, mod, output=None):
    """The first-time-setup screen, rendered in Textual.

    Same contract and the same four sentinels as launcher_app.setup_screen, including the
    one that matters most: CANCEL is not SKIP. Skip launches without configuring; cancel
    launches nothing. Returns None only when this tier cannot draw, which is the signal
    the caller uses to fall through - never to mean "the user declined".
    """
    widgets = _widgets()
    if widgets is None:
        return None
    try:
        from launcher_app import (
            SETUP_CANCEL,
            SETUP_DEFAULTS,
            SETUP_GUIDED,
            SETUP_SKIP,
        )
    except Exception:  # noqa: BLE001
        return None
    rows = [
        (SETUP_DEFAULTS, "set up with recommended defaults", "no questions asked"),
        (SETUP_GUIDED, "guided setup", "asks questions; leaves this screen"),
        (SETUP_SKIP, "skip for now", "launch without setting up"),
    ]
    try:
        app = widgets.SetupApp(project_dir, rows, SETUP_CANCEL)
        with _true_terminal_size():
            app.run()
    except Exception:  # noqa: BLE001 — any failure degrades
        return None
    if not getattr(app, "ran", False):
        return None
    return getattr(app, "picked", SETUP_CANCEL)


def archive_screen(project_dir: Path, mod, engagement_state, menu: dict, output=None):
    """The [a] screen, rendered in Textual.

    Returns True when something was archived, False when the user left without acting,
    and None when this tier cannot draw - the same three answers launcher_app gives, and
    the same reason they are three: "did nothing" and "could not run" lead somewhere
    different.
    """
    widgets = _widgets()
    if widgets is None:
        return None
    shown = list(menu.get("shown") or [])
    if not shown:
        return None  # nothing to archive: the caller owns that message
    open_rows = list(menu.get("open") or shown)
    try:
        views = [mod.row_view(r) for r in shown]
        app = widgets.ArchiveApp(project_dir, views, len(open_rows))
        with _true_terminal_size():
            app.run()
    except Exception:  # noqa: BLE001 — any failure degrades
        return None
    if not getattr(app, "ran", False):
        return None
    index = getattr(app, "picked", None)
    if index is None:
        return False  # left without archiving - a decision, not a failure
    targets = open_rows if index >= len(views) else [shown[index]]
    try:
        mod._archive_perform(engagement_state, targets)
        return True
    except Exception:  # noqa: BLE001
        return False


def finished_screen(project_dir: Path, mod, engagement_state, output=None):
    """The [b] screen, rendered in Textual. Returns the resume token, a
    ("supersede", slug) pair, "" for back, or None when this tier cannot draw."""
    widgets = _widgets()
    if widgets is None:
        return None
    try:
        from launcher_app import _vsit_paths

        rows = engagement_state.finished_engagements(_vsit_paths().engagements_dir(project_dir))
    except Exception:  # noqa: BLE001
        return None
    if not rows:
        return None  # the fallback menu owns the "nothing yet" message
    try:
        views = [mod.row_view(r) for r in rows]
        slugs = [mod._row_resume_token(r) or "" for r in rows]
        app = widgets.FinishedApp(
            project_dir,
            views,
            slugs,
            lambda slug: mod._record_sign_off(project_dir, slug),
            lambda slug: mod._sign_off_state(project_dir, slug) if slug else "",
        )
        with _true_terminal_size():
            app.run()
    except Exception:  # noqa: BLE001
        return None
    if not getattr(app, "ran", False):
        return None
    return getattr(app, "picked", "")


def artifacts_screen(project_dir: Path, mod, slug: str, output=None):
    """The [v] screen, rendered in Textual. True when it ran, None when it could not."""
    widgets = _widgets()
    if widgets is None:
        return None
    try:
        items = mod._engagement_artifacts(project_dir, slug)
    except Exception:  # noqa: BLE001
        return None
    if not items:
        return None
    labels = [label for label, _path in items]
    try:
        app = widgets.ArtifactsApp(project_dir, labels, f"Artifacts  ·  {slug}")
        with _true_terminal_size():
            app.run()
    except Exception:  # noqa: BLE001
        return None
    if not getattr(app, "ran", False):
        return None
    index = getattr(app, "picked", None)
    if index is not None and 0 <= index < len(items):
        try:
            mod._open_path(items[index][1])
        except Exception:  # noqa: BLE001 - failing to open is not a crash
            pass
    return True


def slug_picker_screen(project_dir: Path, mod, shown: list, output=None):
    """Pick one open engagement. Returns the slug, or "" on cancel/unavailable."""
    widgets = _widgets()
    if widgets is None:
        return ""  # this screen's unavailable IS its cancel
    if not shown:
        return ""
    try:
        views = [mod.row_view(r) for r in shown]
        app = widgets.SlugPickerApp(project_dir, views, "Which engagement?")
        with _true_terminal_size():
            app.run()
    except Exception:  # noqa: BLE001
        return ""
    if not getattr(app, "ran", False):
        return ""
    index = getattr(app, "picked", None)
    if index is None or not (0 <= index < len(shown)):
        return ""
    return mod._row_resume_token(shown[index]) or ""


def browse_screen(start_dir: Path, mod, output=None):
    """The project explorer, rendered in Textual.

    Returns the chosen Path, BROWSE_CANCELLED on Esc, or None when this tier cannot draw -
    the same three answers launcher_app gives, and all three are different: a cancel must
    not fall through to the next tier, which would draw the same explorer again.
    """
    widgets = _widgets()
    if widgets is None:
        return None
    try:
        from launcher_app import BROWSE_CANCELLED, _dir_entries
    except Exception:  # noqa: BLE001
        return None
    try:
        here = start_dir.resolve()
    except Exception:  # noqa: BLE001
        here = start_dir
    try:
        recents = mod._recent_projects()
    except Exception:  # noqa: BLE001
        recents = []

    def rows_for(directory):
        """(label, kind, payload) - the same four kinds launcher_app builds, from the
        same helper, so the two explorers cannot disagree about what a row is."""
        rows = [(f"use this folder  ({directory.name or directory})", "use", directory)]
        if directory.parent != directory:
            rows.append(
                (".. up to " + (directory.parent.name or str(directory.parent)), "up", None)
            )
        for recent in recents:
            if recent != directory:
                rows.append((f"{recent.name}", "recent", recent))
        try:
            for child, is_project in _dir_entries(directory, mod):
                rows.append((child.name, "dir", (child, is_project)))
        except Exception:  # noqa: BLE001 - an unreadable directory is still browsable
            pass
        return rows

    try:
        app = widgets.BrowseApp(start_dir, here, rows_for, recents)
        with _true_terminal_size():
            app.run()
    except Exception:  # noqa: BLE001
        return None
    if not getattr(app, "ran", False):
        return None
    picked = getattr(app, "picked", None)
    return BROWSE_CANCELLED if picked is None else picked


def auto_preflight_screen(project_dir: Path, mod, ref: str, output=None):
    """The unattended authorisation gate, rendered in Textual.

    Returns the authorisations dict, AUTO_CANCELLED, or None when this tier cannot draw.

    The rows, the defaults and the answer shape all come from launcher_app: this is the
    single gate that arms an unattended run, and a second copy of WHAT is being authorised
    is the last thing that should exist. Only the drawing is here.
    """
    widgets = _widgets()
    if widgets is None:
        return None
    try:
        from launcher_app import AUTO_CANCELLED, _preflight_model
    except Exception:  # noqa: BLE001
        return None
    try:
        model = _preflight_model()
    except Exception:  # noqa: BLE001
        return None
    try:
        app = widgets.PreflightApp(
            project_dir,
            model["rows"],
            model["state"],
            model["value_of"],
            model["caps"],
            model["on_budget"],
            model["modes"],
        )
        with _true_terminal_size():
            app.run()
    except Exception:  # noqa: BLE001
        return None
    if not getattr(app, "ran", False):
        return None
    if not getattr(app, "confirmed", False):
        return AUTO_CANCELLED
    return model["answers"](app.state)
