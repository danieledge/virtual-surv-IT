# ADR-014: A persistent guard daemon - eliminating per-call interpreter cold start

> Architecture Decision Record (Nygard format). One file per significant decision, so the
> *why* is auditable later. Authored in `.md`, rendered to `.html`.

> **Document control** · ID `ADR-014` · Version `0.1` · Status `Proposed` · Classification
> `Internal` · Owner 🤖 Morgan (PM), Virtual Surveillance IT · As-of `2026-08-11`
>
> | Version | Date | Author | Change |
> |---|---|---|---|
> | 0.1 | 2026-08-11 | live corp bug report (Windows debug-log monitoring) + same-session remediation | Initial proposal - design space and recommendation, no code |

| | |
|---|---|
| **Status** | **Proposed - design only, not built.** Items 1-4 of the same bug report (trailing-slash path bug, silent stamp-write failure, undersized wait budget, active-engagement scoping on the DoD Stop hook) are fixed separately, staged, and out of scope here - see `scripts/staged_hooks/run-guard.sh` and `scripts/staged_hooks/dod_stop_gate.py`. This ADR is about the one item from that report those fixes cannot reach: the cold-start cost itself. |
| **Date** | 2026-08-11 |
| **Deciders** | Human approver (not yet decided) |
| **Traceability** | ADR-002 (safety-hook threat model - this proposal changes the enforcement boundary's own architecture); `.claude/hooks/run-guard.sh`; `scripts/bash_hook_dispatcher.py` |

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

1. **IPC that is genuinely portable, not "portable in the common case."** Unix domain
   sockets are the natural choice on Linux/macOS but are not a given on native Windows;
   named pipes exist on Windows but are not naturally reachable from `sh`/Git Bash without
   extra tooling. A TCP socket bound to `127.0.0.1` is the most likely candidate precisely
   because it is available identically everywhere `run-guard.sh` already needs to run - but
   "everywhere" needs to be verified against Git Bash specifically, the same way every other
   fix in this launcher has been (2026-07-30/31 corp reports, both bugs found live, not
   anticipated in the abstract).
2. **Staleness of a long-lived process is a safety question here, not a performance one.**
   Everywhere else in this codebase, "the guard logic changed but the running thing hasn't
   picked it up yet" is caught by the staged/live sync test (`test_hooks_in_sync.py`,
   hard-failure by design, born from the exact 2026-08-01 audit where a guard drifted from
   its staged copy while the suite stayed green). A daemon that imports the guard modules
   once and keeps running introduces a NEW staleness window that mechanism doesn't cover:
   a guard fix gets applied to disk, but a daemon already running keeps serving decisions
   from the old, in-memory version until it restarts. This needs either a file-watch +
   reload, a mtime check per request (cheap, no watcher dependency), or an explicit
   "restart the daemon" step folded into the SAME apply scripts that promote staged guards
   today - the third option is the safest but relies on the human remembering, which is
   exactly the class of failure this project's own hooks-over-prompts philosophy exists to
   avoid.
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
   before (three failed prompt-only concurrency fixes, `workflow-dispatch.md`).

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

## Build plan (not started)

1. Measure first: instrument `run-guard.sh`'s cold-start probe (already staged, item 3 of
   the 2026-08-11 fixes) across a real session on the reporting corp box, and separately
   measure how much of that is interpreter startup vs. module import - this tells us
   whether the "smaller step" alternative above is worth trying before the daemon.
2. If the daemon is still the answer after (1): a design spike answering open questions 1-4
   above with evidence (a working prototype on both a POSIX box and a real Windows/Git-Bash
   box), not assumptions - the exact discipline every other fix in this file's history has
   required (2026-07-30, 2026-07-31, 2026-08-01, 2026-08-10, 2026-08-11 were all live
   reproductions, not design-time reasoning alone).
3. Only then: implementation, staged the same way every other hook change is, with test
   coverage for the daemon's own lifecycle before it's trusted with the client/IPC contract.
