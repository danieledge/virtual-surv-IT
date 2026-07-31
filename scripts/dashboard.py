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
    separately): slug, status, phase, title, opened/closed, outstanding-item count, pending
    human ratifications, the recorded execution-consent outcome (asked/declined, distinct
    from the marker - a "No" leaves a trace even though the marker itself is absent).
  - The mechanical DoD gate result, at FULL parity with `check_artifacts.py`'s own CLI (not
    a narrower hand-rolled subset): per-pack findings + registry staleness + root orphans +
    the ARCHIVED-OPEN safeguard (an archived pack that never actually closed).
  - Codebase-map presence and hygiene (ADR-003).
Plus a cost panel: measured token usage parsed from the Claude Code session transcripts for
those projects (~/.claude/projects/<slug>/*.jsonl, 📊 measured, session-level) - kept
deliberately separate from and NOT summed with per-engagement `footprint` estimates (🧠
inferred, human/model-estimated) to avoid two differently-sourced token numbers reading as a
contradiction; footprint is left to each engagement's own START-HERE.md.

LIMITS (stated on the page): sees only this machine; cost covers sessions whose transcripts
are still on disk; the dashboard is read-only by design - management actions stay deliberate
human acts in the terminal.

Usage: `python -m scripts.dashboard [project_dir ...] [--out dashboard.html]`
This is a USER-run tool (open the output yourself); agents do not need to invoke it.
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
    the recorded (non-granting) execution-consent outcome. Best-effort - an unreadable
    state file yields all-zero/None rather than breaking the row."""
    try:
        state = json.loads((pack_dir / "engagement-state.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"outstanding": 0, "pending_ratifications": 0, "consent_outcome": None}
    outstanding = state.get("outstanding")
    ratifications = state.get("ratifications")
    outcome = state.get("execution_consent_outcome")
    return {
        "outstanding": len(outstanding) if isinstance(outstanding, list) else 0,
        "pending_ratifications": (
            sum(1 for r in ratifications if isinstance(r, dict) and r.get("status") == "pending")
            if isinstance(ratifications, list)
            else 0
        ),
        "consent_outcome": outcome.get("outcome") if isinstance(outcome, dict) else None,
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
        "emails": [e.name for e in emails],
        "gate_findings": gate,
        "consent_open": (project / ".claude" / ".exec-consent").is_file(),
        "map_path": map_path,
        "map_findings": map_findings,
    }


def _walk_usage(obj) -> dict | None:
    """Find a usage dict ({input_tokens, output_tokens, ...}) anywhere in a JSON object.

    The transcript schema is internal and has moved before; searching structurally is the
    tolerant option. First match wins (one usage block per assistant message).
    """
    if isinstance(obj, dict):
        usage = obj.get("usage")
        if isinstance(usage, dict) and ("input_tokens" in usage or "output_tokens" in usage):
            return usage
        for value in obj.values():
            found = _walk_usage(value)
            if found:
                return found
    elif isinstance(obj, list):
        for value in obj:
            found = _walk_usage(value)
            if found:
                return found
    return None


def parse_transcripts(transcript_dir: Path) -> dict:
    """Aggregate measured token usage across a project's session transcripts."""
    sessions = []
    unparsable_files = 0
    for jl in sorted(transcript_dir.glob("*.jsonl")):
        tokens_in = tokens_out = cache_read = cache_write = 0
        bad_lines = 0
        any_usage = False
        try:
            with jl.open(encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        usage = _walk_usage(json.loads(line))
                    except ValueError:
                        bad_lines += 1
                        continue
                    if not usage:
                        continue
                    any_usage = True
                    tokens_in += int(usage.get("input_tokens") or 0)
                    tokens_out += int(usage.get("output_tokens") or 0)
                    cache_read += int(usage.get("cache_read_input_tokens") or 0)
                    cache_write += int(usage.get("cache_creation_input_tokens") or 0)
        except OSError:
            unparsable_files += 1
            continue
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
                }
            )
    sessions.sort(key=lambda s: s["date"], reverse=True)
    return {"sessions": sessions, "unparsable_files": unparsable_files}


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
    """Did the TEAM run here (vs ordinary Claude Code use)? Any one trace qualifies."""
    artifacts = project / "artifacts"
    # rglob, not glob: workspace-mode engagements (the default since 0.31) put the
    # closing email at artifacts/<slug>/engagement-summary-*.txt, not the flat root - a
    # non-recursive glob here silently missed the majority of real modern usage.
    if artifacts.is_dir() and next(artifacts.rglob("engagement-summary-*.txt"), None):
        return True
    if find_codebase_map(project) is not None:
        return True
    if (project / ".claude" / ".exec-consent").is_file():
        return True
    manifest = project / ".claude-plugin" / "plugin.json"
    if manifest.is_file():
        try:
            if json.loads(manifest.read_text(encoding="utf-8")).get("name") == _PLUGIN_NAME:
                return True
        except (OSError, ValueError):
            pass
    return False


def discover_projects(claude_home: Path) -> list[dict]:
    """Union of the machine's evidence for team usage, each entry labelled by basis:

      config      - the Claude Code config marks the plugin enabled there (authoritative)
      fingerprint - transcripts exist AND the directory carries team traces (heuristic)
      historical  - transcripts exist but the directory is gone (usage still happened)

    Ordinary Claude Code projects (transcripts, no team traces) are excluded rather than
    listed - the dashboard is about the team, not everything Claude ever touched.
    """
    found: dict[str, dict] = {}

    config = claude_home.parent / ".claude.json"
    try:
        entries = json.loads(config.read_text(encoding="utf-8")).get("projects", {})
    except (OSError, ValueError):
        entries = {}
    for path_str, entry in entries.items():
        if _contains_plugin_name(entry):
            found[path_str] = {"path": Path(path_str), "basis": "config"}

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
body { font-family: -apple-system, Segoe UI, Roboto, sans-serif; margin: 0 auto;
  max-width: 72rem; padding: 1.5rem 1.25rem 3rem; color: #1a1a1a; background: #f6f8fa; }
h1 { font-size: 1.3rem; border-bottom: 2px solid #0969da; padding-bottom: .4rem; }
h2 { font-size: .95rem; margin-top: 1.8rem; color: #57606a; text-transform: uppercase;
  letter-spacing: .08em; }
h3 { font-size: .85rem; margin: 1.1rem 0 .3rem; color: #24292f; }
table { border-collapse: collapse; width: 100%; background: #fff; font-size: .85rem; }
th, td { border: 1px solid #dcdcdc; padding: .45rem .6rem; text-align: left;
  vertical-align: top; }
th { background: #f0f3f6; }
td.num { text-align: right; font-variant-numeric: tabular-nums; }
.ok { color: #1a7f37; font-weight: 600; }
.bad { color: #cf222e; font-weight: 600; }
.warn { color: #9a6700; font-weight: 600; }
.muted { color: #57606a; }
.chip { display: inline-block; padding: .1rem .5rem; border-radius: 1rem; font-size: .78rem;
  background: #eaeef2; color: #24292f; margin-right: .3rem; }
.note { font-size: .78rem; color: #57606a; margin-top: 1.6rem; line-height: 1.5; }
.sub { font-size: .8rem; color: #57606a; margin: 0 0 .6rem; }
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
        rows.append(
            f"<tr><td>{_E(e.get('slug') or '-')}</td>{status_cell and '<td>' + status_cell + '</td>'}"
            f"<td>{_E(e.get('title') or '-')}</td><td class='num'>{outstanding_cell}</td>"
            f"<td>{pending_cell}</td><td>{outcome_cell}</td>"
            f"<td>{_E(e.get('opened') or '-')}</td><td>{_E(e.get('closed') or '-')}</td></tr>"
        )
    table = (
        "<table><tr><th>Slug</th><th>Status</th><th>Title</th><th>Outstanding</th>"
        "<th>Ratifications</th><th>Consent asked?</th><th>Opened</th><th>Closed</th></tr>"
        + "".join(rows)
        + "</table>"
    )
    if archived_count:
        table += (
            f'<p class="sub muted">+ {archived_count} archived (excluded above - '
            "`engagement_state unarchive &lt;slug&gt;` to bring one back into scope).</p>"
        )
    return table


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

        sections.append(
            f"<h3>{_E(p['name'])} <span class='muted' style='font-weight:400'>"
            f"({basis_cell} &middot; v{_E(p['version'] or '-')})</span></h3>"
            f"<p class='sub'>{_setup_chips(p)}</p>"
            f"<table><tr><th>Engagements</th><th>Archived</th><th>Closing emails</th>"
            f"<th>DoD gate</th><th>Codebase map</th><th>Exec-consent marker</th></tr>"
            f"<tr><td class='num'>{len(p['engagements'])}</td>"
            f"<td class='num'>{p['archived_count']}</td>"
            f"<td class='num'>{len(p['emails'])}</td>"
            f"<td>{gate}</td><td>{map_cell}</td><td>{consent}</td></tr></table>"
            f"{_engagement_table(p['engagements'], p['archived_count'])}"
        )
    project_blocks = "".join(sections) or '<p class="muted">No team projects found.</p>'

    cost_rows, totals = [], {"in": 0, "out": 0, "cache_read": 0, "cache_write": 0}
    total_unparsable = 0
    for pname, stats in usage_by_project.items():
        total_unparsable += stats["unparsable_files"]
        for s in stats["sessions"][:20]:
            for k in totals:
                totals[k] += s[k]
            bad = (
                f' <span class="warn">({s["bad_lines"]} unparsed)</span>' if s["bad_lines"] else ""
            )
            cost_rows.append(
                f"<tr><td>{_E(pname)}</td><td>{_E(s['date'])}</td>"
                f"<td class='muted'>{_E(s['session'][:12])}&hellip;</td>"
                f"<td class='num'>{_fmt(s['in'])}</td><td class='num'>{_fmt(s['out'])}</td>"
                f"<td class='num'>{_fmt(s['cache_read'])}</td>"
                f"<td class='num'>{_fmt(s['cache_write'])}{bad}</td></tr>"
            )
    cost_table = (
        "<table><tr><th>Project</th><th>Date</th><th>Session</th><th>Input</th>"
        "<th>Output</th><th>Cache read</th><th>Cache write</th></tr>"
        + "".join(cost_rows)
        + f"<tr><th colspan='3'>Total (listed sessions)</th>"
        f"<th class='num'>{_fmt(totals['in'])}</th><th class='num'>{_fmt(totals['out'])}</th>"
        f"<th class='num'>{_fmt(totals['cache_read'])}</th>"
        f"<th class='num'>{_fmt(totals['cache_write'])}</th></tr></table>"
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
<h2>Projects</h2>
{project_blocks}
<h2>Measured token usage (from session transcripts)</h2>
{cost_table}
{unparsable_note}
<p class="note">&#128202; Session token counts above are the API's own usage fields
(measured, machine-wide, from disk transcripts) - kept separate from any per-engagement
footprint estimate (&#129504; inferred, in each engagement's own START-HERE.md), which is
a different kind of number and not summed in here to avoid two unlabelled token figures
reading as a contradiction. This page sees only this machine, and only sessions whose
transcripts remain on disk. It is read-only by design: management actions (granting
consent, running engagements) stay deliberate human acts in the terminal. Regenerate with
<code>python -m scripts.dashboard</code>.</p>
</body></html>
"""


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
    args.out.write_text(render(projects, usage, generated), encoding="utf-8")
    print(f"Dashboard written to {args.out} - open it in a browser (file://).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
