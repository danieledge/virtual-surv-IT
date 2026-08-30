#!/usr/bin/env python3
"""virt-surv2 — the Textual front end: screens and widgets.

Presentation only. No install logic, no network, nothing written. The engine stays
`install_helper.py` — every Windows fix in it (claude-CLI discovery, the PATH-shim
fallback, `windows_shim_cmdline`, cp1252 handling) is kept as-is and this becomes an
implementation of its `observer` protocol.

Two screens:

    DECIDE   every decision up front, defaults pre-filled, skimmable
    INSTALL  runs all 14 steps uninterrupted

Today those are interleaved: the engine stops to ask at steps 2, 3, 4, 7, 8, 12, 13
and 14, so an install can never run unattended, and the "use recommended defaults for
all of these?" fast path is not offered until step 7 — after the user has already
answered steps 2, 3 and 4.

Assumes a modern VT terminal (Windows Terminal on Win11, VS Code, iTerm2, ...).
There is deliberately no 16-colour or ASCII degradation — see design/tokens.md.

Flags:
    (none)          the decide screen, then the animated install
    --install       jump straight to the install screen
    --frozen        hold the reference frame
    --done          the completed state
    --shot OUT.svg  export a frame to SVG
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Input, Static

# ── tokens ────────────────────────────────────────────────────────────────────
ACCENT = "#d97757"
GOLD = "#c9a227"
OK = "#3fb950"
ERR = "#f85149"
KEY = "#7aa2f7"
TEXT = "#e6e6e6"
DIM = "#8a8f98"
HINT = "#6b7280"
TRACK = "#2a2a31"
# The mouth needs a lighter track than the row bars: at 0% an unlit mouth on
# #2a2a31 disappears and the robot reads as faceless.
MOUTH = "#3d3d47"

EIGHTHS = " ▏▎▍▌▋▊▉█"
SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

PENDING, ACTIVE, DONE = 0, 1, 2

# Below this, a two-pane split cannot hold both panes and the hint column has to go.
# Phones and split panes land here; `launcher_app.py` already learned this the hard
# way ("overflows the frame on a phone, where the same text is the only column").
NARROW = 76


class Responsive(Screen):
    """Screens stamp their own width class, so the breakpoint lives in one place."""

    def on_resize(self, event) -> None:
        self.set_class(event.size.width < NARROW, "-narrow")
        # Not every screen repaints from state - the input screens build themselves in
        # on_mount and have nothing to redraw. Assuming paint() existed crashed them on
        # the first resize, which in a terminal is the very first event they see.
        painter = getattr(self, "paint", None)
        if callable(painter):
            painter()

    @property
    def narrow(self) -> bool:
        return self.has_class("-narrow")


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
    """The robot mark. Its mouth IS the progress bar; its eyes go green on success.

    One identity object doing three jobs — static on the decide screen, animated
    during an install, lit on completion.
    """

    def render_frame(self, pct: float, subtitle: str, narrow: bool = False) -> None:
        eye = OK if pct >= 1.0 else ACCENT
        # The mark is 13 cells wide; the rule takes whatever is left after it and the
        # gutter. A fixed 46 ran off the side of a phone.
        rule = max(4, (self.size.width or 92) - 20)
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


# ══════════════════════════════════════════════════════════════════════════════
# DECIDE
# ══════════════════════════════════════════════════════════════════════════════


@dataclass
class Decision:
    key: str
    label: str
    kind: str  # "choice" | "toggle" | "path"
    value: Any
    hint: str
    options: tuple = field(default_factory=tuple)


# Seven decisions, down from twenty-eight. What was dropped and why:
#
#   * The three sync questions ("bring you up to date?", "stash them?", "discard
#     them?") cannot fire on a first install — there is no clone yet. They stay in
#     the engine as interrupts for the re-run case.
#   * "Full path to the claude CLI" only fires when preflight fails to find one.
#     Same treatment: an interrupt, not a question everyone answers.
#   * "Replace the existing status line?" only fires when one is already set.
#   * The six project questions (docx, citations, skeleton drift, map status,
#     Morgan's model, which project directory) are per-project configuration, not
#     installation — `virt-surv configure` already exists to do exactly this, and
#     the README is explicit that enablement is deliberately per-project.
#   * The seven "machine defaults" questions at step 14 duplicate those six for new
#     projects. Deferred with them.
GROUPS: list[tuple[str, list[Decision]]] = [
    (
        "Source",
        [
            Decision(
                "channel", "Release channel", "choice", "dev",
                "recommended — main can lag", ("dev", "main"),
            ),
            Decision("clone", "Clone to", "path", "~/virtual-surv-IT", ""),
        ],
    ),
    (
        # Not "Optional". These are what the team can DO — a user turning them off is
        # choosing a smaller product, not declining a developer convenience. Framing
        # the .docx/.html toolchain as "dev requirements, only needed to contribute"
        # was actively misleading: python-docx is what the docx-export SETTING runs on.
        "Capabilities",
        [
            Decision("pip", "Document output", "toggle", True,
                     ".docx + .html artifact export"),
            Decision("intel", "Code intelligence", "toggle", True,
                     "tree-sitter — sharper codebase orientation"),
            Decision("analysers", "Review analysers", "toggle", True,
                     "ruff, black, mypy, bandit, sqlfluff"),
        ],
    ),
    (
        "This machine",
        [
            Decision("statusline", "Status line", "toggle", True,
                     "team state in every project"),
            Decision("alias", "virt-surv alias", "toggle", True,
                     "the 'virt-surv go' shortcut"),
        ],
    ),
    # No "enable for a project" row. Enabling is a per-project decision taken from
    # inside the project - `virt-surv go` does it on first use - and asking for a path
    # here invited someone to name a folder they were not in. The install now says what
    # to do next instead of half-doing it.
]

LABEL_W = 20
# A fixed value column, so the hints start at the same x on every row type. Without
# it a toggle's hint began after "[x]  " and a choice's after "dev main", and the
# eye had nothing to run down.
VALUE_W = 12


class Row(Static):
    """One decision. Selection is a class, so the look lives in app.tcss."""

    def __init__(self, d: Decision, **kw) -> None:
        super().__init__(**kw)
        self.d = d

    def render_frame(self, selected: bool, narrow: bool = False) -> None:
        d = self.d
        label_w = 18 if narrow else LABEL_W
        t = Text()
        t.append("▸ " if selected else "  ", style=ACCENT if selected else HINT)
        t.append(d.label.ljust(label_w), style=f"bold {TEXT}" if selected else TEXT)

        if d.kind == "toggle":
            t.append("[", style=TRACK)
            t.append("✓" if d.value else " ", style=OK if d.value else TRACK)
            t.append("]", style=TRACK)
            t.append(" " * (VALUE_W - 3))
        elif d.kind == "choice":
            val = ""
            for opt in d.options:
                on = opt == d.value
                t.append(opt + "  ", style=f"bold {ACCENT}" if on else HINT)
                val += opt + "  "
            t.append(" " * max(0, VALUE_W - len(val)))
        else:
            # Paths carry their own meaning, so they take the hint column too and
            # earn an explicit edit affordance instead.
            shown = str(d.value) if d.value else "skip"
            t.append(shown, style=TEXT if d.value else HINT)
            if selected:
                t.append("  ↵", style=ACCENT)
            self.update(t)
            self.set_class(selected, "-selected")
            return

        if not narrow:
            t.append(d.hint, style=HINT)
        self.update(t)
        self.set_class(selected, "-selected")


class DecideScreen(Responsive):
    BINDINGS = [("q", "app.quit", "quit"), ("escape", "app.quit", "back")]

    def __init__(self, defaults: dict | None = None) -> None:
        super().__init__()
        # Per-instance copies: GROUPS holds module-level Decision objects, so mutating
        # them would leak a previous run's answers into the next one.
        #
        # compose() MUST build its rows from these copies. Iterating GROUPS there
        # instead left every Row rendering the original object while the toggles
        # mutated the copy — the value changed, the screen never did, and nothing
        # caught it because the tests asserted model state rather than pixels.
        self.groups = [(title, [replace(d) for d in ds]) for title, ds in GROUPS]
        self.decisions = [d for _title, ds in self.groups for d in ds]
        for d in self.decisions:
            if defaults and d.key in defaults and defaults[d.key] is not None:
                d.value = defaults[d.key]
        self.cursor = 0
        self.editing = False

    def compose(self) -> ComposeResult:
        with Vertical(id="shell"):
            yield Brand(id="brand")
            with Vertical(id="panel"):
                # No trailing spacer per group and no screen eyebrow: the panel's own
                # border title already names the screen, and the three extra rows were
                # what pushed the footer off a 26-row terminal.
                for i, (group, ds) in enumerate(self.groups):
                    yield Static(group, classes="group -first" if i == 0 else "group")
                    for d in ds:
                        yield Row(d, id=f"row-{d.key}", classes="task")
            yield Input(placeholder="path…", id="edit")
            yield Static(id="detail")
            yield Static(id="keys")

    def on_mount(self) -> None:
        self.query_one("#panel").border_title = "7 decisions"
        edit = self.query_one("#edit", Input)
        edit.display = False
        # Textual auto-focuses the first focusable widget on mount. That was the hidden
        # edit box, which then swallowed every printable key — "q" never reached the
        # binding, and left/right never reached the channel row.
        edit.can_focus = False
        self.set_focus(None)
        self.paint()

    # ── painting ──────────────────────────────────────────────────────────────
    def paint(self) -> None:
        if self.narrow:
            sub = f"install  ·  {self.get('channel')}"
        else:
            sub = f"first-time install  ·  {self.get('channel')}  ·  {self.get('clone')}"
        self.query_one("#brand", Brand).render_frame(0.0, sub, self.narrow)
        for i, d in enumerate(self.decisions):
            self.query_one(f"#row-{d.key}", Row).render_frame(
                i == self.cursor and not self.editing, self.narrow
            )

        d = self.decisions[self.cursor]
        det = Text("  ")
        det.append("│ ", style=TRACK)
        if self.editing:
            msg = "editing — enter commits, esc cancels"
        elif self.narrow and d.hint:
            msg = d.hint          # the hint column is gone; show the selected one here
        else:
            msg = "every decision has a sensible default; press i to install"
        det.append(msg, style=HINT)
        self.query_one("#detail", Static).update(det)

        keys: tuple[tuple[str, str], ...]
        if self.editing:
            keys = (("enter", "commit"), ("esc", "cancel"))
        elif d.kind == "toggle":
            keys = (("↑↓", "move"), ("space", "toggle"), ("i", "install"),
                    ("a", "advanced"), ("x", "diagnostics"), ("q", "quit"))
        elif d.kind == "choice":
            keys = (("↑↓", "move"), ("←→", "change"), ("i", "install"),
                    ("a", "advanced"), ("x", "diagnostics"), ("q", "quit"))
        else:
            keys = (("↑↓", "move"), ("enter", "edit"), ("i", "install"),
                    ("a", "advanced"), ("x", "diagnostics"), ("q", "quit"))
        k = Text("  ")
        for name, desc in keys:
            k.append(name, style=KEY)
            k.append(f" {desc}   ", style=HINT)
        self.query_one("#keys", Static).update(k)

    def get(self, key: str) -> Any:
        return next(d.value for d in self.decisions if d.key == key)

    # ── input ─────────────────────────────────────────────────────────────────
    def on_key(self, event) -> None:
        if self.editing:
            return
        d = self.decisions[self.cursor]
        k = event.key
        if k in ("down", "j"):
            self.cursor = (self.cursor + 1) % len(self.decisions)
        elif k in ("up", "k"):
            self.cursor = (self.cursor - 1) % len(self.decisions)
        elif k == "space" and d.kind == "toggle":
            d.value = not d.value
        elif k in ("left", "right") and d.kind == "choice":
            i = d.options.index(d.value)
            step = 1 if k == "right" else -1
            d.value = d.options[(i + step) % len(d.options)]
        elif k == "enter" and d.kind == "path":
            self.editing = True
            edit = self.query_one("#edit", Input)
            edit.value = str(d.value)
            edit.display = True
            edit.can_focus = True
            edit.focus()
        elif k == "i":
            starter = getattr(self.app, "start_install", None)
            if starter:
                starter(self.snapshot())
            else:
                self.app.push_screen(InstallScreen(self.snapshot()))
        elif k == "a":
            # Everything the classic menu keeps behind "Advanced / one-off settings",
            # machine defaults included. Unreachable from here, it may as well not
            # exist - which is exactly how it was reported.
            self.app.push_screen(AdvancedScreen("advanced"))
        elif k == "x":
            self.app.push_screen(AdvancedScreen("diagnostics"))
        else:
            return
        event.stop()
        self.paint()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.decisions[self.cursor].value = event.value.strip()
        self.close_edit()

    def close_edit(self) -> None:
        edit = self.query_one("#edit", Input)
        edit.display = False
        edit.can_focus = False
        self.editing = False
        self.set_focus(None)
        self.paint()

    def key_escape(self, event) -> None:
        if self.editing:
            event.stop()          # esc cancels the edit, it does not leave the app
            self.close_edit()

    def snapshot(self) -> dict:
        return {d.key: d.value for d in self.decisions}


# ══════════════════════════════════════════════════════════════════════════════
# INSTALL
# ══════════════════════════════════════════════════════════════════════════════

# Titles come from install_helper.Installer.build_plan()'s full-run branch. The four
# dropped rows are the ones the decide screen already settled or that only fire
# conditionally — the engine still runs every one of them.
TASKS = [
    ("Preflight", "git 2.43.0  ·  claude 1.0.72  ·  network ok",
     "resolving git, claude CLI, network reachability"),
    ("Clone repository", "danieledge/virtual-surv-IT @ main",
     "remote: Enumerating objects: 4821, done."),
    ("Guard interpreter cache", "warmed",
     "resolving interpreter for 4 hooks"),
    ("Code intelligence", "tree-sitter ready",
     "installing tree-sitter grammars"),
    ("Claude Code marketplace", "virtual-surv-it added",
     "claude plugin marketplace add virtual-surv-it"),
    ("Install plugin", "compliance-surveillance-team",
     "claude plugin install compliance-surveillance-team"),
    ("Status line", "wired",
     "merging statusLine into ~/.claude/settings.json"),
    ("Alias setup", "virt-surv registered",
     "stamping alias into ~/.bashrc"),
]


class TaskRow(Static):
    def __init__(self, index: int, **kw) -> None:
        super().__init__(**kw)
        self.index = index

    def render_frame(self, state: int, pct: float, frame: int, narrow: bool = False) -> None:
        label, meta, _ = TASKS[self.index]
        width = 22 if narrow else LABEL_W + 4
        t = Text("  ")
        if state == DONE:
            t.append("✓  ", style=OK)
            t.append(label.ljust(width), style=TEXT)
            if not narrow:
                t.append(meta, style=HINT)
        elif state == ACTIVE:
            t.append(SPINNER[frame % len(SPINNER)] + "  ", style=ACCENT)
            t.append(label.ljust(width), style=f"bold {TEXT}")
            if not narrow:
                t.append_text(bar(pct, 16))
            t.append(f"  {int(pct * 100):>3}%", style=DIM)
        else:
            t.append("·  ", style=HINT)
            t.append(label.ljust(width), style=HINT)
        self.update(t)


class InstallScreen(Responsive):
    BINDINGS = [("q", "app.quit", "quit"), ("escape", "app.quit", "back")]

    def __init__(self, choices: dict | None = None, frozen: bool = False,
                 done: bool = False) -> None:
        super().__init__()
        self.choices = choices or {"channel": "dev", "clone": "~/virtual-surv-IT"}
        self.frozen = frozen
        self.frame = 0
        if done:
            self.states = [DONE] * len(TASKS)
            self.pct = 1.0
        else:
            self.states = [DONE, ACTIVE] + [PENDING] * (len(TASKS) - 2)
            self.pct = 0.62

    def compose(self) -> ComposeResult:
        with Vertical(id="shell"):
            yield Brand(id="brand")
            yield Static("INSTALL", id="eyebrow")
            with Vertical(id="panel"):
                for i in range(len(TASKS)):
                    yield TaskRow(i, id=f"task{i}", classes="task")
            yield Static(id="detail")
            yield Static(id="keys")

    def on_mount(self) -> None:
        self.query_one("#panel").border_title = f"{len(TASKS)} steps"
        k = Text("  ")
        for name, desc in (("i", "detail"), ("q", "quit")):
            k.append(name, style=KEY)
            k.append(f" {desc}   ", style=HINT)
        self.query_one("#keys", Static).update(k)
        self.paint()
        if not self.frozen:
            self.set_interval(1 / 20, self.tick)

    def paint(self) -> None:
        chan = self.choices.get("channel", "dev")
        if all(s == DONE for s in self.states):
            sub = f"installed  ·  {chan}"
        elif self.narrow:
            sub = f"installing  ·  {chan}"
        else:
            sub = f"installing  ·  {chan}  ·  {self.choices.get('clone', '~/virtual-surv-IT')}"
        self.query_one("#brand", Brand).render_frame(self.overall(), sub, self.narrow)
        for i in range(len(TASKS)):
            self.query_one(f"#task{i}", TaskRow).render_frame(
                self.states[i], self.pct, self.frame, self.narrow
            )

        active = next((i for i, s in enumerate(self.states) if s == ACTIVE), None)
        d = Text("  ")
        if active is None:
            d.append("✓ ", style=OK)
            d.append("done — restart Claude Code, then ", style=DIM)
            d.append("virt-surv go", style=ACCENT)
            d.append(" from your project", style=DIM)
        else:
            d.append("│ ", style=TRACK)
            d.append(TASKS[active][2], style=HINT)
        self.query_one("#detail", Static).update(d)

    def overall(self) -> float:
        n_done = sum(1 for s in self.states if s == DONE)
        running = self.pct if ACTIVE in self.states else 0.0
        return (n_done + running) / len(TASKS)

    def tick(self) -> None:
        self.frame += 1
        if ACTIVE not in self.states:
            self.paint()
            return
        self.pct += 0.03
        if self.pct >= 1.0:
            i = self.states.index(ACTIVE)
            self.states[i] = DONE
            if i + 1 < len(self.states):
                self.states[i + 1] = ACTIVE
            self.pct = 0.0
        self.paint()


# ══════════════════════════════════════════════════════════════════════════════
# LAUNCH — `virt-surv go`
# ══════════════════════════════════════════════════════════════════════════════

# Rows and keys are ported verbatim from launcher_app.run_app(), including the
# "Or" divider before settings/archive/launch — the comment there records that
# mis-grouping those made "change a project setting" read as an engagement.
#
# `virt-surv configure` is redundant: the project settings the installer used to
# ask about live behind [c] here, on the project you are actually in.
ENGAGEMENTS = [
    ("spoofing-review", "●", ACCENT, "most recent",
     [("status", "in progress"), ("next", "tune thresholds"),
      ("opened", "3 days ago"), ("artifacts", "4")]),
    ("wash-trade-pack", "◐", GOLD, "",
     [("status", "blocked"), ("next", "await venue data feed"),
      ("opened", "11 days ago"), ("artifacts", "2")]),
    ("mar-gap-analysis", "○", HINT, "",
     [("status", "open"), ("next", "scope the gap list"),
      ("opened", "21 days ago"), ("artifacts", "0")]),
]

ACTIONS = [
    ("n", "a new engagement", "Start a fresh engagement in this project."),
    ("j", "a new engagement from a Jira ticket", "Seed an engagement from a ticket's summary and acceptance criteria."),
    ("c", "change a project setting", "Docx output, citations, review tools and Morgan's model — for this project."),
    ("o", "open a different project folder", "Point the team at another repo without leaving the launcher."),
    ("v", "view an engagement's artifacts", "Browse what the team produced, without starting a session."),
    ("a", "archive engagement(s)", "Close finished work and take it out of the resume list."),
    ("b", "browse done & archived", "Everything already signed off or archived."),
    ("t", "watch the engagement running",
     "Follow a run already in progress. Starts nothing - you come back here after."),
    ("", "decide inside the session", "Launch Claude Code and choose there instead."),
]

# (kind, payload) — "group" rows are headings and cannot be selected.
LAUNCH_ROWS: list[tuple[str, Any]] = (
    [("group", "Resume an engagement")]
    + [("eng", i) for i in range(len(ENGAGEMENTS))]
    + [("group", "Start something new"), ("act", 0), ("act", 1), ("group", "Or")]
    + [("act", i) for i in range(2, len(ACTIONS))]
)


class LaunchRow(Static):
    def __init__(self, screen_rows, kind: str, payload, **kw) -> None:
        super().__init__(**kw)
        self.screen_rows, self.kind, self.payload = screen_rows, kind, payload

    def render_frame(self, selected: bool) -> None:
        t = Text()
        t.append("▸ " if selected else "  ", style=ACCENT if selected else HINT)
        if self.kind == "eng":
            v = self.screen_rows[self.payload]
            colour = GOLD if v.get("mark_style") == "warn" else DIM
            t.append((v.get("mark") or "•") + " ", style=colour)
            t.append(v.get("title") or "?", style=f"bold {TEXT}" if selected else TEXT)
            if v.get("recommended"):
                t.append("   ← most recent", style=OK)
        else:
            key, label, _ = ACTIONS[self.payload]
            t.append(f"[{key}] " if key else "    ", style=KEY)
            t.append(label, style=f"bold {TEXT}" if selected else TEXT)
        self.update(t)
        self.set_class(selected, "-selected")


class LaunchScreen(Responsive):
    """`virt-surv2 go`. Real engagement state for the folder you are in.

    The first version of this screen was a mock with invented engagements and a made-up
    project name, which is why it could not say which folder it was reading or whether
    the list belonged to it. Both were reported, and both were the same defect.
    """

    # Esc leaves, as it does on every other screen and as the footer promises. Lost in
    # the rewrite that wired this to real data, and caught only because a test pinned it.
    BINDINGS = [("q", "app.quit", "quit"), ("escape", "app.quit", "back to terminal")]

    def __init__(self, project=None, rows=None, note: str = "") -> None:
        super().__init__()
        self.project = Path(project) if project else Path.cwd()
        self.engagements = list(rows or [])
        self.note = note
        resume: list[tuple[str, Any]] = []
        if self.engagements:
            resume = ([("group", "Resume an engagement")]
                      + [("eng", i) for i in range(len(self.engagements))])
        elif self.note:
            # Not an empty heading: a heading with nothing under it claims a list exists
            # and then shows none, which is worse than saying so.
            resume = [("note", self.note)]
        self.rows: list[tuple[str, Any]] = (
            resume
            + [("group", "Start something new"), ("act", 0), ("act", 1), ("group", "Or")]
            + [("act", i) for i in range(2, len(ACTIONS))]
        )
        self.selectable = [i for i, (k, _) in enumerate(self.rows)
                           if k not in ("group", "note")]
        self.cursor = 0

    def compose(self) -> ComposeResult:
        with Vertical(id="shell"):
            yield Brand(id="brand")
            with Horizontal(id="panes"):
                with VerticalScroll(id="panel"):
                    for i, (kind, payload) in enumerate(self.rows):
                        if kind == "group":
                            yield Static(payload,
                                         classes="group -first" if i == 0 else "group")
                        elif kind == "note":
                            yield Static(id="lnote", classes="group -first")
                        else:
                            yield LaunchRow(self.engagements, kind, payload,
                                            id=f"lrow{i}", classes="task")
                with Vertical(id="side"):
                    yield Static(id="side-body")
            yield Static(id="detail")
            yield Static(id="keys")

    def on_mount(self) -> None:
        n = len(self.engagements)
        self.query_one("#panel").border_title = f"{n} open" if n else "nothing open"
        self.query_one("#side").border_title = "detail"
        k = Text("  ")
        for name, desc in (("↑↓", "move"), ("enter", "choose"), ("c", "settings"),
                           ("esc", "back to terminal")):
            k.append(name, style=KEY)
            k.append(f" {desc}   ", style=HINT)
        self.query_one("#keys", Static).update(k)
        self.paint()

    def _folder(self) -> str:
        """The folder being read, shortened but never guessed at."""
        try:
            p = self.project.resolve()
        except OSError:
            p = self.project
        home = Path.home()
        try:
            return "~/" + str(p.relative_to(home))
        except ValueError:
            return str(p)

    def paint(self) -> None:
        folder = self._folder()
        self.query_one("#brand", Brand).render_frame(
            0.0, folder if self.narrow else f"{folder}  ·  engagements in this folder",
            self.narrow)

        try:
            n = Text()
            n.append(self.note, style=HINT)
            self.query_one("#lnote", Static).update(n)
        except Exception:               # noqa: BLE001 — only present when there is a note
            pass

        sel_row = self.selectable[self.cursor] if self.selectable else -1
        for i, (kind, payload) in enumerate(self.rows):
            if kind in ("group", "note"):
                continue
            self.query_one(f"#lrow{i}", LaunchRow).render_frame(i == sel_row)

        t = Text("\n")
        if sel_row >= 0:
            kind, payload = self.rows[sel_row]
            if kind == "eng":
                v = self.engagements[payload]
                t.append(f"  {v.get('title') or '?'}\n\n", style=f"bold {ACCENT}")
                for label, value in v.get("lines") or []:
                    t.append(f"  {label:<10}", style=HINT)
                    warn = v.get("status") == "blocked" and label in ("status", "next")
                    t.append(f"{value}\n", style=GOLD if warn else TEXT)
            else:
                key, label, blurb = ACTIONS[payload]
                t.append(f"  {label}\n\n", style=f"bold {ACCENT}")
                for line in _wrap(blurb, 26):
                    t.append(f"  {line}\n", style=DIM)
                if key:
                    t.append("\n  shortcut  ", style=HINT)
                    t.append(key, style=KEY)
        self.query_one("#side-body", Static).update(t)

        d = Text("  ")
        d.append("│ ", style=TRACK)
        if self.note:
            # Says WHICH folder, because "no open engagements" on its own reads as a
            # statement about the product rather than about where you are standing.
            d.append(f"{self.note} — {folder}", style=HINT)
        else:
            d.append(f"{len(self.engagements)} open in {folder}", style=HINT)
        self.query_one("#detail", Static).update(d)

    def on_key(self, event) -> None:
        if not self.selectable:
            return
        kind, payload = self.rows[self.selectable[self.cursor]]
        # Arrows only here, NOT vim j/k: this screen advertises [j] for Jira, and a
        # vim binding silently ate it - the row printed a hotkey that moved the cursor.
        # v1's launcher binds arrows only for the same reason.
        if event.key == "down":
            self.cursor = (self.cursor + 1) % len(self.selectable)
        elif event.key == "up":
            self.cursor = (self.cursor - 1) % len(self.selectable)
        elif event.key == "enter":
            event.stop()
            self._choose(kind, payload)
            return
        elif any(event.key == k for k, _l, _b in ACTIONS if k):
            # The rows advertise [n] [j] [c] [o] [v] [a] [b]; only [c] was wired, so
            # every other one silently did nothing - a hotkey that is printed and
            # ignored is worse than one that was never offered.
            event.stop()
            idx = next(i for i, (k, _l, _b) in enumerate(ACTIONS) if k == event.key)
            self._choose("act", idx)
            return
        else:
            return
        event.stop()
        self.paint()

    # Launcher rows that hand a DECISION to the shell wrapper, which then starts
    # Claude Code with it - the same stdout contract `virt-surv go` uses.
    # Rows that run engine work in this process instead.
    # [b] is a SCREEN now, not a listing: it has to return a token so --review and
    # sign-off are reachable.
    # [a] is a SCREEN now: v1 picks one or all, v2 archived everything closed.
    ENGINE_ACTIONS = {"v": "artifacts", "t": "watch"}

    def _decide(self, decision: str) -> None:
        """Hand a decision to the wrapper and leave, exactly as virt_team_launcher does:
        stdout carries it, nothing else may."""
        self.app.decision = decision
        self.app.exit()

    @property
    def engage_cmd(self) -> str:
        # Defaulted, not assumed: the screen-only app has no engine to resolve the
        # project's engage spelling, and a fuzzed Enter must not crash it.
        return getattr(self.app, "engage_cmd", "/compliance-surveillance-team:engage")

    def _choose(self, kind, payload) -> None:
        """Enter used to do nothing at all - reported as "doesn't allow any option to
        be selected"."""
        if kind == "eng":
            v = self.engagements[payload]
            token = ""
            getter = getattr(self.app, "resume_token", None)
            if getter:
                token = getter(v)
            if not token:
                self.note = f"no resume token for {v.get('title')} - open it with virt-surv go"
                self.paint()
                return
            self._decide(f"{self.engage_cmd} --resume {token}")
            return

        key, label, _blurb = ACTIONS[payload]
        if key == "n":
            self._decide(f"{self.engage_cmd} --new")
            return
        if key == "":
            # "decide inside the session": launch with no decision, which is what an
            # empty stdout means to the wrapper.
            self._decide("")
            return
        if key == "c":
            self.app.push_screen(SettingsScreen(str(self.project)))
            return
        if key == "o":
            self.app.push_screen(OpenProjectScreen(self.project))
            return
        if key == "j":
            self.app.push_screen(JiraScreen(self.project))
            return
        if key == "a":
            self.app.push_screen(ArchiveScreen(self.project, self.engagements))
            return
        if key == "b":
            reader = getattr(self.app, "finished_engagements", None)
            rows, note = reader(self.project) if reader else ([], "needs the engine")
            self.app.push_screen(BrowseScreen(self.project, rows, note))
            return
        runner = getattr(self.app, "start_action", None)
        engine_action = self.ENGINE_ACTIONS.get(key)
        if engine_action and runner:
            # Pass the HIGHLIGHTED engagement so artifacts shows the one you picked.
            token = ""
            sel = self.rows[self.selectable[self.cursor]]
            if sel[0] == "eng":
                getter = getattr(self.app, "resume_token", None)
                token = getter(self.engagements[sel[1]]) if getter else ""
            runner(engine_action, project=self.project, back=True, slug=token)
            return
        if False:
            # back=True: none of these starts a session, so they return here rather
            # than ending the launcher.
            runner(engine_action, project=self.project, back=True)
            return
        self.note = f"{label}: not available here"
        self.paint()


def _wrap(text: str, width: int) -> list[str]:
    out, line = [], ""
    for word in text.split():
        if line and len(line) + 1 + len(word) > width:
            out.append(line)
            line = word
        else:
            line = f"{line} {word}".strip()
    if line:
        out.append(line)
    return out


# ══════════════════════════════════════════════════════════════════════════════
# SETTINGS — `[c] change a project setting`
# ══════════════════════════════════════════════════════════════════════════════

# `virt-surv configure` is redundant: settings belong on the project you are in, so
# this is where the install's deferred project questions land. Groups, labels and help
# text are GENERATED from scripts/virt_team_launcher.py by tools/gen_settings.py — the
# screen cannot drift from the thing it configures.

SET_LABEL_W = 32


class SettingRow(Static):
    def __init__(self, row: dict, **kw) -> None:
        super().__init__(**kw)
        self.row = row

    def render_frame(self, selected: bool, narrow: bool = False) -> None:
        r = self.row
        width = 24 if narrow else SET_LABEL_W
        t = Text()
        t.append("▸ " if selected else "  ", style=ACCENT if selected else HINT)
        label = r["label"]
        if len(label) > width - 1:
            label = label[: width - 2] + "…"
        t.append(label.ljust(width), style=f"bold {TEXT}" if selected else TEXT)
        # The value as the launcher formats it, provenance and all: "on  (machine
        # default)" and "on" are different states - one is inherited, one was set here -
        # and a bare on/off cannot tell them apart.
        head, _, qualifier = str(r["value"]).partition("  ")
        t.append(head, style=OK if r["on"] else HINT)
        if qualifier and not narrow:
            t.append("  " + qualifier, style=HINT)
        self.update(t)
        self.set_class(selected, "-selected")


class SettingsScreen(Responsive):
    """The project's real settings, read and written through the launcher's editor.

    The first version of this screen rendered a generated constant and wrote nothing,
    while printing "currently: on" and "N changed" - it asserted a project's
    configuration as fact and claimed edits it did not keep.
    """

    BINDINGS = [("q", "app.quit", "quit")]

    def __init__(self, project: str = ".") -> None:
        super().__init__()
        self.project = Path(project).expanduser()
        self.groups: list = []
        self.rows: list = []
        self.note = ""
        self.cursor = 0

    def compose(self) -> ComposeResult:
        with Vertical(id="shell"):
            yield Brand(id="brand")
            with Horizontal(id="panes"):
                with VerticalScroll(id="panel"):
                    yield Static(id="setting-rows")
                with Vertical(id="side"):
                    yield Static(id="side-body")
            yield Static(id="detail")
            yield Static(id="keys")

    def on_mount(self) -> None:
        self.query_one("#side").border_title = "what it does"
        self.reload()

    def reload(self) -> None:
        """Re-read from disk. Every write goes through the launcher, so the only way to
        show what a project is now configured to do is to ask again."""
        reader = getattr(self.app, "settings_rows", None)
        if reader:
            self.groups, err = reader(self.project)
        else:
            self.groups, err = [], "settings need the engine"
        if err:
            self.note = err
        self.rows = [r for _t, rows in self.groups for r in rows]
        self.cursor = min(self.cursor, max(0, len(self.rows) - 1))
        try:
            self.query_one("#panel").border_title = (
                f"{len(self.rows)} settings" if self.rows else "no settings")
        except Exception:               # noqa: BLE001
            pass
        self.paint()

    def paint(self) -> None:
        folder = str(self.project)
        try:
            folder = "~/" + str(self.project.resolve().relative_to(Path.home()))
        except (ValueError, OSError):
            pass
        self.query_one("#brand", Brand).render_frame(
            0.0, folder if self.narrow else f"{folder}  ·  project settings", self.narrow)

        t = Text()
        idx = 0
        for title, rows in self.groups:
            t.append(f"  {title}\n", style=f"bold {HINT}")
            for r in rows:
                sel = idx == self.cursor
                t.append("  ▸ " if sel else "    ", style=ACCENT if sel else HINT)
                label = r["label"]
                if len(label) > SET_LABEL_W - 1:
                    label = label[: SET_LABEL_W - 2] + "…"
                t.append(label.ljust(SET_LABEL_W),
                         style=f"bold {TEXT}" if sel else TEXT)
                head, _, qual = str(r["value"]).partition("  ")
                t.append(head, style=OK if r["on"] else HINT)
                if qual and not self.narrow:
                    t.append("  " + qual, style=HINT)
                t.append("\n")
                idx += 1
            t.append("\n")
        self.query_one("#setting-rows", Static).update(t)

        body = Text("\n")
        if self.rows:
            cur = self.rows[self.cursor]
            for line in _wrap(cur["label"], 26):
                body.append(f"  {line}\n", style=f"bold {ACCENT}")
            body.append("\n")
            for line in _wrap(cur["what"], 26):
                body.append(f"  {line}\n", style=TEXT)
            if cur["off"]:
                body.append("\n")
                for line in _wrap(cur["off"], 26):
                    body.append(f"  {line}\n", style=HINT)
            body.append("\n  currently\n", style=HINT)
            for line in _wrap(str(cur["value"]), 26):
                body.append(f"  {line}\n", style=OK if cur["on"] else HINT)
        self.query_one("#side-body", Static).update(body)

        d = Text("  ")
        d.append("│ ", style=TRACK)
        d.append(self.note or f"changes are written to {folder} as you make them",
                 style=GOLD if self.note else HINT)
        self.query_one("#detail", Static).update(d)

        k = Text("  ")
        for name, desc in (("↑↓", "move"), ("space", "change"),
                           ("d", "restore machine defaults"), ("esc", "back")):
            k.append(name, style=KEY)
            k.append(f" {desc}   ", style=HINT)
        self.query_one("#keys", Static).update(k)

    def on_key(self, event) -> None:
        if not self.rows:
            return
        k = event.key
        if k == "down":
            self.cursor = (self.cursor + 1) % len(self.rows)
        elif k == "up":
            self.cursor = (self.cursor - 1) % len(self.rows)
        elif k in ("space", "enter", "left", "right"):
            self._apply(self.rows[self.cursor])
            return
        elif k == "d":
            self._restore()
            return
        else:
            return
        event.stop()
        self.paint()

    def _apply(self, row: dict) -> None:
        applier = getattr(self.app, "settings_apply", None)
        if not applier:
            self.note = "settings need the engine"
            self.paint()
            return
        try:
            self.note = applier(self.project, row["key"]) or ""
        except Exception as exc:        # noqa: BLE001 — a bad write must say so
            self.note = f"could not change {row['label']}: {exc}"
        self.reload()

    def _restore(self) -> None:
        restorer = getattr(self.app, "settings_restore", None)
        if not restorer:
            return
        try:
            self.note = restorer(self.project) or "restored machine defaults"
        except Exception as exc:        # noqa: BLE001
            self.note = f"could not restore defaults: {exc}"
        self.reload()

    def key_escape(self, event) -> None:
        event.stop()
        if len(self.app.screen_stack) > 2:
            self.app.pop_screen()
        else:
            self.app.exit()


# ══════════════════════════════════════════════════════════════════════════════
# ADVANCED / DIAGNOSTICS — mirrors `virt-surv`'s own submenus
# ══════════════════════════════════════════════════════════════════════════════

# Same items, same order, same wording as install_helper.choose_action()'s
# "Advanced / one-off settings..." and "Diagnostics..." submenus. Each runs the
# engine's own code — an `Installer(subset=...)` plan or the same `run_*` function
# main() calls — so this is a different front door onto identical behaviour.
#
# The shell-rc edits live HERE as optional items, exactly as they do today. Nothing
# writes to a shell profile from a top-level flag or during a normal install.
#
#   (action, label, blurb)
ADVANCED: list[tuple[str, str, str]] = [
    ("setup", "Environment setup only",
     "This machine, no code pull: marketplace, plugin, status line, enablement."),
    ("statusline", "Status line",
     "This machine - shown in every project."),
    ("model", "Morgan's model",
     "Per project only."),
    ("formats", "Analyser overrides (this project)",
     "Turn any of the seven supported analysers (ruff, mypy, bandit, black, sqlfluff, "
     "shfmt, gitleaks) on or off for one project, and validate the forced-on ones "
     "against what is actually installed. Everything else this step used to ask - docx "
     "output and regulatory citations - now lives in the settings screen."),
    ("demo", "Demo",
     "Watch the whole run - nothing executed or written."),
    ("machinedefaults", "This machine's defaults",
     "View/edit - no project needed."),
    ("dashboard", "Rebuild the local team dashboard",
     "Regenerate the dashboard from current state."),
    ("fixbashrc", "Fix a slow ~/.bashrc",
     "Checks first, applies only if needed. Backs the file up before writing. A slow "
     "profile costs every Claude Code tool call, because the Bash tool sources it "
     "non-interactively before each one."),
    ("cleanplugincache", "Clean stale plugin cache",
     "Removes old installs, keeps the active one."),
    ("aliasmanage", "Manage the shell shortcuts",
     "Register or update BOTH shortcuts - virt-surv and virt-surv2 - or change the "
     "command 'go' launches. One block, one stamp, so an upgrade keeps them together."),
    ("gitbashperf", "Git Bash performance fix",
     "Claude Code shell-snapshot slowness on Windows."),
    ("codeintel", "Code intelligence",
     "Install/refresh tree-sitter - sharper codebase orientation; optional, degrades "
     "to pattern matching without it. Reports 'already available' when present, so it "
     "is also the safe way to check."),
    ("extensions", "Org extensions",
     "Review/edit the standard workflow this machine applies to every project - "
     "analysers, close actions, instructions."),
    ("reprobe", "Re-probe installed tools",
     "Run after installing an analyser or tree-sitter, so the team stops reporting "
     "it missing."),
    ("relocate", "Move team files into VSIT/",
     "One folder instead of scattered across your docs/ and repo root - shows you the "
     "plan before moving anything."),
]

DIAGNOSTICS: list[tuple[str, str, str]] = [
    ("check", "Check for updates", "Read-only."),
    ("toolcheck", "Quick: analyser output cleanliness only", "Are the analysers parseable?"),
    ("envcheck", "Comprehensive: the full environment + synthetic-engagement report",
     "The long one."),
    ("selftest", "Self-test only: just the synthetic engagement", ""),
    ("hooklatency", "Hook latency",
     "Feeds the ADR-014 daemon decision - slower, repeated + concurrent. Internal."),
    ("adr014smoke", "ADR-014 spike smoke test",
     "PROTOTYPE - starts a real daemon process. Internal."),
    ("daemonstart", "Guard daemon start diagnostic",
     "Starts the REAL daemon - why isn't it starting. Internal."),
]

# Items that write to a shell profile need a second, deliberate keypress.
SHELL_WRITERS = {"fixbashrc", "aliasmanage", "gitbashperf"}

# v1 Advanced items deliberately NOT duplicated here, and where they went instead.
# The parity test allows these and requires a destination for each, so "missing" and
# "moved on purpose" stay different things.
# Nothing is deduped away right now. `formats` was, on the belief that the settings
# screen covered it - it covers docx and citations, but NOT the per-project analyser
# overrides, which live in a different store. The item is back, renamed to the part
# that is genuinely only there.
DEDUPED: dict = {}


class AdvancedRow(Static):
    def __init__(self, items, index: int, **kw) -> None:
        super().__init__(**kw)
        self.items, self.index = items, index

    def render_frame(self, selected: bool, narrow: bool = False) -> None:
        action, label, _blurb = self.items[self.index]
        t = Text()
        t.append("▸ " if selected else "  ", style=ACCENT if selected else HINT)
        shown = label if len(label) <= 46 or narrow else label[:45] + "…"
        t.append(shown, style=f"bold {TEXT}" if selected else TEXT)
        if action in SHELL_WRITERS and not narrow:
            t.append("   · shell profile", style=GOLD if selected else HINT)
        self.update(t)
        self.set_class(selected, "-selected")


class AdvancedScreen(Responsive):
    BINDINGS = [("q", "app.quit", "quit")]

    def __init__(self, mode: str = "advanced") -> None:
        super().__init__()
        self.mode = mode
        self.items = DIAGNOSTICS if mode == "diagnostics" else ADVANCED
        self.cursor = 0
        self.armed = False
        self.note = ""

    def compose(self) -> ComposeResult:
        with Vertical(id="shell"):
            yield Brand(id="brand")
            with Horizontal(id="panes"):
                with VerticalScroll(id="panel"):
                    for i in range(len(self.items)):
                        yield AdvancedRow(self.items, i, id=f"adv{i}", classes="task")
                with Vertical(id="side"):
                    yield Static(id="side-body")
            yield Static(id="detail")
            yield Static(id="keys")

    def on_mount(self) -> None:
        self.query_one("#panel").border_title = f"{len(self.items)} actions"
        self.query_one("#side").border_title = "what it does"
        self.paint()

    def paint(self) -> None:
        title = "diagnostics" if self.mode == "diagnostics" else "advanced / one-off settings"
        self.query_one("#brand", Brand).render_frame(
            0.0, self.mode if self.narrow else title, self.narrow)
        for i in range(len(self.items)):
            self.query_one(f"#adv{i}", AdvancedRow).render_frame(i == self.cursor, self.narrow)

        action, label, blurb = self.items[self.cursor]
        body = Text("\n")
        for line in _wrap(label, 26):
            body.append(f"  {line}\n", style=f"bold {ACCENT}")
        body.append("\n")
        for line in _wrap(blurb, 26):
            body.append(f"  {line}\n", style=TEXT)
        self.query_one("#side-body", Static).update(body)

        d = Text("  ")
        if self.note:
            d.append("✓ ", style=OK)
            d.append(self.note, style=DIM)
        elif self.armed:
            d.append("│ ", style=TRACK)
            d.append("press enter again to run it, esc to cancel", style=GOLD)
        else:
            d.append("│ ", style=TRACK)
            d.append("nothing here runs until you choose it", style=HINT)
        self.query_one("#detail", Static).update(d)

        k = Text("  ")
        for name, desc in (("↑↓", "move"), ("enter", "run"), ("esc", "back"), ("q", "quit")):
            k.append(name, style=KEY)
            k.append(f" {desc}   ", style=HINT)
        self.query_one("#keys", Static).update(k)

    def on_key(self, event) -> None:
        action = self.items[self.cursor][0]
        if event.key in ("down", "j"):
            self.cursor = (self.cursor + 1) % len(self.items)
            self.armed, self.note = False, ""
            self.query_one(f"#adv{self.cursor}", AdvancedRow).scroll_visible()
        elif event.key in ("up", "k"):
            self.cursor = (self.cursor - 1) % len(self.items)
            self.armed, self.note = False, ""
            self.query_one(f"#adv{self.cursor}", AdvancedRow).scroll_visible()
        elif event.key == "enter":
            self._activate(action)
        else:
            return
        event.stop()
        self.paint()

    def _activate(self, action: str) -> None:
        if action in SHELL_WRITERS and not self.armed:
            self.armed, self.note = True, ""
            return

        self.armed = False
        runner = getattr(self.app, "start_action", None)
        if runner:
            runner(action)
        else:
            self.note = f"'{action}' needs the engine — run virt-surv2 without --advanced"

    def key_escape(self, event) -> None:
        event.stop()
        if self.armed:
            self.armed, self.note = False, ""
            self.paint()
        elif len(self.app.screen_stack) > 2:
            self.app.pop_screen()
        else:
            self.app.exit()


# ══════════════════════════════════════════════════════════════════════════════
# MAIN MENU — mirrors `virt-surv`'s own front door
# ══════════════════════════════════════════════════════════════════════════════

# The same seven entries as install_helper.choose_action(), same keys, same order.
# Without this, three of v1's top-level options - configure, help, update-only - had
# nowhere to live in v2 and were simply absent.
MAIN_MENU: list[tuple[str, str, str, str]] = [
    ("1", "full", "Install or reconfigure the team",
     "The full run. Every decision up front, then it runs start to finish without "
     "stopping to ask."),
    ("2", "configure", "Configure a project",
     "Per project: enable, permissions, preferences and Morgan's model, in one guided "
     "pass over one folder."),
    ("3", "diagnostics", "Diagnostics...",
     "Update check, analyser cleanliness, the full environment report, self-test, and "
     "the internal daemon probes."),
    ("4", "advanced", "Advanced / one-off settings...",
     "Status line, project preferences, machine defaults, the aliases, code "
     "intelligence, org extensions, tool re-probe and the rest."),
    ("5", "howto", "Help: using the plugin",
     "Morgan explains what the team is and how to work with it. Read-only."),
    ("u", "update", "Update only (quick)",
     "New code and a refreshed plugin, keeping every setting. Does NOT re-ask the "
     "channel: an update that silently changed channel would be a different thing "
     "wearing an update's name."),
    ("q", "quit", "Quit", "Leave. Nothing is written."),
]


# The three answers `virt-surv go` offers on a project with no team configuration.
# Same shape as launcher_app.setup_screen's, because it is the same decision.
FIRST_RUN = [
    ("onboard", "Set it up with the recommended defaults",
     "Applies every recommended project default with no questions: enable the team "
     "here, permissions, preferences and the orchestrator model. The usual answer."),
    ("configure", "Walk me through it",
     "The same setup, asking about each part, with the recommended answer pre-filled."),
    ("skip", "Not now",
     "Leaves this folder untouched and goes straight to the launcher. The team will "
     "not run here until it is set up."),
]


class FirstRunRow(Static):
    def __init__(self, index: int, **kw) -> None:
        super().__init__(**kw)
        self.index = index

    def render_frame(self, selected: bool) -> None:
        _action, label, _blurb = FIRST_RUN[self.index]
        t = Text()
        t.append("▸ " if selected else "  ", style=ACCENT if selected else HINT)
        t.append(label, style=f"bold {TEXT}" if selected else TEXT)
        self.update(t)
        self.set_class(selected, "-selected")


class FirstRunScreen(Responsive):
    """No team configuration in this folder yet.

    `virt-surv go` has offered real first-time setup here since 2026-08-17 rather than
    launching with a hint; entering an unconfigured folder in v2 did nothing of the
    sort, which made v2 look like it had simply lost the folder.
    """

    BINDINGS = [("q", "app.quit", "quit")]

    def __init__(self, project) -> None:
        super().__init__()
        self.project = Path(project)
        self.cursor = 0

    def compose(self) -> ComposeResult:
        with Vertical(id="shell"):
            yield Brand(id="brand")
            with Horizontal(id="panes"):
                with Vertical(id="panel"):
                    for i in range(len(FIRST_RUN)):
                        yield FirstRunRow(i, id=f"fr{i}", classes="task")
                with Vertical(id="side"):
                    yield Static(id="side-body")
            yield Static(id="detail")
            yield Static(id="keys")

    def on_mount(self) -> None:
        self.query_one("#panel").border_title = "first-time setup"
        self.query_one("#side").border_title = "what it does"
        self.paint()

    def paint(self) -> None:
        folder = str(self.project)
        try:
            folder = "~/" + str(self.project.resolve().relative_to(Path.home()))
        except (ValueError, OSError):
            pass
        self.query_one("#brand", Brand).render_frame(
            0.0, folder if self.narrow else f"{folder}  ·  the team is not set up here",
            self.narrow)
        for i in range(len(FIRST_RUN)):
            self.query_one(f"#fr{i}", FirstRunRow).render_frame(i == self.cursor)

        _action, label, blurb = FIRST_RUN[self.cursor]
        body = Text("\n")
        for line in _wrap(label, 26):
            body.append(f"  {line}\n", style=f"bold {ACCENT}")
        body.append("\n")
        for line in _wrap(blurb, 26):
            body.append(f"  {line}\n", style=TEXT)
        self.query_one("#side-body", Static).update(body)

        d = Text("  ")
        d.append("│ ", style=TRACK)
        d.append(f"no team configuration in {folder}", style=HINT)
        self.query_one("#detail", Static).update(d)

        k = Text("  ")
        for name, desc in (("↑↓", "move"), ("enter", "choose"), ("esc", "skip")):
            k.append(name, style=KEY)
            k.append(f" {desc}   ", style=HINT)
        self.query_one("#keys", Static).update(k)

    def on_key(self, event) -> None:
        if event.key in ("down", "j"):
            self.cursor = (self.cursor + 1) % len(FIRST_RUN)
        elif event.key in ("up", "k"):
            self.cursor = (self.cursor - 1) % len(FIRST_RUN)
        elif event.key == "enter":
            event.stop()
            self._choose(FIRST_RUN[self.cursor][0])
            return
        else:
            return
        event.stop()
        self.paint()

    def _choose(self, action: str) -> None:
        opener = getattr(self.app, "open_launcher", None)
        if action == "skip":
            # Esc and "Not now" both mean "carry on unconfigured" - v1 distinguishes
            # those from backing out entirely, which exits without launching.
            if opener:
                self.app.switch_screen(opener())
            return
        runner = getattr(self.app, "start_action", None)
        if runner:
            # Setup finishes and hands you the launcher, as v1 does ("Setup complete -
            # continuing the launch"), rather than leaving you on a done screen.
            runner(action, project=self.project, back=True)

    def key_escape(self, event) -> None:
        event.stop()
        self._choose("skip")


class ArchiveScreen(Responsive):
    """[a] - pick ONE, or all, with the consequence stated before you press the key.

    v2 ran run_archive_engagements, which archives every closed pack with no selection:
    a different operation under the same key. And the ARCHIVED-OPEN consequence was
    nowhere on screen - v1 puts it there deliberately, "because it is the thing a person
    needs before pressing the key, not after".
    """

    BINDINGS = [("q", "app.quit", "quit")]

    def __init__(self, project, rows=None) -> None:
        super().__init__()
        self.project = Path(project)
        self.engagements = list(rows or [])
        self.picked: set = set()
        self.cursor = 0
        self.note = ""

    def compose(self) -> ComposeResult:
        with Vertical(id="shell"):
            yield Brand(id="brand")
            with Horizontal(id="panes"):
                with VerticalScroll(id="panel"):
                    yield Static(id="archive-rows")
                with Vertical(id="side"):
                    yield Static(id="side-body")
            yield Static(id="detail")
            yield Static(id="keys")

    def on_mount(self) -> None:
        self.query_one("#panel").border_title = f"{len(self.engagements)} open"
        self.query_one("#side").border_title = "consequence"
        self.paint()

    def paint(self) -> None:
        self.query_one("#brand", Brand).render_frame(
            0.0, "archive" if self.narrow else "archive engagements", self.narrow)

        t = Text()
        if not self.engagements:
            t.append("\n  nothing open to archive in this folder\n", style=HINT)
        for i, v in enumerate(self.engagements):
            sel = i == self.cursor
            t.append("  ▸ " if sel else "    ", style=ACCENT if sel else HINT)
            t.append("[", style=TRACK)
            t.append("✓" if i in self.picked else " ", style=OK)
            t.append("]  ", style=TRACK)
            title = v.get("title") or "?"
            t.append(title[:38], style=f"bold {TEXT}" if sel else TEXT)
            t.append("   " + (v.get("status") or ""), style=HINT)
            t.append("\n")
        self.query_one("#archive-rows", Static).update(t)

        body = Text("\n")
        body.append("  Archiving in place\n\n", style=f"bold {ACCENT}")
        for line in _wrap("Nothing is deleted. The pack moves out of the resume list "
                          "and stays exactly as it is.", 26):
            body.append(f"  {line}\n", style=TEXT)
        body.append("\n")
        for line in _wrap("An OPEN pack archives with --force and then shows as "
                          "ARCHIVED-OPEN in checks.", 26):
            body.append(f"  {line}\n", style=GOLD)
        self.query_one("#side-body", Static).update(body)

        d = Text("  ")
        d.append("│ ", style=TRACK)
        d.append(self.note or f"{len(self.picked)} selected", style=GOLD if self.note else HINT)
        self.query_one("#detail", Static).update(d)

        k = Text("  ")
        for name, desc in (("↑↓", "move"), ("space", "pick"), ("a", "all"),
                           ("enter", "archive"), ("esc", "back")):
            k.append(name, style=KEY)
            k.append(f" {desc}   ", style=HINT)
        self.query_one("#keys", Static).update(k)

    def on_key(self, event) -> None:
        k = event.key
        if k == "escape":
            self.key_escape(event)
            return
        if not self.engagements:
            return
        if k == "down":
            self.cursor = (self.cursor + 1) % len(self.engagements)
        elif k == "up":
            self.cursor = (self.cursor - 1) % len(self.engagements)
        elif k == "space":
            if self.cursor in self.picked:
                self.picked.discard(self.cursor)
            else:
                self.picked.add(self.cursor)
        elif k == "a":
            self.picked = set(range(len(self.engagements)))
        elif k == "enter":
            event.stop()
            self._archive()
            return
        else:
            return
        event.stop()
        self.paint()

    def _archive(self) -> None:
        chosen = [self.engagements[i] for i in sorted(self.picked)]
        if not chosen:
            self.note = "nothing picked - space to pick, a for all"
            self.paint()
            return
        doer = getattr(self.app, "archive_engagements", None)
        if not doer:
            self.note = "archiving needs the engine"
            self.paint()
            return
        try:
            self.note = doer(self.project, chosen)
        except Exception as exc:        # noqa: BLE001
            self.note = f"could not archive: {exc}"
        self.picked.clear()
        self.paint()

    def key_escape(self, event) -> None:
        event.stop()
        if len(self.app.screen_stack) > 2:
            self.app.pop_screen()
        else:
            self.app.exit()


class BrowseScreen(Responsive):
    """[b] - done & archived engagements, with review, sign-off and supersede.

    v2 routed [b] at run_list_engagements, a read-only listing: no token came back, so
    --review was unreachable and so was human sign-off - the control that exists
    precisely so an agent cannot sign off its own work.
    """

    BINDINGS = [("q", "app.quit", "quit")]

    def __init__(self, project, rows=None, note: str = "") -> None:
        super().__init__()
        self.project = Path(project)
        self.engagements = list(rows or [])
        self.note = note
        self.cursor = 0

    def compose(self) -> ComposeResult:
        with Vertical(id="shell"):
            yield Brand(id="brand")
            with Horizontal(id="panes"):
                with VerticalScroll(id="panel"):
                    yield Static(id="browse-rows")
                with Vertical(id="side"):
                    yield Static(id="side-body")
            yield Static(id="detail")
            yield Static(id="keys")

    def on_mount(self) -> None:
        n = len(self.engagements)
        self.query_one("#panel").border_title = f"{n} done or archived" if n else "nothing yet"
        self.query_one("#side").border_title = "detail"
        self.paint()

    def reload(self) -> None:
        reader = getattr(self.app, "finished_engagements", None)
        if reader:
            self.engagements, note = reader(self.project)
            if note:
                self.note = note
        self.cursor = min(self.cursor, max(0, len(self.engagements) - 1))
        self.paint()

    def paint(self) -> None:
        self.query_one("#brand", Brand).render_frame(
            0.0, "done & archived" if self.narrow else "done & archived engagements",
            self.narrow)

        t = Text()
        if not self.engagements:
            t.append(f"\n  {self.note or 'nothing done or archived here yet'}\n", style=HINT)
        for i, v in enumerate(self.engagements):
            sel = i == self.cursor
            t.append("  ▸ " if sel else "    ", style=ACCENT if sel else HINT)
            title = v.get("title") or "?"
            # Short enough that the state tags stay on the same line - a row that wraps
            # puts "archived / unsigned" under the wrong engagement.
            width = 24 if self.narrow else 34
            shown = title if len(title) <= width else title[: width - 1] + "…"
            t.append(shown.ljust(width), style=f"bold {TEXT}" if sel else TEXT)
            t.append(("archived" if v.get("archived") else "done").ljust(9), style=HINT)
            # Signed vs unsigned is the whole point of the screen, so it is on the row.
            if v.get("signed"):
                t.append("   ✓ signed off", style=OK)
            else:
                t.append("   unsigned", style=GOLD)
            t.append("\n")
        self.query_one("#browse-rows", Static).update(t)

        body = Text("\n")
        if self.engagements:
            v = self.engagements[self.cursor]
            for line in _wrap(v.get("title") or "?", 26):
                body.append(f"  {line}\n", style=f"bold {ACCENT}")
            body.append("\n")
            for label, value in v.get("lines") or []:
                body.append(f"  {label:<10}", style=HINT)
                body.append(f"{value}\n", style=TEXT)
            body.append("\n  sign-off  ", style=HINT)
            body.append(v.get("signed") or "not signed off", style=OK if v.get("signed") else GOLD)
            body.append("\n")
        self.query_one("#side-body", Static).update(body)

        d = Text("  ")
        d.append("│ ", style=TRACK)
        d.append(self.note or "opening one is read-only - it never reopens a closed pack",
                 style=GOLD if self.note else HINT)
        self.query_one("#detail", Static).update(d)

        k = Text("  ")
        for name, desc in (("↑↓", "move"), ("enter", "open read-only"),
                           ("s", "sign off"), ("n", "supersede"), ("esc", "back")):
            k.append(name, style=KEY)
            k.append(f" {desc}   ", style=HINT)
        self.query_one("#keys", Static).update(k)

    def on_key(self, event) -> None:
        if not self.engagements:
            if event.key == "escape":
                self.key_escape(event)
            return
        v = self.engagements[self.cursor]
        k = event.key
        if k == "down":
            self.cursor = (self.cursor + 1) % len(self.engagements)
        elif k == "up":
            self.cursor = (self.cursor - 1) % len(self.engagements)
        elif k == "enter":
            event.stop()
            self._decide(getattr(self.app, "review_decision")(self.project, v["token"])
                         if hasattr(self.app, "review_decision") else "")
            return
        elif k == "n":
            event.stop()
            self._decide(getattr(self.app, "supersede_decision")(self.project, v["token"])
                         if hasattr(self.app, "supersede_decision") else "")
            return
        elif k == "s":
            event.stop()
            signer = getattr(self.app, "sign_off", None)
            if signer and v.get("token"):
                try:
                    self.note = signer(self.project, v["token"]) or "signed off"
                except Exception as exc:    # noqa: BLE001
                    self.note = f"could not sign off: {exc}"
            self.reload()
            return
        else:
            return
        event.stop()
        self.paint()

    def _decide(self, decision: str) -> None:
        if not decision:
            self.note = "no token for this engagement"
            self.paint()
            return
        self.app.decision = decision
        self.app.exit()

    def key_escape(self, event) -> None:
        event.stop()
        if len(self.app.screen_stack) > 2:
            self.app.pop_screen()
        else:
            self.app.exit()


class JiraScreen(Responsive):
    """[j] - start an engagement from a ticket.

    Emits the decision virt_team_launcher._jira_command builds, so the spelling cannot
    drift from what `virt-surv go` hands Claude Code for the same choice.
    """

    BINDINGS = [("q", "app.quit", "quit")]

    def __init__(self, project) -> None:
        super().__init__()
        self.project = Path(project)

    def compose(self) -> ComposeResult:
        with Vertical(id="shell"):
            yield Brand(id="brand")
            with Vertical(id="panel"):
                yield Static(id="open-help")
            yield Input(placeholder="e.g. ABC-123 or a ticket URL", id="edit")
            yield Static(id="detail")
            yield Static(id="keys")

    def on_mount(self) -> None:
        # Jira write-back is unusable in the "on (key UNSET)" state, and v2 had no way
        # out of it: it could start work FROM a ticket but never name the project key.
        needs = getattr(self.app, "jira_needs_key", None)
        self.needs_key = bool(needs(self.project)) if needs else False
        self.query_one("#panel").border_title = (
            "Jira project key" if self.needs_key else "from a Jira ticket")
        h = Text()
        if self.needs_key:
            h.append("\n  Jira write-back is on, but no project key is set\n\n",
                     style=f"bold {GOLD}")
            h.append("  Until it is, the team cannot raise or update an issue.\n",
                     style=TEXT)
            h.append("  Enter the key (e.g. SURV) to finish turning it on.\n", style=TEXT)
            self.query_one("#open-help", Static).update(h)
            inp = self.query_one("#edit", Input)
            inp.placeholder = "project key, e.g. SURV"
            self.call_after_refresh(inp.focus)
            d = Text("  ")
            d.append("│ ", style=TRACK)
            d.append("esc leaves it unset", style=HINT)
            self.query_one("#detail", Static).update(d)
            k = Text("  ")
            for name, desc in (("enter", "save the key"), ("esc", "back")):
                k.append(name, style=KEY)
                k.append(f" {desc}   ", style=HINT)
            self.query_one("#keys", Static).update(k)
            return
        h.append("\n  Which ticket?\n\n", style=f"bold {ACCENT}")
        h.append("  The engagement opens with the ticket's summary and acceptance\n",
                 style=TEXT)
        h.append("  criteria already read in.\n", style=TEXT)
        self.query_one("#open-help", Static).update(h)
        inp = self.query_one("#edit", Input)
        self.call_after_refresh(inp.focus)
        d = Text("  ")
        d.append("│ ", style=TRACK)
        d.append("enter starts the session with it; esc goes back", style=HINT)
        self.query_one("#detail", Static).update(d)
        k = Text("  ")
        for name, desc in (("enter", "start"), ("esc", "back")):
            k.append(name, style=KEY)
            k.append(f" {desc}   ", style=HINT)
        self.query_one("#keys", Static).update(k)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        ref = event.value.strip()
        if not ref:
            self.app.pop_screen()
            return
        if getattr(self, "needs_key", False):
            setter = getattr(self.app, "set_jira_key", None)
            if setter:
                setter(self.project, ref)
            self.needs_key = False
            self.on_mount()             # re-render as the ticket prompt
            self.query_one("#edit", Input).value = ""
            return
        builder = getattr(self.app, "jira_decision", None)
        self.app.decision = (builder(self.project, ref) if builder
                             else f"{getattr(self.app, 'engage_cmd', '')} --new --jira {ref}")
        self.app.exit()

    def key_escape(self, event) -> None:
        event.stop()
        self.app.pop_screen()


class OpenProjectScreen(Responsive):
    """Point the launcher at a different folder without leaving it."""

    BINDINGS = [("q", "app.quit", "quit")]

    def __init__(self, project) -> None:
        super().__init__()
        self.project = Path(project)

    def compose(self) -> ComposeResult:
        with Vertical(id="shell"):
            yield Brand(id="brand")
            with Vertical(id="panel"):
                yield Static(id="open-help")
            yield Input(placeholder="path to a project folder", id="edit")
            yield Static(id="detail")
            yield Static(id="keys")

    def on_mount(self) -> None:
        self.query_one("#panel").border_title = "open a folder"
        h = Text()
        h.append("\n  Which project folder?\n\n", style=f"bold {ACCENT}")
        h.append("  The launcher re-reads engagements for whatever you name here.\n",
                 style=TEXT)
        h.append("  Blank keeps the current one.\n", style=HINT)
        # v1's explorer offers the folders it has seen; a bare Input made you retype a
        # path you have already been in.
        getter = getattr(self.app, "recent_projects", None)
        recents = getter() if getter else []
        if recents:
            h.append("\n  Recent\n", style=f"bold {HINT}")
            for r in recents[:6]:
                h.append(f"    {r}\n", style=DIM)
        self.query_one("#open-help", Static).update(h)
        inp = self.query_one("#edit", Input)
        inp.value = str(self.project)
        self.call_after_refresh(inp.focus)
        d = Text("  ")
        d.append("│ ", style=TRACK)
        d.append(f"currently {self.project}", style=HINT)
        self.query_one("#detail", Static).update(d)
        k = Text("  ")
        for name, desc in (("enter", "open"), ("esc", "cancel")):
            k.append(name, style=KEY)
            k.append(f" {desc}   ", style=HINT)
        self.query_one("#keys", Static).update(k)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        target = Path(event.value.strip() or self.project).expanduser()
        opener = getattr(self.app, "open_launcher", None)
        if not target.is_dir():
            d = Text("  ")
            d.append("✗ ", style=ERR)
            d.append(f"not a directory: {target}", style=HINT)
            self.query_one("#detail", Static).update(d)
            return
        if opener:
            self.app.switch_screen(opener(target))
        else:
            self.app.pop_screen()

    def key_escape(self, event) -> None:
        event.stop()
        self.app.pop_screen()


class MenuRow(Static):
    def __init__(self, index: int, **kw) -> None:
        super().__init__(**kw)
        self.index = index

    def render_frame(self, selected: bool) -> None:
        key, _action, label, _blurb = MAIN_MENU[self.index]
        t = Text()
        t.append("▸ " if selected else "  ", style=ACCENT if selected else HINT)
        t.append(f"[{key}] ", style=KEY)
        t.append(label, style=f"bold {TEXT}" if selected else TEXT)
        self.update(t)
        self.set_class(selected, "-selected")


class MenuScreen(Responsive):
    BINDINGS = [("q", "app.quit", "quit"), ("escape", "app.quit", "quit")]

    def __init__(self) -> None:
        super().__init__()
        self.cursor = 0

    def compose(self) -> ComposeResult:
        with Vertical(id="shell"):
            yield Brand(id="brand")
            with Horizontal(id="panes"):
                with Vertical(id="panel"):
                    for i in range(len(MAIN_MENU)):
                        yield MenuRow(i, id=f"menu{i}", classes="task")
                with Vertical(id="side"):
                    yield Static(id="side-body")
            yield Static(id="detail")
            yield Static(id="keys")

    def on_mount(self) -> None:
        self.query_one("#panel").border_title = "what can I do for you?"
        self.query_one("#side").border_title = "what it does"
        self.paint()

    def paint(self) -> None:
        self.query_one("#brand", Brand).render_frame(
            0.0, "virt-surv2" if self.narrow else "virt-surv2  ·  same engine, new front end",
            self.narrow)
        for i in range(len(MAIN_MENU)):
            self.query_one(f"#menu{i}", MenuRow).render_frame(i == self.cursor)

        _key, _action, label, blurb = MAIN_MENU[self.cursor]
        body = Text("\n")
        for line in _wrap(label, 26):
            body.append(f"  {line}\n", style=f"bold {ACCENT}")
        body.append("\n")
        for line in _wrap(blurb, 26):
            body.append(f"  {line}\n", style=TEXT)
        self.query_one("#side-body", Static).update(body)

        d = Text("  ")
        d.append("│ ", style=TRACK)
        d.append("nothing runs until you choose it", style=HINT)
        self.query_one("#detail", Static).update(d)

        k = Text("  ")
        for name, desc in (("↑↓", "move"), ("enter", "choose"), ("1-5 u", "jump"),
                           ("q", "quit")):
            k.append(name, style=KEY)
            k.append(f" {desc}   ", style=HINT)
        self.query_one("#keys", Static).update(k)

    def on_key(self, event) -> None:
        keys = [row[0] for row in MAIN_MENU]
        if event.key in ("down", "j"):
            self.cursor = (self.cursor + 1) % len(MAIN_MENU)
        elif event.key in ("up", "k"):
            self.cursor = (self.cursor - 1) % len(MAIN_MENU)
        elif event.key in keys:
            self.cursor = keys.index(event.key)
            self._choose()
            return
        elif event.key == "enter":
            self._choose()
            return
        else:
            return
        event.stop()
        self.paint()

    def _choose(self) -> None:
        action = MAIN_MENU[self.cursor][1]
        if action == "quit":
            self.app.exit()
        elif action == "full":
            opener = getattr(self.app, "open_decide", None)
            self.app.push_screen(opener() if opener else DecideScreen())
        elif action in ("advanced", "diagnostics"):
            self.app.push_screen(AdvancedScreen(action))
        else:
            runner = getattr(self.app, "start_action", None)
            if runner:
                runner(action)


class VirtSurvApp(App):
    # Absolute: Textual resolves a relative CSS_PATH against the SUBCLASS's
    # module file, so any subclass defined elsewhere looked for ui.tcss beside
    # itself and failed to start.
    CSS_PATH = str(Path(__file__).resolve().parent / "ui.tcss")

    # The launcher's stdout contract, so the screen-only app answers it too rather
    # than raising the moment a launcher row is chosen.
    decision = None
    engage_cmd = "/compliance-surveillance-team:engage"
    # The screen-only app has no engine, so the settings screen renders empty with a
    # note rather than pretending to show a project's configuration.
    settings_rows = None
    settings_apply = None
    settings_restore = None
    finished_engagements = None
    recent_projects = None
    archive_engagements = None
    jira_needs_key = None


    def _fatal_error(self) -> None:
        """Report a crash without rich.traceback, which needs pygments.

        pygments is deliberately NOT vendored (tests/test_virt_team_launcher.py pins
        that: rich's Console/Table/Panel/Rule need neither it nor markdown-it). Textual's
        default handler imports rich.traceback anyway, so on a real user's machine a
        crash surfaced as ModuleNotFoundError: pygments - the one moment you need the
        actual cause, replaced by a message about a package you never asked for.

        Plain traceback to stderr instead: no dependency, and the cause survives.
        """
        import traceback as _tb

        self.bell()
        exc = getattr(self, "_exception", None)
        try:
            self._exit_renderables.append(
                "".join(_tb.format_exception(type(exc), exc, exc.__traceback__))
                if exc is not None else "virt-surv2 stopped unexpectedly."
            )
        except Exception:               # noqa: BLE001 — reporting must never re-raise
            self._exit_renderables.append("virt-surv2 stopped unexpectedly.")
        self.exit()

    def __init__(self, start: str = "decide", frozen: bool = False, done: bool = False,
                 project=None, rows=None, note: str = "") -> None:
        super().__init__()
        self.start, self.frozen, self.done = start, frozen, done
        self.project, self.rows, self.note = project, rows, note

    def on_mount(self) -> None:
        if self.start == "install":
            self.push_screen(InstallScreen(frozen=self.frozen, done=self.done))
        elif self.start == "launch":
            self.push_screen(LaunchScreen(self.project, self.rows, self.note))
        elif self.start == "settings":
            self.push_screen(SettingsScreen(str(self.project) if self.project
                                            else "~/www/my-project"))
        elif self.start == "advanced":
            self.push_screen(AdvancedScreen())
        elif self.start == "diagnostics":
            self.push_screen(AdvancedScreen("diagnostics"))
        elif self.start == "menu":
            self.push_screen(MenuScreen())
        else:
            self.push_screen(DecideScreen())


async def shoot(out: Path, start: str, done: bool, size: tuple | None = None) -> None:
    app = VirtSurvApp(start=start, frozen=True, done=done)
    # The launcher is a two-pane screen with more rows; sizing every shot to the
    # narrowest one is what clipped its footer.
    size = size or ((104, 34) if start in ("launch", "settings") else (92, 30))
    async with app.run_test(size=size):
        out.write_text(app.export_screenshot(), encoding="utf-8")
