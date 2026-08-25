#!/usr/bin/env python3
"""Open a command in a NEW terminal window (2026-08-25).

WHY. `virt-surv go` replaced itself with the Claude session, so the TUI that just took the
decision vanished the moment the work started. For an ATTENDED run that is merely a lost
pane; for an UNATTENDED one it is the whole problem - nobody is being asked anything, so
the launcher is the only place progress could be shown, and it had already exited. Opening
the session beside the launcher rather than on top of it is what makes a live status view
possible at all, which is why this lands before headless rather than after it.

WHAT IT DOES NOT DO. It does not detach, daemonise, or survive logout - the window is an
ordinary child of the user's desktop session. Headless operation is a separate problem and
this is deliberately not a half-built version of it.

HOW IT DECIDES. Tiers per platform, first that exists wins, and **every tier is checked for
existence before it is used** - a corporate Windows box may have no Windows Terminal, a
Linux box may have no X display at all, and guessing wrong means the session silently never
starts. `available()` answers the question without launching anything, so the caller can
fall back to launching in-place instead of stranding the user with neither.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

# Windows: Windows Terminal first (tabs, modern, present on Win11), then the classic hosts.
# `start` is a cmd builtin, not an exe, hence the cmd /c wrapper.
_WINDOWS_TIERS = ("wt.exe", "pwsh.exe", "powershell.exe", "cmd.exe")
# Linux/BSD: the Debian alternatives symlink first (respects the user's own choice), then
# the desktop-native emulators, then the universal fallback.
_POSIX_TIERS = (
    "x-terminal-emulator",
    "gnome-terminal",
    "konsole",
    "xfce4-terminal",
    "mate-terminal",
    "kitty",
    "alacritty",
    "xterm",
)


def _display_present() -> bool:
    """A graphical session to open a window INTO. Without one, every emulator below exists
    and fails at runtime - the worst shape of failure, since the caller has already decided
    not to launch in-place by then."""
    if sys.platform == "darwin" or sys.platform == "win32":
        return True
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def _which(name: str) -> str | None:
    return shutil.which(name)


def available() -> str:
    """The terminal this machine would use, or "" if none. Launches nothing."""
    if not _display_present():
        return ""
    if sys.platform == "win32":
        for candidate in _WINDOWS_TIERS:
            if _which(candidate):
                return candidate
        return ""
    if sys.platform == "darwin":
        return "osascript" if _which("osascript") else ""
    for candidate in _POSIX_TIERS:
        if _which(candidate):
            return candidate
    return ""


def _posix_argv(terminal: str, command: list[str], cwd: Path) -> list[str]:
    exe = _which(terminal) or terminal
    # gnome-terminal and its relatives take `--` before the command; the others use -e.
    if terminal in ("gnome-terminal", "mate-terminal"):
        return [exe, f"--working-directory={cwd}", "--"] + command
    if terminal == "xfce4-terminal":
        return [exe, f"--working-directory={cwd}", "-x"] + command
    if terminal == "konsole":
        return [exe, "--workdir", str(cwd), "-e"] + command
    if terminal in ("kitty", "alacritty"):
        flag = "--directory" if terminal == "kitty" else "--working-directory"
        return [exe, flag, str(cwd)] + (["-e"] if terminal == "alacritty" else []) + command
    # x-terminal-emulator and xterm: no portable working-directory flag, so cd in a shell.
    joined = " ".join(_quote(part) for part in command)
    return [exe, "-e", "sh", "-c", f"cd {_quote(str(cwd))} && {joined}"]


def _quote(text: str) -> str:
    """POSIX single-quoting. Only used for the sh -c tiers above."""
    return "'" + str(text).replace("'", "'\\''") + "'"


def _windows_argv(terminal: str, command: list[str], cwd: Path) -> list[str]:
    exe = _which(terminal) or terminal
    if terminal == "wt.exe":
        return [exe, "-d", str(cwd)] + command
    if terminal in ("pwsh.exe", "powershell.exe"):
        # -NoExit would leave a dead shell if the command fails; the caller wants the
        # window to close with the session, same as any other tier here.
        return [exe, "-NoLogo", "-Command", f"Set-Location -LiteralPath {_ps_quote(str(cwd))}; "
                + " ".join(_ps_quote(part) for part in command)]
    return [exe, "/c", "start", "", "/D", str(cwd)] + command


def _ps_quote(text: str) -> str:
    """PowerShell single-quoting: double the single quotes, wrap in singles. NOT used for
    the value that broke a typed request (2026-08-25) - nothing here crosses a native-exe
    argument boundary carrying user prose; the request travels in a file for that reason."""
    return "'" + str(text).replace("'", "''") + "'"


def open_in_new_window(command: list[str], cwd: Path) -> bool:
    """Start `command` in a new terminal window rooted at `cwd`. True if it was launched.

    Never raises: a caller that gets False launches in-place instead, which is the
    behaviour this replaces and is always correct."""
    terminal = available()
    if not terminal:
        return False
    try:
        if sys.platform == "darwin":
            joined = " ".join(_quote(part) for part in command)
            script = (
                f'tell application "Terminal" to do script '
                f'"cd {_quote(str(cwd))} && {joined}"'
            )
            argv = ["osascript", "-e", script, "-e",
                    'tell application "Terminal" to activate']
        elif sys.platform == "win32":
            argv = _windows_argv(terminal, command, cwd)
        else:
            argv = _posix_argv(terminal, command, cwd)
        kwargs = {"cwd": str(cwd)}
        if sys.platform == "win32":
            # Detach so the launcher's own console is not the parent of the new window.
            kwargs["creationflags"] = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
                subprocess, "CREATE_NEW_PROCESS_GROUP", 0
            )
        else:
            kwargs["start_new_session"] = True
        subprocess.Popen(argv, **kwargs)  # noqa: S603 - argv is built here, never shell
        return True
    except (OSError, ValueError):
        return False
