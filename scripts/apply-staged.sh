#!/usr/bin/env bash
# Promote every pending hook change from scripts/staged_hooks/ to its live path, then delete
# the staged copy. HUMAN-RUN, never by an agent (ADR-002 rec 5; CLAUDE.md §7): the model can
# write into scripts/staged_hooks/ and nowhere on the live side, and this is the one command
# that crosses that line. Replaces the 28 per-fix apply scripts (2026-09-13, plan step 3.6).
#
#   bash scripts/apply-staged.sh          # promote everything pending, list what moved
#   bash scripts/apply-staged.sh --dry-run
#
# Placement rule (the same one the installer's pending check and tests/_staging.py use):
# guard-* files and run-guard.sh live under .claude/hooks/, everything else under scripts/.
set -euo pipefail
here="$(cd "$(dirname "$0")/.." && pwd)"
cd "$here"
dry=0; [ "${1:-}" = "--dry-run" ] && dry=1
staged_dir="scripts/staged_hooks"
moved=0
if [ -d "$staged_dir" ]; then
  for staged in "$staged_dir"/*; do
    [ -f "$staged" ] || continue
    name="$(basename "$staged")"
    case "$name" in *.pyc|.*) continue ;; esac
    case "$name" in
      guard-*|run-guard.sh) live=".claude/hooks/$name" ;;
      *)                    live="scripts/$name" ;;
    esac
    if [ ! -f "$live" ]; then
      echo "!! $name has no live counterpart at $live - a NEW hook needs its wiring reviewed first" >&2
      exit 1
    fi
    if cmp -s "$staged" "$live"; then
      echo "identical, dropping the staged copy: $name"
      [ "$dry" -eq 1 ] || rm -f "$staged"
      continue
    fi
    echo "promote: $staged -> $live"
    if [ "$dry" -eq 0 ]; then
      cp "$staged" "$live"
      case "$live" in *.sh) chmod +x "$live" ;; esac
      rm -f "$staged"
    fi
    moved=$((moved + 1))
  done
  rm -rf "$staged_dir/__pycache__"
fi
if [ "$moved" -eq 0 ]; then
  echo "nothing pending in $staged_dir"
else
  echo "$moved file(s) promoted. Next: .venv/bin/python -m pytest -q (expect 0 failed), then commit the live files and restart the session."
fi
