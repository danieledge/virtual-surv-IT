#!/usr/bin/env bash
# Claude Code statusLine for the compliance-surveillance team (0.33.7).
#
# Shows Morgan's state at ZERO context cost (a statusline is a shell render, not a model
# turn): dormant sessions show that plainly; while an engagement is live it names the
# ACTIVE slug, its status and phase. Every render also shows the project's docx/citations/
# model preferences (same three /preferences and /engage's banner show), so they're visible
# without asking. Reads the statusLine stdin JSON (model, cost, workspace) plus the on-disk
# engagement state and team-preferences.json/settings.json; never talks to the model.
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
PY_BIN=""
for c in python3 python py; do
  "$c" --version >/dev/null 2>&1 && PY_BIN="$c" && break
done
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
# same three settings /preferences and /engage's banner show).
prefs = {}
try:
    prefs = json.loads((Path(cwd) / ".claude" / "team-preferences.json").read_text(encoding="utf-8"))
except Exception:
    pass
docx_on = "docx" in (prefs.get("extra_formats") or [])
citations_on = prefs.get("regulatory_citations", True)
morgan_model = ""
try:
    settings = json.loads((Path(cwd) / ".claude" / "settings.json").read_text(encoding="utf-8"))
    morgan_model = settings.get("model") or ""
except Exception:
    pass
bits.append(f"docx:{'on' if docx_on else 'off'} cite:{'on' if citations_on else 'off'} morgan:{morgan_model or 'default'}")

if model:
    bits.append(model)
if isinstance(cost, (int, float)) and cost > 0:
    bits.append(f"${cost:.2f}")
print(" | ".join(bits))
PY
