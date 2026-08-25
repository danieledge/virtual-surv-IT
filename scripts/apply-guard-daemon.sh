#!/usr/bin/env bash
# ADR-014 (docs/adr/ADR-014-persistent-guard-daemon.md) - persistent guard daemon,
# promoted from the design spike (docs/internal/adr-014-spike/) after live validation on
# the actual reporting Windows box, 2026-08-12: 8/8 smoke-test checks passed, including
# genuinely concurrent request safety and staleness detection (see ADR-014 v0.3).
#
# Installs THREE staged files together - they only make sense as one unit:
#   - .claude/hooks/run-guard.sh          (updated: daemon-aware, opt-in, see below)
#   - scripts/guard_daemon.py             (new: the daemon itself)
#   - scripts/guard_daemon_client.py      (new: run-guard.sh's daemon client)
#
# The launcher blocks the model from editing .claude/hooks/** directly (correctly - a model
# that can edit a guard can neuter it, ADR-002 rec 5), so installing is a HUMAN act, same as
# every other hook change in this project. Idempotent.
#
#   Usage:  bash scripts/apply-guard-daemon.sh
#   Undo:   git checkout .claude/hooks/run-guard.sh scripts/guard_daemon.py \
#             scripts/guard_daemon_client.py
#
# ON BY DEFAULT since 2026-08-25 - APPLYING THIS DOES CHANGE LIVE BEHAVIOUR.
#   It was opt-in until then, and the flip is deliberate: the daemon runs the SAME guard
#   code, so the only difference is one interpreter cold start per hook, and the opt-in
#   default was charging every user that cost to guard a risk that never materialised.
#   The daemon branch engages when the target is bash_hook_dispatcher.py (never
#   locked_menu_guard.py or anything else this launcher is used for) AND the two-tier
#   preference resolves on: project .claude/team-preferences.json "guard_daemon" wins over
#   the machine installer.json "default_guard_daemon", and absent config means ON.
#   Turn it off per project via `/preferences`, or machine-wide in installer.json.
#   Fail-safe direction: unreadable, absent or malformed config leaves it ON, because the
#   path it falls back to is slower, never less safe.
#
# WHAT THIS CLOSES
#   Every hook invocation was a fresh OS process paying a full interpreter cold start PLUS
#   guard-module import cost every single call - measured live on the reporting box,
#   2026-08-12: real guard-launcher cost 1372-3808ms (median 1404ms) vs. bare interpreter
#   cold start 82-106ms, ~15x. The daemon imports the real, unmodified
#   scripts.bash_hook_dispatcher ONCE and serves subsequent requests over a local socket -
#   measured live on the same box: 12.6ms daemon-backed median vs. 307ms cold-start median.
#
# ATTACK SURFACE (ADR-014 question 3): bound strictly to 127.0.0.1, never 0.0.0.0. A random
# per-daemon token is required on every request - closes the gap where a local process
# WITHOUT filesystem read access to this project's .claude/ directory could otherwise reach
# the daemon by port-scanning; does not (and is not intended to) defend against a process
# that already has that access, which is the same trust boundary .guard-interpreter/
# .guard-lock already imply as plain files.
#
# CONCURRENCY (found live while building the spike, not anticipated in ADR-014's original
# text): bash_hook_dispatcher.main() reads sys.stdin/writes sys.stderr directly -
# process-global state. Dispatch is serialized behind a lock inside the daemon even though
# its TCP server accepts concurrent connections - live-tested, 10 genuinely concurrent mixed
# requests, zero cross-talk.
#
# KNOWN LIMITATION, DELIBERATE FOR THIS PASS: daemon-path calls still go through
# run-guard.sh's own mkdir-lock (the launcher's pre-existing fan-out serialization) in
# ADDITION to the daemon's internal lock - correctness-safe (no regression), but not
# maximally fast under heavy concurrent fan-out, since the shell-level lock still queues
# calls that the daemon itself could have safely run back-to-back once past its own lock.
# Moving the daemon-check ahead of the mkdir-lock is a real follow-up optimisation, not
# attempted here - smaller, more reviewable change first.
#
# NOT covered by live validation yet: idle-timeout actually firing (needs a manual 60s+
# wait, deliberately excluded from the automated smoke test), and whether the Windows
# detached-spawn (DETACHED_PROCESS | CREATE_NO_WINDOW) stays genuinely invisible in a real
# Claude Code hook invocation (only checked via the smoke test's own daemon start, not via
# a real PreToolUse call).
#
# Regression net: tests/test_hooks_in_sync.py (staged==live, auto-discovers these three
# files by scripts/staged_hooks/'s own naming convention - guard_daemon.py/
# guard_daemon_client.py route to scripts/, not .claude/hooks/, since they don't start with
# "guard-"), tests/test_adr014_guard_daemon_spike.py (pure-logic coverage, still valid - the
# production files are the validated spike design plus the token addition), and the spike's
# own live smoke test (docs/internal/adr-014-spike/smoke_test.py / Diagnostics menu option
# 6) for the execution-dependent claims.
set -euo pipefail

here="$(cd "$(dirname "$0")/.." && pwd)"

apply_one() {
  local src="$1" dst="$2"
  if [ ! -f "$src" ]; then
    echo "ERROR: staged file not found at $src" >&2
    exit 1
  fi
  if [ -f "$dst" ] && cmp -s "$src" "$dst"; then
    echo "already installed: $dst"
    return 0   # 0 = unchanged; a copy returns 1. Callers read this, so do not "tidy" it.
  fi
  cp "$src" "$dst"
  echo "installed: $dst updated from staged copy."
  return 1
}

changed=0
apply_one "$here/scripts/staged_hooks/run-guard.sh" "$here/.claude/hooks/run-guard.sh" || changed=1
apply_one "$here/scripts/staged_hooks/guard_daemon.py" "$here/scripts/guard_daemon.py" || changed=1
apply_one "$here/scripts/staged_hooks/guard_daemon_client.py" "$here/scripts/guard_daemon_client.py" || changed=1

if [ "$changed" -eq 0 ]; then
  echo ""
  echo "Nothing to do - live already matches staged, so there is nothing to commit either."
  exit 0
fi

echo ""
echo "Now commit the change (all three ship together, plus their staged copies):"
echo "  git add .claude/hooks/run-guard.sh scripts/guard_daemon.py scripts/guard_daemon_client.py \\"
echo "          scripts/staged_hooks/run-guard.sh scripts/staged_hooks/guard_daemon.py \\"
echo "          scripts/staged_hooks/guard_daemon_client.py"
echo ""
echo "ON by default from this change, at machine and project level. It runs the SAME"
echo "guard code in a persistent process - the difference is one interpreter start per"
echo "hook, not what gets checked. Turn it off for a project via /preferences, or for"
echo "this machine with \"default_guard_daemon\": false in installer.json; project wins."
