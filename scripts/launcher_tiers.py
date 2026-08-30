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

    def render_frame(self, pct: float, subtitle: str, narrow: bool = False) -> None:
        eye = OK if pct >= 1.0 else ACCENT
        # A fixed rule per width class, not a measured one. content_size is 0 on the
        # first paint and self.size is the screen, so both overflowed the shell's
        # padding and wrapped the rule onto its own line. It is decoration - the
        # subtitle beside it carries the information - so a value that always fits
        # beats one that is occasionally exact.
        rule = 34 if narrow else 52
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
    BINDINGS = [("q", "app.quit", "quit"), ("escape", "app.quit", "back")]

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

    def on_resize(self, event) -> None:
        # The class goes on the SCREEN, not the app: the stylesheet selects
        # `Screen.-narrow #side`, so setting it on the app node matched nothing and the
        # detail pane stayed put at phone width - squeezing the list until rows fell off
        # the bottom, which is exactly what the breakpoint exists to prevent.
        narrow = event.size.width < NARROW
        self._narrow = narrow
        try:
            self.screen.set_class(narrow, "-narrow")
        except Exception:               # noqa: BLE001 — cosmetic only
            pass
        painter = getattr(self, "paint", None)
        if callable(painter):
            painter()

    @property
    def narrow(self) -> bool:
        return bool(getattr(self, "_narrow", False))

    def folder(self) -> str:
        """The folder being read, shortened but never guessed at."""
        try:
            return "~/" + str(self.project.resolve().relative_to(Path.home()))
        except (ValueError, OSError):
            return str(self.project)

    def head(self, subtitle: str) -> None:
        self.query_one("#brand", Brand).render_frame(0.0, subtitle, self.narrow)

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
        self.items = ([("eng", i) for i in range(len(self.views))]
                      + [("act", i) for i in range(len(self.actions))])

    def on_mount(self) -> None:
        self.ran = True
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
