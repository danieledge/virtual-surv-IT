#!/bin/bash
# Review/perf tooling probe - now CACHED, so a static environment isn't re-probed on every
# engagement. Morgan knows which analysers are installed and SKIPs the missing ones for the rest
# of the session instead of re-invoking tools that aren't there.
#
#   bash scripts/check-review-tools.sh            # serve a fresh cache if present, else probe + cache
#   bash scripts/check-review-tools.sh --refresh  # force a re-probe (run after changing your toolchain)
#
# Cache file:  .claude/.tool-availability   (override with CST_TOOLCHECK_CACHE)
# Freshness:   CST_TOOLCHECK_TTL_DAYS days  (default 7); older -> re-probe automatically.
# Prints a present/missing table + an install hint per missing tool. Exit code is always 0
# (this is a report, not a gate). The cache holds only tool-presence booleans - no secrets.
set -uo pipefail

CACHE="${CST_TOOLCHECK_CACHE:-.claude/.tool-availability}"
TTL_DAYS="${CST_TOOLCHECK_TTL_DAYS:-7}"
REFRESH=0
case "${1:-}" in --refresh | --force) REFRESH=1 ;; esac

# Serve from cache when it's fresh and a refresh wasn't requested.
if [ "$REFRESH" -eq 0 ] && [ -f "$CACHE" ] && [ -n "$(find "$CACHE" -mtime "-${TTL_DAYS}" 2>/dev/null)" ]; then
  cat "$CACHE"
  echo
  echo "(cached - from a probe within the last ${TTL_DAYS} day(s); re-run with --refresh after"
  echo " installing or removing analysers.)"
  exit 0
fi

# tool | language/role | install hint
TOOLS=(
  "ruff|Python lint/style|pip install -r requirements-review.txt"
  "mypy|Python types|pip install -r requirements-review.txt"
  "bandit|Python security|pip install -r requirements-review.txt"
  "black|Python format|pip install -r requirements-review.txt"
  "pip-audit|Python deps CVEs|pip install -r requirements-review.txt"
  "semgrep|multi-lang security|pip install -r requirements-review.txt"
  "gitleaks|secret scan|apt/brew install gitleaks"
  "shellcheck|Bash lint|apt install shellcheck"
  "shfmt|Bash format|go install mvdan.cc/sh/v3/cmd/shfmt@latest"
  "scalafmt|Scala format|coursier install scalafmt"
  "checkstyle|Java style|via Maven/Gradle or brew/apt"
  "pmd|Java static analysis|via Maven/Gradle or brew/apt"
  "spotbugs|Java bugs/security|via Maven/Gradle or brew/apt"
  "pwsh|PowerShell + PSScriptAnalyzer|install PowerShell, then Install-Module PSScriptAnalyzer"
)
# NOTE: profilers/benchmarks (py-spy, scalene, hyperfine, cProfile, Measure-Command, JMH) are
# intentionally NOT listed - the team is STATIC-ONLY for now (it does not execute reviewed code,
# CLAUDE.md §7). Re-add them here if/when measured profiling is re-enabled via the consent flow.

present=()
missing=()
for entry in "${TOOLS[@]}"; do
  IFS='|' read -r bin role hint <<<"$entry"
  if command -v "$bin" >/dev/null 2>&1; then
    present+=("$bin ($role)")
  else
    missing+=("$bin - $role  →  $hint")
  fi
done

# Build the report once, then both cache and print it.
report="$(
  echo "=== Review/perf tooling check ==="
  echo "Checked: $(date '+%Y-%m-%d %H:%M')"
  echo
  echo "✅ Installed (${#present[@]}):"
  if [ "${#present[@]}" -eq 0 ]; then echo "   (none)"; else printf '   - %s\n' "${present[@]}"; fi
  echo
  echo "⚠️  Missing (${#missing[@]}) - reviews still run but degrade to inference-only (🧠) for these:"
  if [ "${#missing[@]}" -eq 0 ]; then echo "   (none - full tool-backed 📊 coverage)"; else printf '   - %s\n' "${missing[@]}"; fi
  echo
  echo "Note: Morgan records this once and skips the missing tools for the rest of the session"
  echo "(does not re-invoke them). Install the ones you care about for measured (📊) findings."
)"

# Cache it (best-effort; never fail the report if the cache can't be written).
if mkdir -p "$(dirname "$CACHE")" 2>/dev/null; then
  printf '%s\n' "$report" >"$CACHE" 2>/dev/null || true
fi

printf '%s\n' "$report"
exit 0
