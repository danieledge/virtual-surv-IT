"""render_findings report-shape tests: the findings-at-a-glance summary table, the fix-first
remediation-priority line, the Found/Reported/Filtered transparency line, and the optional
taxonomy-tags and fix-effort fields.

These pin the enhancements added on top of the canonical five-field finding block (which
tests/test_findings.py covers). The rule throughout: new fields are OPTIONAL and render only
when the pack supplies them, so a pack that predates them is byte-for-byte unaffected in the
finding blocks and simply omits the new sections it has no data for.
"""

from __future__ import annotations

from pathlib import Path

from scripts.findings_pack_io import read_pack, write_pack
from scripts.render_findings import _anchor, render

_ROOT = Path(__file__).resolve().parents[1]
_GOLD = read_pack(_ROOT / "docs" / "review" / "gold-findings.jsonl")


def _pack(**over):
    base = {
        "slug": "demo",
        "scope": "app.py",
        "mode": "audit",
        "verdict": "conditional",
        "kind": "review",
        "developer_guidance": "More tests.",
        "findings": [
            {
                "id": "F-01",
                "title": "Critical thing",
                "severity": "critical",
                "location": "app.py:10",
                "confidence": 96,
                "basis": "coded",
                "standard": "CWE-89",
                "problem": "p",
                "likely_cause": "l",
                "impact": "i",
                "fix": {"diff": "- a\n+ b", "why": "w"},
                "disposition": "open",
            },
            {
                "id": "F-02",
                "title": "Warning thing",
                "severity": "warning",
                "location": "app.py:20",
                "confidence": 82,
                "basis": "inferred",
                "standard": "CWE-20",
                "problem": "p",
                "likely_cause": "l",
                "impact": "i",
                "fix": {"diff": "- c\n+ d", "why": "w"},
                "disposition": "open",
            },
        ],
    }
    base.update(over)
    return base


# ---------------------------------------------------------------- at-a-glance summary table


def test_summary_table_has_a_row_per_finding_with_anchor_links():
    md = render(_pack())
    assert "## Findings at a glance" in md
    # each finding id links to its own anchor, and the anchor exists in the detail
    for fid in ("F-01", "F-02"):
        assert f"[{fid}](#{_anchor(fid)})" in md
        assert f'<a id="{_anchor(fid)}"></a>' in md


def test_summary_table_is_worst_first():
    md = render(_pack())
    table = md.split("## Findings at a glance", 1)[1]
    assert table.index("F-01") < table.index("F-02")  # critical row before warning row


def test_anchor_is_deterministic_from_id_not_title():
    assert _anchor("CR-01") == "f-cr-01"
    assert _anchor("F-01") == "f-f-01"


def test_no_summary_table_columns_for_absent_optional_fields():
    md = render(_pack())
    glance = md.split("## Findings at a glance", 1)[1].split("## ", 1)[0]
    assert "Tags" not in glance
    assert "Fix effort" not in glance


def test_empty_pack_has_no_glance_section_and_stays_explicit():
    md = render(_pack(findings=[]))
    assert "## Findings at a glance" not in md
    assert "_No findings._" in md


# ---------------------------------------------------------------- fix-first remediation priority


def test_fix_first_lists_open_blocking_by_severity_then_confidence():
    p = _pack()
    p["findings"][1]["confidence"] = 90  # still warning, below the critical
    md = render(p)
    line = next(line for line in md.splitlines() if line.startswith("**Fix first**"))
    assert line.index("F-01") < line.index("F-02")


def test_fix_first_excludes_non_open_and_non_blocking():
    p = _pack()
    p["findings"][0]["disposition"] = "fixed"  # critical no longer open
    p["findings"][1]["severity"] = "medium"  # non-blocking
    md = render(p)
    assert "**Fix first:** no open critical or warning findings." in md


# ------------------------------------------------------------- found/reported/filtered surfacing


def test_transparency_line_parsed_from_scoring_prose():
    md = render(_pack(scoring="scored by review-scorer: Found 5 · Reported 2 · Filtered 3."))
    assert "**Found 5**  ·  **Reported 2**  ·  **Filtered 3**" in md
    assert "> **Scoring & filtering.**" in md


def test_transparency_line_prefers_explicit_integer_fields():
    md = render(_pack(found=9, reported=2, filtered=7))
    assert "**Found 9**  ·  **Reported 2**  ·  **Filtered 7**" in md


def test_transparency_line_omitted_when_no_scoring_data():
    md = render(_pack())
    assert "**Found " not in md


# --------------------------------------------------------------- optional taxonomy tags + effort


def test_tags_render_in_block_and_table_only_when_present():
    p = _pack()
    p["findings"][0]["tags"] = ["CWE-89", "OWASP A03:2021"]
    md = render(p)
    assert "**Tags:** `CWE-89`" in md  # per-finding line
    glance = md.split("## Findings at a glance", 1)[1].split("## ", 1)[0]
    assert "Tags" in glance  # column appears
    assert "`OWASP A03:2021`" in glance


def test_effort_renders_on_disposition_line_and_table_when_present():
    p = _pack()
    p["findings"][0]["effort"] = "~15 min"
    md = render(p)
    assert "**Fix effort:** ~15 min" in md
    glance = md.split("## Findings at a glance", 1)[1].split("## ", 1)[0]
    assert "Fix effort" in glance


# ---------------------------------------------------------------- backward compatibility + HTML


def test_gold_pack_still_renders_the_five_fields_unchanged():
    md = render(_GOLD)
    # the canonical block is intact for a pack that carries none of the new optional fields
    assert md.count("**Standard:**") == len(_GOLD["findings"])
    assert "**Tags:**" not in md  # gold has no tags
    assert "**Fix effort:**" not in md  # gold has no effort


def test_legend_is_present():
    assert "**Legend** ·" in render(_pack())


def test_html_render_links_summary_row_to_finding_anchor(tmp_path):
    from scripts.render_findings import render_pack_file

    p = tmp_path / "data" / "findings-demo.jsonl"
    write_pack(p, _pack())
    out = render_pack_file(p, want_html=True)
    html = out.with_suffix(".html").read_text(encoding="utf-8")
    assert 'id="f-f-01"' in html
    assert 'href="#f-f-01"' in html


def test_optional_fields_pass_schema_validation(tmp_path):
    from scripts.validate_findings import load_and_validate

    p = _pack(found=6, reported=2, filtered=4)
    p["findings"][0]["tags"] = ["CWE-89"]
    p["findings"][0]["effort"] = "S"
    path = tmp_path / "data" / "findings-demo.jsonl"
    write_pack(path, p)
    assert load_and_validate(path) == []
