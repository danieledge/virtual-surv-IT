#!/usr/bin/env python3
"""Client for guard_daemon.py - ADR-014 (docs/adr/ADR-014-persistent-guard-daemon.md).

Invoked by run-guard.sh ONLY when both hold: the target script is one of the
daemon-servable set (guard_daemon.py's _TARGET_MODULE_NAMES), and
.claude/team-preferences.json has "guard_daemon": true. Every other case never
reaches this file - run-guard.sh's own cold-start path is unchanged.

Behaviour: try to connect to a running daemon (via the port file, token included
in the request per ADR-014 question 3); if that fails for ANY reason - no port
file, connection refused, timeout, a malformed or unauthorized/stale-flagged
response - fall back to the existing cold-start path for THIS call only
(subprocess against the real target script directly, exactly what run-guard.sh
would have done without the daemon), and separately, best-effort, start a
detached daemon for next time. A daemon that fails to start is not this call's
problem; the fallback already covers it.

2026-08-13 fix: TWO roots, not one - see guard_daemon.py's module docstring for
the full rationale. `module_root` locates the real target scripts (plugin-shipped,
CLAUDE_PLUGIN_ROOT-first). `state_root` locates this project's port file
(CLAUDE_PROJECT_DIR only). Passing only module_root keeps today's project-mode
behaviour (they default to each other) - only plugin-install mode, where the two
genuinely differ, needs both.

2026-08-14 multi-target extension: a THIRD argument names which target script this
call is for (defaults to "bash_hook_dispatcher" for a caller that predates this -
today's ONLY behaviour before this extension). Relays captured stdout as well as
stderr now - stop_hook_dispatcher.py answers via stdout, not stderr; every other
target never writes stdout at all, so this is a no-op for them.

Usage: guard_daemon_client.py <module_root> [state_root] [target]
Stdin: the PreToolUse/PostToolUse/Stop JSON payload (same contract as the real
target script would read directly).
Exit code: whatever the target script itself would exit - identical contract
either path (daemon-served or cold-start fallback).
"""

from __future__ import annotations

import json
import socket
import subprocess  # nosec B404 - fixed argv, shell=False, invoking our own sibling scripts only
import sys
from pathlib import Path

_CONNECT_TIMEOUT = 0.5
_RESPONSE_TIMEOUT = 20.0

# H2 (2026-08-14 perf audit): this file used to `from guard_daemon import
# read_port_and_token` - which executes the WHOLE daemon module (socketserver/threading/
# secrets/io, a real TCP server implementation) just to reach a 10-line file-read helper.
# Every daemon-routed hook call launches this client as a fresh interpreter (that per-call
# cold start is the whole reason the daemon exists - see the module docstring), so on the
# HAPPY PATH (daemon connects immediately) the daemon's own server-side imports were paid
# for nothing this call ever used. Inlined below instead of imported.
#
# `subprocess` stays a top-level import (NOT deferred to the two functions that use it,
# though the same reasoning would suggest it): tests/test_guard_daemon.py patches it as a
# module attribute (`monkeypatch.setattr(client.subprocess, "Popen", ...)`), which only
# resolves if the import is module-level - a local import inside a function is never
# reachable as `client.subprocess` from outside. Not worth breaking that established
# patching convention for a much smaller win than the read_port_and_token inline above.
PORT_FILE_NAME = ".guard-daemon-port"  # must match guard_daemon.py's own PORT_FILE_NAME


def read_port_and_token(state_root: Path):
    """Fail-open ((None, None)) on any read/parse error - a corrupt or half-written port
    file must never crash a client; it just means "no daemon available right now", the
    exact same posture as no port file existing at all. Takes the PROJECT root
    (per-project state), never the plugin root. Kept byte-identical to guard_daemon.py's
    own copy (this file's canonical source - see the H2 comment above for why this is a
    deliberate inline, not drift) - tests/test_guard_daemon.py pins the two in sync."""
    port_file = state_root / ".claude" / PORT_FILE_NAME
    try:
        lines = port_file.read_text(encoding="utf-8").splitlines()
        return int(lines[0].strip()), lines[1].strip()
    except (OSError, ValueError, IndexError):
        return None, None


def _try_daemon(state_root: Path, target: str, payload_text: str):
    """Returns (exit_code, stderr_text, stdout_text) on success, None on ANY
    failure - never raises, since a broken daemon connection must fall back
    cleanly, not crash the tool call it's guarding."""
    port, token = read_port_and_token(state_root)
    if port is None:
        return None
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=_CONNECT_TIMEOUT) as sock:
            sock.settimeout(_RESPONSE_TIMEOUT)
            request = json.dumps({"token": token, "target": target, "payload": payload_text}) + "\n"
            sock.sendall(request.encode("utf-8"))
            sock.shutdown(socket.SHUT_WR)
            chunks = []
            while True:
                chunk = sock.recv(65536)
                if not chunk:
                    break
                chunks.append(chunk)
            raw = b"".join(chunks)
        response = json.loads(raw.decode("utf-8"))
    except (OSError, ValueError):
        return None
    if response.get("daemon_stale") or response.get("stderr") == "unauthorized":
        # Both treated exactly like "no daemon" - cold-start THIS call. A stale
        # daemon (or an unknown-target response, which reuses this same signal -
        # see guard_daemon.py's _Handler.handle()) has already self-terminated or
        # answered safely on its side; an "unauthorized" response means the port
        # file and this client's read of it raced (a new daemon started between
        # the two reads) - either way, the fresh daemon start below picks up a
        # consistent state for next time.
        return None
    return response.get("exit_code", 0), response.get("stderr", ""), response.get("stdout", "")


def _start_daemon_detached(module_root: Path, state_root: Path) -> None:
    """Best-effort, never blocks and never raises - a failed daemon start is not
    this call's problem, only a missed optimisation for next time."""
    try:
        daemon_script = Path(__file__).resolve().parent / "guard_daemon.py"
        kwargs = {}
        if sys.platform == "win32":
            # DETACHED_PROCESS: no console inherited from this process.
            # CREATE_NO_WINDOW: no new VISIBLE console window either - avoids a
            # known Windows-specific bug class (a conhost.exe popup per
            # subprocess spawn) found in upstream Claude Code issue tracking
            # during this same investigation - missing windowsHide.
            # CREATE_BREAKAWAY_FROM_JOB (2026-08-13, reported via log analysis of a real
            # session): DETACHED_PROCESS/CREATE_NO_WINDOW control console inheritance, NOT
            # Windows Job Object membership - a child process is, by default, still added
            # to the SAME job as its parent regardless of those two flags. Many terminal/IDE
            # process launchers (and Git Bash's own process management) put their process
            # tree in a job with JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE, specifically so closing
            # the terminal kills every descendant - which silently kills this "detached"
            # daemon the moment the invoking session ends, defeating the entire point of a
            # persistent daemon. If the current job doesn't permit breakaway (rare, some
            # locked-down sandboxes), CreateProcess fails and Python raises OSError here -
            # already caught below, same fail-open posture as any other daemon-start
            # failure: the caller just falls back to cold-start, same as if this succeeded
            # and the daemon crashed a second later.
            kwargs["creationflags"] = (
                subprocess.DETACHED_PROCESS
                | subprocess.CREATE_NO_WINDOW
                | subprocess.CREATE_BREAKAWAY_FROM_JOB
            )
        else:
            kwargs["start_new_session"] = True  # POSIX: detach from this process group
        subprocess.Popen(  # nosec B603 - fixed argv, shell=False
            [sys.executable, str(daemon_script), str(module_root), str(state_root)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            **kwargs,
        )
    except OSError:
        pass


def _cold_start_fallback(module_root: Path, target: str, payload_text: str):
    """Exactly today's path - a fresh subprocess against the real target script.
    Fails open on any launch problem, same posture as run-guard.sh's own
    no-interpreter-found case: a broken fallback must not brick the tool call."""
    dispatcher = module_root / "scripts" / f"{target}.py"
    try:
        proc = subprocess.run(  # nosec B603 - fixed argv, shell=False
            [sys.executable, str(dispatcher)],
            input=payload_text,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return proc.returncode, proc.stderr, proc.stdout
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 0, f"cold-start fallback failed: {exc}", ""


def main() -> int:
    module_root = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path.cwd()
    state_root = Path(sys.argv[2]).resolve() if len(sys.argv) > 2 else module_root
    # Backward-compat default: a caller that predates the multi-target extension
    # never passes a third argument - it only ever meant bash_hook_dispatcher.
    target = sys.argv[3] if len(sys.argv) > 3 else "bash_hook_dispatcher"
    payload_text = sys.stdin.read()

    result = _try_daemon(state_root, target, payload_text)
    if result is None:
        _start_daemon_detached(module_root, state_root)
        result = _cold_start_fallback(module_root, target, payload_text)

    exit_code, stderr_text, stdout_text = result
    if stdout_text:
        sys.stdout.write(stdout_text)
    if stderr_text:
        sys.stderr.write(stderr_text)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
