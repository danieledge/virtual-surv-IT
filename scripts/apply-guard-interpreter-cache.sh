#!/usr/bin/env bash
# SUPERSEDED by scripts/apply-guard-daemon.sh (ADR-014, 2026-08-12).
#
# This script used to install just the interpreter-caching fix for run-guard.sh. The
# staged launcher (scripts/staged_hooks/run-guard.sh) now also carries the ADR-014
# daemon-aware branch on top of that same fix - one file, two features layered in - so
# applying THIS script alone would still correctly install the interpreter-cache fix,
# but would leave a launcher whose daemon branch references scripts/guard_daemon.py and
# scripts/guard_daemon_client.py without ever installing them. Harmless by design (the
# daemon branch checks `[ -f "$DAEMON_CLIENT" ]` before ever using it, so a live launcher
# without those two files just never engages the daemon path, same cold-start behaviour
# as always) - but it silently leaves "guard_daemon": true in team-preferences.json doing
# nothing, which is confusing to debug later.
#
# Kept as a thin redirect (not deleted outright) in case anything still references this
# filename directly - deleting a named, documented human-run script out from under a
# stale doc link is worse than a clear pointer.
#
# Exits 0 (not 1): a redirect that made no changes is a legitimate, expected outcome
# here, not a failure - scripts/apply-outstanding.sh loops over every apply-*.sh
# unconditionally and relies on each one being a safe, always-succeeds no-op when
# there's nothing (or nothing further) for it to do; exiting nonzero here would abort
# that whole batch under set -e for a script that only exists to point elsewhere.
#
#   Usage:  bash scripts/apply-guard-interpreter-cache.sh
set -euo pipefail
echo "apply-guard-interpreter-cache.sh is superseded - run this instead:"
echo "  bash scripts/apply-guard-daemon.sh"
echo ""
echo "It installs the same run-guard.sh (which now carries this fix already, plus the"
echo "ADR-014 daemon branch) together with the two daemon files that branch needs -"
echo "the three only make sense as one unit. Exiting without changing anything."
exit 0
