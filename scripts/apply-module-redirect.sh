#!/usr/bin/env bash
# Promote the staged module_form_redirect.py to its live location, scripts/.
#
# History: this script used to say "superseded - nothing to apply", because the hook needs
# no PreToolUse entry of its own (scripts/bash_hook_dispatcher.py runs it from its _CHECKS
# table, one process per call). That was true of the WIRING and wrong about the FILE: the
# staged copy still has to reach scripts/module_form_redirect.py, and the first live run of
# the 2026-09-12 audit apply pass found the staged H-5 fix (allow decision only for a
# single-segment command) sitting unpromoted while this script printed that there was
# nothing to do. It now does the copy and nothing else; wiring stays where it was.
set -euo pipefail
here="$(cd "$(dirname "$0")/.." && pwd)"
cp "$here/scripts/staged_hooks/module_form_redirect.py" "$here/scripts/module_form_redirect.py"
echo "module_form_redirect: staged copy installed to scripts/ (no hook entry needed; the dispatcher runs it)."
