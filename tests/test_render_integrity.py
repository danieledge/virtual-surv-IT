"""check_render_integrity() (scripts/check_artifacts.py): three render-only defects the
incident log recorded as invisible in source and caught only by hand (2026-09) - a
duplicate `[TOC]` marker renders the table of contents twice, a markdown link points at an
anchor no heading in the render produces, and a reviewability-blocker placeholder survives
into a rendered artifact. Also exercises the check() gate wiring end-to-end via a real
render_html pass, so a regression in the toc extension's output shape (the `<div class="toc">`
wrapper, the `id="..."` slug it assigns headings) is caught here too."""

from __future__ import annotations

from pathlib import Path

from scripts.check_artifacts import check, check_render_integrity
from scripts.render_html import render_file


def test_clean_render_is_silent():
    html = (
        '<div class="toc"><ul><li><a href="#section-one">Section One</a></li></ul></div>\n'
        '<h2 id="section-one">Section One</h2>\n<p>Text.</p>\n'
    )
    assert check_render_integrity(html, "Text.", Path("REVIEW-demo.md")) == []


def test_duplicate_toc_marker_flagged():
    # Detection reads the MARKDOWN source, not the rendered div: bleach strips div's class
    # attribute (render_html._ALLOWED_ATTRS has no "div" entry), so a class="toc" check
    # would never fire against real sanitised output - see test_bleach_strips_toc_div_class.
    md_text = "[TOC]\n\n[TOC]\n\n## A\n"
    findings = check_render_integrity("<div><ul><li><a href=\"#a\">A</a></li></ul></div>", md_text, Path("REVIEW-demo.md"))
    assert any(f.startswith("TOC-DUPLICATE-RENDER:") for f in findings)
    assert any("REVIEW-demo.md" in f and "2 `[TOC]`" in f for f in findings)


def test_bleach_strips_toc_div_class():
    """Documents the sanitiser behaviour check_render_integrity's docstring relies on -
    if bleach's allow-list ever starts letting div keep its class, this test (not the
    render-only check above) is what should catch the drift."""
    from scripts.render_html import markdown_to_safe_html

    out = markdown_to_safe_html("[TOC]\n\n## Section One\n\nText.\n")
    assert '<div class="toc">' not in out
    assert 'id="section-one"' in out


def test_broken_anchor_flagged():
    html = '<p><a href="#never-written">see below</a></p>\n<h2 id="section-one">Section One</h2>\n'
    findings = check_render_integrity(html, "text", Path("REVIEW-demo.md"))
    assert any(f.startswith("ANCHOR-BROKEN:") and "never-written" in f for f in findings)


def test_valid_anchor_not_flagged():
    html = '<p><a href="#section-one">jump</a></p>\n<h2 id="section-one">Section One</h2>\n'
    assert check_render_integrity(html, "text", Path("REVIEW-demo.md")) == []


def test_stale_reviewability_blocker_flagged():
    findings = check_render_integrity(
        "<p>ok</p>", "Finding F-001: UNABLE TO ASSESS pending source access.", Path("REVIEW-demo.md")
    )
    assert any(f.startswith("STALE-REVIEWABILITY-BLOCKER:") for f in findings)


def test_gate_wiring_catches_a_real_double_toc_render(tmp_path):
    """End-to-end: two [TOC] markers in source -> render_html -> check() flags it, using the
    real markdown toc extension rather than a hand-built HTML fixture."""
    md = tmp_path / "REVIEW-demo.md"
    md.write_text(
        "[TOC]\n\n[TOC]\n\n## Section One\n\nText.\n\n## Section Two\n\nText.\n",
        encoding="utf-8",
    )
    render_file(md)
    findings = check(tmp_path)
    assert any(f.startswith("TOC-DUPLICATE-RENDER:") for f in findings)


def test_gate_wiring_catches_a_real_broken_anchor(tmp_path):
    md = tmp_path / "REVIEW-demo.md"
    md.write_text(
        "See the [findings](#findings-section) below.\n\n## Overview\n\nText.\n",
        encoding="utf-8",
    )
    render_file(md)
    findings = check(tmp_path)
    assert any(f.startswith("ANCHOR-BROKEN:") and "findings-section" in f for f in findings)


def test_gate_wiring_is_silent_on_a_clean_single_toc_render(tmp_path):
    md = tmp_path / "REVIEW-demo.md"
    md.write_text("[TOC]\n\n## Section One\n\nText.\n", encoding="utf-8")
    render_file(md)
    findings = check(tmp_path)
    assert not any(f.startswith("TOC-DUPLICATE-RENDER:") for f in findings)
    assert not any(f.startswith("ANCHOR-BROKEN:") for f in findings)
