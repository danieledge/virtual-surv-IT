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

    def render_frame(self, pct: float, subtitle: str, narrow: bool = False,
                     width: int = 0) -> None:
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
        t.append("VIRT-SURV\n", style=f"bold {ACCENT}")
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
    # Esc ONLY. `q` is a quit key on a list and a letter on anything that takes text,
    # and Textual MERGES BINDINGS up the MRO - so a subclass cannot take it away, and
    # a `q` here silently ended the composer instead of typing (caught under a pty).
    # Screens that want it add it themselves.
    BINDINGS = [("escape", "app.quit", "back")]

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
                if exc is not None else "virt-surv stopped unexpectedly.")
        except Exception:               # noqa: BLE001 — reporting must never re-raise
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
        except Exception:               # noqa: BLE001 — cosmetic only
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
        if self.narrow:                 # shell pad 1, border 1, pad 1, each side
            return max(20, w - 6)
        return max(20, w - 46)          # ... plus the 32-wide side pane and its margin

    def folder(self) -> str:
        """The folder being read, shortened but never guessed at."""
        try:
            return "~/" + str(self.project.resolve().relative_to(Path.home()))
        except (ValueError, OSError):
            return str(self.project)

    def head(self, subtitle: str) -> None:
        self.query_one("#brand", Brand).render_frame(
            0.0, subtitle, self.narrow, getattr(self.size, "width", 0) or 0)

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

    #: A list has no text to type into, so `q` can be a second way out of it.
    BINDINGS = [("q", "app.quit", "quit")]

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
        self.items = ([("eng", i) for i in range(len(self.views))]
                      + [("act", i) for i in range(len(self.actions))])

    def on_mount(self) -> None:
        self.ran = True
        self._apply_width()             # before the first paint, not after a resize
        n = len(self.views)
        self.query_one("#panel").border_title = f"{n} open" if n else "nothing open"
        self.query_one("#side").border_title = "detail"
        self.paint()

    def paint(self) -> None:
        folder = self.folder()
        self.head(folder if self.narrow
                  else f"{folder}  ·  engagements in this folder")

        t = Text()
        if self.views:
            t.append("  Resume an engagement\n", style=f"bold {HINT}")
            for i, v in enumerate(self.views):
                self._row(t, ("eng", i), v.get("title") or "?",
                          mark=v.get("mark") or "•",
                          warn=v.get("mark_style") == "warn",
                          tag="← most recent" if v.get("recommended") else "")
        else:
            # Which FOLDER, because "no open engagements" alone reads as a statement
            # about the product rather than about where you are standing.
            archived = self.menu.get("archived") or 0
            t.append(f"  no open engagements here"
                     f"{f' ({archived} archived)' if archived else ''}\n", style=HINT)

        t.append("\n  Start something new\n", style=f"bold {HINT}")
        seen_or = False
        for i, (pick, label, key) in enumerate(self.actions):
            # "Or" before the non-new actions, because without it "change a project
            # setting" read as though it were an engagement.
            if pick[0] not in ("new", "jira") and not seen_or:
                t.append("\n  Or\n", style=f"bold {HINT}")
                seen_or = True
            self._row(t, ("act", i), label, key=key)
        self.query_one("#rows", Static).update(t)

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

        self.foot((("↑↓", "move"), ("enter", "choose"), ("esc", "back to terminal")),
                  f"{len(self.views)} open in {folder}")

    def _row(self, t: Text, item, label: str, mark: str = "", warn: bool = False,
             tag: str = "", key=None) -> None:
        sel = self.items[self.cursor] == item if self.items else False
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
        self.query_one("#panel").border_title = "new engagement"
        self.query_one("#side").border_title = "detail"
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
            lines = lines[-self.LINES:]
            lines[0] = "..." + lines[0]
        for i, line in enumerate(lines):
            t.append("  > " if i == 0 else "    ", style=ACCENT if i == 0 else HINT)
            t.append(line, style=TEXT)
            if i == len(lines) - 1:
                t.append("_", style=HINT)      # where the next character lands
            t.append("\n")

        if self.auto_offered:
            t.append("\n")
            t.append("  " + ("●" if self.auto else "○") + " ",
                     style=GOLD if self.auto else DIM)
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
        for line in wrap("Whatever you type is handed to Morgan as the request, so the "
                         "session starts on the work instead of asking what it is.", 26):
            body.append(f"  {line}\n", style=DIM)
        body.append("\n")
        for line in wrap("Leave it empty and nothing changes - you get the plain "
                         "launch.", 26):
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
            keys = (("^d", "send"), ("enter", "new line"), ("esc", "back"),
                    ("^u", "clear"))
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
            self.buf = self.buf[:-1]    # deletes a newline like any other character
        else:
            ch = getattr(event, "character", None)
            if not ch or not ch.isprintable():
                return                  # let anything else through to the bindings
            self.buf += ch
        event.stop()
        self.paint()
