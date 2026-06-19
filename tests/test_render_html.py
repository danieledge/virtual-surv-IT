"""Tests for the Markdown -> standalone HTML renderer (scripts/render_html.py)."""
from __future__ import annotations

from scripts.render_html import _title_from, render

SAMPLE = """# Review Report

Some **bold** text.

| ID | Status |
|----|--------|
| R1 | open   |
"""


def test_title_pulled_from_first_h1():
    assert _title_from(SAMPLE, "fallback") == "Review Report"
    assert _title_from("no heading here", "fallback") == "fallback"


def test_render_is_standalone_html():
    html = render(SAMPLE, "Review Report")
    assert html.lstrip().startswith("<!doctype html>")
    assert "<title>Review Report</title>" in html
    assert "<style>" in html              # CSS is inlined (no external assets)
    assert "<table>" in html              # tables extension active
    assert "<strong>bold</strong>" in html
