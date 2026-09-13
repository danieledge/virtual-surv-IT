#!/usr/bin/env bash
# Promote the STAGED document_input_redirect check to its live location.
#
# HISTORY. document_input_redirect's WIRING is consolidated into
# scripts/bash_hook_dispatcher.py's own _CHECKS table (the 2026-07-31 P4 consolidation that
# collapsed five separate Bash-matching hooks, this one included, into ONE process per call).
# This script used to ALSO re-wire a standalone "Read|Bash" PreToolUse entry on top of the
# dispatcher's, duplicating the check and spawning an extra cold-start process per call - a
# bug caught twice (2026-08-13). So it was turned into a no-op.
#
# But turning it into a no-op threw out the file promotion with the wiring: the live check
# still lives in scripts/document_input_redirect.py, the dispatcher imports and runs it, and a
# staged fix to scripts/staged_hooks/document_input_redirect.py never reached it - the
# staged/live sync test then failed with no working apply path (2026-09-13, the day a real fix
# to this check could not be applied). This script now does the one thing an apply script must:
# copy the staged file to the live location. It deliberately does NOT add any hook wiring - the
# dispatcher already covers that, and re-adding it is the original bug.
#
#   Usage:  bash scripts/apply-document-redirect.sh
set -euo pipefail
here="$(cd "$(dirname "$0")/.." && pwd)"
staged="$here/scripts/staged_hooks/document_input_redirect.py"
live="$here/scripts/document_input_redirect.py"

if [ ! -f "$staged" ]; then
	echo "no staged copy at $staged - nothing to apply." >&2
	exit 0
fi
if cmp -s "$staged" "$live"; then
	echo "document_input_redirect.py already in sync - nothing to apply."
	exit 0
fi
cp "$staged" "$live"
echo "installed: $live updated from the staged copy."
echo ""
echo "WIRING UNCHANGED: document_input_redirect runs through scripts/bash_hook_dispatcher.py's"
echo "own _CHECKS table (P4 consolidation). This script copies the FILE only and adds no"
echo "standalone hook entry - re-adding one duplicates the check per call. If a standalone entry"
echo "exists in hooks/hooks.json or .claude/settings.json, remove it (git checkout)."
echo ""
echo "Now commit the change (both files ship together):"
echo "  git add scripts/document_input_redirect.py scripts/staged_hooks/document_input_redirect.py"
