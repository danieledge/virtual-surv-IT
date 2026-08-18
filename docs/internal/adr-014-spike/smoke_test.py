#!/usr/bin/env python3
"""ADR-014 spike smoke test - live, end-to-end, actually starts a real daemon
process and talks to it over a real socket. Not pytest: the questions this
answers (does concurrency actually stay safe under real threads, does staleness
detection actually fire, does idle-timeout actually terminate the process, is
this actually faster than cold-start in practice) are execution questions, not
things a mock can answer honestly.

NEVER RUN BY THE MODEL THAT WROTE THIS - CLAUDE.md's execution-consent gate
applies to this exactly as it does to anything else that runs code. This exists
to be run BY A HUMAN (or an already-authorised agent) who has granted that
consent, same as every other verification script in this project.

Usage: python3 smoke_test.py   (from anywhere - resolves the repo root itself)
Exit code: 0 if every check passed, 1 otherwise. Cleans up its own daemon
process and port file on exit, pass or fail.
"""

from __future__ import annotations

import json
import socket
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

SPIKE_DIR = Path(__file__).resolve().parent
REPO_ROOT = SPIKE_DIR.parents[2]
DAEMON = SPIKE_DIR / "guard_daemon.py"
CLIENT = SPIKE_DIR / "guard_daemon_client.py"
PORT_FILE = REPO_ROOT / ".claude" / ".guard-daemon-port"

HARMLESS = json.dumps({"tool_name": "Read", "tool_input": {"file_path": "/tmp/adr014-smoke-harmless"}})


def _blocking_payload() -> str:
    # data/raw/ is hard-blocked regardless of what's actually there - this is
    # the same real payload shape test_run_guard_lock.py's own tests use.
    return json.dumps({"tool_name": "Grep", "tool_input": {"pattern": "x", "path": "data/raw"}})


_ok_count = 0
_fail_count = 0


def check(label: str, condition: bool, detail: str = "") -> None:
    global _ok_count, _fail_count
    if condition:
        _ok_count += 1
        print(f"  OK   {label}" + (f" - {detail}" if detail else ""))
    else:
        _fail_count += 1
        print(f"  FAIL {label}" + (f" - {detail}" if detail else ""))


def send(payload: str, timeout: float = 20.0):
    """Direct socket call to whatever daemon is currently at the recorded
    port - bypasses the client's fallback so a daemon-specific failure is
    visible as a failure here, not silently absorbed by cold-start."""
    port = int(PORT_FILE.read_text(encoding="utf-8").strip())
    with socket.create_connection(("127.0.0.1", port), timeout=timeout) as sock:
        sock.sendall((json.dumps({"payload": payload}) + "\n").encode("utf-8"))
        sock.shutdown(socket.SHUT_WR)
        chunks = []
        while True:
            chunk = sock.recv(65536)
            if not chunk:
                break
            chunks.append(chunk)
    return json.loads(b"".join(chunks).decode("utf-8"))


def main() -> int:
    print(f"ADR-014 guard-daemon spike - smoke test\nRepo root: {REPO_ROOT}\n")

    daemon_proc = None
    try:
        print("Starting daemon (60s idle-timeout for this test run)...")
        daemon_proc = subprocess.Popen(
            [sys.executable, str(DAEMON), str(REPO_ROOT), "--idle-timeout", "60"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and not PORT_FILE.is_file():
            time.sleep(0.1)
        check("daemon wrote its port file within 10s", PORT_FILE.is_file())
        if not PORT_FILE.is_file():
            print("  Cannot continue without a port file - daemon stderr:")
            print("  " + (daemon_proc.stderr.read() if daemon_proc.stderr else "(none)"))
            return 1

        print("\nHarmless payload:")
        resp = send(HARMLESS)
        check("harmless payload allowed (exit 0)", resp.get("exit_code") == 0, str(resp))

        print("\nBlocking payload (data/raw/):")
        resp = send(_blocking_payload())
        check("raw-data payload blocked (exit 2)", resp.get("exit_code") == 2, str(resp))
        check("block reason present in stderr", bool(resp.get("stderr")), resp.get("stderr", "")[:150])

        print("\nConcurrency (10 mixed requests, genuinely concurrent - the real")
        print("safety question: does each request get ITS OWN correct answer back,")
        print("never another request's):")
        requests = [(HARMLESS if i % 2 == 0 else _blocking_payload()) for i in range(10)]
        expected = [0 if i % 2 == 0 else 2 for i in range(10)]
        with ThreadPoolExecutor(max_workers=10) as pool:
            results = list(pool.map(send, requests))
        actual = [r.get("exit_code") for r in results]
        check(
            "every concurrent request got its own correct exit code",
            actual == expected,
            f"expected {expected}, got {actual}",
        )

        print("\nLatency comparison (daemon-backed vs cold-start, 5 calls each):")
        daemon_times = []
        for _ in range(5):
            t0 = time.monotonic()
            send(HARMLESS)
            daemon_times.append(time.monotonic() - t0)
        cold_times = []
        dispatcher = REPO_ROOT / "scripts" / "bash_hook_dispatcher.py"
        for _ in range(5):
            t0 = time.monotonic()
            subprocess.run(
                [sys.executable, str(dispatcher)], input=HARMLESS, capture_output=True, text=True, timeout=20
            )
            cold_times.append(time.monotonic() - t0)
        daemon_median = sorted(daemon_times)[2] * 1000
        cold_median = sorted(cold_times)[2] * 1000
        print(f"  daemon-backed median: {daemon_median:.1f}ms")
        print(f"  cold-start median:    {cold_median:.1f}ms")
        check(
            "daemon-backed calls are meaningfully faster than cold-start",
            daemon_median < cold_median * 0.5,
            f"{daemon_median:.1f}ms vs {cold_median:.1f}ms",
        )

        print("\nStaleness detection (touching guard_daemon.py's own mtime):")
        real_stat = DAEMON.stat()
        import os

        os.utime(DAEMON, (real_stat.st_atime, real_stat.st_mtime + 5))
        try:
            resp = send(HARMLESS, timeout=5)
            check("stale daemon flags itself rather than answering normally", resp.get("daemon_stale") is True, str(resp))
        finally:
            os.utime(DAEMON, (real_stat.st_atime, real_stat.st_mtime))  # restore - don't leave this file touched

        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and daemon_proc.poll() is None:
            time.sleep(0.2)
        check("daemon process actually exited after flagging stale", daemon_proc.poll() is not None)
        daemon_proc = None  # already exited, nothing to clean up below

    finally:
        if daemon_proc is not None and daemon_proc.poll() is None:
            daemon_proc.terminate()
            try:
                daemon_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                daemon_proc.kill()
        PORT_FILE.unlink(missing_ok=True)

    print(f"\n{_ok_count} passed, {_fail_count} failed.")
    print(
        "\nNot covered by this run: idle-timeout actually firing (would need a "
        "60s+ wait with no requests - run manually if you want to confirm it: "
        "start the daemon with --idle-timeout 5, wait 10s with no requests, "
        "confirm the process exits on its own) and real behaviour on Windows/"
        "Git-Bash specifically (DETACHED_PROCESS/CREATE_NO_WINDOW, the "
        "client's start_new_session branch) - this test only ran on whatever "
        "platform executed it."
    )
    return 1 if _fail_count else 0


if __name__ == "__main__":
    sys.exit(main())
