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
        self.paint()

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
    (
        "After install",
        [
            Decision("project", "Enable for project", "path", "~/www/my-project", ""),
        ],
    ),
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
            keys = (("↑↓", "move"), ("space", "toggle"), ("i", "install"), ("q", "quit"))
        elif d.kind == "choice":
            keys = (("↑↓", "move"), ("←→", "change"), ("i", "install"), ("q", "quit"))
        else:
            keys = (("↑↓", "move"), ("enter", "edit"), ("i", "install"), ("q", "quit"))
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
    def __init__(self, kind: str, payload: Any, **kw) -> None:
        super().__init__(**kw)
        self.kind, self.payload = kind, payload

    def render_frame(self, selected: bool) -> None:
        t = Text()
        t.append("▸ " if selected else "  ", style=ACCENT if selected else HINT)
        if self.kind == "eng":
            name, mark, colour, tag, _ = ENGAGEMENTS[self.payload]
            t.append(mark + " ", style=colour)
            t.append(name, style=f"bold {TEXT}" if selected else TEXT)
            if tag:
                t.append(f"   ← {tag}", style=OK)
        else:
            key, label, _ = ACTIONS[self.payload]
            t.append(f"[{key}] " if key else "    ", style=KEY)
            t.append(label, style=f"bold {TEXT}" if selected else TEXT)
        self.update(t)
        self.set_class(selected, "-selected")


class LaunchScreen(Responsive):
    BINDINGS = [("q", "app.quit", "quit"), ("escape", "app.quit", "back")]

    def __init__(self) -> None:
        super().__init__()
        self.selectable = [i for i, (k, _) in enumerate(LAUNCH_ROWS) if k != "group"]
        self.cursor = 0

    def compose(self) -> ComposeResult:
        with Vertical(id="shell"):
            yield Brand(id="brand")
            with Horizontal(id="panes"):
                with Vertical(id="panel"):
                    for i, (kind, payload) in enumerate(LAUNCH_ROWS):
                        if kind == "group":
                            yield Static(payload, classes="group -first" if i == 0 else "group")
                        else:
                            yield LaunchRow(kind, payload, id=f"lrow{i}", classes="task")
                with Vertical(id="side"):
                    yield Static(id="side-body")
            yield Static(id="detail")
            yield Static(id="keys")

    def on_mount(self) -> None:
        self.query_one("#panel").border_title = f"{len(ENGAGEMENTS)} open"
        self.query_one("#side").border_title = "detail"
        k = Text("  ")
        for name, desc in (("↑↓", "move"), ("enter", "choose"), ("?", "help"),
                           ("esc", "back to terminal")):
            k.append(name, style=KEY)
            k.append(f" {desc}   ", style=HINT)
        self.query_one("#keys", Static).update(k)
        self.paint()

    def paint(self) -> None:
        sub = ("my-project  ·  dev" if self.narrow
               else "my-project  ·  v0.34.0  ·  dev  ·  4 agents idle")
        self.query_one("#brand", Brand).render_frame(0.0, sub, self.narrow)
        sel_row = self.selectable[self.cursor]
        for i, (kind, payload) in enumerate(LAUNCH_ROWS):
            if kind == "group":
                continue
            self.query_one(f"#lrow{i}", LaunchRow).render_frame(i == sel_row)

        # The detail pane. The settings screen already makes each SETTING explain
        # itself; doing the same for actions costs nothing and removes the last
        # place where you had to guess what a key does.
        kind, payload = LAUNCH_ROWS[sel_row]
        t = Text("\n")
        if kind == "eng":
            name, _m, _c, _tag, lines = ENGAGEMENTS[payload]
            t.append(f"  {name}\n\n", style=f"bold {ACCENT}")
            for label, value in lines:
                t.append(f"  {label:<10}", style=HINT)
                warn = label in ("status", "next") and value in ("blocked", "await venue data feed")
                t.append(f"{value}\n", style=GOLD if warn else TEXT)
        else:
            key, label, blurb = ACTIONS[payload]
            t.append(f"  {label}\n\n", style=f"bold {ACCENT}")
            for line in _wrap(blurb, 26):
                t.append(f"  {line}\n", style=DIM)
            if key:
                t.append(f"\n  shortcut  ", style=HINT)
                t.append(key, style=KEY)
        self.query_one("#side-body", Static).update(t)

        d = Text("  ")
        if self.narrow:
            d.append("│ ", style=TRACK)
            if kind == "eng":
                name, _m, _c, _tag, lines = ENGAGEMENTS[payload]
                d.append(f"{dict(lines)['status']} · next: {dict(lines)['next']}", style=HINT)
            else:
                d.append(ACTIONS[payload][2], style=HINT)
        else:
            d.append("⚠ ", style=GOLD)
            d.append("wash-trade-pack has been open 11 days", style=HINT)
        self.query_one("#detail", Static).update(d)

    def on_key(self, event) -> None:
        kind, payload = LAUNCH_ROWS[self.selectable[self.cursor]]
        if event.key in ("down", "j"):
            self.cursor = (self.cursor + 1) % len(self.selectable)
        elif event.key in ("up", "k"):
            self.cursor = (self.cursor - 1) % len(self.selectable)
        elif event.key == "c" or (event.key == "enter" and kind == "act"
                                  and ACTIONS[payload][0] == "c"):
            event.stop()
            self.app.push_screen(SettingsScreen())
            return
        else:
            return
        event.stop()
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
from .settings_data import SETTING_GROUPS  # noqa: E402

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
        if r["kind"] == "toggle":
            on = bool(r["value"])
            t.append("[", style=TRACK)
            t.append("✓" if on else " ", style=OK if on else TRACK)
            t.append("] ", style=TRACK)
            t.append("on" if on else "off", style=OK if on else HINT)
        else:
            for opt in r["options"]:
                sel = opt == r["value"]
                t.append(opt + "  ", style=f"bold {ACCENT}" if sel else HINT)
        self.update(t)
        self.set_class(selected, "-selected")


class SettingsScreen(Responsive):
    BINDINGS = [("q", "app.quit", "quit")]

    def __init__(self, project: str = "~/www/my-project") -> None:
        super().__init__()
        self.project = project
        self.groups = [(title, [dict(r) for r in rows]) for title, rows in SETTING_GROUPS]
        self.rows = [r for _title, rows in self.groups for r in rows]
        self.defaults = {r["label"]: r["value"] for r in self.rows}
        self.cursor = 0
        self.changed: list[str] = []

    def compose(self) -> ComposeResult:
        with Vertical(id="shell"):
            yield Brand(id="brand")
            with Horizontal(id="panes"):
                with VerticalScroll(id="panel"):
                    for gi, (title, rows) in enumerate(self.groups):
                        yield Static(title, classes="group -first" if gi == 0 else "group")
                        for r in rows:
                            yield SettingRow(r, id=f"set-{r['key'].replace('.', '-')}",
                                             classes="task")
                with Vertical(id="side"):
                    yield Static(id="side-body")
            yield Static(id="detail")
            yield Static(id="keys")

    def on_mount(self) -> None:
        self.query_one("#panel").border_title = f"{len(self.rows)} settings"
        self.query_one("#side").border_title = "what it does"
        self.paint()

    def _row_widget(self, r: dict) -> SettingRow:
        return self.query_one(f"#set-{r['key'].replace('.', '-')}", SettingRow)

    def paint(self) -> None:
        self.query_one("#brand", Brand).render_frame(
            0.0, self.project if self.narrow else f"{self.project}  ·  project settings",
            self.narrow)
        for i, r in enumerate(self.rows):
            self._row_widget(r).render_frame(i == self.cursor, self.narrow)

        cur = self.rows[self.cursor]
        # The highlighted setting explains ITSELF — the pane that described the screen's
        # keys answered a question everyone had already worked out, while "what does this
        # one DO?" went unanswered.
        body = Text("\n")
        body.append(f"  {cur['label']}\n\n", style=f"bold {ACCENT}")
        for line in _wrap(cur["what"], 26):
            body.append(f"  {line}\n", style=TEXT)
        if cur["off"]:
            body.append("\n")
            for line in _wrap(cur["off"], 26):
                body.append(f"  {line}\n", style=HINT)
        if cur.get("needs"):
            body.append("\n")
            for line in _wrap(cur["needs"], 26):
                body.append(f"  {line}\n", style=GOLD)
        body.append("\n  currently: ", style=HINT)
        val = cur["value"]
        shown = ("on" if val else "off") if cur["kind"] == "toggle" else str(val)
        body.append(shown, style=OK if (val is True or cur["kind"] == "choice") else HINT)
        if self.defaults[cur["label"]] != val:
            body.append("   (changed)", style=GOLD)
        self.query_one("#side-body", Static).update(body)

        d = Text("  ")
        d.append("│ ", style=TRACK)
        if self.narrow:
            d.append(cur["what"][:70], style=HINT)
        elif self.changed:
            d.append(f"{len(self.changed)} changed — applies to {self.project} only", style=GOLD)
        else:
            d.append(f"applies to {self.project} only, not to your other projects", style=HINT)
        self.query_one("#detail", Static).update(d)

        keys = [("↑↓", "move")]
        keys.append(("←→", "change") if cur["kind"] == "choice" else ("space", "toggle"))
        keys += [("d", "defaults"), ("esc", "back")]
        k = Text("  ")
        for name, desc in keys:
            k.append(name, style=KEY)
            k.append(f" {desc}   ", style=HINT)
        self.query_one("#keys", Static).update(k)

    def _note_change(self, r: dict) -> None:
        if r["value"] != self.defaults[r["label"]]:
            if r["label"] not in self.changed:
                self.changed.append(r["label"])
        elif r["label"] in self.changed:
            self.changed.remove(r["label"])

    def on_key(self, event) -> None:
        r = self.rows[self.cursor]
        k = event.key
        if k in ("down", "j"):
            self.cursor = (self.cursor + 1) % len(self.rows)
            self._row_widget(self.rows[self.cursor]).scroll_visible()
        elif k in ("up", "k"):
            self.cursor = (self.cursor - 1) % len(self.rows)
            self._row_widget(self.rows[self.cursor]).scroll_visible()
        elif k == "space" and r["kind"] == "toggle":
            r["value"] = not r["value"]
            self._note_change(r)
        elif k in ("left", "right") and r["kind"] == "choice":
            i = r["options"].index(r["value"])
            r["value"] = r["options"][(i + (1 if k == "right" else -1)) % len(r["options"])]
            self._note_change(r)
        elif k == "d":
            for row in self.rows:
                row["value"] = self.defaults[row["label"]]
            self.changed.clear()
        else:
            return
        event.stop()
        self.paint()

    def key_escape(self, event) -> None:
        # Back to the launcher when there is one, otherwise leave. Esc that quits an app
        # you opened a sub-screen from is the classic way to lose someone's place.
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
    ("formats", "Project preferences",
     "docx, citations, review tools."),
    ("model", "Morgan's model",
     "Per project only."),
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
    ("aliasmanage", "Manage the 'virt-surv' alias",
     "Register/update it, or change the 'go' launch command. This is v1's alias - "
     "the virt-surv2 shortcut is the item below."),
    ("alias2", "Register the 'virt-surv2' shortcut",
     "Adds a 'virt-surv2' shell function to ~/.bashrc (and ~/.zshrc if you have one) "
     "so you can run this from any folder. Shows the exact line first and writes "
     "nothing until you confirm. Leaves the 'virt-surv' alias untouched."),
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
SHELL_WRITERS = {"alias2", "fixbashrc", "aliasmanage", "gitbashperf"}


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
        body.append(f"  {label}\n\n", style=f"bold {ACCENT}")
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
            if action == "alias2":
                from .__main__ import alias_line
                body = Text("\n")
                body.append("  about to append\n\n", style=f"bold {GOLD}")
                for line in alias_line().splitlines():
                    for part in _wrap(line, 26):
                        body.append(f"  {part}\n", style=TEXT)
                body.append("\n  to ~/.bashrc\n", style=HINT)
                self.query_one("#side-body", Static).update(body)
            return

        self.armed = False
        if action == "alias2":
            from .__main__ import install_alias
            install_alias(write=True)
            self.note = "added to your shell profile — open a new terminal"
            return
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


class VirtSurvApp(App):
    CSS_PATH = "ui.tcss"

    def __init__(self, start: str = "decide", frozen: bool = False, done: bool = False) -> None:
        super().__init__()
        self.start, self.frozen, self.done = start, frozen, done

    def on_mount(self) -> None:
        if self.start == "install":
            self.push_screen(InstallScreen(frozen=self.frozen, done=self.done))
        elif self.start == "launch":
            self.push_screen(LaunchScreen())
        elif self.start == "settings":
            self.push_screen(SettingsScreen())
        elif self.start == "advanced":
            self.push_screen(AdvancedScreen())
        elif self.start == "diagnostics":
            self.push_screen(AdvancedScreen("diagnostics"))
        else:
            self.push_screen(DecideScreen())


async def shoot(out: Path, start: str, done: bool, size: tuple | None = None) -> None:
    app = VirtSurvApp(start=start, frozen=True, done=done)
    # The launcher is a two-pane screen with more rows; sizing every shot to the
    # narrowest one is what clipped its footer.
    size = size or ((104, 34) if start in ("launch", "settings") else (92, 30))
    async with app.run_test(size=size):
        out.write_text(app.export_screenshot(), encoding="utf-8")
