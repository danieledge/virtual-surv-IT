#!/usr/bin/env python3
"""
Local observability dashboard - a static HTML page generated from files already on disk.

WHY STATIC: everything runs and stays on the user's machine. No server, no port, no auth
surface - the output is a self-contained `dashboard.html` opened via file:// and refreshed
by re-running the script. This is deliberate (house rule: never serve sensitive paths from
a casual server) and honest: the data changes when engagements run, not continuously.

WHAT IT SHOWS, per working project passed on the command line (default: cwd):
  - engagement artifacts (count + closing emails) and the mechanical DoD gate result
    (reusing scripts/check_artifacts - the same checks the PM runs at close);
  - codebase-map presence and hygiene (ADR-003);
  - the execution-consent state (an OPEN gate is highlighted - it is easy to forget);
  - plugin/team version if the project carries a manifest.
Plus a cost panel: measured token usage parsed from the Claude Code session transcripts
for those projects (~/.claude/projects/<slug>/*.jsonl). Token counts come from the API's
own usage fields (📊 measured); the transcript format is internal and may change between
Claude Code versions, so unparsable lines/files are COUNTED AND SHOWN, never silently
skipped.

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
import sys
from pathlib import Path

try:  # repo-relative import (python -m scripts.dashboard) with a fallback for direct runs
    from scripts.check_artifacts import check, check_map, find_codebase_map
except ImportError:  # pragma: no cover
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from scripts.check_artifacts import check, check_map, find_codebase_map

_E = html.escape


# ---------------------------------------------------------------------------
# Data collection.
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


def project_summary(project: Path) -> dict:
    """Facts about one working project, all from files on disk."""
    artifacts = project / "artifacts"
    md_files = sorted(artifacts.rglob("*.md")) if artifacts.is_dir() else []
    emails = sorted(artifacts.rglob("engagement-summary-*.txt")) if artifacts.is_dir() else []
    gate = list(check(artifacts))
    map_path = find_codebase_map(project)
    map_findings = check_map(map_path) if map_path else None

    version = None
    manifest = project / ".claude-plugin" / "plugin.json"
    if manifest.is_file():
        try:
            version = json.loads(manifest.read_text(encoding="utf-8")).get("version")
        except (OSError, ValueError):
            version = "unreadable"

    return {
        "path": project,
        "name": project.name,
        "version": version,
        "artifact_count": len(md_files),
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
    """Claude Code names the per-project transcript dir after the absolute path."""
    slug = str(project.resolve()).replace("/", "-").replace("\\", "-")
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
    if artifacts.is_dir() and next(artifacts.glob("engagement-summary-*.txt"), None):
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
  max-width: 64rem; padding: 1.5rem 1.25rem 3rem; color: #1a1a1a; background: #f6f8fa; }
h1 { font-size: 1.3rem; border-bottom: 2px solid #0969da; padding-bottom: .4rem; }
h2 { font-size: .95rem; margin-top: 1.8rem; color: #57606a; text-transform: uppercase;
  letter-spacing: .08em; }
table { border-collapse: collapse; width: 100%; background: #fff; font-size: .85rem; }
th, td { border: 1px solid #dcdcdc; padding: .45rem .6rem; text-align: left;
  vertical-align: top; }
th { background: #f0f3f6; }
td.num { text-align: right; font-variant-numeric: tabular-nums; }
.ok { color: #1a7f37; font-weight: 600; }
.bad { color: #cf222e; font-weight: 600; }
.warn { color: #9a6700; font-weight: 600; }
.muted { color: #57606a; }
.note { font-size: .78rem; color: #57606a; margin-top: 1.6rem; line-height: 1.5; }
""".strip()


def _fmt(n: int) -> str:
    return f"{n:,}"


def render(projects: list[dict], usage_by_project: dict, generated: str) -> str:
    rows = []
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
        rows.append(
            f"<tr><td>{_E(p['name'])}</td>"
            f"<td>{basis_cell}</td>"
            f"<td>{_E(p['version'] or '-')}</td>"
            f"<td class='num'>{p['artifact_count']}</td>"
            f"<td class='num'>{len(p['emails'])}</td>"
            f"<td>{gate}</td><td>{map_cell}</td><td>{consent}</td></tr>"
        )
    project_table = (
        "<table><tr><th>Project</th><th>Found via</th><th>Version</th><th>Artifacts</th>"
        "<th>Closing emails</th><th>DoD gate</th><th>Codebase map</th><th>Exec consent</th></tr>"
        + "".join(rows)
        + "</table>"
    )

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
<h2>Working projects</h2>
{project_table}
<h2>Measured token usage (from session transcripts)</h2>
{cost_table}
{unparsable_note}
<p class="note">&#128202; Token counts are the API's own usage fields (measured); the
transcript format is internal to Claude Code and may change - parse gaps are shown, never
hidden. This page sees only this machine, and only sessions whose transcripts remain on
disk. It is read-only by design: management actions (granting consent, running engagements)
stay deliberate human acts in the terminal. Regenerate with
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
