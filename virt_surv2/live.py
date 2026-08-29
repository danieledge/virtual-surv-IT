#!/usr/bin/env python3
"""The engine-driven screens: a real install, rendered live.

`app.py`'s InstallScreen is a fake with a timer. This one is driven entirely by the
three observer calls the engine already makes, so the step list, its order and its
count are whatever `Installer.build_plan()` decides — not a list copied into the UI.
"""

from __future__ import annotations

import threading

from rich.text import Text
from pathlib import Path

from textual.app import App, ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Input, Static

from .ui import (ACCENT, DIM, ERR, GOLD, HINT, KEY, OK, SPINNER, TEXT, TRACK,
                 Brand, DecideScreen, Responsive, bar)

STATUS_GLYPH = {"ok": ("✓", OK), "skip": ("–", HINT), "fail": ("✗", ERR)}

# build_plan()'s titles are written for a run that stops and asks. Here nothing is
# asked - the decide screen already answered - so a completed step reading "Quick setup
# or manual?" describes a choice the user never saw, and "(optional)" implies one they
# were never offered. Reported live: "I don't get asked any questions ... there was no
# quick install option as it indicated there was".
#
# The titles are RELABELLED, never dropped: every step the engine runs still appears,
# in its order, with its result. Only the wording changes.
TITLE_OVERRIDES = {
    # Named for what the step DID, in words that mean something to someone who has
    # never read this codebase. "Setup mode" was the first attempt and was no better
    # than the question it replaced - it named a mechanism, not an outcome.
    "Quick setup or manual?": "Applying your choices",
    "Guard interpreter cache": "Safety guard cache",
    "Pending hook fixes": "Hook updates",
    "Optional pip requirements": "Document output (.docx / .html)",
    "Code intelligence (optional)": "Code intelligence (tree-sitter)",
    "Claude Code marketplace": "Plugin marketplace",
    "Alias setup": "Shell shortcuts (virt-surv, virt-surv2)",
    "Machine defaults (optional)": "Machine defaults",
    "Enable for a project (optional)": "Enable for a project",
    "Status line (optional)": "Status line",
}


def display_title(title: str) -> str:
    return TITLE_OVERRIDES.get(title, title)


class PromptModal(ModalScreen):
    """A question the decide screen could not have answered — a dirty clone, an
    unusable claude CLI, an existing status line. The engine thread is blocked on
    `done` until this returns, so every path must set it."""

    def __init__(self, kind: str, prompt: str, default, box: dict, done: threading.Event,
                 context: str = ""):
        super().__init__()
        self.kind, self.prompt_text, self.default = kind, prompt, default
        self.box, self.done, self.context = box, done, context

    def compose(self) -> ComposeResult:
        with Vertical(id="modal"):
            yield Static(id="modal-q")
            yield Input(id="modal-input")
            yield Static(id="modal-keys")

    def on_mount(self) -> None:
        q = Text()
        # The dialog is opaque, so it has to carry its own context — otherwise you lose
        # all sense of where in the run the question came from.
        q.append(f"  {self.context or 'the installer is asking'}\n\n", style=GOLD)
        for line in _wrap(self.prompt_text.strip(), 60):
            q.append(f"  {line}\n", style=TEXT)
        self.query_one("#modal-q", Static).update(q)

        inp = self.query_one("#modal-input", Input)
        k = Text("  ")
        if self.kind == "confirm":
            inp.display = False
            # Hidden is not the same as unfocused. Textual auto-focuses the first
            # focusable widget, and clearing can_focus AFTERWARDS does not take the
            # focus back — the hidden Input kept swallowing "y"/"n" as text and on_key
            # was never reached. Only Esc got through, because Input ignores it.
            inp.can_focus = False
            self.set_focus(None)
            for name, desc in (("y", "yes"), ("n", "no"),
                               ("esc", f"default ({'yes' if self.default else 'no'})")):
                k.append(name, style=KEY)
                k.append(f" {desc}   ", style=HINT)
        else:
            inp.value = str(self.default or "")
            # Focus AFTER the refresh: when this screen is pushed from a worker thread
            # the widget is not laid out yet, focus() silently does not stick, and the
            # Input then never receives Enter — the modal became a dead end mid-install.
            self.call_after_refresh(inp.focus)
            for name, desc in (("enter", "accept"), ("esc", "use the default")):
                k.append(name, style=KEY)
                k.append(f" {desc}   ", style=HINT)
        self.query_one("#modal-keys", Static).update(k)

    def _answer(self, value) -> None:
        if self.done.is_set():
            return
        self.box["value"] = value
        self.done.set()
        self.dismiss()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._answer(event.value.strip() or self.default)

    def on_key(self, event) -> None:
        # Esc takes the default on BOTH kinds. Without it an ask-modal traps you: focus
        # is in the Input, so "q" is typed as text and the engine thread stays blocked.
        if event.key == "escape":
            self._answer(self.default)
            event.stop()
            return
        if self.kind != "confirm":
            # Enter is handled here as well as via on_input_submitted, so the answer
            # does not depend on the Input having won focus.
            if event.key == "enter":
                inp = self.query_one("#modal-input", Input)
                self._answer(inp.value.strip() or self.default)
                event.stop()
            return
        if event.key == "y":
            self._answer(True)
        elif event.key == "n":
            self._answer(False)
        elif event.key == "enter":
            self._answer(self.default)
        else:
            return
        event.stop()


class LiveInstallScreen(Responsive):
    BINDINGS = [("q", "app.quit", "quit"), ("escape", "app.quit", "back")]

    def __init__(self, choices: dict, demo: bool) -> None:
        super().__init__()
        self.choices, self.demo = choices, demo
        self.steps: list[dict] = []
        self.total = 0
        self.current = -1
        self.detail = "starting"
        self.frame = 0
        self.code: int | None = None
        self.failure: str | None = None
        self.crash_detail: str = ""
        self.asked: list = []
        self.self_updated = False

    def compose(self) -> ComposeResult:
        with Vertical(id="shell"):
            yield Brand(id="brand")
            yield Static("INSTALL" + ("  ·  DRY RUN" if self.demo else ""), id="eyebrow")
            with VerticalScroll(id="panel"):
                yield Static(id="steps")
            yield Static(id="detail")
            yield Static(id="keys")

    def on_mount(self) -> None:
        self.query_one("#panel").border_title = "running"
        k = Text("  ")
        for name, desc in (("q", "quit"),):
            k.append(name, style=KEY)
            k.append(f" {desc}   ", style=HINT)
        self.query_one("#keys", Static).update(k)
        self.set_interval(1 / 12, self._spin)
        self.paint()

    def _spin(self) -> None:
        self.frame += 1
        if self.code is None:
            self.paint()

    # ── the observer protocol lands here ──────────────────────────────────────
    def engine_step(self, number: int, total: int, title: str) -> None:
        self.total = total
        while len(self.steps) < number:
            self.steps.append({"title": "", "results": [], "state": "pending"})
        self.steps[number - 1]["title"] = display_title(title)
        for i in range(number - 1):
            if self.steps[i]["state"] == "active":
                self.steps[i]["state"] = "done"
        self.steps[number - 1]["state"] = "active"
        self.current = number - 1
        self.paint()

    def engine_result(self, name: str, status: str, detail: str = "") -> None:
        if 0 <= self.current < len(self.steps):
            self.steps[self.current]["results"].append((name, status, detail))
            if status == "fail":
                self.steps[self.current]["state"] = "fail"
        self.detail = f"{name}{(' — ' + detail) if detail else ''}"
        self.paint()

    def engine_line(self, text: str) -> None:
        clean = text.strip()
        if clean:
            self.detail = clean
        self.paint()

    def engine_finished(self, code: int, asked: list, failure: str | None = None) -> None:
        self.code, self.failure, self.asked = code, failure, asked
        for s in self.steps:
            if s["state"] == "active":
                s["state"] = "done" if code == 0 else "fail"
        if failure:
            self.detail = failure
        elif code == 0:
            self.detail = "installed"
        elif code == 130:
            self.detail = "cancelled"
        else:
            self.detail = f"the installer stopped (exit {code}) — see the steps above"
        try:
            self.query_one("#panel").border_title = "done" if code == 0 else "stopped"
        except Exception:               # noqa: BLE001 — cosmetic only
            pass
        k = Text("  ")
        for name, desc in (("q", "quit"), ("r", "change & retry")) if code else (("q", "quit"),):
            k.append(name, style=KEY)
            k.append(f" {desc}   ", style=HINT)
        self.query_one("#keys", Static).update(k)
        self.paint()

    def on_key(self, event) -> None:
        # Only once the run is over: r during a run would leave a worker behind.
        if event.key == "r" and self.code is not None:
            event.stop()
            if len(self.app.screen_stack) > 2:
                self.app.pop_screen()          # back to decide, choices intact

    def _show_next_steps(self) -> None:
        """What to do next, in the panel where the steps were.

        The install cannot enable a project for you and should not pretend to: that is
        a decision taken from inside the project, and `virt-surv go` makes it on first
        use. So this says so, once, where you are already looking.
        """
        t = Text()
        t.append("\n  ✓  installed\n\n", style=f"bold {OK}")
        t.append("  Next\n\n", style=f"bold {GOLD}")
        t.append("    1  ", style=HINT)
        t.append("open a new terminal", style=TEXT)
        t.append("   or  ", style=HINT)
        t.append(". $PROFILE", style=ACCENT)
        t.append("  /  ", style=HINT)
        t.append("source ~/.bashrc", style=ACCENT)
        t.append("\n", style=HINT)
        t.append("    2  ", style=HINT)
        t.append("cd", style=ACCENT)
        t.append(" into the project you want the team on\n", style=TEXT)
        t.append("    3  run ", style=HINT)
        t.append("virt-surv go", style=ACCENT)
        t.append("   it sets the project up on first use\n", style=TEXT)
        t.append("\n  A Claude Code session already open elsewhere needs a restart.\n",
                 style=HINT)
        if self.self_updated:
            t.append("\n  The installer updated itself during this run - run ", style=GOLD)
            t.append("virt-surv2", style=ACCENT)
            t.append(" again\n  to pick up the new version.\n", style=GOLD)
        self.query_one("#steps", Static).update(t)

    # ── prompts ─────────────────────────────────────────────────────────────
    def open_prompt(self, kind, prompt, default, box, done) -> None:
        ctx = "the installer is asking"
        if 0 <= self.current < len(self.steps) and self.total:
            ctx = f"step {self.current + 1} of {self.total}  ·  {self.steps[self.current]['title']}"
        self.app.push_screen(PromptModal(kind, prompt, default, box, done, ctx))

    # ── painting ──────────────────────────────────────────────────────────────
    def paint(self) -> None:
        done_n = sum(1 for s in self.steps if s["state"] in ("done", "fail"))
        pct = (done_n / self.total) if self.total else 0.0
        chan = self.choices.get("channel", "dev")
        sub = f"{'installed' if self.code == 0 else 'installing'}  ·  {chan}"
        if self.demo:
            sub += "  ·  dry run"
        self.query_one("#brand", Brand).render_frame(pct, sub, self.narrow)

        t = Text()
        for i, s in enumerate(self.steps):
            if not s["title"]:
                continue
            if s["state"] == "active":
                t.append("  " + SPINNER[self.frame % len(SPINNER)] + "  ", style=ACCENT)
                t.append(s["title"] + "\n", style=f"bold {TEXT}")
            elif s["state"] == "fail":
                t.append("  ✗  ", style=ERR)
                t.append(s["title"] + "\n", style=TEXT)
            elif s["state"] == "done":
                t.append("  ✓  ", style=OK)
                t.append(s["title"] + "\n", style=TEXT)
            else:
                t.append("  ·  ", style=HINT)
                t.append(s["title"] + "\n", style=HINT)
            # Sub-results only for the step in flight; finished steps collapse to a tick
            # so a fourteen-step run still fits on one screen.
            if s["state"] in ("active", "fail") and not self.narrow:
                for name, status, detail in s["results"][-4:]:
                    glyph, colour = STATUS_GLYPH.get(status, ("·", HINT))
                    t.append(f"       {glyph} ", style=colour)
                    t.append(name, style=DIM)
                    if detail:
                        t.append(f"  {detail}", style=HINT)
                    t.append("\n")
        self.query_one("#steps", Static).update(t)

        d = Text("  ")
        if self.code == 0:
            self._show_next_steps()
            d.append("", style=DIM)
        elif self.code:
            d.append("✗ ", style=ERR)
            d.append(self.detail, style=DIM)
        else:
            d.append("│ ", style=TRACK)
            d.append(self.detail[:78], style=HINT)
        self.query_one("#detail", Static).update(d)


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


class InstallerTuiApp(App):
    """The drop-in. Decide, then run the real engine."""

    CSS_PATH = "ui.tcss"

    def __init__(self, ih, repo, demo: bool, start: str = "decide",
                 project=None, rows=None, note: str = "") -> None:
        super().__init__()
        self.ih, self.repo, self.demo = ih, repo, demo
        self.start = start
        self.project, self.rows, self.note = project, rows, note
        self.exit_code = 0
        self.broker = None
        self.pending_action = None
        # The launcher's stdout contract: a decision the shell wrapper hands to Claude
        # Code. None means "nothing chosen" (exit 97, launch nothing); "" means "launch
        # with no pre-seeded prompt".
        self.decision = None
        self.engage_cmd = "/compliance-surveillance-team:engage"

    def on_mount(self) -> None:
        if self.start == "settings":
            from .ui import SettingsScreen
            self.push_screen(SettingsScreen(str(self.project) if self.project else "."))
            return
        if self.start in ("advanced", "diagnostics"):
            from .ui import AdvancedScreen
            self.push_screen(AdvancedScreen(self.start))
            return
        if self.start == "launch":
            from . import engine as E
            from .ui import FirstRunScreen
            # Same check virt-surv go makes: an unconfigured folder gets the offer, not
            # a launcher listing nothing with no explanation.
            if E.project_is_configured(self.repo, self.project) is False:
                self.push_screen(FirstRunScreen(self.project))
            else:
                self.push_screen(self.open_launcher())
            return
        if self.start == "menu":
            from .ui import MenuScreen
            self.push_screen(MenuScreen())
            if getattr(self, "pending_action", None):
                self.start_action(self.pending_action)
            return
        # Seed "Clone to" with the clone we actually loaded the engine from, so the row
        # reflects reality instead of a guess the run then silently overrides.
        self.push_screen(DecideScreen({"clone": str(self.repo) if self.repo else None}))

    def start_install(self, choices: dict) -> None:
        from . import engine as E

        screen = LiveInstallScreen(choices, self.demo)
        self.push_screen(screen)
        # Held on the app, not the closure: quitting has to be able to unblock an
        # engine thread parked on a question, or the app cannot shut down at all.
        self.broker = E.PromptBroker(self, screen)
        self.run_worker(
            lambda: E.run_installer(self.ih, self, screen, choices, self.repo,
                                    self.demo, broker=self.broker),
            thread=True,
            name="installer",
        )

    def open_launcher(self, project=None):
        from . import engine as E
        from .ui import LaunchScreen

        if project is not None:
            self.project = Path(project)
            self.rows, self.note = E.load_engagements(self.repo, self.project)
        self.engage_cmd = E.engage_command(self.repo, self.project or Path.cwd())
        return LaunchScreen(self.project, self.rows, self.note)

    def jira_decision(self, project, ref: str) -> str:
        from . import engine as E
        return E.jira_decision(self.repo, project, ref)

    def resume_token(self, view: dict) -> str:
        from . import engine as E
        return E.resume_token(self.repo, view)

    def open_decide(self):
        """The decide screen, seeded with the clone the engine was loaded from."""
        return DecideScreen({"clone": str(self.repo) if self.repo else None})

    def start_action(self, action: str, project=None) -> None:
        """An Advanced/Diagnostics/first-run item, on the same live screen."""
        from . import engine as E

        screen = LiveInstallScreen({"channel": "dev"}, self.demo or action == "demo")
        self.push_screen(screen)
        self.broker = E.PromptBroker(self, screen)
        target = project or self.project
        self.run_worker(
            lambda: E.run_action(self.ih, self, screen, action, {"channel": "dev"},
                                 self.repo, self.demo, broker=self.broker,
                                 project=target),
            thread=True, name=f"action:{action}")

    def action_quit(self) -> None:
        # Release before exiting: a modal on screen means a thread is waiting on it.
        broker = getattr(self, "broker", None)
        if broker is not None:
            broker.release_all()
        self.exit(self.exit_code)
