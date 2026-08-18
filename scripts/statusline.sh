#!/usr/bin/env bash
# Claude Code statusLine for the compliance-surveillance team (0.33.7).
#
# Shows Morgan's state at ZERO context cost (a statusline is a shell render, not a model
# turn): dormant sessions show that plainly; while an engagement is live it names the
# ACTIVE slug, its status and phase. Every render also shows the project's docx/citations/
# review-split/map-skeleton preferences plus Morgan's own configured model (the same four
# preferences + model /preferences shows; /engage's banner surfaces the same set but stays
# silent on review-split when it's off, since that one is a reliability workaround, not an
# output choice - docs/internal/large-context-review-splitting-plan.md), so they're visible
# without asking. Reads the statusLine stdin JSON (model, cost, workspace) plus the on-disk
# engagement state and team-preferences.json/settings.json/installer.json; never talks to
# the model.
#
# Wire (HUMAN-run - settings edits are human-only, ADR-002 rec 5):
#   bash scripts/apply-statusline.sh
set -u

INPUT=$(cat 2>/dev/null || true)

# Resolve the interpreter like run-guard.sh does - Windows (Git Bash) has python or the
# py launcher, rarely python3; a hardcoded python3 degraded the whole line to the static
# fallback there (2026-07-30 fix).
#
# `command -v` only checks that a name resolves on PATH - it does not run the binary. On
# Windows, "python3" often resolves to the Microsoft Store execution-alias stub, which
# exists on PATH but exits 49 without launching a real interpreter; command -v still
# reported it as found, so PY_BIN latched onto the stub, the heredoc below silently
# failed, and every render fell to the static fallback (live corp report 2026-07-31 -
# the 2026-07-30 fix above only addressed the encoding, not this stub-detection gap).
# `--version` actually invokes the binary, so the stub's exit 49 correctly skips it.
#
# Cache the resolved interpreter (2026-08-03 perf audit), same file run-guard.sh already
# writes: a statusline renders far more often than any single hook fires (every turn, often
# every UI refresh), so re-EXECUTING each candidate's --version on every render repeats the
# exact multi-second Windows Store-stub hang run-guard.sh's own cache exists to avoid.
# `command -v` on the cached name is cheap and safe to redo every time; only the EXECUTION
# probe below needs to happen once per session and be trusted after (same trust model as
# run-guard.sh: a cache hit is never re-version-checked).
PY_BIN=""
CACHE="${CLAUDE_PROJECT_DIR:-.}/.claude/.guard-interpreter"
if [ -f "$CACHE" ]; then
  cached=$(cat "$CACHE" 2>/dev/null)
  if [ -n "$cached" ] && command -v "$cached" >/dev/null 2>&1; then
    PY_BIN="$cached"
  fi
fi
if [ -z "$PY_BIN" ]; then
  for c in python3 python py; do
    "$c" --version >/dev/null 2>&1 && PY_BIN="$c" && break
  done
  if [ -n "$PY_BIN" ]; then
    mkdir -p "$(dirname "$CACHE")" 2>/dev/null
    printf '%s' "$PY_BIN" >"$CACHE" 2>/dev/null
  fi
fi
[ -z "$PY_BIN" ] && { printf '😴 Morgan dormant'; exit 0; }

# PYTHONUTF8: on Windows, Python encodes piped stdout with the locale codepage
# (cp1252), so printing the emoji marks raised UnicodeEncodeError and every render
# fell to the static fallback - glasses, no stats (live report 2026-07-30).
PYTHONUTF8=1 PYTHONIOENCODING=utf-8 "$PY_BIN" - "$INPUT" 2>/dev/null <<'PY' || printf '😴 Morgan dormant'
import json, sys
from pathlib import Path

try:
    data = json.loads(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1] else {}
except Exception:
    data = {}

model = (data.get("model") or {}).get("display_name") or ""
cost = (data.get("cost") or {}).get("total_cost_usd")
cwd = (data.get("workspace") or {}).get("project_dir") or data.get("cwd") or "."
bits = []

MARKS = {"in_progress": "⏳", "blocked": "⛔", "closing": "🔒", "closed": "✅"}
art = Path(cwd) / "artifacts"
live = None
if art.is_dir():
    packs = []
    state = art / "engagement-state.json"
    if state.is_file():
        packs.append(("(flat)", state))
    try:
        packs += [(p.name, p / "engagement-state.json") for p in sorted(art.iterdir())
                  if p.is_dir() and (p / "engagement-state.json").is_file()
                  and not (p / ".archive").is_file()]  # archived = out of play (0.33.2)
    except OSError:
        pass
    active = None
    try:
        active = json.loads((art / ".active-engagement.json").read_text()).get("slug")
    except Exception:
        pass
    rows = []
    for name, sf in packs:
        try:
            st = json.loads(sf.read_text(encoding="utf-8"))
        except Exception:
            continue
        status = st.get("status")
        if status in ("in_progress", "blocked", "closing"):
            rows.append((name, status, st.get("phase") or ""))
    if rows:
        pick = next((r for r in rows if r[0] == active), rows[0])
        name, status, phase = pick
        label = "" if name == "(flat)" else f"{name} "
        more = f" +{len(rows) - 1}" if len(rows) > 1 else ""
        live = f"🎩 Morgan active - {label}{MARKS.get(status, status)} {status}·{phase}{more}"

bits.append(live if live else "😴 Morgan dormant")

# Preferences (project-wide; independent of whether an engagement is currently open -
# same four settings /preferences shows; always-shown here regardless of state, unlike
# /engage's banner which stays silent on review-split when it's off).
prefs = {}
try:
    prefs = json.loads((Path(cwd) / ".claude" / "team-preferences.json").read_text(encoding="utf-8"))
except Exception:
    pass
docx_on = "docx" in (prefs.get("extra_formats") or [])
citations_on = prefs.get("regulatory_citations", True)
split_on = prefs.get("large_context_review_split", False)


def _project_or_machine_default(key, machine_key, builtin_default):
    """Key-presence-wins-else-machine-else-builtin - the same 3-tier precedence
    engage_probe.py and check_artifacts.py already use for map_skeleton (ADR-007 Phase 1
    Chunk D), now shared by statusline_show_map too. A statusline is a shell render (no
    model context), so this is a small, self-contained re-derivation rather than an import -
    same rationale as every other standalone-runnability note in this codebase."""
    if key in prefs:
        return bool(prefs[key])
    try:
        import os

        xdg = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
        installer_cfg = json.loads(
            (Path(xdg) / "virt-surv-it" / "installer.json").read_text(encoding="utf-8")
        )
        return bool(installer_cfg.get(machine_key, builtin_default))
    except Exception:
        return builtin_default


map_skeleton_on = _project_or_machine_default("map_skeleton", "default_map_skeleton", False)
# statusline_show_map is its OWN off-by-default preference (separate from map_skeleton
# itself) - a project can have drift-checking on without a longer statusline, since not
# every project wants the extra field just because the underlying toggle happens to be on.
statusline_show_map = _project_or_machine_default(
    "statusline_show_map", "default_statusline_show_map", False
)
morgan_model = ""
try:
    settings = json.loads((Path(cwd) / ".claude" / "settings.json").read_text(encoding="utf-8"))
    morgan_model = settings.get("model") or ""
except Exception:
    pass
pref_line = (
    f"docx:{'on' if docx_on else 'off'} cite:{'on' if citations_on else 'off'} "
    f"split:{'on' if split_on else 'off'}"
)
if statusline_show_map:
    pref_line += f" map:{'on' if map_skeleton_on else 'off'}"
pref_line += f" morgan:{morgan_model or 'default'}"
bits.append(pref_line)

if model:
    bits.append(model)
if isinstance(cost, (int, float)) and cost > 0:
    bits.append(f"${cost:.2f}")
print(" | ".join(bits))
PY
