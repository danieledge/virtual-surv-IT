#!/usr/bin/env python3
"""Textual implementations of `launcher_app`'s screens.

Each one answers the SAME contract as its prompt_toolkit twin - same signature, same
return values, same "None means this tier cannot run" sentinel - so `scripts/
launcher_textual.py` can offer them as a tier above launcher_app and every existing
call site works unchanged.

Nothing here decides what a choice MEANS. These screens collect an answer and hand it
back; virt_team_launcher does the rest, exactly as it does for the tier below. That is
the whole reason this is a tier and not a second launcher: one behaviour, two
renderings, and no copy of v1 to keep in step.
"""

from __future__ import annotations

from pathlib import Path

from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Input, Static

from .ui import (ACCENT, DIM, ERR, GOLD, HINT, KEY, NARROW, OK, TEXT, TRACK, Brand,
                 _wrap)


class _TierApp(App):
    """Shared chrome: the mark, a list pane, a detail pane, a footer."""

    CSS_PATH = str(Path(__file__).resolve().parent / "ui.tcss")
    BINDINGS = [("q", "app.quit", "quit")]

    def __init__(self, project) -> None:
        super().__init__()
        self.project = Path(project)
        self.result = None
        self.note = ""
        self.cursor = 0

    # Crash reporting without rich.traceback, which needs pygments - deliberately not
    # vendored. See virt_surv2.ui for the full reasoning.
    def _fatal_error(self) -> None:
        import traceback as _tb

        self.bell()
        exc = getattr(self, "_exception", None)
        try:
            self._exit_renderables.append(
                "".join(_tb.format_exception(type(exc), exc, exc.__traceback__))
                if exc is not None else "virt-surv stopped unexpectedly.")
        except Exception:               # noqa: BLE001
            self._exit_renderables.append("virt-surv stopped unexpectedly.")
        self.exit()

    def compose(self) -> ComposeResult:
        with Vertical(id="shell"):
            yield Brand(id="brand")
            with Horizontal(id="panes"):
                with VerticalScroll(id="panel"):
                    yield Static(id="tier-rows")
                with Vertical(id="side"):
                    yield Static(id="side-body")
            yield Static(id="detail")
            yield Static(id="keys")

    def on_resize(self, event) -> None:
        self.set_class(event.size.width < NARROW, "-narrow")
        painter = getattr(self, "paint", None)
        if callable(painter):
            painter()

    @property
    def narrow(self) -> bool:
        return self.has_class("-narrow")

    def folder(self) -> str:
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

    def move(self, event, count: int) -> bool:
        if not count:
            return False
        if event.key == "down":
            self.cursor = (self.cursor + 1) % count
        elif event.key == "up":
            self.cursor = (self.cursor - 1) % count
        else:
            return False
        event.stop()
        self.paint()
        return True


# ── [c] settings ──────────────────────────────────────────────────────────────

class SettingsTier(_TierApp):
    """Live on/off column, toggle in place, Esc to leave.

    Returns True/False for "the screen ran and did/did not change something", which is
    launcher_app's contract - None is reserved for "this tier cannot run", and
    conflating the two once dumped users into the numbered editor after a clean cancel.
    """

    def __init__(self, project, mod) -> None:
        super().__init__(project)
        self.mod = mod
        self.groups: list = []
        self.rows: list = []
        self.changed = False

    def on_mount(self) -> None:
        self.query_one("#side").border_title = "what it does"
        self.reload()

    def reload(self) -> None:
        try:
            layout = self.mod._editor_layout(self.project) or []
        except Exception:               # noqa: BLE001
            layout = []
        keys = {}
        try:
            for label, key in self.mod._TOGGLE_PREFS:
                keys[label] = key
            keys[self.mod._ENV_ROW_LABEL] = self.mod._ENV_KEY
            keys[self.mod._JIRA_ROW_LABEL] = self.mod._JIRA_KEY
            for label, key, _v, _d in self.mod._CHOICE_PREFS:
                keys[label] = key
        except Exception:               # noqa: BLE001
            pass
        self.groups = []
        for title, label, value, on in layout:
            if title or not self.groups:
                self.groups.append((title or "Other", []))
            help_text = ()
            try:
                help_text = self.mod.setting_help(label) or ()
            except Exception:           # noqa: BLE001
                pass
            self.groups[-1][1].append({
                "key": keys.get(label, label), "label": label, "value": value,
                "on": bool(on),
                "what": help_text[0] if help_text else "",
                "off": help_text[1] if len(help_text) > 1 else "",
            })
        self.rows = [r for _t, rs in self.groups for r in rs]
        self.cursor = min(self.cursor, max(0, len(self.rows) - 1))
        try:
            self.query_one("#panel").border_title = f"{len(self.rows)} settings"
        except Exception:               # noqa: BLE001
            pass
        self.paint()

    def paint(self) -> None:
        self.head(self.folder() if self.narrow
                  else f"{self.folder()}  ·  project settings")
        t = Text()
        i = 0
        for title, rows in self.groups:
            t.append(f"  {title}\n", style=f"bold {HINT}")
            for r in rows:
                sel = i == self.cursor
                t.append("  ▸ " if sel else "    ", style=ACCENT if sel else HINT)
                label = r["label"]
                # Narrow enough that value + provenance stay on the row: a wrapped
                # setting puts "(machine default)" under the wrong one.
                w = 20 if self.narrow else 27
                t.append((label[: w - 1] + "…" if len(label) > w else label).ljust(w),
                         style=f"bold {TEXT}" if sel else TEXT)
                head, _, qual = str(r["value"]).partition("  ")
                t.append(head.ljust(9), style=OK if r["on"] else HINT)
                # Provenance as a marker, not a phrase: "(machine default)" spelled out
                # on every row wrapped them, and a wrapped row puts the qualifier under
                # the WRONG setting. The pane carries the full text; the footer says
                # what the marker means.
                if qual:
                    t.append("·", style=HINT)
                t.append("\n")
                i += 1
            t.append("\n")
        self.query_one("#tier-rows", Static).update(t)

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

        self.foot((("↑↓", "move"), ("space", "change"),
                   ("d", "restore machine defaults"), ("esc", "done")),
                  self.note or "· inherited from this machine's defaults  ·  "
                               "changes are written as you make them",
                  warn=bool(self.note))

    def on_key(self, event) -> None:
        if self.move(event, len(self.rows)):
            return
        k = event.key
        if k in ("space", "enter", "left", "right") and self.rows:
            event.stop()
            try:
                self.note = self.mod._editor_apply_key(
                    self.project, self.rows[self.cursor]["key"]) or ""
                self.changed = True
            except Exception as exc:    # noqa: BLE001
                self.note = f"could not change it: {exc}"
            self.reload()
        elif k == "d":
            event.stop()
            try:
                self.note = self.mod._editor_apply(self.project, "d") or \
                    "restored machine defaults"
                self.changed = True
            except Exception as exc:    # noqa: BLE001
                self.note = f"could not restore: {exc}"
            self.reload()
        elif k == "escape":
            event.stop()
            self.result = self.changed
            self.exit()


# ── [b] done & archived ───────────────────────────────────────────────────────

class FinishedTier(_TierApp):
    """Returns the chosen resume token, or "" when the user backs out."""

    def __init__(self, project, mod, rows) -> None:
        super().__init__(project)
        self.mod = mod
        self.rows = list(rows)
        self.result = ""

    def on_mount(self) -> None:
        self.query_one("#panel").border_title = f"{len(self.rows)} done or archived"
        self.query_one("#side").border_title = "detail"
        self.paint()

    def _token(self, row) -> str:
        try:
            return self.mod._row_resume_token(row.get("row") or row) or ""
        except Exception:               # noqa: BLE001
            return ""

    def _signed(self, row) -> str:
        try:
            return self.mod._sign_off_state(self.project, self._token(row)) or ""
        except Exception:               # noqa: BLE001
            return ""

    def paint(self) -> None:
        self.head("done & archived")
        t = Text()
        if not self.rows:
            t.append("\n  nothing done or archived here yet\n", style=HINT)
        for i, v in enumerate(self.rows):
            sel = i == self.cursor
            t.append("  ▸ " if sel else "    ", style=ACCENT if sel else HINT)
            title = v.get("title") or "?"
            w = 24 if self.narrow else 34
            t.append((title[: w - 1] + "…" if len(title) > w else title).ljust(w),
                     style=f"bold {TEXT}" if sel else TEXT)
            t.append(("archived" if v.get("archived") else "done").ljust(9), style=HINT)
            if self._signed(v):
                t.append("✓ signed off", style=OK)
            else:
                t.append("unsigned", style=GOLD)
            t.append("\n")
        self.query_one("#tier-rows", Static).update(t)

        body = Text("\n")
        if self.rows:
            v = self.rows[self.cursor]
            for line in _wrap(v.get("title") or "?", 26):
                body.append(f"  {line}\n", style=f"bold {ACCENT}")
            body.append("\n")
            for label, value in v.get("lines") or []:
                body.append(f"  {label:<10}", style=HINT)
                body.append(f"{value}\n", style=TEXT)
            signed = self._signed(v)
            body.append("\n  sign-off  ", style=HINT)
            body.append(signed or "not signed off", style=OK if signed else GOLD)
            body.append("\n")
        self.query_one("#side-body", Static).update(body)

        self.foot((("↑↓", "move"), ("enter", "open read-only"), ("s", "sign off"),
                   ("esc", "back")),
                  self.note or "opening one never reopens a closed pack",
                  warn=bool(self.note))

    def on_key(self, event) -> None:
        if self.move(event, len(self.rows)):
            return
        if not self.rows:
            if event.key == "escape":
                event.stop()
                self.result = ""
                self.exit()
            return
        row = self.rows[self.cursor]
        if event.key == "enter":
            event.stop()
            self.result = self._token(row)
            self.exit()
        elif event.key == "s":
            event.stop()
            # A HUMAN sign-off: the control exists so an agent cannot sign its own work.
            try:
                self.note = self.mod._record_sign_off(
                    self.project, self._token(row)) or "signed off"
            except Exception as exc:    # noqa: BLE001
                self.note = f"could not sign off: {exc}"
            self.paint()
        elif event.key == "escape":
            event.stop()
            self.result = ""
            self.exit()


# ── [a] archive ───────────────────────────────────────────────────────────────

class ArchiveTier(_TierApp):
    """Pick one, or all, with the consequence stated BEFORE the key is pressed."""

    def __init__(self, project, mod, engagement_state, rows) -> None:
        super().__init__(project)
        self.mod, self.es = mod, engagement_state
        self.rows = list(rows)
        self.picked: set = set()

    def on_mount(self) -> None:
        self.query_one("#panel").border_title = f"{len(self.rows)} open"
        self.query_one("#side").border_title = "consequence"
        self.paint()

    def paint(self) -> None:
        self.head("archive engagements")
        t = Text()
        if not self.rows:
            t.append("\n  nothing open to archive here\n", style=HINT)
        for i, r in enumerate(self.rows):
            sel = i == self.cursor
            t.append("  ▸ " if sel else "    ", style=ACCENT if sel else HINT)
            t.append("[", style=TRACK)
            t.append("✓" if i in self.picked else " ", style=OK)
            t.append("]  ", style=TRACK)
            slug = ""
            try:
                slug = self.mod._row_resume_token(r) or "?"
            except Exception:           # noqa: BLE001
                slug = "?"
            t.append(slug[:34], style=f"bold {TEXT}" if sel else TEXT)
            t.append("   " + (r.get("status") or ""), style=HINT)
            t.append("\n")
        self.query_one("#tier-rows", Static).update(t)

        body = Text("\n")
        body.append("  Archiving in place\n\n", style=f"bold {ACCENT}")
        for line in _wrap("Nothing is deleted. The pack leaves the resume list and "
                          "stays exactly as it is.", 26):
            body.append(f"  {line}\n", style=TEXT)
        body.append("\n")
        for line in _wrap("An OPEN pack archives with --force and then shows as "
                          "ARCHIVED-OPEN in checks.", 26):
            body.append(f"  {line}\n", style=GOLD)
        self.query_one("#side-body", Static).update(body)

        self.foot((("↑↓", "move"), ("space", "pick"), ("a", "all"),
                   ("enter", "archive"), ("esc", "back")),
                  self.note or f"{len(self.picked)} selected", warn=bool(self.note))

    def on_key(self, event) -> None:
        if self.move(event, len(self.rows)):
            return
        k = event.key
        if k == "escape":
            event.stop()
            self.result = True
            self.exit()
        elif not self.rows:
            return
        elif k == "space":
            event.stop()
            self.picked.symmetric_difference_update({self.cursor})
            self.paint()
        elif k == "a":
            event.stop()
            self.picked = set(range(len(self.rows)))
            self.paint()
        elif k == "enter":
            event.stop()
            chosen = [self.rows[i] for i in sorted(self.picked)]
            if not chosen:
                self.note = "nothing picked - space to pick, a for all"
                self.paint()
                return
            try:
                self.mod._archive_perform(self.es, chosen)
                self.note = f"archived {len(chosen)}"
            except Exception as exc:    # noqa: BLE001
                self.note = f"could not archive: {exc}"
            self.picked.clear()
            self.paint()


# ── text-entry tiers ──────────────────────────────────────────────────────────

class _AskTier(_TierApp):
    """One question, one field. Used by request, jira and the folder explorer."""

    title = ""
    prompt = ""
    blurb: tuple = ()
    placeholder = ""
    keys = (("enter", "ok"), ("esc", "back"))

    def compose(self) -> ComposeResult:
        with Vertical(id="shell"):
            yield Brand(id="brand")
            with Vertical(id="panel"):
                yield Static(id="ask-body")
            yield Input(placeholder=self.placeholder, id="edit")
            yield Static(id="detail")
            yield Static(id="keys")

    def on_mount(self) -> None:
        self.query_one("#panel").border_title = self.title
        h = Text()
        h.append(f"\n  {self.prompt}\n\n", style=f"bold {ACCENT}")
        for line in self.blurb:
            h.append(f"  {line}\n", style=TEXT if not line.startswith("(") else HINT)
        self.query_one("#ask-body", Static).update(h)
        inp = self.query_one("#edit", Input)
        self.call_after_refresh(inp.focus)
        self.paint()

    def paint(self) -> None:
        self.head(self.folder())
        self.foot(self.keys, self.note, warn=bool(self.note))

    def key_escape(self, event) -> None:
        event.stop()
        self.cancel()

    def cancel(self) -> None:
        self.exit()


class RequestTier(_AskTier):
    """[n] - what is the work?

    Returns (request, auto) when text was typed, or the caller's REQUEST_SKIPPED for a
    plain launch. Typing is an OFFER, never a toll gate.
    """

    title = "new engagement"
    prompt = "What is the work?"
    blurb = ("This becomes the session's opening prompt, so Morgan starts on it",
             "instead of asking you what it is.",
             "",
             "(leave it blank to start a new engagement and decide in the session)")
    placeholder = "what should the team work on?"
    keys = (("enter", "start"), ("ctrl+t", "unattended"), ("esc", "skip"))

    def __init__(self, project, skipped) -> None:
        super().__init__(project)
        self.skipped = skipped
        self.auto = False
        self.result = skipped

    def on_key(self, event) -> None:
        if event.key == "ctrl+t":
            event.stop()
            self.auto = not self.auto
            self.note = ("unattended: the run answers its own questions"
                         if self.auto else "")
            self.paint()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        self.result = (text, self.auto) if text else self.skipped
        self.exit()

    def cancel(self) -> None:
        self.result = self.skipped
        self.exit()


class JiraTier(_AskTier):
    """[j] - a ticket ref, or the project key when one is not set yet."""

    title = "from a Jira ticket"
    prompt = "Which ticket?"
    blurb = ("The engagement opens with the ticket's summary and acceptance",
             "criteria already read in.")
    placeholder = "e.g. ABC-123 or a ticket URL"
    keys = (("enter", "start"), ("esc", "back"))

    def __init__(self, project, mod, cancelled) -> None:
        super().__init__(project)
        self.mod, self.cancelled = mod, cancelled
        self.result = cancelled
        self.needs_key = False
        try:
            self.needs_key = bool(mod._jira_needs_key(Path(project)))
        except Exception:               # noqa: BLE001
            pass
        if self.needs_key:
            self.title = "Jira project key"
            self.prompt = "Jira write-back is on, but no project key is set"
            self.blurb = ("Until it is, the team cannot raise or update an issue.",
                          "Enter the key (e.g. SURV) to finish turning it on.")
            self.placeholder = "project key, e.g. SURV"

    def on_input_submitted(self, event: Input.Submitted) -> None:
        value = event.value.strip()
        if not value:
            self.cancel()
            return
        if self.needs_key:
            try:
                self.mod.set_jira_project_key(self.project, value)
            except Exception:           # noqa: BLE001
                pass
            self.needs_key = False
            self.title, self.prompt = "from a Jira ticket", "Which ticket?"
            self.blurb = ("The engagement opens with the ticket's summary and",
                          "acceptance criteria already read in.")
            self.on_mount()
            self.query_one("#edit", Input).value = ""
            return
        self.result = value
        self.exit()

    def cancel(self) -> None:
        self.result = self.cancelled
        self.exit()


class BrowseTier(_AskTier):
    """[o] - the project explorer. Returns a Path, or the caller's cancel sentinel."""

    title = "open a folder"
    prompt = "Which project folder?"
    placeholder = "path to a project folder"
    keys = (("enter", "open"), ("esc", "cancel"))

    def __init__(self, start, mod, cancelled) -> None:
        super().__init__(start)
        self.mod, self.cancelled = mod, cancelled
        self.result = cancelled
        recents = []
        try:
            recents = [str(p) for p in (mod._recent_projects() or [])][:6]
        except Exception:               # noqa: BLE001
            pass
        self.blurb = (["The launcher re-reads engagements for whatever you name here.",
                       ""] + (["Recent:"] + [f"  {r}" for r in recents] if recents else []))

    def on_mount(self) -> None:
        super().on_mount()
        self.query_one("#edit", Input).value = str(self.project)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        target = Path(event.value.strip() or self.project).expanduser()
        if not target.is_dir():
            self.note = f"not a directory: {target}"
            self.paint()
            return
        self.result = target
        self.exit()

    def cancel(self) -> None:
        self.result = self.cancelled
        self.exit()


# ── list-pick tiers ───────────────────────────────────────────────────────────

class _PickTier(_TierApp):
    """A titled list that returns one choice."""

    title = ""
    heading = ""
    keys = (("↑↓", "move"), ("enter", "choose"), ("esc", "cancel"))

    def __init__(self, project, options, cancel_value=None) -> None:
        super().__init__(project)
        self.options = list(options)    # [(value, label, blurb)]
        self.result = cancel_value
        self.cancel_value = cancel_value

    def on_mount(self) -> None:
        self.query_one("#panel").border_title = self.title
        self.query_one("#side").border_title = "what it does"
        self.paint()

    def paint(self) -> None:
        self.head(self.folder())
        t = Text()
        if self.heading:
            t.append(f"  {self.heading}\n\n", style=f"bold {HINT}")
        for i, (_v, label, _b) in enumerate(self.options):
            sel = i == self.cursor
            t.append("  ▸ " if sel else "    ", style=ACCENT if sel else HINT)
            t.append(label, style=f"bold {TEXT}" if sel else TEXT)
            t.append("\n")
        self.query_one("#tier-rows", Static).update(t)

        body = Text("\n")
        if self.options:
            _v, label, blurb = self.options[self.cursor]
            for line in _wrap(label, 26):
                body.append(f"  {line}\n", style=f"bold {ACCENT}")
            body.append("\n")
            for line in _wrap(blurb, 26):
                body.append(f"  {line}\n", style=TEXT)
        self.query_one("#side-body", Static).update(body)
        self.foot(self.keys, self.note, warn=bool(self.note))

    def on_key(self, event) -> None:
        if self.move(event, len(self.options)):
            return
        if event.key == "enter" and self.options:
            event.stop()
            self.result = self.options[self.cursor][0]
            self.exit()
        elif event.key == "escape":
            event.stop()
            self.result = self.cancel_value
            self.exit()


class SetupTier(_PickTier):
    """First-time project setup, asked inside the interface.

    SKIP and CANCEL are deliberately different answers: skip launches without
    configuring, cancel launches nothing at all.
    """

    title = "first-time setup"
    heading = "The team is not set up in this folder"


class SlugPickTier(_PickTier):
    """Pick one open engagement, when an action needs to know which."""

    title = "which engagement?"
    heading = "Several are open"
