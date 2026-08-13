#!/usr/bin/env bash
# SUPERSEDED - module_form_redirect is already registered in
# scripts/bash_hook_dispatcher.py's own _CHECKS table (the 2026-07-31 P4 consolidation
# that collapsed five separate Bash-matching hooks, this one included, into ONE process
# per call). This script predates that consolidation and was never updated afterwards -
# every time it (or scripts/apply-outstanding.sh, which runs it automatically) ran, it
# silently RE-WIRED a standalone "Bash" PreToolUse entry for
# scripts/module_form_redirect.py on top of the dispatcher's own entry, duplicating the
# check on every Bash call and spawning an extra cold-start process per call the P4
# consolidation exists specifically to avoid. Caught twice: once by a 2026-08-13
# Fable-model audit (reverted by hand), and again the same day when a later
# apply-outstanding.sh run silently reintroduced it - this script was the actual root
# cause both times, never fixed at the source until now.
#
# Kept as a thin redirect (not deleted outright) in case anything still references this
# filename directly - deleting a named, documented human-run script out from under a
# stale doc link is worse than a clear pointer. scripts/module_form_redirect.py itself
# is unaffected and still current; only THIS script's wiring behaviour is retired.
#
# Exits 0 (not 1): a redirect that makes no changes is a legitimate, expected outcome -
# scripts/apply-outstanding.sh loops over every apply-*.sh unconditionally and relies on
# each one being a safe, always-succeeds no-op when there's nothing for it to do;
# exiting nonzero here would abort that whole batch under set -e for a script whose only
# job now is explaining why it does nothing.
#
#   Usage:  bash scripts/apply-module-redirect.sh
set -euo pipefail
echo "apply-module-redirect.sh is superseded - nothing to apply."
echo ""
echo "module_form_redirect is already covered by scripts/bash_hook_dispatcher.py's own"
echo "consolidated dispatch (its _CHECKS table) - the single PreToolUse entry already wired"
echo "for Read|Grep|Glob|Write|Edit|MultiEdit|NotebookEdit|NotebookRead|WebFetch|Bash runs"
echo "it, along with every other consolidated check, in ONE process per call. A standalone"
echo "entry for this script alone would only duplicate that check and cost an extra"
echo "cold-start process per Bash call - exactly what the P4 consolidation exists to avoid."
echo "If a standalone entry exists in hooks/hooks.json or .claude/settings.json, remove it"
echo "(git checkout, or a targeted edit) rather than running this script."
exit 0
