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
# If no suitable Python is found we exit 0 (allow): the OS-level permissions.deny list in
# .claude/settings.json remains the hard boundary for data/raw and secrets - but NOTE this
# backstop covers Read/Grep/Glob only; there are no Bash() deny entries, so on a Python-less
# host the execution gate is inert (see ADR-002 §launcher trade-off). A hard block here would
# brick every tool call on a Python-less host, which is not the guard's job.
for interpreter in python3 python py; do
	if command -v "$interpreter" >/dev/null 2>&1; then
		if "$interpreter" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' >/dev/null 2>&1; then
			exec "$interpreter" "$@"
		fi
	fi
done
exit 0
