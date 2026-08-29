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

HOSTS ARE NOT SHELLS (2026-08-26). On Windows the command ALWAYS runs through a shell, and
by preference through the shell the launcher itself was started from. Windows Terminal is a
host that runs a shell, not an alternative to one; handing it the launch command directly
spawned a bare process with no profile, no alias and no user PATH, which is why a corp box
that starts sessions perfectly well by hand got a window that failed on sight.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

# Windows SHELLS, in preference order - the things that can actually resolve a launch
# command. `start` is a cmd builtin, not an exe, hence the cmd /c wrapper further down.
_WINDOWS_SHELLS = ("pwsh.exe", "powershell.exe", "cmd.exe")
# Windows Terminal first (tabs, modern, present on Win11), then the shells hosting
# themselves. wt.exe is NOT a shell: it is a terminal HOST that runs one. Treating it as a
# peer of powershell.exe - handing it the launch command directly - is what broke the corp
# box on 2026-08-26: wt started `claude` as a bare process, with no profile loaded and no
# alias resolved, and the session never began. See _windows_argv.
_WINDOWS_TIERS = ("wt.exe",) + _WINDOWS_SHELLS
# Linux/BSD: the Debian alternatives symlink first (respects the user's own choice), then
# the desktop-native emulators, then the universal fallback.
# How long to wait for a spawned terminal to prove it did not die on its argv. Short enough
# not to be felt, long enough for a bad command line to fail.
_START_GRACE = 1.5
# Asking the shell whether it knows a command starts a shell, which on Windows is not fast.
# Generous, because timing out here means falling back to a same-window launch.
_RESOLVE_TIMEOUT = 20

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


def _in_tmux() -> bool:
    """Are we inside a tmux session, with tmux available to talk to?

    If so it is the right answer and the FIRST answer (2026-08-25, owner: "if running tmux
    why not open in a tmux window"). Exactly so: tmux is a window manager that needs no X
    display, works over ssh and mosh, and works in a container - all the places the
    graphical tiers below cannot go. Someone already in tmux almost certainly wants the new
    session in their tmux, not in a separate desktop window they then have to find.

    $TMUX is set by tmux inside every pane and by nothing else, so its presence is the test.
    """
    return bool(os.environ.get("TMUX")) and _which("tmux") is not None


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
    # BEFORE the display check, deliberately: tmux needs no display, and a headless box
    # inside tmux would otherwise report "no windowed terminal" while a perfectly good
    # window manager was running in the same terminal.
    if _in_tmux():
        return "tmux"
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


def _invoking_shell() -> str:
    """The Windows shell this process was started FROM, or "" if it cannot be told.

    THE POINT (owner, 2026-08-26: "why cant it just spawn a new window of the shell the tui
    is running in?"). Exactly so. The launcher is already running inside a shell that
    resolves the user's launch command - their profile, their alias, their PATH. Any other
    shell is a guess, and on a corporate box the guess is wrong in a way nothing downstream
    can recover from: the window opens, the command is unresolvable, and the launcher has
    already told the caller to stand down.

    Walks the PARENT CHAIN rather than reading the immediate parent, because that parent is
    normally python.exe (or py.exe, or the console host) and the shell sits above it.

    Returns "" freely - a failed detection falls back to the preference order, which is the
    behaviour this replaces. Never raises: this runs on the launch path."""
    if sys.platform != "win32":
        return ""
    try:
        import ctypes
        from ctypes import wintypes

        TH32CS_SNAPPROCESS = 0x00000002

        class PROCESSENTRY32W(ctypes.Structure):
            _fields_ = [
                ("dwSize", wintypes.DWORD),
                ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
                ("th32ModuleID", wintypes.DWORD),
                ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD),
                ("pcPriClassBase", ctypes.c_long),
                ("dwFlags", wintypes.DWORD),
                ("szExeFile", ctypes.c_wchar * 260),
            ]

        k32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        snapshot = k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if snapshot == ctypes.c_void_p(-1).value:
            return ""
        parents: dict[int, int] = {}
        names: dict[int, str] = {}
        try:
            entry = PROCESSENTRY32W()
            entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
            ok = k32.Process32FirstW(snapshot, ctypes.byref(entry))
            while ok:
                parents[entry.th32ProcessID] = entry.th32ParentProcessID
                names[entry.th32ProcessID] = entry.szExeFile.lower()
                ok = k32.Process32NextW(snapshot, ctypes.byref(entry))
        finally:
            k32.CloseHandle(snapshot)
        known = {name.lower() for name in _WINDOWS_SHELLS}
        pid = os.getpid()
        # Bounded: a corrupt or cyclic parent map must not spin on the launch path.
        for _ in range(12):
            pid = parents.get(pid, 0)
            if not pid:
                return ""
            name = names.get(pid, "")
            if name in known:
                return name
        return ""
    except Exception:
        return ""


def _windows_shell() -> str:
    """Which shell should run the command inside the new window.

    The one we were invoked from if we can tell and it is present, else the first available
    in preference order. Returns "" only when the box has no shell at all, which cannot
    happen in practice but must not raise if it does."""
    found = _invoking_shell()
    if found and _which(found):
        return found
    for candidate in _WINDOWS_SHELLS:
        if _which(candidate):
            return candidate
    return ""


def _posix_argv(terminal: str, command: list[str], cwd: Path) -> list[str]:
    exe = _which(terminal) or terminal
    if terminal == "tmux":
        # A new WINDOW in the caller's own session, not a new session: the point is that it
        # appears alongside what they are already looking at, one Ctrl-B n away. -c sets the
        # working directory; the command follows as separate arguments, which tmux runs
        # directly rather than through a shell - so nothing here needs quoting.
        return [exe, "new-window", "-c", str(cwd), "--"] + command
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


def _resolvable(program: str, terminal: str = "") -> bool:
    """Can the SHELL that will run this actually start it?

    `which` is the wrong authority and assuming otherwise broke a real setup (2026-08-25:
    the user's launch command is `cc`, a PowerShell alias defined in their profile - it is
    how they always start Claude, it is on no PATH, and the pre-check rejected it, so the
    session fell back to the same window every time). A launch command may legitimately be
    an alias, a function or a cmdlet; only the shell knows.

    So: cheap checks first, and if those fail, ASK THE SHELL rather than conclude. Nothing
    is more authoritative than the thing that would run it."""
    if not program:
        return False
    try:
        candidate = Path(program)
        if candidate.is_absolute():
            return candidate.is_file()
    except (OSError, ValueError):
        return False
    if _which(program) is not None:
        return True
    return _shell_knows(program, terminal)


def _shell_knows(program: str, terminal: str) -> bool:
    """Ask the launching shell whether it can resolve `program` - aliases and all.

    Costs one short-lived process, spent once on an unattended launch, and only when the
    cheap checks have already failed. Anything unexpected answers True: this is a
    pre-flight, and a pre-flight that blocks a launch it merely could not verify would
    recreate the bug it exists to prevent."""
    try:
        if sys.platform == "win32":
            # Ask the shell that will ACTUALLY run it. Under wt.exe this used to fall
            # through and answer True unconditionally, so an unresolvable command sailed
            # past the one check that exists to catch it - and because wt.exe forks its own
            # window and exits 0 immediately, the post-spawn check could not catch it
            # either. Both nets missed the same path (2026-08-26).
            shell = terminal if terminal in ("pwsh.exe", "powershell.exe") else _windows_shell()
            if shell not in ("pwsh.exe", "powershell.exe"):
                return True  # cmd.exe has no aliases to ask about
            # The PROFILE is loaded (no -NoProfile), which is where an alias like `cc`
            # lives - the same reason it works in the window the human already has open.
            exe = _which(shell) or shell
            probe = subprocess.run(  # noqa: S603 - argv built here, never shell
                # No -NoProfile, deliberately: the profile is exactly where an alias like
                # `cc` is defined, and skipping it would make the probe answer a different
                # question from the one that matters.
                [
                    exe,
                    "-NoLogo",
                    "-Command",
                    f"if (Get-Command {_ps_quote(program)} -ErrorAction SilentlyContinue) "
                    "{exit 0} else {exit 1}",
                ],
                capture_output=True,
                timeout=_RESOLVE_TIMEOUT,
            )
            return probe.returncode == 0
        if sys.platform != "win32":
            probe = subprocess.run(  # noqa: S603 - argv built here, never shell
                ["sh", "-lc", f"command -v {_quote(program)} >/dev/null 2>&1"],
                capture_output=True,
                timeout=_RESOLVE_TIMEOUT,
            )
            return probe.returncode == 0
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return True  # could not ask; do not block a launch on a failed question
    return True


def _quote(text: str) -> str:
    """POSIX single-quoting. Only used for the sh -c tiers above."""
    return "'" + str(text).replace("'", "'\\''") + "'"


def _shell_argv(shell: str, command: list[str], cwd: Path, set_cwd: bool = True) -> list[str]:
    """Run `command` THROUGH a shell, so the shell resolves it.

    Every Windows window path funnels through here, because "start the command" and "start
    a shell that starts the command" are not interchangeable: only the second loads the
    profile where the user's alias lives, and only the second gets the PATH they actually
    have. `set_cwd` is False when the window host has already been told the directory.
    """
    exe = _which(shell) or shell
    if shell in ("pwsh.exe", "powershell.exe"):
        # The CALL OPERATOR is not optional (live report 2026-08-25: PowerShell on Windows,
        # nothing launched, several minutes of nothing). Without `&`, "'claude' '/engage ...'"
        # is a STRING EXPRESSION - PowerShell evaluates it, prints it, and never runs a thing.
        # This is the same invocation shape the virt-surv alias itself uses to start a
        # session (`& $__vtCmd[0] @__vtCmdArgs "$__vtDecision"`), which is the method that is
        # known to work and therefore the one to copy.
        #
        # -NoExit deliberately: if the session fails to start, the window must stay open
        # carrying the error. It flashing shut is how this bug stayed invisible.
        call = "& " + " ".join(_ps_quote(part) for part in command)
        if set_cwd:
            call = f"Set-Location -LiteralPath {_ps_quote(str(cwd))}; {call}"
        return [exe, "-NoLogo", "-NoExit", "-Command", call]
    # cmd.exe: /k keeps the window open for the same reason -NoExit does.
    return [exe, "/k"] + command


def _wt_escape(argv: list[str]) -> list[str]:
    """Escape `;` for wt.exe's OWN command line, where it delimits subcommands.

    Unescaped, `wt -d . pwsh -Command "a; b"` opens a window running `a` and then tries to
    run `b` as a second wt subcommand. Nothing we pass carries prose (a typed request
    travels in a file, deliberately), so this is defence rather than a live fix."""
    return [part.replace(";", "\\;") for part in argv]


def _windows_argv(terminal: str, command: list[str], cwd: Path) -> list[str]:
    exe = _which(terminal) or terminal
    if terminal == "wt.exe":
        # wt.exe HOSTS a shell; it does not replace one. Handing it the command directly
        # made Windows Terminal spawn `claude` as a bare process - no profile, no alias, no
        # user PATH - which is precisely how a corp box that launches sessions perfectly
        # well by hand got a window that failed instantly (2026-08-26). `-d` already sets
        # the directory, so the shell does not repeat it and the argv carries no `;`.
        shell = _windows_shell()
        if shell:
            inner = _shell_argv(shell, command, cwd, set_cwd=False)
            return [exe, "-d", str(cwd)] + _wt_escape(inner)
        return [exe, "-d", str(cwd)] + command
    if terminal in ("pwsh.exe", "powershell.exe"):
        return _shell_argv(terminal, command, cwd)
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
    # Resolve the TARGET before spawning anything. Waiting on the spawned process cannot
    # answer this: the terminal wrapper starts fine and, with -NoExit, never exits at all -
    # so a command that does not exist still looked like a successful launch (proven on
    # WINTEST, PowerShell 5.1, 2026-08-25: a bogus executable reported True). The realistic
    # failure is `claude` not being on PATH for the spawned window, and this catches exactly
    # that, before the caller has been told to stand down.
    if command and not _resolvable(command[0], terminal):
        return False
    try:
        if terminal == "tmux":
            # tmux talks to its own server; it must NOT be detached from this process group
            # or it cannot find the session it is being asked to add a window to.
            argv = _posix_argv(terminal, command, cwd)
            proc = subprocess.run(argv, capture_output=True, timeout=_START_GRACE + 10)  # noqa: S603
            if proc.returncode != 0:
                return False
            return True
        if sys.platform == "darwin":
            joined = " ".join(_quote(part) for part in command)
            script = f'tell application "Terminal" to do script "cd {_quote(str(cwd))} && {joined}"'
            argv = ["osascript", "-e", script, "-e", 'tell application "Terminal" to activate']
        elif sys.platform == "win32":
            argv = _windows_argv(terminal, command, cwd)
        else:
            argv = _posix_argv(terminal, command, cwd)
        kwargs = {"cwd": str(cwd)}
        if sys.platform == "win32":
            # CREATE_NEW_CONSOLE, never DETACHED_PROCESS. Detached means the child gets NO
            # console at all - so powershell.exe starts, has nowhere to draw, and the user
            # sees nothing whatsoever (live report 2026-08-25). A new console is what
            # "another window" actually means on Windows.
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
        else:
            kwargs["start_new_session"] = True
        proc = subprocess.Popen(argv, **kwargs)  # noqa: S603 - argv is built here, never shell
    except (OSError, ValueError):
        return False
    # Popen succeeding proves only that the SPAWNER was found - not that a session started.
    # Treating it as proof is what let the launcher tell the shell to stand down while
    # nothing ran (2026-08-25). Give it a moment and reject an immediate non-zero exit, which
    # is what a bad argv looks like.
    try:
        proc.wait(timeout=_START_GRACE)
    except subprocess.TimeoutExpired:
        return True  # still running: the window is up
    except Exception:
        return True  # cannot tell; the terminal itself was found, so do not double-launch
    if proc.returncode not in (0, None):
        return False
    # A terminal that forks its own window (wt.exe, cmd start) exits 0 immediately and that
    # is normal, so 0 is not failure here.
    return True


def main(argv: list[str] | None = None) -> int:
    """Diagnose the windowed launch WITHOUT starting an engagement.

    Added 2026-08-25 after a live Windows report where an unattended run produced no window
    and no session: the only way to test the spawn was to start real work, which is a
    terrible way to debug and a worse way to find out it is broken. This reports what was
    found, prints the exact argv it would use, and with --open actually launches a harmless
    command so the window can be seen (or not) in isolation.

        python -m scripts.launch_terminal            # what would be used, and how
        python -m scripts.launch_terminal --open     # actually open one, harmlessly
    """
    import argparse

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass
    ap = argparse.ArgumentParser(description="Check the windowed-launch path.")
    ap.add_argument("--open", action="store_true", help="really open a test window")
    ap.add_argument("--command", default="", help="command to run (default: a harmless echo)")
    args = ap.parse_args(argv)

    print(f"platform          : {sys.platform}")
    print(f"graphical session : {_display_present()}")
    terminal = available()
    print(f"terminal found    : {terminal or 'NONE - a run would open in this window instead'}")
    if not terminal:
        return 1
    command = args.command.split() if args.command else _probe_command()
    cwd = Path.cwd()
    argv_built = (
        _windows_argv(terminal, command, cwd)
        if sys.platform == "win32"
        else _posix_argv(terminal, command, cwd)
    )
    print("argv it would run :")
    for part in argv_built:
        print(f"    {part}")
    if not args.open:
        print("\n(dry run - add --open to actually launch a window)")
        return 0
    ok = open_in_new_window(command, cwd)
    print(f"\nlaunched          : {ok}")
    print(
        "A window should now be visible. If this says True and you see nothing, the spawn "
        "is reporting success it cannot back up - say so, because that is the bug that "
        "stopped a session starting at all on 2026-08-25."
        if ok
        else "Nothing launched - an unattended run would fall back to this window, which is the "
        "correct behaviour."
    )
    return 0 if ok else 1


def _probe_command() -> list[str]:
    """Something harmless that proves a window appeared and stayed long enough to read."""
    if sys.platform == "win32":
        return ["cmd.exe", "/c", "echo virt-surv window test && pause"]
    return ["sh", "-c", "echo 'virt-surv window test'; sleep 20"]


if __name__ == "__main__":
    sys.exit(main())
