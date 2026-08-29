#!/usr/bin/env python3
"""Full-screen screens for `virt-surv`, the installer/manager menu.

The second consumer of tui_chrome (2026-08-28). `virt-surv go` has had arrow keys, a
two-pane layout and in-place toggles since 2026-08-20; `virt-surv` had numbered prompts,
and the two front doors of one product did not look like one product.

WHY THE MENU SPECIFICALLY. Not "it looks plain". The Advanced submenu has fifteen items,
six of which carry a parenthetical longer than the option itself - one is 136 characters.
Printed as `  12) label (explanation...)` they soft-wrap to column 0 with no hanging
indent, so the continuation sits under the number gutter and reads as a separate,
unnumbered option. That is a layout problem and no amount of rewording fixes it: the text
needs somewhere to go, and the right-hand pane is where.

And ten of the twenty-one options write outside the repo - shell rc files,
~/.claude/settings.json, one rmtree - with nothing on screen saying so. The launcher marks
state on every row and states consequences before the keypress. This did not.

A TIER, NEVER A REPLACEMENT. Every entry point returns None when it could not run, and the
caller falls back to the numbered prompt it has always had. That keeps the installer
working headless, under --yes, over a pipe, and on any box where prompt_toolkit will not
start - which is the same box that most needs the installer to work.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path


def _vendor_on_path() -> None:
    """Make the VENDORED prompt_toolkit importable.

    Without this the screens are dead on any machine that has not pip-installed
    prompt_toolkit - which is the normal case, since the whole point of vendoring it was
    that a locked-down corporate box cannot pip-install anything. The import failed, the
    `except Exception` turned that into "this console cannot host an app", and the
    numbered menu came back looking like a graceful fallback.

    It was invisible from here because this development machine HAS prompt_toolkit
    installed, and the test fixture put vendor/ on the path by hand - so both the manual
    render and the whole test file exercised a path production never takes. Reported from
    a container that has neither (2026-08-28: "I don't see the better interface").

    virt_team_launcher._ptk_ui has done exactly this since the app tier was written; this
    is the same three lines, in the file that also needed them."""
    here = Path(__file__).resolve().parent
    for candidate in (here.parent / "vendor", here.parent.parent / "vendor"):
        if (candidate / "prompt_toolkit").is_dir():
            if str(candidate) not in sys.path:
                sys.path.insert(0, str(candidate))
            return


def _chrome():
    """tui_chrome, found from this file's own directory.

    The installer may run from a bare clone, a marketplace cache or a temp directory that
    a downloaded copy of install_helper.py was dropped into, so `scripts/` is not reliably
    importable - the same reason launcher_app resolves vsit_paths this way."""
    here = Path(__file__).resolve().parent
    for candidate in (here, here.parent, here.parent / "scripts"):
        if (candidate / "tui_chrome.py").is_file():
            if str(candidate) not in sys.path:
                sys.path.insert(0, str(candidate))
            break
    import tui_chrome

    return tui_chrome


class InstallerHost:
    """The four attributes tui_chrome asks of a host, backed by install_helper.

    A CLASS rather than passing install_helper itself, for one reason that is easy to get
    wrong: install_helper._can_encode defaults its stream to sys.stdout, and the chrome
    renders to sys.stderr. Handing the module over directly would probe one console and
    draw on another - and that failure is silent, because the two are the same console on
    every machine where anyone would notice."""

    def __init__(self, ih, repo: Path | None = None):
        self._ih = ih
        self._repo = repo

    def _can_encode(self, text: str) -> bool:
        return self._ih._can_encode(text, sys.stderr)

    def _morgan_line(self) -> str:
        return self._ih.morgan_intro(sys.stderr)

    def _plugin_version(self, *_args) -> str:
        try:
            if self._repo is not None:
                return self._ih.installed_version(self._repo) or ""
        except Exception:
            pass
        return ""

    def _git_branch(self, *_args) -> str:
        """The configured channel, which is what a reader of this menu cares about.

        Not the checked-out branch: the installer's own clone may be on anything, and the
        question the title answers is "which channel am I installing from"."""
        try:
            cfg = self._ih.load_config(self._ih.config_path())
            branch = cfg.get("branch")
            return branch if branch in self._ih.BRANCHES else ""
        except Exception:
            return ""


def _wrap(text: str, width: int = 0, indent: str = "  ") -> str:
    """Word-wrap for the explanation pane.

    Hand-wrapped rather than left to the Window, for the same reason launcher_app does it:
    the right pane is a weighted split, so wrap_lines would rewrap on every resize and the
    text would jump around under the cursor while someone is reading it."""
    width = width or _chrome().pane_width()
    out, line = [], ""
    for word in (text or "").split():
        if line and len(line) + 1 + len(word) > width:
            out.append(indent + line)
            line = word
        else:
            line = f"{line} {word}".strip()
    if line:
        out.append(indent + line)
    return "\n".join(out)


# tui_chrome's palette names, keyed by the brand banner's own role names. The banner is
# rendered for a terminal by install_helper and for an app by this - one set of art, two
# painters, so the mascot cannot drift between the two front doors.
_BRAND_STYLE = {
    "cyan": "class:on",
    "violet": "class:group",
    "green": "class:on",
    "bold": "class:title",
    "dim": "class:dim",
    "amber": "class:warn",
    "plain": "",
}


def brand_header(mod):
    """The VSIT banner as frame-header rows, or None when the art is unavailable.

    None rather than [] so the caller keeps tui_chrome's own identity line instead of a
    blank strip - a missing banner should cost the art, never the header."""
    try:
        brand = _import_brand(mod)
        if brand is None:
            return None
        # Through tui_chrome, which measures stderr: the same captured-stdout problem
        # would otherwise pick the full banner tier on a phone.
        width = _chrome().term_columns()
        rows = brand.banner(width)
    except Exception:
        return None
    if not rows:
        return None
    return [[(_BRAND_STYLE.get(role, ""), text) for role, text in row] for row in rows]


def _import_brand(mod):
    """brand_banner, via the host's own resolver when it has one.

    install_helper._import_from_scripts knows that this file may be running from a temp
    copy of itself and asks the configured clone instead - which is exactly the mistake
    that hid the banner from every real installation until 2026-08-28."""
    resolver = getattr(mod, "_import_from_scripts", None)
    if callable(resolver):
        found = resolver("brand_banner")
        if found is not None:
            return found
    try:
        import brand_banner

        return brand_banner
    except Exception:
        return None


def _rows(options, ih, actions=None):
    """[(key, label, blurb, writes)] from the menu tables install_helper already has.

    The tables carry `key, text` where text is "label (explanation)". Split on the first
    " (" so the label stays short enough for a column and the explanation goes to the
    pane - which is the whole point of having a pane.

    `actions` is the caller's OWN key->action mapping and matters more than it looks: the
    same key means different things in different menus ("1" is a full install at the top
    level, environment-setup-only under Advanced, check-for-updates under Diagnostics).
    Guessing which table a key belongs to showed the wrong consequence for the most
    prominent option on the most-seen screen (found on screen, 2026-08-28)."""
    out = []
    for key, text in options:
        if not key:  # a divider row in the source table
            continue
        label, _, blurb = text.partition(" (")
        out.append((key, label.strip(), blurb.rstrip(")").strip(), _writes(key, ih, actions)))
    return out


# What each menu key touches OUTSIDE the repo, in the words a person needs before pressing
# it. Absent means "nothing outside the repo", which is the safe default for a new entry:
# a missing note understates, and understating is the direction that cannot mislead someone
# into an action they would have declined.
_WRITES = {
    "statusline": "writes ~/.claude/settings.json",
    "formats": "writes this machine's installer.json",
    "model": "writes ~/.claude/settings.json",
    "machinedefaults": "writes this machine's installer.json",
    "fixbashrc": "edits your shell startup file",
    "aliasmanage": "edits your shell startup file",
    "cleanplugincache": "Deletes cached plugin copies from the user Claude directory",
    "relocate": "moves files in the working project",
    "codeintel": "installs a Python package",
    "setup": "installs requirements and may write ~/.claude",
    "extensions": "writes this machine's org extensions file",
    # Top-level actions. They had no notes at all while only the submenus used this
    # screen, which made the one menu everybody sees the least informative of the three.
    "full": "installs dependencies, updates the clone, and registers the plugin",
    "configure": "writes settings into the project you choose",
    "update": "pulls new code and refreshes the plugin; keeps every setting",
    "howto": "reads only - explains the plugin, changes nothing",
    "diagnostics": "reads only, except the two prototype items that start a daemon",
    "advanced": "opens a submenu; each item states its own consequence",
    "quit": "",
}


def _writes(key: str, ih, actions=None) -> str:
    """The consequence note for one row, resolved through the caller's own action table.

    The fallback scan is only for a caller that did not pass one, and it is a guess: keys
    collide across the three menus, so it can and did answer for the wrong action."""
    action = None
    if isinstance(actions, dict) and key in actions:
        action = actions[key]
    else:
        for table in ("MENU_ACTIONS", "_ADVANCED_ACTIONS", "_DIAGNOSTICS_ACTIONS"):
            mapping = getattr(ih, table, None)
            if isinstance(mapping, dict) and key in mapping:
                action = mapping[key]
                break
    return _WRITES.get(action or "", "")


def _marker_kind(note: str) -> str:
    """ "deletes", "writes", or "" - what to put beside the row.

    Driven off the note rather than a second table, so a note and its marker cannot
    disagree. A note that opens with "reads only" or "opens a submenu" describes something
    that changes nothing here, and marking it as a write would make the marker meaningless
    on the screen where most rows carry one."""
    lowered = (note or "").lower()
    if not note:
        return ""
    if lowered.startswith("deletes"):
        return "deletes"
    if lowered.startswith(("reads only", "opens a submenu")):
        return ""
    return "writes"


def chooser_screen(options, ih, *, title: str, actions=None, repo: Path | None = None, output=None):
    """One menu as a full-screen picker. Returns the chosen key, "" for back/Esc, or
    **None when the screen could not run at all** - the caller then prints its numbered
    menu exactly as before.

    The None-vs-"" distinction is not decoration. The launcher's settings screen conflated
    them once and cancelling dumped the user into the old numbered editor (2026-08-20); a
    cancel is a decision, not an unavailability."""
    try:
        chrome = _chrome()
        _vendor_on_path()
        from prompt_toolkit.key_binding import KeyBindings
    except Exception:
        return None

    # The same gate the launcher's _ptk_ui applies. Without it, every scripted test and
    # every piped run would try to start a full-screen app. VIRT_SURV_FORCE_PTK skips it
    # so this tier can be driven headlessly - an untestable tier is precisely how the
    # launcher's two menus drifted apart in the first place.
    if not os.environ.get("VIRT_SURV_FORCE_PTK"):
        if not (sys.stdin.isatty() and sys.stderr.isatty()):
            return None

    host = InstallerHost(ih, repo)
    rows = _rows(options, ih, actions)
    if not rows:
        return None
    g = chrome.glyphs(host)
    # Its OWN markers, not glyphs()' on/off pair. "·" already means "off" on every
    # launcher row, and reusing it here for "this writes outside the repo" would give one
    # symbol two meanings in one product - which is worse than having no marker at all.
    rich = host._can_encode("✎⛔")
    mark_writes = "✎" if rich else "*"
    mark_deletes = "⛔" if rich else "!"
    idx = [0]
    picked = [""]

    def _body():
        out = []
        width = min(max((len(label) for _k, label, _b, _w in rows), default=0), 34)
        for i, (key, label, _blurb, writes) in enumerate(rows):
            sel = idx[0] == i
            out.append(("class:sel" if sel else "", f"  {g['point']} " if sel else "    "))
            out.append(("class:sel" if sel else "", f"{key:>2}  {label.ljust(width)}"))
            # The consequence marker rides on the ROW, not only in the pane: someone
            # arrowing quickly past a destructive option should not have to read to
            # notice it.
            kind = _marker_kind(writes)
            mark = ""
            if kind == "deletes":
                mark = f"  {mark_deletes}"
            elif kind == "writes":
                mark = f"  {mark_writes}"
            out.append(("class:warn" if kind == "deletes" else "class:dim", mark))
            out.append(("", "\n"))
        return out

    def _right():
        _key, label, blurb, writes = rows[idx[0]]
        out = [("class:group", chrome.ui_text(host, f"  {label}\n\n"))]
        if blurb:
            out.append(("class:dim", _wrap(blurb) + "\n\n"))
        if writes:
            style = "class:warn" if _marker_kind(writes) == "deletes" else "class:dim"
            out.append((style, _wrap(writes) + "\n"))
        else:
            out.append(("class:dim", _wrap("Nothing outside this project.") + "\n"))
        return out

    def _footer():
        kinds = {_marker_kind(w) for _k, _l, _b, w in rows}
        legend = ""
        if "writes" in kinds:
            legend = f"   {mark_writes} writes outside this project"
        if "deletes" in kinds:
            legend += f"{' · ' if legend else '   '}{mark_deletes} deletes"
        return [
            (
                "class:hint",
                chrome.ui_text(host, f"  ↑↓ move · Enter choose · Esc back{legend}"),
            )
        ]

    kb = KeyBindings()

    @kb.add("up")
    def _up(event):
        idx[0] = (idx[0] - 1) % len(rows)

    @kb.add("down")
    def _down(event):
        idx[0] = (idx[0] + 1) % len(rows)

    @kb.add("enter")
    def _enter(event):
        picked[0] = rows[idx[0]][0]
        event.app.exit()

    @kb.add("escape", eager=True)
    @kb.add("c-c")
    @kb.add("q")
    def _esc(event):
        picked[0] = ""
        event.app.exit()

    # Typing a key jumps straight to it, so muscle memory from the numbered menu still
    # works - a picker that punishes people who already know the number is a downgrade.
    for row_key, _label, _blurb, _writes in rows:
        if len(row_key) == 1 and row_key.isalnum():

            @kb.add(row_key)
            def _jump(event, _k=row_key):
                for position, row in enumerate(rows):
                    if row[0] == _k:
                        idx[0] = position
                        break

    try:
        chrome.screen(
            host,
            title=title,
            body_fn=_body,
            right_fn=_right,
            footer_fn=_footer,
            key_bindings=kb,
            output=output,
            header_fn=lambda: brand_header(ih),
        )
    except Exception:
        # A screen that cannot run degrades to the numbered menu, always. But a swallowed
        # exception is indistinguishable from "this console cannot host an app", and a
        # real TypeError in _right hid behind exactly this for one commit - the picker
        # silently never ran and looked like a graceful fallback. VIRT_SURV_DEBUG_APP
        # makes it loud when you are the one asking.
        if os.environ.get("VIRT_SURV_DEBUG_APP"):
            raise
        return None
    return picked[0]


def grid_screen(rows_fn, apply_fn, help_fn, ih, *, title, repo=None, output=None):
    """A settings GRID: every value visible at once, Enter changes the highlighted row.

    The shape `virt-surv go` has used since 2026-08-20, pointed at this machine's config
    instead of a project's. What it replaces was a fixed interrogation - seven blocking
    questions in a set order with no way to skip forward, go back, or see the whole state
    while editing, and the current values printed once as a single ~250-character line that
    wrapped three times.

    `rows_fn` returns [(group, label, value, on, key)] and `apply_fn(key)` changes exactly
    that key. Dispatch goes through the KEY, never the row's position: this repo has shipped
    that bug twice (a renumbered Advanced menu redirecting an action, and a grouped settings
    screen toggling a different row than the one on screen), and both times every test
    passed.

    Returns True if anything changed, False if not, and None when the screen could not run -
    the caller then falls back to its prompts. False and None are different answers and the
    caller must not conflate them.
    """
    try:
        chrome = _chrome()
        _vendor_on_path()
        from prompt_toolkit.key_binding import KeyBindings
    except Exception:
        return None
    if not os.environ.get("VIRT_SURV_FORCE_PTK"):
        if not (sys.stdin.isatty() and sys.stderr.isatty()):
            return None

    host = InstallerHost(ih, repo)
    rows = list(rows_fn() or [])
    if not rows:
        return None
    g = chrome.glyphs(host)
    idx = [0]
    changed = [False]
    notes: list = []

    def _refresh():
        rows[:] = list(rows_fn() or rows)

    def _body():
        out = []
        width = min(max((len(label) for _gr, label, _v, _o, _k in rows), default=0), 28)
        for i, (group, label, value, on, _key) in enumerate(rows):
            if group:
                out.append(("class:group", ("\n" if i else "") + f"  {group}\n"))
            sel = idx[0] == i
            out.append(("class:sel" if sel else "", f"  {g['point']} " if sel else "    "))
            out.append(("class:sel" if sel else "", f"{label.ljust(width + 1)} "))
            mark = g["on"] if on else g["off"]
            out.append(("class:on" if on else "class:off", f"{mark} {value}\n"))
        return out

    def _right():
        _group, label, value, on, key = rows[idx[0]]
        out = [("class:group", _wrap(label) + "\n\n")]
        text = help_fn(key) if help_fn else ""
        out.append(("class:dim", _wrap(text or "No description for this setting yet.") + "\n\n"))
        out.append(("class:on" if on else "class:off", _wrap(f"currently: {value}") + "\n"))
        if notes:
            out.append(("class:group", "\n  Just changed\n"))
            for note in notes[-4:]:
                out.append(("class:on", _wrap(note) + "\n"))
        return out

    def _footer():
        return [("class:hint", chrome.ui_text(host, "  ↑↓ move · Enter change · Esc done"))]

    kb = KeyBindings()

    @kb.add("up")
    def _up(event):
        idx[0] = (idx[0] - 1) % len(rows)

    @kb.add("down")
    def _down(event):
        idx[0] = (idx[0] + 1) % len(rows)

    @kb.add("enter")
    @kb.add(" ")
    def _change(event):
        before = list(rows)
        note = apply_fn(rows[idx[0]][4]) or ""
        _refresh()
        if list(rows) != before:
            changed[0] = True
            for (_g, label, value, _o, _k), (_bg, _bl, was, _bo, _bk) in zip(rows, before):
                if value != was:
                    # ONE line per setting: toggling a row twice used to append two, which
                    # reads as the panel duplicating rather than as two edits (2026-08-28).
                    prefix = f"{label}: "
                    notes[:] = [n for n in notes if not n.startswith(prefix)]
                    notes.append(f"{label}: {was} -> {value}")
        if note:
            notes.append(note.strip())

    @kb.add("escape", eager=True)
    @kb.add("c-c")
    @kb.add("q")
    def _esc(event):
        event.app.exit()

    try:
        chrome.screen(
            host,
            title=title,
            body_fn=_body,
            right_fn=_right,
            footer_fn=_footer,
            key_bindings=kb,
            output=output,
            header_fn=lambda: brand_header(ih),
        )
    except Exception:
        if os.environ.get("VIRT_SURV_DEBUG_APP"):
            raise
        return None
    return changed[0]


# ANSI escapes as the installer emits them - stripped before a formatted-text control
# sees them, which renders escape codes as the characters they are.
_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")

# Rows a caller can hand to progress_screen: pending until the run reaches them.
_PENDING, _RUNNING, _OK, _SKIP, _FAIL = "pending", "running", "ok", "skip", "fail"


class _RunState:
    """What a running install looks like to a screen.

    Mutated from a WORKER THREAD and read by the render loop, which is safe here for one
    specific reason: every field is replaced wholesale rather than edited in place, and
    Python guarantees the assignment itself is atomic. A partially-updated row would show
    for at most one 150ms frame; a lock around it would buy nothing a person could see.
    """

    def __init__(self, titles):
        self.rows = [[title, _PENDING, ""] for title in titles]
        self.lines = []
        self.current = -1
        self.done = False
        self.code = None

    # -- the observer protocol install_helper.Installer speaks --------------------
    def step(self, number, total, title):
        index = number - 1
        if 0 <= index < len(self.rows):
            self.rows[index][0] = title  # lazy titles resolve only once the step starts
            self.rows[index][1] = _RUNNING
            self.current = index

    def result(self, name, status, detail):
        if 0 <= self.current < len(self.rows):
            self.rows[self.current][1] = status
            self.rows[self.current][2] = detail or ""

    def line(self, text):
        # The installer pre-styles its own output with ANSI (self.style.dim(...)), which
        # a terminal interprets and a formatted-text control renders LITERALLY - so the
        # pane filled up with "^[[2m Just the basics...^[[0m" (seen on screen 2026-08-29).
        # Stripped here rather than in the installer, because the streaming tier still
        # wants its colour; only this renderer needs plain text.
        text = _ANSI.sub("", (text or "")).rstrip()
        if text:
            self.lines.append(text)
            # Bounded: an install can emit hundreds of lines and only the tail is ever
            # rendered, so keeping them all would be a slow leak for no visible gain.
            if len(self.lines) > 200:
                del self.lines[:100]


def progress_screen(titles, run_fn, ih, *, title, repo=None, output=None):
    """Run `run_fn(observer)` while showing its steps live. Returns its exit code, or
    None when the screen could not run and the caller should fall back to streaming.

    WHY THIS EXISTS. Picking "update" from the new picker used to drop straight out of
    the full-screen interface into a scrolling step log - the interface the picker was
    built to replace (owner report, 2026-08-29). The work is unchanged; only who renders
    it moves.

    The run happens on a WORKER THREAD because prompt_toolkit needs its event loop free
    to redraw; a blocking subprocess on the main thread would freeze the frame it is
    supposed to be animating. Which also means run_fn must not prompt - see update_screen
    for how the decisions are taken before this starts."""
    try:
        chrome = _chrome()
        _vendor_on_path()
        from prompt_toolkit.key_binding import KeyBindings
    except Exception:
        return None
    if not os.environ.get("VIRT_SURV_FORCE_PTK"):
        if not (sys.stdin.isatty() and sys.stderr.isatty()):
            return None

    import threading

    host = InstallerHost(ih, repo)
    g = chrome.glyphs(host)
    state = _RunState(titles)
    marks = {
        _PENDING: ("class:dim", g["off"]),
        _RUNNING: ("class:group", g["point"]),
        _OK: ("class:on", g["on"]),
        _SKIP: ("class:warn", g["closing"]),
        _FAIL: ("class:warn", g["blocked"]),
    }

    def _work():
        try:
            state.code = run_fn(state)
        except BaseException:  # noqa: BLE001 - the screen must close whatever happens
            state.code = 1
        finally:
            state.done = True

    def _body():
        out = []
        for row_title, status, detail in state.rows:
            style, mark = marks.get(status, marks[_PENDING])
            out.append((style, f"  {mark} "))
            out.append(("class:title" if status == _RUNNING else "", row_title))
            if detail and status != _RUNNING:
                out.append(("class:dim", f"  ({detail[:40]})"))
            out.append(("", "\n"))
        return out

    def _right():
        out = [("class:group", _wrap("Output") + "\n\n")]
        for text in state.lines[-12:]:
            out.append(("class:dim", _wrap(text) + "\n"))
        return out

    def _footer():
        if state.done:
            ok = state.code == 0
            word = "done" if ok else f"finished with errors (exit {state.code})"
            return [("class:hint", chrome.ui_text(host, f"  {word} · Enter close"))]
        return [("class:hint", chrome.ui_text(host, "  working... · Ctrl-C stop"))]

    kb = KeyBindings()

    @kb.add("enter")
    @kb.add("escape", eager=True)
    @kb.add("q")
    def _close(event):
        # Only once the work has finished. Closing mid-run would leave the installer
        # writing into a screen that no longer exists, and the user with no idea whether
        # their plugin was half-updated.
        if state.done:
            event.app.exit()

    @kb.add("c-c")
    def _stop(event):
        if state.done:
            event.app.exit()

    worker = threading.Thread(target=_work, daemon=True)
    worker.start()
    try:
        chrome.screen(
            host,
            title=title,
            body_fn=_body,
            right_fn=_right,
            footer_fn=_footer,
            key_bindings=kb,
            output=output,
            refresh_interval=0.15,
            header_fn=lambda: brand_header(ih),
        )
    except Exception:
        if os.environ.get("VIRT_SURV_DEBUG_APP"):
            raise
        return None
    worker.join(timeout=1)
    return state.code


def _update_facts(ih, repo=None):
    """(local_version, remote_version, headlines, dirty) - all best-effort.

    Read-only and cheap: this runs BEFORE the screen opens, because a screen that has to
    wait on the network to draw its first frame is a screen that looks broken."""
    local = remote = ""
    headlines = []
    dirty = False
    try:
        clone = repo or ih._resolve_repo_root(None)
        if clone is None:
            return local, remote, headlines, dirty
        cfg = ih.load_config(ih.config_path())
        branch = cfg.get("branch") if cfg.get("branch") in ih.BRANCHES else "dev"
        local = ih.installed_version(clone) or ""
        preview = ih.gather_update_preview(clone, branch, local) or {}
        remote = preview.get("remote_version") or ""
        headlines = [h for h in (preview.get("headlines") or []) if h][:6]
        proc = ih.run_cmd(["git", "-C", str(clone), "status", "--porcelain"], timeout=10)
        dirty = bool((proc.stdout or "").strip()) if proc and proc.returncode == 0 else False
    except Exception:
        pass
    return local, remote, headlines, dirty


def update_decision_screen(ih, repo=None, output=None):
    """What the update would bring, and the one question worth asking. Returns "update",
    "cancel", or None when the screen could not run.

    ONE question, asked before anything starts. The streaming flow asked two, mid-run,
    between blocks of log output - and a question you meet halfway through a wall of text
    is one you answer without reading. Everything the human needs to decide is on this
    screen at once: which version, what changed, and whether their working tree is dirty."""
    try:
        chrome = _chrome()
        _vendor_on_path()
        from prompt_toolkit.key_binding import KeyBindings
    except Exception:
        return None
    if not os.environ.get("VIRT_SURV_FORCE_PTK"):
        if not (sys.stdin.isatty() and sys.stderr.isatty()):
            return None

    host = InstallerHost(ih, repo)
    g = chrome.glyphs(host)
    local, remote, headlines, dirty = _update_facts(ih, repo)
    options = [("update", "update now"), ("cancel", "not now")]
    idx = [0]
    picked = ["cancel"]

    def _body():
        out = []
        if remote and local and remote != local:
            out.append(("class:group", f"  {local}  ->  {remote}\n\n"))
        elif remote and local and remote == local:
            out.append(("class:on", f"  already on {local} - nothing to pull\n\n"))
        else:
            out.append(("class:dim", "  checking what is available...\n\n"))
        if dirty:
            # Stated BEFORE the keypress, not discovered mid-run. The streaming flow
            # asked about this after it had already started working.
            out.append(("class:warn", "  note: your clone has uncommitted changes\n"))
            out.append(("class:dim", "        they are stashed and restored around the pull\n\n"))
        for i, (key, label) in enumerate(options):
            sel = idx[0] == i
            out.append(("class:sel" if sel else "", f"  {g['point']} " if sel else "    "))
            out.append(("class:sel" if sel else "", f"{label}\n"))
        return out

    def _right():
        out = [("class:group", _wrap("What is coming") + "\n\n")]
        if headlines:
            for line in headlines:
                out.append(("class:dim", _wrap(f"- {line}") + "\n"))
        else:
            out.append(("class:dim", _wrap("No release notes available.") + "\n"))
        out.append(
            (
                "class:dim",
                "\n"
                + _wrap(
                    "Pulls the new code and refreshes the copy Claude Code loads. Your settings, "
                    "preferences and model choice are not touched and are not re-asked."
                )
                + "\n",
            )
        )
        return out

    def _footer():
        return [("class:hint", chrome.ui_text(host, "  up/down move - Enter choose - Esc cancel"))]

    kb = KeyBindings()

    @kb.add("up")
    def _up(event):
        idx[0] = (idx[0] - 1) % len(options)

    @kb.add("down")
    def _down(event):
        idx[0] = (idx[0] + 1) % len(options)

    @kb.add("enter")
    def _enter(event):
        picked[0] = options[idx[0]][0]
        event.app.exit()

    @kb.add("escape", eager=True)
    @kb.add("c-c")
    @kb.add("q")
    def _esc(event):
        picked[0] = "cancel"
        event.app.exit()

    try:
        chrome.screen(
            host,
            title="Update the team",
            body_fn=_body,
            right_fn=_right,
            footer_fn=_footer,
            key_bindings=kb,
            output=output,
            header_fn=lambda: brand_header(ih),
        )
    except Exception:
        if os.environ.get("VIRT_SURV_DEBUG_APP"):
            raise
        return None
    return picked[0]
