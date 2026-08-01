#!/bin/sh
# Portable launcher for the PreToolUse safety guards.
#
# Claude Code runs hook commands in a POSIX shell (sh/bash on Linux & macOS, Git Bash on
# Windows). The bare `python3` used previously is not present on Windows, where the interpreter
# is `python` or the `py` launcher - so the guard failed to start there ("python3: command not
# found") and, worse, did not run at all. This finds whichever interpreter exists and `exec`s it,
# so the guard's stdin (the tool payload) and exit code (2 = block) pass through unchanged.
#
# This wrapper is intentionally tiny and holds NO guard logic - the guards themselves
# (guard-raw-data.py, guard-code-execution.py) are unchanged. It only selects an interpreter.
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

CACHE="${CLAUDE_PLUGIN_ROOT:-${CLAUDE_PROJECT_DIR:-.}}/.claude/.guard-interpreter"
if [ -f "$CACHE" ]; then
	cached=$(cat "$CACHE" 2>/dev/null)
	if [ -n "$cached" ] && command -v "$cached" >/dev/null 2>&1; then
		exec "$cached" "$@"
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
			exec "$interpreter" "$@"
		fi
	fi
done
exit 0
