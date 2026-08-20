#!/usr/bin/env python3
"""Full-screen launcher app for `virt-surv go` (prototype, 2026-08-20).

Phase 2 of docs/internal/plan-tui-app-2026-08-20.md. Built on the ALREADY-VENDORED
prompt_toolkit (3.0.53) - no new dependency. Textual was measured and rejected for now: it
needs 10 packages/2.5MB including exactly the pygments/markdown-it tree this repo
deliberately avoided when it vendored a trimmed `rich`, and the launcher is the one
component that must work before anything else on a locked-down corporate box.

WHAT IT FIXES. Not "it looks plain" - the launcher had TWO renderers kept in visual sync
by hand, and they diverged for real (2026-08-19: a redesign reached the numbered tier
only, while the picker tier - the one most users see - kept the old rows until a
screenshot exposed it). Row CONTENT now comes from `virt_team_launcher.row_view()`, which
every tier shares; this file only decides layout.

CONTRACTS THAT MUST HOLD (each has already caused a live bug):
  * stdout is the DECISION channel. This app renders to STDERR and writes nothing to
    stdout, ever - the caller prints the decision after the app exits.
  * cp1252 consoles: box characters are chosen through `_can_encode`, never assumed.
  * It is a TIER, not a replacement: any failure returns the fallback sentinel and the
    numbered flow takes over, exactly as the picker does today.
  * Headlessly drivable (VIRT_SURV_FORCE_PTK + pipe input), because an untestable tier is
    how the drift went unnoticed in the first place.
"""

from __future__ import annotations

import sys
from pathlib import Path

APP_FALLBACK = "__app_fallback__"


def _bits(project_dir: Path, mod):
    """Header facts, reusing the launcher's own resolvers so nothing is re-derived."""
    facts = [project_dir.resolve().name or str(project_dir)]
    version = mod._plugin_version()
    if version:
        facts.append(f"v{version}")
    branch = mod._git_branch(project_dir)
    if branch:
        facts.append(branch)
    return "  ·  ".join(facts)


def run_app(project_dir: Path, mod, menu: dict, shown: list, jira_on: bool = False, output=None):
    """One full-screen round. Returns the same decision values `_pt_menu_round` does
    (("resume", i) / ("new",) / ("jira",) / ("settings",) / ("archive",) / ("launch",)),
    None on Esc, or APP_FALLBACK when the app cannot run here."""
    try:
        p = mod._ptk_ui()
        if not p:
            return APP_FALLBACK
        from prompt_toolkit.application import Application
        from prompt_toolkit.formatted_text import to_formatted_text
        from prompt_toolkit.key_binding import KeyBindings
        from prompt_toolkit.layout import HSplit, Layout, VSplit, Window
        from prompt_toolkit.layout.controls import FormattedTextControl
        from prompt_toolkit.layout.dimension import D
        from prompt_toolkit.widgets import Frame
        from prompt_toolkit.output.defaults import create_output
        from prompt_toolkit.styles import Style
    except Exception:
        return APP_FALLBACK

    default_slug = menu.get("default") or ""
    views = [mod.row_view(r, default_slug=default_slug, of_many=len(shown) > 1) for r in shown]
    actions: list[tuple] = [(("new",), "[n]  a new engagement")]
    if jira_on:
        actions.append((("jira",), "[j]  a new engagement from a Jira ticket"))
    actions.append((("settings",), "[c]  change a project setting"))
    if shown:
        actions.append((("archive",), "[a]  archive engagement(s)"))
    actions.append(
        (("launch",), "[Enter] decide inside the session" if shown else "[Enter] just launch")
    )
    # One flat selection list over both regions, so Up/Down crosses the boundary naturally.
    items: list[tuple] = [(("resume", i), None) for i in range(len(views))] + [
        (ret, None) for ret, _label in actions
    ]
    idx = [0 if views else 0]
    result = {"v": None}

    def _left():
        out = []
        if views:
            out.append(("class:group", "  Resume an engagement\n"))
            for i, v in enumerate(views):
                sel = idx[0] == i
                out.append(("class:sel" if sel else "", "  > " if sel else "    "))
                out.append(
                    ("class:warn" if v["mark_style"] == "warn" else "class:dim", f"{v['mark']} ")
                )
                out.append(("class:sel" if sel else "class:title", v["title"]))
                if v["recommended"]:
                    out.append(("class:on", "  <- most recent"))
                out.append(("", "\n"))
            more = menu.get("more") or 0
            if more:
                out.append(("class:dim", f"      (+{more} more)\n"))
            out.append(("", "\n"))
        else:
            archived = menu.get("archived") or 0
            note = (
                f"no open engagements ({archived} archived)" if archived else "no open engagements"
            )
            out.append(("class:dim", f"  {note}\n\n"))
        # Actions carry their own group headings, so "change a project setting" never
        # reads as an engagement (the mis-grouping fixed in the plain tier on 2026-08-20).
        printed_or = False
        out.append(("class:group", "  Start something new\n"))
        for offset, (ret, label) in enumerate(actions):
            i = len(views) + offset
            if ret[0] in ("settings", "archive", "launch") and not printed_or:
                out.append(("", "\n"))
                out.append(("class:group", "  Or\n"))
                printed_or = True
            sel = idx[0] == i
            out.append(("class:sel" if sel else "", "  > " if sel else "    "))
            out.append(("class:sel" if sel else "", label + "\n"))
        return to_formatted_text(out)

    def _right():
        """Detail pane - the real gain over cramming everything onto one row."""
        if not views or idx[0] >= len(views):
            return to_formatted_text(
                [
                    (
                        "class:dim",
                        "\n  Nothing selected.\n\n  Pick an engagement to see its\n"
                        "  state, or start something new.\n",
                    )
                ]
            )
        v = views[idx[0]]
        out = [("class:title", f"\n  {v['title']}\n\n")]
        for label, value in v["lines"]:
            out.append(("class:dim", f"  {label:<8}"))
            style = "class:warn" if label in ("status", "next") and v["status"] == "blocked" else ""
            out.append((style, f"{value}\n"))
        return to_formatted_text(out)

    def _footer():
        """Keys first (a full-screen app has to teach its own navigation), then the one
        contextual nudge if there is something worth saying."""
        try:
            hint = mod._suggestion_line(project_dir, menu)
        except Exception:
            hint = ""
        out = [("class:dim", "  ↑↓ move · Enter choose · Esc decide in session")]
        if hint:
            out.append(("class:warn", f"   ⚠ {hint}"))
        return to_formatted_text(out)

    kb = KeyBindings()

    def _exit(event, value):
        result["v"] = value
        event.app.exit()

    @kb.add("up")
    def _up(event):
        idx[0] = (idx[0] - 1) % len(items)

    @kb.add("down")
    def _down(event):
        idx[0] = (idx[0] + 1) % len(items)

    @kb.add("enter")
    def _enter(event):
        _exit(event, items[idx[0]][0])

    @kb.add("escape", eager=True)
    @kb.add("c-c")
    @kb.add("q")
    def _esc(event):
        _exit(event, None)

    for key, ret in (("n", ("new",)), ("j", ("jira",)), ("c", ("settings",)), ("a", ("archive",))):
        if any(r == ret for r, _ in actions):
            kb.add(key)(lambda event, _r=ret: _exit(event, _r))

    for i, _v in enumerate(views):
        if i < 9:
            kb.add(str(i + 1))(lambda event, _i=i: _exit(event, ("resume", _i)))

    frame_title = f"Virtual Surv-IT  ·  {_bits(project_dir, mod)}"
    body = VSplit(
        [
            Window(FormattedTextControl(_left), wrap_lines=False),
            Window(width=1, char="│" if mod._can_encode("│") else "|", style="class:dim"),
            Window(FormattedTextControl(_right), width=D(min=28, weight=1), wrap_lines=True),
        ]
    )
    root = HSplit(
        [
            Window(
                FormattedTextControl(
                    lambda: to_formatted_text([("class:title", f"  {mod._morgan_line()}")])
                ),
                height=1,
            ),
            Frame(body, title=frame_title),
            Window(FormattedTextControl(_footer), height=1),
        ]
    )
    style = Style.from_dict(
        {
            "title": "bold",
            "group": "bold",
            "dim": "#888888",
            "warn": "#d29922",
            "on": "#3fb950",
            "sel": "reverse",
        }
    )
    try:
        app = Application(
            layout=Layout(root),
            key_bindings=kb,
            style=style,
            full_screen=True,
            mouse_support=True,
            # STDERR, never stdout: the caller's shell captures stdout as the decision.
            # `output` is injectable ONLY so the tier can be driven headlessly in tests -
            # an untestable tier is precisely how the two renderers drifted apart.
            output=output or create_output(stdout=sys.stderr),
        )
        app.run()
    except Exception:
        return APP_FALLBACK
    return result["v"]
