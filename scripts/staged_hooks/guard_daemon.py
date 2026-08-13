#!/usr/bin/env python3
"""Persistent guard daemon - eliminates per-call interpreter cold start.

ADR-014 (docs/adr/ADR-014-persistent-guard-daemon.md). Preference-gated
(.claude/team-preferences.json `guard_daemon`, no machine-wide tier - same pattern
as `standards_critique`; on by default for any project set up via `/preferences`
or the installer's configure flow - see that skill's own docstring for the exact
"off if the key is genuinely absent" mechanics). run-guard.sh only ever talks to
this when the preference resolves true AND the target script is
bash_hook_dispatcher.py - every other case (preference off, or any other target
script such as locked_menu_guard.py) is completely unaffected; run-guard.sh's own
cold-start path is byte-for-byte what it was before this file existed.

Promoted from the design spike (docs/internal/adr-014-spike/) after live
validation on the actual reporting Windows box, 2026-08-12: 8/8 smoke-test
checks passed, including genuinely concurrent request safety and staleness
detection. This file adds the one thing the spike deliberately left open
(ADR-014 question 3, attack surface) - see "Attack surface" below - everything
else is the validated spike design, not a rewrite.

Mechanism: a per-project daemon, started lazily by run-guard.sh's client-mode
branch, holding scripts.bash_hook_dispatcher's real, UNMODIFIED main() imported
ONCE, serving requests over a TCP socket bound to 127.0.0.1 on an OS-assigned
ephemeral port. The bound port (and an auth token, see below) are written to
.claude/.guard-daemon-port (project-scoped, same file-based-coordination pattern
.guard-interpreter/.guard-lock already use).

2026-08-13 fix (same bug class run-guard.sh's own $_root/$_project_root split
already fixed elsewhere - live audit caught one instance the earlier fix missed):
this module now takes TWO roots, not one. `module_root` is where the real
scripts.bash_hook_dispatcher and the guard-*.py files actually live - genuinely
CLAUDE_PLUGIN_ROOT-first in plugin-install mode, since those are files the plugin
ships, not the consuming project. `state_root` is where per-project daemon state
(the port file) belongs - CLAUDE_PROJECT_DIR only, same reasoning as
run-guard.sh's own $_project_root: there is no correct case where one project's
port file/token should be shared with another project just because both happen
to use the same plugin install. Passing a single root for both (the old
behaviour) meant every project sharing one plugin install would share ONE
daemon and ONE port file - and since this daemon inherits CLAUDE_PROJECT_DIR at
its own startup and never re-reads it, a stale/wrong project's exec-consent
marker could get evaluated against a different project's request. Latent in
plugin-install mode only; a project-mode checkout (module_root == state_root,
e.g. this repo dogfooding itself) was never affected. Both parameters default to
each other when only one is given, so a caller that still passes just one root
keeps today's (project-mode-correct) behaviour unchanged.

Concurrency (found live while building the spike, not anticipated in ADR-014's
original text): bash_hook_dispatcher.main() reads sys.stdin and writes
sys.stderr directly - process-global state. A naive threaded daemon serving
concurrent requests could let one request's payload leak into another's guard
evaluation mid-dispatch - genuinely dangerous for a security boundary, not just
a correctness nitpick. Dispatch is therefore serialized behind a single lock
even though the TCP server itself accepts concurrent connections; requests
queue for the lock rather than running the guard logic in parallel. Live-tested
on the spike, 2026-08-12: 10 genuinely concurrent mixed requests, zero cross-talk.

Staleness (ADR-014 question 2, confirmed live 2026-08-12): checked per request
via mtime comparison against the guard files loaded at startup. On detected
staleness the daemon answers the in-flight request with a "stale, retry" signal
and self-terminates (removing its port file) rather than attempting in-process
module reload, which is failure-prone for interdependent modules. The next
client request that finds no daemon running just starts a fresh one, which
re-imports current code.

Lifecycle (ADR-014 question 4): idle-timeout self-termination (default 30
minutes, --idle-timeout to override) is the bounded approximation used here - a
daemon with no session tie-in cannot know for certain when "its" Claude Code
session ended, so it errs toward not lingering forever rather than trying to
detect session end precisely. Not independently live-verified (the automated
spike smoke test deliberately excluded it - needs a 60s+ manual wait).

Attack surface (ADR-014 question 3 - the one thing this promotion actually
changes from the spike): bound strictly to 127.0.0.1, never 0.0.0.0. A random
per-daemon token (secrets.token_hex, regenerated every start) is written
alongside the port and required on every request - a connection with a missing
or wrong token gets no useful response. This does NOT raise the bar against
someone who already has filesystem read access to this project's .claude/
directory (they can read the token from the same file they'd read the port
from - the same trust boundary .guard-interpreter/.guard-lock already imply as
plain files). It DOES close a narrower, real gap: a local process WITHOUT that
filesystem access can no longer reach the daemon just by port-scanning
127.0.0.1. Matches, rather than weakens, the trust model already implied
elsewhere in this project's file-based coordination.

Protocol: one newline-delimited JSON request per connection -
{"token": "<from the port file>", "payload": "<the PreToolUse JSON as text>"} -
and one newline-delimited JSON response -
{"exit_code": int, "stderr": str, "daemon_stale": bool (only if true)}. A
missing/wrong token gets {"exit_code": 0, "stderr": "unauthorized"} - fails
open at the PROTOCOL level (never blocks a tool call over an auth mismatch),
relying on the client falling back to cold-start, not on the daemon itself
enforcing a block. No stdout field - bash_hook_dispatcher.main() never writes
stdout (verified by reading its actual source, not assumed).
"""

from __future__ import annotations

import io
import json
import secrets
import socketserver
import sys
import threading
import time
from pathlib import Path

IDLE_TIMEOUT_SECONDS_DEFAULT = 30 * 60
PORT_FILE_NAME = ".guard-daemon-port"


def _guard_module_paths(repo_root: Path) -> list:
    """Files whose mtime, if changed since load, mean this daemon's in-memory guard
    logic is stale. The same set bash_hook_dispatcher.py itself dispatches to, plus
    the dispatcher module and this daemon's own file (a daemon-code change should
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
            token = request.get("token", "")
        except (ValueError, UnicodeDecodeError) as exc:
            self._respond({"exit_code": 0, "stderr": f"bad request: {exc}"})
            return

        if not secrets.compare_digest(token, server.token):
            # Constant-time comparison deliberately, even though the token's only
            # job here is closing the port-scan gap (see module docstring) rather
            # than defending a determined local attacker - cheap to get right,
            # no reason not to.
            self._respond({"exit_code": 0, "stderr": "unauthorized"})
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
        self.token = secrets.token_hex(16)
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


def run(
    module_root: Path,
    state_root: Path | None = None,
    idle_timeout: int = IDLE_TIMEOUT_SECONDS_DEFAULT,
) -> int:
    """Starts the daemon and blocks until it shuts down (idle timeout or
    detected staleness) - the caller (main(), or a test) owns process lifetime.
    state_root defaults to module_root (today's project-mode behaviour,
    unchanged) when not given - only plugin-install mode needs them to differ."""
    if state_root is None:
        state_root = module_root
    daemon = GuardDaemon(module_root, idle_timeout=idle_timeout)
    port_file = state_root / ".claude" / PORT_FILE_NAME
    port_file.parent.mkdir(parents=True, exist_ok=True)
    port_file.write_text(f"{daemon.server_address[1]}\n{daemon.token}\n", encoding="utf-8")
    watchdog = threading.Thread(target=daemon.idle_watchdog, daemon=True)
    watchdog.start()
    try:
        daemon.serve_forever(poll_interval=1.0)
    finally:
        # Only remove the port file if it still points at THIS daemon - a newer
        # daemon may have already overwritten it (e.g. a fast restart racing this
        # shutdown), and removing its entry would strand the next client.
        try:
            first_line = port_file.read_text(encoding="utf-8").splitlines()[0]
            if first_line.strip() == str(daemon.server_address[1]):
                port_file.unlink(missing_ok=True)
        except (OSError, IndexError):
            pass
    return 0


def read_port_and_token(state_root: Path):
    """Fail-open ((None, None)) on any read/parse error - a corrupt or
    half-written port file must never crash a client; it just means "no daemon
    available right now", the exact same posture as no port file existing at
    all. Takes the PROJECT root (per-project state), never the plugin root -
    see the module docstring's 2026-08-13 note."""
    port_file = state_root / ".claude" / PORT_FILE_NAME
    try:
        lines = port_file.read_text(encoding="utf-8").splitlines()
        return int(lines[0].strip()), lines[1].strip()
    except (OSError, ValueError, IndexError):
        return None, None


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("module_root", nargs="?", default=".")
    parser.add_argument(
        "state_root",
        nargs="?",
        default=None,
        help="Per-project daemon state (port file). Defaults to module_root when omitted.",
    )
    parser.add_argument("--idle-timeout", type=int, default=IDLE_TIMEOUT_SECONDS_DEFAULT)
    args = parser.parse_args()
    module_root = Path(args.module_root).resolve()
    state_root = Path(args.state_root).resolve() if args.state_root else None
    return run(module_root, state_root, idle_timeout=args.idle_timeout)


if __name__ == "__main__":
    sys.exit(main())
