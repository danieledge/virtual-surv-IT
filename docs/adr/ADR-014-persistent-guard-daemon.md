# ADR-014: A persistent guard daemon - eliminating per-call interpreter cold start

> Architecture Decision Record (Nygard format). One file per significant decision, so the
> *why* is auditable later. Authored in `.md`, rendered to `.html`.

> **Document control** · ID `ADR-014` · Version `0.3` · Status `Proposed` · Classification
> `Internal` · Owner 🤖 Morgan (PM), Virtual Surveillance IT · As-of `2026-08-12`
>
> | Version | Date | Author | Change |
> |---|---|---|---|
> | 0.1 | 2026-08-11 | live corp bug report (Windows debug-log monitoring) + same-session remediation | Initial proposal - design space and recommendation, no code |
> | 0.2 | 2026-08-12 | build-plan step 1 measured live on the reporting box; build-plan step 2 (design spike) built | Step 1 done with real numbers (below). Step 2: a working prototype at `docs/internal/adr-014-spike/` - `guard_daemon.py` + `guard_daemon_client.py` + a live smoke test + pytest coverage for the pure-logic pieces. One real, previously-unanticipated finding from actually building it: `bash_hook_dispatcher.main()` reads `sys.stdin`/writes `sys.stderr` directly (process-global), so a naive threaded daemon risked one request's payload leaking into another's guard evaluation - dispatch is now serialized behind a lock. Not yet validated on the actual Windows/Git-Bash box - see the spike README's "still genuinely open" section. |
> | 0.3 | 2026-08-12 | spike smoke-tested live on the actual reporting Windows box (via the new Diagnostics-menu entry, 0.33.58) | **8/8 checks passed.** Concurrency safety, staleness detection and IPC all confirmed working on the real box, not just Linux - open questions 1 and 2 move from "prototyped" to "confirmed." Measured daemon-backed latency: **12.6ms median vs. 307ms cold-start median** (dispatcher invoked directly, not through the full `run-guard.sh` launcher - a cleaner isolation of dispatch-import cost specifically than the ~15x figure in v0.2). Idle-timeout still unconfirmed (needs a manual 60s+ run, out of scope for the automated smoke test by design). |

| | |
|---|---|
| **Status** | **Proposed - spike validated on Windows (8/8 smoke-test checks), not yet wired into any live hook path.** Items 1-4 of the same bug report (trailing-slash path bug, silent stamp-write failure, undersized wait budget, active-engagement scoping on the DoD Stop hook) are fixed separately, staged, and out of scope here - see `scripts/staged_hooks/run-guard.sh` and `scripts/staged_hooks/dod_stop_gate.py`. This ADR is about the one item from that report those fixes cannot reach: the cold-start cost itself. |
| **Date** | 2026-08-11, updated 2026-08-12 |
| **Deciders** | Human approver (not yet decided) |
| **Traceability** | ADR-002 (safety-hook threat model - this proposal changes the enforcement boundary's own architecture); `.claude/hooks/run-guard.sh`; `scripts/bash_hook_dispatcher.py`; `docs/internal/adr-014-spike/` (the prototype) |

## Context

A live corp report (Windows, debug-log monitoring, 2026-08-11) measured 87 slow PreToolUse
hook events, 2-9s per call in normal use, escalating to 25-90s under Workflow-tool fan-out.
Four causes were identified; three have surgical, staged fixes (a trailing-slash path bug that
silently disabled stale-lock reclaim, a stamp-write failure with no fail-open backstop, and a
lock wait-budget that didn't scale with real interpreter start-up time). The fourth does not:

**Every hook invocation is a fresh OS process.** `run-guard.sh` is invoked once per
PreToolUse event; there is no long-lived process. `bash_hook_dispatcher.py` (2026-07-31)
already consolidated five separate hook processes into one *per call* - a real, measured
fix (51s → single-digit seconds for the step-0 probe) - but it did nothing to the *per-call*
cost, because each call still starts a brand-new Python interpreter from cold. On a
corporate, AV-scanned Windows box, that cold start is the dominant cost, and it is paid
again, in full, on every single tool call, all session long. The 2026-08-10 mkdir-lock
(serializing concurrent launches under fan-out) and the wait-budget fix above manage the
*consequences* of N simultaneous cold starts; neither removes a single cold start from the
total bill. Only not paying it repeatedly does that.

**Measured live, 2026-08-12, on the actual reporting box** (`run_hook_latency_diagnostic`,
0.33.56, after the fallback-path fix that let it actually reach the real guard path):

| Measurement | Result |
|---|---|
| Bare interpreter cold start | 82-106ms, median 86ms |
| Repetition trend | flat (106ms → ~86ms) - no meaningful drop-off, consistent with per-*something* scanning regardless of repetition, not a one-time trust cache |
| **Real guard-launcher cost** (`run-guard.sh` → `bash_hook_dispatcher.py`, actual dispatch) | **1372-3808ms, median 1404ms** |
| Guard overhead beyond bare interpreter | **~1319ms** |
| Concurrent fan-out (8 genuinely concurrent calls) | worst single call **21017ms**, total wall-clock 21021ms |

The gap between bare interpreter (86ms) and the real guard-launcher path (1404ms median) is
the actual finding: the dominant cost is not raw interpreter start-up, it's something in the
guard-dispatch path itself - importing five separate `.py` files from disk plus their own
imports, versus a bare `python -c 'pass'` which touches no files beyond the interpreter. If
the endpoint-security product scans file *reads* rather than (or in addition to) process
*launches*, that asymmetry is exactly what you'd expect - stated here as the better-fitting
inference from this data, not as something independently confirmed against Defender's own
logs. The 8-way concurrent fan-out's worst case (21s) lands in the same order of magnitude as
the originally reported 25-90s, reproducing the reported symptom on demand rather than
waiting for it to happen organically - the diagnostic doing the job it was built for.

## Decision (proposed)

**Not yet decided.** This section lays out the design space and a recommendation; it is not
an implemented architecture. Recommendation: **build it**, but behind an opt-in preference
(same pattern as `map_skeleton`, `standards_critique`), and only after the design questions
below have real answers, not assumed ones - this is the enforcement boundary itself, and a
plausible-sounding design that fails live here is a materially worse outcome than the
mechanical fixes it would replace.

### The mechanism

A long-lived process (started on first use, one per project/session) holds a warm Python
interpreter and the guard modules already imported. `run-guard.sh` becomes a thin client:
detect whether the daemon is running and healthy; if not, start it (detached) and fall back
to the current cold-start path for *this* call only; if so, send the tool-call payload over
IPC and relay the response (exit code + stdout) unchanged. The guard's documented contract
(stdin in, exit code 2 = block out) does not change - only what's on the other end of it.

### Open questions - answers needed before this is buildable, not just conceivable

1. **IPC that is genuinely portable, not "portable in the common case."** ✅ **Confirmed on
   Windows, 2026-08-12.** The spike uses TCP on `127.0.0.1` with an OS-assigned ephemeral
   port written to a port file (`.claude/.guard-daemon-port`) - same file-based-coordination
   pattern `.guard-interpreter`/`.guard-lock` already use, sidestepping port-collision logic
   entirely rather than picking a fixed port. Live-run on the actual reporting box: daemon
   started, wrote its port file, served a harmless payload (allowed) and a raw-data payload
   (blocked, with the real `guard-raw-data.py` message verbatim - proof it's running actual
   current guard logic in-process, not a stand-in) correctly.
   **A second, previously unanticipated finding from actually building it, also now
   confirmed fixed**: `bash_hook_dispatcher.main()` reads `sys.stdin` and writes `sys.stderr`
   directly - process-global state, not a function parameter (found by reading its actual
   source before assuming an interface, not by guessing). A naive threaded daemon serving
   concurrent connections would risk one request's payload leaking into another's guard
   evaluation mid-dispatch - genuinely dangerous for a security boundary, not a theoretical
   concern. Dispatch is serialized behind a lock even though the TCP server itself accepts
   concurrent connections. **Live-tested, 10 genuinely concurrent mixed requests (thread
   pool, not a loop): expected exit codes `[0,2,0,2,0,2,0,2,0,2]`, got exactly that - zero
   cross-talk.** This is exactly the class of thing a working prototype surfaces, and the
   live concurrency test is exactly what makes "we fixed it" a checked claim, not an assumed
   one.
   **Measured speedup**: daemon-backed median **12.6ms** vs. cold-start median **307ms**
   (dispatcher invoked directly for this specific comparison, not through the full
   `run-guard.sh` launcher) - real, on the actual box, not projected.
2. **Staleness of a long-lived process is a safety question here, not a performance one.**
   ✅ **Confirmed on Windows, 2026-08-12.** Everywhere else in this codebase, "the guard
   logic changed but the running thing hasn't picked it up yet" is caught by the staged/live
   sync test (`test_hooks_in_sync.py`, hard-failure by design, born from the exact 2026-08-01
   audit where a guard drifted from its staged copy while the suite stayed green). A daemon
   that imports the guard modules once and keeps running introduces a NEW staleness window
   that mechanism doesn't cover: a guard fix gets applied to disk, but a daemon already
   running keeps serving decisions from the old, in-memory version until it restarts. The
   spike implements the mtime-per-request option (cheap, no watcher dependency, per this
   question's own original recommendation): on detected staleness the daemon answers the
   in-flight request with a "stale, retry" signal and self-terminates rather than attempting
   in-process module reload (failure-prone for interdependent modules) - the next client
   request that finds no daemon just starts a fresh one, which re-imports current code.
   **Live-tested on the real box**: touching `guard_daemon.py`'s own mtime correctly
   produced `daemon_stale: True` on the next request, and the daemon process actually exited
   afterward - both confirmed, not just designed. **Still open**: idle-timeout actually
   firing was deliberately out of scope for the automated smoke test (needs a 60s+ wait with
   no requests) and has not been run manually either.
3. **Attack surface.** A short-lived CLI process that runs, decides, and exits has no
   window where another local process can interact with it. A long-lived localhost listener
   does. Binding strictly to `127.0.0.1` is necessary but likely not sufficient on a
   shared/multi-user box - whether a per-session token or OS-level socket permissions are
   needed is a real question, not a formality, given what this daemon would be trusted to
   decide (raw-data access, code execution, config writes).
4. **Lifecycle and cleanup.** Who starts it (first hook call, lazily) is the easy part.
   Detecting "running but wedged" vs. "running and healthy" needs the same kind of explicit,
   bounded-wait-then-fail-open posture `run-guard.sh` already uses for its lock - a daemon
   health check must never itself become a new way to hang every tool call. Equally
   important: it must never outlive the session it belongs to. An orphaned daemon left
   running after Claude Code exits is a resource leak at best and, combined with (2) above,
   a genuine staleness risk at worst - it would keep serving guard decisions for a project
   nobody is actively working in, based on whatever guard code was live when it started.
5. **Testing strategy changes materially.** Every existing hook test
   (`test_run_guard_lock.py`, `test_run_guard_interpreter_cache.py`, `test_guards.py`, etc.)
   spawns the actual launcher per test via `subprocess.run`, which cleanly isolates each
   test's state. A daemon-backed launcher needs either a per-test daemon spin-up/teardown
   (slower, and now the daemon's OWN lifecycle bugs are on the critical path of every guard
   test) or a documented, deliberate split between "test the client/IPC contract" and "test
   the daemon's own logic" - undecided which, and the wrong choice risks exactly the kind
   of theoretically-sound-but-untested-in-practice fix this codebase has been burned by
   before (three failed prompt-only concurrency fixes, `.claude/skills/.shared/workflow-dispatch.md`).

### What this does NOT change

The guard *decision* logic (`guard-raw-data.py`, `guard-code-execution.py`,
`guard-consent-writes.py`, `guard-findings-pack-write.py`) is untouched by this proposal -
this is purely about what runs them and how often a fresh interpreter is paid for, not what
they decide or how. The staged/human-apply discipline (ADR-002 rec 5) applies to the daemon
code exactly as it does to every other file in `.claude/hooks/`.

## Consequences (if built)

- Eliminates the per-call cold-start cost entirely for warm calls - the actual root cause
  of the 2-9s-normal/25-90s-fan-out latency the corp report measured, which the staged
  fixes in `run-guard.sh` manage the symptoms of but cannot remove.
- Adds a genuinely new class of failure mode to a safety-critical enforcement boundary
  (daemon health, staleness, IPC availability) that does not exist today. Every fix so far
  in this file's history has been "harden the thing that already exists," not "add a new
  long-lived component" - this is a different risk category, not a bigger version of the
  same one.
- The opt-in preference pattern (`map_skeleton`, `standards_critique`) means a project that
  hasn't opted in sees zero behaviour change - this should ship the same way, off by
  default, so the blast radius of getting it wrong is scoped to projects that deliberately
  chose it.

## Alternatives considered

- **Do nothing further** (ship only the trailing-slash/stamp-write/wait-budget fixes) -
  genuinely reduces the WORST-case symptoms (a stuck, unreclaimable lock; a caller that
  gives up too early) but leaves the root cause - N cold starts under fan-out - fully in
  place. Rejected as the final word, but not rejected as a real, already-shipped interim
  improvement; this ADR does not block on it.
- **Reduce fan-out width instead of eliminating cold-start cost** (cap Workflow concurrency
  lower on corp-detected-slow hosts) - cheaper to build, but treats a host-speed problem by
  making the team slower everywhere that host is used, rather than fixing the actual
  bottleneck. Worth a one-line mention, not a real contender.
- **A smaller step short of a full daemon**: keep the interpreter cache but pre-warm the
  Python import of the guard modules into a `.pyc`/frozen state, or investigate whether a
  lighter interpreter (e.g. a stripped `-S` startup) closes most of the gap without a
  long-lived process at all. Not evaluated in this pass - worth measuring before committing
  to the daemon's added complexity, since the actual coldstart numbers this project has
  measured elsewhere (aider-style tooling, etc.) suggest interpreter startup itself, not
  import cost, may dominate - if so, a daemon is the only real lever; if not, a cheaper fix
  exists and should be tried first.

## Build plan

1. ✅ **Done, 2026-08-12.** Measured live on the reporting corp box (table above): real
   guard-launcher cost is ~15x bare interpreter cost, pointing at import/dispatch-path cost
   (or file-read-triggered scanning of it) rather than raw interpreter start-up alone - the
   "smaller step" alternative (`-S`/pyc pre-warming) would not address this, since it only
   reduces in-process work, not file-read count. Concurrent fan-out reproduced the originally
   reported symptom's order of magnitude on demand.
2. ✅ **Done, 2026-08-12 - validated live on the reporting Windows box, 8/8 smoke-test
   checks passed.** A working prototype at `docs/internal/adr-014-spike/` (`guard_daemon.py`,
   `guard_daemon_client.py`, a live smoke test, pytest coverage for the pure-logic pieces),
   exposed via the Diagnostics menu (0.33.58) for easy remote access. Open questions 1
   (IPC/concurrency) and 2 (staleness) are now confirmed with live evidence, not just design
   - see above. **Still open within step 2's own scope**: idle-timeout actually firing
   (deliberately out of the automated smoke test, never run manually either), and whether the
   `DETACHED_PROCESS`/`CREATE_NO_WINDOW` detached-spawn stays genuinely invisible (the smoke
   test starts the daemon itself and watches for the port file, not for a visible window - a
   visual check during a live run would close this). Open questions 3 (attack surface) and 5
   (testing strategy) remain genuinely open regardless - not addressed by this prototype at
   all, design questions still to answer before step 3.
3. **Not started.** Real implementation, staged the same way every other hook change is.
   Step 2's core execution risk (does this actually work, safely, on the real box) is now
   retired with evidence; open questions 3 and 5 should still be answered explicitly before
   this step begins, not discovered mid-implementation.
