#!/usr/bin/env python3
"""Shared terminal chrome for BOTH front doors: `virt-surv go` and `virt-surv`.

Extracted from launcher_app.py (2026-08-28) so the installer can look like the launcher
rather than like a 2019 shell script. Presentation only - the frame, the palette, the
glyph degradation, the two-pane split. Nothing here knows about engagements, settings or
installs, and nothing here should learn.

THE HOST PROTOCOL. Every entry point takes a `mod` handle and touches exactly four
attributes on it:

    _can_encode(text) -> bool     can THIS console render these glyphs?
    _morgan_line()    -> str      the one-line identity shown above the frame
    _plugin_version() -> str      for the frame title
    _git_branch(dir)  -> str      for the frame title

Four, deliberately. A host that has to supply more than a handful is a sign a screen has
leaked domain knowledge into this file.

ONE TRAP, AND IT IS SUBTLE. `_can_encode` must ask about the stream this chrome RENDERS
to, which is stderr. virt_team_launcher._can_encode already reads sys.stderr;
install_helper._can_encode defaults to sys.stdout, so its adapter has to pin the stream
explicitly. Getting that wrong does not fail loudly - it probes one console and draws on
another, so the ASCII fallbacks fire on the wrong condition and everything looks correct
on a developer machine.

CONTRACTS INHERITED FROM THE LAUNCHER (each has already caused a live bug):
  * stdout is a DATA channel for `virt-surv go`. This renders to STDERR, always.
  * cp1252 consoles: glyphs are chosen through `_can_encode`, never assumed - see
    ui_text() for the navigation glyphs and glyphs() for the semantic ones.
  * It is a TIER. Any failure must leave the caller able to fall back to plain prompts.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


def _bits(project_dir: Path, mod):
    """Header facts, reusing the launcher's own resolvers so nothing is re-derived."""
    facts = [project_dir.resolve().name or str(project_dir)]
    version = mod._plugin_version()
    if version:
        facts.append(f"v{version}")
    branch = mod._git_branch(project_dir)
    if branch:
        facts.append(branch)
    return ui_text(mod, "  ·  ").join(facts)


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

# Navigation glyphs, degraded together. The file's own header says box characters are
# "chosen through _can_encode, never assumed" - and then twenty-two footers, frame titles
# and hint lines assumed. The vendored output layer encodes with errors="replace", so a
# cp1252 console never crashed on them; it just rendered the navigation hint as
# "?? move ? Enter choose ? help ? Esc back", which is worse than useless because it
# looks like a rendering fault rather than a fallback.
#
# A WRAPPER rather than a dict of pieces, so the source still reads as the line it
# produces and a new footer cannot forget to consult it in one of its three spans.
_UI_FALLBACKS = (
    ("\u2191\u2193", "up/dn"),
    ("\u00b7", "-"),
    ("\u26a0", "!"),
    ("\u2190", "<-"),
    ("\u2026", "..."),
)


def ui_text(mod, text: str) -> str:
    """A hint, title or footer with its glyphs swapped for ASCII where the console needs
    it. Identity on any console that can encode them, which is most."""
    try:
        if mod._can_encode("".join(fancy for fancy, _plain in _UI_FALLBACKS)):
            return text
    except Exception:
        return text
    for fancy, plain in _UI_FALLBACKS:
        text = text.replace(fancy, plain)
    return text


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
        # An ellipsis, which is what the probe was there to test: three ASCII periods
        # encode everywhere, so the old check could only ever answer yes and the "fallback"
        # was unreachable.
        lead = "\u2026" if mod._can_encode("\u2026") else "..."
        text = lead + text[-(width - len(lead)) :]
    return text


# The narrowest terminal a two-pane split can honestly fit.
#
# The panes carry minimum widths (34 and 26) plus a divider and the frame's own borders,
# so below this the layout is WIDER THAN THE SCREEN and prompt_toolkit resolves that by
# overflowing: labels clip mid-word, the explanation wraps outside the frame border, and
# the right edge disappears off-screen entirely. Seen on a phone terminal at ~50 columns
# (2026-08-29) - "set up with recommended defau", and pane text running past the frame.
#
# 34 + 1 divider + 26 + 2 borders = 63, so 64 is the first width where the split has room
# to be what it claims to be.
NARROW_COLUMNS = 64


def term_columns(default: int = 80) -> int:
    """This terminal's width, measured on STDERR - never raising.

    shutil.get_terminal_size asks sys.__stdout__, and for `virt-surv go` stdout is a
    CAPTURED PIPE: the shell function runs the launcher inside $(...) to read the launch
    decision back. A pipe has no size, so shutil returned its (80, 24) fallback and every
    caller believed it was on an 80-column terminal - which is why the two-pane split kept
    being drawn on a 50-column phone even after it was taught to fold (photographed
    2026-08-29, second time).

    This module's own docstring already warns that _can_encode must ask about the stream
    the chrome RENDERS to, which is stderr, "and getting that wrong does not fail loudly".
    The same trap, one function further down, written by someone who had just documented
    it.

    Order: the real tty we draw on, then an explicitly exported COLUMNS, then stdout for
    the odd caller whose stdout is the terminal, then the default."""
    for stream in (sys.stderr, sys.stdout):
        try:
            if stream is not None and stream.isatty():
                return os.get_terminal_size(stream.fileno()).columns
        except Exception:
            continue
    try:
        declared = int(os.environ.get("COLUMNS", "") or 0)
        if declared > 0:
            return declared
    except Exception:
        pass
    try:
        return shutil.get_terminal_size((default, 24)).columns
    except Exception:
        return default


def is_narrow() -> bool:
    """Whether to fold the two panes into one column."""
    return term_columns() < NARROW_COLUMNS


def pane_width(default: int = 30) -> int:
    """Characters available for wrapped pane text.

    A single hard-coded 30 was fine beside a 26-column pane on a laptop and far too wide
    for the same text on a phone, where it is the only column and the frame borders and
    indent have to come out of it too."""
    columns = term_columns()
    if columns < NARROW_COLUMNS:
        return max(20, columns - 6)
    return default


def _stacked_rows(body_fn, right_fn) -> list:
    """The two panes as one column: the list, a blank line, then the explanation.

    A named function rather than a closure so it can be asserted on directly - the fold is
    the only thing that differs between a wide terminal and a narrow one, and both columns
    come from the same two callables either way."""
    rows = list(body_fn())
    rows.append(("", "\n"))
    rows.extend(right_fn())
    return rows


def screen(
    mod,
    *,
    title,
    body_fn,
    footer_fn,
    key_bindings,
    output=None,
    right_fn=None,
    project_dir=None,
    refresh_interval=None,
    header_fn=None,
):
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
    if right_fn is not None and is_narrow():
        # ONE COLUMN. The explanation is not dropped - it moves underneath the list, where
        # it still describes the highlighted row and has the full width to do it in. A
        # pane that has to clip both of its columns tells you less than a single column
        # that fits.
        body = Window(
            FormattedTextControl(lambda: _stacked_rows(body_fn, right_fn)), wrap_lines=True
        )
    elif right_fn is not None:
        # 2:1 in favour of the left. An even split (the original) truncated the settings
        # rows mid-label once the explanation pane arrived and pushed the on/off column
        # clean off the screen - proven under a pty, 2026-08-20.
        body = VSplit(
            [
                Window(FormattedTextControl(body_fn), wrap_lines=False, width=D(min=34, weight=2)),
                # A GAP, not a pipe, when the console cannot encode the box-drawing
                # glyph (2026-08-28 live report: "the vertical divider has misplaced pipe
                # symbols"). U+2502 is designed to join vertically, so a column of them
                # reads as one continuous line. An ASCII '|' is not: the glyph has
                # clearance above and below, so a column of them reads as a ladder of
                # disconnected marks - which on a corp-Windows cp1252 console, where the
                # fallback always fires, is exactly what it looked like.
                #
                # Two spaces separate the panes just as clearly and cannot render badly.
                # A divider that only works on half the target machines is worse than
                # whitespace that works on all of them.
                Window(
                    width=1 if mod._can_encode("│") else 2,
                    char="│" if mod._can_encode("│") else " ",
                    style="class:dim",
                ),
                Window(FormattedTextControl(right_fn), width=D(min=26, weight=1), wrap_lines=True),
            ]
        )
    # A caller-supplied header replaces the identity line entirely, and may be several
    # rows tall. The installer uses it to put the brand banner INSIDE the frame: the app
    # runs in the alternate screen, so anything printed before it is invisible for as long
    # as someone is actually using the menu, and only reappears once they leave (owner
    # decision, 2026-08-28). Identity belongs where it can be seen.
    if header_fn is not None:
        rows = header_fn()
        header = [
            Window(FormattedTextControl(row_fn), height=1)
            for row_fn in (lambda row=row: row for row in rows)
        ]
    else:
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
