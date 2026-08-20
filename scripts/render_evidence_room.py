#!/usr/bin/env python3
"""Evidence Room - one self-contained HTML pack per engagement (2026-08-19 user request).

The problem: a finished engagement leaves a FOLDER (state file, brief, RTM, review
report, QA handover, decision log, findings JSONL, delivery report). Every piece is
correct and the DoD already enforces that they exist, but the RELATIONSHIPS between them
live implicitly across a dozen files, so anyone who wasn't there - an auditor, a
stakeholder, a colleague inheriting the work - has to reconstruct the story by opening
each one. The rigour is real and invisible.

This assembles the same material into the shape an outside reader needs. Design rules,
each load-bearing:

* DERIVED, NEVER AUTHORED. Every value comes from a file on disk. The pack can therefore
  never claim more than the engagement actually produced - a missing QA handover shows
  as a gap, which is the point of an evidence pack rather than a brochure.
* DETERMINISTIC. No model runs at render time: it is a renderer in the same family as
  render_html/check_artifacts, so it is free, reproducible and testable.
* SELF-CONTAINED. Inline CSS, no external assets, no network, no server - a single file
  that opens offline, attaches to an email, or rides a Jira comment.
* VERIFIABLE. A manifest of every source file with its SHA-256, so a reader can confirm
  the pack matches the artifacts it was built from.
* NO COMPLIANCE CLAIM. It reports EVIDENCE COMPLETENESS - a mechanical present/absent
  checklist - never an "audit readiness" verdict. Formal MRM/regulatory scope for this
  work is contested (CLAUDE.md §8, and the repo already refuses "SR 11-7 compliant"), so
  a confident readiness percentage would be a claim this tool cannot support.

Gated per project: `"evidence_room": true` in the working project's
.claude/team-preferences.json (off by default, no machine tier - whether a project wants
an auditor-facing pack is a fact about that project's governance). `--force` renders
anyway, for a one-off in a project that hasn't opted in.

Usage:
    python -m scripts.render_evidence_room artifacts/<slug>
    python -m scripts.render_evidence_room artifacts/<slug> --force
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import sys
from pathlib import Path

# Every artifact worth naming in the pack, with the section it belongs to and whether
# its absence is a genuine gap. "expected" drives the completeness checklist; anything
# not expected is listed when present and simply not mentioned when absent.
_EVIDENCE_ITEMS = (
    ("engagement-brief.md", "Scope & assumptions", True),
    ("rtm.md", "Requirements traceability", True),
    ("qa-handover.md", "Independent QA evidence", True),
    ("delivery-report.md", "Delivery report", True),
    ("decision-log.md", "Decision register", False),
    ("user-stories.md", "Requirements", False),
    ("START-HERE.md", "Living index", False),
)

_SEVERITY_ORDER = {"critical": 0, "high": 1, "warning": 2, "medium": 3, "low": 4, "style": 5}


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None


def _sha256(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ""


def load_findings(workspace: Path) -> tuple[list[dict], dict]:
    """Every finding across every pack in data/, plus the first envelope seen.

    Packs are JSONL: envelope line first (pack fields except `findings`), then one
    finding per line. A component-split review leaves several packs; all are read, in
    sorted order, so the pack the orchestrator merged and the per-component ones cannot
    disagree about what exists. Unparseable lines are skipped rather than fatal - an
    evidence pack that refuses to render because one line is malformed is worse than one
    that renders what it can."""
    findings: list[dict] = []
    envelope: dict = {}
    data_dir = workspace / "data"
    if not data_dir.is_dir():
        return findings, envelope
    seen_ids: set[str] = set()
    for pack in sorted(data_dir.glob("findings-*.jsonl")):
        for line in pack.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            if not isinstance(obj, dict):
                continue
            if "findings" in obj or ("id" not in obj and "title" not in obj):
                if not envelope:
                    envelope = obj
                continue
            fid = str(obj.get("id") or obj.get("title") or len(findings))
            if fid in seen_ids:
                continue  # merged canonical pack + its component packs overlap by design
            seen_ids.add(fid)
            findings.append(obj)
    findings.sort(key=lambda f: _SEVERITY_ORDER.get(str(f.get("severity", "")).lower(), 9))
    return findings, envelope


def completeness(workspace: Path, state: dict, findings: list[dict]) -> list[dict]:
    """The mechanical checklist: one row per expected evidence item, present or not.

    Deliberately NOT scored as readiness - each row is a fact ("this file exists"), and
    the summary is a count of facts, so a reader can audit the audit."""
    rows = []
    for name, label, expected in _EVIDENCE_ITEMS:
        path = workspace / name
        if not expected and not path.is_file():
            continue
        rows.append(
            {
                "item": label,
                "file": name,
                "present": path.is_file(),
                "expected": expected,
                "bytes": path.stat().st_size if path.is_file() else 0,
            }
        )
    rows.append(
        {
            "item": "Findings register",
            "file": "data/findings-*.jsonl",
            "present": bool(findings),
            "expected": True,
            "bytes": len(findings),
        }
    )
    team = state.get("team") or []
    rows.append(
        {
            "item": "Named delivery team",
            "file": "engagement-state.json",
            "present": bool(team),
            "expected": True,
            "bytes": len(team),
        }
    )
    return rows


def _esc(value) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


_CSS = """
:root{--bg:#0f1115;--fg:#e6e6e6;--dim:#9aa0aa;--line:#262b33;--accent:#4aa3ff;
--ok:#3fb950;--warn:#d29922;--bad:#f85149;--card:#151922}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);
font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
.wrap{max-width:1040px;margin:0 auto;padding:32px 20px 72px}
h1{font-size:26px;margin:0 0 4px}
h2{font-size:17px;margin:36px 0 10px;padding-bottom:6px;border-bottom:1px solid var(--line)}
.sub{color:var(--dim);font-size:13px;margin-bottom:22px}
.bar{display:inline-block;padding:2px 9px;border-radius:11px;font-size:12px;
border:1px solid var(--line);background:var(--card);color:var(--dim)}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px;margin:18px 0}
.card{background:var(--card);border:1px solid var(--line);border-radius:9px;padding:13px 15px}
.card .n{font-size:23px;font-weight:600}
.card .l{color:var(--dim);font-size:12px;text-transform:uppercase;letter-spacing:.6px}
table{width:100%;border-collapse:collapse;margin:10px 0;font-size:14px}
th,td{text-align:left;padding:7px 9px;border-bottom:1px solid var(--line);vertical-align:top}
th{color:var(--dim);font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:.5px}
code,.mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12.5px}
.ok{color:var(--ok)}.warn{color:var(--warn)}.bad{color:var(--bad)}.dim{color:var(--dim)}
.chain{background:var(--card);border:1px solid var(--line);border-left:3px solid var(--accent);
border-radius:7px;padding:11px 14px;margin:9px 0}
.chain .step{color:var(--dim);font-size:13px}
.chain .step b{color:var(--fg);font-weight:600}
.gap{border-left-color:var(--warn)}
footer{margin-top:44px;padding-top:14px;border-top:1px solid var(--line);
color:var(--dim);font-size:12px}
"""


def _card(number, label, cls="") -> str:
    return (
        f'<div class="card"><div class="n {cls}">{_esc(number)}</div>'
        f'<div class="l">{_esc(label)}</div></div>'
    )


def build_html(workspace: Path, state: dict, findings: list[dict], envelope: dict) -> str:
    eng = state.get("engagement") or {}
    slug = eng.get("slug") or workspace.name
    title = eng.get("title") or slug
    status = state.get("status") or "unknown"
    rows = completeness(workspace, state, findings)
    expected_rows = [r for r in rows if r["expected"]]
    present = sum(1 for r in expected_rows if r["present"])
    open_findings = [
        f for f in findings if str(f.get("disposition", "")).lower().startswith(("open", "🔴"))
    ]
    parts: list[str] = []
    parts.append(
        f"<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>Evidence Room - {_esc(title)}</title><style>{_CSS}</style></head><body>"
        f"<div class='wrap'><h1>{_esc(title)}</h1>"
        f"<div class='sub'>Evidence Room &middot; <span class='mono'>{_esc(slug)}</span> "
        f"&middot; status {_esc(status)}"
        + (f" &middot; opened {_esc(eng.get('opened'))}" if eng.get("opened") else "")
        + (f" &middot; closed {_esc(eng.get('closed'))}" if eng.get("closed") else "")
        + "</div>"
    )
    # Summary cards - counts of facts, never a readiness verdict.
    parts.append("<div class='grid'>")
    parts.append(
        _card(
            f"{present}/{len(expected_rows)}",
            "evidence items present",
            "ok" if present == len(expected_rows) else "warn",
        )
    )
    parts.append(_card(len(findings), "findings recorded"))
    parts.append(_card(len(open_findings), "findings open", "warn" if open_findings else "ok"))
    parts.append(
        _card(
            len(state.get("outstanding") or []),
            "outstanding items",
            "warn" if state.get("outstanding") else "ok",
        )
    )
    parts.append("</div>")
    parts.append(
        "<p class='dim'>Evidence completeness is a mechanical present/absent count of the "
        "items this engagement was expected to produce. It is not an audit-readiness or "
        "compliance verdict, and makes no regulatory claim.</p>"
    )

    # --- completeness -------------------------------------------------------
    parts.append(
        "<h2>Evidence completeness</h2><table><tr><th>Item</th><th>Source</th><th>State</th></tr>"
    )
    for r in rows:
        mark = (
            "<span class='ok'>present</span>"
            if r["present"]
            else "<span class='bad'>missing</span>"
        )
        if not r["present"] and not r["expected"]:
            mark = "<span class='dim'>n/a</span>"
        parts.append(
            f"<tr><td>{_esc(r['item'])}</td><td class='mono dim'>{_esc(r['file'])}</td>"
            f"<td>{mark}</td></tr>"
        )
    parts.append("</table>")

    # --- traceability -------------------------------------------------------
    parts.append("<h2>Traceability</h2>")
    rtm = workspace / "rtm.md"
    if rtm.is_file():
        parts.append(
            f"<p class='dim'>Requirement &rarr; implementation &rarr; test &rarr; obligation, "
            f"as recorded in <span class='mono'>rtm.md</span> "
            f"({rtm.stat().st_size} bytes). The chains below are drawn from the findings "
            f"register; the RTM remains the authoritative matrix.</p>"
        )
    else:
        parts.append(
            "<div class='chain gap'><div class='step'><b>Gap:</b> no <span class='mono'>rtm.md"
            "</span> in this workspace, so requirement&rarr;test traceability cannot be shown "
            "from evidence.</div></div>"
        )
    for f in findings[:12]:
        steps = []
        if f.get("standard"):
            steps.append(f"standard <b>{_esc(f['standard'])}</b>")
        if f.get("location"):
            steps.append(f"location <b>{_esc(f['location'])}</b>")
        if f.get("basis"):
            steps.append(f"evidence <b>{_esc(f['basis'])}</b>")
        if f.get("disposition"):
            steps.append(f"disposition <b>{_esc(f['disposition'])}</b>")
        if not steps:
            continue
        parts.append(
            f"<div class='chain'><div class='step'><b>{_esc(f.get('id') or '')}</b> "
            f"{_esc(f.get('title') or '')}</div>"
            f"<div class='step'>{' &rarr; '.join(steps)}</div></div>"
        )

    # --- findings -----------------------------------------------------------
    parts.append("<h2>Findings register</h2>")
    if findings:
        parts.append(
            "<table><tr><th>ID</th><th>Severity</th><th>Title</th><th>Location</th>"
            "<th>Basis</th><th>Disposition</th></tr>"
        )
        for f in findings:
            sev = str(f.get("severity") or "")
            cls = (
                "bad"
                if sev.lower() in ("critical", "high")
                else ("warn" if sev.lower() in ("warning", "medium") else "dim")
            )
            parts.append(
                f"<tr><td class='mono'>{_esc(f.get('id'))}</td>"
                f"<td class='{cls}'>{_esc(sev)}</td><td>{_esc(f.get('title'))}</td>"
                f"<td class='mono dim'>{_esc(f.get('location'))}</td>"
                f"<td>{_esc(f.get('basis'))}</td><td>{_esc(f.get('disposition'))}</td></tr>"
            )
        parts.append("</table>")
        if envelope.get("scoring"):
            parts.append(f"<p class='dim'>Scoring provenance: {_esc(envelope['scoring'])}</p>")
    else:
        parts.append("<p class='dim'>No findings register in this workspace.</p>")

    # --- decisions, gates, team --------------------------------------------
    parts.append("<h2>Decisions &amp; gates</h2>")
    decisions = state.get("decisions") or {}
    if decisions:
        parts.append("<table><tr><th>Decision</th><th>Recorded</th></tr>")
        for key, value in decisions.items():
            parts.append(f"<tr><td>{_esc(key)}</td><td>{_esc(value)}</td></tr>")
        parts.append("</table>")
    else:
        parts.append("<p class='dim'>No decisions recorded.</p>")
    consent = state.get("consent_outcome")
    parts.append(
        f"<p class='dim'>Execution-consent outcome: <b>{_esc(consent or 'not recorded')}</b>. "
        "A recorded outcome is never a grant - execution consent lives only in the "
        "human-created marker.</p>"
    )
    team = state.get("team") or []
    if team:
        parts.append(
            "<p class='dim'>Delivery team: "
            + ", ".join(f"<b>{_esc(m)}</b>" for m in team)
            + " &mdash; all AI agents of Virtual Surveillance IT.</p>"
        )

    # --- residual risk ------------------------------------------------------
    outstanding = state.get("outstanding") or []
    parts.append("<h2>Residual risk &amp; outstanding</h2>")
    if outstanding:
        parts.append("<table><tr><th>Outstanding item</th></tr>")
        for item in outstanding:
            text = item.get("item") if isinstance(item, dict) else item
            parts.append(f"<tr><td>{_esc(text)}</td></tr>")
        parts.append("</table>")
    else:
        parts.append("<p class='dim'>No outstanding items recorded.</p>")

    # --- manifest -----------------------------------------------------------
    parts.append(
        "<h2>Manifest</h2><p class='dim'>Every source file this pack was built "
        "from, with its SHA-256, so a reader can verify the pack matches the "
        "artifacts.</p><table><tr><th>File</th><th>Bytes</th><th>SHA-256</th></tr>"
    )
    for path in sorted(workspace.rglob("*")):
        if not path.is_file() or path.name.startswith("EVIDENCE-ROOM"):
            continue
        rel = path.relative_to(workspace).as_posix()
        parts.append(
            f"<tr><td class='mono'>{_esc(rel)}</td><td class='dim'>{path.stat().st_size}</td>"
            f"<td class='mono dim'>{_esc(_sha256(path)[:16])}&hellip;</td></tr>"
        )
    parts.append("</table>")
    parts.append(
        "<footer>Generated by Virtual Surv-IT from the engagement's own artifacts. "
        "Derived view only - the artifacts and <span class='mono'>engagement-state.json"
        "</span> remain authoritative. Produced by AI agents; human sign-off is recorded "
        "in the delivery report.</footer></div></body></html>"
    )
    return "".join(parts)


def render(workspace: Path, force: bool = False) -> tuple[int, str]:
    """(exit_code, message). Never raises for expected conditions - a disabled project,
    a missing workspace and an unreadable state file each get their own clear message."""
    workspace = workspace.expanduser().resolve()
    if not workspace.is_dir():
        return 1, f"not a directory: {workspace}"
    state = _read_json(workspace / "engagement-state.json")
    if not isinstance(state, dict):
        return 1, f"no readable engagement-state.json in {workspace}"
    if not force:
        # The project gate. Walk up from the workspace to the project root (artifacts/
        # sits under it) rather than assuming a cwd.
        project = workspace.parent.parent if workspace.parent.name == "artifacts" else workspace
        prefs = _read_json(project / ".claude" / "team-preferences.json") or {}
        if not (isinstance(prefs, dict) and prefs.get("evidence_room") is True):
            return 0, (
                "evidence room is off for this project - enable it with "
                "'\"evidence_room\": true' in .claude/team-preferences.json "
                "(virt-surv go, [c]), or pass --force for a one-off"
            )
    findings, envelope = load_findings(workspace)
    out = (
        workspace
        / f"EVIDENCE-ROOM-{(state.get('engagement') or {}).get('slug') or workspace.name}.html"
    )
    out.write_text(build_html(workspace, state, findings, envelope), encoding="utf-8")
    return 0, f"evidence room: {out}"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Render an engagement's Evidence Room (HTML).")
    ap.add_argument("workspace", help="the engagement workspace, e.g. artifacts/<slug>")
    ap.add_argument(
        "--force",
        action="store_true",
        help="render even when the project has not opted in (evidence_room)",
    )
    args = ap.parse_args(argv)
    code, message = render(Path(args.workspace), force=args.force)
    print(message)
    return code


if __name__ == "__main__":
    sys.exit(main())
