#!/usr/bin/env python3
"""Textual widgets for the launcher's screens.

Drawing only. Nothing here decides what a choice MEANS: a screen collects an answer
and hands it back, and virt_team_launcher does the rest - exactly as it does for the
prompt_toolkit tier in launcher_app.py. That is what keeps the two renderings in step
without a copy of the launcher to maintain.

`launcher_textual.py` is the adapter that offers these under launcher_app's own
signatures; this file knows nothing about tiers or sentinels.
"""

from __future__ import annotations

import sys
from pathlib import Path

from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Static

# ── palette ───────────────────────────────────────────────────────────────────
# The warm accent is the launcher's existing one (scripts/tui_chrome.py's PALETTE),
# so the two tiers do not read as different products. Every colour is a hex the
# terminal maps itself, so a 16-colour console still renders something sensible.
ACCENT = "#d97757"
GOLD = "#c9a227"
OK = "#3fb950"
KEY = "#7aa2f7"
TEXT = "#e6e6e6"
DIM = "#8a8f98"
HINT = "#6b7280"
TRACK = "#2a2a31"
MOUTH = "#3d3d47"

EIGHTHS = " ▏▎▍▌▋▊▉█"

# Below this, two panes cannot both hold their content: the detail pane is dropped and
# its text moves to the footer. Phones and split panes land here - launcher_app already
# learned this ("overflows the frame on a phone, where the same text is the only
# column and the borders come out of it too").
NARROW = 76


def wrap(text: str, width: int) -> list[str]:
    """Hand-wrap to a fixed width.

    Hand-rolled rather than left to the widget: these panes are a weighted split, so
    letting the renderer rewrap would move text under the cursor on every resize.
    """
    out, line = [], ""
    for word in (text or "").split():
        if line and len(line) + 1 + len(word) > width:
            out.append(line)
            line = word
        else:
            line = f"{line} {word}".strip()
    if line:
        out.append(line)
    return out


def wrap_display(text: str, width: int) -> list[str]:
    """Word-wrap for DISPLAY only, honouring the newlines the human typed.

    Never used to decide what is SENT - the request is flattened on the way out - so
    this can be purely cosmetic and lossless. Mirrors tui_chrome._wrapped, which the
    prompt_toolkit tier uses, so the two renderings break lines in the same places.
    """
    lines: list[str] = []
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


def bar(pct: float, width: int, fill: str = ACCENT, track: str = TRACK) -> Text:
    """Sub-cell progress bar: eighth-blocks on a shaded track."""
    total = width * 8
    units = max(0, min(total, round(pct * total)))
    full, rem = divmod(units, 8)
    t = Text()
    if full:
        t.append("█" * full, style=fill)
    if full < width:
        if rem:
            t.append(EIGHTHS[rem], style=fill)
            t.append("░" * (width - full - 1), style=track)
        else:
            t.append("░" * (width - full), style=track)
    return t


class Brand(Static):
    """The mark: a robot head whose mouth is a progress bar and whose eyes light on
    success. One identity object, static here and animated where there is progress."""

    #: Columns the mark itself occupies on the rule's line, before the rule starts.
    MARK_COLS = 16

    def render_frame(self, pct: float, subtitle: str, narrow: bool = False, width: int = 0) -> None:
        eye = OK if pct >= 1.0 else ACCENT
        # Fitted to the terminal, then capped. A fixed rule per width class is wrong at
        # the bottom of a class - 34 columns plus the mark overflowed a 50-column
        # terminal and wrapped the rule onto its own line - and a MEASURED one is wrong
        # on the first paint, where content_size is 0 and self.size is the screen. The
        # caller knows the real width, so take it and clamp.
        pad = 1 if narrow else 3
        cap = 34 if narrow else 52
        rule = cap
        if width:
            rule = max(4, min(cap, width - 2 * pad - self.MARK_COLS))
        t = Text()
        t.append("       ○\n", style=DIM)
        t.append("   ╭───┴───╮   ", style=DIM)
        # The product is VIRT-SURV-IT; "virt-surv" is only the command you type
        # (owner, 2026-08-31). The mark is the name, not the alias.
        t.append("VIRT-SURV-IT\n", style=f"bold {ACCENT}")
        t.append("  ─┤ ", style=DIM)
        t.append("●", style=f"bold {eye}")
        t.append("   ", style=DIM)
        t.append("●", style=f"bold {eye}")
        t.append(" ├─   ", style=DIM)
        t.append("─" * rule + "\n", style=TRACK)
        t.append("   │ ", style=DIM)
        t.append_text(bar(pct, 5, track=MOUTH))
        t.append(" │   ", style=DIM)
        t.append(subtitle + "\n", style=DIM)
        t.append("   ╰───────╯", style=DIM)
        self.update(t)


class TierApp(App):
    """Shared chrome: the mark, a list pane, a detail pane, a footer."""

    CSS_PATH = str(Path(__file__).resolve().parent / "launcher_tiers.tcss")
    # NO BINDINGS, on purpose. Textual MERGES BINDINGS up the MRO and a binding fires
    # even when a handler has already consumed the key, so a base-class binding is one
    # a screen can neither remove nor override. Both attempts to use one cost a bug: a
    # quit-on-q ended the composer instead of typing a q, and a quit-on-Esc closed the
    # settings screen when Esc was meant to cancel the Jira-key edit inside it. Every
    # screen therefore handles its own exits in on_key, where the state that decides
    # what a key means is in scope.
    BINDINGS: list = []

    def __init__(self, project) -> None:
        super().__init__()
        self.project = Path(project)
        self.result = None
        self.note = ""
        self.cursor = 0

    def _fatal_error(self) -> None:
        """Report a crash without rich.traceback, which needs pygments.

        pygments is deliberately NOT vendored - rich's Console/Table/Panel/Rule need
        neither it nor markdown-it, and a test pins that. Textual's default handler
        imports it anyway, so on a user's machine a crash surfaced as
        "ModuleNotFoundError: pygments" - the one moment the cause matters, replaced by
        a package they never asked for.
        """
        import traceback as _tb

        self.bell()
        exc = getattr(self, "_exception", None)
        try:
            self._exit_renderables.append(
                "".join(_tb.format_exception(type(exc), exc, exc.__traceback__))
                if exc is not None
                else "virt-surv stopped unexpectedly."
            )
        except Exception:  # noqa: BLE001 — reporting must never re-raise
            self._exit_renderables.append("virt-surv stopped unexpectedly.")
        self.exit()

    def compose(self) -> ComposeResult:
        with Vertical(id="shell"):
            yield Brand(id="brand")
            with Horizontal(id="panes"):
                with VerticalScroll(id="panel"):
                    yield Static(id="rows")
                with Vertical(id="side"):
                    yield Static(id="side-body")
            yield Static(id="detail")
            yield Static(id="keys")

    def _apply_width(self, width: int | None = None) -> None:
        """Set the width class from the CURRENT size.

        Driven from on_mount as well as on_resize: a resize event is not guaranteed for
        the INITIAL size, and over mosh/tmux it can arrive late or not at all. Relying
        on the event alone left the app laid out for a wide terminal inside a narrow
        one, so content sized for two panes wrapped at the left margin and the wrapped
        remnants read as a second, mangled copy of the screen.
        """
        if width is None:
            width = getattr(self.size, "width", 0) or 0
        narrow = 0 < width < NARROW
        self._narrow = narrow
        # The class goes on the SCREEN: the stylesheet selects `Screen.-narrow #side`,
        # so setting it on the app node matched nothing.
        try:
            self.screen.set_class(narrow, "-narrow")
        except Exception:  # noqa: BLE001 — cosmetic only
            pass

    def on_resize(self, event) -> None:
        self._apply_width(event.size.width)
        painter = getattr(self, "paint", None)
        if callable(painter):
            painter()

    @property
    def narrow(self) -> bool:
        return bool(getattr(self, "_narrow", False))

    def panel_width(self) -> int:
        """Columns available for text inside the list pane.

        Derived from the screen rather than measured: content_size is 0 on a first
        paint, and a composer that rewraps a line under the cursor on the second paint
        is worse than one that is a column conservative.
        """
        w = getattr(self.size, "width", 0) or 0
        if not w:
            return 40
        if self.narrow:  # shell pad 1, border 1, pad 1, each side
            return max(20, w - 6)
        return max(20, w - 46)  # ... plus the 32-wide side pane and its margin

    def chrome_ready(self, panel_title: str, side_title: str = "detail") -> None:
        """Name the panes and take the keyboard away from them.

        A VerticalScroll is focusable, and Textual gives a key to the FOCUSED WIDGET
        before it bubbles to the app - so every Down was scrolling the pane by a line
        before this screen ever saw it, and the app's own scrolling then fought a list
        that had already moved. Clearing can_focus is not enough on its own: focus
        already taken is not released by it, so it has to be dropped explicitly.
        """
        try:
            panel = self.query_one("#panel")
            panel.border_title = panel_title
            panel.can_focus = False
            self.query_one("#side").border_title = side_title
            self.set_focus(None)
        except Exception:  # noqa: BLE001 — cosmetic
            pass

    def scroll_row(self, line: int) -> None:
        """Keep the highlighted row in view.

        The list pane scrolls, and nothing was moving it: with seventeen settings the
        cursor walked off the bottom of the pane and the screen looked frozen - the
        selection was still moving, just where it could not be seen. The prompt_toolkit
        tier paged instead; scrolling is the same guarantee without the page seams.
        """
        try:
            panel = self.query_one("#panel")
            height = panel.content_size.height or 0
            if height <= 0:
                return
            top = panel.scroll_offset.y
            if line < top:
                panel.scroll_to(y=line, animate=False)
            elif line >= top + height:
                panel.scroll_to(y=line - height + 1, animate=False)
        except Exception:  # noqa: BLE001 — scrolling is cosmetic
            pass

    def folder(self) -> str:
        """The folder being read, shortened but never guessed at."""
        try:
            return "~/" + str(self.project.resolve().relative_to(Path.home()))
        except (ValueError, OSError):
            return str(self.project)

    def head(self, subtitle: str) -> None:
        self.query_one("#brand", Brand).render_frame(
            0.0, subtitle, self.narrow, getattr(self.size, "width", 0) or 0
        )

    def foot(self, pairs, note: str = "", warn: bool = False) -> None:
        d = Text("  ")
        d.append("│ ", style=TRACK)
        d.append(note or "", style=GOLD if warn else HINT)
        self.query_one("#detail", Static).update(d)
        k = Text("  ")
        for name, desc in pairs:
            k.append(name, style=KEY)
            k.append(f" {desc}   ", style=HINT)
        self.query_one("#keys", Static).update(k)


class MenuApp(TierApp):
    """The engagement menu.

    Returns a PICK and nothing else - ("resume", i) or one of launcher_app's action
    tuples. Every consequence of that pick is virt_team_launcher's
    `_decision_from_pick`: the request composer, Jira, archive, artifacts, watch,
    review. So this screen never learns what any of them mean.
    """

    def __init__(self, project, views: list, actions: list, menu: dict) -> None:
        super().__init__(project)
        self.views = list(views)
        self.actions = list(actions)
        self.menu = menu or {}
        self.pick = None
        # Did this screen actually DRAW? "The user backed out" and "this tier cannot
        # run" are different answers - launcher_app returns None for the first and its
        # own sentinel for the second - and conflating them sent Esc through to the
        # next tier, which then drew the old menu.
        self.ran = False
        # One flat list over both regions, so up/down crosses the boundary naturally -
        # the same shape launcher_app uses.
        self.items = [("eng", i) for i in range(len(self.views))] + [
            ("act", i) for i in range(len(self.actions))
        ]

    def on_mount(self) -> None:
        self.ran = True
        self._apply_width()  # before the first paint, not after a resize
        n = len(self.views)
        self.chrome_ready(f"{n} open" if n else "nothing open")
        self.paint()

    def paint(self) -> None:
        folder = self.folder()
        self.head(folder if self.narrow else f"{folder}  ·  engagements in this folder")

        t = Text()
        # Line counter for scroll_row: the pane scrolls, so the highlighted row has to
        # be findable by line, and headings make the row index and the line number
        # different numbers.
        self._y = 0
        self._cursor_line = 0
        if self.views:
            t.append("  Resume an engagement\n", style=f"bold {HINT}")
            self._y += 1
            for i, v in enumerate(self.views):
                self._row(
                    t,
                    ("eng", i),
                    v.get("title") or "?",
                    mark=v.get("mark") or "•",
                    warn=v.get("mark_style") == "warn",
                    tag="← most recent" if v.get("recommended") else "",
                )
        else:
            # Which FOLDER, because "no open engagements" alone reads as a statement
            # about the product rather than about where you are standing.
            archived = self.menu.get("archived") or 0
            t.append(
                f"  no open engagements here{f' ({archived} archived)' if archived else ''}\n",
                style=HINT,
            )
            self._y += 1

        t.append("\n  Start something new\n", style=f"bold {HINT}")
        self._y += 2
        seen_or = False
        for i, (pick, label, key) in enumerate(self.actions):
            # "Or" before the non-new actions, because without it "change a project
            # setting" read as though it were an engagement.
            if pick[0] not in ("new", "jira") and not seen_or:
                t.append("\n  Or\n", style=f"bold {HINT}")
                self._y += 2
                seen_or = True
            self._row(t, ("act", i), label, key=key)
        self.query_one("#rows", Static).update(t)
        self.scroll_row(self._cursor_line)

        kind, idx = self.items[self.cursor] if self.items else ("act", 0)
        body = Text("\n")
        if kind == "eng" and self.views:
            v = self.views[idx]
            body.append(f"  {v.get('title') or '?'}\n\n", style=f"bold {ACCENT}")
            for label, value in v.get("lines") or []:
                body.append(f"  {label:<10}", style=HINT)
                warn = v.get("status") == "blocked" and label in ("status", "next")
                body.append(f"{value}\n", style=GOLD if warn else TEXT)
        elif self.actions:
            _pick, label, key = self.actions[idx]
            for line in wrap(label, 26):
                body.append(f"  {line}\n", style=f"bold {ACCENT}")
            if key:
                body.append("\n  shortcut  ", style=HINT)
                body.append(key, style=KEY)
                body.append("\n")
        self.query_one("#side-body", Static).update(body)

        self.foot(
            (("↑↓", "move"), ("enter", "choose"), ("esc/q", "back to terminal")),
            f"{len(self.views)} open in {folder}",
        )

    def _row(
        self, t: Text, item, label: str, mark: str = "", warn: bool = False, tag: str = "", key=None
    ) -> None:
        sel = self.items[self.cursor] == item if self.items else False
        if sel:
            self._cursor_line = self._y
        self._y += 1
        t.append("  ▸ " if sel else "    ", style=ACCENT if sel else HINT)
        if mark:
            t.append(mark + " ", style=GOLD if warn else DIM)
        if key:
            t.append(f"[{key}] ", style=KEY)
        t.append(label, style=f"bold {TEXT}" if sel else TEXT)
        if tag:
            t.append("   " + tag, style=OK)
        t.append("\n")

    def on_key(self, event) -> None:
        # A list has no text to type into, so `q` is a second way out of it alongside
        # Esc. Both leave `pick` as None, which the caller reads as "launch nothing".
        if event.key in ("escape", "q", "ctrl+c"):
            event.stop()
            self.exit()
            return
        if not self.items:
            return
        # Arrows only, NOT vim j/k: the rows advertise [j] for Jira, and a vim binding
        # silently ate it - a printed hotkey that moved the cursor instead.
        if event.key == "down":
            self.cursor = (self.cursor + 1) % len(self.items)
        elif event.key == "up":
            self.cursor = (self.cursor - 1) % len(self.items)
        elif event.key == "enter":
            event.stop()
            self._choose(*self.items[self.cursor])
            return
        else:
            hot = [i for i, (_p, _l, key) in enumerate(self.actions) if key == event.key]
            if hot:
                event.stop()
                self._choose("act", hot[0])
            return
        event.stop()
        self.paint()

    def _choose(self, kind: str, idx: int) -> None:
        self.pick = ("resume", idx) if kind == "eng" else self.actions[idx][0]
        self.exit()


class RequestApp(TierApp):
    """The request for a NEW engagement.

    Typing is an OFFER, never a toll gate: sending an empty field gives exactly the
    plain launch, so nobody is forced to compose a brief at a prompt. Returns
    (request, auto) in `value`, or None for "launch plainly" - the caller turns that
    into its own sentinel.

    The key map is launcher_app's, deliberately, because each binding there is a
    recorded bug:
      * Enter inserts a LINE BREAK and Ctrl-D sends. Enter used to send, so composing
        across lines - the natural way to write a brief - submitted the first line and
        silently discarded the rest.
      * Ctrl-T arms unattended, not Ctrl-A (the tmux prefix on many setups, which never
        reaches the app) and not a bare letter (every printable key is text here).
      * Paste collapses whitespace instead of dropping unprintables, which used to weld
        sentences into "extract.Then" - worse than truncation, because it looks like
        text the human wrote.
    """

    #: Visible lines of the buffer. Scrolling off the top is normal; hiding what you
    #: are currently typing is not, so the LAST lines are the ones kept.
    LINES = 9

    def __init__(self, project, auto_offered: bool = False, auto: bool = False) -> None:
        super().__init__(project)
        self.buf = ""
        self.auto_offered = bool(auto_offered)
        self.auto = bool(auto) and self.auto_offered
        self.value = None
        self.ran = False

    def on_mount(self) -> None:
        self.ran = True
        self._apply_width()
        self.chrome_ready("new engagement")
        self.paint()

    def paint(self) -> None:
        folder = self.folder()
        self.head(folder if self.narrow else f"{folder}  ·  a new engagement")

        width = self.panel_width()
        t = Text()
        t.append("  What would you like the team to do?\n\n", style=f"bold {HINT}")
        t.append("  Type it. Esc to decide in session instead.\n\n", style=DIM)

        lines = wrap_display(self.buf, max(10, width - 4))
        if len(lines) > self.LINES:
            lines = lines[-self.LINES :]
            lines[0] = "..." + lines[0]
        for i, line in enumerate(lines):
            t.append("  > " if i == 0 else "    ", style=ACCENT if i == 0 else HINT)
            t.append(line, style=TEXT)
            if i == len(lines) - 1:
                t.append("_", style=HINT)  # where the next character lands
            t.append("\n")

        if self.auto_offered:
            t.append("\n")
            t.append("  " + ("●" if self.auto else "○") + " ", style=GOLD if self.auto else DIM)
            t.append("Ctrl-T  run unattended", style=GOLD if self.auto else DIM)
            # Kept SHORT: this row already spends 26 columns on the label, and the full
            # explanation lives in the pane beside it, which has the room for it.
            if self.auto and not self.buf.strip():
                t.append("  (needs a request)", style=GOLD)
            elif self.auto:
                t.append("  (confirm next)", style=DIM)
            else:
                t.append("  (off - it asks)", style=DIM)
            t.append("\n")
        self.query_one("#rows", Static).update(t)

        body = Text("\n")
        body.append("  Starting new work\n\n", style=f"bold {ACCENT}")
        for line in wrap(
            "Whatever you type is handed to Morgan as the request, so the "
            "session starts on the work instead of asking what it is.",
            26,
        ):
            body.append(f"  {line}\n", style=DIM)
        body.append("\n")
        for line in wrap("Leave it empty and nothing changes - you get the plain launch.", 26):
            body.append(f"  {line}\n", style=DIM)
        if self.auto_offered and self.auto:
            body.append("\n")
            for line in wrap("Unattended: you authorise it on the next screen.", 26):
                body.append(f"  {line}\n", style=GOLD)
        self.query_one("#side-body", Static).update(body)

        words = len(self.buf.split())
        note = f"{words} word{'' if words == 1 else 's'}" if words else "nothing typed yet"
        if self.narrow:
            keys = ((" ^d", "send"), ("esc", "back"))
        else:
            keys = (("^d", "send"), ("enter", "new line"), ("esc", "back"), ("^u", "clear"))
        self.foot(keys, note)

    def on_paste(self, event) -> None:
        # A newline is a WORD BREAK, never nothing: the request travels as one line
        # anyway, so collapse here and keep every word.
        text = getattr(event, "text", "") or ""
        self.buf += " ".join(text.split())
        if self.buf and text.endswith(("\n", " ", "\t")):
            self.buf += " "
        event.stop()
        self.paint()

    def on_key(self, event) -> None:
        key = event.key
        if key in ("escape", "ctrl+c"):
            event.stop()
            self.exit()  # value stays None: the plain launch
            return
        if key == "ctrl+d":
            event.stop()
            text = " ".join(self.buf.split())
            self.value = (text, self.auto) if text else None
            self.exit()
            return
        if key == "ctrl+u":
            self.buf = ""
            self.auto = False
        elif key == "ctrl+t":
            # Toggles whether or not there is text yet: arming first and then writing
            # the brief is a natural order, and a guard here made the keypress a SILENT
            # no-op - the worst answer, since the screen then looked as though
            # unattended had been declined. An armed toggle with an empty field still
            # starts nothing; the row says what it needs.
            if self.auto_offered:
                self.auto = not self.auto
        elif key == "enter":
            self.buf += "\n"
        elif key in ("backspace", "ctrl+h"):
            self.buf = self.buf[:-1]  # deletes a newline like any other character
        else:
            ch = getattr(event, "character", None)
            if not ch or not ch.isprintable():
                return  # let anything else through to the bindings
            self.buf += ch
        event.stop()
        self.paint()


class SettingsApp(TierApp):
    """The [c] screen: a live on/off column, toggled in place.

    Drives the SAME `_editor_*` helpers the other tiers use, so precedence, machine
    defaults, the Jira row and 'd' restore cannot diverge - only the drawing differs.
    `changed` says whether anything was written; the caller distinguishes that from
    "could not run", which is a distinction with a history: treating Esc as
    unavailability once dumped people into the numbered editor after they cancelled.
    """

    def __init__(self, project, mod) -> None:
        super().__init__(project)
        self.mod = mod
        self.rows = list(mod._editor_rows(project) or [])
        # Group headings, parallel to `rows` and deliberately NOT part of them: a
        # heading is not selectable, and folding it in would shift every index that the
        # keyboard and _editor_keys agree on.
        self.titles = [t for t, _l, _v, _o in (mod._editor_layout(project) or [])]
        # Inline edit buffer while typing the Jira key, None otherwise. Kept IN the
        # screen: tearing it down to ask one question is the behaviour the [j] flow was
        # corrected for.
        self.editing = None
        self.notes: list[str] = []
        self.changed = False
        self.ran = False

    def on_mount(self) -> None:
        self.ran = True
        self._apply_width()
        self.chrome_ready("settings")
        self.paint()

    # ── state ────────────────────────────────────────────────────────────────
    def _refresh(self) -> None:
        self.rows = list(self.mod._editor_rows(self.project) or self.rows)
        self.titles = [
            t for t, _l, _v, _o in (self.mod._editor_layout(self.project) or [])
        ] or self.titles

    def _note(self, text: str, label: str = "") -> None:
        """Record a "Just changed" line, ONE PER SETTING.

        Toggling a row on and then off appended two lines for the same setting, which
        reads as the display duplicating rather than as two edits. A setting has one
        current state, so it gets one line.
        """
        if label:
            prefix = f"{label}: "
            self.notes = [n for n in self.notes if not n.startswith(prefix)]
        elif text in self.notes:
            self.notes.remove(text)
        self.notes.append(text)

    def _apply(self, action) -> None:
        # Change is detected by COMPARING ROWS, not by whether a note came back:
        # _editor_apply returns '' on a perfectly successful toggle, so a note-based
        # check reported "no change" for every ordinary toggle.
        before = list(self.rows)
        note = ""
        try:
            if action == "d":
                note = self.mod._editor_apply(self.project, "d")
            else:
                # By KEY, not by screen position. This screen is GROUPED, so the
                # highlighted row's index is not the dispatch index - when that was
                # assumed, position 3 showed one setting while the toggle changed
                # another.
                keys = self.mod._editor_keys(self.project)
                if 0 <= action < len(keys):
                    note = self.mod._editor_apply_key(self.project, keys[action])
        except Exception:  # noqa: BLE001 — a failed write must not kill the screen
            note = ""
        self._refresh()
        if list(self.rows) != before:
            self.changed = True
            for (label, value, _on), (_bl, b_value, _b) in zip(self.rows, before):
                if value != b_value:
                    self._note(f"{label}: {b_value} -> {value}", label)
        if note:
            self._note(str(note).strip().lstrip("-> ").strip())

    def _start_editing(self) -> None:
        try:
            self.editing = self.mod.jira_project_key(self.project) or ""
        except Exception:  # noqa: BLE001
            self.editing = ""

    def _is_jira_row(self) -> bool:
        try:
            keys = self.mod._editor_keys(self.project)
            return self.cursor < len(keys) and keys[self.cursor] == self.mod._JIRA_KEY
        except Exception:  # noqa: BLE001
            return False

    # ── drawing ──────────────────────────────────────────────────────────────
    def paint(self) -> None:
        folder = self.folder()
        name = self.project.resolve().name
        self.head(name if self.narrow else f"{folder}  ·  project settings")

        # Padding is CAPPED, not simply the longest label: one long label used to set
        # the column for every row and push the value hard against the divider, so the
        # longest value clipped. Rows past the cap keep one separating space instead.
        width = min(max((len(lbl) for lbl, _v, _o in self.rows), default=0), 24)
        t = Text()
        y, at = 0, 0
        for i, (label, value, on) in enumerate(self.rows):
            title = self.titles[i] if i < len(self.titles) else ""
            if title:
                t.append(("\n" if i else "") + f"  {title}\n", style=f"bold {HINT}")
                y += 2 if i else 1
            sel = self.cursor == i
            if sel:
                at = y
            y += 1
            t.append("  ▸ " if sel else "    ", style=ACCENT if sel else HINT)
            t.append(f"{label.ljust(width + 1)} ", style=f"bold {TEXT}" if sel else TEXT)
            if sel and self.editing is not None:
                t.append(f"{self.editing}█\n", style=ACCENT)
                continue
            t.append("● " if on else "○ ", style=OK if on else DIM)
            # Only the HEAD of the value. The qualifier after a double space
            # ("  (machine default)") is longer than the column has room for and was
            # clipped mid-word; the pane beside it shows the value in full.
            t.append(f"{value.partition('  ')[0]}\n", style=OK if on else DIM)
        self.query_one("#rows", Static).update(t)
        self.scroll_row(at)

        self.query_one("#side-body", Static).update(self._detail())

        if self.editing is not None:
            keys = (("type", "the key"), ("enter", "save"), ("esc", "cancel"))
            note = "editing the Jira project key"
        elif self.narrow:
            keys = (("↑↓", "move"), ("enter", "toggle"), ("esc/q", "back"))
            note = name
        else:
            keys = (
                ("↑↓", "move"),
                ("enter", "toggle"),
                ("e", "edit key"),
                ("d", "defaults"),
                ("esc", "back"),
            )
            note = name
        self.foot(keys, note)

    def _detail(self) -> Text:
        """The highlighted setting explains ITSELF here.

        The pane used to describe the screen's keys, which everyone had worked out by
        the time they read it, while "what does this one DO?" went unanswered.
        """
        body = Text("\n")
        if not self.rows:
            return body
        label, value, on = self.rows[self.cursor]
        w = 26 if not self.narrow else max(20, self.panel_width() - 4)
        body.append(f"  {label}\n\n", style=f"bold {ACCENT}")
        help_text = None
        try:
            help_text = self.mod.setting_help(label)
        except Exception:  # noqa: BLE001
            help_text = None
        if help_text:
            for line in wrap(help_text[0], w):
                body.append(f"  {line}\n", style=TEXT)
            body.append("\n")
            for line in wrap(help_text[1], w):
                body.append(f"  {line}\n", style=DIM)
        else:
            for line in wrap("No description available for this setting yet.", w):
                body.append(f"  {line}\n", style=DIM)
        body.append("\n")
        for line in wrap(f"currently: {value}", w):
            body.append(f"  {line}\n", style=OK if on else DIM)
        if self.notes:
            body.append("\n  Just changed\n", style=f"bold {HINT}")
            for n in self.notes[-4:]:
                for line in wrap(n, w):
                    body.append(f"  {line}\n", style=OK)
        return body

    # ── keys ─────────────────────────────────────────────────────────────────
    def on_key(self, event) -> None:
        key = event.key
        if self.editing is not None:
            event.stop()  # while editing, EVERY key is text or an edit key
            if key == "escape":
                self.editing = None  # cancels the edit, not the screen
            elif key == "enter":
                try:
                    note = self.mod.set_jira_project_key(self.project, self.editing)
                except Exception:  # noqa: BLE001
                    note = ""
                self.editing = None
                self._refresh()
                if note:
                    self.changed = True
                    self._note(str(note))
            elif key in ("backspace", "ctrl+h"):
                self.editing = self.editing[:-1]
            else:
                ch = getattr(event, "character", None)
                # Printable single characters only: control sequences arrive here too,
                # and a stray escape code would be written to the config file.
                if ch and ch.isprintable() and len(self.editing) < 24:
                    self.editing += ch.upper()
            self.paint()
            return

        if key in ("escape", "q", "ctrl+c"):
            # Checked BEFORE the row guard: a screen with no rows still has to be
            # possible to leave. Handled here rather than by a binding because Esc
            # means "cancel the edit" while the Jira key is being typed, and a binding
            # fires even when a handler has already consumed the key.
            event.stop()
            self.exit()
            return
        if not self.rows:
            return
        if key == "down":
            self.cursor = (self.cursor + 1) % len(self.rows)
        elif key == "up":
            self.cursor = (self.cursor - 1) % len(self.rows)
        elif key in ("enter", "space"):
            self._apply(self.cursor)
            # Enabling Jira with no project key is a half-finished action: the screen
            # used to name the gap and leave the fix in a JSON file. Ask now, while the
            # intent is on screen.
            try:
                if self._is_jira_row() and self.mod._jira_needs_key(self.project):
                    self._start_editing()
            except Exception:  # noqa: BLE001
                pass
        elif key == "d":
            self._apply("d")
        elif key == "e":
            # Change an already-set key without toggling Jira off and on again.
            if self._is_jira_row():
                self._start_editing()
        else:
            return
        event.stop()
        self.paint()


class ChooserApp(TierApp):
    """One menu as a full-screen picker - the installer's top-level menu and both of
    its submenus.

    Rows arrive already built as (key, label, blurb, writes) from installer_app's own
    `_rows`, so the labels, the explanations and - most importantly - what each option
    touches OUTSIDE the repo are computed in exactly one place. That last column is the
    reason this screen exists rather than a plain list: someone arrowing quickly past a
    destructive option should not have to read the pane to notice it.

    `picked` is the chosen key, or "" for Esc/q, which the caller reads as back/quit.
    """

    def __init__(self, project, rows: list, title: str, marker_kind) -> None:
        super().__init__(project)
        self.rows = list(rows)
        self.title_text = title or ""
        self._marker_kind = marker_kind
        self.picked = ""
        self.ran = False
        # Its OWN markers, not the on/off pair the other screens use: "·" already means
        # "off" on every launcher row, and reusing it for "this writes outside the repo"
        # would give one symbol two meanings in one product.
        rich = self._can_encode("✎⛔")
        self.mark_writes = "✎" if rich else "*"
        self.mark_deletes = "⛔" if rich else "!"

    @staticmethod
    def _can_encode(text: str) -> bool:
        try:
            text.encode(sys.stderr.encoding or "utf-8")
            return True
        except Exception:  # noqa: BLE001
            return False

    def on_mount(self) -> None:
        self.ran = True
        self._apply_width()
        self.chrome_ready(self.title_text or "menu")
        self.paint()

    def paint(self) -> None:
        folder = self.folder()
        self.head(self.title_text if self.narrow else f"{folder}  ·  {self.title_text}")

        width = min(max((len(lbl) for _k, lbl, _b, _w in self.rows), default=0), 34)
        t = Text()
        for i, (key, label, _blurb, writes) in enumerate(self.rows):
            sel = self.cursor == i
            t.append("  ▸ " if sel else "    ", style=ACCENT if sel else HINT)
            t.append(f"{key:>2}  ", style=KEY)
            t.append(label.ljust(width), style=f"bold {TEXT}" if sel else TEXT)
            kind = self._marker_kind(writes)
            if kind == "deletes":
                t.append(f"  {self.mark_deletes}", style=GOLD)
            elif kind == "writes":
                t.append(f"  {self.mark_writes}", style=DIM)
            t.append("\n")
        self.query_one("#rows", Static).update(t)
        self.scroll_row(self.cursor)  # one line per row, so index IS the line

        w = 26 if not self.narrow else max(20, self.panel_width() - 4)
        body = Text("\n")
        if self.rows:
            _key, label, blurb, writes = self.rows[self.cursor]
            body.append(f"  {label}\n\n", style=f"bold {ACCENT}")
            if blurb:
                for line in wrap(blurb, w):
                    body.append(f"  {line}\n", style=DIM)
                body.append("\n")
            note = writes or "Nothing outside this project."
            style = GOLD if self._marker_kind(writes) == "deletes" else DIM
            for line in wrap(note, w):
                body.append(f"  {line}\n", style=style)
        self.query_one("#side-body", Static).update(body)

        kinds = {self._marker_kind(w_) for _k, _l, _b, w_ in self.rows}
        legend = ""
        if "writes" in kinds:
            legend = f"{self.mark_writes} writes outside this project"
        if "deletes" in kinds:
            legend += f"{' · ' if legend else ''}{self.mark_deletes} deletes"
        keys = (
            (("↑↓", "move"), ("enter", "choose"), ("esc/q", "back"))
            if self.narrow
            else (("↑↓", "move"), ("enter", "choose"), ("esc/q", "back"))
        )
        self.foot(keys, legend)

    def on_key(self, event) -> None:
        key = event.key
        if key in ("escape", "q", "ctrl+c"):
            event.stop()
            self.picked = ""  # a decision - back/quit - not an unavailability
            self.exit()
            return
        if not self.rows:
            return
        if key == "down":
            self.cursor = (self.cursor + 1) % len(self.rows)
        elif key == "up":
            self.cursor = (self.cursor - 1) % len(self.rows)
        elif key == "enter":
            event.stop()
            self.picked = self.rows[self.cursor][0]
            self.exit()
            return
        else:
            # Typing a key JUMPS to it and does not choose it, which is what the
            # prompt_toolkit picker does: muscle memory from the numbered menu still
            # lands you on the right row, and a mistyped key costs a keystroke rather
            # than starting a thirteen-step install.
            ch = getattr(event, "character", None) or ""
            hit = [i for i, r in enumerate(self.rows) if r[0] == ch]
            if not hit:
                return
            self.cursor = hit[0]
        event.stop()
        self.paint()


class SetupApp(TierApp):
    """First-time setup, for a folder the team has never run in.

    THE FIRST SCREEN ANYONE EVER SEES. A brand-new project has no configuration, so this
    is what greets a new user before the menu exists - which is exactly why it being the
    last screen on the old renderer was the wrong way round (2026-08-30).

    `picked` is one of the caller's sentinels, or the cancel sentinel for Esc. Cancel is
    NOT skip: skip launches without configuring, cancel launches nothing at all, and
    folding the two together once meant that backing out of this screen started a session
    anyway.
    """

    def __init__(self, project, rows: list, cancel_value) -> None:
        super().__init__(project)
        self.rows = list(rows)  # (value, label, blurb)
        self._cancel = cancel_value
        self.picked = cancel_value
        self.ran = False

    def on_mount(self) -> None:
        self.ran = True
        self._apply_width()
        self.chrome_ready("Set up this project")
        self.paint()

    def paint(self) -> None:
        folder = self.folder()
        self.head(folder if self.narrow else f"{folder}  ·  Set up this project")

        t = Text()
        t.append("  First-time setup\n\n", style=f"bold {GOLD}")
        t.append("  No team configuration in this folder yet.\n\n", style=DIM)
        for i, (_value, label, blurb) in enumerate(self.rows):
            sel = self.cursor == i
            t.append("  ▸ " if sel else "    ", style=ACCENT if sel else HINT)
            t.append(f"{label}\n", style=f"bold {TEXT}" if sel else TEXT)
            t.append(f"        {blurb}\n\n", style=DIM)
        self.query_one("#rows", Static).update(t)
        # Three rows of three lines each, so the cursor's line is not its index.
        self.scroll_row(self.cursor * 3 + 2)

        w = 26 if not self.narrow else max(20, self.panel_width() - 4)
        body = Text("\n")
        body.append("  What setup does\n\n", style=f"bold {ACCENT}")
        for line in wrap(
            "Writes this project's own team-preferences.json, so the team knows how you "
            "want it to work here.",
            w,
        ):
            body.append(f"  {line}\n", style=DIM)
        body.append("\n")
        for line in wrap(
            "Nothing outside this folder is touched, and every setting can be changed "
            "later from the menu.",
            w,
        ):
            body.append(f"  {line}\n", style=DIM)
        self.query_one("#side-body", Static).update(body)

        self.foot((("↑↓", "move"), ("enter", "choose"), ("esc/q", "back to the shell")))

    def on_key(self, event) -> None:
        key = event.key
        if key in ("escape", "q", "ctrl+c"):
            event.stop()
            self.picked = self._cancel  # leaving is a decision, and it launches nothing
            self.exit()
            return
        if not self.rows:
            return
        if key == "down":
            self.cursor = (self.cursor + 1) % len(self.rows)
        elif key == "up":
            self.cursor = (self.cursor - 1) % len(self.rows)
        elif key == "enter":
            event.stop()
            self.picked = self.rows[self.cursor][0]
            self.exit()
            return
        else:
            return
        self.paint()


class ListApp(TierApp):
    """A list, a detail pane, Enter acts, Esc/q leaves.

    Four screens have that shape and differ only in what a row is and what Enter does, so
    they share this rather than being four near-copies that drift. Subclasses supply
    `row_line`, `detail`, `footer_keys` and `choose`; everything else - cursor, painting,
    scrolling, the way out - is the same by construction.

    `picked` is the subclass's own answer, whatever that means for it. `ran` says the
    screen drew, which the adapters need to tell "the user chose nothing" apart from
    "this tier could not run" - a distinction the launcher has paid for twice.
    """

    def __init__(self, project, rows: list, title: str) -> None:
        super().__init__(project)
        self.rows = list(rows)
        self.title_text = title
        self.picked = None
        self.ran = False

    # -- what a subclass fills in ------------------------------------------------
    def row_line(self, index: int, row, selected: bool) -> Text:
        raise NotImplementedError

    def detail(self, row, width: int) -> Text:
        raise NotImplementedError

    def footer_keys(self):
        return (("↑↓", "move"), ("enter", "choose"), ("esc/q", "back"))

    def choose(self, index: int) -> None:
        """Enter on `index`. Set self.picked; the app exits straight after."""
        self.picked = index

    def lines_per_row(self) -> int:
        return 1

    # -- the shared half ---------------------------------------------------------
    def on_mount(self) -> None:
        self.ran = True
        self._apply_width()
        self.chrome_ready(self.title_text)
        self.paint()

    def paint(self) -> None:
        folder = self.folder()
        self.head(self.title_text if self.narrow else f"{folder}  ·  {self.title_text}")

        body = Text()
        for i, row in enumerate(self.rows):
            body.append(self.row_line(i, row, self.cursor == i))
        self.query_one("#rows", Static).update(body)
        self.scroll_row(self.cursor * self.lines_per_row())

        width = 26 if not self.narrow else max(20, self.panel_width() - 4)
        side = self.detail(self.rows[self.cursor] if self.rows else None, width)
        self.query_one("#side-body", Static).update(side)
        self.foot(self.footer_keys())

    def on_key(self, event) -> None:
        key = event.key
        if key in ("escape", "q", "ctrl+c"):
            event.stop()
            self.picked = None  # leaving is an answer, and it is "nothing chosen"
            self.exit()
            return
        if not self.rows:
            return
        if key == "down":
            self.cursor = (self.cursor + 1) % len(self.rows)
        elif key == "up":
            self.cursor = (self.cursor - 1) % len(self.rows)
        elif key == "enter":
            event.stop()
            self.choose(self.cursor)
            self.exit()
            return
        else:
            return
        self.paint()


class ArchiveApp(ListApp):
    """Pick one engagement to archive, or all of them.

    The last row is "archive ALL", which is why the row list is the views PLUS one: the
    consequence of that row is different in kind from the others, so it is stated on the
    row itself rather than only in the pane.
    """

    def __init__(self, project, views: list, open_count: int) -> None:
        super().__init__(project, list(views) + [None], "Archive engagements")
        self.open_count = open_count

    def lines_per_row(self) -> int:
        return 2

    def row_line(self, index: int, row, selected: bool) -> Text:
        t = Text()
        t.append("  ▸ " if selected else "    ", style=ACCENT if selected else HINT)
        if row is None:
            t.append(
                f"archive ALL open engagements ({self.open_count})\n",
                style=f"bold {GOLD}" if selected else GOLD,
            )
            t.append("\n")
            return t
        t.append(f"{row['mark']} ", style=GOLD if row["mark_style"] == "warn" else DIM)
        t.append(f"{row['title']}\n", style=f"bold {TEXT}" if selected else TEXT)
        t.append(f"      {row['slug']}  {row['detail']}\n", style=DIM)
        return t

    def detail(self, row, width: int) -> Text:
        t = Text("\n")
        t.append("  Archiving\n\n", style=f"bold {ACCENT}")
        for line in wrap(
            "In place - nothing is deleted. A marker excludes the pack from every scanner.", width
        ):
            t.append(f"  {line}\n", style=DIM)
        t.append("\n")
        for line in wrap(
            "An OPEN pack archives with --force and shows as ARCHIVED-OPEN in checks.", width
        ):
            t.append(f"  {line}\n", style=GOLD)
        return t

    def footer_keys(self):
        return (("↑↓", "move"), ("enter", "archive"), ("esc/q", "back"))


class FinishedApp(ListApp):
    """Done and archived engagements. Enter opens one, r redoes it, s signs it off.

    s ACTS IN PLACE and does not leave: signing off is something you do to a row while
    looking at the list, and the row's own state changes under the cursor so you can see
    it took. Making it exit would match the other two keys and be wrong - the
    prompt_toolkit screen has always behaved this way, and a port that quietly changed it
    would be a regression nobody would think to test for.

    Behaviour is injected rather than reached for: `sign_off(slug)` and `signed(slug)` are
    passed in, so this file keeps knowing only how to draw.
    """

    def __init__(self, project, views: list, slugs: list, sign_off, signed) -> None:
        super().__init__(project, views, "Done & archived")
        self.slugs = list(slugs)
        self._sign_off = sign_off
        self._signed = signed
        self.note = ""
        self.picked = ""  # "" is this screen's cancel, not None

    def row_line(self, index: int, row, selected: bool) -> Text:
        t = Text()
        t.append("  ▸ " if selected else "    ", style=ACCENT if selected else HINT)
        t.append(f"{row.get('mark', '')} ", style=DIM)
        t.append(f"{row.get('title', '')}\n", style=f"bold {TEXT}" if selected else TEXT)
        who = self._signed(self.slugs[index]) if index < len(self.slugs) else ""
        t.append("      signed off\n" if who else "      unsigned\n", style=OK if who else GOLD)
        return t

    def lines_per_row(self) -> int:
        return 2

    def detail(self, row, width: int) -> Text:
        t = Text("\n")
        if not row:
            return t
        t.append(f"  {row.get('title', '')}\n\n", style=f"bold {ACCENT}")
        for key in ("slug", "detail"):
            value = row.get(key)
            if value:
                for line in wrap(str(value), width):
                    t.append(f"  {line}\n", style=DIM)
        if self.note:
            t.append("\n")
            for line in wrap(self.note, width):
                t.append(f"  {line}\n", style=OK)
        return t

    def footer_keys(self):
        return (
            ("↑↓", "move"),
            ("enter", "open"),
            ("s", "sign off"),
            ("r", "redo"),
            ("esc/q", "back"),
        )

    def choose(self, index: int) -> None:
        self.picked = self.slugs[index] if index < len(self.slugs) else ""

    def on_key(self, event) -> None:
        key = event.key
        slug = self.slugs[self.cursor] if self.cursor < len(self.slugs) else ""
        if key == "s" and slug:
            # Recorded HERE, by the human at the keyboard - never by a session. An agent
            # signing off its own work is what the Definition-of-Done gate exists to
            # prevent, so the signature is taken where a person demonstrably is.
            event.stop()
            try:
                self.note = self._sign_off(slug) or ""
            except Exception:  # noqa: BLE001 - a failed sign-off is not a crash
                self.note = ""
            self.paint()
            return
        if key == "r" and slug:
            event.stop()
            self.picked = ("supersede", slug)
            self.exit()
            return
        if key in ("escape", "q", "ctrl+c"):
            event.stop()
            self.picked = ""  # this screen's cancel is "", not None
            self.exit()
            return
        super().on_key(event)


class ArtifactsApp(ListApp):
    """What an engagement produced. Enter opens the highlighted file."""

    def row_line(self, index: int, row, selected: bool) -> Text:
        t = Text()
        t.append("  ▸ " if selected else "    ", style=ACCENT if selected else HINT)
        t.append(f"{row}\n", style=f"bold {TEXT}" if selected else TEXT)
        return t

    def detail(self, row, width: int) -> Text:
        t = Text("\n")
        t.append("  Artifacts\n\n", style=f"bold {ACCENT}")
        for line in wrap(
            "Everything this engagement produced. Enter opens the highlighted "
            "file with your system viewer.",
            width,
        ):
            t.append(f"  {line}\n", style=DIM)
        return t

    def footer_keys(self):
        return (("↑↓", "move"), ("enter", "open"), ("esc/q", "back"))


class SlugPickerApp(ListApp):
    """Pick one open engagement, when several are open and the action needs just one."""

    def row_line(self, index: int, row, selected: bool) -> Text:
        t = Text()
        t.append("  ▸ " if selected else "    ", style=ACCENT if selected else HINT)
        t.append(
            f"{row.get('title', row.get('slug', ''))}\n", style=f"bold {TEXT}" if selected else TEXT
        )
        t.append(f"      {row.get('slug', '')}  {row.get('detail', '')}\n", style=DIM)
        return t

    def lines_per_row(self) -> int:
        return 2

    def detail(self, row, width: int) -> Text:
        t = Text("\n")
        t.append("  Which engagement?\n\n", style=f"bold {ACCENT}")
        for line in wrap(
            "Several are open, and this action works on one. Pick the one you mean.", width
        ):
            t.append(f"  {line}\n", style=DIM)
        return t


class BrowseApp(TierApp):
    """Choose a project folder.

    Rows are rebuilt on every move because the list IS the current directory: "use this
    folder", "up", the recent projects, then the children. A row therefore carries what
    it means - use / up / recent / dir - rather than the caller inferring it from the
    index, which would break the moment the row order changed.

    `picked` is the chosen Path, or None for cancel.
    """

    def __init__(self, project, start, rows_for, recents: list) -> None:
        super().__init__(
            project,
        )
        self.here = start
        self._rows_for = rows_for  # (directory) -> [(label, kind, payload)]
        self.recents = list(recents)
        self.rows = self._rows_for(self.here)
        self.picked = None
        self.ran = False

    def on_mount(self) -> None:
        self.ran = True
        self._apply_width()
        self.chrome_ready("Choose a project folder")
        self.paint()

    def _reload(self, new_dir) -> None:
        self.here = new_dir
        self.rows = self._rows_for(new_dir)
        self.cursor = 0

    def paint(self) -> None:
        self.head(str(self.here) if self.narrow else f"{self.here}")
        t = Text()
        for i, (label, kind, _payload) in enumerate(self.rows):
            sel = self.cursor == i
            t.append("  ▸ " if sel else "    ", style=ACCENT if sel else HINT)
            style = f"bold {TEXT}" if sel else (GOLD if kind in ("use", "recent") else TEXT)
            t.append(f"{label}\n", style=style)
        self.query_one("#rows", Static).update(t)
        self.scroll_row(self.cursor)

        width = 26 if not self.narrow else max(20, self.panel_width() - 4)
        side = Text("\n")
        side.append("  Where to work\n\n", style=f"bold {ACCENT}")
        for line in wrap(
            "Enter opens a folder. The first row uses the folder you are in. "
            "Recent projects jump straight there.",
            width,
        ):
            side.append(f"  {line}\n", style=DIM)
        self.query_one("#side-body", Static).update(side)
        self.foot((("↑↓", "move"), ("enter", "open"), ("bksp", "up"), ("esc/q", "cancel")))

    def on_key(self, event) -> None:
        key = event.key
        if key in ("escape", "q", "ctrl+c"):
            event.stop()
            self.picked = None
            self.exit()
            return
        if key in ("backspace", "left"):
            event.stop()
            if self.here.parent != self.here:
                self._reload(self.here.parent)
                self.paint()
            return
        if not self.rows:
            return
        if key == "down":
            self.cursor = (self.cursor + 1) % len(self.rows)
        elif key == "up":
            self.cursor = (self.cursor - 1) % len(self.rows)
        elif key == "enter":
            event.stop()
            _label, kind, payload = self.rows[self.cursor]
            if kind == "use":
                self.picked = self.here
                self.exit()
                return
            if kind == "up":
                if self.here.parent != self.here:
                    self._reload(self.here.parent)
                self.paint()
                return
            if kind == "recent":
                # A recent entry is a DESTINATION, not a place to browse into: you picked
                # it because you already know it is the project you want.
                self.picked = payload
                self.exit()
                return
            self._reload(payload[0])
            self.paint()
            return
        else:
            return
        self.paint()


class PreflightApp(TierApp):
    """The single authorisation gate for an unattended run.

    ENTER TOGGLES, IT DOES NOT COMMIT. On this screen of all screens the most reflexive
    key on the keyboard must not be the one that arms an unattended run, so Enter does the
    harmless thing people expect - it acts on the highlighted row - and committing is
    Ctrl-D, the same send key the request composer uses. Preserved deliberately from the
    prompt_toolkit screen (owner, 2026-08-25: "enter is too easy to press... user may
    press enter thinking it toggles options").

    `confirmed` says whether Ctrl-D was pressed; the caller reads the answers off `state`.
    """

    def __init__(self, project, rows: list, state: dict, value_of, caps, on_budget, modes) -> None:
        super().__init__(project)
        self.rows = list(rows)
        self.state = state
        self._value_of = value_of
        self._caps = caps
        self._on_budget = on_budget
        self._modes = modes
        self.confirmed = False
        self.ran = False

    def on_mount(self) -> None:
        self.ran = True
        self._apply_width()
        self.chrome_ready("Authorise this run")
        self.paint()

    def paint(self) -> None:
        self.head("Auto mode" if self.narrow else f"{self.folder()}  ·  Auto mode")
        t = Text()
        for i, (key, kind, label, _hint) in enumerate(self.rows):
            sel = self.cursor == i
            t.append("  ▸ " if sel else "    ", style=ACCENT if sel else HINT)
            if kind == "toggle":
                on = bool(self.state[key])
                t.append("✓ " if on else "· ", style=OK if on else DIM)
            else:
                t.append("• ", style=KEY)
            t.append(f"{label}", style=f"bold {TEXT}" if sel else TEXT)
            if kind != "toggle":
                t.append(f"   {self._value_of(key)}", style=GOLD)
            t.append("\n")
        self.query_one("#rows", Static).update(t)
        self.scroll_row(self.cursor)

        width = 26 if not self.narrow else max(20, self.panel_width() - 4)
        side = Text("\n")
        key, _kind, label, hint = self.rows[self.cursor]
        side.append(f"  {label}\n\n", style=f"bold {ACCENT}")
        for line in wrap(hint, width):
            side.append(f"  {line}\n", style=DIM)
        self.query_one("#side-body", Static).update(side)
        self.foot(
            (("↑↓", "move"), ("space/enter", "change"), ("^d", "START"), ("esc/q", "cancel")),
            "nothing starts until Ctrl-D",
        )

    def on_key(self, event) -> None:
        key = event.key
        if key in ("escape", "q", "ctrl+c"):
            event.stop()
            self.confirmed = False
            self.exit()
            return
        if key == "ctrl+d":
            event.stop()
            self.confirmed = True
            self.exit()
            return
        if key == "down":
            self.cursor = (self.cursor + 1) % len(self.rows)
        elif key == "up":
            self.cursor = (self.cursor - 1) % len(self.rows)
        elif key in ("enter", "space"):
            event.stop()
            name, kind = self.rows[self.cursor][0], self.rows[self.cursor][1]
            if kind == "toggle":
                self.state[name] = not self.state[name]
            elif name == "cap":
                self.state["cap"] = (self.state["cap"] + 1) % len(self._caps)
            elif name == "mode":
                self.state["mode"] = (self.state["mode"] + 1) % len(self._modes)
            else:
                self.state["on_budget"] = (self.state["on_budget"] + 1) % len(self._on_budget)
        else:
            return
        self.paint()


class JiraApp(TierApp):
    """Start an engagement from a ticket.

    A composer like RequestApp, with one deliberate difference: ENTER SUBMITS here. The
    request composer treats Enter as a newline because a brief is prose that wants
    paragraphs; a ticket reference is one short token, so the key that ends a line is the
    key that finishes. Kept as it was rather than harmonised - the two screens differ
    because what they collect differs.

    `value` is the ref, or (ref, True) when unattended was armed, or None for cancel.
    """

    def __init__(self, project, auto_offered: bool = False, key_of=None) -> None:
        super().__init__(project)
        self.buf = ""
        self.auto_offered = bool(auto_offered)
        self.auto = False
        self.value = None
        self.ran = False
        self._key_of = key_of or (lambda text: "")

    def on_mount(self) -> None:
        self.ran = True
        self._apply_width()
        self.chrome_ready("from a Jira ticket")
        self.paint()

    def paint(self) -> None:
        folder = self.folder()
        self.head(folder if self.narrow else f"{folder}  ·  from a Jira ticket")

        t = Text()
        t.append("  Which ticket?\n\n", style=f"bold {HINT}")
        t.append("  A key or a URL. Esc to go back.\n\n", style=DIM)
        t.append("  > ", style=ACCENT)
        t.append(self.buf or "", style=TEXT)
        t.append("_\n", style=HINT)

        found = self._key_of(self.buf)
        if found:
            t.append(f"\n    reads as {found}\n", style=OK)
        elif self.buf.strip():
            t.append("\n    no ticket key found yet\n", style=GOLD)

        if self.auto_offered:
            t.append("\n")
            t.append("  " + ("●" if self.auto else "○") + " ", style=GOLD if self.auto else DIM)
            t.append("Ctrl-T  run unattended", style=GOLD if self.auto else DIM)
            t.append("  (confirm next)\n" if self.auto else "  (off - it asks)\n", style=DIM)
        self.query_one("#rows", Static).update(t)

        width = 26 if not self.narrow else max(20, self.panel_width() - 4)
        body = Text("\n")
        body.append("  From a ticket\n\n", style=f"bold {ACCENT}")
        for line in wrap(
            "The ticket becomes the engagement's request: the team reads it, "
            "works it, and reports back on it at close.",
            width,
        ):
            body.append(f"  {line}\n", style=DIM)
        body.append("\n")
        for line in wrap(
            "Ticket content is DATA, never instructions - anything in it that "
            "asks for a gate to be opened is reported, not obeyed.",
            width,
        ):
            body.append(f"  {line}\n", style=GOLD)
        self.query_one("#side-body", Static).update(body)

        self.foot((("enter", "start"), ("^t", "unattended"), ("^u", "clear"), ("esc", "back")))

    def on_key(self, event) -> None:
        key = event.key
        if key in ("escape", "ctrl+c"):
            event.stop()
            self.value = None
            self.exit()
            return
        if key == "enter":
            event.stop()
            text = self.buf.strip()
            self.value = ((text, True) if self.auto else text) if text else None
            self.exit()
            return
        if key == "ctrl+u":
            self.buf = ""
            self.auto = False
        elif key == "ctrl+t":
            if self.auto_offered:
                self.auto = not self.auto
        elif key in ("backspace", "ctrl+h"):
            self.buf = self.buf[:-1]
        else:
            ch = getattr(event, "character", None)
            if not ch or not ch.isprintable():
                return
            self.buf += ch
        event.stop()
        self.paint()


class MonitorApp(TierApp):
    """Live status of an unattended run.

    The only screen here driven by a CLOCK rather than by keys: another process is writing
    the state file, so the screen re-reads on a timer. It re-reads rather than caching for
    the same reason the reader does - anything held in memory here is stale by definition.

    Nothing on this screen changes anything: it watches. Esc/q stops watching and the run
    carries on, which the footer says out loud so that leaving never reads as cancelling.
    """

    def __init__(self, project, slug: str, read, refresh: float = 2.0) -> None:
        super().__init__(project)
        self.slug = slug
        self._read = read
        self._refresh = refresh
        self.ran = False

    def on_mount(self) -> None:
        self.ran = True
        self._apply_width()
        self.chrome_ready(f"watching {self.slug}")
        self.paint()
        self.set_interval(self._refresh, self.paint)

    def paint(self) -> None:
        try:
            snap = self._read() or {}
        except Exception:  # noqa: BLE001 - a failed read is a state, not a crash
            snap = {}
        self.head(self.slug if self.narrow else f"{self.folder()}  ·  watching {self.slug}")

        t = Text()
        status = str(snap.get("status") or "unknown")
        t.append("  status  ", style=DIM)
        t.append(f"{status}\n\n", style=OK if status in ("closed", "done") else GOLD)
        for label in ("phase", "elapsed", "spend", "artifacts", "outstanding"):
            value = snap.get(label)
            if value not in (None, "", []):
                t.append(f"  {label:<12}", style=DIM)
                t.append(f"{value}\n", style=TEXT)
        note = snap.get("note") or snap.get("last_note")
        if note:
            t.append("\n")
            for line in wrap(str(note), max(20, self.panel_width() - 4)):
                t.append(f"  {line}\n", style=DIM)
        self.query_one("#rows", Static).update(t)

        width = 26 if not self.narrow else max(20, self.panel_width() - 4)
        body = Text("\n")
        body.append("  Watching\n\n", style=f"bold {ACCENT}")
        for line in wrap(
            "Another process is doing the work; this reads its state file every "
            f"{self._refresh:g} seconds.",
            width,
        ):
            body.append(f"  {line}\n", style=DIM)
        body.append("\n")
        for line in wrap("Leaving stops the watching, not the run.", width):
            body.append(f"  {line}\n", style=GOLD)
        self.query_one("#side-body", Static).update(body)

        self.foot(
            (("r", "refresh now"), ("esc/q", "stop watching")), "the run continues either way"
        )

    def on_key(self, event) -> None:
        key = event.key
        if key in ("escape", "q", "ctrl+c"):
            event.stop()
            self.exit()
            return
        if key == "r":
            event.stop()
            self.paint()


class DecisionApp(TierApp):
    """A short question with a fixed set of answers and the facts beside it.

    The update screen is the case it was written for: what you are on, what is coming,
    whether your clone is dirty - all visible at once, then one answer. `picked` is the
    chosen key, or the caller's cancel value.
    """

    def __init__(self, project, options: list, facts, detail, title: str, cancel="cancel") -> None:
        super().__init__(project)
        self.options = list(options)  # [(key, label)]
        self._facts = facts  # () -> Text, drawn above the options
        self._detail = detail  # (width) -> Text for the side pane
        self.title_text = title
        self._cancel = cancel
        self.picked = cancel
        self.ran = False

    def on_mount(self) -> None:
        self.ran = True
        self._apply_width()
        self.chrome_ready(self.title_text)
        self.paint()

    def paint(self) -> None:
        self.head(self.title_text if self.narrow else f"{self.folder()}  ·  {self.title_text}")
        t = Text()
        t.append(self._facts())
        t.append("\n")
        for i, (_key, label) in enumerate(self.options):
            sel = self.cursor == i
            t.append("  ▸ " if sel else "    ", style=ACCENT if sel else HINT)
            t.append(f"{label}\n", style=f"bold {TEXT}" if sel else TEXT)
        self.query_one("#rows", Static).update(t)

        width = 26 if not self.narrow else max(20, self.panel_width() - 4)
        self.query_one("#side-body", Static).update(self._detail(width))
        self.foot((("↑↓", "move"), ("enter", "choose"), ("esc/q", "cancel")))

    def on_key(self, event) -> None:
        key = event.key
        if key in ("escape", "q", "ctrl+c"):
            event.stop()
            self.picked = self._cancel
            self.exit()
            return
        if not self.options:
            return
        if key == "down":
            self.cursor = (self.cursor + 1) % len(self.options)
        elif key == "up":
            self.cursor = (self.cursor - 1) % len(self.options)
        elif key == "enter":
            event.stop()
            self.picked = self.options[self.cursor][0]
            self.exit()
            return
        else:
            return
        self.paint()


class ProgressApp(TierApp):
    """Work happening, watched.

    Rows move pending -> running -> their result while a WORKER THREAD does the work: a
    blocking subprocess on the main thread would freeze the frame it is meant to be
    animating. The shared state is only ever assigned wholesale, never edited in place, so
    a torn read shows for at most one frame.

    Closing is only possible once the work has finished - closing mid-run would leave the
    installer writing into a screen that no longer exists, and the user with no idea
    whether their plugin was half-updated.
    """

    def __init__(self, project, state, title: str, refresh: float = 0.15) -> None:
        super().__init__(project)
        self.state = state
        self.title_text = title
        self._refresh = refresh
        self.ran = False

    def on_mount(self) -> None:
        self.ran = True
        self._apply_width()
        self.chrome_ready(self.title_text)
        self.paint()
        self.set_interval(self._refresh, self.paint)

    def paint(self) -> None:
        self.head(self.title_text if self.narrow else f"{self.folder()}  ·  {self.title_text}")
        marks = {
            "pending": ("·", DIM),
            "running": ("▸", ACCENT),
            "ok": ("✓", OK),
            "skip": ("~", GOLD),
            "fail": ("✗", GOLD),
        }
        t = Text()
        for row_title, status, detail in self.state.rows:
            mark, style = marks.get(status, marks["pending"])
            t.append(f"  {mark} ", style=style)
            t.append(row_title, style=f"bold {TEXT}" if status == "running" else TEXT)
            if detail and status != "running":
                t.append(f"  ({detail[:36]})", style=DIM)
            t.append("\n")
        self.query_one("#rows", Static).update(t)

        width = 26 if not self.narrow else max(20, self.panel_width() - 4)
        body = Text("\n")
        body.append("  Output\n\n", style=f"bold {ACCENT}")
        for line in self.state.lines[-12:]:
            for wrapped in wrap(line, width):
                body.append(f"  {wrapped}\n", style=DIM)
        self.query_one("#side-body", Static).update(body)

        if self.state.done:
            ok = self.state.code == 0
            self.foot(
                (("enter", "close"),),
                "done" if ok else f"finished with errors (exit {self.state.code})",
                warn=not ok,
            )
        else:
            self.foot((("^c", "stop"),), "working...")

    def on_key(self, event) -> None:
        if not self.state.done:
            return  # nothing leaves while the installer is mid-write
        if event.key in ("enter", "escape", "q", "ctrl+c"):
            event.stop()
            self.exit()


class GridApp(TierApp):
    """A settings grid: every value visible at once, Enter changes the highlighted row.

    Rows arrive as (group, label, value, on, key) and are dispatched BY KEY, never by
    position - this repo has shipped positional dispatch twice and both times every test
    passed while the wrong setting changed.
    """

    def __init__(self, project, rows_fn, apply_fn, help_fn, title: str) -> None:
        super().__init__(project)
        self._rows_fn = rows_fn
        self._apply = apply_fn
        self._help = help_fn
        self.title_text = title
        self.rows = list(rows_fn() or [])
        self.changed = False
        self.notes: list = []
        self.ran = False

    def on_mount(self) -> None:
        self.ran = True
        self._apply_width()
        self.chrome_ready(self.title_text)
        self.paint()

    def paint(self) -> None:
        self.head(self.title_text if self.narrow else f"{self.folder()}  ·  {self.title_text}")
        width = min(max((len(r[1]) for r in self.rows), default=0), 28)
        t = Text()
        for i, (group, label, value, on, _key) in enumerate(self.rows):
            if group:
                t.append(("\n" if i else "") + f"  {group}\n", style=f"bold {GOLD}")
            sel = self.cursor == i
            t.append("  ▸ " if sel else "    ", style=ACCENT if sel else HINT)
            t.append(f"{label.ljust(width + 1)} ", style=f"bold {TEXT}" if sel else TEXT)
            t.append(f"{'✓' if on else '·'} {value}\n", style=OK if on else DIM)
        self.query_one("#rows", Static).update(t)

        w = 26 if not self.narrow else max(20, self.panel_width() - 4)
        body = Text("\n")
        if self.rows:
            _group, label, value, on, key = self.rows[self.cursor]
            body.append(f"  {label}\n\n", style=f"bold {ACCENT}")
            for line in wrap(self._help(key) or "No description yet.", w):
                body.append(f"  {line}\n", style=DIM)
            body.append("\n")
            for line in wrap(f"currently: {value}", w):
                body.append(f"  {line}\n", style=OK if on else DIM)
        if self.notes:
            body.append("\n  Just changed\n", style=f"bold {GOLD}")
            for note in self.notes[-4:]:
                for line in wrap(note, w):
                    body.append(f"  {line}\n", style=OK)
        self.query_one("#side-body", Static).update(body)
        self.foot((("↑↓", "move"), ("enter", "change"), ("esc/q", "done")))

    def on_key(self, event) -> None:
        key = event.key
        if key in ("escape", "q", "ctrl+c"):
            event.stop()
            self.exit()
            return
        if not self.rows:
            return
        if key == "down":
            self.cursor = (self.cursor + 1) % len(self.rows)
        elif key == "up":
            self.cursor = (self.cursor - 1) % len(self.rows)
        elif key in ("enter", "space"):
            event.stop()
            before = list(self.rows)
            note = ""
            try:
                note = self._apply(self.rows[self.cursor][4]) or ""
            except Exception:  # noqa: BLE001 - a failed write is not a crash
                note = ""
            self.rows = list(self._rows_fn() or self.rows)
            if list(self.rows) != before:
                self.changed = True
                for (_g, label, value, _o, _k), (_bg, _bl, was, _bo, _bk) in zip(self.rows, before):
                    if value != was:
                        # ONE line per setting: toggling twice used to append two, which
                        # reads as the panel duplicating rather than as two edits.
                        prefix = f"{label}: "
                        self.notes = [n for n in self.notes if not n.startswith(prefix)]
                        self.notes.append(f"{label}: {was} -> {value}")
            if note:
                self.notes.append(note.strip())
        else:
            return
        self.paint()
