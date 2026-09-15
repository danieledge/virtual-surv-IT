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
* THE TEAM'S FORMAT. The pack is wrapped by render_html.render_document, the same
  letterhead, house CSS and footer as every other HTML artifact the engagement produces
  (2026-09-14 user report: the room "is not in the team's usual style and format" - it had
  carried a dark dashboard theme of its own). Only the few classes its summary cards and
  traceability chains need are added, in the house palette.
* VERIFIABLE. A manifest of every source file with its SHA-256, so a reader can confirm
  the pack matches the artifacts it was built from.
* NO COMPLIANCE CLAIM. It reports EVIDENCE COMPLETENESS - a mechanical present/absent
  checklist - never an "audit readiness" verdict. Formal MRM/regulatory scope for this
  work is contested (CLAUDE.md §8, and the repo already refuses "SR 11-7 compliant"), so
  a confident readiness percentage would be a claim this tool cannot support.

Off by default (reverted 2026-09-15; briefly on-by-default from the 2026-09-13 framework
review). A project opts in with `"evidence_room": true` in its .claude/team-preferences.json -
whether a project wants an auditor-facing pack rendered on every close is a fact about that
project's governance, not something to assume. `--force` renders anyway, for a one-off in a
project that hasn't opted in.

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


def _render_document():
    """render_html.render_document, resolved dual-mode (repo checkout or bundled plugin copy),
    the same way render_findings reaches render_html."""
    try:
        from scripts.render_html import render_document
    except ImportError:
        import sys as _sys

        _here = Path(__file__).resolve().parent
        if str(_here) not in _sys.path:
            _sys.path.insert(0, str(_here))
        from render_html import render_document  # type: ignore[no-redef]
    return render_document


def _vsit_paths():
    """The layout resolver (VSIT migration), imported lazily.

    Lazy because this file may run standalone from a bare clone where `scripts/` is not yet
    on sys.path. Searches its own directory AND a sibling `scripts/`, because several of
    these files also exist as staged copies under `scripts/staged_hooks/`."""
    import sys as _sys

    _here = Path(__file__).resolve().parent
    for _candidate in (_here, _here.parent, _here.parent / "scripts"):
        if (_candidate / "vsit_paths.py").is_file():
            if str(_candidate) not in _sys.path:
                _sys.path.insert(0, str(_candidate))
            break
    import vsit_paths

    return vsit_paths


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

# Matches findings-schema.json's severity enum exactly - no "high"/"low" bucket exists in the
# schema, so don't carry one here (dead weight left over from an earlier severity vocabulary).
_SEVERITY_ORDER = {"critical": 0, "warning": 1, "medium": 2, "style": 3}


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
    findings.sort(key=_finding_sort_key)
    return findings, envelope


def _finding_sort_key(f: dict) -> tuple:
    """Fix-first, same idea as render_findings' at-a-glance line: an evidence-room reader
    wants to see what's still OUTSTANDING before what's already settled. Open findings sort
    before fixed/accepted/deferred; within each group, worst severity first, then highest
    confidence - severity/confidence order alone (the old behaviour) let a fixed critical
    from a past engagement sit ahead of an open one from this one."""
    sev = _SEVERITY_ORDER.get(str(f.get("severity", "")).lower(), 9)
    is_open = str(f.get("disposition", "")).lower() == "open"
    confidence = f.get("confidence")
    return (0 if is_open else 1, sev, -(confidence if isinstance(confidence, int) else 0))


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


# Only what the house CSS (render_html._CSS) does not already have: the summary cards, the
# traceability chains and the state colours. Same palette as the letterhead, light first,
# dark under the same media query render_html uses, so the pack matches the documents beside it.
_EXTRA_CSS = """
.sub { color: #57606a; font-size: .9rem; margin: -.6rem 0 1.2rem; }
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(11rem, 1fr)); gap: .7rem;
  margin: 1rem 0; }
.card { border: 1px solid #d0d7de; border-radius: 6px; padding: .7rem .9rem; background: #f6f8fa; }
.card .n { font-size: 1.5rem; font-weight: 600; line-height: 1.2; }
.card .l { color: #57606a; font-size: .75rem; text-transform: uppercase; letter-spacing: .05em; }
.mono { font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace; font-size: .9em; }
.ok { color: #1a7f37; } .warn { color: #9a6700; } .bad { color: #cf222e; } .dim { color: #57606a; }
.chain { border: 1px solid #d0d7de; border-left: 4px solid #0969da; border-radius: 6px;
  padding: .6rem .9rem; margin: .6rem 0; background: #f6f8fa; }
.chain .step { color: #57606a; font-size: .9rem; }
.chain .step b { color: inherit; font-weight: 600; }
.chain.gap { border-left-color: #9a6700; }
@media (prefers-color-scheme: dark) {
  .sub, .card .l, .dim, .chain .step { color: #9da7b3; }
  .card, .chain { background: #161b22; border-color: #30363d; }
  .chain { border-left-color: #539bf5; } .chain.gap { border-left-color: #d29922; }
  .ok { color: #3fb950; } .warn { color: #d29922; } .bad { color: #f85149; }
}
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
        f"<h1>Evidence Room: {_esc(title)}</h1>"
        f"<p class='sub'><span class='mono'>{_esc(slug)}</span> "
        f"&middot; status {_esc(status)}"
        + (f" &middot; opened {_esc(eng.get('opened'))}" if eng.get("opened") else "")
        + (f" &middot; closed {_esc(eng.get('closed'))}" if eng.get("closed") else "")
        + "</p>"
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
            "<p class='dim'>Ordered fix-first: open findings before fixed/accepted/deferred, "
            "worst severity first within each group.</p>"
            "<table><tr><th>ID</th><th>Severity</th><th>Title</th><th>Location</th>"
            "<th>Basis</th><th>Disposition</th></tr>"
        )
        for f in findings:
            sev = str(f.get("severity") or "")
            cls = (
                "bad"
                if sev.lower() == "critical"
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
        # Roster names read as AI agents (operating guide "Voice, names & console"): the 🤖
        # marker on each name and the team named in full.
        parts.append(
            "<p class='dim'>Delivery team: "
            + ", ".join(f"<b>\U0001f916 {_esc(m)}</b>" for m in team)
            + ", all AI agents of Virtual Surveillance IT.</p>"
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
    footer_bits = (
        "Generated by the compliance surveillance engineering team (AI agents, Virtual "
        "Surveillance IT) from the engagement's own artifacts.",
        "Derived view only: the artifacts and <span class='mono'>engagement-state.json</span> "
        "remain authoritative.",
        "Human sign-off is recorded in the delivery report.",
    )
    meta = f"Evidence Room · {slug} · status {status}"
    return _render_document()(
        "".join(parts),
        f"Evidence Room: {title}",
        meta=meta,
        footer_bits=footer_bits,
        extra_css=_EXTRA_CSS,
    )


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
        prefs = _read_json(_vsit_paths().preferences_file(project)) or {}
        # OFF BY DEFAULT (reverted 2026-09-15, user request - it had briefly been on-by-default
        # since the 2026-09-13 framework review). A project must opt IN with
        # '"evidence_room": true'; anything else (absent, false, unreadable prefs) skips.
        if not (isinstance(prefs, dict) and prefs.get("evidence_room") is True):
            return 0, (
                "evidence room is off by default for this project (set "
                "'\"evidence_room\": true' in .claude/team-preferences.json to render it at "
                "close), or pass --force for a one-off"
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
