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

# Engagement rows visible at once before the list scrolls. Same reasoning as the
# explorer's page size: the frame height is not known when the body is built.
_MENU_PAGE = 9


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
        # ASCII fallbacks are BRACKETS, not the words "on"/"off" (2026-08-20, found on a
        # real cp1252 Windows console). As words they collided with the value beside them:
        # boolean rows stuttered ("docx export  off off") and, far worse, a choice row read
        # "qa depth  off auto" - stating the setting was OFF when it was set to auto. Only
        # the corporate console path ever showed it; the emoji path never could.
        "on": "✓" if rich else "[x]",
        "off": "·" if rich else "[ ]",
        "in_progress": "⏳" if rich else "*",
        "blocked": "⛔" if rich else "!",
        "closing": "🔒" if rich else "~",
        "closed": "✓" if rich else "+",
        "open": "📂 " if rich else "",
        # Distinct from "archive" (📦, the WRITE action) - this is the read side, and
        # the archive glyph already fronts three different labels.
        "browse": "🗂️  " if rich and mod._can_encode("🗂️") else "",
    }


def _style(mod):
    from prompt_toolkit.styles import Style

    return Style.from_dict(PALETTE)


def project_line(project_dir: Path, mod, width=72):
    """The working directory, in full, left-truncated to keep the tail (2026-08-20 user
    request: "show what project directory the user is in"). The basename alone was in the
    frame title, which is not enough when several checkouts share a name - and picking the
    wrong directory is a documented way to get a silent plain launch on corp Windows. The
    TAIL is the informative end, so an over-long path loses its head, never its leaf."""
    try:
        text = str(project_dir.resolve())
    except Exception:
        text = str(project_dir)
    if len(text) > width:
        lead = "..." if mod._can_encode("...") else ".."
        text = lead + text[-(width - len(lead)) :]
    return text


def screen(mod, *, title, body_fn, footer_fn, key_bindings, output=None, right_fn=None,
           project_dir=None, refresh_interval=None):
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
        # 2:1 in favour of the left. An even split (the original) truncated the settings
        # rows mid-label once the explanation pane arrived and pushed the on/off column
        # clean off the screen - proven under a pty, 2026-08-20.
        body = VSplit(
            [
                Window(FormattedTextControl(body_fn), wrap_lines=False, width=D(min=34, weight=2)),
                Window(width=1, char="│" if mod._can_encode("│") else "|", style="class:dim"),
                Window(FormattedTextControl(right_fn), width=D(min=26, weight=1), wrap_lines=True),
            ]
        )
    header = [
        Window(
            FormattedTextControl(lambda: [("class:title", f"  {mod._morgan_line()}")]),
            height=1,
        )
    ]
    if project_dir is not None:
        folder = "📂 " if mod._can_encode("📂") else ""
        header.append(
            Window(
                FormattedTextControl(
                    lambda: [("class:dim", f"  {folder}{project_line(project_dir, mod)}")]
                ),
                height=1,
            )
        )
    root = HSplit(
        header
        + [
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
        # Only the live monitor passes this; every other screen redraws on a keypress, and
        # a timer on those would burn CPU redrawing something that cannot have changed.
        refresh_interval=refresh_interval,
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
    actions.append((("open",), f"{g['open']}open a different project folder", "o"))
    if shown:
        actions.append((("artifacts",), f"{g['archive']}view an engagement's artifacts", "v"))
    if shown:
        actions.append((("archive",), f"{g['archive']}archive engagement(s)", "a"))
    actions.append((("finished",), f"{g['browse']}browse done & archived", "b"))
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
            # Viewport over the engagement rows (2026-08-20): this tier now receives EVERY
            # open engagement rather than the top three, and a FormattedTextControl does
            # not follow a cursor - without a window, row 12 of 30 is simply invisible.
            # The action rows below are few and fixed, so only this region scrolls.
            first, last = 0, len(views)
            if len(views) > _MENU_PAGE:
                first = min(max(idx[0] - _MENU_PAGE // 2, 0), len(views) - _MENU_PAGE)
                last = first + _MENU_PAGE
                if first:
                    out.append(("class:dim", f"      ... {first} more above\n"))
            for i, v in list(enumerate(views))[first:last]:
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
            below = len(views) - last
            if below > 0:
                out.append(("class:dim", f"      ... {below} more below\n"))
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
        out = [("class:dim", "  ↑↓ move · Enter choose · ? help · Esc back to terminal")]
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

    @kb.add("?")
    def _help(event):
        _exit(event, ("help",))

    @kb.add("escape", eager=True)
    @kb.add("c-c")
    @kb.add("q")
    def _esc(event):
        _exit(event, None)

    for key, ret in (
        ("n", ("new",)),
        ("j", ("jira",)),
        ("c", ("settings",)),
        ("o", ("open",)),
        ("v", ("artifacts",)),
        ("a", ("archive",)),
        ("b", ("finished",)),
    ):
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
            project_dir=project_dir,
        )
    except Exception:
        return APP_FALLBACK
    return result["v"]


def settings_screen(project_dir: Path, mod, output=None):
    """The [c] screen as a real app: live on/off column, toggle in place, Esc to leave.

    Replaces a numbered re-prompt loop where every toggle reprinted the whole table.
    Drives the SAME `_editor_rows` / `_editor_apply` the plain tier uses, so behaviour
    (precedence, machine defaults, the jira row, 'd' restore) cannot diverge - only the
    presentation differs.

    Returns True/False when the screen RAN (changed anything or not), and **None when it
    could not run at all** - the caller falls back to the numbered editor only on None.
    Conflating the two was a live bug (2026-08-20): Esc with nothing changed returned
    False, so cancelling the app screen dumped the user into the old numbered editor."""
    try:
        p = mod._ptk_ui()
        if not p:
            return None
        from prompt_toolkit.key_binding import KeyBindings
    except Exception:
        return None

    g = glyphs(mod)
    rows = mod._editor_rows(project_dir) or []
    if not rows:
        return None  # cannot render a settings screen without settings
    idx = [0]
    notes: list[str] = []
    changed = [False]

    def _refresh():
        rows[:] = mod._editor_rows(project_dir) or rows

    def _body():
        out = [("class:group", f"  {g['settings']}Project settings\n\n")]
        # Padding is CAPPED, not simply the longest label: one long label used to set the
        # column for all ten rows and push the value hard against the divider, so the
        # longest VALUE ("not applied") clipped. Rows longer than the cap keep a single
        # separating space and sit slightly right of the column - untidier than a clip is
        # wrong.
        width = min(max((len(label) for label, _v, _o in rows), default=0), 24)
        for i, (label, value, on) in enumerate(rows):
            sel = idx[0] == i
            out.append(("class:sel" if sel else "", f"  {g['point']} " if sel else "    "))
            out.append(("class:sel" if sel else "", f"{label.ljust(width + 1)} "))
            mark = g["on"] if on else g["off"]
            # Only the HEAD of the value here ("on" / "off" / "applied"). The qualifier
            # that follows a double space ("  (machine default)") is longer than the
            # column has room for and was being clipped mid-word against the divider; the
            # explanation pane shows the value in full instead.
            head = value.partition("  ")[0]
            out.append(("class:on" if on else "class:off", f"{mark} {head}\n"))
        return out

    def _wrap(text, width=30, indent="  "):
        """Hand-wrapped rather than left to the Window: the right pane is a weighted
        split, so wrap_lines would rewrap on every resize and the explanation would jump
        around under the cursor while someone is reading it."""
        out, line = [], ""
        for word in text.split():
            if line and len(line) + 1 + len(word) > width:
                out.append(indent + line)
                line = word
            else:
                line = f"{line} {word}".strip()
        if line:
            out.append(indent + line)
        return "\n".join(out)

    def _right():
        # The highlighted setting explains ITSELF here (2026-08-20 user request). The old
        # pane described the screen's keys, which everyone had already worked out by the
        # time they were reading it, while the actual question - "what does this one DO?" -
        # went unanswered and had to be asked out loud.
        label, value, on = rows[idx[0]]
        out = [("class:title", f"\n  {label}\n\n")]
        help_text = mod.setting_help(label)
        if help_text:
            out.append(("", _wrap(help_text[0]) + "\n\n"))
            out.append(("class:dim", _wrap(help_text[1]) + "\n\n"))
        else:
            out.append(("class:dim", "  No description available for\n  this setting yet.\n\n"))
        out.append(("class:on" if on else "class:off", _wrap(f"currently: {value}") + "\n\n"))
        # No key hints here: the footer already teaches Enter/d/Esc, and repeating them
        # cost three lines that the explanation itself needs.
        if notes:
            out.append(("class:group", "  Just changed\n"))
            for n in notes[-4:]:
                out.append(("class:on", _wrap(n) + "\n"))
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
            project_dir=project_dir,
        )
    except Exception:
        return changed[0]
    return changed[0]


def archive_screen(project_dir: Path, mod, engagement_state, menu: dict, output=None):
    """The [a] screen as a real app: pick one, or all, with the consequence stated.

    Archiving an OPEN pack is allowed but shows as ARCHIVED-OPEN in checks - that warning
    is on screen rather than buried in a prompt, because it is the thing a person needs
    before pressing the key, not after."""
    try:
        p = mod._ptk_ui()
        if not p:
            return None
        from prompt_toolkit.key_binding import KeyBindings
    except Exception:
        return None

    g = glyphs(mod)
    shown = list(menu.get("shown") or [])
    if not shown:
        return None  # nothing to archive - let the caller decide what to say
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
            project_dir=project_dir,
        )
    except Exception:
        return done[0]
    return done[0]


def finished_screen(project_dir: Path, mod, engagement_state, output=None):
    """The [b] screen: browse DONE and ARCHIVED engagements, Enter opens the selected
    one in a Claude session as a read-only `--review`. The read side of the archive
    story - archive_screen writes the marker, this is how you find the pack again.

    Returns the chosen engagement's resume token, '' when the user backs out (Esc),
    None when the screen cannot run at all (no ptk, no finished packs) - the caller
    falls back to the numbered menu ONLY on None, same contract as settings_screen."""
    try:
        p = mod._ptk_ui()
        if not p:
            return None
        from prompt_toolkit.key_binding import KeyBindings
    except Exception:
        return None

    try:
        rows = engagement_state.finished_engagements(project_dir / "artifacts")
    except Exception:
        return None
    if not rows:
        return None  # the fallback menu owns the "nothing yet" message

    g = glyphs(mod)
    views = [mod.row_view(r) for r in rows]
    idx = [0]
    chosen: list = [""]
    note = [""]

    def _signed(i):
        """Who signed this pack off, or '' - read fresh so [s] updates the screen."""
        try:
            return mod._sign_off_state(project_dir, mod._row_resume_token(rows[i]) or "")
        except Exception:
            return ""

    def _body():
        out = [("class:group", f"  {g['browse']}Done & archived engagements\n\n")]
        # Same viewport arithmetic as the main menu: the frame height is unknown when
        # the body is built, so page on a constant.
        top = max(0, min(idx[0] - _MENU_PAGE + 1, len(views) - _MENU_PAGE))
        for i in range(top, min(top + _MENU_PAGE, len(views))):
            v = views[i]
            row = rows[i]
            sel = idx[0] == i
            out.append(("class:sel" if sel else "", f"  {g['point']} " if sel else "    "))
            out.append(("class:dim", f"{g.get(v['status'], v['mark'])} "))
            out.append(("class:sel" if sel else "", f"{v['title']}\n"))
            tail = "archived" if row.get("archived") else (row.get("status") or "")
            when = str(row.get("closed") or row.get("opened") or "")[:10]
            out.append(("class:dim", f"      {v['slug']}  {tail}" + (f"  {when}" if when else "")))
            out.append(("class:on" if _signed(i) else "class:warn",
                        "  signed off\n" if _signed(i) else "  unsigned\n"))
        if len(views) > _MENU_PAGE:
            out.append(("class:hint", f"\n  {idx[0] + 1}/{len(views)}\n"))
        return out

    def _right():
        row = rows[idx[0]]
        v = views[idx[0]]
        lines = [("class:title", f"\n  {v['title']}\n\n")]
        for label, value in v["lines"]:
            lines.append(("class:dim", f"  {label.ljust(8)}"))
            lines.append(("", f"{value}\n"))
        if row.get("archived"):
            lines.append(("class:warn", "\n  archived (marker on disk)\n"))
        who = _signed(idx[0])
        if who:
            lines.append(("class:on", f"\n  Signed off by {who}\n"))
        else:
            lines.append(("class:warn", "\n  Not signed off yet\n"))
            lines.append(("class:dim", "  s  record sign-off (appends;\n     nothing is rewritten)\n"))
        lines.append(
            ("class:dim",
             "\n  Enter opens it in Claude,\n  read-only - nothing is\n  reopened.\n"
             "\n  r  redo as NEW work that\n     supersedes this one\n")
        )
        if note[0]:
            lines.append(("class:on", f"\n  {note[0]}\n"))
        return lines

    def _footer():
        return [("class:hint",
                 "  ↑↓ move · Enter open · s sign off · r redo (supersede) · Esc back")]

    kb = KeyBindings()

    @kb.add("up")
    def _up(event):
        idx[0] = (idx[0] - 1) % len(views)

    @kb.add("down")
    def _down(event):
        idx[0] = (idx[0] + 1) % len(views)

    @kb.add("s")
    def _sign(event):
        # Recorded HERE, by the human at the keyboard - never by a session. An agent
        # signing off its own work is the thing the Definition-of-Done gate exists to
        # prevent, so the signature is taken where a person demonstrably is.
        slug = mod._row_resume_token(rows[idx[0]]) or ""
        note[0] = mod._record_sign_off(project_dir, slug)

    @kb.add("r")
    def _redo(event):
        slug = mod._row_resume_token(rows[idx[0]]) or ""
        if slug:
            chosen[0] = ("supersede", slug)
            event.app.exit()

    @kb.add("enter")
    def _go(event):
        chosen[0] = mod._row_resume_token(rows[idx[0]]) or ""
        event.app.exit()

    @kb.add("escape", eager=True)
    @kb.add("c-c")
    @kb.add("q")
    def _esc(event):
        chosen[0] = ""
        event.app.exit()

    try:
        screen(
            mod,
            title=f"{g['browse']}Done & archived  ·  {project_dir.resolve().name}",
            body_fn=_body,
            right_fn=_right,
            footer_fn=_footer,
            key_bindings=kb,
            output=output,
            project_dir=project_dir,
        )
    except Exception:
        return None
    return chosen[0]


JIRA_CANCELLED = "__jira_cancelled__"

# Visible width of the ticket field. Conservative rather than measured: the left pane is a
# weighted split, so the exact column count is not known at render time, and under-showing
# is harmless (the detected key is on its own line) while over-showing collides with the
# divider.
_INPUT_WINDOW = 38
_COMPOSER_LINES = 9  # visible lines in the request composer; the buffer itself is unbounded.
# Sized against a real pty (2026-08-25): a two-sentence brief - the case that prompted the
# composer - now fits without scrolling its own opening away, and the pane still has room
# beneath for the unattended row. Longer briefs scroll, with a leading marker saying so.


def _wrapped(text: str, width: int) -> list:
    """Word-wrap for DISPLAY only, honouring the newlines the human typed.

    Never used to decide what is sent - the request is flattened to one line on the way
    out (_sanitise_request), so wrapping here can be purely cosmetic and lossless."""
    lines = []
    for paragraph in (text or "").split("\n"):
        if not paragraph:
            lines.append("")
            continue
        current = ""
        for word in paragraph.split(" "):
            candidate = f"{current} {word}".strip() if current else word
            if len(candidate) <= width or not current:
                current = candidate
            else:
                lines.append(current)
                current = word
        lines.append(current)
    return lines or [""]


def jira_screen(project_dir: Path, mod, output=None):
    """The [j] ticket prompt as a real screen (2026-08-20 user report: "when selecting J
    it drops out of the interface to prompt for jira ticket url").

    Picking [j] used to tear down the full-screen app and fall back to a bare `input()`
    on stderr, so the one flow a colleague is most likely to be watched through was also
    the one that broke the illusion of an app. The typing surface is built from key
    bindings rather than a focusable widget so the shared `screen()` shell - and its
    stderr-only output contract - is reused unchanged.

    Returns the ref to pass to `--jira` (URL when one was pasted, bare key otherwise),
    JIRA_CANCELLED on Esc, or None when the app cannot run here (the caller then uses the
    plain `_jira_decision` prompt, which stays fully maintained)."""
    try:
        p = mod._ptk_ui()
        if not p:
            return None
        from prompt_toolkit.key_binding import KeyBindings
        from prompt_toolkit.keys import Keys
    except Exception:
        return None

    g = glyphs(mod)
    buf = [""]
    result = {"v": JIRA_CANCELLED}
    configured = mod._jira_enabled(project_dir)
    # Offered only where the project opted in; off by default (2026-08-20 owner decision).
    auto_offered = mod._auto_offered(project_dir)
    auto = [mod._auto_armed(project_dir)]  # pre-armed only if the project asked

    def _detected():
        m = mod._JIRA_KEY_RE.search(buf[0])
        return m.group(1).upper() if m else ""

    def _body():
        out = [("class:group", f"  {g['jira']}Start an engagement from a Jira ticket\n\n")]
        out.append(("class:dim", "  Paste the issue URL, or type the key (e.g. SURV-142).\n\n"))
        cursor = "_" if mod._can_encode("_") else " "
        out.append(("class:title", "  > "))
        # Window on the TAIL, not the head: a pasted Jira URL is longer than the pane and
        # used to run straight into the divider, hiding the very part that carries the key
        # (proven under a real pty, 2026-08-20). The full value is still what gets returned.
        shown = buf[0] or ""
        if len(shown) > _INPUT_WINDOW:
            lead = "..." if mod._can_encode("...") else ".."
            shown = lead + shown[-(_INPUT_WINDOW - len(lead)) :]
        out.append(("", shown))
        out.append(("class:hint", cursor))
        out.append(("", "\n\n"))
        key = _detected()
        if key:
            out.append(("class:on", f"  {g['on']} will open from {key}\n"))
        elif buf[0]:
            out.append(("class:warn", "  no issue key found yet - keep typing\n"))
        else:
            out.append(("class:dim", "  waiting for a ticket reference\n"))
        if auto_offered:
            out.append(("", "\n"))
            mark = g["on"] if auto[0] else g["off"]
            out.append(("class:on" if auto[0] else "class:off", f"  {mark} "))
            out.append(("class:warn" if auto[0] else "class:dim", "Ctrl-A  run unattended"))
            out.append(("class:dim", "  (no further questions)\n"))
        return out

    def _right():
        out = [("class:title", "\n  What happens next\n\n")]
        out.append(
            (
                "class:dim",
                "  The launcher never talks to\n  Jira. The session fetches the\n"
                "  ticket itself and delivers the\n  results back to it at close.\n\n"
                "  Ticket content is treated as\n  DATA, never as instructions.\n\n",
            )
        )
        if not configured:
            out.append(("class:warn", "  No Jira integration configured\n"))
            out.append(
                (
                    "class:dim",
                    "  here, so the session can only\n  fetch the ticket if access\n"
                    "  already exists. See\n  docs/INTEGRATIONS.md\n\n",
                )
            )
        out.append(("class:dim", "  Enter   start\n  Esc     back\n"))
        if auto_offered:
            out.append(("class:dim", "  Ctrl-A  unattended run\n"))
        return out

    def _footer():
        tail = " · Ctrl-A unattended run" if auto_offered else ""
        return [("class:hint", f"  Enter start · Esc back · Ctrl-U clear{tail}")]

    kb = KeyBindings()

    @kb.add("c-a")
    def _auto(event):
        # Ctrl-A, not a bare "a": every printable key is text for the ticket field, and a
        # letter that sometimes types and sometimes toggles is how you paste a key and
        # silently authorise an unattended run.
        if auto_offered:
            auto[0] = not auto[0]

    @kb.add(Keys.Any)
    def _type(event):
        data = event.data or ""
        if data.isprintable():
            buf[0] += data

    @kb.add(Keys.BracketedPaste)
    def _paste(event):
        # A pasted URL is the common case; strip newlines rather than letting them land
        # in the ref, and keep the rest verbatim so the instance host survives.
        buf[0] += "".join(ch for ch in (event.data or "") if ch.isprintable())

    @kb.add("backspace")
    def _back(event):
        buf[0] = buf[0][:-1]

    @kb.add("c-u")
    def _clear(event):
        buf[0] = ""

    @kb.add("enter")
    def _accept(event):
        raw = buf[0].strip()
        key = _detected()
        if not key:
            return  # nothing valid yet - stay on the screen rather than bouncing out
        result["v"] = raw if "://" in raw else key
        result["auto"] = auto[0]
        event.app.exit()

    @kb.add("escape", eager=True)
    @kb.add("c-c")
    def _esc(event):
        result["v"] = JIRA_CANCELLED
        event.app.exit()

    try:
        screen(
            mod,
            title=f"{g['jira']}From a Jira ticket  ·  {project_dir.resolve().name}",
            body_fn=_body,
            right_fn=_right,
            footer_fn=_footer,
            key_bindings=kb,
            output=output,
            project_dir=project_dir,
        )
    except Exception:
        return None
    # A ref alone stays a plain string (every existing caller keeps working); an unattended
    # pick returns (ref, True), so a caller cannot start one without noticing that it did.
    if result["v"] != JIRA_CANCELLED and result.get("auto"):
        return (result["v"], True)
    return result["v"]


BROWSE_CANCELLED = "__browse_cancelled__"

# Rows visible at once in the explorer. Fixed rather than measured: the frame height is
# not known when the body is built, and 15 fits the 24-line terminal that is the floor
# everywhere this runs.
_BROWSE_PAGE = 15


def _dir_entries(here: Path, mod, limit=200):
    """Sub-directories of `here`, each tagged with whether it is a team project. Hidden
    and dependency directories are skipped: they are never the answer and they bury the
    ones that are. Unreadable directory = empty list, never a traceback."""
    skip = {".git", "node_modules", "__pycache__", ".venv", "venv", ".mypy_cache", ".idea"}
    out = []
    try:
        for child in sorted(here.iterdir(), key=lambda p: p.name.lower()):
            if not child.is_dir() or child.name in skip:
                continue
            if child.name.startswith(".") and child.name != ".claude":
                continue
            try:
                is_project = bool(mod._plugin_enabled(child))
            except Exception:
                is_project = False
            out.append((child, is_project))
            if len(out) >= limit:
                break
    except (OSError, PermissionError):
        return []
    return out


def browse_screen(start_dir: Path, mod, output=None):
    """Project explorer (2026-08-20 user request: "the ability to change the folder and
    restart virt-surv go from that folder").

    Rows are unambiguous by construction: the first row opens the folder you are IN,
    ".." goes up, and any other row descends. A file picker that overloads Enter to mean
    both "descend" and "choose" is the classic way to open the wrong project.

    Team projects are ticked, so you can see which directories the plugin is actually set
    up in rather than guessing from the name.

    Returns the chosen Path, BROWSE_CANCELLED on Esc, or None when the app cannot run."""
    try:
        p = mod._ptk_ui()
        if not p:
            return None
        from prompt_toolkit.key_binding import KeyBindings
    except Exception:
        return None

    g = glyphs(mod)
    try:
        here = [start_dir.resolve()]
    except Exception:
        here = [start_dir]
    entries = [_dir_entries(here[0], mod)]
    try:
        recents = mod._recent_projects()
    except Exception:
        recents = []
    idx = [0]
    result = {"v": BROWSE_CANCELLED}

    def _rows():
        """(label, kind, payload) - kind is 'use' | 'up' | 'recent' | 'dir'."""
        rows = [(f"use this folder  ({here[0].name or here[0]})", "use", here[0])]
        if here[0].parent != here[0]:
            rows.append((".. up to " + (here[0].parent.name or str(here[0].parent)), "up", None))
        # Recent projects jump straight there (2026-08-20): the explorer opens on the
        # current directory, so without this, reaching a project you use daily means
        # walking the tree from wherever you happened to be standing.
        for recent in recents:
            if recent != here[0]:
                rows.append((f"{recent.name}", "recent", recent))
        for child, is_project in entries[0]:
            rows.append((child.name, "dir", (child, is_project)))
        return rows

    def _reload(new_dir):
        here[0] = new_dir
        entries[0] = _dir_entries(new_dir, mod)
        idx[0] = 0

    def _body():
        rows = _rows()
        out = [("class:group", f"  {g['engagements']}Choose a project folder\n\n")]
        # Viewport, not the whole list: a FormattedTextControl does not follow a cursor,
        # so in any real projects folder the selection walked off the bottom of the frame
        # and became invisible. Window slides to keep the highlighted row inside it.
        top = 0
        if len(rows) > _BROWSE_PAGE:
            top = min(max(idx[0] - _BROWSE_PAGE // 2, 0), len(rows) - _BROWSE_PAGE)
            if top:
                out.append(("class:dim", f"    ... {top} above\n"))
        window = list(enumerate(rows))[top : top + _BROWSE_PAGE]
        for i, (label, kind, payload) in window:
            sel = idx[0] == i
            out.append(("class:sel" if sel else "", f"  {g['point']} " if sel else "    "))
            if kind == "use":
                out.append(("class:on" if not sel else "class:sel", f"{label}\n"))
                continue
            if kind == "up":
                out.append(("class:dim" if not sel else "class:sel", f"{label}\n"))
                continue
            if kind == "recent":
                out.append(("class:sel" if sel else "class:title", label))
                out.append(("class:dim", "  recent\n"))
                continue
            _child, is_project = payload
            out.append(("class:sel" if sel else "class:title", label))
            if is_project:
                out.append(("class:on", f"  {g['on']} team project"))
            out.append(("", "\n"))
        below = len(rows) - (top + _BROWSE_PAGE)
        if below > 0:
            out.append(("class:dim", f"    ... {below} below\n"))
        if len(rows) == 1:
            out.append(("class:dim", "\n    (no sub-folders here)\n"))
        return out

    def _right():
        out = [("class:title", "\n  Project explorer\n\n")]
        out.append(("", "  " + str(here[0])[-30:] + "\n\n"))
        out.append(
            (
                "class:dim",
                "  Enter on a folder opens it.\n  Enter on the first row picks\n"
                "  the folder you are in.\n\n  Switching restarts the menu\n"
                "  for that project, and the\n  session starts there too.\n\n",
            )
        )
        ticked = sum(1 for _c, is_p in entries[0] if is_p)
        if ticked:
            out.append(("class:on", f"  {ticked} team project(s) here\n"))
        return out

    def _footer():
        return [("class:hint", "  ↑↓ move · Enter open · Backspace up · Esc cancel")]

    kb = KeyBindings()

    @kb.add("up")
    def _up(event):
        idx[0] = (idx[0] - 1) % max(len(_rows()), 1)

    @kb.add("down")
    def _down(event):
        idx[0] = (idx[0] + 1) % max(len(_rows()), 1)

    @kb.add("backspace")
    @kb.add("left")
    def _parent(event):
        if here[0].parent != here[0]:
            _reload(here[0].parent)

    @kb.add("enter")
    def _choose(event):
        rows = _rows()
        if not rows:
            return
        _label, kind, payload = rows[idx[0]]
        if kind == "use":
            result["v"] = here[0]
            event.app.exit()
        elif kind == "up":
            _parent(event)
        elif kind == "recent":
            # A recent entry is a destination, not a place to browse into: you picked it
            # because you already know it is the project you want.
            result["v"] = payload
            event.app.exit()
        else:
            _reload(payload[0])

    @kb.add("escape", eager=True)
    @kb.add("c-c")
    def _esc(event):
        result["v"] = BROWSE_CANCELLED
        event.app.exit()

    try:
        screen(
            mod,
            title=f"{g['engagements']}Open a project",
            body_fn=_body,
            right_fn=_right,
            footer_fn=_footer,
            key_bindings=kb,
            output=output,
            project_dir=here[0],
        )
    except Exception:
        return None
    return result["v"]


SETUP_DEFAULTS = "__setup_defaults__"
SETUP_GUIDED = "__setup_guided__"
SETUP_SKIP = "__setup_skip__"


def setup_screen(project_dir: Path, mod, output=None):
    """First-time project setup, asked INSIDE the interface (2026-08-20 user report: "it
    currently creates and prompts for whether the user wants defaults outside of the new
    TUI - integrate that flow").

    It used to be a bare `[Y/n]` on stderr followed by a separate interactive program, so
    the very first thing a new project showed you was the thing the TUI exists to replace.

    Three outcomes, and the honest bit is the middle one: applying defaults runs without
    prompting and stays in here, while the guided pass IS a separate interactive program
    and cannot be hosted in this app - so the screen says it will leave rather than
    pretending otherwise.

    Returns SETUP_DEFAULTS / SETUP_GUIDED / SETUP_SKIP, or None when the app cannot run."""
    try:
        p = mod._ptk_ui()
        if not p:
            return None
        from prompt_toolkit.key_binding import KeyBindings
    except Exception:
        return None

    g = glyphs(mod)
    options = [
        (SETUP_DEFAULTS, f"{g['new']}set up with recommended defaults", "no questions asked"),
        (SETUP_GUIDED, f"{g['settings']}guided setup", "asks questions; leaves this screen"),
        (SETUP_SKIP, f"{g['launch']}skip for now", "launch without setting up"),
    ]
    idx = [0]
    result = {"v": SETUP_SKIP}

    def _body():
        out = [("class:group", f"  {g['settings']}First-time setup\n\n")]
        out.append(("class:dim", "  No team configuration in this folder yet.\n\n"))
        for i, (_ret, label, note) in enumerate(options):
            sel = idx[0] == i
            out.append(("class:sel" if sel else "", f"  {g['point']} " if sel else "    "))
            out.append(("class:sel" if sel else "class:title", label))
            # Note on its OWN line: inline, the three notes ran past the pane edge and
            # were clipped mid-word ("asks questions; leaves"), which is exactly the
            # wrong half to lose.
            out.append(("", "\n"))
            out.append(("class:dim", f"        {note}\n"))
            if i < len(options) - 1:
                out.append(("", "\n"))
        return out

    def _right():
        out = [("class:title", "\n  What setup does\n\n")]
        out.append(
            (
                "class:dim",
                "  Writes this project's own\n  team-preferences.json, so the\n"
                "  team knows how you want it\n  to work here.\n\n"
                "  Nothing outside this folder\n  is touched, and every setting\n"
                "  can be changed later from\n  the menu.\n\n",
            )
        )
        return out

    def _footer():
        return [("class:hint", "  ↑↓ move · Enter choose · Esc skip")]

    kb = KeyBindings()

    @kb.add("up")
    def _up(event):
        idx[0] = (idx[0] - 1) % len(options)

    @kb.add("down")
    def _down(event):
        idx[0] = (idx[0] + 1) % len(options)

    @kb.add("enter")
    def _pick(event):
        result["v"] = options[idx[0]][0]
        event.app.exit()

    @kb.add("escape", eager=True)
    @kb.add("c-c")
    def _esc(event):
        result["v"] = SETUP_SKIP
        event.app.exit()

    try:
        screen(
            mod,
            title=f"{g['settings']}Set up this project",
            body_fn=_body,
            right_fn=_right,
            footer_fn=_footer,
            key_bindings=kb,
            output=output,
            project_dir=project_dir,
        )
    except Exception:
        return None
    return result["v"]


def artifacts_screen(project_dir: Path, mod, slug: str, output=None):
    """What an engagement produced, openable (2026-08-20). The launcher could resume and
    archive an engagement but offered no route to its delivery report, START-HERE or
    evidence-room pack - the one screen seen every day had no way to reach the things the
    work exists to produce. Enter hands the file to the OS opener rather than trying to
    render a report in a 30-column pane. Returns True when the screen ran."""
    try:
        p = mod._ptk_ui()
        if not p:
            return None
        from prompt_toolkit.key_binding import KeyBindings
    except Exception:
        return None

    g = glyphs(mod)
    items = mod._engagement_artifacts(project_dir, slug)
    idx = [0]
    note = [""]

    def _body():
        out = [("class:group", f"  {g['archive']}Artifacts for {slug}\n\n")]
        if not items:
            out.append(("class:dim", "    nothing rendered yet in this workspace\n"))
            return out
        for i, (label, _path) in enumerate(items):
            sel = idx[0] == i
            out.append(("class:sel" if sel else "", f"  {g['point']} " if sel else "    "))
            out.append(("class:sel" if sel else "class:title", f"{label}\n"))
        if note[0]:
            out.append(("class:warn", f"\n    {note[0]}\n"))
        return out

    def _right():
        out = [("class:title", "\n  Open an artifact\n\n")]
        out.append(
            (
                "class:dim",
                "  Enter opens the highlighted\n  file with whatever your\n"
                "  system uses for it.\n\n  Rendered .html is listed in\n"
                "  preference to its .md twin.\n\n  Esc  back to the menu\n",
            )
        )
        return out

    def _footer():
        return [("class:hint", f"  ↑↓ move · Enter open · Esc back   {slug}")]

    kb = KeyBindings()

    @kb.add("up")
    def _up(event):
        if items:
            idx[0] = (idx[0] - 1) % len(items)

    @kb.add("down")
    def _down(event):
        if items:
            idx[0] = (idx[0] + 1) % len(items)

    @kb.add("enter")
    def _open(event):
        if items:
            note[0] = mod._open_path(items[idx[0]][1]) or "opened"

    @kb.add("escape", eager=True)
    @kb.add("c-c")
    @kb.add("q")
    def _esc(event):
        event.app.exit()

    try:
        screen(
            mod,
            title=f"{g['archive']}Artifacts",
            body_fn=_body,
            right_fn=_right,
            footer_fn=_footer,
            key_bindings=kb,
            output=output,
            project_dir=project_dir,
        )
    except Exception:
        return None
    return True


def help_screen(project_dir: Path, mod, output=None):
    """The legend (2026-08-20). The settings screen explains itself, but the menu's own
    status glyphs did not - a row marked ⛔ told you something was wrong without saying
    what. Returns True when it ran."""
    try:
        p = mod._ptk_ui()
        if not p:
            return None
        from prompt_toolkit.key_binding import KeyBindings
    except Exception:
        return None

    g = glyphs(mod)
    # Every string here is sized to its pane. The first draft wrapped in BOTH columns
    # ("Enter choose the highlighted r/ow"), which is a poor look for the screen whose
    # entire job is explaining things.
    rows = [
        (g["in_progress"], "in progress", "being worked on"),
        (g["blocked"], "blocked", "parked, outside our control"),
        (g["closing"], "closing", "DoD gate and sign-off"),
        (g["on"], "most recent", "resume defaults here"),
    ]
    keys = [
        ("Enter", "choose highlighted"),
        ("n", "new engagement"),
        ("j", "from a Jira ticket"),
        ("c", "project settings"),
        ("o", "another project"),
        ("a", "archive"),
        ("b", "browse done & archived"),
        ("v", "view artifacts"),
        ("m", "show all open"),
        ("?", "this screen"),
        ("Esc", "quit, no launch"),
    ]

    def _body():
        out = [("class:group", "  What the marks mean\n\n")]
        for mark, name, meaning in rows:
            out.append(("class:title", f"    {mark}  "))
            out.append(("", f"{name}"))
            out.append(("class:dim", f" - {meaning}\n"))
        return out

    def _right():
        out = [("class:title", "\n  Keys\n\n")]
        for key, meaning in keys:
            out.append(("class:key", f"  {key.ljust(6)}"))
            out.append(("class:dim", f"{meaning}\n"))
        return out

    def _footer():
        return [("class:hint", "  any key returns to the menu")]

    kb = KeyBindings()

    @kb.add("<any>")
    @kb.add("escape", eager=True)
    @kb.add("c-c")
    def _any(event):
        event.app.exit()

    try:
        screen(
            mod,
            title="Help",
            body_fn=_body,
            right_fn=_right,
            footer_fn=_footer,
            key_bindings=kb,
            output=output,
            project_dir=project_dir,
        )
    except Exception:
        return None
    return True


def slug_picker_screen(project_dir: Path, mod, shown: list, output=None):
    """Pick one open engagement. Only used when several are open and the action needs to
    know which - artifacts today. Returns the slug, or "" on cancel/unavailable."""
    try:
        p = mod._ptk_ui()
        if not p:
            return ""
        from prompt_toolkit.key_binding import KeyBindings
    except Exception:
        return ""

    g = glyphs(mod)
    rows = [(mod._row_resume_token(r) or "?", mod.row_view(r, default_slug="", of_many=True)) for r in shown]
    idx = [0]
    result = {"v": ""}

    def _body():
        out = [("class:group", f"  {g['engagements']}Which engagement?\n\n")]
        first = 0
        if len(rows) > _MENU_PAGE:
            first = min(max(idx[0] - _MENU_PAGE // 2, 0), len(rows) - _MENU_PAGE)
        for i, (slug, view) in list(enumerate(rows))[first : first + _MENU_PAGE]:
            sel = idx[0] == i
            out.append(("class:sel" if sel else "", f"  {g['point']} " if sel else "    "))
            out.append(("class:sel" if sel else "class:title", view["title"]))
            out.append(("class:dim", f"   {slug}\n"))
        return out

    def _footer():
        return [("class:hint", "  ↑↓ move · Enter choose · Esc back")]

    kb = KeyBindings()

    @kb.add("up")
    def _up(event):
        idx[0] = (idx[0] - 1) % len(rows)

    @kb.add("down")
    def _down(event):
        idx[0] = (idx[0] + 1) % len(rows)

    @kb.add("enter")
    def _pick(event):
        result["v"] = rows[idx[0]][0]
        event.app.exit()

    @kb.add("escape", eager=True)
    @kb.add("c-c")
    def _esc(event):
        event.app.exit()

    try:
        screen(
            mod,
            title=f"{g['engagements']}Choose an engagement",
            body_fn=_body,
            footer_fn=_footer,
            key_bindings=kb,
            output=output,
            project_dir=project_dir,
        )
    except Exception:
        return ""
    return result["v"]


AUTO_CANCELLED = "__auto_cancelled__"


def auto_preflight_screen(project_dir: Path, mod, ref: str, output=None):
    """The single authorisation gate for an unattended run (2026-08-20).

    Auto mode's whole premise is that nothing interrupts the session afterwards, so every
    question it would have asked has to be answered HERE, while a human is present. That
    makes this screen the entire safety story, and it is written to be read: what auto mode
    will do, what it will not do, and what each toggle authorises.

    Execution consent is granted here when asked for - see
    virt_team_launcher.grant_execution_consent for why a launcher keypress is a legitimate
    human grant while a session's own request never is.

    Returns a dict of the authorisations, or AUTO_CANCELLED, or None if it cannot run."""
    try:
        p = mod._ptk_ui()
        if not p:
            return None
        from prompt_toolkit.key_binding import KeyBindings
    except Exception:
        return None

    g = glyphs(mod)
    # Cycling choices as well as toggles (2026-08-24). Unattended work is the one case where
    # nobody is watching the spend, and the attended degrade ladder is a QUESTION - which an
    # unattended run has nobody to ask, and which `--permission-mode dontAsk` denies outright.
    # Both are therefore answered here, once, while a human is present.
    CAPS = (0, 10, 25, 35, 50, 100)
    ON_BUDGET = ("park", "light", "continue")
    # Defaults set by the owner, 2026-08-25: a $35 ceiling, and "carry on, report it" when
    # it is reached. Note which way that leans - continuing past the ceiling is the LESS
    # cautious rung, chosen deliberately because an unattended run that parks at the cap
    # has produced nothing anyone can use, and the ceiling is advisory pacing rather than a
    # hard stop. It is still reported, and the run still closes PARTIAL for sign-off.
    state = {"data": False, "exec": False, "cap": 3, "on_budget": 2, "confirmed": False}
    idx = [0]
    rows = [
        ("data", "toggle", "Data is synthetic or masked",
         "no PII/MNPI - your attestation"),
        ("exec", "toggle", "Allow the session to RUN code unattended",
         "grants the gate here, expiring"),
        ("cap", "cycle", "Spend ceiling for this engagement",
         "advisory pacing, not a hard stop"),
        ("on_budget", "cycle", "At the ceiling",
         "the degrade ladder, answered up front"),
    ]

    def _value(key):
        if key == "cap":
            return "no ceiling" if CAPS[state["cap"]] == 0 else f"${CAPS[state['cap']]}"
        return {
            "park": "park at next gate",
            "light": "drop to light profile",
            "continue": "carry on, report it",
        }[ON_BUDGET[state["on_budget"]]]

    def _body():
        out = [("class:group", f"  {g['jira']}Unattended run: {ref}\n\n")]
        out.append(("class:warn", "  This session will not stop to ask you anything.\n\n"))
        for i, (key, kind, label, note) in enumerate(rows):
            sel = idx[0] == i
            out.append(("class:sel" if sel else "", f"  {g['point']} " if sel else "    "))
            if kind == "toggle":
                on = state[key]
                out.append(("class:on" if on else "class:off", f"{g['on'] if on else g['off']} "))
                out.append(("class:sel" if sel else "", label))
            else:
                out.append(("class:sel" if sel else "", label))
                out.append(("class:title", f"  {_value(key)}"))
            out.append(("", "\n"))
            out.append(("class:dim", f"        {note}\n"))
        out.append(("", "\n"))
        out.append(("class:dim", "    Space cycles · Enter starts · Esc cancels\n"))
        return out

    def _right():
        out = [("class:title", "\n  How auto mode works\n\n")]
        out.append(
            (
                "class:dim",
                "  It works the ticket end to\n  end and never asks you a\n  question.\n\n"
                "  Questions it WOULD have\n  asked become recorded\n  assumptions, listed in the\n"
                "  report and posted to the\n  ticket for you to check.\n\n"
                "  If scope is genuinely\n  unclear, or something it\n  needs is missing, it PARKS\n"
                "  the work and says why - it\n  does not guess.\n\n",
            )
        )
        out.append(("class:warn", "  It always closes PARTIAL.\n"))
        out.append(("class:dim", "  A human still signs off.\n\n"))
        if state["exec"]:
            out.append(("class:warn", "  Code execution AUTHORISED\n"))
            out.append(("class:dim", "  for this run, then expires.\n"))
        else:
            out.append(("class:dim", "  No execution: review stays\n  static, findings inferred.\n"))
        return out

    def _footer():
        return [("class:hint", "  Space/Enter toggle · Ctrl-D START unattended · Esc cancel")]

    kb = KeyBindings()

    @kb.add("up")
    def _up(event):
        idx[0] = (idx[0] - 1) % len(rows)

    @kb.add("down")
    def _down(event):
        idx[0] = (idx[0] + 1) % len(rows)

    @kb.add(" ")
    @kb.add("enter")
    def _toggle(event):
        # Enter TOGGLES here, it does not commit (owner, 2026-08-25: "enter is too easy to
        # press ... user may press enter thinking it toggles options"). That was exactly
        # right, and on this screen of all screens: it is the single authorisation gate for
        # an unattended run, so the most reflexive key on the keyboard must not be the one
        # that arms it. Enter now does the harmless thing people expect - it acts on the
        # highlighted row - and committing moved to Ctrl-D, the same send key the request
        # composer uses, so the two screens in this flow agree.
        key, kind = rows[idx[0]][0], rows[idx[0]][1]
        if kind == "toggle":
            state[key] = not state[key]
        elif key == "cap":
            state["cap"] = (state["cap"] + 1) % len(CAPS)
        else:
            state["on_budget"] = (state["on_budget"] + 1) % len(ON_BUDGET)

    @kb.add("c-d")
    def _start(event):
        state["confirmed"] = True
        event.app.exit()

    @kb.add("escape", eager=True)
    @kb.add("c-c")
    def _esc(event):
        event.app.exit()

    try:
        screen(
            mod,
            title=f"{g['jira']}Auto mode - authorise this run",
            body_fn=_body,
            right_fn=_right,
            footer_fn=_footer,
            key_bindings=kb,
            output=output,
            project_dir=project_dir,
        )
    except Exception:
        return None
    if not state["confirmed"]:
        return AUTO_CANCELLED
    return {
        "data_attested": state["data"],
        "allow_exec": state["exec"],
        "engagement_usd": CAPS[state["cap"]] or None,
        "on_budget": ON_BUDGET[state["on_budget"]],
    }


REQUEST_SKIPPED = "__request_skipped__"


def request_screen(project_dir: Path, mod, output=None):
    """Take the request for a NEW engagement at the launcher (2026-08-24 user report: "I
    clicked new engagement but there was no option to pre-seed a prompt, it just opened cc").

    `[n]` launched with `--new` and nothing else, so the first thing that happened in-session
    was Morgan asking what the work is - a question the human could have answered here, with a
    keyboard already under their hands. The Jira route has collected its input at the launcher
    since it was built; the route people actually use most could not.

    Typing is an OFFER, never a toll gate: Enter on an empty field gives exactly today's plain
    `--new`, so nobody is forced to compose a brief at a prompt.

    Returns (request, auto) when text was typed, REQUEST_SKIPPED for the plain launch, or
    None when the screen cannot run (the caller then does what it did before)."""
    try:
        p = mod._ptk_ui()
        if not p:
            return None
        from prompt_toolkit.key_binding import KeyBindings
        from prompt_toolkit.keys import Keys
    except Exception:
        return None

    g = glyphs(mod)
    buf = [""]
    auto = [mod._auto_armed(project_dir)]  # pre-armed only if the project asked
    result = {"v": REQUEST_SKIPPED}
    auto_offered = mod._auto_offered(project_dir)

    def _body():
        out = [("class:group", f"  {g['new']}What would you like the team to do?\n\n")]
        out.append(("class:dim", "  Type it. Esc to decide in session instead.\n\n"))
        cursor = "_" if mod._can_encode("_") else " "
        # Wrap for DISPLAY across the pane, and show the LAST few lines - a composer that
        # scrolls off the top is normal; one that hides what you are currently typing is
        # not. The full value is always what gets returned.
        lines = _wrapped(buf[0], _INPUT_WINDOW)
        if len(lines) > _COMPOSER_LINES:
            lines = lines[-_COMPOSER_LINES:]
            lines[0] = ("..." if mod._can_encode("...") else "..") + lines[0]
        for i, line in enumerate(lines):
            out.append(("class:title", "  > " if i == 0 else "    "))
            out.append(("", line))
            if i == len(lines) - 1:
                out.append(("class:hint", cursor))
            out.append(("", "\n"))
        out.append(("", "\n"))
        if auto_offered:
            mark = g["on"] if auto[0] else g["off"]
            out.append(("class:on" if auto[0] else "class:off", f"  {mark} "))
            out.append(("class:warn" if auto[0] else "class:dim", "Ctrl-A  run unattended"))
            # Kept SHORT on purpose: the left pane is ~47 columns and this row already
            # spends 26 on the label, so anything longer is clipped mid-word at the border
            # (caught under a real pty 2026-08-25 - "(you authorise it o"). The full
            # explanation lives in the right-hand pane, which has the room for it.
            if auto[0] and not buf[0].strip():
                out.append(("class:warn", "  (needs a request)\n"))
            elif auto[0]:
                out.append(("class:dim", "  (confirm next)\n"))
            else:
                out.append(("class:dim", "  (off - it asks)\n"))
        return out

    def _right():
        out = [("class:title", "\n  Starting new work\n\n")]
        out.append(
            (
                "class:dim",
                "  Whatever you type is handed\n  to Morgan as the request, so\n"
                "  the session starts on the\n  work instead of asking what\n  it is.\n\n"
                "  Leave it empty and nothing\n  changes - you get today's\n  plain launch.\n\n",
            )
        )
        if auto_offered and auto[0]:
            out.append(("class:warn", "  Unattended: you authorise\n  it on the next screen.\n"))
        return out

    def _footer():
        tail = " · Ctrl-A unattended" if auto_offered else ""
        return [
            ("class:hint", f"  Ctrl-D send · Enter new line · Esc back · Ctrl-U clear{tail}")
        ]

    kb = KeyBindings()

    @kb.add("c-a")
    def _auto(event):
        # Ctrl-A, not a bare letter: every printable key is text for the request field.
        # Toggles whether or not there is text yet (2026-08-25): arming first and then
        # writing the brief is a natural order, and the old guard made that keypress a
        # SILENT no-op - the worst possible answer, since the screen then looked as though
        # unattended had been declined. An armed toggle with an empty field still cannot
        # start anything: sending with no text is a skip, and _new_command drops --auto
        # without a request. The row below says what it needs.
        if auto_offered:
            auto[0] = not auto[0]

    @kb.add(Keys.Any)
    def _type(event):
        data = event.data or ""
        if data.isprintable():
            buf[0] += data

    @kb.add(Keys.BracketedPaste)
    def _paste(event):
        # A newline is a WORD BREAK, never nothing (2026-08-25 report: a multi-sentence
        # request arrived incomplete). Dropping unprintables welded the sentences either
        # side of a line break into "extract.Then", which is worse than truncation because
        # it looks like text the human wrote. The request travels as one line anyway
        # (_sanitise_request flattens it), so collapse here and keep every word.
        buf[0] += " ".join((event.data or "").split())
        if buf[0] and (event.data or "").endswith(("\n", " ", "\t")):
            buf[0] += " "  # a trailing break is still a word boundary for whatever follows

    @kb.add("backspace")
    def _back(event):
        buf[0] = buf[0][:-1]  # deletes a newline like any other character

    @kb.add("c-u")
    def _clear(event):
        buf[0] = ""
        auto[0] = False

    @kb.add("enter")
    def _newline(event):
        # 2026-08-25 live report: "claude never got the full instruction i typed which was
        # a couple of sentences". Enter used to SEND, so composing across lines - the
        # natural way to write a brief, and what a paste does in any terminal without
        # bracketed paste - submitted the first line and discarded the rest silently.
        # A key that can destroy what you just typed has no place on a composer, so Enter
        # is a line break here and sending moved to a key you cannot hit by accident.
        buf[0] += "\n"

    @kb.add("c-d")
    # No Alt-Enter: Esc is bound eager (it has to be, or every arrow key waits on a
    # disambiguation timeout), and an eager Esc fires before the two-key escape+enter
    # sequence can ever resolve. Verified 2026-08-25 - the binding existed and silently
    # backed out instead of sending. Esc-to-back is worth more than a second send key.
    def _accept(event):
        text = " ".join(buf[0].split())
        result["v"] = (text, auto[0]) if text else REQUEST_SKIPPED
        event.app.exit()

    @kb.add("escape", eager=True)
    @kb.add("c-c")
    def _esc(event):
        result["v"] = REQUEST_SKIPPED
        event.app.exit()

    try:
        screen(
            mod,
            title=f"{g['new']}New engagement",
            body_fn=_body,
            right_fn=_right,
            footer_fn=_footer,
            key_bindings=kb,
            output=output,
            project_dir=project_dir,
        )
    except Exception:
        return None
    return result["v"]


MONITOR_CLOSED = "__monitor_closed__"
# The monitor asking its CALLER to show the workflow. It cannot show it itself: a second
# Application started from inside a running one never runs (2026-08-25).
MONITOR_WANTS_WORKFLOW = "__monitor_wants_workflow__"
_MONITOR_REFRESH = 2.0  # seconds; the state file changes at human pace, not machine pace


def _clock() -> float:
    """Monotonic, so the elapsed line cannot go backwards when the system clock is set."""
    import time

    return time.monotonic()


def _elapsed(since: float) -> str:
    seconds = max(0, int(_clock() - since))
    if seconds < 60:
        return f"{seconds}s"
    minutes, seconds = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {seconds:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes:02d}m"


def _monitor_read(project_dir: Path, slug: str) -> dict:
    """One snapshot of an engagement, read fresh from disk every tick.

    Deliberately re-reads rather than caching: the whole point is that another PROCESS is
    writing this file, so anything held in memory here is stale by definition. Failure is
    normal, not exceptional - the pack does not exist until the session creates it, and a
    read can land mid-write - so every problem resolves to a displayable state instead of
    an exception."""
    import json as _json

    pack = project_dir / "artifacts" / slug
    state_path = pack / "engagement-state.json"
    snap = {"slug": slug, "exists": pack.is_dir(), "state": None, "artifacts": 0, "error": ""}
    try:
        snap["artifacts"] = sum(1 for p in pack.rglob("*") if p.is_file()) if pack.is_dir() else 0
    except OSError:
        pass
    try:
        snap["state"] = _json.loads(state_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        snap["error"] = "waiting for the session to create the workspace"
    except ValueError:
        # A partial read of a file being rewritten. Says so rather than showing "invalid",
        # which would read as a broken engagement rather than a two-millisecond race.
        snap["error"] = "state file is being written"
    except OSError as exc:
        snap["error"] = f"cannot read state ({exc.__class__.__name__})"
    return snap


def monitor_screen(project_dir: Path, mod, slug: str, ref: str = "", output=None):
    """Live status of an unattended engagement, shown in the launcher after the session
    has been opened in its own window (2026-08-25).

    This is the half of "run it unattended" that was missing. Nobody is being asked
    anything, so without a view here the human has a terminal that closed and no idea
    whether the run is working, parked or finished. It is also the precursor to headless:
    once the launcher can WATCH an engagement it did not host, hosting it elsewhere - a
    detached process, another machine - becomes a change of where, not of what.

    Read-only by construction. It opens no files for writing and sends the session nothing;
    closing it stops the watching, never the work. That property is what makes it safe to
    leave running, and it is why Esc says "stop watching" rather than "stop"."""
    try:
        p = mod._ptk_ui()
        if not p:
            return None
        from prompt_toolkit.key_binding import KeyBindings
    except Exception:
        return None

    g = glyphs(mod)
    started = _clock()
    result = {"v": MONITOR_CLOSED}
    # How long a workspace may take to appear before the monitor stops saying "waiting" and
    # starts saying something useful. A session that has started creates its pack within
    # seconds; if nothing exists after this, the far more likely explanation is that no
    # session started at all - which is exactly what happened on Windows (2026-08-25: several
    # minutes of a patient "waiting" line while nothing whatsoever was running).
    _PATIENCE = 45.0

    def _rows(snap: dict) -> list:
        state = snap.get("state") or {}
        eng = state.get("engagement") or {}
        outstanding = state.get("outstanding") or []
        budget = state.get("budget") or {}
        rows = [
            ("engagement", eng.get("title") or slug),
            ("slug", slug),
            ("status", state.get("status") or "-"),
            ("phase", state.get("phase") or "-"),
            ("outstanding", str(len(outstanding)) if isinstance(outstanding, list) else "-"),
            ("artifacts", str(snap.get("artifacts", 0))),
        ]
        if state.get("auto"):
            # Two short rows, not one long one: the left pane is ~47 columns and a value
            # that runs past it is clipped mid-word at the border - caught under a pty
            # twice now (2026-08-25), because a headless harness cannot see it.
            rows.append(("unattended", "yes"))
            rung = state.get("auto_on_budget") or "-"
            cap = budget.get("engagement_usd") or state.get("engagement_usd")
            rows.append(("ceiling", f"${cap}, then {rung}" if cap else f"none, {rung}"))
        return rows

    def _body():
        snap = _monitor_read(project_dir, slug)
        state = snap.get("state") or {}
        out = [("class:group", f"  {g['new']}Watching this run\n\n")]
        if snap.get("error"):
            waited = _clock() - started
            if not snap.get("exists") and waited > _PATIENCE:
                # Say the quiet part: a monitor that only ever reports patience is
                # indistinguishable from a monitor watching nothing.
                out.append(("class:warn",
                            f"  No workspace after {_elapsed(started)} - the session may not "
                            "have started.\n"))
                out.append(("class:dim",
                            "  Check the other window for an error, or press Esc and launch\n"
                            "  in this one instead.\n\n"))
            else:
                out.append(("class:dim", f"  {snap['error']}\n\n"))
        width = 13
        for label, value in _rows(snap):
            out.append(("class:dim", f"  {label:<{width}}"))
            style = ""
            if label == "status" and value in ("blocked", "parked"):
                style = "class:warn"
            elif label == "status" and value in ("closed", "done"):
                style = "class:on"
            out.append((style, f"{value}\n"))
        outstanding = state.get("outstanding") or []
        if isinstance(outstanding, list) and outstanding:
            out.append(("class:dim", "\n  outstanding\n"))
            for item in outstanding[:6]:
                text = item.get("text", "") if isinstance(item, dict) else str(item)
                out.append(("", f"    - {text[:52]}\n"))
            if len(outstanding) > 6:
                out.append(("class:dim", f"    +{len(outstanding) - 6} more\n"))
        out.append(("class:dim", f"\n  watching for {_elapsed(started)}\n"))
        return out

    def _right():
        out = [("class:title", "\n  Unattended run\n\n")]
        out.append(
            (
                "class:dim",
                "  The session is running in\n  its own window. This pane\n"
                "  reads its state file every\n  couple of seconds.\n\n"
                "  Nothing here talks to the\n  session: closing this stops\n"
                "  the watching, never the\n  work.\n\n"
                "  It closes PARTIAL for your\n  sign-off, whatever it\n  finds.\n",
            )
        )
        return out

    workflow_on = False
    try:
        workflow_on = bool(mod._workflow_view_on(project_dir))
    except Exception:
        workflow_on = False

    def _footer():
        tail = " · w workflow" if workflow_on else ""
        return [("class:hint",
                 f"  Esc stop watching (the run continues) · r refresh now{tail}")]

    kb = KeyBindings()

    @kb.add("r")
    def _refresh(event):
        event.app.invalidate()

    @kb.add("w")
    def _workflow(event):
        # EXIT with an intent; never open a second Application from inside a running one.
        # prompt_toolkit's app.run() detects the live event loop, hands back a coroutine
        # nobody awaits, and returns None - surfacing as "coroutine 'Application.run_async'
        # was never awaited ... enable tracemalloc" printed into the middle of the screen
        # (reported 2026-08-25 on pressing w). The caller re-enters, so this reads as a
        # nested view to the human while being a flat sequence to the runtime.
        if workflow_on:
            result["v"] = MONITOR_WANTS_WORKFLOW
            event.app.exit()

    @kb.add("escape", eager=True)
    @kb.add("c-c")
    @kb.add("q")
    def _close(event):
        event.app.exit()

    try:
        screen(
            mod,
            title=f"{g['new']}Unattended - {slug}",
            body_fn=_body,
            right_fn=_right,
            footer_fn=_footer,
            key_bindings=kb,
            output=output,
            project_dir=project_dir,
            refresh_interval=_MONITOR_REFRESH,
        )
    except Exception:
        return None
    return result["v"]


WORKFLOW_CLOSED = "__workflow_closed__"
_WORKFLOW_ROWS = 9  # visible stage rows; the trace itself is never truncated
_WORKFLOW_REFRESH = 6.0  # seconds - a transcript is large and grows; the state file is not
# Two panes of one picture are drawn milliseconds apart. Anything inside this window is the
# same frame; well under the refresh interval, so it never masks a real update.
_FRAME_WINDOW = 0.5


def workflow_screen(project_dir: Path, mod, output=None, session: str = ""):
    """The workflow the team is following: stage, model, cost, and where it looped.

    Reads scripts/workflow_trace - it does no parsing of its own, so this screen and the
    exporter cannot drift apart. Refreshes on the monitor's cadence, because a running
    engagement gains stages while you watch.

    Read-only, like the monitor beside it: nothing here writes, and closing it stops the
    watching rather than the work."""
    try:
        p = mod._ptk_ui()
        if not p:
            return None
        from prompt_toolkit.key_binding import KeyBindings
    except Exception:
        return None

    g = glyphs(mod)
    top = [0]
    note = [""]
    frame = {"at": -1.0, "trace": None}

    def _trace():
        """The trace for THIS frame, computed at most once.

        Both panes need it, and calling through twice per render doubled the work on a file
        that can be tens of megabytes (2026-08-25 report: the view ran out of memory). A
        short time window rather than a frame counter, because there is no frame hook to
        count - the two panes of one picture are drawn milliseconds apart, and anything
        inside that window is the same picture. The parser caches on (path, size, mtime)
        too; this stops even the stat call happening twice for one frame."""
        now = _clock()
        if frame["trace"] is not None and (now - frame["at"]) < _FRAME_WINDOW:
            return frame["trace"]
        try:
            import workflow_trace

            trace = (
                workflow_trace.parse(Path(session)) if session
                else workflow_trace.trace_for(project_dir)
            )
        except MemoryError:
            # Named separately because it is the one failure the reader can act on, and
            # "unavailable" would hide it.
            trace = {"ok": False, "stages": [],
                     "error": "transcript too large to trace on this machine"}
        except Exception as exc:
            trace = {"ok": False, "stages": [],
                     "error": f"trace unavailable ({exc.__class__.__name__})"}
        frame["at"], frame["trace"] = now, trace
        return trace

    def _body():
        trace = _trace()
        out = [("class:group", f"  {g['new']}Workflow\n\n")]
        if not trace.get("ok"):
            out.append(("class:dim", f"  {trace.get('error', 'no trace')}\n"))
            return out
        totals = trace.get("totals") or {}
        stages = trace.get("stages") or []
        out.append(("class:dim", "  "))
        out.append(("", f"{totals.get('agent_stages', 0)} stages"))
        out.append(("class:dim", "  ·  "))
        out.append(("", f"{_compact(totals.get('tokens', 0))} tok"))
        out.append(("class:dim", "  ·  "))
        out.append(("class:warn", f"{_cost(totals.get('cost'))} est"))
        out.append(("", "\n\n"))
        window = stages[top[0] : top[0] + _WORKFLOW_ROWS]
        width = min(18, max((len(s.get("agent", "")) for s in window), default=10))
        for stage in window:
            mark = g["on"] if stage.get("status") == "completed" else g["off"]
            if stage.get("kind") == "orchestration":
                mark = "·" if mod._can_encode("·") else "."
            loop = stage.get("loop_index", 1)
            out.append(("class:on" if stage.get("status") == "completed" else "class:dim",
                        f"  {mark} "))
            out.append(("", f"{stage.get('agent', '?')[:width].ljust(width)} "))
            if loop > 1:
                out.append(("class:warn", f"x{loop} "))
            else:
                out.append(("", "   "))
            out.append(("class:dim", f"{_short(stage.get('model', '')):<7}"))
            out.append(("", f"{_compact(stage.get('tokens', 0)):>7} "))
            out.append(("class:warn", f"{_cost(stage.get('cost')):>9}"))
            out.append(("", "\n"))
        if len(stages) > _WORKFLOW_ROWS:
            out.append(("class:dim",
                        f"\n  {top[0] + 1}-{min(top[0] + _WORKFLOW_ROWS, len(stages))}"
                        f" of {len(stages)}   up/down to scroll\n"))
        if totals.get("unpriced_stages"):
            out.append(("class:warn",
                        f"\n  {totals['unpriced_stages']} stage(s) on an unpriced model\n"))
        if note[0]:
            out.append(("class:on", f"\n  {note[0]}\n"))
        return out

    def _right():
        trace = _trace()
        out = [("class:title", "\n  Reading the run\n\n")]
        out.append(
            (
                "class:dim",
                "  One row per stage, in the\n  order they ran.\n\n"
                "  x2 marks a repeat - the\n  same specialist called\n  again. That is a loop,\n"
                "  and its cost is the one\n  nobody can see today.\n\n"
                "  Tokens are measured.\n  Cost is INFERRED from a\n  rate table and is an\n"
                "  estimate, never a bill.\n\n"
                "  For the SESSION total,\n  trust /cost in Claude -\n  that is the authority.\n"
                "  These figures exist to\n  apportion it across the\n  stages, which /cost\n"
                "  cannot do.\n\n",
            )
        )
        if trace.get("rates_as_of"):
            out.append(("class:dim", f"  rates of {trace['rates_as_of']}\n"))
        return out

    def _footer():
        return [("class:hint", "  e export · up/down scroll · Esc back")]

    kb = KeyBindings()

    @kb.add("up")
    def _up(event):
        top[0] = max(0, top[0] - 1)

    @kb.add("down")
    def _down(event):
        top[0] += 1

    @kb.add("e")
    def _export(event):
        note[0] = _export_trace(project_dir, _trace())

    @kb.add("escape", eager=True)
    @kb.add("c-c")
    @kb.add("q")
    def _close(event):
        event.app.exit()

    try:
        screen(
            mod,
            title=f"{g['new']}Workflow",
            body_fn=_body,
            right_fn=_right,
            footer_fn=_footer,
            key_bindings=kb,
            output=output,
            project_dir=project_dir,
            # Slower than the status monitor on purpose: that reads one small state file,
            # this reads a transcript that grows all session. Every refresh of a LIVE file
            # is a real re-parse, cache or no cache, because its mtime has moved.
            refresh_interval=_WORKFLOW_REFRESH,
        )
    except Exception:
        return None
    return WORKFLOW_CLOSED


def _export_trace(project_dir: Path, trace: dict) -> str:
    """Write the trace out and report where, in one short line for the screen."""
    if not trace.get("ok"):
        return "nothing to export yet"
    try:
        import contextlib
        import io
        import warnings

        import render_workflow

        out_dir = project_dir / "artifacts" / "workflow"
        # stderr is the TUI's DRAWING channel. The HTML renderer pulls in bleach, which emits
        # a warning on import, and that warning lands in the middle of the frame - caught
        # under a pty, 2026-08-25, garbling the screen the moment anyone pressed e. Anything
        # a screen calls has to be silenced on this stream, not trusted to be quiet.
        sink = io.StringIO()
        with contextlib.redirect_stderr(sink), contextlib.redirect_stdout(sink):
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                written = render_workflow.export(trace, out_dir, ("md", "html", "json", "csv"))
        return f"exported {len(written)} file(s) to artifacts/workflow/" if written else (
            "export produced nothing"
        )
    except Exception as exc:
        return f"export failed ({exc.__class__.__name__})"


def _compact(tokens) -> str:
    """1_240_000 -> 1.2m. A column of raw digits is unreadable at pane width."""
    try:
        value = int(tokens or 0)
    except (TypeError, ValueError):
        return "-"
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}m"
    if value >= 1_000:
        return f"{value / 1_000:.0f}k"
    return str(value)


def _cost(value) -> str:
    if value is None:
        return "unpriced"
    if 0 < value < 0.01:
        return f"${value:.3f}"
    return f"${value:,.2f}"


def _short(model: str) -> str:
    """Family name if we know it, otherwise the DISTINCTIVE part of the id.

    Truncating from the left gives "claude-" for every unknown model, which identifies
    nothing - the vendor prefix is the one part they all share. Drop it first."""
    for family in ("opus", "sonnet", "haiku", "fable"):
        if family in (model or ""):
            return family
    tail = (model or "-").removeprefix("claude-")
    return tail[:7] if tail else "-"
