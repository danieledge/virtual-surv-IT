#!/bin/sh
# Portable launcher for the PreToolUse safety guards.
#
# Claude Code runs hook commands in a POSIX shell (sh/bash on Linux & macOS, Git Bash on
# Windows). The bare `python3` used previously is not present on Windows, where the interpreter
# is `python` or the `py` launcher - so the guard failed to start there ("python3: command not
# found") and, worse, did not run at all. This finds whichever interpreter exists and runs it
# (as a foreground child, not `exec` - see the locking comment below for why), so the guard's
# stdin (the tool payload) and exit code (2 = block) pass through unchanged either way.
#
# This wrapper is intentionally tiny and holds NO guard logic - the guards themselves
# (guard-raw-data.py, guard-code-execution.py) are unchanged. It selects an interpreter and
# (2026-08-10) serializes concurrent launches under subagent fan-out - see the lock section
# below for why and how.
#
# Interpreters are version-probed: the guards need Python >= 3.9 (pathlib.Path.is_relative_to);
# an older interpreter would crash at runtime, and we'd rather skip it and try the next one than
# exec into a known crash.
#
# If no suitable Python is found we exit 0 (allow). In repo-as-project mode the OS-level
# permissions.deny list in .claude/settings.json still backs Read/Grep/Glob for data/raw and
# secrets - but a plugin install ships no deny list (recreate it in the host project, see
# ADR-002 rec 10), and there are no Bash() deny entries either, so on a Python-less host the
# guards are inert (see ADR-002 §launcher trade-off). A hard block here would brick every tool
# call on a Python-less host, which is not the guard's job.
#
# Cache the resolved interpreter (2026-07-30 corporate report): FIVE hooks match Bash, so
# this loop runs 5x per Bash call, all session long. On a Windows box where `python3.exe`
# is the App Execution Alias stub (present via `command -v` but not a real interpreter),
# actually EXECUTING it to version-check triggers a multi-second Microsoft Store redirect
# check EVERY time - "several minutes" for a single /engage turned out to be that stub hang
# repeated dozens of times. `command -v` alone (existence, no execution) is cheap and safe
# to redo every call; only the EXECUTION probe needs to happen once and be trusted after.

# UTF-8 pin (2026-07-31 corporate report): the guards' stdin is the tool-call JSON payload,
# which can carry non-ASCII (the Fix-cycle arrow "→" in locked_menu_guard.py's canonical
# labels, curly quotes, section signs). Python 3 decodes stdin/stdout/stderr using the
# platform's default text encoding unless told otherwise - on native Windows Python that's
# the console codepage (e.g. cp1252), not UTF-8. Unlike a strict codec, cp1252 rarely raises
# on decode; it silently mis-decodes multi-byte UTF-8 sequences into different-but-valid
# characters, so a correctly-formed answer compares unequal to the guard's UTF-8 constant
# and trips a false "drift" block instead of erroring loudly. Pin both interpreter env vars
# before every exec path below (cache hit and full probe alike) so the guard always reads
# and writes UTF-8 regardless of OS locale/console codepage.
export PYTHONIOENCODING=utf-8
export PYTHONUTF8=1

# Serialize concurrent invocations (corp report, 2026-08-10): a Workflow-tool fan-out fires
# several subagents' tool calls within the same instant, each independently spawning this
# launcher - normally hidden (one spawn finishes before the next tool call starts), but under
# real concurrency N interpreter cold-starts hit CPU scheduling and endpoint-security scanning
# on a Windows box AT ONCE, measured live turning ~50-100ms hook latency into 2,000-8,000ms
# across the board. An mkdir-based lock (atomic and portable - no flock dependency, which Git
# Bash is not guaranteed to ship) queues concurrent launches instead of letting them all spawn
# simultaneously; total process-creation work is unchanged, but it stops happening in one
# contended burst. Two failure modes are handled explicitly rather than left implicit, because
# this gates every tool call in the session - a bug here is worse than the slowness it fixes:
#   - Bounded wait, not indefinite: give up and proceed WITHOUT the lock (fail open) after
#     LOCK_WAIT_BUDGET_MS rather than risk hanging every tool call on a stuck lock. Same
#     "launcher-level infrastructure problems fail open" posture as the no-interpreter-found
#     case below - a missing/broken serialization mechanism is not a reason to brick the
#     session, only a reason to lose the (purely perf) benefit of serializing.
#   - Stale-lock reclaim: a lock older than LOCK_MAX_AGE_SECONDS is treated as abandoned (its
#     holder crashed or was SIGKILLed - not catchable by the EXIT trap below) and is removed
#     immediately rather than waited out, so one dead holder can't starve every call behind it
#     for the rest of the session.
# Strip trailing slash(es) from the resolved root (2026-08-11 corp report): a
# CLAUDE_PLUGIN_ROOT ending in "/" produces a doubled "//" in LOCK_DIR/CACHE below. mkdir
# tolerates that fine, but on at least one real Windows/Git-Bash environment the SUBSEQUENT
# `date +%s >"$LOCK_STAMP"` write does not - it fails silently, which permanently disables
# the stale-lock reclaim below (a lock with no stamp can never be recognised as stale) for
# the rest of the session. POSIX parameter expansion only, no external command.
_root="${CLAUDE_PLUGIN_ROOT:-${CLAUDE_PROJECT_DIR:-.}}"
while [ "${_root%/}" != "$_root" ] && [ -n "$_root" ]; do
	_root="${_root%/}"
done
[ -n "$_root" ] || _root="/"

# 2026-08-13 live report: team-preferences.json, the interpreter cache, the fan-out lock
# and the cold-start cache are all PER-PROJECT state (install_helper.py's own
# write_guard_interpreter_cache() writes .guard-interpreter under the PROJECT directory,
# never a plugin install directory) - but until now they were resolved via the SAME
# $_root as DAEMON_CLIENT below, which is deliberately CLAUDE_PLUGIN_ROOT-first (correct
# for THAT one case: bash_hook_dispatcher.py is a file the plugin itself ships, genuinely
# found under the plugin's own install directory). In plugin-install mode, whenever
# CLAUDE_PLUGIN_ROOT happens to be set in the hook's own process (probe-contract.md
# already documents this exact env var as "not reliably expanded" - sometimes it is,
# sometimes it silently isn't), that conflation pointed all four project-state paths at
# the plugin's own directory instead of the project's. Confirmed live: a project's
# team-preferences.json had "guard_daemon": true recorded, but the daemon never
# activated - the hook was checking a team-preferences.json under the plugin's install
# path, which does not exist, not the one under the actual project. A separate root,
# CLAUDE_PROJECT_DIR only (deliberately never CLAUDE_PLUGIN_ROOT as a fallback here -
# unlike $_root, there is no correct case where a project's own state should live under
# the plugin's install directory instead of the project itself), same trailing-slash
# treatment as $_root above and for the identical reason.
#
# 2026-08-13 follow-up (live audit caught one instance this fix missed the first time):
# DAEMON_CLIENT itself has the exact same conflation one layer down - it was invoked
# with only $_root, which it needs correctly to locate the real bash_hook_dispatcher.py,
# but was ALSO using that same value to place ITS OWN per-project port file
# (.claude/.guard-daemon-port) and to decide which project's exec-consent marker a
# spawned daemon evaluates requests against. Now invoked with BOTH roots -
# guard_daemon_client.py's own docstring has the full rationale.
_project_root="${CLAUDE_PROJECT_DIR:-.}"
while [ "${_project_root%/}" != "$_project_root" ] && [ -n "$_project_root" ]; do
	_project_root="${_project_root%/}"
done
[ -n "$_project_root" ] || _project_root="/"

# Daemon path (ADR-014, docs/adr/ADR-014-persistent-guard-daemon.md) - checked once here,
# used at both invocation points below. Deliberately narrow: only ever engages when the
# target script ($1 - this launcher's own usage is always `run-guard.sh <script>`, never a
# flag first) is EXACTLY bash_hook_dispatcher.py by basename - locked_menu_guard.py and any
# other target this launcher is used for are completely unaffected, identical cold-start
# path as always. Off by default (no team-preferences.json, or an explicit false): this
# whole block resolves to _use_daemon=0 and NOTHING else in this file's behaviour changes,
# not even one byte - opt-in via .claude/team-preferences.json "guard_daemon": true
# (scripts/guard_daemon.py + scripts/guard_daemon_client.py, promoted 2026-08-12 from the
# design spike after live validation on the actual reporting Windows box - 8/8 smoke-test
# checks passed, including genuinely concurrent request safety).
_use_daemon=0
if [ "$(basename "$1" 2>/dev/null)" = "bash_hook_dispatcher.py" ]; then
	_prefs="$_project_root/.claude/team-preferences.json"
	if [ -f "$_prefs" ] && grep -q '"guard_daemon" *: *true' "$_prefs" 2>/dev/null; then
		_use_daemon=1
	fi
fi
DAEMON_CLIENT="$_root/scripts/guard_daemon_client.py"

# 2026-08-13 fast path (reported via log analysis of a real session): the lock/coldstart
# machinery below exists solely to serialize concurrent COLD STARTS - many interpreters
# racing to start at once under subagent fan-out. A daemon-routed call has no cold-start
# race to serialize against: every such call shares ONE persistent daemon process that
# already serializes its own requests internally (guard_daemon.py's own _dispatch_lock).
# Paying the lock-acquisition/coldstart-measurement overhead unconditionally on a
# daemon-routed call is pure waste - on a corporate Windows/Git-Bash host under AV
# scanning, each step below is its own process spawn (mkdir x2, date, cat, rm - roughly
# 3+ seconds stacked up under real conditions), swamping whatever latency benefit the
# daemon exists to provide, and paid BEFORE this launcher even reaches the daemon
# decision. Steady state (interpreter already cached from a prior call - the
# overwhelmingly common case in a real session) skips straight to the daemon invocation
# here. A cold cache (this project's very first call) falls through to the full machinery
# below unchanged - it still finds and caches an interpreter, and its own
# daemon-invocation branch further down handles that first call correctly; this fast path
# only ever engages once the interpreter is already known, never before.
if [ "$_use_daemon" = 1 ] && [ -f "$DAEMON_CLIENT" ]; then
	_fastcache="$_project_root/.claude/.guard-interpreter"
	if [ -f "$_fastcache" ]; then
		_fastcached=$(cat "$_fastcache" 2>/dev/null)
		if [ -n "$_fastcached" ] && command -v "$_fastcached" >/dev/null 2>&1; then
			"$_fastcached" "$DAEMON_CLIENT" "$_root" "$_project_root"
			exit $?
		fi
	fi
fi

LOCK_DIR="$_project_root/.claude/.guard-lock"
LOCK_STAMP="$LOCK_DIR/acquired-at"
# Same normalized root as LOCK_DIR above - defined here (once) rather than at its original,
# later point of use, so the cold-start probe below and the real interpreter-cache lookup
# further down read and write the exact same path instead of two independently-computed
# variables that could silently diverge the same way LOCK_DIR/LOCK_STAMP just did.
CACHE="$_project_root/.claude/.guard-interpreter"
LOCK_MAX_AGE_SECONDS=10  # generous upper bound for one interpreter start + guard check;
# older means the holder is gone, not genuinely still working.

# LOCK_WAIT_BUDGET_MS must exceed real interpreter cold-start time on THIS host, or a
# waiting caller gives up and races ahead unlocked before the current holder could
# realistically finish - defeating serialization for exactly the slow-host case it exists
# for (2026-08-11 corp report: this was a flat 1500ms while observed cold starts on a
# corp-AV-scanned Windows box ran 2-9s normally, 25-90s under fan-out contention). The floor
# stays the original 1500ms, NOT tied to LOCK_MAX_AGE_SECONDS - an earlier version of this
# fix raised the floor above LOCK_MAX_AGE_SECONDS*1000 reasoning a waiter should always be
# able to reach the stale-lock reclaim check, but that reasoning was wrong and conflicted
# with this launcher's own deliberate design: the reclaim check compares the LOCK's absolute
# age each poll, not the waiter's own elapsed time, so a short budget does not block reclaim
# - and test_run_guard_lock.py::test_a_genuinely_held_lock_fails_open_within_the_wait_budget
# already encodes the correct intent here on purpose: a genuinely (non-stale) held lock
# should fail this caller open QUICKLY, not wait around hoping it goes stale. Only the
# ADAPTIVE part (scaling with measured cold start) is this fix; the floor for a fast host or
# a not-yet-cached one is unchanged from before it. Measured using the ALREADY-CACHED interpreter
# only (.guard-interpreter, populated by the selection loop further down) - never a fresh,
# unvalidated probe here, which would risk reintroducing the exact Windows "python3
# resolves to the Store stub" multi-second hang that selection loop is specifically ordered
# to avoid. On a session's very first call (no cache yet) this measurement is skipped and
# the floor below applies - that first call already pays its own one-time
# interpreter-resolution cost separately; a second, possibly stub-prone probe here would
# only add to it, not save anything.
COLDSTART_CACHE="$_project_root/.claude/.guard-coldstart-ms"
_measured_ms=""
if [ -f "$COLDSTART_CACHE" ]; then
	_measured_ms=$(cat "$COLDSTART_CACHE" 2>/dev/null)
fi
case "$_measured_ms" in
	''|*[!0-9]*) _measured_ms="" ;;  # missing, empty or non-numeric cache -> (re)measure
esac
if [ -z "$_measured_ms" ] && [ -f "$CACHE" ]; then
	_known_good=$(cat "$CACHE" 2>/dev/null)
	if [ -n "$_known_good" ] && command -v "$_known_good" >/dev/null 2>&1; then
		# Whole-second `date +%s` only, matching the rest of this script - `%N` (sub-second)
		# is a GNU extension BSD/macOS `date` does not reliably support, and the costs this
		# measures are already multi-second under the conditions that motivate this fix, so
		# second-level precision is coarse but adequate; it only ever errs toward the floor
		# on a genuinely fast host, which is the safe direction to be wrong in.
		_t0=$(date +%s 2>/dev/null) || _t0=""
		"$_known_good" -c 'pass' >/dev/null 2>&1
		_t1=$(date +%s 2>/dev/null) || _t1=""
		if [ -n "$_t0" ] && [ -n "$_t1" ] && [ "$_t1" -ge "$_t0" ] 2>/dev/null; then
			_measured_ms=$(( (_t1 - _t0) * 1000 ))
		else
			_measured_ms=0
		fi
		mkdir -p "$(dirname "$COLDSTART_CACHE")" 2>/dev/null
		printf '%s' "$_measured_ms" >"$COLDSTART_CACHE" 2>/dev/null
	fi
fi
[ -n "$_measured_ms" ] || _measured_ms=0
# Budget = 4x measured cold start (headroom for AV-scan variance and shallow queueing under
# fan-out), floored at the original 1500ms (never LESS generous than before this fix - a
# fast host or one with no measurement yet behaves exactly as it did previously) and capped
# so a wait this long stops being "serialization" and starts being a hang - the reclaim and
# the budget-exhausted fail-open below both still apply as backstops beyond this cap either
# way.
LOCK_WAIT_BUDGET_MS=$(( _measured_ms * 4 ))
[ "$LOCK_WAIT_BUDGET_MS" -ge 1500 ] 2>/dev/null || LOCK_WAIT_BUDGET_MS=1500
[ "$LOCK_WAIT_BUDGET_MS" -le 20000 ] 2>/dev/null || LOCK_WAIT_BUDGET_MS=20000
LOCK_POLL_MS=25

# Ensure the PARENT exists once, up front - mkdir "$LOCK_DIR" below deliberately has no -p
# (an existing target must make it fail, that failure IS the "someone else holds it" signal
# the loop polls on); without this, a missing .claude/ would make every acquisition attempt
# fail the same way as real contention, silently wasting the full wait budget every call
# before falling through to fail-open, rather than succeeding immediately as it should.
mkdir -p "$(dirname "$LOCK_DIR")" 2>/dev/null

_lock_acquired=0
_elapsed_ms=0
while [ "$_elapsed_ms" -lt "$LOCK_WAIT_BUDGET_MS" ]; do
	if mkdir "$LOCK_DIR" 2>/dev/null; then
		if date +%s >"$LOCK_STAMP" 2>/dev/null; then
			_lock_acquired=1
		else
			# Stamp write failed even though mkdir succeeded (2026-08-11 corp report: seen
			# with a trailing-slash root producing a doubled "//" before the strip above
			# existed - kept as a defensive backstop in case another path-translation edge
			# case on Windows/Git Bash produces the same mkdir/write asymmetry some other
			# way). A lock with no stamp can NEVER be recognised as stale by the reclaim
			# logic below, so holding it would risk exactly the stuck-lock-for-the-rest-
			# of-the-session failure the reclaim exists to prevent - worse than just not
			# serializing this one call. Visible (stderr, never stdout - this script's
			# stdout must stay clean for the wrapped guard's own output), then release and
			# fail open rather than risk a lock nobody can ever reclaim.
			echo "run-guard.sh: warning: lock acquired but stale-lock stamp write failed" \
				"($LOCK_STAMP) - releasing lock, proceeding without serialization for" \
				"this call" >&2
			rm -rf "$LOCK_DIR" 2>/dev/null
		fi
		break
	fi
	if [ -f "$LOCK_STAMP" ]; then
		_stamp=$(cat "$LOCK_STAMP" 2>/dev/null)
		_now=$(date +%s 2>/dev/null)
		if [ -n "$_stamp" ] && [ -n "$_now" ] && [ "$((_now - _stamp))" -gt "$LOCK_MAX_AGE_SECONDS" ] 2>/dev/null; then
			rm -rf "$LOCK_DIR" 2>/dev/null
			continue
		fi
	fi
	sleep 0.025 2>/dev/null || sleep 1
	_elapsed_ms=$((_elapsed_ms + LOCK_POLL_MS))
done
if [ "$_lock_acquired" = 1 ]; then
	# Covers the interpreter (or crash/kill) exiting abnormally; SIGKILL still can't be
	# trapped by design (POSIX), which is exactly why the stale-lock reclaim above exists as
	# the backstop for that one case this trap cannot cover.
	trap 'rm -rf "$LOCK_DIR" 2>/dev/null' EXIT INT TERM
fi

# Below: same interpreter resolution as before, just "run and wait" instead of "exec" (exec
# replaces this process image, which would skip the lock-release above entirely - it must
# run after the guard completes, not instead of this script continuing). CACHE is already
# set above (same normalized $_project_root as LOCK_DIR).

if [ -f "$CACHE" ]; then
	cached=$(cat "$CACHE" 2>/dev/null)
	if [ -n "$cached" ] && command -v "$cached" >/dev/null 2>&1; then
		if [ "$_use_daemon" = 1 ] && [ -f "$DAEMON_CLIENT" ]; then
			"$cached" "$DAEMON_CLIENT" "$_root" "$_project_root"
			exit $?
		fi
		"$cached" "$@"
		exit $?
	fi
fi
# Probe order (2026-07-31 corporate report, P2): the loop below still EXECUTES the first
# name command -v resolves, to version-check it, before any cache exists - on Windows,
# "python3" resolving to the Store stub means that first, uncached call pays the multi-
# second stub hang even though `python`/`py` were sitting right behind it. $OS is set to
# "Windows_NT" by the OS itself and inherited into Git Bash, so this is a real, not
# heuristic, signal - try the real interpreters first there and leave the stub for last.
if [ "${OS:-}" = "Windows_NT" ]; then
	order="python py python3"
else
	order="python3 python py"
fi
for interpreter in $order; do
	if command -v "$interpreter" >/dev/null 2>&1; then
		if "$interpreter" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' >/dev/null 2>&1; then
			mkdir -p "$(dirname "$CACHE")" 2>/dev/null
			printf '%s' "$interpreter" >"$CACHE" 2>/dev/null
			if [ "$_use_daemon" = 1 ] && [ -f "$DAEMON_CLIENT" ]; then
				"$interpreter" "$DAEMON_CLIENT" "$_root" "$_project_root"
				exit $?
			fi
			"$interpreter" "$@"
			exit $?
		fi
	fi
done
exit 0
