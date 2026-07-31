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
CACHE="${CLAUDE_PLUGIN_ROOT:-${CLAUDE_PROJECT_DIR:-.}}/.claude/.guard-interpreter"
if [ -f "$CACHE" ]; then
	cached=$(cat "$CACHE" 2>/dev/null)
	if [ -n "$cached" ] && command -v "$cached" >/dev/null 2>&1; then
		exec "$cached" "$@"
	fi
fi
for interpreter in python3 python py; do
	if command -v "$interpreter" >/dev/null 2>&1; then
		if "$interpreter" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' >/dev/null 2>&1; then
			mkdir -p "$(dirname "$CACHE")" 2>/dev/null
			printf '%s' "$interpreter" >"$CACHE" 2>/dev/null
			exec "$interpreter" "$@"
		fi
	fi
done
exit 0
