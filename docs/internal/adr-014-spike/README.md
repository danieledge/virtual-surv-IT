# ADR-014 design spike - persistent guard daemon prototype

**Not production. Not wired into any live hook path.** `.claude/hooks/run-guard.sh` is
completely unchanged by anything in this directory. This exists to answer
[ADR-014](../../adr/ADR-014-persistent-guard-daemon.md)'s open questions with a working
prototype and real measurements, per its own build plan step 2, before any decision to
build the real thing (step 3).

## What's here

- `guard_daemon.py` - the daemon: imports the real, unmodified `scripts.bash_hook_dispatcher`
  once, serves requests over a TCP socket on `127.0.0.1` (OS-assigned port, written to
  `.claude/.guard-daemon-port`), self-terminates on detected staleness or idle timeout.
- `guard_daemon_client.py` - connects to a running daemon if one exists; falls back to
  today's cold-start subprocess path for that one call if not, and starts a detached daemon
  for next time. Standalone - not called by `run-guard.sh`.
- `smoke_test.py` - a live, end-to-end check (starts a real daemon, sends real requests over
  a real socket, checks concurrency safety, staleness detection, and measures the actual
  daemon-vs-cold-start latency difference). **Not pytest** - these are execution questions a
  mock can't answer honestly.
- `tests/test_adr014_guard_daemon_spike.py` (repo `tests/`, not here) - pytest coverage for
  the pure-logic pieces (mtime comparison, port-file read/write, client fallback decisions).

## Running it

**Neither this README's author nor the model that wrote this code has run any of it.**
CLAUDE.md's execution-consent gate applies here exactly as it does to anything else that
runs code - this needs a human (or an already-consented agent) to actually execute it before
its claims are more than syntax/lint-verified.

```
python3 -m pytest tests/test_adr014_guard_daemon_spike.py -q
python3 docs/internal/adr-014-spike/smoke_test.py
```

The smoke test prints a clear pass/fail per check and cleans up its own daemon process and
port file on exit either way.

**On Windows/Git-Bash specifically** - this has *only* been written against the same corp
box's earlier `run_hook_latency_diagnostic` findings, never actually run there. Two things
in the code are Windows-conditional and specifically need live confirmation on that box, not
just on whatever ran the smoke test above:
- `guard_daemon_client._start_daemon_detached`'s `DETACHED_PROCESS | CREATE_NO_WINDOW`
  branch - does the daemon actually detach cleanly with no visible console popup.
- The daemon actually surviving Git-Bash/PowerShell process-tree quirks documented earlier
  this investigation (Git Bash's own `exec` emulation spawns rather than replaces).

## What this spike has already answered, with evidence

- **The concurrency hazard is real, not theoretical.** `bash_hook_dispatcher.main()` reads
  `sys.stdin`/writes `sys.stderr` directly - process-global state. A naive threaded daemon
  would risk one request's payload leaking into another's guard evaluation. Found by reading
  the dispatcher's actual source before assuming an interface (it doesn't take a payload
  parameter at all) - dispatch is now serialized behind a lock, trading some theoretical
  concurrency for correctness on a security boundary. This is exactly the kind of thing a
  design spike is supposed to surface that reasoning about the ADR text alone would not.
- **Staleness**: mtime-per-request, self-terminate-and-let-the-client-restart, per ADR-014's
  own recommendation - implemented, smoke-tested for the "does it actually detect a touched
  file and exit" question, not just designed.
- **IPC**: TCP on `127.0.0.1`, OS-assigned port via a port file (same file-based-coordination
  pattern `.guard-interpreter`/`.guard-lock` already use) - avoids port-collision logic
  entirely rather than picking a fixed port.

## What's still genuinely open

- **Lifecycle**: idle-timeout is a bounded approximation, not a real answer to "does this
  daemon ever outlive the session it belongs to" - it cannot know that with certainty.
- **Attack surface**: the port file IS the access control here. No per-session token. Flagged
  as an explicit gap, not solved.
- **Windows validation**: everything above is unverified on the actual reporting box.
- **Whether the measured latency win survives real guard content on Windows specifically** -
  the smoke test's latency comparison only means something once it's actually been run there.
