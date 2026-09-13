"""scripts/check_pdf_links.py (2026-09-13 framework review, step 7.12): a tracked PDF must not
carry link annotations that point at the author's local filesystem."""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
if str(REPO / "vendor") not in sys.path:
    sys.path.insert(0, str(REPO / "vendor"))

from scripts import check_pdf_links as cpl  # noqa: E402


def _pdf_with_link(path: Path, url: str) -> Path:
    from pypdf import PdfWriter
    from pypdf.annotations import Link

    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.add_annotation(page_number=0, annotation=Link(rect=(10, 10, 100, 30), url=url))
    with open(path, "wb") as fh:
        writer.write(fh)
    return path


def test_a_local_file_link_fails_and_a_web_link_passes(tmp_path, capsys):
    bad = _pdf_with_link(tmp_path / "bad.pdf", "file:///home/someone/www/repo/docs/FAQ.md")
    good = _pdf_with_link(tmp_path / "good.pdf", "https://github.com/danieledge/virtual-surv-IT")
    assert cpl.local_link_targets(bad) == ["file:///home/someone/www/repo/docs/FAQ.md"]
    assert cpl.local_link_targets(good) == []
    assert cpl.main([str(good)]) == 0
    assert cpl.main([str(bad)]) == 1
    assert "point at a local path" in capsys.readouterr().out


def test_every_tracked_pdf_is_clean():
    for pdf in cpl.tracked_pdfs():
        assert cpl.local_link_targets(pdf) == [], f"{pdf} carries local-path links"
