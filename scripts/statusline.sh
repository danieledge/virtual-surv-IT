#!/usr/bin/env bash
# Claude Code statusLine for the compliance-surveillance team (0.33.1).
#
# Shows the team's state at ZERO context cost (a statusline is a shell render, not a model
# turn): dormant sessions show the model + cost as usual; while an engagement is live it
# names the ACTIVE slug, its status and phase. Reads the statusLine stdin JSON (model,
# cost, workspace) plus the on-disk engagement state; never talks to the model.
#
# Wire (HUMAN-run - settings edits are human-only, ADR-002 rec 5):
#   bash scripts/apply-statusline.sh
set -u

INPUT=$(cat 2>/dev/null || true)

# Resolve the interpreter like run-guard.sh does - Windows (Git Bash) has python or the
# py launcher, rarely python3; a hardcoded python3 degraded the whole line to the static
# fallback there (2026-07-30 fix).
PY_BIN=""
for c in python3 python py; do
  command -v "$c" >/dev/null 2>&1 && PY_BIN="$c" && break
done
[ -z "$PY_BIN" ] && { printf '🕶 virt-surv-IT'; exit 0; }

# PYTHONUTF8: on Windows, Python encodes piped stdout with the locale codepage
# (cp1252), so printing the emoji marks raised UnicodeEncodeError and every render
# fell to the static fallback - glasses, no stats (live report 2026-07-30).
PYTHONUTF8=1 PYTHONIOENCODING=utf-8 "$PY_BIN" - "$INPUT" 2>/dev/null <<'PY' || printf '🕶 virt-surv-IT'
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
        live = f"🎩 {label}{MARKS.get(status, status)} {status}·{phase}{more}"

bits.append(live if live else "🕶 team dormant")
if model:
    bits.append(model)
if isinstance(cost, (int, float)) and cost > 0:
    bits.append(f"${cost:.2f}")
print(" | ".join(bits))
PY
