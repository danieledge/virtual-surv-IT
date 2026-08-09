#!/usr/bin/env python3
"""
Local observability dashboard - a static HTML page generated from files already on disk.

WHY STATIC: everything runs and stays on the user's machine. No server, no port, no auth
surface - the output is a self-contained `dashboard.html` opened via file:// and refreshed
by re-running the script. This is deliberate (house rule: never serve sensitive paths from
a casual server) and honest: the data changes when engagements run, not continuously.

2026-07-31 rewrite: the previous version predated every capability built over the prior
two days and was archive-blind - it re-scanned and DoD-checked `.archive`-marked engagements
on every regen, defeating the point of archiving (0.33.2), and only aggregated one
artifact-count/gate-pass-fail number per PROJECT with no per-engagement breakdown. Two
audits (one by hand, one by an Explore agent) informed this version:

WHAT IT SHOWS NOW, per working project passed on the command line (default: cwd):
  - Project setup (configuration, not lifecycle): version + tracked git branch when
    knowable, team-preferences.json (docx export / regulatory citations), review-tool
    availability (cached probe), hook-wiring completeness (repo-as-project mode only -
    meaningless for a plugin-cache install, which is always fully wired), execution-consent
    marker state.
  - Per-ENGAGEMENT breakdown (archived engagements excluded from the live table, counted
    separately): slug, status, title, opened/closed + day-span, outstanding-item count,
    pending human ratifications, the recorded execution-consent outcome (asked/declined,
    distinct from the marker - a "No" leaves a trace even though the marker itself is
    absent), the settings snapshot recorded at open (2026-08-08), and a per-engagement
    timeline (2026-08-08, one click via <details>) built from `opened` -> each artifact's
    added date -> `log` entries (a `log-note --tag review-loop` note renders with a distinct
    icon - a "sent back to X" handoff) -> `closed`.
  - The mechanical DoD gate result, at FULL parity with `check_artifacts.py`'s own CLI (not
    a narrower hand-rolled subset): per-pack findings + registry staleness + root orphans +
    the ARCHIVED-OPEN safeguard (an archived pack that never actually closed).
  - Codebase-map presence and hygiene (ADR-003).
Plus, portfolio-wide (2026-08-08, across every known project - see auto-discovery below):
  - A contribution-style activity heatmap (engagement opens/closes + artifacts added).
  - A roster-involvement bar chart, tallying `team` across every known engagement.
  - An obligation-coverage map: every artifact's citations, scanned with
    `check_citations.find_citations()`/`check_text()` (the SAME matcher `check_citations`
    itself uses - no new parsing) against `config/regulatory-register.yaml`, tallied by
    obligation id and verified/unverified - 📊 observed, purely mechanical text-scanning.
Plus a cost panel: measured token usage AND measured ACTIVE session time (sum of
consecutive-message timestamp gaps under a 15-minute idle cap - NOT first-to-last span,
which would count a session left open for hours/days, a routine resume-later pattern, as
active work), parsed from the Claude Code session transcripts for those projects
(~/.claude/projects/<slug>/*.jsonl, 📊 measured, session-level) - kept deliberately
separate from and NOT summed with per-engagement `footprint` estimates or the coarse
open->close day-span above (🧠 inferred, date-granularity only) to avoid differently-sourced
numbers reading as a contradiction; footprint is left to each engagement's own START-HERE.md.

Auto-discovery note: with no project args, `discover_projects()` already unions every
project this machine has evidence the team ran in (Claude Code's own project config +
transcript fingerprinting) - this IS the cross-project portfolio view; no separate registry
file exists or is needed. Explicit project args still mean single/multi-project mode as
before.

LIMITS (stated on the page): sees only this machine; cost covers sessions whose transcripts
are still on disk; the dashboard is read-only by design - management actions stay deliberate
human acts in the terminal.

Usage: `python -m scripts.dashboard [project_dir ...] [--out dashboard.html | --json data.json]`
`--json` (2026-08-08) writes the data-only payload `dashboard-ui/` (a Vite/React app) builds
into the real, current UI - `emit_json()` is the frontend's ONLY data source, camelCase keys,
same in-memory structures `render()` already computes. `--out` (default, no Node required)
keeps rendering the original plain HTML page UNCHANGED - frozen as the no-Node fallback, not
under active visual development, but not deleted: cheap insurance.
This is a USER-run tool (open the output yourself); agents do not need to invoke it. The
`/dashboard` skill is the discoverable front door - it runs this with a portfolio-appropriate
`--out` under the Claude home rather than dropping a cross-project file into one project's
own tree.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import html
import json
import re
import sys
from pathlib import Path

try:  # repo-relative import (python -m scripts.dashboard) with a fallback for direct runs
    from scripts.check_artifacts import (
        archived_open_packs,
        check,
        check_map,
        check_registry,
        check_root_orphans,
        engagement_packs,
        find_codebase_map,
    )
except ImportError:  # pragma: no cover
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from scripts.check_artifacts import (
        archived_open_packs,
        check,
        check_map,
        check_registry,
        check_root_orphans,
        engagement_packs,
        find_codebase_map,
    )

try:
    from scripts.engagement_state import archived_slugs, scan_engagements
except ImportError:  # pragma: no cover
    from scripts.engagement_state import archived_slugs, scan_engagements

try:
    from scripts.engage_probe import git_branch
except ImportError:  # pragma: no cover
    from scripts.engage_probe import git_branch

try:
    from scripts.check_citations import _load_register, check_text
except ImportError:  # pragma: no cover
    from scripts.check_citations import _load_register, check_text

_E = html.escape

# The routine-wired hooks (scripts/apply-hooks.sh's own list) - meaningful only in
# repo-as-project mode, where wiring is a manual step; a plugin-cache install is always
# fully wired by definition (hooks/hooks.json ships pre-wired), so this check is skipped
# there entirely rather than showing a misleading "0/9".
_ROUTINE_HOOK_SCRIPTS = (
    "dod_stop_gate.py",
    "persona_anchor.py",
    "document_input_redirect.py",
    "session_resume_brief.py",
    "post_edit_lint.py",
    "module_form_redirect.py",
    "subagent_return_budget.py",
    "locked_menu_guard.py",
    "todo_panel_nudge.py",
)


# ---------------------------------------------------------------------------
# Data collection - project setup (configuration, not engagement lifecycle).
# ---------------------------------------------------------------------------
def plugin_cache_version(claude_home: Path) -> str | None:
    """The installed plugin's version from the central cache.

    Install topology matters here: `/plugin` clones the marketplace into the Claude home
    and the user then ENABLES it per project - so a plugin-mode working project carries no
    manifest of its own. Engagement state (artifacts, consent marker, codebase map) still
    lives in the working directory; only the version has to come from the cache.
    """
    try:
        for manifest in (claude_home / "plugins").rglob(".claude-plugin/plugin.json"):
            try:
                data = json.loads(manifest.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if data.get("name") == "compliance-surveillance-team":
                return data.get("version")
    except OSError:
        pass
    return None


def read_team_preferences(project: Path) -> dict:
    """`.claude/team-preferences.json` - docx export and regulatory citations, both
    opt-in/opt-out project-wide settings. Absent file reads as today's defaults (docx
    off, citations on), matching engage_probe.py's own interpretation exactly."""
    p = project / ".claude" / "team-preferences.json"
    try:
        data = json.loads(p.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    return {
        "docx": "docx" in (data.get("extra_formats") or []),
        "citations": data.get("regulatory_citations", True),
    }


_INSTALLED_RE = re.compile(r"✅ Installed \((\d+)\):")
_MISSING_RE = re.compile(r"Missing \((\d+)\)")


def read_tool_probe(project: Path) -> dict | None:
    """The cached review-tool probe (`.claude/.tool-availability`, written by
    check-review-tools.sh) - a plain-text report, parsed defensively by regex against its
    own known header lines rather than assuming a stricter format. None when no cache
    exists yet (never probed) - distinct from a 0/N cache, which means probed-and-empty."""
    p = project / ".claude" / ".tool-availability"
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
        age_days = (_dt.datetime.now().timestamp() - p.stat().st_mtime) / 86400
    except OSError:
        return None
    installed = _INSTALLED_RE.search(text)
    missing = _MISSING_RE.search(text)
    if not installed or not missing:
        return None
    n_installed = int(installed.group(1))
    total = n_installed + int(missing.group(1))
    return {"installed": n_installed, "total": total, "fresh": age_days <= 7}


def hook_wiring(project: Path) -> dict | None:
    """How many of the routine-wired hooks are present in THIS project's own
    .claude/settings.json - meaningful only in repo-as-project mode. None (not "0/9") for
    a plugin-cache install, which ships hooks/hooks.json pre-wired and has no per-project
    settings.json hook block of its own to check - showing 0/9 there would misreport a
    fully-wired install as broken."""
    settings_path = project / ".claude" / "settings.json"
    live_scripts_dir = project / "scripts"
    if not settings_path.is_file() or not (project / "hooks" / "hooks.json").is_file():
        return None  # not a repo-as-project checkout
    try:
        settings = json.loads(settings_path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
    hooks_cfg = settings.get("hooks") or {}
    blob = json.dumps(hooks_cfg)
    wired = sum(1 for name in _ROUTINE_HOOK_SCRIPTS if name in blob)
    installed = sum(1 for name in _ROUTINE_HOOK_SCRIPTS if (live_scripts_dir / name).is_file())
    return {"wired": wired, "installed": installed, "total": len(_ROUTINE_HOOK_SCRIPTS)}


# ---------------------------------------------------------------------------
# Data collection - per-engagement breakdown + the mechanical DoD gate.
# ---------------------------------------------------------------------------
def _engagement_extras(pack_dir: Path) -> dict:
    """Fields scan_engagements() doesn't carry: outstanding count, pending ratifications,
    the recorded (non-granting) execution-consent outcome, team roster, the artifact
    inventory (path/title/status/added), the settings snapshot recorded at open, and the
    raw log (source for the timeline). Best-effort - an unreadable state file yields
    all-zero/empty/None rather than breaking the row."""
    empty = {
        "outstanding": 0,
        "pending_ratifications": 0,
        "consent_outcome": None,
        "team": [],
        "artifacts": [],
        "settings_snapshot": None,
        "log": [],
    }
    try:
        state = json.loads((pack_dir / "engagement-state.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return empty
    outstanding = state.get("outstanding")
    ratifications = state.get("ratifications")
    outcome = state.get("execution_consent_outcome")
    team = state.get("team")
    artifacts = state.get("artifacts")
    log = state.get("log")
    settings_snapshot = state.get("settings_snapshot")
    return {
        "outstanding": len(outstanding) if isinstance(outstanding, list) else 0,
        "pending_ratifications": (
            sum(1 for r in ratifications if isinstance(r, dict) and r.get("status") == "pending")
            if isinstance(ratifications, list)
            else 0
        ),
        "consent_outcome": outcome.get("outcome") if isinstance(outcome, dict) else None,
        "team": team if isinstance(team, list) else [],
        "artifacts": artifacts if isinstance(artifacts, list) else [],
        "settings_snapshot": settings_snapshot if isinstance(settings_snapshot, dict) else None,
        "log": log if isinstance(log, list) else [],
    }


def engagement_rows(artifacts: Path) -> list[dict]:
    """Per-engagement breakdown, archived engagements excluded (scan_engagements already
    does this) - each row enriched with the extras scan_engagements doesn't carry."""
    if not artifacts.is_dir():
        return []
    rows = []
    for row in scan_engagements(artifacts):
        pack_dir = artifacts if row.get("dir") in (None, "(flat)") else artifacts / row["dir"]
        rows.append({**row, **_engagement_extras(pack_dir)})
    return rows


def gate_findings_for(artifacts: Path) -> list[str]:
    """Full parity with check_artifacts.py's own CLI main(): per-pack findings (archive-
    aware via engagement_packs, NOT the archive-blind workspace_dirs the pre-2026-07-31
    version used) + registry staleness + root orphans + the ARCHIVED-OPEN safeguard. The
    previous version only ever called per-pack check() - registry/orphan/archived-open
    findings were silently absent from the dashboard's gate column even though the CLI
    itself has always checked them. Read-only: create_snapshot=False, this is a viewer."""
    if not artifacts.is_dir():
        return []
    packs = engagement_packs(artifacts)
    findings: list[str] = []
    if packs:
        for p in packs:
            findings.extend(f"[{p.name}] {f}" for f in check(p))
        if (artifacts / "engagement-state.json").is_file():
            findings.append(
                "FLAT-PACK-UNMIGRATED: legacy flat pack coexists with workspaces - run "
                "`python -m scripts.engagement_state migrate`"
            )
        else:
            findings.extend(check_root_orphans(artifacts, create_snapshot=False))
        findings.extend(check_registry(artifacts))
    else:
        findings.extend(check(artifacts))
    findings.extend(archived_open_packs(artifacts))
    return findings


def project_summary(project: Path) -> dict:
    """Facts about one working project, all from files on disk. Read-only throughout."""
    artifacts = project / "artifacts"
    emails = sorted(artifacts.rglob("engagement-summary-*.txt")) if artifacts.is_dir() else []
    engagements = engagement_rows(artifacts)
    archived = archived_slugs(artifacts) if artifacts.is_dir() else []
    gate = gate_findings_for(artifacts)
    map_path = find_codebase_map(project)
    map_findings = check_map(map_path) if map_path else None

    version = None
    manifest = project / ".claude-plugin" / "plugin.json"
    if manifest.is_file():
        try:
            version = json.loads(manifest.read_text(encoding="utf-8")).get("version")
        except (OSError, ValueError):
            version = "unreadable"
    branch = git_branch(project) or None

    return {
        "path": project,
        "name": project.name,
        "version": version,
        "branch": branch,
        "preferences": read_team_preferences(project),
        "tool_probe": read_tool_probe(project),
        "hook_wiring": hook_wiring(project),
        "engagements": engagements,
        "archived_count": len(archived),
        "emails": emails,  # list[Path] - render() only ever calls len() on this; emit_json()
        # needs the full paths to link each one (2026-08-08, dashboard-ui clickable-artifacts).
        "gate_findings": gate,
        "consent_open": (project / ".claude" / ".exec-consent").is_file(),
        "map_path": map_path,
        "map_findings": map_findings,
    }


def _walk_message_usage(obj) -> tuple[dict, str | None] | None:
    """Find a (usage, model) pair anywhere in a JSON object - model is the sibling `model`
    field on the same message dict that carries `usage` (Claude Code transcripts nest both
    under `message: {model, usage}`), so it has to be read alongside usage, not from inside
    it. Same tolerant recursive-search rationale as the original _walk_usage: the transcript
    schema is internal and has moved before. First match wins (one usage block per assistant
    message)."""
    if isinstance(obj, dict):
        usage = obj.get("usage")
        if isinstance(usage, dict) and ("input_tokens" in usage or "output_tokens" in usage):
            return usage, obj.get("model")
        for value in obj.values():
            found = _walk_message_usage(value)
            if found:
                return found
    elif isinstance(obj, list):
        for value in obj:
            found = _walk_message_usage(value)
            if found:
                return found
    return None


def _walk_usage(obj) -> dict | None:
    """Usage-only view of _walk_message_usage, kept for callers that don't need the model."""
    found = _walk_message_usage(obj)
    return found[0] if found else None


# $ per 1M tokens: (input, output, cache_write_5m, cache_write_1h, cache_read). Cached
# pricing snapshot (2026-08-08, via the claude-api skill) - Claude Sonnet 5's introductory
# rate ($2/$10 through 2026-08-31) is deliberately NOT used here; the standard list rate
# ($3/$15) keeps historical cost figures stable once the intro window ends rather than
# having every past session's $ total silently shift on that date.
_MODEL_PRICING_PER_MTOK: dict[str, tuple[float, float, float, float, float]] = {
    "claude-opus-5": (5.00, 25.00, 6.25, 10.00, 0.50),
    "claude-opus-4-8": (5.00, 25.00, 6.25, 10.00, 0.50),
    "claude-opus-4-7": (5.00, 25.00, 6.25, 10.00, 0.50),
    "claude-opus-4-6": (5.00, 25.00, 6.25, 10.00, 0.50),
    "claude-opus-4-5": (5.00, 25.00, 6.25, 10.00, 0.50),
    "claude-opus-4-1": (5.00, 25.00, 6.25, 10.00, 0.50),
    "claude-opus-4-0": (5.00, 25.00, 6.25, 10.00, 0.50),
    "claude-sonnet-5": (3.00, 15.00, 3.75, 6.00, 0.30),
    "claude-sonnet-4-6": (3.00, 15.00, 3.75, 6.00, 0.30),
    "claude-sonnet-4-5": (3.00, 15.00, 3.75, 6.00, 0.30),
    "claude-sonnet-4-0": (3.00, 15.00, 3.75, 6.00, 0.30),
    "claude-haiku-4-5": (1.00, 5.00, 1.25, 2.00, 0.10),
    "claude-fable-5": (10.00, 50.00, 12.50, 20.00, 1.00),
    "claude-mythos-5": (10.00, 50.00, 12.50, 20.00, 1.00),
}


def _price_usage(model: str | None, usage: dict) -> float | None:
    """Dollar cost of one message's usage at current list pricing. Returns None - never a
    guess - when the model isn't in the pricing table: synthetic/internal messages (model
    `<synthetic>`), a missing model field on older transcripts, or a model released after
    this table was last refreshed. Callers surface that as "estimate, partially priced"
    rather than silently underselling the total."""
    if not model or model not in _MODEL_PRICING_PER_MTOK:
        return None
    price_in, price_out, price_cw5, price_cw1, price_cr = _MODEL_PRICING_PER_MTOK[model]
    cache_creation = usage.get("cache_creation") or {}
    cw_5m = int(cache_creation.get("ephemeral_5m_input_tokens") or 0)
    cw_1h = int(cache_creation.get("ephemeral_1h_input_tokens") or 0)
    if not cache_creation:
        # Older transcripts have no 5m/1h breakdown - assume the API's own default TTL
        # rather than splitting arbitrarily.
        cw_5m = int(usage.get("cache_creation_input_tokens") or 0)
    return (
        int(usage.get("input_tokens") or 0) * price_in
        + int(usage.get("output_tokens") or 0) * price_out
        + cw_5m * price_cw5
        + cw_1h * price_cw1
        + int(usage.get("cache_read_input_tokens") or 0) * price_cr
    ) / 1_000_000


def _parse_ts(raw) -> _dt.datetime | None:
    """A transcript line's top-level `timestamp` field, ISO-8601 (the 'Z' suffix Python's
    fromisoformat only started accepting itself in 3.11 - normalised here so this keeps
    working on whatever interpreter runs it). None on anything that doesn't parse - never
    a guess."""
    if not isinstance(raw, str):
        return None
    try:
        return _dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


_ACTIVE_GAP_CAP_SECONDS = 15 * 60  # a gap wider than this reads as idle/resumed-later,
# not active work - Claude Code sessions routinely sit open for hours or days between
# messages (resume-later is a normal pattern), so first-to-last timestamp span was tried
# first and rejected: a live check against this repo's own transcripts produced "171h 55m"
# for one session - a straight span counts idle/resumed time as if it were active work.


def _active_seconds(timestamps: list) -> float:
    """Sum of consecutive-message gaps under the idle cap - the honest 'measured active
    time' figure. Gaps wider than the cap are excluded entirely rather than guessed at."""
    if len(timestamps) < 2:
        return 0.0
    ordered = sorted(timestamps)
    total = 0.0
    for a, b in zip(ordered, ordered[1:]):
        gap = (b - a).total_seconds()
        if 0 < gap <= _ACTIVE_GAP_CAP_SECONDS:
            total += gap
    return total


def parse_transcripts(transcript_dir: Path) -> dict:
    """Aggregate measured token usage AND measured ACTIVE session time (sum of consecutive
    per-line `timestamp` gaps under a 15-minute idle cap, 2026-08-08 - see
    _ACTIVE_GAP_CAP_SECONDS for why this isn't simply last-minus-first) across a project's
    session transcripts."""
    sessions = []
    unparsable_files = 0
    total_seconds = 0.0
    for jl in sorted(transcript_dir.glob("*.jsonl")):
        tokens_in = tokens_out = cache_read = cache_write = 0
        bad_lines = 0
        any_usage = False
        cost_usd = 0.0
        cost_partial = False
        by_model: dict[str, dict] = {}  # model id (or "unknown") -> per-model totals, see
        # emit_json's costByModel for the portfolio-wide rollup of this same breakdown
        timestamps = []
        try:
            with jl.open(encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except ValueError:
                        bad_lines += 1
                        continue
                    found = _walk_message_usage(obj)
                    if found:
                        usage, model = found
                        any_usage = True
                        m_in = int(usage.get("input_tokens") or 0)
                        m_out = int(usage.get("output_tokens") or 0)
                        m_cr = int(usage.get("cache_read_input_tokens") or 0)
                        m_cw = int(usage.get("cache_creation_input_tokens") or 0)
                        tokens_in += m_in
                        tokens_out += m_out
                        cache_read += m_cr
                        cache_write += m_cw
                        priced = _price_usage(model, usage)
                        if priced is None:
                            cost_partial = True
                        else:
                            cost_usd += priced
                        row = by_model.setdefault(
                            model or "unknown",
                            {"in": 0, "out": 0, "cache_read": 0, "cache_write": 0, "cost_usd": 0.0},
                        )
                        row["in"] += m_in
                        row["out"] += m_out
                        row["cache_read"] += m_cr
                        row["cache_write"] += m_cw
                        row["cost_usd"] += priced or 0.0
                    ts = _parse_ts(obj.get("timestamp")) if isinstance(obj, dict) else None
                    if ts is not None:
                        timestamps.append(ts)
        except OSError:
            unparsable_files += 1
            continue
        span_seconds = _active_seconds(timestamps)
        total_seconds += span_seconds
        if any_usage:
            sessions.append(
                {
                    "session": jl.stem,
                    "date": _dt.datetime.fromtimestamp(jl.stat().st_mtime).strftime("%Y-%m-%d"),
                    "in": tokens_in,
                    "out": tokens_out,
                    "cache_read": cache_read,
                    "cache_write": cache_write,
                    "bad_lines": bad_lines,
                    "span_seconds": span_seconds,
                    "cost_usd": cost_usd,
                    "cost_partial": cost_partial,
                    "cost_by_model": by_model,
                }
            )
    sessions.sort(key=lambda s: s["date"], reverse=True)
    return {"sessions": sessions, "unparsable_files": unparsable_files, "total_seconds": total_seconds}


def transcripts_dir_for(project: Path, claude_home: Path) -> Path:
    """Claude Code names the per-project transcript dir after the absolute path.

    The drive colon is flattened too: a leading `C:` in a joined segment makes pathlib
    treat it as a drive-relative path and silently discard the base directory.
    """
    slug = str(project.resolve()).replace("/", "-").replace("\\", "-").replace(":", "-")
    return claude_home / "projects" / slug


# ---------------------------------------------------------------------------
# Auto-discovery: which projects on this machine used the team?
# ---------------------------------------------------------------------------
_PLUGIN_NAME = "compliance-surveillance-team"


def _contains_plugin_name(obj) -> bool:
    """Defensively search a config entry for the plugin name - the enablement key's exact
    name is Claude Code internal and has no compatibility promise."""
    if isinstance(obj, str):
        return _PLUGIN_NAME in obj
    if isinstance(obj, dict):
        return any(_contains_plugin_name(k) or _contains_plugin_name(v) for k, v in obj.items())
    if isinstance(obj, list):
        return any(_contains_plugin_name(v) for v in obj)
    return False


def _cwd_from_transcripts(tdir: Path) -> str | None:
    """Recover the project's real path from a transcript dir.

    The dir name flattens '/' to '-', which is ambiguous when the path itself contains
    dashes - but session lines carry a `cwd` field, which is authoritative. Read a bounded
    number of lines; never guess from the slug."""
    for jl in sorted(tdir.glob("*.jsonl")):
        try:
            with jl.open(encoding="utf-8", errors="replace") as fh:
                for i, line in enumerate(fh):
                    if i > 50:
                        break
                    try:
                        obj = json.loads(line)
                    except ValueError:
                        continue
                    cwd = obj.get("cwd") if isinstance(obj, dict) else None
                    if (
                        isinstance(cwd, str)
                        and cwd.startswith(("/", "\\"))
                        or (isinstance(cwd, str) and len(cwd) > 2 and cwd[1] == ":")
                    ):
                        return cwd
        except OSError:
            continue
    return None


def _has_team_fingerprint(project: Path) -> bool:
    """Did the TEAM run here (vs ordinary Claude Code use)? Any one trace qualifies.

    Deliberately NOT a signal: a bare `.claude-plugin/plugin.json` manifest naming this
    plugin. That only proves the plugin is installed/available in the project - it says
    nothing about whether the team was ever actually engaged there. Counting it produced
    "0 engagements / No engagements yet" cards for every project that merely has the plugin
    cached (2026-08-09 live feedback: "picked up projects not built by the plugin" -
    confirmed via AskUserQuestion: drop the manifest-only signal entirely, don't just relabel
    it).

    Also no longer a signal, replaced 2026-08-09: a bare `.claude/.exec-consent` marker. That
    only proves execution consent was granted at some point - not that any real engagement ever
    happened (live example: budget/email/ha-dash/server/tradingagent all had a marker with zero
    engagements). Swapped for `artifacts/engagements.json`'s own `engagements` list - the
    project's own DERIVED, scan-and-archive-aware registry (scripts/engagement_state.py's
    `render_registry`/`scan_engagements` - regenerated on every mutation, empties out an
    all-archived project correctly, exactly the ground truth this function wants) - a real
    signal (the user's own suggestion), not a heuristic proxy for one.

    Also no longer a signal, dropped 2026-08-09 (same session, user's own live judgment): a
    bare `artifacts/**/engagement-summary-*.txt` closing-email file. Not a strong signal - an
    in-progress engagement legitimately has none yet, an old pre-registry engagement can leave
    one lying around indefinitely, and (the exact live case that surfaced this) it doesn't
    respect archival status at all: archiving a pack excludes it from the `engagements.json`
    registry check above, but this rglob doesn't know what "archived" means, so an archived
    engagement's closing email kept counting forever. The registry check above is the real,
    archive-aware signal for "closed engagements" too - this rglob was a redundant, weaker
    duplicate of it, not an independent source of truth.

    The check below is the one real remaining usage trace that ISN'T already covered by the
    registry: a generated codebase map (real registry engagements are covered by the check
    below that)."""
    artifacts = project / "artifacts"
    if find_codebase_map(project) is not None:
        return True
    registry = artifacts / "engagements.json"
    if registry.is_file():
        try:
            data = json.loads(registry.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = None
        if isinstance(data, dict) and data.get("engagements"):
            return True
    return False


def discover_projects(claude_home: Path) -> list[dict]:
    """Union of the machine's evidence for team usage, each entry labelled by basis:

      config      - the Claude Code config marks the plugin enabled there AND (while the
                    directory still exists) it carries a real usage trace
      fingerprint - transcripts exist AND the directory carries team traces (heuristic)
      historical  - config-known or transcript-known, but the directory is gone (can't
                    rule usage out, so it's kept rather than silently dropped)

    Ordinary Claude Code projects (transcripts, no team traces) are excluded rather than
    listed - the dashboard is about the team, not everything Claude ever touched. Plugin
    *enablement* alone (config says on, or a manifest is merely present) is the same class of
    non-signal as a bare manifest file: it says the tool is available, not that the team ever
    did anything - 2026-08-09 live feedback ("picked up projects not built by the plugin")
    confirmed via AskUserQuestion, twice (once for the manifest-only fingerprint signal, once
    for this config-enabled-but-idle case) - drop both rather than relabel them.
    """
    found: dict[str, dict] = {}

    config = claude_home.parent / ".claude.json"
    try:
        entries = json.loads(config.read_text(encoding="utf-8")).get("projects", {})
    except (OSError, ValueError):
        entries = {}
    for path_str, entry in entries.items():
        if not _contains_plugin_name(entry):
            continue
        p = Path(path_str)
        # Still exists? Require a real usage trace, same bar as the fingerprint path below -
        # "enabled" isn't "used". Gone? Keep it (can't check for a trace that may have existed
        # before deletion) - the "historical" basis below covers exactly this case.
        if p.is_dir() and not _has_team_fingerprint(p):
            continue
        found[path_str] = {"path": p, "basis": "config"}

    projects_root = claude_home / "projects"
    if projects_root.is_dir():
        for tdir in sorted(p for p in projects_root.iterdir() if p.is_dir()):
            cwd = _cwd_from_transcripts(tdir)
            if not cwd or cwd in found:
                continue
            p = Path(cwd)
            if not p.is_dir():
                # Deleted/moved: only surface it if we can't rule team usage out AND it
                # was config-known - otherwise it is ordinary history, skip.
                continue
            if _has_team_fingerprint(p):
                found[cwd] = {"path": p, "basis": "fingerprint"}

    out = []
    for path_str, info in sorted(found.items()):
        info["exists"] = info["path"].is_dir()
        if not info["exists"]:
            info["basis"] = "historical"
        out.append(info)
    return out


# ---------------------------------------------------------------------------
# Rendering - one self-contained page, no scripts, everything escaped.
# ---------------------------------------------------------------------------
_CSS = """
:root {
  --bg: #f6f8fa; --fg: #1a1a1a; --surface: #fff; --surface-alt: #f0f3f6;
  --border: #dcdcdc; --border-strong: #0969da; --muted: #57606a;
  --ok: #1a7f37; --bad: #cf222e; --warn: #9a6700;
  --chip-bg: #eaeef2; --chip-fg: #24292f;
  --bar-track: #eaeef2; --bar-fill: #0969da;
  --heat-0: #ebedf0; --heat-1: #9be9a8; --heat-2: #40c463; --heat-3: #216e39;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #0d1117; --fg: #e6edf3; --surface: #161b22; --surface-alt: #11161d;
    --border: #30363d; --border-strong: #539bf5; --muted: #8b949e;
    --ok: #3fb950; --bad: #f85149; --warn: #d29922;
    --chip-bg: #21262d; --chip-fg: #e6edf3;
    --bar-track: #21262d; --bar-fill: #539bf5;
    --heat-0: #161b22; --heat-1: #0e4429; --heat-2: #26a641; --heat-3: #39d353;
  }
}
body { font-family: -apple-system, Segoe UI, Roboto, sans-serif; margin: 0 auto;
  max-width: 72rem; padding: 1.5rem 1.25rem 3rem; color: var(--fg); background: var(--bg); }
h1 { font-size: 1.3rem; border-bottom: 2px solid var(--border-strong); padding-bottom: .4rem; }
h2 { font-size: .95rem; margin-top: 1.8rem; color: var(--muted); text-transform: uppercase;
  letter-spacing: .08em; }
h3 { font-size: .85rem; margin: 1.1rem 0 .3rem; color: var(--fg); }
table { border-collapse: collapse; width: 100%; background: var(--surface); font-size: .85rem; }
th, td { border: 1px solid var(--border); padding: .45rem .6rem; text-align: left;
  vertical-align: top; }
th { background: var(--surface-alt); }
td.num { text-align: right; font-variant-numeric: tabular-nums; }
.ok { color: var(--ok); font-weight: 600; }
.bad { color: var(--bad); font-weight: 600; }
.warn { color: var(--warn); font-weight: 600; }
.muted { color: var(--muted); }
.chip { display: inline-block; padding: .1rem .5rem; border-radius: 1rem; font-size: .78rem;
  background: var(--chip-bg); color: var(--chip-fg); margin-right: .3rem; }
.note { font-size: .78rem; color: var(--muted); margin-top: 1.6rem; line-height: 1.5; }
.sub { font-size: .8rem; color: var(--muted); margin: 0 0 .6rem; }
.card { background: var(--surface); border: 1px solid var(--border); border-left: 4px solid
  var(--border); border-radius: 8px; padding: .2rem 1.2rem 1.1rem; margin: 1rem 0;
  box-shadow: 0 1px 3px rgba(0,0,0,.06); }
.card-ok { border-left-color: var(--ok); }
.card-bad { border-left-color: var(--bad); }
.table-wrap { overflow-x: auto; margin-bottom: .3rem; }
.table-wrap table { min-width: max-content; }
.kpi-strip { display: grid; grid-template-columns: repeat(auto-fit, minmax(7.2rem, 1fr));
  gap: .7rem; margin: 1.1rem 0 1.6rem; }
.kpi { background: var(--surface); border: 1px solid var(--border); border-radius: 10px;
  padding: .8rem .6rem; text-align: center; box-shadow: 0 1px 3px rgba(0,0,0,.06); }
.kpi-value { font-size: 1.6rem; font-weight: 700; font-variant-numeric: tabular-nums;
  color: var(--border-strong); line-height: 1.15; }
.kpi-value.ok { color: var(--ok); }
.kpi-value.warn { color: var(--warn); }
.kpi-label { font-size: .68rem; color: var(--muted); text-transform: uppercase;
  letter-spacing: .06em; margin-top: .25rem; }
.detail-row td { border-top: none; background: var(--surface-alt); padding: .5rem .6rem 1rem; }
.timeline { margin-top: .4rem; }
.timeline summary { cursor: pointer; font-size: .8rem; color: var(--muted); font-weight: 600; }
.tl-cast { margin: .5rem 0 .2rem; }
.tl-body { border-left: 3px solid var(--border-strong); margin: .5rem 0 .2rem .4rem; padding-left: .9rem; }
.tl-node { font-size: .8rem; padding: .3rem .1rem; }
.tl-loop { background: var(--surface-alt); background: color-mix(in srgb, var(--warn) 12%, transparent);
  border-left: 3px solid var(--warn); margin-left: -.9rem; padding-left: .7rem;
  border-radius: 0 4px 4px 0; }
.tl-badge { display: inline-block; background: var(--warn); color: #1a1200; font-weight: 700;
  font-size: .68rem; text-transform: uppercase; letter-spacing: .04em; border-radius: 3px;
  padding: .05rem .4rem; margin-right: .4rem; }
.tl-dot { margin-right: .3rem; }
.tl-date { margin-right: .4rem; font-variant-numeric: tabular-nums; }
.bar-row { display: flex; align-items: center; gap: .5rem; font-size: .82rem; margin: .25rem 0; }
.bar-label { width: 12rem; flex-shrink: 0; overflow: hidden; text-overflow: ellipsis;
  white-space: nowrap; }
.bar-track { flex: 1; background: var(--bar-track); border-radius: 3px; height: .6rem;
  overflow: hidden; }
.bar-fill { height: 100%; background: var(--bar-fill); }
.bar-count { width: 2rem; text-align: right; }
.heatmap { display: grid; grid-auto-flow: column; grid-template-rows: repeat(7, 10px);
  gap: 2px; margin: .6rem 0; width: max-content; }
.heat { width: 10px; height: 10px; border-radius: 2px; background: var(--heat-0); }
.heat-1 { background: var(--heat-1); }
.heat-2 { background: var(--heat-2); }
.heat-3 { background: var(--heat-3); }
.heat-legend { display: flex; align-items: center; gap: .2rem; font-size: .72rem; margin: .2rem 0 .8rem; }
.heat-legend .heat { width: 9px; height: 9px; }
@media (max-width: 640px) {
  body { padding: 1.1rem .8rem 3rem; }
  h1 { font-size: 1.15rem; }
  .card { padding: .2rem .8rem .9rem; }
  .kpi-strip { grid-template-columns: repeat(2, 1fr); gap: .5rem; }
  .kpi-value { font-size: 1.3rem; }
  .bar-label { width: 6.5rem; font-size: .78rem; }
  th, td { padding: .35rem .45rem; font-size: .78rem; }
}
""".strip()

_STATUS_MARK = {
    "in_progress": ("⏳", ""),
    "blocked": ("⛔", "warn"),
    "closing": ("🔒", ""),
    "closed": ("✅", "ok"),
    "invalid": ("❗", "bad"),
}


def _fmt(n: int) -> str:
    return f"{n:,}"


def _fmt_duration(seconds: float) -> str:
    """Whole-minute human span - sub-minute rounds to '<1m' rather than '0m' (which would
    misread as 'no measured activity')."""
    if seconds <= 0:
        return "-"
    total_minutes = int(seconds // 60)
    hours, minutes = divmod(total_minutes, 60)
    if hours and minutes:
        return f"{hours}h {minutes}m"
    if hours:
        return f"{hours}h"
    if minutes:
        return f"{minutes}m"
    return "<1m"


def _day_span(opened: str | None, closed: str | None) -> str | None:
    """🧠 inferred, coarse: closed - opened at DATE granularity only (both fields are
    dates, not timestamps) - not a substitute for the measured session wall-time in the
    cost panel, which is a different kind of number from a different source. None when
    `opened` is missing/unparsable. An engagement not yet closed spans to today, marked
    "so far" so it never reads as a finished duration."""
    if not opened:
        return None
    try:
        o = _dt.date.fromisoformat(opened)
    except ValueError:
        return None
    if closed:
        try:
            c = _dt.date.fromisoformat(closed)
        except ValueError:
            return None
        return f"{(c - o).days}d"
    return f"{(_dt.date.today() - o).days}d so far"


# A still-open engagement's window used to extend through "today" with no upper bound at
# all - in practice that means EVERY session in the project from `opened` onward gets swept
# in, including ones doing something else entirely, for as long as the engagement stays open
# (2026-08-09 live finding: dashboard-demo, opened 2026-08-08 and never closed, matched an
# unrelated 8-hour dashboard-ui rebuild session the very next day, inflating its cost rollup
# by orders of magnitude). Capped instead at the engagement's own last observed activity
# (opened / an artifact's `added` / the latest dated log line) plus this many days of grace -
# covers a genuine short wrap-up gap without growing without bound. A judgment call, not a
# regulatory threshold - no obligation rides on the exact number.
_STILL_OPEN_GRACE_DAYS = 3


def _last_known_activity_date(e: dict) -> str | None:
    """The latest real date this engagement record itself carries - `opened`, any artifact's
    `added`, or any log line's own date (tagged or plain, same two regexes the Python-rendered
    timeline already uses at line ~980 above) - never `date.today()`, which is exactly the
    unbounded-growth problem this function exists to avoid. None only when the engagement has
    no dated evidence at all (shouldn't happen once `opened` is required by the caller, but
    defensive rather than assumed)."""
    dates = []
    opened = e.get("opened")
    if opened:
        dates.append(opened)
    for art in e.get("artifacts") or []:
        if isinstance(art, dict) and art.get("added"):
            dates.append(art["added"])
    for entry in e.get("log") or []:
        if not isinstance(entry, str):
            continue
        m = _TAGGED_LOG_RE.match(entry) or _PLAIN_LOG_RE.match(entry)
        if m:
            dates.append(m.group(1))
    return max(dates) if dates else None


def _match_engagement(session_date: str | None, engagements: list[dict]) -> str | None:
    """🧠 inferred: which engagement (if any) a session's date falls inside, by DATE-level
    `opened` -> `closed-or-capped-still-open` window - there is no direct session-to-engagement
    link in the data, so this is a best-effort heuristic (2026-08-08, cost-scoping; capped
    2026-08-09), not a hard join. An engagement with no `opened` date is never a candidate
    (nothing to compare against - no guessing). A still-open engagement's window extends to its
    own last known activity date plus `_STILL_OPEN_GRACE_DAYS` (see that constant's own
    docstring for why this replaced an unbounded "through today" window). When a session's date
    falls inside more than one engagement's window, the most recently opened one wins (tightest
    containing window) - ties are rare (would need two engagements opened the same day) and
    this is a reasonable, deterministic tiebreak rather than an important one. Returns None
    (unattributed) when nothing matches."""
    if not session_date:
        return None
    candidates = []
    for e in engagements:
        opened = e.get("opened")
        if not opened:
            continue
        if session_date < opened:
            continue
        closed = e.get("closed")
        if closed:
            if session_date > closed:
                continue
        else:
            last_activity = _last_known_activity_date(e) or opened
            cap = (_dt.date.fromisoformat(last_activity) + _dt.timedelta(days=_STILL_OPEN_GRACE_DAYS)).isoformat()
            if session_date > cap:
                continue
        candidates.append(e)
    if not candidates:
        return None
    candidates.sort(key=lambda e: e["opened"], reverse=True)
    return candidates[0].get("slug")


_PREF_LABELS = (
    ("regulatory_citations", "citations"),
    ("large_context_review_split", "review-split"),
    ("parallel_dispatch_via_workflow", "workflow-dispatch"),
    ("map_skeleton", "map-skeleton"),
)


def _settings_chips(snapshot: dict | None) -> str:
    """The team-preferences flags resolved AT OPEN TIME (engagement_state._cmd_init),
    never re-resolved - a point-in-time record, so this can legitimately differ from the
    project's CURRENT preferences (shown in _setup_chips) for an older engagement."""
    if not snapshot:
        return '<span class="chip muted">settings: not captured</span>'
    docx_on = "docx" in (snapshot.get("extra_formats") or [])
    chips = [f'<span class="chip">docx: {"on" if docx_on else "off"}</span>']
    for key, label in _PREF_LABELS:
        chips.append(f'<span class="chip">{label}: {"on" if snapshot.get(key) else "off"}</span>')
    return "".join(chips)


_TAGGED_LOG_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}) \[([^\]]+)\]: (.*)$")
_PLAIN_LOG_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}): (.*)$")
_TIMELINE_ICONS = {"review-loop": "&#128257;"}  # 🔁 - other tags fall back to a generic tag icon

# Plain-English job descriptions by role slug - NOT names (a real engagement's own `team`
# list, "Name (role)", already carries the real name playing that role; this is only the
# "in easier terms" annotation, so a bare role slug in free-text log/team entries reads as
# a person doing a recognisable job, not an internal identifier). Kept in sync with
# `.claude/skills/meet-the-team/SKILL.md`'s roster by hand - both are read-only prose about
# an unrelated file, not worth a generated-from-single-source step for 16 short strings.
_ROLE_LABELS = {
    "business-analyst": "requirements",
    "rules-developer": "detection rules",
    "data-analyst": "data analysis",
    "tuning-analyst": "threshold tuning",
    "ml-engineer": "ML/AI detection",
    "platform-engineer": "data pipelines",
    "qa-engineer": "QA & testing",
    "tm-sme": "AML advisor",
    "trade-surveillance-sme": "market-abuse advisor",
    "comms-surveillance-sme": "e-comms advisor",
    "model-validator": "model validation",
    "code-reviewer": "code review",
    "performance-reviewer": "performance review",
    "compliance-reviewer": "compliance review",
    "data-quality-reviewer": "data-quality review",
    "review-scorer": "review scoring",
}
_ROLE_SLUG_RE = re.compile(
    r"\b(" + "|".join(re.escape(k) for k in sorted(_ROLE_LABELS, key=len, reverse=True)) + r")\b"
)
_TEAM_MEMBER_RE = re.compile(r"^(.*?)\s*\(([^)]+)\)\s*$")
# A second team-string convention this project's own eval harness (scripts/eval_engage.py)
# writes: "🤖 Name, Role (Team)" - e.g. "🤖 Ravi, Code Reviewer (Virtual Surveillance IT)" -
# rather than this file's own "Name (role-slug)" convention. The comma before the role is the
# distinguishing signal (real single first-names in this roster never contain one) - matched
# FIRST, since _TEAM_MEMBER_RE would otherwise also match this shape, just with the wrong split
# (2026-08-09 live finding: real review-loop handoffs using slug tokens like "code-reviewer"
# silently failed to resolve to any actor because of this, so 3 genuine rework moments in one
# real engagement never rendered - traced and fixed, not a hypothetical).
_TEAM_MEMBER_COMMA_RE = re.compile(r"^(.*?),\s*(.+?)\s*\([^)]*\)\s*$")


def _slugify(text: str) -> str:
    """Free-text role ("Code Reviewer") -> the lowercase-hyphenated slug convention
    _ROLE_LABELS/log-line handoff tokens actually use ("code-reviewer") - collapses any
    run of non-alphanumerics to one hyphen, trims the ends."""
    return re.sub(r"[^a-z0-9]+", "-", text.strip().lower()).strip("-")


def _team_role_map(team: list | None) -> dict:
    """{role-slug: name} parsed from THIS engagement's own team list - the real name playing
    that role here, never a hardcoded global roster (which would be wrong for a genuine
    external collaborator marked as such). Handles both team-string conventions this project's
    own tooling produces - see _TEAM_MEMBER_COMMA_RE's own comment for why the second one
    exists and why it's tried first."""
    out = {}
    for member in team or []:
        if not isinstance(member, str):
            continue
        cleaned = member.lstrip("\U0001f916").strip()  # 🤖 prefix, if present
        m = _TEAM_MEMBER_COMMA_RE.match(cleaned)
        if m:
            out[_slugify(m.group(2))] = m.group(1).strip()
            continue
        m = _TEAM_MEMBER_RE.match(cleaned)
        if m:
            out[m.group(2).strip()] = m.group(1).strip()
    return out


def _humanize_agents(text: str, role_map: dict) -> str:
    """A bare role slug (e.g. "code-reviewer") in free-text log/team content becomes "Name
    (job description)" using this engagement's own roster where known, else just the plain-
    English description - so a timeline reads "Ravi (code review) -> Mateo (detection
    rules)" instead of raw internal slugs, whichever style the log-note was written in."""

    def sub(m: re.Match) -> str:
        slug = m.group(1)
        label = _ROLE_LABELS.get(slug, slug)
        name = role_map.get(slug)
        return f"{name} ({label})" if name else f"({label})"

    return _ROLE_SLUG_RE.sub(sub, text)


def _team_cast_html(team: list | None) -> str:
    """A one-line "who's who" for this engagement, named + in plain English - shown once
    above the timeline rather than re-explained on every event."""
    role_map = _team_role_map(team)
    if not role_map:
        return ""
    chips = "".join(
        f'<span class="chip">{_E(name)} &middot; {_E(_ROLE_LABELS.get(slug, slug))}</span>'
        for slug, name in role_map.items()
    )
    return f'<div class="tl-cast">{chips}</div>'


def _timeline_events(e: dict) -> list[dict]:
    """One ordered list of {date, icon, text, loop} per engagement: opened -> each
    artifact's added date -> log entries (tag-aware - a `log-note --tag review-loop`
    handoff gets its own icon AND a distinct visual style, `loop: True`, so a rework moment
    visibly breaks the line instead of blending into the flat flow) -> closed. Role slugs in
    log text are humanized against this engagement's own team roster. 📊 observed
    throughout: every event is read straight off a field a mutator already wrote
    (add-artifact/log-note/set-status) - nothing here is inferred. Engagements that never
    used --tag still get a real timeline, just without loop styling - graceful degradation."""
    role_map = _team_role_map(e.get("team"))
    events = []
    opened = e.get("opened")
    if opened:
        events.append({"date": opened, "icon": "&#128681;", "text": "Engagement opened", "loop": False})
    for art in e.get("artifacts") or []:
        if not isinstance(art, dict) or not art.get("added"):
            continue
        title = art.get("title") or art.get("path") or "artifact"
        events.append(
            {
                "date": art["added"],
                "icon": "&#128196;",
                "text": f"{title} ({art.get('status', '?')})",
                "loop": False,
            }
        )  # 📄
    for entry in e.get("log") or []:
        if not isinstance(entry, str):
            continue
        m = _TAGGED_LOG_RE.match(entry)
        if m:
            date, tag, text = m.groups()
            events.append(
                {
                    "date": date,
                    "icon": _TIMELINE_ICONS.get(tag, "&#128278;"),
                    "text": _humanize_agents(text, role_map),
                    "loop": tag == "review-loop",
                }
            )
            continue
        m = _PLAIN_LOG_RE.match(entry)
        if m:
            date, text = m.groups()
            events.append(
                {"date": date, "icon": "&#128221;", "text": _humanize_agents(text, role_map), "loop": False}
            )  # 📝
    closed = e.get("closed")
    if closed:
        events.append({"date": closed, "icon": "&#9989;", "text": "Engagement closed", "loop": False})
    events.sort(key=lambda ev: ev["date"])
    return events


_REWORK_BADGE = '<span class="tl-badge">rework</span> '


def _timeline_html(e: dict) -> str:
    events = _timeline_events(e)
    if not events:
        return ""
    node_htmls = []
    for ev in events:
        node_cls = "tl-node tl-loop" if ev["loop"] else "tl-node"
        badge = _REWORK_BADGE if ev["loop"] else ""
        node_htmls.append(
            f'<div class="{node_cls}"><span class="tl-dot">{ev["icon"]}</span>'
            f'<span class="tl-date muted">{_E(ev["date"])}</span>'
            f'{badge}{_E(ev["text"])}</div>'
        )
    nodes = "".join(node_htmls)
    return (
        f"<details class='timeline'><summary>Timeline ({len(events)})</summary>"
        f"{_team_cast_html(e.get('team'))}<div class='tl-body'>{nodes}</div></details>"
    )


def _engagement_table(engagements: list[dict], archived_count: int) -> str:
    if not engagements and not archived_count:
        return '<p class="sub muted">No engagements yet.</p>'
    rows = []
    for e in engagements:
        mark, cls = _STATUS_MARK.get(e.get("status"), ("?", ""))
        status_cell = f'<span class="{cls}">{mark} {_E(e.get("status") or "?")}</span>'
        outstanding = e.get("outstanding", 0)
        outstanding_cell = (
            f'<span class="warn">{outstanding}</span>'
            if outstanding
            else '<span class="muted">0</span>'
        )
        pending = e.get("pending_ratifications", 0)
        pending_cell = (
            f'<span class="warn">{pending} pending</span>'
            if pending
            else '<span class="muted">-</span>'
        )
        outcome = e.get("consent_outcome")
        outcome_cell = {"asked": "asked", "declined": "declined"}.get(
            outcome, '<span class="muted">-</span>'
        )
        span = _day_span(e.get("opened"), e.get("closed"))
        span_cell = f'<span class="muted">{_E(span)}</span>' if span else '<span class="muted">-</span>'
        rows.append(
            f"<tr><td>{_E(e.get('slug') or '-')}</td><td>{status_cell}</td>"
            f"<td>{_E(e.get('title') or '-')}</td><td class='num'>{outstanding_cell}</td>"
            f"<td>{pending_cell}</td><td>{outcome_cell}</td>"
            f"<td>{_E(e.get('opened') or '-')}</td><td>{_E(e.get('closed') or '-')}</td>"
            f"<td>{span_cell}</td></tr>"
        )
        detail = _settings_chips(e.get("settings_snapshot")) + _timeline_html(e)
        rows.append(f"<tr class='detail-row'><td colspan='9'>{detail}</td></tr>")
    table = (
        "<div class='table-wrap'><table><tr><th>Slug</th><th>Status</th><th>Title</th>"
        "<th>Outstanding</th><th>Ratifications</th><th>Consent asked?</th><th>Opened</th>"
        "<th>Closed</th><th>Span</th></tr>"
        + "".join(rows)
        + "</table></div>"
    )
    if archived_count:
        table += (
            f'<p class="sub muted">+ {archived_count} archived (excluded above - '
            "`engagement_state unarchive &lt;slug&gt;` to bring one back into scope).</p>"
        )
    return table


# ---------------------------------------------------------------------------
# Portfolio-wide sections (2026-08-08): every known project's engagements, aggregated.
# ---------------------------------------------------------------------------
def _roster_bars_html(projects: list[dict]) -> str:
    """Tally `team` ("Name (role)" strings) across every known engagement. No chart
    library - plain width-percent divs, same CSS-only approach as the rest of the page."""
    tally: dict[str, int] = {}
    for p in projects:
        for e in p.get("engagements") or []:
            for member in e.get("team") or []:
                if isinstance(member, str) and member:
                    tally[member] = tally.get(member, 0) + 1
    if not tally:
        return '<p class="sub muted">No team attributions recorded yet (set-team).</p>'
    ranked = sorted(tally.items(), key=lambda kv: (-kv[1], kv[0]))[:20]
    top = ranked[0][1]
    rows = []
    for name, count in ranked:
        pct = round(100 * count / top) if top else 0
        rows.append(
            '<div class="bar-row"><span class="bar-label">'
            f'{_E(name)}</span><div class="bar-track">'
            f'<div class="bar-fill" style="width:{pct}%"></div></div>'
            f'<span class="bar-count muted">{count}</span></div>'
        )
    return "".join(rows)


def _activity_tally(projects: list[dict]) -> dict[str, int]:
    """Every dated event across every known engagement: opened, closed, artifact-added."""
    tally: dict[str, int] = {}
    for p in projects:
        for e in p.get("engagements") or []:
            for date in (e.get("opened"), e.get("closed")):
                if date:
                    tally[date] = tally.get(date, 0) + 1
            for art in e.get("artifacts") or []:
                if isinstance(art, dict) and art.get("added"):
                    tally[art["added"]] = tally.get(art["added"], 0) + 1
    return tally


def _heatmap_html(tally: dict[str, int], max_days: int = 120) -> str:
    """A GitHub-contribution-style calendar (weeks = columns, Sun-Sat = rows), CSS grid
    only - no chart library, no JS. Capped to the most recent `max_days` so a long-lived
    portfolio doesn't balloon the page; the cap is stated on the page, not silent."""
    parsed = []
    for d, count in tally.items():
        try:
            parsed.append((_dt.date.fromisoformat(d), count))
        except ValueError:
            continue
    if not parsed:
        return '<p class="sub muted">No dated activity recorded yet.</p>'
    parsed.sort()
    end = parsed[-1][0]
    start = max(parsed[0][0], end - _dt.timedelta(days=max_days - 1))
    start -= _dt.timedelta(days=(start.weekday() + 1) % 7)  # align grid to a Sunday
    by_day: dict[_dt.date, int] = {}
    for d, c in parsed:
        if d >= start:
            by_day[d] = by_day.get(d, 0) + c
    total_days = (end - start).days + 1
    cells = []
    cur = start
    for _ in range(((total_days + 6) // 7) * 7):
        c = by_day.get(cur, 0)
        level = 0 if c == 0 else 1 if c == 1 else 2 if c <= 3 else 3
        cells.append(f'<div class="heat heat-{level}" title="{_E(cur.isoformat())}: {c} event(s)"></div>')
        cur += _dt.timedelta(days=1)
    legend = "".join(f'<div class="heat heat-{lvl}"></div>' for lvl in range(4))
    return (
        f"<div class='table-wrap'><div class='heatmap'>{''.join(cells)}</div></div>"
        f'<div class="heat-legend muted">Less {legend} More</div>'
        f'<p class="sub muted">Each cell = one day (Sun-Sat rows), most recent {max_days} '
        "days of engagement opens/closes and artifacts added. Hover a cell for the date.</p>"
    )


def obligation_coverage(projects: list[dict]) -> list[dict]:
    """Portfolio-wide: which regulatory obligations have actually been CITED across every
    known engagement's artifacts, reusing check_citations' own matcher verbatim (no new
    parsing) against config/regulatory-register.yaml. 📊 observed - mechanical text
    scanning, not an inference. An unreadable/missing artifact file is skipped silently
    (best-effort; the DoD gate, not this page, is the authority on artifact completeness).

    Each row also carries `sources` - the distinct (project, engagement) pairs that cited it
    (2026-08-08, dashboard-ui cross-linking) - so the frontend can link a citation straight
    back to the engagement(s) that cite it, instead of leaving Portfolio a dead end."""
    register = _load_register()
    tally: dict[str, dict] = {}
    for p in projects:
        artifacts_root = p["path"] / "artifacts"
        for e in p.get("engagements") or []:
            pack_dir = (
                artifacts_root if e.get("dir") in (None, "(flat)") else artifacts_root / e["dir"]
            )
            source_key = (p["name"], e.get("slug"))
            source = {"project": p["name"], "slug": e.get("slug"), "title": e.get("title")}
            for art in e.get("artifacts") or []:
                if not isinstance(art, dict) or not art.get("path"):
                    continue
                try:
                    text = (pack_dir / art["path"]).read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                result = check_text(text, register)
                for cite in result["verified"]:
                    row = tally.setdefault(cite, {"count": 0, "verified": True, "sources": {}})
                    row["count"] += 1
                    row["sources"][source_key] = source
                for cite in result["unverified"]:
                    row = tally.setdefault(cite, {"count": 0, "verified": False, "sources": {}})
                    row["count"] += 1
                    row["sources"][source_key] = source
    rows = [
        {"citation": k, "count": v["count"], "verified": v["verified"], "sources": list(v["sources"].values())}
        for k, v in tally.items()
    ]
    return sorted(rows, key=lambda r: (-r["count"], r["citation"]))


def _obligation_table_html(rows: list[dict]) -> str:
    if not rows:
        return '<p class="sub muted">No pinpoint citations found in any known artifact yet.</p>'
    body = []
    for r in rows:
        verdict = (
            '<span class="ok">verified</span>' if r["verified"] else '<span class="warn">unverified</span>'
        )
        body.append(
            f"<tr><td>{_E(r['citation'])}</td><td class='num'>{r['count']}</td><td>{verdict}</td></tr>"
        )
    return (
        "<div class='table-wrap'><table><tr><th>Citation</th><th>Cited by</th>"
        "<th>Register status</th></tr>" + "".join(body) + "</table></div>"
    )


def _setup_chips(p: dict) -> str:
    chips = []
    prefs = p["preferences"]
    chips.append(f'<span class="chip">docx export: {"on" if prefs["docx"] else "off"}</span>')
    chips.append(f'<span class="chip">citations: {"on" if prefs["citations"] else "off"}</span>')
    tp = p["tool_probe"]
    if tp is not None:
        stale = "" if tp["fresh"] else " (stale)"
        chips.append(f'<span class="chip">tools: {tp["installed"]}/{tp["total"]}{stale}</span>')
    else:
        chips.append('<span class="chip muted">tools: not probed</span>')
    hw = p["hook_wiring"]
    if hw is not None:
        chips.append(f'<span class="chip">hooks wired: {hw["wired"]}/{hw["total"]}</span>')
    if p["branch"]:
        chips.append(f'<span class="chip">branch: {_E(p["branch"])}</span>')
    return "".join(chips)


def _kpi_strip_html(projects: list[dict], obligation_rows: list[dict]) -> str:
    """The executive-summary read, before anyone opens a single table - headline numbers
    only, all 📊 observed (straight counts off data already collected, `obligation_rows`
    passed in rather than re-scanned so the portfolio's artifacts aren't read twice)."""
    engagements = [e for p in projects for e in p.get("engagements") or []]
    status_counts: dict[str, int] = {}
    for e in engagements:
        st = e.get("status") or "?"
        status_counts[st] = status_counts.get(st, 0) + 1
    total_artifacts = sum(len(e.get("artifacts") or []) for e in engagements)
    team_members = {m for e in engagements for m in (e.get("team") or []) if m}
    gate_clean = sum(1 for p in projects if not p["gate_findings"])

    tiles = [
        ("Projects", len(projects), None),
        ("Engagements", len(engagements), None),
        ("Closed", status_counts.get("closed", 0), "ok" if status_counts.get("closed") else None),
        (
            "In progress",
            status_counts.get("in_progress", 0) + status_counts.get("closing", 0),
            None,
        ),
        ("Blocked", status_counts.get("blocked", 0), "warn" if status_counts.get("blocked") else None),
        ("Artifacts", total_artifacts, None),
        ("Team members", len(team_members), None),
        ("Obligations cited", len(obligation_rows), None),
        (
            "DoD-clean projects",
            f"{gate_clean}/{len(projects)}" if projects else "0/0",
            "ok" if projects and gate_clean == len(projects) else ("warn" if projects else None),
        ),
    ]
    cells = []
    for label, value, cls in tiles:
        cls_attr = f" {cls}" if cls else ""
        cells.append(
            f'<div class="kpi"><div class="kpi-value{cls_attr}">{value}</div>'
            f'<div class="kpi-label">{_E(label)}</div></div>'
        )
    return f'<div class="kpi-strip">{"".join(cells)}</div>'


def render(projects: list[dict], usage_by_project: dict, generated: str) -> str:
    sections = []
    for p in projects:
        gate = (
            '<span class="ok">PASS</span>'
            if not p["gate_findings"]
            else f'<span class="bad">{len(p["gate_findings"])} finding(s)</span>'
        )
        consent = (
            '<span class="warn">&#9888; OPEN</span>'
            if p["consent_open"]
            else '<span class="muted">closed</span>'
        )
        if p["map_path"] is None:
            map_cell = '<span class="muted">none yet</span>'
        elif p["map_findings"]:
            map_cell = f'<span class="bad">{len(p["map_findings"])} finding(s)</span>'
        else:
            map_cell = '<span class="ok">healthy</span>'
        basis = p.get("basis", "explicit")
        basis_cell = {
            "config": '<span class="ok" title="plugin enabled in Claude config">config</span>',
            "fingerprint": '<span class="warn" title="inferred from team traces on disk">traces</span>',
            "explicit": '<span class="muted">given</span>',
        }.get(basis, _E(basis))

        accent = "card-ok" if not p["gate_findings"] else "card-bad"
        sections.append(
            f"<div class='card {accent}'>"
            f"<h3>{_E(p['name'])} <span class='muted' style='font-weight:400'>"
            f"({basis_cell} &middot; v{_E(p['version'] or '-')})</span></h3>"
            f"<p class='sub'>{_setup_chips(p)}</p>"
            "<div class='table-wrap'><table><tr><th>Engagements</th><th>Archived</th>"
            f"<th>Closing emails</th><th>DoD gate</th><th>Codebase map</th>"
            f"<th>Exec-consent marker</th></tr>"
            f"<tr><td class='num'>{len(p['engagements'])}</td>"
            f"<td class='num'>{p['archived_count']}</td>"
            f"<td class='num'>{len(p['emails'])}</td>"
            f"<td>{gate}</td><td>{map_cell}</td><td>{consent}</td></tr></table></div>"
            f"{_engagement_table(p['engagements'], p['archived_count'])}"
            "</div>"
        )
    project_blocks = "".join(sections) or '<p class="muted">No team projects found.</p>'

    obligation_rows = obligation_coverage(projects)  # computed ONCE, reused by the KPI
    # strip and the table below - each call re-reads every known artifact off disk.
    kpi_strip = _kpi_strip_html(projects, obligation_rows)

    activity_tally = _activity_tally(projects)
    portfolio_block = (
        "<div class='card'><h3>Activity</h3>"
        f"{_heatmap_html(activity_tally)}</div>"
        "<div class='card'><h3>Roster involvement</h3>"
        f"{_roster_bars_html(projects)}</div>"
        "<div class='card'><h3>Obligation coverage</h3>"
        f"{_obligation_table_html(obligation_rows)}"
        "<p class='sub muted'>Citations found in every known engagement's artifacts, "
        "matched against config/regulatory-register.yaml - the same matcher "
        "check_citations.py itself uses.</p></div>"
    )

    cost_rows, totals = [], {"in": 0, "out": 0, "cache_read": 0, "cache_write": 0, "span": 0.0}
    total_unparsable = 0
    portfolio_seconds = 0.0  # ALL sessions, every project - deliberately NOT the same
    # scope as `totals` below (capped to the first 20 listed sessions per project, the
    # pre-existing convention for the token columns) - kept as its own labelled line so
    # the two differently-scoped numbers never read as one contradicting total.
    for pname, stats in usage_by_project.items():
        total_unparsable += stats["unparsable_files"]
        portfolio_seconds += stats.get("total_seconds", 0.0)
        for s in stats["sessions"][:20]:
            for k in ("in", "out", "cache_read", "cache_write"):
                totals[k] += s[k]
            totals["span"] += s["span_seconds"]
            bad = (
                f' <span class="warn">({s["bad_lines"]} unparsed)</span>' if s["bad_lines"] else ""
            )
            cost_rows.append(
                f"<tr><td>{_E(pname)}</td><td>{_E(s['date'])}</td>"
                f"<td class='muted'>{_E(s['session'][:12])}&hellip;</td>"
                f"<td class='num'>{_fmt(s['in'])}</td><td class='num'>{_fmt(s['out'])}</td>"
                f"<td class='num'>{_fmt(s['cache_read'])}</td>"
                f"<td class='num'>{_fmt(s['cache_write'])}{bad}</td>"
                f"<td class='num'>{_E(_fmt_duration(s['span_seconds']))}</td></tr>"
            )
    cost_table = (
        "<div class='table-wrap'><table><tr><th>Project</th><th>Date</th><th>Session</th>"
        "<th>Input</th><th>Output</th><th>Cache read</th><th>Cache write</th><th>Duration</th></tr>"
        + "".join(cost_rows)
        + f"<tr><th colspan='3'>Total (listed sessions)</th>"
        f"<th class='num'>{_fmt(totals['in'])}</th><th class='num'>{_fmt(totals['out'])}</th>"
        f"<th class='num'>{_fmt(totals['cache_read'])}</th>"
        f"<th class='num'>{_fmt(totals['cache_write'])}</th>"
        f"<th class='num'>{_E(_fmt_duration(totals['span']))}</th></tr></table></div>"
        f"<p class='sub muted'>Active time across ALL known sessions, every listed and "
        f"unlisted one (not just the rows above): {_E(_fmt_duration(portfolio_seconds))}.</p>"
    )
    unparsable_note = (
        f"<p class='note warn'>&#9888; {total_unparsable} transcript file(s) could not be "
        "read - their usage is missing from the totals above.</p>"
        if total_unparsable
        else ""
    )

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Team dashboard - local observability</title><style>{_CSS}</style></head><body>
<h1>&#127913; Team dashboard <span class="muted" style="font-weight:400">- local, read-only
- generated {_E(generated)}</span></h1>
{kpi_strip}
<h2>Projects</h2>
{project_blocks}
<h2>Portfolio</h2>
{portfolio_block}
<h2>Measured token usage &amp; session time (from session transcripts)</h2>
{cost_table}
{unparsable_note}
<p class="note">&#128202; Session token counts above are the API's own usage fields; Duration
is the sum of consecutive-message gaps under 15 minutes (wider gaps read as idle/resumed,
not active work, and are excluded) - both machine-wide, from disk transcripts, kept
separate from any per-engagement footprint estimate
(&#129504; inferred, in each engagement's own START-HERE.md) and from each engagement row's
coarse open&#8594;close day-span above (&#129504; inferred, date-granularity only), to avoid
differently-sourced numbers reading as a contradiction. This page sees only this machine,
and only sessions whose transcripts remain on disk. It is read-only by design: management
actions (granting consent, running engagements) stay deliberate human acts in the terminal.
Regenerate with <code>python -m scripts.dashboard</code>.</p>
</body></html>
"""


# ---------------------------------------------------------------------------
# JSON data export (2026-08-08, dashboard-ui) - the frontend's ONLY data source.
# ---------------------------------------------------------------------------
def _artifact_json(art: dict, pack_dir: Path) -> dict:
    path = art.get("path")
    return {
        "path": path,
        "absPath": str(pack_dir / path) if path else None,  # dashboard-ui links to this
        "title": art.get("title"),
        "status": art.get("status"),
        "added": art.get("added"),
    }


def _engagement_json(e: dict, project_path: Path) -> dict:
    # Same pack-dir resolution as obligation_coverage()/_engagement_extras() - a workspaced
    # engagement lives at artifacts/<dir>, a legacy flat pack's artifacts sit at artifacts/
    # itself (dir is None or the "(flat)" sentinel scan_engagements() uses).
    artifacts_root = project_path / "artifacts"
    pack_dir = artifacts_root if e.get("dir") in (None, "(flat)") else artifacts_root / e["dir"]
    return {
        "slug": e.get("slug"),
        "dir": e.get("dir"),
        "title": e.get("title"),
        "status": e.get("status"),
        "profile": e.get("profile"),
        "opened": e.get("opened"),
        "closed": e.get("closed"),
        "outstanding": e.get("outstanding", 0),
        "pendingRatifications": e.get("pending_ratifications", 0),
        "consentOutcome": e.get("consent_outcome"),
        "team": e.get("team") or [],
        "artifacts": [
            _artifact_json(a, pack_dir) for a in (e.get("artifacts") or []) if isinstance(a, dict)
        ],
        "settingsSnapshot": e.get("settings_snapshot"),
        "log": e.get("log") or [],
    }


def _project_json(p: dict) -> dict:
    project_path: Path = p["path"]  # still a Path here - _engagement_json needs it for joins
    return {
        "name": p["name"],
        "path": str(project_path),
        "version": p.get("version"),
        "branch": p.get("branch"),
        "basis": p.get("basis", "explicit"),
        "preferences": p.get("preferences") or {"docx": False, "citations": True},
        "toolProbe": p.get("tool_probe"),
        "hookWiring": p.get("hook_wiring"),
        "archivedCount": p.get("archived_count", 0),
        "emails": [{"name": e.name, "absPath": str(e)} for e in (p.get("emails") or [])],
        "gateFindings": p.get("gate_findings") or [],
        "consentOpen": bool(p.get("consent_open")),
        "mapPath": str(p["map_path"]) if p.get("map_path") else None,
        "mapFindings": p.get("map_findings"),
        "engagements": [_engagement_json(e, project_path) for e in (p.get("engagements") or [])],
    }


def _session_json(s: dict, engagement_slug: str | None) -> dict:
    return {
        "session": s.get("session"),
        "date": s.get("date"),
        "in": s.get("in", 0),
        "out": s.get("out", 0),
        "cacheRead": s.get("cache_read", 0),
        "cacheWrite": s.get("cache_write", 0),
        "badLines": s.get("bad_lines", 0),
        "spanSeconds": s.get("span_seconds", 0.0),
        "costUsd": s.get("cost_usd", 0.0),
        "costPartial": bool(s.get("cost_partial", False)),
        "engagementSlug": engagement_slug,
        "costByModel": {
            # outer key is the raw model id (data, not a schema field - not camelCased)
            model: {
                "in": row.get("in", 0),
                "out": row.get("out", 0),
                "cacheRead": row.get("cache_read", 0),
                "cacheWrite": row.get("cache_write", 0),
                "costUsd": row.get("cost_usd", 0.0),
            }
            for model, row in (s.get("cost_by_model") or {}).items()
        },
    }


def _cost_by_model_rows(usage_by_project: dict) -> list[dict]:
    """Portfolio-wide (machine-wide, every known session - not capped like the Sessions &
    cost tab's listed rows, matching the KpiStrip convention) breakdown of cost/tokens by
    model, for the "Cost by model" table. The `unknown` bucket - sessions.cost_by_model's
    fallback key for a missing/unpriced model - always prices to $0 by construction
    (_price_usage returns None there), so its tokens are real but its cost is a floor, not
    a number to trust; the frontend labels it accordingly rather than folding it into a
    silently-wrong total."""
    tally: dict[str, dict] = {}
    for stats in usage_by_project.values():
        for s in stats.get("sessions") or []:
            for model, row in (s.get("cost_by_model") or {}).items():
                agg = tally.setdefault(
                    model, {"in": 0, "out": 0, "cache_read": 0, "cache_write": 0, "cost_usd": 0.0}
                )
                agg["in"] += row.get("in", 0)
                agg["out"] += row.get("out", 0)
                agg["cache_read"] += row.get("cache_read", 0)
                agg["cache_write"] += row.get("cache_write", 0)
                agg["cost_usd"] += row.get("cost_usd", 0.0)
    rows = [
        {
            "model": model,
            "in": agg["in"],
            "out": agg["out"],
            "cacheRead": agg["cache_read"],
            "cacheWrite": agg["cache_write"],
            "costUsd": agg["cost_usd"],
        }
        for model, agg in tally.items()
    ]
    return sorted(rows, key=lambda r: r["costUsd"], reverse=True)


def _engagement_cost_rollup(sessions: list[dict], slug: str) -> dict | None:
    """🧠 inferred: sum the (already date-matched, see _match_engagement) sessions
    attributed to one engagement. None when no session matched - an engagement with no
    session activity in its window shows no rollup rather than a misleading all-zero one."""
    matched = [s for s in sessions if s["engagementSlug"] == slug]
    if not matched:
        return None
    return {
        "sessionCount": len(matched),
        "tokensIn": sum(s["in"] for s in matched),
        "tokensOut": sum(s["out"] for s in matched),
        "cacheRead": sum(s["cacheRead"] for s in matched),
        "cacheWrite": sum(s["cacheWrite"] for s in matched),
        "costUsd": sum(s["costUsd"] for s in matched),
        "costPartial": any(s["costPartial"] for s in matched),
    }


def emit_json(projects: list[dict], usage_by_project: dict, generated: str) -> dict:
    """Serialize the SAME in-memory structures render() consumes into the JSON shape the
    dashboard-ui frontend imports at build time (dashboard-ui/src/lib/types.ts mirrors this
    exactly - this function is the source of truth for the shape; TS types follow it, never
    the reverse). camelCase keys at this boundary only - every internal Python dict stays
    snake_case, unchanged, everywhere else in this module.

    obligation_coverage() is computed here (not left to the frontend) because its matcher
    (scripts.check_citations) is Python-only by design - re-implementing citation matching
    in JS was explicitly rejected (plan decision: Python collects, JS only renders).

    Sessions are date-matched to the engagement whose opened->closed window contains them
    (_match_engagement, 2026-08-08 cost-scoping) - each session carries the resulting
    `engagementSlug` (None = unattributed), and each engagement carries a `costRollup`
    summing its matched sessions, so the frontend can render both the flat, grouped session
    table AND a per-engagement cost figure without re-deriving the match itself."""
    obligation_rows = obligation_coverage(projects)
    engagements_by_project = {p["name"]: (p.get("engagements") or []) for p in projects}

    usage_json = {}
    for name, stats in usage_by_project.items():
        engagements = engagements_by_project.get(name, [])
        sessions_json = [
            _session_json(s, _match_engagement(s.get("date"), engagements))
            for s in (stats.get("sessions") or [])
        ]
        usage_json[name] = {
            "sessions": sessions_json,
            "unparsableFiles": stats.get("unparsable_files", 0),
            "totalSeconds": stats.get("total_seconds", 0.0),
        }

    projects_json = [_project_json(p) for p in projects]
    for proj in projects_json:
        sessions_json = usage_json.get(proj["name"], {}).get("sessions", [])
        for eng in proj["engagements"]:
            eng["costRollup"] = _engagement_cost_rollup(sessions_json, eng["slug"])

    return {
        "generated": generated,
        "roleLabels": dict(_ROLE_LABELS),
        "projects": projects_json,
        "usageByProject": usage_json,
        "costByModel": _cost_by_model_rows(usage_by_project),
        "obligations": [
            {
                "citation": r["citation"],
                "count": r["count"],
                "verified": r["verified"],
                "sources": r["sources"],
            }
            for r in obligation_rows
        ],
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Generate the local static team dashboard.")
    ap.add_argument(
        "projects",
        nargs="*",
        default=[],
        help="working project dirs (default: auto-discover from the Claude home; cwd if none found)",
    )
    ap.add_argument("--out", type=Path, default=Path("dashboard.html"))
    ap.add_argument(
        "--json",
        type=Path,
        default=None,
        dest="json_out",
        help="write the data-only JSON payload here instead of rendering HTML - consumed by "
        "dashboard-ui's build (`npm run dashboard`); mutually exclusive with --out, which "
        "keeps rendering the plain no-Node HTML fallback unchanged when --json is omitted",
    )
    ap.add_argument(
        "--claude-home",
        type=Path,
        default=Path.home() / ".claude",
        help="Claude Code home (transcript root); overridable for tests",
    )
    args = ap.parse_args(argv)

    basis_by_path: dict = {}
    if args.projects:
        project_dirs = [Path(p) for p in args.projects]
    else:
        discovered = discover_projects(args.claude_home)
        project_dirs = [d["path"] for d in discovered if d["exists"]]
        basis_by_path = {str(d["path"].resolve()): d["basis"] for d in discovered}
        if not project_dirs:
            project_dirs = [Path(".")]
    projects = [project_summary(p.resolve()) for p in project_dirs if p.is_dir()]
    for p in projects:
        p["basis"] = basis_by_path.get(str(p["path"]), "explicit")
    cache_version = plugin_cache_version(args.claude_home)
    for p in projects:
        if p["version"] is None and cache_version:
            p["version"] = f"{cache_version} (plugin cache)"
    usage = {}
    for p in projects:
        tdir = transcripts_dir_for(p["path"], args.claude_home)
        if tdir.is_dir():
            usage[p["name"]] = parse_transcripts(tdir)

    generated = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    if args.json_out:
        payload = emit_json(projects, usage, generated)
        args.json_out.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(
            f"Dashboard data written to {args.json_out} - "
            "run `npm run dashboard` in dashboard-ui/ to build the UI."
        )
    else:
        args.out.write_text(render(projects, usage, generated), encoding="utf-8")
        print(f"Dashboard written to {args.out} - open it in a browser (file://).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
