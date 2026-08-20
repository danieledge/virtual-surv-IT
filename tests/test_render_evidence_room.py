"""The Evidence Room renderer (scripts/render_evidence_room.py, 2026-08-19).

A derived, deterministic, self-contained HTML pack per engagement. These tests pin the
properties that make it trustworthy rather than merely pretty:

* the PROJECT GATE (off by default; --force is the only bypass),
* DERIVED-ONLY output (a gap in the evidence shows as a gap, never as a pass),
* NO COMPLIANCE CLAIM (completeness counts, never an audit-readiness verdict),
* SELF-CONTAINED (no external asset can smuggle in a network dependency),
* ESCAPING (artifact text is untrusted content and must never become live HTML),
* robustness against the malformed packs a real workspace eventually produces.
"""

from __future__ import annotations

import json
from pathlib import Path

from scripts.render_evidence_room import (
    build_html,
    completeness,
    load_findings,
    main,
    render,
)

_STATE = {
    "status": "closed",
    "engagement": {"slug": "spoofing-v2", "title": "Spoofing detection v2", "opened": "2026-08-01"},
    "team": ["Amara", "Mateo", "Linh"],
    "decisions": {"go-ahead": "Proceed as briefed (user, 2026-08-01)"},
    "outstanding": [],
    "consent_outcome": "declined",
}


def _workspace(tmp_path: Path, *, opted_in=True, state=None, files=(), findings=()) -> Path:
    project = tmp_path / "proj"
    ws = project / "artifacts" / "spoofing-v2"
    ws.mkdir(parents=True)
    (project / ".claude").mkdir(parents=True, exist_ok=True)
    (project / ".claude" / "team-preferences.json").write_text(
        json.dumps({"evidence_room": True} if opted_in else {}), encoding="utf-8"
    )
    (ws / "engagement-state.json").write_text(
        json.dumps(state if state is not None else _STATE), encoding="utf-8"
    )
    for name in files:
        (ws / name).write_text(f"# {name}\n", encoding="utf-8")
    if findings:
        (ws / "data").mkdir(exist_ok=True)
        lines = [json.dumps({"slug": "spoofing-v2", "scoring": "scored by review-scorer"})]
        lines += [json.dumps(f) for f in findings]
        (ws / "data" / "findings-spoofing-v2.jsonl").write_text(
            "\n".join(lines) + "\n", encoding="utf-8"
        )
    return ws


def _rendered(ws: Path) -> str:
    return next(ws.glob("EVIDENCE-ROOM-*.html")).read_text(encoding="utf-8")


# --- the project gate ---------------------------------------------------------------


def test_disabled_project_renders_nothing_and_says_why(tmp_path):
    ws = _workspace(tmp_path, opted_in=False)
    code, message = render(ws)
    assert code == 0, "a disabled project is a normal outcome, not an error"
    assert not list(ws.glob("EVIDENCE-ROOM-*.html")), "wrote a pack a project never opted into"
    assert "evidence_room" in message and "--force" in message


def test_force_overrides_the_gate(tmp_path):
    ws = _workspace(tmp_path, opted_in=False)
    code, _ = render(ws, force=True)
    assert code == 0 and list(ws.glob("EVIDENCE-ROOM-*.html"))


def test_opted_in_project_renders(tmp_path):
    ws = _workspace(tmp_path)
    code, message = render(ws)
    assert code == 0 and "EVIDENCE-ROOM-spoofing-v2.html" in message
    assert list(ws.glob("EVIDENCE-ROOM-*.html"))


def test_gate_reads_the_project_root_not_the_cwd(tmp_path, monkeypatch):
    """The workspace is artifacts/<slug>/, so the preference lives two levels up. A
    cwd-relative lookup would silently render for any project you happened to be in."""
    ws = _workspace(tmp_path, opted_in=False)
    elsewhere = tmp_path / "somewhere-else"
    (elsewhere / ".claude").mkdir(parents=True)
    (elsewhere / ".claude" / "team-preferences.json").write_text(
        json.dumps({"evidence_room": True}), encoding="utf-8"
    )
    monkeypatch.chdir(elsewhere)
    code, message = render(ws)
    assert code == 0 and not list(ws.glob("EVIDENCE-ROOM-*.html")), message


# --- derived-only: gaps stay visible -------------------------------------------------


def test_missing_evidence_shows_as_missing(tmp_path):
    """The whole point of an evidence pack: absent QA must read as absent."""
    ws = _workspace(tmp_path, files=["engagement-brief.md"])
    render(ws)
    page = _rendered(ws)
    assert "qa-handover.md" in page and "missing" in page
    # Derived, not hardcoded: the brief and the named team are present, the other four
    # expected items are not. (An earlier hardcoded "1/6" here was simply wrong - the
    # state fixture carries a team - which is exactly how a hand-written count drifts.)
    rows = completeness(ws, _STATE, [])
    expected = [r for r in rows if r["expected"]]
    present = sum(1 for r in expected if r["present"])
    assert present == 2 and len(expected) == 6
    assert f"{present}/{len(expected)}" in page


def test_full_evidence_reports_complete(tmp_path):
    ws = _workspace(
        tmp_path,
        files=["engagement-brief.md", "rtm.md", "qa-handover.md", "delivery-report.md"],
        findings=[{"id": "SEC-01", "title": "x", "severity": "warning"}],
    )
    render(ws)
    page = _rendered(ws)
    assert "6/6" in page
    assert "missing" not in page.split("Evidence completeness")[1].split("</table>")[0]


def test_absent_rtm_is_named_as_a_traceability_gap(tmp_path):
    ws = _workspace(tmp_path, files=["engagement-brief.md"])
    render(ws)
    assert "traceability cannot be shown" in _rendered(ws)


# --- no compliance claim -------------------------------------------------------------


def test_pack_makes_no_audit_readiness_or_compliance_claim(tmp_path):
    """CLAUDE.md §8 forbids compliance claims, and a confident readiness score is exactly
    that. The pack counts evidence; it never grades the regulator's answer."""
    ws = _workspace(
        tmp_path,
        files=["engagement-brief.md", "rtm.md", "qa-handover.md", "delivery-report.md"],
    )
    render(ws)
    page = _rendered(ws).lower()
    for banned in ("audit readiness", "audit-ready", "compliant", "sr 11-7", "certif"):
        assert banned not in page, f"pack claims {banned!r}"
    assert "not an audit-readiness or compliance verdict" in page


def test_consent_outcome_is_never_presented_as_a_grant(tmp_path):
    ws = _workspace(tmp_path)
    render(ws)
    assert "never a grant" in _rendered(ws)


# --- self-contained + escaping -------------------------------------------------------


def test_pack_is_self_contained(tmp_path):
    """No external asset of any kind: the pack must open offline, from an email
    attachment, with no network."""
    ws = _workspace(tmp_path, files=["rtm.md"])
    render(ws)
    page = _rendered(ws)
    for smell in ("http://", "https://", "<script", "src=", "@import", "<link"):
        assert smell not in page, f"pack reaches outside itself: {smell!r}"


def test_artifact_text_is_escaped_not_executed(tmp_path):
    """Findings text is untrusted content (CLAUDE.md §7) - a title carrying markup must
    render as characters, never as live HTML."""
    ws = _workspace(
        tmp_path,
        findings=[
            {
                "id": "X<1>",
                "title": "<img src=x onerror=alert(1)>",
                "severity": "critical",
                "location": "a.py:1",
            }
        ],
    )
    render(ws)
    page = _rendered(ws)
    assert "<img src=x" not in page
    assert "&lt;img src=x" in page


# --- findings assembly ---------------------------------------------------------------


def test_findings_are_read_deduped_and_severity_ordered(tmp_path):
    ws = _workspace(
        tmp_path,
        findings=[
            {"id": "A", "title": "low one", "severity": "low"},
            {"id": "B", "title": "critical one", "severity": "critical"},
            {"id": "A", "title": "dupe of A", "severity": "low"},
        ],
    )
    findings, envelope = load_findings(ws)
    assert [f["id"] for f in findings] == ["B", "A"], "severity order / dedup failed"
    assert envelope.get("scoring"), "envelope line was not recognised"


def test_component_split_packs_are_all_read(tmp_path):
    ws = _workspace(tmp_path)
    (ws / "data").mkdir()
    for component in ("api", "rules"):
        (ws / "data" / f"findings-spoofing-v2-{component}.jsonl").write_text(
            json.dumps({"slug": "spoofing-v2"})
            + "\n"
            + json.dumps({"id": component.upper(), "title": component, "severity": "warning"})
            + "\n",
            encoding="utf-8",
        )
    findings, _ = load_findings(ws)
    assert {f["id"] for f in findings} == {"API", "RULES"}


def test_malformed_pack_lines_are_skipped_not_fatal(tmp_path):
    ws = _workspace(tmp_path)
    (ws / "data").mkdir()
    (ws / "data" / "findings-spoofing-v2.jsonl").write_text(
        "\n".join(
            [
                json.dumps({"slug": "s"}),
                "{not json",
                "",
                "[1,2,3]",
                json.dumps({"id": "OK", "title": "survivor", "severity": "high"}),
            ]
        ),
        encoding="utf-8",
    )
    findings, _ = load_findings(ws)
    assert [f["id"] for f in findings] == ["OK"]


# --- manifest + determinism ----------------------------------------------------------


def test_manifest_lists_sources_with_hashes_and_excludes_itself(tmp_path):
    ws = _workspace(tmp_path, files=["rtm.md"])
    render(ws)
    page = _rendered(ws)
    assert "rtm.md" in page and "engagement-state.json" in page
    assert "SHA-256" in page
    assert "EVIDENCE-ROOM-spoofing-v2.html</td>" not in page, "pack lists itself in its manifest"


def test_render_is_deterministic(tmp_path):
    ws = _workspace(tmp_path, files=["rtm.md"], findings=[{"id": "A", "title": "t"}])
    render(ws)
    first = _rendered(ws)
    render(ws)
    assert _rendered(ws) == first, "two renders of unchanged input differ"


# --- failure modes -------------------------------------------------------------------


def test_missing_workspace_is_a_clear_error(tmp_path):
    code, message = render(tmp_path / "nope")
    assert code == 1 and "not a directory" in message


def test_unreadable_state_is_a_clear_error(tmp_path):
    ws = tmp_path / "artifacts" / "x"
    ws.mkdir(parents=True)
    (ws / "engagement-state.json").write_text("{not json", encoding="utf-8")
    code, message = render(ws, force=True)
    assert code == 1 and "engagement-state.json" in message


def test_cli_returns_the_exit_code(tmp_path, capsys):
    ws = _workspace(tmp_path)
    assert main([str(ws)]) == 0
    assert "EVIDENCE-ROOM" in capsys.readouterr().out
    assert main([str(tmp_path / "missing")]) == 1


def test_build_html_needs_no_optional_dependency(tmp_path):
    """Stdlib only - the pack must render in a plugin install with nothing pip-installed
    (the same constraint the vendored converter exists for)."""
    ws = _workspace(tmp_path)
    page = build_html(ws, _STATE, [], {})
    assert page.startswith("<!doctype html>") and page.rstrip().endswith("</html>")
