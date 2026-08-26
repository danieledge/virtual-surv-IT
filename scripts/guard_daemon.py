#!/usr/bin/env python3
"""Persistent guard daemon - eliminates per-call interpreter cold start.

ADR-014 (docs/adr/ADR-014-persistent-guard-daemon.md). Preference-gated
(.claude/team-preferences.json `guard_daemon`, no machine-wide tier - same pattern
as `standards_critique`; on by default for any project set up via `/preferences`
or the installer's configure flow - see that skill's own docstring for the exact
"off if the key is genuinely absent" mechanics). run-guard.sh only ever talks to
this when the preference resolves true AND the target script is one of the
daemon-servable set (_TARGET_MODULE_NAMES below - originally bash_hook_
dispatcher.py alone, extended 2026-08-14 to the four other hook scripts this
daemon was audited safe to serve) - every other case (preference off, or any
target NOT in that set, e.g. persona_anchor.py, deliberately excluded pending
its own fixes) is completely unaffected; run-guard.sh's own cold-start path is
byte-for-byte what it was before this file existed.

Promoted from the design spike (docs/internal/adr-014-spike/) after live
validation on the actual reporting Windows box, 2026-08-12: 8/8 smoke-test
checks passed, including genuinely concurrent request safety and staleness
detection. This file adds the one thing the spike deliberately left open
(ADR-014 question 3, attack surface) - see "Attack surface" below - everything
else is the validated spike design, not a rewrite.

Mechanism: a per-project daemon, started lazily by run-guard.sh's client-mode
branch, holding every daemon-servable target's real, UNMODIFIED main() imported
ONCE each (_TARGET_MODULE_NAMES), serving requests over a TCP socket bound to
127.0.0.1 on an OS-assigned ephemeral port - the request names which target it
wants (see _Handler.handle()). The bound port (and an auth token, see below) are
written to .claude/.guard-daemon-port (project-scoped, same file-based-
coordination pattern .guard-interpreter/.guard-lock already use).

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
{"token": "<from the port file>", "target": "<name from _TARGET_MODULE_NAMES,
defaults to bash_hook_dispatcher if omitted - a pre-2026-08-14 client never sends
this field>", "payload": "<the hook's own stdin JSON as text>"} - and one
newline-delimited JSON response - {"exit_code": int, "stderr": str, "stdout": str,
"daemon_stale": bool (only if true)}. A missing/wrong token gets {"exit_code": 0,
"stderr": "unauthorized"} - fails open at the PROTOCOL level (never blocks a tool
call over an auth mismatch), relying on the client falling back to cold-start, not
on the daemon itself enforcing a block. An unrecognised target reuses the same
daemon_stale signal for the identical reason. stdout is almost always empty -
only stop_hook_dispatcher.py and persona_anchor.py among the current targets
write real stdout (verified by reading their actual source, not assumed; this
line went stale once before, when persona_anchor.py was added without updating
it - checked again now); every other target's capture is empty every time, same
as bash_hook_dispatcher.main() always was.
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

# 2026-08-14 (multi-target extension): originally hosted exactly ONE script
# (bash_hook_dispatcher.py). Four more hook scripts fire on their own PreToolUse/
# PostToolUse/Stop matchers via the SAME run-guard.sh launcher and pay the identical
# cold-start cost with zero daemon benefit - audited first (a general-purpose agent read
# all five in full against this file's own dispatch() mechanism) to confirm each is safe
# to serve from one long-lived process: locked_menu_guard.py, post_edit_lint.py and
# subagent_return_budget.py all read sys.stdin and write sys.stderr directly, the exact
# same shape bash_hook_dispatcher.py already has, and carry no module-level mutable
# state - safe with ONLY the existing dispatch lock, no changes to the scripts
# themselves. stop_hook_dispatcher.py writes its real answer to stdout, not stderr (Stop
# hooks signal via stdout JSON) - dispatch() now captures stdout too, a strict superset
# of before (bash_hook_dispatcher.py never writes stdout, so its capture is always empty
# and nothing downstream changes for it). persona_anchor.py was audited too and INITIALLY
# left out (two genuine bugs that only mattered once daemonized: unbounded sys.path
# growth per call, and a module-level check_artifacts cache with no staleness watch) -
# both fixed (the sys.path insert is deduped now; check_artifacts.py is in the watch
# list below) and it's included as of the same day. Fires on every user message, the
# highest-frequency point in this set besides Bash calls.
#
# engage_probe_prefetch.py joined on 2026-08-25 after the same audit, and it is the OTHER
# hook on every user message - so until now every prompt on a corporate box paid two hook
# spawns, only one of them daemon-served. It passes the checks that kept persona_anchor out
# initially: both sys.path inserts are already guarded by an `in sys.path` test (no unbounded
# growth), it holds no module-level mutable state, and it caches no other module itself. What
# it DOES do is import engage_probe, engagement_state and find_plugin_root in-function, which
# sys.modules then caches for the daemon's lifetime - so all three are in the watch list
# below, exactly as check_artifacts.py is for persona_anchor.
# prompt_hook_dispatcher joined 2026-08-26 (F4 perf audit). It supersedes persona_anchor
# and engage_probe_prefetch as the single UserPromptSubmit entry - the two of them were
# registered separately, so every user message paid two complete launcher chains for
# ~1.5ms of combined work. Both are KEPT in this list rather than removed: they remain
# individually daemon-servable for any caller still wired the old way (a project whose
# settings the human has not re-applied yet), and they are still the files whose staleness
# matters, since the dispatcher imports them.
_TARGET_MODULE_NAMES = (
    "bash_hook_dispatcher",
    "locked_menu_guard",
    "post_edit_lint",
    "subagent_return_budget",
    "stop_hook_dispatcher",
    "prompt_hook_dispatcher",
    "persona_anchor",
    "engage_probe_prefetch",
)


def _guard_module_paths(repo_root: Path) -> list:
    """Files whose mtime, if changed since load, mean this daemon's in-memory guard
    logic is stale. The set bash_hook_dispatcher.py itself dispatches to, every
    daemon-servable target script (an edit to any of them must restart the daemon -
    they're each imported ONCE at startup, same reasoning as bash_hook_dispatcher.py
    itself), check_artifacts.py (persona_anchor.py's own _load_checker caches it at
    module level in its fallback path - restarting the whole daemon on a live edit is
    simpler and more robust than bespoke per-hook cache invalidation, and correctly
    resets that cache to None too since a restart is a fresh process), and this
    daemon's own file (a daemon-code change should also trigger a restart, not just a
    guard change). Deliberately excludes dod_stop_gate.py and todo_panel_nudge.py -
    stop_hook_dispatcher.py loads those two fresh via importlib on every call rather
    than caching them at daemon-startup time (confirmed by the same audit that scoped
    this registry), so a live edit to either is already picked up on the very next
    call with no staleness risk at all - watching them here would only cause
    unnecessary restarts."""
    hooks = repo_root / ".claude" / "hooks"
    return [
        *(repo_root / "scripts" / f"{name}.py" for name in _TARGET_MODULE_NAMES),
        repo_root / "scripts" / "check_artifacts.py",
        # engage_probe_prefetch.py imports these three in-function, so a long-lived daemon
        # would serve a stale copy after a live edit - the same trap persona_anchor.py set
        # with check_artifacts.py (2026-08-25 audit).
        repo_root / "scripts" / "engage_probe.py",
        repo_root / "scripts" / "engagement_state.py",
        repo_root / "scripts" / "find_plugin_root.py",
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


def _load_targets(repo_root: Path) -> dict:
    """Imports every daemon-servable target module ONCE, by name, never a
    reimplementation - same "real, unmodified" posture the single-target version
    already had. If ANY import fails, the daemon must not start at all (fail closed:
    no daemon serving some targets but silently missing others is worse than no
    daemon - a caller for the missing target would get a KeyError deep in dispatch()
    instead of a clean cold-start fallback)."""
    import sys as _sys

    if str(repo_root) not in _sys.path:
        _sys.path.insert(0, str(repo_root))
    import importlib

    return {name: importlib.import_module(f"scripts.{name}") for name in _TARGET_MODULE_NAMES}


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
            # Backward-compat default: an older client that predates the multi-target
            # extension never sends "target" at all - it only ever meant
            # bash_hook_dispatcher, so that stays the default rather than a hard error.
            target = request.get("target", "bash_hook_dispatcher")
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

        if target not in server.dispatcher_modules:
            # A genuinely unknown target (protocol mismatch, or a typo somewhere
            # upstream) - reuse the existing daemon_stale signal rather than invent a
            # new one: the client already treats it as "cold-start THIS call, start a
            # fresh daemon for next time", which is exactly the safe degraded
            # behaviour here too (fails open, never silently drops the request).
            self._respond(
                {"exit_code": 0, "stderr": f"unknown daemon target: {target}", "daemon_stale": True}
            )
            return

        current = _mtimes(server.guard_paths)
        if current != server.loaded_mtimes:
            server.stale = True
            self._respond(
                {"exit_code": 0, "stderr": "daemon stale, restart and retry", "daemon_stale": True}
            )
            return

        exit_code, stderr_text, stdout_text = server.dispatch(target, payload_text)
        self._respond({"exit_code": exit_code, "stderr": stderr_text, "stdout": stdout_text})

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
        self.dispatcher_modules = _load_targets(repo_root)
        self.last_activity = time.monotonic()
        self.stale = False
        self._dispatch_lock = threading.Lock()

    def dispatch(self, target: str, payload_text: str):
        """Runs <target>.main() in-process - no subprocess, no cold start. Serialized
        (see module docstring: sys.stdin/sys.stdout/sys.stderr are process-global,
        unsafe to swap concurrently across threads) across ALL targets, not just
        per-target - two different targets dispatched at once would race on the same
        process-global streams exactly like two of the same target would. Captures
        stdout as well as stderr (2026-08-14 multi-target extension - stop_hook_
        dispatcher.py answers via stdout, not stderr; bash_hook_dispatcher.py and the
        other original targets never write stdout at all, so their capture is always
        empty and nothing changes for them), so a client sees identical behaviour to
        today's cold-start path either way."""
        module = self.dispatcher_modules[target]
        with self._dispatch_lock:
            old_stdin, old_stdout, old_stderr = sys.stdin, sys.stdout, sys.stderr
            stdout_capture = io.StringIO()
            stderr_capture = io.StringIO()
            try:
                sys.stdin = io.StringIO(payload_text)
                sys.stdout = stdout_capture
                sys.stderr = stderr_capture
                exit_code = module.main()
            finally:
                sys.stdin = old_stdin
                sys.stdout = old_stdout
                sys.stderr = old_stderr
            return exit_code, stderr_capture.getvalue(), stdout_capture.getvalue()

    def idle_watchdog(self) -> None:
        while True:
            # Sleep no longer than the timeout it is policing (2026-08-25 performance
            # review). A fixed 5s meant an idle_timeout below that could never fire on the
            # first pass - harmless in production, where the timeout is 30 minutes, but two
            # tests using a 1s timeout each paid the full 5s waiting for a watchdog that had
            # already decided. Measured: 10s off the suite, production behaviour unchanged.
            time.sleep(min(5, max(0.1, self.idle_timeout)))
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
