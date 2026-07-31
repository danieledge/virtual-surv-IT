"""check_findings_render_freshness() (scripts/check_artifacts.py): the mechanical piece
of close-time reconciliation (audit finding #3, 2026-07-30). A 2026-07-25 live failure
shipped a stale finding count and tally because the rendered REVIEW-<slug>.md was never
re-run after the findings pack changed - this catches exactly that drift class."""

from __future__ import annotations

import json

from scripts.check_artifacts import check_findings_render_freshness
from scripts.render_findings import render

VALID_FINDING = {
    "id": "F-001",
    "title": "Example",
    "severity": "warning",
    "location": "app.py:10",
    "basis": "measured",
    "standard": "s",
    "problem": "p",
    "likely_cause": "l",
    "impact": "i",
    "fix": {"diff": "- a\n+ b", "why": "w"},
    "disposition": "open",
}


def _pack(slug="demo", findings=None, kind="review"):
    return {
        "slug": slug,
        "scope": "app.py",
        "mode": "quick",
        "verdict": "conditional",
        "kind": kind,
        "developer_guidance": "Consider more tests.",
        "findings": findings if findings is not None else [dict(VALID_FINDING)],
    }


def _write(tmp_path, pack, render_it=True):
    data_dir = tmp_path / "data"
    data_dir.mkdir(exist_ok=True)
    pack_path = data_dir / f"findings-{pack['slug']}.json"
    pack_path.write_text(json.dumps(pack), encoding="utf-8")
    if render_it:
        (tmp_path / f"REVIEW-{pack['slug']}.md").write_text(render(pack), encoding="utf-8")
    return pack_path


def test_fresh_render_passes(tmp_path):
    _write(tmp_path, _pack())
    assert check_findings_render_freshness(tmp_path) == []


def test_no_findings_pack_is_silent(tmp_path):
    assert check_findings_render_freshness(tmp_path) == []


def test_no_render_yet_is_not_flagged_here(tmp_path):
    """A missing render is a different, already-covered check (MISSING-HTML-style) -
    this check only fires once a render EXISTS and has gone stale."""
    _write(tmp_path, _pack(), render_it=False)
    assert check_findings_render_freshness(tmp_path) == []


def test_pack_grew_a_finding_after_the_last_render(tmp_path):
    """The exact live failure: a fix cycle added/changed a finding, the render never
    caught up - a fresh render is written, then the pack is mutated afterward."""
    pack = _pack()
    pack_path = _write(tmp_path, pack)
    grown = json.loads(pack_path.read_text(encoding="utf-8"))
    grown["findings"].append({**VALID_FINDING, "id": "F-002", "title": "New one"})
    pack_path.write_text(json.dumps(grown), encoding="utf-8")
    findings = check_findings_render_freshness(tmp_path)
    assert any("STALE-FINDINGS-RENDER" in f and "F-002" in f for f in findings)


def test_pack_lost_a_finding_after_the_last_render(tmp_path):
    pack = _pack(findings=[dict(VALID_FINDING), {**VALID_FINDING, "id": "F-002"}])
    pack_path = _write(tmp_path, pack)
    shrunk = json.loads(pack_path.read_text(encoding="utf-8"))
    shrunk["findings"] = shrunk["findings"][:1]
    pack_path.write_text(json.dumps(shrunk), encoding="utf-8")
    findings = check_findings_render_freshness(tmp_path)
    assert any("STALE-FINDINGS-RENDER" in f and "F-002" in f for f in findings)


def test_disposition_changed_after_render_flags_count_mismatch(tmp_path):
    """Same finding IDs, but a disposition flipped (e.g. a fix landed) without a
    re-render - the tally in the .md is now stale, exactly the close-checklist's
    'one authoritative number everywhere' rule, mechanised."""
    pack = _pack()
    pack_path = _write(tmp_path, pack)
    changed = json.loads(pack_path.read_text(encoding="utf-8"))
    changed["findings"][0]["disposition"] = "fixed"
    pack_path.write_text(json.dumps(changed), encoding="utf-8")
    findings = check_findings_render_freshness(tmp_path)
    assert any("COUNT-MISMATCH" in f for f in findings)


def test_stale_id_set_skips_the_tally_check_to_avoid_double_reporting(tmp_path):
    pack = _pack()
    pack_path = _write(tmp_path, pack)
    grown = json.loads(pack_path.read_text(encoding="utf-8"))
    grown["findings"].append({**VALID_FINDING, "id": "F-002"})
    pack_path.write_text(json.dumps(grown), encoding="utf-8")
    findings = check_findings_render_freshness(tmp_path)
    codes = [f.split(":")[0] for f in findings]
    assert codes.count("STALE-FINDINGS-RENDER") == 1
    assert "COUNT-MISMATCH" not in codes


def test_unreadable_pack_fails_open(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "findings-broken.json").write_text("{not json", encoding="utf-8")
    assert check_findings_render_freshness(tmp_path) == []


def test_security_audit_kind_uses_its_own_prefix(tmp_path):
    pack = _pack(kind="security-audit")
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    pack_path = data_dir / f"findings-{pack['slug']}.json"
    pack_path.write_text(json.dumps(pack), encoding="utf-8")
    (tmp_path / "SECURITY-AUDIT-demo.md").write_text(render(pack), encoding="utf-8")
    assert check_findings_render_freshness(tmp_path) == []
