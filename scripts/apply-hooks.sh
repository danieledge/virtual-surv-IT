#!/bin/bash
# HUMAN-run umbrella (ADR-002 rec 5: hook wiring is a human act): applies EVERY staged
# repo hook wiring in one go. Each underlying apply script is idempotent, so this is
# always safe to re-run - and it removes the pick-the-right-apply-script trap (three
# live runs on 2026-07-30 grabbed apply-document-redirect.sh when the module one was
# needed).
#
# Deliberately excluded:
#   apply-statusline.sh       - USER-level settings, opt-in (the installer offers it)
#   apply-guard-exec-allow.sh - guard allow-list changes are reviewed one by one
#
#   bash scripts/apply-hooks.sh
set -euo pipefail
cd "$(dirname "$0")"

for s in apply-project-anchor.sh apply-document-redirect.sh apply-session-brief.sh \
  apply-post-edit-lint.sh apply-module-redirect.sh; do
  if [ -f "$s" ]; then
    echo "== $s"
    bash "$s"
    echo
  fi
done
echo "All hook wirings applied. Restart the session (or /hooks) to load them."
