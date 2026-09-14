"""Tests for the Markdown -> standalone HTML renderer (scripts/render_html.py)."""

from __future__ import annotations

import pytest

import scripts.render_html as rh
from scripts.render_html import _sanitise, _title_from, render

SAMPLE = """# Review Report

Some **bold** text.

| ID | Status |
|----|--------|
| R1 | open   |
"""


def test_title_pulled_from_first_h1():
    assert _title_from(SAMPLE, "fallback") == "Review Report"
    assert _title_from("no heading here", "fallback") == "fallback"


def test_render_file_writes_html_alongside_by_default(tmp_path):
    src = tmp_path / "REPORT.md"
    src.write_text(SAMPLE, encoding="utf-8")
    out = rh.render_file(src)
    assert out == src.with_suffix(".html")
    assert out.is_file()
    assert "Review Report" in out.read_text(encoding="utf-8")


def test_render_file_honours_explicit_out_path(tmp_path):
    src = tmp_path / "REPORT.md"
    src.write_text(SAMPLE, encoding="utf-8")
    out_path = tmp_path / "elsewhere" / "custom.html"
    out_path.parent.mkdir()
    out = rh.render_file(src, out_path)
    assert out == out_path
    assert out.is_file()


def test_render_is_standalone_html():
    html = render(SAMPLE, "Review Report")
    assert html.lstrip().startswith("<!doctype html>")
    assert "<title>Review Report</title>" in html
    assert "<style>" in html  # CSS is inlined (no external assets)
    assert "<table>" in html  # tables extension active
    assert "<strong>bold</strong>" in html


# --- Sanitisation (XSS guard) -------------------------------------------------
# Artifacts may carry untrusted content (captured comms, third-party output), so the
# rendered HTML must be sanitised. These assert the safe path actually strips payloads.


def test_sanitise_strips_script_tags():
    # The <script> ELEMENT is removed; any inner text survives only as inert plain
    # text (no executable element), which is the safe outcome.
    out = _sanitise("<p>ok</p><script>alert(1)</script>")
    assert "<script" not in out
    assert "</script>" not in out
    assert "<p>ok</p>" in out


def test_sanitise_strips_event_handlers():
    out = _sanitise('<img src="x" onerror="alert(1)">')
    assert "onerror" not in out


def test_sanitise_strips_javascript_uris():
    out = _sanitise('<a href="javascript:alert(1)">click</a>')
    assert "javascript:" not in out


def test_sanitise_strips_html_comments():
    # Comments can hide conditional-comment payloads; strip_comments=True removes them.
    out = _sanitise("<p>visible</p><!-- <script>evil()</script> -->")
    assert "evil()" not in out


def test_render_sanitises_inline_html_in_markdown():
    html = render("# T\n\nIntro <script>alert(1)</script> tail.", "T")
    assert "<script" not in html  # no executable element in the rendered page


def test_render_rewrites_md_links_to_html():
    # Inter-artifact relative .md links must point at .html in the rendered pack;
    # external/anchor links must be left alone.
    html = render("# T\n\nSee [spec](FSD-001.md) and [site](https://example.com/x.md).", "T")
    assert 'href="FSD-001.html"' in html
    assert 'href="https://example.com/x.md"' in html  # external left untouched


def test_render_fails_closed_when_bleach_unavailable(monkeypatch):
    # bleach is pinned; if it ever goes missing we must RAISE, never emit raw HTML.
    monkeypatch.setattr(rh, "_BLEACH_AVAILABLE", False)
    with pytest.raises(RuntimeError, match="bleach"):
        render("# T\n\n<script>alert(1)</script>", "T")


@pytest.mark.skipif(rh._CSS_SANITIZER is None, reason="bleach[css] (tinycss2) not installed")
def test_render_preserves_table_alignment():
    # A right-aligned Markdown column must keep its text-align after sanitisation
    # (regression: without a CSS sanitiser bleach silently drops the style attribute).
    html = render("# T\n\n| Amount |\n|------:|\n| 100 |\n", "T")
    assert "text-align" in html


def test_render_allows_inline_data_image():
    # Inline base64 images keep the artifact self-contained; data: URIs are allowed.
    html = render("# T\n\n![chart](data:image/png;base64,iVBORw0KGgo=)", "T")
    assert "data:image/png" in html


def test_render_body_with_literal_placeholder_not_clobbered():
    # A body that contains a literal %%FOOTER%% token must survive intact, and the real footer
    # must still render exactly once (regression: sequential str.replace re-scanned inserts).
    html = render("# T\n\nThis doc mentions the %%FOOTER%% token literally.", "T")
    assert "%%FOOTER%%" in html  # the literal in the body was not substituted
    assert "Generated from Markdown" in html  # the real footer still rendered


# --- render_document: the shared wrapper (2026-09-14) -------------------------------------


def test_render_document_wraps_trusted_body_in_the_team_template():
    page = rh.render_document(
        "<h1>Body</h1><div class='card'>x</div>",
        'Title <script>"q"</script>',
        meta="meta <b>bold</b>",
        footer_bits=("first", "second"),
        extra_css=".card { color: red; }",
    )
    assert page.startswith("<!doctype html>") and page.rstrip().endswith("</html>")
    assert '<span class="brand">Compliance Surveillance Engineering</span>' in page
    assert "<title>Title &lt;script&gt;&quot;q&quot;&lt;/script&gt;</title>" in page
    assert "<span>meta &lt;b&gt;bold&lt;/b&gt;</span>" in page  # meta is escaped
    assert "<h1>Body</h1><div class='card'>x</div>" in page  # body is inserted verbatim
    assert '<div class="footer">first &middot; second</div>' in page
    house, extra = page.index(rh._CSS.splitlines()[0]), page.index(".card { color: red; }")
    assert house < extra < page.index("</style>")  # extra CSS after the house CSS, inside <style>


def test_render_document_without_extras_matches_render_shape():
    plain = rh.render_document("<p>x</p>", "T")
    assert "<span></span></header>" in plain  # empty meta
    assert '<div class="footer"></div>' in plain
    assert plain.count("<style>") == 1
    # render() is now render_document over the sanitised Markdown body
    via_md = rh.render("# T\n\nx", "T", source="a.md", generated="2026-09-14")
    assert "Generated from Markdown by the compliance surveillance engineering team." in via_md
    assert "Source: a.md &middot; 2026-09-14</div>" in via_md
    assert "<span>2026-09-14</span></header>" in via_md
