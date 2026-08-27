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
import os
import socket
import sys
import time

_CONNECT_TIMEOUT = 0.5
_RESPONSE_TIMEOUT = 20.0

# H3 (2026-08-14 perf audit): a daemon that can NEVER actually start (e.g.
# CREATE_BREAKAWAY_FROM_JOB denied on a locked-down Windows sandbox, or one of the six
# daemon target modules failing to import inside guard_daemon.py's constructor) used to
# pay a full `_start_daemon_detached` Popen AND the cold-start fallback's own subprocess
# on every single call, forever - strictly worse than daemon-off, silently, with no
# backoff. The marker below rate-limits repeated Popen attempts once a streak of them has
# produced no working daemon (inferred the only way a client CAN infer it: _try_daemon
# still misses on a later call), same short-TTL-file-cache pattern as
# guard-raw-data.py's `_RAW_PRESENT_CACHE` / run-guard.sh's `.guard-coldstart-ms`.
# Conservative by construction: any read/write failure on the marker falls through to
# "attempt the Popen" (today's behaviour, never worse), and the fallback cold-start path
# below is completely untouched either way - only the redundant Popen-per-call is gated.
_START_BACKOFF_MARKER_NAME = ".guard-daemon-start-backoff"
_START_BACKOFF_THRESHOLD = 3  # consecutive failed-to-connect attempts before backing off
_START_BACKOFF_TTL_SECONDS = 300  # retry again after this long even while backed off -
# a daemon that WAS broken but got fixed (e.g. the user updated a target module) must
# not be permanently locked out.

# H2 (2026-08-14 perf audit): this file used to `from guard_daemon import
# read_port_and_token` - which executes the WHOLE daemon module (socketserver/threading/
# secrets/io, a real TCP server implementation) just to reach a 10-line file-read helper.
# Every daemon-routed hook call launches this client as a fresh interpreter (that per-call
# cold start is the whole reason the daemon exists - see the module docstring), so on the
# HAPPY PATH (daemon connects immediately) the daemon's own server-side imports were paid
# for nothing this call ever used. Inlined below instead of imported.
#
# `subprocess` IS deferred (2026-08-26). The note here previously kept it top-level to
# preserve tests/test_guard_daemon.py's `monkeypatch.setattr(client.subprocess, ...)`
# convention, judging the win "much smaller" than the read_port_and_token inline - a
# judgement made without a measurement. Measured: `-X importtime` puts subprocess at 11.9ms
# of an ~87ms client call, and NOTHING on the happy path uses it (it appears only in
# _start_daemon_detached and _cold_start_fallback). Every daemon-routed hook call was
# importing a process-spawning library in order not to spawn a process.
#
# The patching convention is preserved exactly, by two mechanisms that work together:
#   - the module-level __getattr__ below resolves `client.subprocess` for outside callers
#     (PEP 562), so `monkeypatch.setattr(client.subprocess, "Popen", ...)` still finds the
#     real module;
#   - that patch mutates the singleton in sys.modules, so the deferred `import subprocess`
#     inside each function retrieves the SAME already-patched object.
# Module-level __getattr__ is not consulted for the module's own global lookups, which is
# why each function imports it by name rather than relying on the hook.
PORT_FILE_NAME = ".guard-daemon-port"  # must match guard_daemon.py's own PORT_FILE_NAME


def __getattr__(name):
    """Resolve `client.subprocess` on demand - see the deferral note above.

    Only ever fires for an attribute this module does not define, so it costs nothing on
    the happy path and keeps the established test-patching convention working."""
    if name == "subprocess":
        import subprocess  # nosec B404 - fixed argv, shell=False, our own sibling scripts

        return subprocess
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def read_port_and_token(state_root):
    """Fail-open ((None, None)) on any read/parse error - a corrupt or half-written port
    file must never crash a client; it just means "no daemon available right now", the
    exact same posture as no port file existing at all. Takes the PROJECT root
    (per-project state), never the plugin root. guard_daemon.py keeps its own copy of this
    logic (this file is the canonical source - see the H2 comment above for why that is a
    deliberate inline, not drift); the two are pinned by the BEHAVIOURAL tests in
    tests/test_guard_daemon.py, not by textual identity - an earlier version of this
    docstring claimed a byte-identical pin that no test actually asserted.

    F2 (2026-08-26 perf audit): os.path, not pathlib. Accepts str or Path either way."""
    port_file = os.path.join(str(state_root), ".claude", PORT_FILE_NAME)
    try:
        with open(port_file, encoding="utf-8") as handle:
            lines = handle.read().splitlines()
        return int(lines[0].strip()), lines[1].strip()
    except (OSError, ValueError, IndexError):
        return None, None


def _try_daemon(state_root, target: str, payload_text: str):
    """Returns (exit_code, stderr_text, stdout_text) on success, None on ANY
    failure - never raises, since a broken daemon connection must fall back
    cleanly, not crash the tool call it's guarding."""
    port, token = read_port_and_token(state_root)
    if port is None:
        return None
    # F3 (2026-08-26 perf audit): a raw socket, NOT socket.create_connection.
    # create_connection routes even a dotted-quad literal through getaddrinfo, whose C
    # IDNA converter imports encodings.idna -> stringprep -> unicodedata. Verified:
    # create_connection(("127.0.0.1", 1)) leaves encodings.idna imported, a bare
    # socket().connect() does not. Measured 6.6ms per call here - and on Windows the cost
    # is worse in kind, not just degree: getaddrinfo traverses the Winsock LSP/NSP chain,
    # which on a corporate box routinely has DNS-client and security providers layered
    # in, and which occasionally HANGS rather than merely being slow.
    #
    # Nothing is given up. The daemon binds ("127.0.0.1", 0) - always IPv4, always a
    # literal - so there is no name to resolve and no address list to walk. connect()
    # raises the same OSError class create_connection re-raises, so the fail-open-to-
    # cold-start posture below is unchanged. try/finally replaces the context manager,
    # which create_connection provided and a bare socket does not.
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.settimeout(_CONNECT_TIMEOUT)
            sock.connect(("127.0.0.1", port))
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
        finally:
            sock.close()
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


def _start_daemon_detached(module_root, state_root) -> None:
    """Best-effort, never blocks and never raises - a failed daemon start is not
    this call's problem, only a missed optimisation for next time."""
    import subprocess  # nosec B404 - deferred; see the note above

    try:
        daemon_script = os.path.join(os.path.dirname(os.path.realpath(__file__)), "guard_daemon.py")
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


def _start_backoff_marker(state_root) -> str:
    return os.path.join(str(state_root), ".claude", _START_BACKOFF_MARKER_NAME)


def _read_start_backoff(state_root):
    """Returns (streak_count, age_seconds) - (0, None) when the marker is absent,
    unreadable or corrupt (fail open: an unreadable marker means "no known backoff",
    same posture as read_port_and_token above). age_seconds is always populated
    together with a non-zero count, since both come from the same successful read."""
    marker = _start_backoff_marker(state_root)
    try:
        with open(marker, encoding="utf-8") as handle:
            count = int(handle.read().strip())
        age = time.time() - os.stat(marker).st_mtime
        return count, age
    except (OSError, ValueError):
        return 0, None


def _record_start_attempt(state_root, streak_count: int) -> None:
    """Best-effort - a failed write just means the next call re-evaluates from
    scratch (falls open to "attempt the Popen"), never a reason to raise."""
    marker = _start_backoff_marker(state_root)
    try:
        os.makedirs(os.path.dirname(marker), exist_ok=True)
        with open(marker, "w", encoding="utf-8") as handle:
            handle.write(str(streak_count))
    except OSError:
        pass


def _clear_start_backoff(state_root) -> None:
    """Called once a daemon actually answers a request - the one signal this client
    ever gets that a start attempt genuinely worked. Wipes the streak so the next
    failure (if the daemon later dies) starts counting from zero again, not from
    wherever an old streak left off."""
    try:
        os.remove(_start_backoff_marker(state_root))
    except OSError:
        pass


def _maybe_start_daemon(module_root, state_root) -> None:
    """Rate-limited wrapper around _start_daemon_detached: after
    _START_BACKOFF_THRESHOLD consecutive attempts with no confirmed-working daemon,
    stop spawning a fresh Popen every call until _START_BACKOFF_TTL_SECONDS has
    passed since the last attempt. Worst case on ANY failure in the backoff
    bookkeeping itself is "attempt the Popen anyway" - identical to before this fix
    existed, never worse."""
    count, age = _read_start_backoff(state_root)
    if count >= _START_BACKOFF_THRESHOLD and age is not None and age < _START_BACKOFF_TTL_SECONDS:
        return  # backed off - still within the TTL window since the last attempt
    _start_daemon_detached(module_root, state_root)
    # A fresh streak (no marker, or the TTL window since the last attempt already
    # expired) starts back at 1; otherwise this attempt extends the current streak.
    still_within_ttl = age is not None and age < _START_BACKOFF_TTL_SECONDS
    next_count = count + 1 if (count and still_within_ttl) else 1
    _record_start_attempt(state_root, next_count)


def _cold_start_fallback(module_root, target: str, payload_text: str):
    """Exactly today's path - a fresh subprocess against the real target script.
    Fails open on any launch problem, same posture as run-guard.sh's own
    no-interpreter-found case: a broken fallback must not brick the tool call."""
    import subprocess  # nosec B404 - deferred; see the note above

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
    # realpath, not abspath: Path.resolve() follows symlinks and this must keep doing so.
    module_root = os.path.realpath(sys.argv[1]) if len(sys.argv) > 1 else os.getcwd()
    state_root = os.path.realpath(sys.argv[2]) if len(sys.argv) > 2 else module_root
    # Backward-compat default: a caller that predates the multi-target extension
    # never passes a third argument - it only ever meant bash_hook_dispatcher.
    target = sys.argv[3] if len(sys.argv) > 3 else "bash_hook_dispatcher"
    payload_text = sys.stdin.read()

    result = _try_daemon(state_root, target, payload_text)
    if result is None:
        _maybe_start_daemon(module_root, state_root)
        result = _cold_start_fallback(module_root, target, payload_text)
    else:
        _clear_start_backoff(state_root)

    exit_code, stderr_text, stdout_text = result
    if stdout_text:
        sys.stdout.write(stdout_text)
    if stderr_text:
        sys.stderr.write(stderr_text)
    return exit_code


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except BaseException:
        # FAIL OPEN (2026-08-27, live report: "sometimes get a UserPromptSubmit hook error
        # failed with non-blocking status code", at a new engagement open). This was the
        # one entry point in the chain without a fail-open wrapper: every hook it carries
        # has `except Exception: sys.exit(0)` in its own __main__, but an uncaught raise in
        # the CLIENT exited 1, and Claude Code reports a non-zero hook exit as an error the
        # user sees. The client is transport - it decides nothing - so a failure here must
        # cost the injected context and never surface as a failed hook.
        #
        # BaseException deliberately: a KeyboardInterrupt or a socket-driven exception that
        # is not an Exception subclass would otherwise escape and produce the same message.
        # SystemExit is re-raised first so a real exit code still propagates.
        sys.exit(0)
