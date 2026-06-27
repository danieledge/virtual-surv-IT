#!/bin/bash
# One-time review/perf tooling probe. Run ONCE per engagement (engage step 0) so Morgan
# knows which analysers/profilers are installed - and can then SKIP the missing ones for the
# rest of the session instead of re-invoking tools that aren't there.
#
#   bash scripts/check-review-tools.sh
#
# Prints a present/missing table and the install hint for each missing tool. Exit code is
# always 0 (this is a report, not a gate).
set -uo pipefail

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

present=() ; missing=()
for entry in "${TOOLS[@]}"; do
  IFS='|' read -r bin role hint <<<"$entry"
  if command -v "$bin" >/dev/null 2>&1; then
    present+=("$bin ($role)")
  else
    missing+=("$bin - $role  →  $hint")
  fi
done

echo "=== Review/perf tooling check ==="
echo
echo "✅ Installed (${#present[@]}):"
if [ "${#present[@]}" -eq 0 ]; then echo "   (none)"; else printf '   - %s\n' "${present[@]}"; fi
echo
echo "⚠️  Missing (${#missing[@]}) - reviews still run but degrade to inference-only (🧠) for these:"
if [ "${#missing[@]}" -eq 0 ]; then echo "   (none - full tool-backed 📊 coverage)"; else printf '   - %s\n' "${missing[@]}"; fi
echo
echo "Note: Morgan should record this once and skip the missing tools for the rest of the"
echo "session (do not re-invoke them). Install the ones you care about for measured (📊) findings."
exit 0
