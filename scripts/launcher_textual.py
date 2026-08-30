#!/usr/bin/env python3
"""The Textual rendering tier for `virt-surv go`.

A THIRD tier above the existing two, not a replacement and not a fork. It implements
`launcher_app`'s signatures and answers its sentinels, so every call site works
unchanged and any failure degrades to exactly today's behaviour:

    Textual  ->  prompt_toolkit (launcher_app)  ->  numbered input()

Why a tier rather than a second launcher. Everywhere virt-surv2 DRIVES v1 - the whole
installer - parity has held. Every parity loss was in a screen it reimplemented, and
copying v1 to restyle it would freeze that problem rather than fix it: two codebases,
every future fix applied twice, and the parity tests left with nothing single to check
against. Rendering is the only thing that differs, so rendering is the only thing this
file owns.

In particular `run_app` returns a PICK, and `_decision_from_pick` does everything
after it - the request composer, Jira, archive, artifacts, watch, review. So this file
does not need to know what any of them mean.

APP_FALLBACK is returned for anything this tier cannot draw, which is the contract the
callers already handle.
"""

from __future__ import annotations

import os
from pathlib import Path

# The sentinel is launcher_app's, imported rather than restated so the two can never
# disagree about what "fall through" means.
try:
    from launcher_app import APP_FALLBACK
except Exception:                       # pragma: no cover - bare clone
    APP_FALLBACK = "__app_fallback__"

REPO = Path(__file__).resolve().parent.parent


def _ui():
    """The shared widgets, or None when Textual cannot be loaded here.

    Imported lazily and defensively: this tier must never be the reason a launch
    fails, and a clone without the vendored Textual is a normal state, not an error.
    """
    if os.environ.get("VIRT_SURV_NO_APP") or os.environ.get("VIRT_SURV_NO_TEXTUAL"):
        return None
    # A REAL terminal, or nothing. Textual's run() takes over the terminal and waits;
    # with no tty there is nobody to press a key, so it blocks forever - which is what
    # it did to the test suite the moment this tier was wired in. launcher_app's own
    # tier makes the same check before it will draw.
    import sys as _sys

    for stream in (_sys.stderr, _sys.stdin):
        try:
            if not stream.isatty():
                return None
        except Exception:               # noqa: BLE001 — a stream that cannot answer is a no
            return None
    for p in (str(REPO / "vendor"), str(REPO)):
        import sys
        if p not in sys.path:
            sys.path.insert(0, p)
    try:
        from virt_surv2 import ui as vs_ui
        return vs_ui
    except Exception:                   # noqa: BLE001
        return None


def available() -> bool:
    """Will this tier actually draw? Asked BEFORE the launcher prints anything.

    The Textual app owns the alternate screen, so v1's banner printed before it and was
    still in the scrollback after it released - the new UI sandwiched in the old one
    ("it shows the old interface, then the new, and on exit the old again"). Knowing up
    front lets the launcher skip the chrome the app is about to replace.
    """
    return _ui() is not None


def run_app(project_dir: Path, mod, menu: dict, shown: list, jira_on: bool = False,
            output=None):
    """The engagement menu, rendered in Textual.

    Same signature and same return as launcher_app.run_app: a pick tuple
    (("resume", i) / ("new",) / ("jira",) / ("settings",) / ("open",) /
    ("artifacts",) / ("archive",) / ("finished",) / ("watch",) / ("launch",)),
    or APP_FALLBACK when this tier cannot run.

    The ROWS are built exactly as launcher_app builds them - same helpers, same order,
    same conditions - because a second list is a second thing to keep in step.
    """
    vs_ui = _ui()
    if vs_ui is None:
        return APP_FALLBACK

    try:
        views = [mod.row_view(r, default_slug=menu.get("default") or "",
                              of_many=len(shown) > 1) for r in shown]
        for view, row in zip(views, shown):
            view["row"] = row           # so a resume token can be derived later
    except Exception:                   # noqa: BLE001
        return APP_FALLBACK

    actions = _actions(project_dir, mod, shown, jira_on)

    try:
        app = vs_ui.LauncherTierApp(project_dir, views, actions, menu)
        app.run()
    except Exception:                   # noqa: BLE001 — any failure degrades
        return APP_FALLBACK
    pick = getattr(app, "pick", None)
    return APP_FALLBACK if pick is None else pick


def _tiers():
    """The screen classes, or None when this tier cannot run at all."""
    if _ui() is None:
        return None
    try:
        from virt_surv2 import tiers
        return tiers
    except Exception:                   # noqa: BLE001
        return None


def _run(app):
    """Run one tier app and return its result, or None if it could not run.

    None is launcher_app's "this tier cannot draw" sentinel on every screen, so a
    failure here always lands on the tier below rather than on a broken screen.
    """
    try:
        app.run()
    except Exception:                   # noqa: BLE001
        return None
    return getattr(app, "result", None)


def settings_screen(project_dir: Path, mod, output=None):
    """True/False when the screen RAN, None when this tier cannot."""
    t = _tiers()
    if t is None:
        return None
    return _run(t.SettingsTier(project_dir, mod))


def finished_screen(project_dir: Path, mod, engagement_state, output=None):
    """The chosen resume token, "" on Esc, None when this tier cannot run."""
    t = _tiers()
    if t is None:
        return None
    try:
        root = mod._vsit_paths().engagements_dir(Path(project_dir))
        rows = engagement_state.finished_engagements(root)
        views = []
        for r in rows:
            v = mod.row_view(r)
            v["row"] = r
            v["archived"] = bool(r.get("archived"))
            views.append(v)
    except Exception:                   # noqa: BLE001
        return None
    return _run(t.FinishedTier(project_dir, mod, views))


def archive_screen(project_dir: Path, mod, engagement_state, menu: dict, output=None):
    """None when this tier cannot run; otherwise it has done the archiving."""
    t = _tiers()
    if t is None:
        return None
    rows = (menu or {}).get("open") or []
    return _run(t.ArchiveTier(project_dir, mod, engagement_state, rows))


def request_screen(project_dir: Path, mod, output=None):
    """(request, auto), the caller's REQUEST_SKIPPED, or None."""
    t = _tiers()
    if t is None:
        return None
    try:
        from launcher_app import REQUEST_SKIPPED
    except Exception:                   # noqa: BLE001
        return None
    return _run(t.RequestTier(project_dir, REQUEST_SKIPPED))


def jira_screen(project_dir: Path, mod, output=None):
    """The ticket ref, the caller's JIRA_CANCELLED, or None."""
    t = _tiers()
    if t is None:
        return None
    try:
        from launcher_app import JIRA_CANCELLED
    except Exception:                   # noqa: BLE001
        return None
    return _run(t.JiraTier(project_dir, mod, JIRA_CANCELLED))


def browse_screen(start_dir: Path, mod, output=None):
    """A Path, the caller's BROWSE_CANCELLED, or None."""
    t = _tiers()
    if t is None:
        return None
    try:
        from launcher_app import BROWSE_CANCELLED
    except Exception:                   # noqa: BLE001
        return None
    return _run(t.BrowseTier(start_dir, mod, BROWSE_CANCELLED))


def setup_screen(project_dir: Path, mod, output=None):
    """SETUP_DEFAULTS / SETUP_GUIDED / SETUP_SKIP / SETUP_CANCEL, or None.

    Skip and cancel are different answers and must stay so: skip launches without
    configuring, cancel launches nothing at all.
    """
    t = _tiers()
    if t is None:
        return None
    try:
        from launcher_app import (SETUP_CANCEL, SETUP_DEFAULTS, SETUP_GUIDED,
                                  SETUP_SKIP)
    except Exception:                   # noqa: BLE001
        return None
    options = [
        (SETUP_DEFAULTS, "Set it up with the recommended defaults",
         "Applies every recommended project default with no questions: enable the team "
         "here, permissions, preferences and the orchestrator model. The usual answer."),
        (SETUP_GUIDED, "Walk me through it",
         "The same setup, asking about each part, with the recommended answer "
         "pre-filled."),
        (SETUP_SKIP, "Not now",
         "Launches without configuring this folder. The team will not run here until "
         "it is set up."),
    ]
    return _run(t.SetupTier(project_dir, options, cancel_value=SETUP_CANCEL))


def slug_picker_screen(project_dir: Path, mod, shown: list, output=None):
    """The chosen slug, or "" on cancel/unavailable."""
    t = _tiers()
    if t is None:
        return None
    options = []
    for row in shown:
        try:
            slug = mod._row_resume_token(row) or "?"
        except Exception:               # noqa: BLE001
            slug = "?"
        options.append((slug, slug, row.get("status") or ""))
    result = _run(t.SlugPickTier(project_dir, options, cancel_value=""))
    return result or ""


def _actions(project_dir: Path, mod, shown: list, jira_on: bool) -> list:
    """(pick, label, hotkey) rows, in launcher_app.run_app's order and conditions.

    `watch` appears only when something is running, and `artifacts`/`archive` only
    when there is an open engagement - the same guards, because offering a key that
    cannot work is the defect this file exists to avoid repeating.
    """
    g = {}
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
