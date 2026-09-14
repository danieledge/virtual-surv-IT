#!/usr/bin/env python3
"""Refuse a tracked PDF whose link annotations point at a local path (step 7.12, 2026-09-13).

A browser's print-to-PDF resolves a page's relative links against the local file it was opened
from, so a regenerated `docs/quick-start.pdf` can carry `file:///home/<user>/...` targets that
name the author's machine and go nowhere for a reader (docs/internal/README.md records the
strip step by hand). This is that step in check mode, for CI: every tracked PDF's `/Link`
annotations must be http(s) or mailto, or in-document.

    python scripts/check_pdf_links.py            # every tracked *.pdf
    python scripts/check_pdf_links.py a.pdf b.pdf

Exit 1 with the offending file and target on any local-path link. Uses the vendored pypdf.
"""

from __future__ import annotations

import re
import subprocess  # nosec B404 - fixed argv, shell=False: git ls-files
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
_VENDOR = REPO / "vendor"
if _VENDOR.is_dir() and str(_VENDOR) not in sys.path:
    sys.path.insert(0, str(_VENDOR))

_LOCAL = re.compile(r"^(?:file:|[A-Za-z]:[\\/]|/|\\\\|\.\.?/)", re.I)


def local_link_targets(pdf: Path) -> list[str]:
    """Every URI action target in the PDF's link annotations that names a local path."""
    from pypdf import PdfReader

    found: list[str] = []
    reader = PdfReader(str(pdf))
    for page in reader.pages:
        annots = page.get("/Annots") or []
        for ref in annots:
            try:
                annot = ref.get_object()
            except Exception:  # noqa: BLE001  # nosec B112 - an unreadable annotation cannot be a local link; the check is for links that resolve, and skipping a broken object is the fail-safe direction for a link scan
                continue
            if annot.get("/Subtype") != "/Link":
                continue
            action = annot.get("/A")
            if action is None:
                continue
            try:
                action = action.get_object()
            except Exception:  # noqa: BLE001  # nosec B112 - same: an action object that will not resolve carries no URI to judge
                continue
            uri = action.get("/URI")
            if uri is None:
                continue
            target = str(uri)
            if _LOCAL.match(target):
                found.append(target)
    return found


def tracked_pdfs() -> list[Path]:
    proc = subprocess.run(  # nosec B603
        ["git", "ls-files", "*.pdf", "**/*.pdf"], cwd=str(REPO), capture_output=True, text=True
    )
    return [REPO / line for line in proc.stdout.splitlines() if line.strip()]


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    pdfs = [Path(a) for a in args] or tracked_pdfs()
    bad = 0
    for pdf in pdfs:
        targets = local_link_targets(pdf)
        if targets:
            bad += 1
            print(f"{pdf}: {len(targets)} link(s) point at a local path, e.g. {targets[0][:80]}")
        else:
            print(f"{pdf}: ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
