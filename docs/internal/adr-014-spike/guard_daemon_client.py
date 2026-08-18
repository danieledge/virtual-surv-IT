#!/usr/bin/env python3
"""ADR-014 design spike - client for the guard_daemon.py prototype.

NOT PRODUCTION. Proves the connect-or-start-and-fall-back concept end to end;
does not modify or get invoked by .claude/hooks/run-guard.sh. A real
implementation would fold this logic into run-guard.sh itself (step 3 of
ADR-014's build plan), only once this spike has actually been validated live.

Behaviour, per ADR-014's own design: try to connect to a running daemon (via the
port file); if that fails for ANY reason (no port file, connection refused,
timeout, a malformed or stale-flagged response), fall back to the existing
cold-start path for THIS call only - subprocess against bash_hook_dispatcher.py
directly, exactly what run-guard.sh already does today - and separately,
best-effort, start a detached daemon for NEXT time. A daemon that fails to start
is not this call's problem; the fallback already covers it.

Usage: guard_daemon_client.py <repo_root>
Stdin: the PreToolUse JSON payload (same contract as bash_hook_dispatcher.py).
Exit code: 2 = block, 0 = allow - identical contract either path.
"""

from __future__ import annotations

import json
import socket
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from guard_daemon import read_port  # noqa: E402

_CONNECT_TIMEOUT = 0.5
_RESPONSE_TIMEOUT = 20.0


def _try_daemon(repo_root: Path, payload_text: str):
    """Returns (exit_code, stderr_text) on success, None on ANY failure - never
    raises, since a broken daemon connection must fall back cleanly, not crash
    the tool call it's guarding."""
    port = read_port(repo_root)
    if port is None:
        return None
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=_CONNECT_TIMEOUT) as sock:
            sock.settimeout(_RESPONSE_TIMEOUT)
            request = json.dumps({"payload": payload_text}) + "\n"
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
    if response.get("daemon_stale"):
        # Treated exactly like "no daemon" - cold-start THIS call; the daemon
        # has already self-terminated on its side, so starting a fresh one
        # below picks up current code.
        return None
    return response.get("exit_code", 0), response.get("stderr", "")


def _start_daemon_detached(repo_root: Path) -> None:
    """Best-effort, never blocks and never raises - a failed daemon start is not
    this call's problem, only a missed optimisation for next time."""
    try:
        daemon_script = Path(__file__).resolve().parent / "guard_daemon.py"
        kwargs = {}
        if sys.platform == "win32":
            # DETACHED_PROCESS: no console inherited from this process.
            # CREATE_NO_WINDOW: no new VISIBLE console window either - avoids
            # reintroducing a known Windows-specific bug class (a conhost.exe
            # popup per subprocess spawn, found in upstream Claude Code issue
            # tracking during this same investigation - missing windowsHide).
            kwargs["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW
        else:
            kwargs["start_new_session"] = True  # POSIX: detach from this process group
        subprocess.Popen(
            [sys.executable, str(daemon_script), str(repo_root)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            **kwargs,
        )
    except OSError:
        pass


def _cold_start_fallback(repo_root: Path, payload_text: str):
    """Exactly today's path - a fresh subprocess against the real dispatcher.
    Fails open on any launch problem, same posture as run-guard.sh's own
    no-interpreter-found case: a broken fallback must not brick the tool call."""
    dispatcher = repo_root / "scripts" / "bash_hook_dispatcher.py"
    try:
        proc = subprocess.run(
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
    repo_root = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path.cwd()
    payload_text = sys.stdin.read()

    result = _try_daemon(repo_root, payload_text)
    if result is None:
        _start_daemon_detached(repo_root)
        result = _cold_start_fallback(repo_root, payload_text)

    exit_code, stderr_text = result
    if stderr_text:
        sys.stderr.write(stderr_text)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
