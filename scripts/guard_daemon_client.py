#!/usr/bin/env python3
"""Client for guard_daemon.py - ADR-014 (docs/adr/ADR-014-persistent-guard-daemon.md).

Invoked by run-guard.sh ONLY when both hold: the target script is
bash_hook_dispatcher.py, and .claude/team-preferences.json has "guard_daemon": true.
Every other case never reaches this file - run-guard.sh's own cold-start path is
unchanged.

Behaviour: try to connect to a running daemon (via the port file, token included
in the request per ADR-014 question 3); if that fails for ANY reason - no port
file, connection refused, timeout, a malformed or unauthorized/stale-flagged
response - fall back to the existing cold-start path for THIS call only
(subprocess against bash_hook_dispatcher.py directly, exactly what run-guard.sh
would have done without the daemon), and separately, best-effort, start a
detached daemon for next time. A daemon that fails to start is not this call's
problem; the fallback already covers it.

2026-08-13 fix: TWO roots now, not one - see guard_daemon.py's module docstring
for the full rationale. `module_root` locates the real bash_hook_dispatcher.py
(plugin-shipped, CLAUDE_PLUGIN_ROOT-first). `state_root` locates this project's
port file (CLAUDE_PROJECT_DIR only). Passing only module_root keeps today's
project-mode behaviour (they default to each other) - only plugin-install mode,
where the two genuinely differ, needs both.

Usage: guard_daemon_client.py <module_root> [state_root]
Stdin: the PreToolUse JSON payload (same contract as bash_hook_dispatcher.py).
Exit code: 2 = block, 0 = allow - identical contract either path.
"""

from __future__ import annotations

import json
import socket
import subprocess  # nosec B404 - fixed argv, shell=False, invoking our own sibling scripts only
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from guard_daemon import read_port_and_token  # noqa: E402

_CONNECT_TIMEOUT = 0.5
_RESPONSE_TIMEOUT = 20.0


def _try_daemon(state_root: Path, payload_text: str):
    """Returns (exit_code, stderr_text) on success, None on ANY failure - never
    raises, since a broken daemon connection must fall back cleanly, not crash
    the tool call it's guarding."""
    port, token = read_port_and_token(state_root)
    if port is None:
        return None
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=_CONNECT_TIMEOUT) as sock:
            sock.settimeout(_RESPONSE_TIMEOUT)
            request = json.dumps({"token": token, "payload": payload_text}) + "\n"
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
        # daemon has already self-terminated on its side; an "unauthorized"
        # response means the port file and this client's read of it raced (a
        # new daemon started between the two reads) - either way, the fresh
        # daemon start below picks up a consistent state for next time.
        return None
    return response.get("exit_code", 0), response.get("stderr", "")


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
            kwargs["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW
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


def _cold_start_fallback(module_root: Path, payload_text: str):
    """Exactly today's path - a fresh subprocess against the real dispatcher.
    Fails open on any launch problem, same posture as run-guard.sh's own
    no-interpreter-found case: a broken fallback must not brick the tool call."""
    dispatcher = module_root / "scripts" / "bash_hook_dispatcher.py"
    try:
        proc = subprocess.run(  # nosec B603 - fixed argv, shell=False
            [sys.executable, str(dispatcher)],
            input=payload_text,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return proc.returncode, proc.stderr
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 0, f"cold-start fallback failed: {exc}"


def main() -> int:
    module_root = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path.cwd()
    state_root = Path(sys.argv[2]).resolve() if len(sys.argv) > 2 else module_root
    payload_text = sys.stdin.read()

    result = _try_daemon(state_root, payload_text)
    if result is None:
        _start_daemon_detached(module_root, state_root)
        result = _cold_start_fallback(module_root, payload_text)

    exit_code, stderr_text = result
    if stderr_text:
        sys.stderr.write(stderr_text)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
