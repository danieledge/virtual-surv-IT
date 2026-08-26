#!/bin/bash
# Review/perf tooling probe - now CACHED, so a static environment isn't re-probed on every
# engagement. Morgan knows which analysers are installed and SKIPs the missing ones for the rest
# of the session instead of re-invoking tools that aren't there.
#
#   bash scripts/check-review-tools.sh            # serve a fresh cache if present, else probe + cache
#   bash scripts/check-review-tools.sh --refresh  # force a re-probe (run after changing your toolchain)
#   bash scripts/check-review-tools.sh --verbose  # fresh probe, FULL report (roles + install hints)
#
# Cache file:  .claude/.tool-availability   (override with CST_TOOLCHECK_CACHE)
# Freshness:   CST_TOOLCHECK_TTL_DAYS days  (default 7); older -> re-probe automatically.
# Default output is the COMPACT report (names + counts - what the probe/banner actually
# consume; token audit Track C, 2026-08-18: the full per-tool hint list re-served ~1.6KB
# into every engagement open while the prompts consume only counts + missing names). The
# full human-facing report with roles and install hints lives behind --verbose. The cache
# always holds the compact form. Exit code is always 0 (this is a report, not a gate).
# The cache holds only tool-presence booleans - no secrets.
set -uo pipefail

CACHE="${CST_TOOLCHECK_CACHE:-.claude/.tool-availability}"
TTL_DAYS="${CST_TOOLCHECK_TTL_DAYS:-7}"
REFRESH=0
VERBOSE=0
case "${1:-}" in
  --refresh | --force) REFRESH=1 ;;
  --verbose) REFRESH=1 VERBOSE=1 ;;
esac

# Allow-list presence - computed FRESH on every run (both cache paths), never cached: the
# user may add it minutes after being tipped, and a stale "missing" would nag for the TTL.
# Marker: the scripts wildcard from the recommended set (install_helper.py
# RECOMMENDED_ALLOW). Detection only - this script never edits settings (ADR-002 rec 5).
allowlist_line() {
  if [ -f ".claude/settings.json" ] && grep -q 'python3\? -m scripts\.\*' ".claude/settings.json" 2>/dev/null; then
    echo "ALLOWLIST: present"
  else
    echo "ALLOWLIST: missing - fewer permission prompts if added; the user runs:"
    echo "  python <clone>/install_helper.py --permissions ."
  fi
}

# Serve from cache when it's fresh and a refresh wasn't requested.
if [ "$REFRESH" -eq 0 ] && [ -f "$CACHE" ] && [ -n "$(find "$CACHE" -mtime "-${TTL_DAYS}" 2>/dev/null)" ]; then
  cat "$CACHE"
  echo
  echo "(cached, <${TTL_DAYS}d - refresh with --refresh after installing/removing analysers; hints: --verbose)"
  allowlist_line
  exit 0
fi

# The seven officially supported, individually on/off/auto-configurable analysers
# (2026-08-04) - the ones proven (install_helper.py's _TOOL_OUTPUT_CHECKS) to run
# single-file, dependency-free and network-free, the same bar semgrep/pip-audit failed.
# Keep in sync with install_helper.py's _REVIEW_TOOLS.
REVIEW_TOOLS=(ruff mypy bandit gitleaks sqlfluff black shfmt)

# Effective state for a supported tool: the CST_NO_EXTERNAL_TOOLS kill switch (strongest,
# set by a human/security team in the launch environment - disables every analyser below,
# supported or not) beats the PROJECT's own .claude/team-preferences.json "review_tools"
# override, which beats this MACHINE's installer-wide default
# (~/.config/virt-surv-it/installer.json "default_review_tools", or
# $XDG_CONFIG_HOME/virt-surv-it/installer.json - set once via install_helper.py, applies
# to every project on this machine unless a project overrides it), which beats the
# implicit "auto" (use if present, skip silently if not - unchanged existing behaviour).
# One python3 call resolves all seven at once rather than one per tool - python3 is
# already a hard dependency of this plugin (the guard hooks require it).
review_tool_states() {
  if [ -n "${CST_NO_EXTERNAL_TOOLS:-}" ]; then
    for t in "${REVIEW_TOOLS[@]}"; do echo "$t=off"; done
    return
  fi
  python3 - << 'PYEOF' 2>/dev/null
import json, os

REVIEW_TOOLS = ("ruff", "mypy", "bandit", "gitleaks", "sqlfluff", "black", "shfmt")


def load(path):
    try:
        with open(path, encoding="utf-8-sig") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


project = load(os.path.join(".claude", "team-preferences.json")).get("review_tools") or {}
cfg_home = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
installer = load(os.path.join(cfg_home, "virt-surv-it", "installer.json")).get("default_review_tools") or {}
for t in REVIEW_TOOLS:
    print(f"{t}={project.get(t) or installer.get(t) or 'auto'}")
PYEOF
}
review_tool_state_for() {
  # $1 = tool name; prints its resolved state, "auto" if the resolver produced nothing
  # (e.g. python3 unavailable) - fails toward existing presence-only behaviour, never
  # toward silently disabling a tool nobody asked to disable.
  local wanted="$1"
  while IFS='=' read -r name state; do
    if [ "$name" = "$wanted" ]; then
      echo "$state"
      return
    fi
  done <<<"$REVIEW_TOOL_STATES_CACHE"
  echo "auto"
}
REVIEW_TOOL_STATES_CACHE="$(review_tool_states)"

# tool | language/role | install hint
# pip-audit and semgrep deliberately NOT probed (2026-08-04): both make unconditional
# network calls with no reliable offline mode found - live corp-proxy reports showed them
# hanging rather than failing fast, both in real reviews and in this probe itself. Not
# listed here at all so they never show as "available" and never get invoked, even if
# installed. See code-reviewer.md for the full removal rationale.
TOOLS=(
  "ruff|Python lint/style|pip install -r requirements-review.txt"
  "mypy|Python types|pip install -r requirements-review.txt"
  "bandit|Python security|pip install -r requirements-review.txt"
  "black|Python format|pip install -r requirements-review.txt"
  "gitleaks|secret scan|apt/brew install gitleaks"
  "shellcheck|Bash lint|apt install shellcheck"
  "shfmt|Bash format|go install mvdan.cc/sh/v3/cmd/shfmt@latest"
  "bashate|Bash style|pip install bashate"
  "eslint|TypeScript/JS lint|npm install -g eslint"
  "tsc|TypeScript types|npm install -g typescript"
  "sqlfluff|SQL lint|pip install sqlfluff"
  "scalafmt|Scala format|coursier install scalafmt"
  "checkstyle|Java style|via Maven/Gradle or brew/apt"
  "pmd|Java static analysis|via Maven/Gradle or brew/apt"
  "spotbugs|Java bugs/security|via Maven/Gradle or brew/apt"
  "pwsh|PowerShell + PSScriptAnalyzer|install PowerShell, then Install-Module PSScriptAnalyzer"
  "ast-grep|structural multi-lang search (find-all-implementations/callers by AST pattern)|brew/cargo/npm install ast-grep, or https://ast-grep.github.io/guide/quick-start.html"
)
# NOTE: profilers/benchmarks (py-spy, scalene, hyperfine, cProfile, Measure-Command, JMH) are
# intentionally NOT listed - the team is STATIC-ONLY for now (it does not execute reviewed code,
# CLAUDE.md §7). Re-add them here if/when measured profiling is re-enabled via the consent flow.

present=()
present_names=()
missing=()
missing_names=()
disabled=()
disabled_names=()
required_missing=()
for entry in "${TOOLS[@]}"; do
  IFS='|' read -r bin role hint <<<"$entry"
  state="auto"
  for rt in "${REVIEW_TOOLS[@]}"; do
    [ "$bin" = "$rt" ] && state="$(review_tool_state_for "$bin")" && break
  done
  if [ "$state" = "off" ]; then
    disabled+=("$bin ($role) - disabled by config, not probed")
    disabled_names+=("$bin")
    continue
  fi
  if command -v "$bin" >/dev/null 2>&1; then
    present+=("$bin ($role)")
    present_names+=("$bin")
  elif [ "$state" = "on" ]; then
    required_missing+=("$bin - $role  →  $hint  (config requires this tool 'on')")
  else
    missing+=("$bin - $role  →  $hint")
    missing_names+=("$bin")
  fi
done

# Comma-join helper for the compact report's name lists.
join_names() {
  local out="" item
  for item in "$@"; do
    if [ -z "$out" ]; then out="$item"; else out="$out, $item"; fi
  done
  echo "$out"
}

# Artifact-renderer libraries (Python, not CLI binaries - a single import probe, not
# command -v). Checked here so a missing renderer is known BEFORE Morgan attempts a
# render, not discovered as a failed tool call mid-engagement (each failed attempt is a
# wasted round-trip). Cached with everything else on this same TTL.
renderers=()
render_missing=()
codeintel=()
codeintel_missing=()
for c in python3 python py; do
  command -v "$c" >/dev/null 2>&1 && PY_PROBE="$c" && break
done
if [ -n "${PY_PROBE:-}" ]; then
  if "$PY_PROBE" -c "import markdown, bleach" >/dev/null 2>&1; then
    renderers+=("markdown+bleach (.html export)")
  else
    render_missing+=(".html export (markdown+bleach)  →  pip install -r requirements-dev.txt")
  fi
  if "$PY_PROBE" -c "import docx" >/dev/null 2>&1; then
    renderers+=("python-docx (.docx export)")
  else
    render_missing+=(".docx export (python-docx)  →  pip install -r requirements-dev.txt")
  fi
  # Code intelligence (2026-08-27). Same reasoning as the renderer probe directly above,
  # and the same reason it belongs HERE rather than in a script of its own: this is the
  # existing tool probe, its result is already cached on this TTL, and Morgan already reads
  # it at engagement open. A second probe would mean a second cache, a second staleness
  # rule, and two places to ask one question.
  #
  # It PARSES, rather than merely importing. An import succeeding proves nothing on a
  # machine where policy blocks the compiled extension from loading - that distinction is
  # exactly what the corporate-box measurement turned on - so the probe parses a sample.
  # timeout, if the host has one: this runs at engagement open on a cold cache, and a
  # probe that wedges there wedges the open. The <1.0 pin removes the runtime-download
  # path that could hang, so this is a backstop rather than the fix.
  if _ts_probe_cmd=("$PY_PROBE" -c "from tree_sitter_language_pack import get_parser; get_parser('python').parse(b'x = 1')") &&
     { command -v timeout >/dev/null 2>&1 && timeout 20 "${_ts_probe_cmd[@]}" >/dev/null 2>&1 ||
       { ! command -v timeout >/dev/null 2>&1 && "${_ts_probe_cmd[@]}" >/dev/null 2>&1; }; }; then
    codeintel+=("tree-sitter (exact symbols + line ranges, ~15 languages)")
  else
    codeintel_missing+=("tree-sitter  →  python install_helper.py --code-intel  (orientation falls back to pattern matching; nothing breaks)")
  fi
fi

# Build the COMPACT report (default output + what gets cached): names and counts only -
# every consumer (probe banner, dashboard's Installed/Missing regexes, the reviewers'
# skip-missing rule) uses exactly this; roles and install hints are --verbose material.
report="$(
  echo "=== Review/perf tooling check ==="
  echo "Checked: $(date '+%Y-%m-%d %H:%M')"
  echo
  if [ "${#present_names[@]}" -eq 0 ]; then
    echo "✅ Installed (0): (none)"
  else
    echo "✅ Installed (${#present_names[@]}): $(join_names "${present_names[@]}")"
  fi
  if [ "${#missing_names[@]}" -eq 0 ]; then
    echo "⚠️  Missing (0): none - full tool-backed 📊 coverage"
  else
    echo "⚠️  Missing (${#missing_names[@]}) - reviews still run but degrade to inference-only (🧠) for these: $(join_names "${missing_names[@]}")"
    echo "   (install hints: bash scripts/check-review-tools.sh --verbose)"
  fi
  if [ "${#required_missing[@]}" -gt 0 ]; then
    echo "❌ Required by config but not installed (${#required_missing[@]}):"
    printf '   - %s\n' "${required_missing[@]}"
  fi
  if [ "${#disabled_names[@]}" -gt 0 ]; then
    echo "⏭  Disabled by config (${#disabled_names[@]}): $(join_names "${disabled_names[@]}")"
  fi
  if [ -n "${CST_NO_EXTERNAL_TOOLS:-}" ]; then
    echo "🔒 CST_NO_EXTERNAL_TOOLS is set - all seven supported analysers treated as disabled"
    echo "   (best-effort, unsupported analysers are unaffected by this switch)."
  fi
  echo "Artifact renderers:"
  if [ "${#renderers[@]}" -gt 0 ]; then printf '   ✅ %s\n' "${renderers[@]}"; fi
  if [ "${#render_missing[@]}" -gt 0 ]; then printf '   ⚠️  %s\n' "${render_missing[@]}"; fi
  echo "Code intelligence:"
  if [ "${#codeintel[@]}" -gt 0 ]; then printf '   ✅ %s\n' "${codeintel[@]}"; fi
  if [ "${#codeintel_missing[@]}" -gt 0 ]; then printf '   ⚠️  %s\n' "${codeintel_missing[@]}"; fi
)"

# Cache the compact form (best-effort; never fail the report if the cache can't be written).
if mkdir -p "$(dirname "$CACHE")" 2>/dev/null; then
  printf '%s\n' "$report" >"$CACHE" 2>/dev/null || true
fi

if [ "$VERBOSE" -eq 1 ]; then
  # Full human-facing report: roles + an install hint per missing tool.
  echo "=== Review/perf tooling check (verbose) ==="
  echo "Checked: $(date '+%Y-%m-%d %H:%M')"
  echo
  echo "✅ Installed (${#present[@]}):"
  if [ "${#present[@]}" -eq 0 ]; then echo "   (none)"; else printf '   - %s\n' "${present[@]}"; fi
  echo
  echo "⚠️  Missing (${#missing[@]}) - reviews still run but degrade to inference-only (🧠) for these:"
  if [ "${#missing[@]}" -eq 0 ]; then echo "   (none - full tool-backed 📊 coverage)"; else printf '   - %s\n' "${missing[@]}"; fi
  echo
  if [ "${#required_missing[@]}" -gt 0 ]; then
    echo "❌ Required by config but not installed (${#required_missing[@]}):"
    printf '   - %s\n' "${required_missing[@]}"
    echo
  fi
  if [ "${#disabled[@]}" -gt 0 ]; then
    echo "⏭  Disabled by config (${#disabled[@]}):"
    printf '   - %s\n' "${disabled[@]}"
    echo
  fi
  if [ -n "${CST_NO_EXTERNAL_TOOLS:-}" ]; then
    echo "🔒 CST_NO_EXTERNAL_TOOLS is set - all seven supported analysers above are treated"
    echo "   as disabled, regardless of team-preferences.json or the installer-wide default."
    echo "   (best-effort, unsupported analysers below are unaffected by this switch.)"
    echo
  fi
  echo "Artifact renderers:"
  if [ "${#renderers[@]}" -gt 0 ]; then printf '   ✅ %s\n' "${renderers[@]}"; fi
  if [ "${#render_missing[@]}" -gt 0 ]; then printf '   ⚠️  %s\n' "${render_missing[@]}"; fi
  echo "Code intelligence:"
  if [ "${#codeintel[@]}" -gt 0 ]; then printf '   ✅ %s\n' "${codeintel[@]}"; fi
  if [ "${#codeintel_missing[@]}" -gt 0 ]; then printf '   ⚠️  %s\n' "${codeintel_missing[@]}"; fi
else
  printf '%s\n' "$report"
fi

allowlist_line
exit 0
