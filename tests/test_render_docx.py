"""render_docx.py: opt-in .docx export for controlled documents, reusing
render_html.markdown_to_safe_html so both formats derive from one parse/sanitisation
pass. python-docx is an optional dependency - tests skip cleanly when it is absent."""

from __future__ import annotations

import pytest

docx = pytest.importorskip("docx")

from scripts.render_docx import render_docx  # noqa: E402

SAMPLE_MD = """# Test BRD

> **Document control** · ID `BRD-001` · Version `0.1` · Status `Draft`

## Executive summary

This is a **bold** and *italic* test with `inline code`.

## Requirements

- First requirement
- Second requirement with a [link](https://example.com)

| ID | Requirement | Priority |
|---|---|---|
| R1 | Do the thing | High |
| R2 | Do another thing | Medium |

> A blockquote note.
"""


def test_headings_and_title():
    doc = render_docx(SAMPLE_MD, title="Test BRD")
    assert doc.core_properties.title == "Test BRD"
    headings = [p for p in doc.paragraphs if p.style.name == "Heading 1"]
    assert headings and headings[0].text == "Test BRD"
    assert any(p.style.name == "Heading 2" and p.text == "Requirements" for p in doc.paragraphs)


def test_bold_italic_and_code_runs_preserved():
    doc = render_docx(SAMPLE_MD, title="t")
    para = next(p for p in doc.paragraphs if "bold" in p.text)
    bold_runs = [r for r in para.runs if r.bold]
    italic_runs = [r for r in para.runs if r.italic]
    assert any("bold" in r.text for r in bold_runs)
    assert any("italic" in r.text for r in italic_runs)


def test_bullet_list_items():
    doc = render_docx(SAMPLE_MD, title="t")
    bullets = [p.text for p in doc.paragraphs if p.style.name == "List Bullet"]
    assert "First requirement" in bullets
    assert any("Second requirement" in b for b in bullets)


def test_table_rendered_with_header():
    doc = render_docx(SAMPLE_MD, title="t")
    assert len(doc.tables) == 1
    rows = [[c.text for c in row.cells] for row in doc.tables[0].rows]
    assert rows[0] == ["ID", "Requirement", "Priority"]
    assert ["R1", "Do the thing", "High"] in rows


def test_blockquote_gets_quote_style_not_normal():
    doc = render_docx(SAMPLE_MD, title="t")
    quote = next(p for p in doc.paragraphs if "blockquote note" in p.text)
    assert quote.style.name == "Intense Quote"


def test_no_stray_empty_paragraphs_between_blocks():
    """Whitespace-only text nodes between block tags (markdown's own pretty-printed
    indentation) must not materialise as blank paragraphs."""
    doc = render_docx(SAMPLE_MD, title="t")
    blanks = [p for p in doc.paragraphs if p.style.name == "Normal" and not p.text.strip()]
    assert blanks == []


def test_link_becomes_hyperlink_not_plain_text():
    doc = render_docx(SAMPLE_MD, title="t")
    para = next(p for p in doc.paragraphs if "Second requirement" in p.text)
    assert para._p.findall(
        ".//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}hyperlink"
    )


def test_raises_a_clear_error_without_python_docx(monkeypatch):
    import scripts.render_docx as rd

    monkeypatch.setattr(rd, "_DOCX_AVAILABLE", False)
    with pytest.raises(RuntimeError, match="python-docx"):
        rd.render_docx("# x", title="x")
