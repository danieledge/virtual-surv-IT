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
        # The day-to-day guide (2026-09-12). Probed on its own, like "browse": the shared
        # probe string above does not carry this character, and a glyph nobody tested is
        # exactly how mojibake reaches a cp1252 console.
        "howto": "📖 " if rich and mod._can_encode("📖") else "",
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
# 34 + 1 divider + 26 + 2 borders = 63, so 64 is where the split first FITS - and 64 was
# the wrong number, because fitting is not the test. Measured on a real phone terminal
# reporting 66 columns (2026-08-29): the right pane is pinned at its 26-column minimum
# anywhere below ~96, so the left pane gets whatever is left - 37 columns at 66 - and the
# longest row on the setup screen is 38 characters. It fitted, and it clipped.
#
# The floor is therefore set by the widest ROW, not by the sum of the minimums: the left
# pane needs ~42 to hold one, so 42 + 26 + 1 + 2 = 71 is the true minimum and 80 is the
# first comfortable width. 80 is also the classic terminal width, which makes the rule
# easy to hold in your head: below 80 columns, one column.
NARROW_COLUMNS = 80


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

    Order: an explicitly exported COLUMNS, then the real tty we draw on, then stdout for
    the odd caller whose stdout is the terminal, then a default.

    COLUMNS FIRST, which is the order shutil.get_terminal_size uses and for the reason it
    uses it: it is the documented way for someone to override a terminal that misreports
    its own size. Putting the ioctl first - as a first version of this did - is defensible
    right up to the moment a terminal lies, and then it takes away the only lever the user
    has. Some phone terminals and multiplexers advertise a width wider than the glass."""
    try:
        declared = int(os.environ.get("COLUMNS", "") or 0)
        if declared > 0:
            return declared
    except Exception:  # nosec B110 - COLUMNS env var probe; falls through to the terminal-size probes below
        pass
    for stream in (sys.stderr, sys.stdout):
        try:
            if stream is not None and stream.isatty():
                return os.get_terminal_size(stream.fileno()).columns
        except Exception:  # nosec B112 - a stream that cannot answer terminal size is a no; try the next stream
            continue
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


def default_output():
    """The Output this chrome renders on when the caller did not supply one.

    WHY IT IS NOT JUST create_output (2026-09-12, Windows CI). prompt_toolkit's
    create_output only asks `isatty()` on the POSIX branch, where a non-tty stream
    degrades to PlainTextOutput. On win32 it goes straight to Win32Output/Windows10_Output,
    which ask the console for a screen buffer and raise NoConsoleScreenBufferError when the
    stream is a pipe or a captured stream. Every screen in this file is wrapped in a
    `return <could-not-draw sentinel>` handler, so that raise read as "this tier cannot
    draw" and the whole full-screen tier fell through to the numbered prompts on any
    Windows box whose stderr was redirected - including the CI runner, where four tests
    that pass everywhere else failed with a plain-tier transcript.

    So make the isatty test ours and apply it on both platforms, which is what the POSIX
    branch already does. A real console is untouched: create_output still picks the Win32
    or VT100 layer there.
    """
    from prompt_toolkit.output.defaults import create_output

    stream = sys.stderr
    try:
        is_tty = bool(stream is not None and stream.isatty())
    except Exception:  # noqa: BLE001 - a stream that cannot answer is a no
        is_tty = False
    if not is_tty:
        from prompt_toolkit.output.plain_text import PlainTextOutput

        return PlainTextOutput(stream if stream is not None else sys.stdout)
    return create_output(stdout=stream)


def hold_for_reader(stream=None, prompt: str = "       Press Enter to continue... ") -> None:
    """Keep a printed message on screen until it has been read.

    ONE helper (2026-09-12 audit, L-28). Two copies of this existed - the launcher's
    `_hold_for_reader` and the installer's `pause_before_menu` - both added on 2026-09-11
    for the same cause (a full-screen app repainting over a line that was on screen for a
    frame), and they disagreed about which stream to test: the launcher required stdin AND
    stderr, the installer stdin AND stdout. Neither file said why, and the two are NOT
    interchangeable - `virt-surv go` runs inside `$(...)`, so its stdout is the alias
    capture pipe and testing it would silence the pause on every real launch, while the
    installer's stdout is the terminal it prints to. The stream to test is therefore the
    caller's decision and is passed in; the rest of the behaviour is shared.

    A read-receipt, not a question: silent when nobody is at the keyboard, and EOF or
    Ctrl-C here carries on rather than aborting anything.
    """
    target = stream if stream is not None else sys.stderr
    try:
        if not sys.stdin.isatty() or not target.isatty():
            return
    except Exception:  # noqa: BLE001 - a stream that cannot answer is a no
        return
    # The prompt goes to the caller's stream by hand. input(prompt) writes its prompt to
    # STDOUT whatever stream the caller chose, and `virt-surv go` runs inside `$(...)`: the
    # words "Press Enter to go back to the menu..." were captured with the launch decision
    # and handed to Claude Code as the opening prompt (live report with a photo, 2026-09-12).
    try:
        target.write(prompt)
        target.flush()
    except Exception:  # noqa: BLE001 - a pause must never cost the caller  # nosec B110 - a pause must never cost the caller
        pass
    try:
        input()
    except (EOFError, KeyboardInterrupt):
        try:
            print("", file=target)
        except Exception:  # noqa: BLE001 - a pause must never cost the caller  # nosec B110 - a pause must never cost the caller
            pass


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
        # OFF, because nothing here answers a click. No row has a mouse handler, so the
        # only effect of enabling it was that terminals which forward mouse events showed
        # a cursor that highlighted nothing and selected nothing - which reads as broken,
        # and also takes text selection away from the terminal, so you cannot copy a path
        # off the screen. Turning it on again means wiring click-to-select first
        # (independent TUI review, 2026-08-31).
        mouse_support=False,
        output=output or default_output(),
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
