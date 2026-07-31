#!/bin/bash
# HUMAN-run diagnostic (not part of any hook/skill flow): times each stage of the
# engage-skill step-0 probe separately, so a slow environment (corp AV, mapped network
# drive, a Windows Store python stub) shows up as a specific number instead of "engage
# takes minutes" with no lead. Read-only - runs the same commands the probe runs,
# writes nothing, changes nothing.
#
#   bash scripts/diagnose-engage-startup.sh
set -u
cd "$(dirname "$0")/.." || exit 1

ms() { # print elapsed ms for "the last timed block" using bash's own clock
  local start=$1 end
  end=$(date +%s%N 2>/dev/null || echo "${start}000000")
  echo $(((end - start) / 1000000))
}

echo "=== engage step-0 probe timing diagnostic ==="
echo "(each stage run in isolation; corp AV/EDR, a mapped network drive, or a Windows"
echo " Store python stub typically shows up as ONE outlier below)"
echo

t0=$(date +%s%N)
cat docs/team-operating-guide.md >/dev/null 2>&1
echo "cat team-operating-guide.md (493 lines): $(ms "$t0") ms"

t0=$(date +%s%N)
python3 --version >/dev/null 2>&1
echo "python3 --version: $(ms "$t0") ms"

t0=$(date +%s%N)
python --version >/dev/null 2>&1
echo "python --version: $(ms "$t0") ms"

t0=$(date +%s%N)
py --version >/dev/null 2>&1
echo "py --version: $(ms "$t0") ms"

t0=$(date +%s%N)
bash scripts/check-review-tools.sh >/dev/null 2>&1
echo "check-review-tools.sh (cached, ~18 tool probes): $(ms "$t0") ms"

t0=$(date +%s%N)
rm -f .claude/.tool-availability 2>/dev/null
bash scripts/check-review-tools.sh >/dev/null 2>&1
echo "check-review-tools.sh (COLD, forces re-probe): $(ms "$t0") ms"

t0=$(date +%s%N)
awk '/^## \[/{n++} n==1' CHANGELOG.md >/dev/null 2>&1
echo "awk first CHANGELOG entry (1960 lines): $(ms "$t0") ms"

t0=$(date +%s%N)
python3 -m scripts.engagement_state list >/dev/null 2>&1
echo "engagement_state list (registry scan): $(ms "$t0") ms"

t0=$(date +%s%N)
find "$HOME/.claude/plugins/cache" "$HOME/.claude/plugins/marketplaces" \
  -name team-operating-guide.md >/dev/null 2>&1
echo "PLUGIN_ROOT find fallback: $(ms "$t0") ms"

echo
echo "=== hook spawn overhead (one Bash tool call fires each PreToolUse hook) ==="
t0=$(date +%s%N)
python3 -c "print(1)" >/dev/null 2>&1
echo "bare python3 startup (proxy for one guard-hook spawn): $(ms "$t0") ms"
echo "  x5 hooks currently wired on Bash => roughly 5x this number per Bash call"

echo
echo "Paste this whole output back - the single largest number is almost certainly"
echo "the actual cause, and fixing that one thing is the whole job."
