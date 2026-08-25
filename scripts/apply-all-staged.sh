#!/usr/bin/env bash
# Apply EVERY pending staged hook fix in one pass - human-only, like all apply-*.sh
# (hook and guard changes are a HUMAN act: ADR-002 rec 5; the model stages fixes under
# scripts/staged_hooks/ and is blocked from installing them itself).
#
#   Usage:  bash scripts/apply-all-staged.sh
#   Undo:   git checkout -- <the live files it lists as updated>
#
# How it works: compares every file in scripts/staged_hooks/ against its live
# counterpart (scripts/<name> or .claude/hooks/<name>) and, for each one that differs,
# runs the MATCHING per-fix apply script from the map below - so each fix keeps its own
# tested install logic, and a staged file this map doesn't know is a hard error, never
# a silent skip (2026-08-01 lesson: a silently inert control looks healthy). Idempotent:
# nothing pending means nothing runs. Finishes by running the sync tests so "applied"
# is verified, not assumed.
#
# 2026-08-25: this script was itself an instance of the failure it was written to prevent.
# It globbed scripts/staged_hooks/*.py, so run-guard.sh - the one shell file in there - was
# invisible to it, and it printed "nothing pending" while that file sat waiting to be
# applied. It had never bitten because run-guard.sh had always changed alongside a .py file
# whose apply script installs both; the day it changed alone, the control reported healthy.
# Two staged files (guard_daemon_client.py, module_form_redirect.py) were also missing from
# apply_for() - latent for the same reason, since the map is only consulted for a file that
# DIFFERS from live. Now globs every regular file and maps all of them.
set -euo pipefail

here="$(cd "$(dirname "$0")/.." && pwd)"
cd "$here"

# staged basename -> the apply script that installs it (one script may cover several).
apply_for() {
  case "$1" in
    dod_stop_gate.py|persona_anchor.py) echo "scripts/apply-project-anchor.sh" ;;
    todo_panel_nudge.py)                echo "scripts/apply-todo-panel-nudge.sh" ;;
    stop_hook_dispatcher.py)            echo "scripts/apply-stop-hook-dispatcher.sh" ;;
    locked_menu_guard.py)               echo "scripts/apply-locked-menu-guard.sh" ;;
    bash_hook_dispatcher.py)            echo "scripts/apply-bash-hook-dispatcher.sh" ;;
    guard-consent-writes.py)            echo "scripts/apply-guard-git-config.sh" ;;
    guard-raw-data.py)                  echo "scripts/apply-guard-raw-coverage.sh" ;;
    guard-code-execution.py)            echo "scripts/apply-guard-exec-allow.sh" ;;
    guard-findings-pack-write.py)       echo "scripts/apply-guard-findings-pack-write.sh" ;;
    document_input_redirect.py)         echo "scripts/apply-document-redirect.sh" ;;
    post_edit_lint.py)                  echo "scripts/apply-post-edit-lint.sh" ;;
    session_resume_brief.py)            echo "scripts/apply-session-brief.sh" ;;
    engage_probe_prefetch.py)           echo "scripts/apply-engage-probe-prefetch.sh" ;;
    subagent_return_budget.py)          echo "scripts/apply-subagent-budget.sh" ;;
    guard_daemon.py|guard_daemon_client.py|run-guard.sh)
                                        echo "scripts/apply-guard-daemon.sh" ;;
    module_form_redirect.py)            echo "scripts/apply-module-redirect.sh" ;;
    *)                                  echo "" ;;
  esac
}

live_for() {
  for candidate in "scripts/$1" ".claude/hooks/$1"; do
    if [ -f "$candidate" ]; then echo "$candidate"; return; fi
  done
  echo ""
}

pending_scripts=""
unknown=0
for staged in scripts/staged_hooks/*; do
  [ -f "$staged" ] || continue          # __pycache__ and any future subdirectory
  name="$(basename "$staged")"
  case "$name" in *.pyc|.*) continue ;; esac
  live="$(live_for "$name")"
  if [ -z "$live" ]; then
    echo "!! $name is staged but has NO live counterpart - install it via its apply script manually"
    unknown=1
    continue
  fi
  if cmp -s "$staged" "$live"; then
    continue
  fi
  apply="$(apply_for "$name")"
  if [ -z "$apply" ] || [ ! -f "$apply" ]; then
    echo "!! $name differs from $live but no apply script is mapped for it - add it to apply_for()"
    unknown=1
    continue
  fi
  echo "pending: $name ($live) -> $apply"
  case " $pending_scripts " in
    *" $apply "*) ;;
    *) pending_scripts="$pending_scripts $apply" ;;
  esac
done

if [ "$unknown" -ne 0 ]; then
  echo "aborting: unmapped staged file(s) above - nothing applied."
  exit 1
fi

if [ -z "$pending_scripts" ]; then
  echo "nothing pending - every staged hook matches its live copy."
  exit 0
fi

for apply in $pending_scripts; do
  echo
  echo "== running $apply"
  bash "$apply"
done

echo
echo "== verifying: staged/live sync tests"
if command -v pytest >/dev/null 2>&1; then
  pytest -q tests/test_hooks_in_sync.py tests/test_todo_panel_nudge.py \
         tests/test_run_guard_interpreter_cache.py -k "sync or match" || {
    echo "!! sync verification FAILED - a fix did not install cleanly; see above."
    exit 1
  }
  echo "all applied and verified."
else
  echo "(pytest not found - applied, but run the sync tests to verify:"
  echo "  python3 -m pytest tests/test_hooks_in_sync.py -q )"
fi
