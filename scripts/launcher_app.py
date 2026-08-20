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


# Warm accent, closer to a Claude session than the default cyan-on-black (2026-08-20 user
# request). Every colour is a hex the terminal maps itself, so a 16-colour console still
# renders something sensible rather than nothing.
PALETTE = {
    "title": "bold #d97757",  # the accent - frame titles, headings
    "group": "bold #c9a227",  # group labels
    "dim": "#8a8f98",
    "warn": "#d29922",
    "on": "#3fb950",
    "off": "#8a8f98",
    "sel": "bold reverse",
    "key": "#7aa2f7",  # hotkeys
    "hint": "#6b7280",
}


def glyphs(mod):
    """Emoji where the console can encode them, ASCII where it cannot - the same
    _can_encode gate the wordmark and Morgan's hat already use, so a cp1252 corp console
    degrades to something readable instead of mojibake."""
    rich = mod._can_encode("📋⚙️📦▸✓✗⏳⛔🔒")
    return {
        "engagements": "📋 " if rich else "",
        "settings": "⚙️  " if rich else "",
        "archive": "📦 " if rich else "",
        "new": "✨ " if rich else "",
        "jira": "🎫 " if rich else "",
        "launch": "🚀 " if rich else "",
        "point": "▸" if rich else ">",
        "on": "✓" if rich else "on",
        "off": "·" if rich else "off",
        "in_progress": "⏳" if rich else "*",
        "blocked": "⛔" if rich else "!",
        "closing": "🔒" if rich else "~",
    }


def _style(mod):
    from prompt_toolkit.styles import Style

    return Style.from_dict(PALETTE)


def screen(mod, *, title, body_fn, footer_fn, key_bindings, output=None, right_fn=None):
    """One framed full-screen round, shared by EVERY launcher screen (menu, settings,
    archive). Written once so the screens cannot drift apart the way the two menu tiers
    did - the thing this whole effort exists to prevent."""
    from prompt_toolkit.application import Application
    from prompt_toolkit.layout import HSplit, Layout, VSplit, Window
    from prompt_toolkit.layout.controls import FormattedTextControl
    from prompt_toolkit.layout.dimension import D
    from prompt_toolkit.output.defaults import create_output
    from prompt_toolkit.widgets import Frame

    body = Window(FormattedTextControl(body_fn), wrap_lines=False)
    if right_fn is not None:
        body = VSplit(
            [
                body,
                Window(width=1, char="│" if mod._can_encode("│") else "|", style="class:dim"),
                Window(FormattedTextControl(right_fn), width=D(min=26, weight=1), wrap_lines=True),
            ]
        )
    root = HSplit(
        [
            Window(
                FormattedTextControl(lambda: [("class:title", f"  {mod._morgan_line()}")]),
                height=1,
            ),
            Frame(body, title=title),
            Window(FormattedTextControl(footer_fn), height=1),
        ]
    )
    app = Application(
        layout=Layout(root),
        key_bindings=key_bindings,
        style=_style(mod),
        full_screen=True,
        mouse_support=True,
        output=output or create_output(stdout=sys.stderr),
    )
    app.run()


def run_app(project_dir: Path, mod, menu: dict, shown: list, jira_on: bool = False, output=None):
    """One full-screen round. Returns the same decision values `_pt_menu_round` does
    (("resume", i) / ("new",) / ("jira",) / ("settings",) / ("archive",) / ("launch",)),
    None on Esc, or APP_FALLBACK when the app cannot run here."""
    try:
        p = mod._ptk_ui()
        if not p:
            return APP_FALLBACK
        from prompt_toolkit.formatted_text import to_formatted_text
        from prompt_toolkit.key_binding import KeyBindings
    except Exception:
        return APP_FALLBACK

    default_slug = menu.get("default") or ""
    views = [mod.row_view(r, default_slug=default_slug, of_many=len(shown) > 1) for r in shown]
    g = glyphs(mod)
    actions: list[tuple] = [(("new",), f"{g['new']}a new engagement", "n")]
    if jira_on:
        actions.append((("jira",), f"{g['jira']}a new engagement from a Jira ticket", "j"))
    actions.append((("settings",), f"{g['settings']}change a project setting", "c"))
    if shown:
        actions.append((("archive",), f"{g['archive']}archive engagement(s)", "a"))
    actions.append(
        (
            ("launch",),
            f"{g['launch']}" + ("decide inside the session" if shown else "just launch"),
            None,
        )
    )
    # One flat selection list over both regions, so Up/Down crosses the boundary naturally.
    items: list[tuple] = [(("resume", i), None) for i in range(len(views))] + [
        (ret, None) for ret, _label, _key in actions
    ]
    idx = [0 if views else 0]
    result = {"v": None}

    def _left():
        out = []
        if views:
            out.append(("class:group", f"  {g['engagements']}Resume an engagement\n"))
            for i, v in enumerate(views):
                sel = idx[0] == i
                out.append(("class:sel" if sel else "", f"  {g['point']} " if sel else "    "))
                out.append(
                    (
                        "class:warn" if v["mark_style"] == "warn" else "class:dim",
                        f"{g.get(v['status'], v['mark'])} ",
                    )
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
        out.append(("class:group", f"  {g['new']}Start something new\n"))
        for offset, (ret, label, key) in enumerate(actions):
            i = len(views) + offset
            if ret[0] in ("settings", "archive", "launch") and not printed_or:
                out.append(("", "\n"))
                out.append(("class:group", "  Or\n"))
                printed_or = True
            sel = idx[0] == i
            out.append(("class:sel" if sel else "", f"  {g['point']} " if sel else "    "))
            if key:
                out.append(("class:key", f"[{key}] "))
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
        if any(r == ret for r, _label, _k in actions):
            kb.add(key)(lambda event, _r=ret: _exit(event, _r))

    for i, _v in enumerate(views):
        if i < 9:
            kb.add(str(i + 1))(lambda event, _i=i: _exit(event, ("resume", _i)))

    frame_title = f"Virtual Surv-IT  ·  {_bits(project_dir, mod)}"
    try:
        screen(
            mod,
            title=frame_title,
            body_fn=_left,
            right_fn=_right,
            footer_fn=_footer,
            key_bindings=kb,
            output=output,
        )
    except Exception:
        return APP_FALLBACK
    return result["v"]


def settings_screen(project_dir: Path, mod, output=None) -> bool:
    """The [c] screen as a real app: live on/off column, toggle in place, Esc to leave.

    Replaces a numbered re-prompt loop where every toggle reprinted the whole table.
    Drives the SAME `_editor_rows` / `_editor_apply` the plain tier uses, so behaviour
    (precedence, machine defaults, the jira row, 'd' restore) cannot diverge - only the
    presentation differs. Returns True if anything changed."""
    try:
        p = mod._ptk_ui()
        if not p:
            return False
        from prompt_toolkit.key_binding import KeyBindings
    except Exception:
        return False

    g = glyphs(mod)
    rows = mod._editor_rows(project_dir) or []
    if not rows:
        return False
    idx = [0]
    notes: list[str] = []
    changed = [False]

    def _refresh():
        rows[:] = mod._editor_rows(project_dir) or rows

    def _body():
        out = [("class:group", f"  {g['settings']}Project settings\n\n")]
        width = max((len(label) for label, _v, _o in rows), default=0)
        for i, (label, value, on) in enumerate(rows):
            sel = idx[0] == i
            out.append(("class:sel" if sel else "", f"  {g['point']} " if sel else "    "))
            out.append(("class:sel" if sel else "", f"{label.ljust(width + 2)}"))
            mark = g["on"] if on else g["off"]
            out.append(("class:on" if on else "class:off", f"{mark} {value}\n"))
        return out

    def _right():
        out = [("class:title", "\n  What this screen does\n\n")]
        out.append(
            (
                "class:dim",
                "  Enter or Space toggles the\n  highlighted setting in place.\n\n"
                "  d  restore machine defaults\n  Esc  back to the menu\n\n",
            )
        )
        if notes:
            out.append(("class:group", "  Just changed\n"))
            for n in notes[-6:]:
                out.append(("class:on", f"  {n}\n"))
        return out

    def _footer():
        return [
            ("class:hint", f"  ↑↓ move · Enter toggle · d defaults · Esc back   {project_dir.name}")
        ]

    kb = KeyBindings()

    @kb.add("up")
    def _up(event):
        idx[0] = (idx[0] - 1) % len(rows)

    @kb.add("down")
    def _down(event):
        idx[0] = (idx[0] + 1) % len(rows)

    def _apply(action):
        # Detect change by COMPARING ROWS, not by whether a note came back:
        # _editor_apply returns '' on a perfectly successful toggle ("'' when there is
        # nothing to say"), so a note-based check silently reported "no change" for
        # every ordinary toggle.
        before = list(rows)
        note = mod._editor_apply(project_dir, action)
        _refresh()
        if list(rows) != before:
            changed[0] = True
            for (label, value, _on), (b_label, b_value, _b) in zip(rows, before):
                if value != b_value:
                    notes.append(f"{label}: {b_value} -> {value}")
        if note:
            notes.append(note.strip().lstrip("-> ").strip())

    @kb.add("enter")
    @kb.add(" ")
    def _toggle(event):
        _apply(idx[0] + 1)

    @kb.add("d")
    def _defaults(event):
        _apply("d")

    @kb.add("escape", eager=True)
    @kb.add("c-c")
    @kb.add("q")
    def _esc(event):
        event.app.exit()

    try:
        screen(
            mod,
            title=f"{g['settings']}Settings  ·  {project_dir.resolve().name}",
            body_fn=_body,
            right_fn=_right,
            footer_fn=_footer,
            key_bindings=kb,
            output=output,
        )
    except Exception:
        return changed[0]
    return changed[0]


def archive_screen(project_dir: Path, mod, engagement_state, menu: dict, output=None) -> bool:
    """The [a] screen as a real app: pick one, or all, with the consequence stated.

    Archiving an OPEN pack is allowed but shows as ARCHIVED-OPEN in checks - that warning
    is on screen rather than buried in a prompt, because it is the thing a person needs
    before pressing the key, not after."""
    try:
        p = mod._ptk_ui()
        if not p:
            return False
        from prompt_toolkit.key_binding import KeyBindings
    except Exception:
        return False

    g = glyphs(mod)
    shown = list(menu.get("shown") or [])
    if not shown:
        return False
    open_rows = list(menu.get("open") or shown)
    views = [mod.row_view(r) for r in shown]
    idx = [0]
    done = [False]

    def _body():
        out = [("class:group", f"  {g['archive']}Archive engagements\n\n")]
        for i, v in enumerate(views):
            sel = idx[0] == i
            out.append(("class:sel" if sel else "", f"  {g['point']} " if sel else "    "))
            out.append(
                (
                    "class:warn" if v["mark_style"] == "warn" else "class:dim",
                    f"{g.get(v['status'], v['mark'])} ",
                )
            )
            out.append(("class:sel" if sel else "", f"{v['title']}\n"))
            out.append(("class:dim", f"      {v['slug']}  {v['detail']}\n"))
        out.append(("", "\n"))
        sel_all = idx[0] == len(views)
        out.append(("class:sel" if sel_all else "", f"  {g['point']} " if sel_all else "    "))
        out.append(
            (
                "class:sel" if sel_all else "class:warn",
                f"archive ALL open engagements ({len(open_rows)})\n",
            )
        )
        return out

    def _right():
        return [
            ("class:title", "\n  Archiving\n\n"),
            (
                "class:dim",
                "  In place - nothing is deleted.\n  A marker excludes the pack from\n"
                "  every scanner.\n\n",
            ),
            (
                "class:warn",
                "  An OPEN pack archives with\n  --force and shows as\n"
                "  ARCHIVED-OPEN in checks.\n\n",
            ),
            ("class:dim", "  Enter archive · Esc back\n"),
        ]

    def _footer():
        return [("class:hint", "  ↑↓ move · Enter archive · Esc back")]

    kb = KeyBindings()
    total = len(views) + 1

    @kb.add("up")
    def _up(event):
        idx[0] = (idx[0] - 1) % total

    @kb.add("down")
    def _down(event):
        idx[0] = (idx[0] + 1) % total

    @kb.add("enter")
    def _go(event):
        targets = open_rows if idx[0] == len(views) else [shown[idx[0]]]
        try:
            mod._archive_perform(engagement_state, targets)
            done[0] = True
        except Exception:
            pass
        event.app.exit()

    @kb.add("escape", eager=True)
    @kb.add("c-c")
    @kb.add("q")
    def _esc(event):
        event.app.exit()

    try:
        screen(
            mod,
            title=f"{g['archive']}Archive  ·  {project_dir.resolve().name}",
            body_fn=_body,
            right_fn=_right,
            footer_fn=_footer,
            key_bindings=kb,
            output=output,
        )
    except Exception:
        return done[0]
    return done[0]
