#!/usr/bin/env python3
"""ADR-014 design spike - persistent guard daemon prototype.

NOT PRODUCTION. Built to answer ADR-014's open questions with evidence (IPC
portability, staleness handling, lifecycle, attack surface, testing strategy)
before any decision to build the real thing - not wired into run-guard.sh or any
live hook path. .claude/hooks/run-guard.sh is completely unchanged by this file's
existence; nothing here is imported or invoked by the live guard system.

Mechanism: a per-project daemon, started lazily by the client (guard_daemon_client.py,
this same directory), holding scripts.bash_hook_dispatcher's real, UNMODIFIED main()
imported ONCE, serving requests over a TCP socket bound to 127.0.0.1 on an
OS-assigned ephemeral port (never a fixed port - avoids collisions between
projects/sessions entirely, no port-picking logic needed). The bound port is
written to .claude/.guard-daemon-port (project-scoped, same file-based-coordination
pattern .guard-interpreter/.guard-lock already use) so a client can find it
without guessing.

Concurrency (a real finding from building this, not anticipated in the ADR text):
bash_hook_dispatcher.main() reads sys.stdin and (on some paths) writes sys.stderr
directly - process-global state. A naive threaded daemon serving concurrent
requests could let one request's payload leak into another's guard evaluation
mid-dispatch - genuinely dangerous for a security boundary, not just a correctness
nitpick. Dispatch is therefore serialized behind a single lock even though the
TCP server itself accepts concurrent connections; requests queue for the lock
rather than running the guard logic in parallel. This trades some of the
theoretical concurrency benefit for correctness - deliberate, not an oversight.
The win that survives: imports happen ONCE at daemon startup, so even serialized,
per-request cost is the guard's own decision time (expected sub-10ms once loaded)
plus IPC overhead, not the ~1.3s+ import/cold-start cost measured live via
run_hook_latency_diagnostic on 2026-08-12.

Staleness (ADR-014 open question 2): checked per request via mtime comparison
against the guard files loaded at startup - simplest viable, no watcher
dependency, per ADR-014's own recommendation. On detected staleness the daemon
answers the in-flight request with a "stale, retry" signal and self-terminates
(removing its port file) rather than attempting in-process module reload, which
is failure-prone for interdependent modules. The next client request that finds
no daemon running just starts a fresh one, which re-imports current code.

Lifecycle (ADR-014 open question 4): idle-timeout self-termination (default 30
minutes, --idle-timeout to override) is the bounded approximation used here - a
daemon with no session tie-in cannot know for certain when "its" Claude Code
session ended, so it errs toward not lingering forever rather than trying to
detect session end precisely. Not a complete answer - flagged as still open below.

Attack surface (ADR-014 open question 3): bound strictly to 127.0.0.1, never
0.0.0.0. The port-file-on-disk IS the access control in this prototype - anyone
with filesystem read access to this project's .claude/ directory can find the
port and connect, roughly the same trust boundary .guard-interpreter/.guard-lock
already imply as plain files. NOT hardened with a per-session token - an explicit
open item for a real implementation, not solved by this spike.

Protocol: one newline-delimited JSON request per connection -
{"payload": "<the PreToolUse JSON as text, exactly what stdin would have carried>"} -
and one newline-delimited JSON response -
{"exit_code": int, "stderr": str, "daemon_stale": bool (only present if true)}.
No stdout field - bash_hook_dispatcher.main() never writes stdout (verified by
reading its actual source, not assumed).
"""

from __future__ import annotations

import io
import json
import socketserver
import sys
import threading
import time
from pathlib import Path
from typing import Optional

IDLE_TIMEOUT_SECONDS_DEFAULT = 30 * 60
PORT_FILE_NAME = ".guard-daemon-port"


def _guard_module_paths(repo_root: Path) -> list:
    """Files whose mtime, if changed since load, mean this daemon's in-memory guard
    logic is stale. The same set bash_hook_dispatcher.py itself dispatches to, plus
    the dispatcher module and this daemon's own file (a spike-code change should
    also trigger a restart, not just a guard change)."""
    hooks = repo_root / ".claude" / "hooks"
    return [
        repo_root / "scripts" / "bash_hook_dispatcher.py",
        hooks / "guard-raw-data.py",
        hooks / "guard-code-execution.py",
        hooks / "guard-consent-writes.py",
        hooks / "guard-findings-pack-write.py",
        Path(__file__).resolve(),
    ]


def _mtimes(paths: list) -> dict:
    out = {}
    for p in paths:
        try:
            out[str(p)] = p.stat().st_mtime
        except OSError:
            out[str(p)] = None
    return out


def _load_dispatcher(repo_root: Path):
    """Imports the REAL, unmodified scripts.bash_hook_dispatcher - never a
    reimplementation. If this import fails, the daemon must not start at all
    (fail closed: no daemon is safer than a daemon with no guard logic loaded)."""
    import sys as _sys

    if str(repo_root) not in _sys.path:
        _sys.path.insert(0, str(repo_root))
    from scripts import bash_hook_dispatcher

    return bash_hook_dispatcher


class _Handler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        server = self.server
        server.last_activity = time.monotonic()
        try:
            raw = self.rfile.readline()
            if not raw:
                return
            request = json.loads(raw.decode("utf-8"))
            payload_text = request.get("payload", "")
        except (ValueError, UnicodeDecodeError) as exc:
            self._respond({"exit_code": 0, "stderr": f"bad request: {exc}"})
            return

        current = _mtimes(server.guard_paths)
        if current != server.loaded_mtimes:
            server.stale = True
            self._respond(
                {"exit_code": 0, "stderr": "daemon stale, restart and retry", "daemon_stale": True}
            )
            return

        exit_code, stderr_text = server.dispatch(payload_text)
        self._respond({"exit_code": exit_code, "stderr": stderr_text})

    def _respond(self, obj: dict) -> None:
        self.wfile.write((json.dumps(obj) + "\n").encode("utf-8"))


class GuardDaemon(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, repo_root: Path, idle_timeout: int = IDLE_TIMEOUT_SECONDS_DEFAULT):
        super().__init__(("127.0.0.1", 0), _Handler)
        self.repo_root = repo_root
        self.idle_timeout = idle_timeout
        self.guard_paths = _guard_module_paths(repo_root)
        self.loaded_mtimes = _mtimes(self.guard_paths)
        self.dispatcher_module = _load_dispatcher(repo_root)
        self.last_activity = time.monotonic()
        self.stale = False
        self._dispatch_lock = threading.Lock()

    def dispatch(self, payload_text: str):
        """Runs bash_hook_dispatcher.main() in-process - no subprocess, no cold
        start. Serialized (see module docstring: sys.stdin/sys.stderr are
        process-global, unsafe to swap concurrently across threads). Captures
        stderr exactly the same way the cold-start subprocess path already does
        (dispatcher writes block-reason text there, e.g. "guard_raw_data crashed
        unexpectedly; failing closed (blocked)."), so a client sees identical
        behaviour to today's cold-start path."""
        with self._dispatch_lock:
            old_stdin, old_stderr = sys.stdin, sys.stderr
            stderr_capture = io.StringIO()
            try:
                sys.stdin = io.StringIO(payload_text)
                sys.stderr = stderr_capture
                exit_code = self.dispatcher_module.main()
            finally:
                sys.stdin = old_stdin
                sys.stderr = old_stderr
            return exit_code, stderr_capture.getvalue()

    def idle_watchdog(self) -> None:
        while True:
            time.sleep(5)
            if self.stale:
                break
            if time.monotonic() - self.last_activity > self.idle_timeout:
                break
        self.shutdown()


def run(repo_root: Path, idle_timeout: int = IDLE_TIMEOUT_SECONDS_DEFAULT) -> int:
    """Starts the daemon and blocks until it shuts down (idle timeout or
    detected staleness) - the caller (main(), or a test) owns process lifetime."""
    daemon = GuardDaemon(repo_root, idle_timeout=idle_timeout)
    port_file = repo_root / ".claude" / PORT_FILE_NAME
    port_file.parent.mkdir(parents=True, exist_ok=True)
    port_file.write_text(str(daemon.server_address[1]), encoding="utf-8")
    watchdog = threading.Thread(target=daemon.idle_watchdog, daemon=True)
    watchdog.start()
    try:
        daemon.serve_forever(poll_interval=1.0)
    finally:
        # Only remove the port file if it still points at THIS daemon - a newer
        # daemon may have already overwritten it (e.g. a fast restart racing this
        # shutdown), and removing its entry would strand the next client.
        try:
            if port_file.read_text(encoding="utf-8").strip() == str(daemon.server_address[1]):
                port_file.unlink(missing_ok=True)
        except OSError:
            pass
    return 0


def read_port(repo_root: Path) -> Optional[int]:
    """Fail-open (None) on any read/parse error - a corrupt or half-written port
    file must never crash a client; it just means "no daemon available right
    now", the exact same posture as no port file existing at all."""
    port_file = repo_root / ".claude" / PORT_FILE_NAME
    try:
        return int(port_file.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo_root", nargs="?", default=".")
    parser.add_argument("--idle-timeout", type=int, default=IDLE_TIMEOUT_SECONDS_DEFAULT)
    args = parser.parse_args()
    return run(Path(args.repo_root).resolve(), idle_timeout=args.idle_timeout)


if __name__ == "__main__":
    sys.exit(main())
