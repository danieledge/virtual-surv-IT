"""
scripts/render_html.py — render a Markdown artifact to a styled, standalone HTML file.

Every deliverable (engagement brief, BRD, FSD, review report, audit pack) is authored in
Markdown and rendered to self-contained HTML (inline CSS, no external assets) so it can be
emailed or shared as a single file — the team always produces artifacts in both .md and
.html for easy distribution.

Usage:
  python -m scripts.render_html artifacts/BRD-spoofing.md
  python -m scripts.render_html artifacts/BRD-spoofing.md --out artifacts/BRD-spoofing.html
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

try:
    import markdown
except ImportError:  # pragma: no cover - import guard
    markdown = None

_CSS = """
:root { color-scheme: light dark; }
body { font-family: -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif;
  line-height: 1.55; max-width: 50rem; margin: 2rem auto; padding: 0 1.25rem;
  color: #1a1a1a; background: #fff; }
h1, h2, h3 { line-height: 1.25; margin-top: 1.8em; }
h1 { border-bottom: 2px solid #e3e3e3; padding-bottom: .3em; }
h2 { border-bottom: 1px solid #ececec; padding-bottom: .2em; }
code { background: #f4f4f5; padding: .15em .35em; border-radius: 4px; font-size: .9em; }
pre { background: #f6f8fa; padding: 1em; border-radius: 8px; overflow-x: auto; }
pre code { background: none; padding: 0; }
table { border-collapse: collapse; width: 100%; margin: 1em 0; }
th, td { border: 1px solid #dcdcdc; padding: .5em .7em; text-align: left; vertical-align: top; }
th { background: #f6f8fa; }
blockquote { border-left: 4px solid #d0d7de; margin: 1em 0; padding: .2em 1em; color: #57606a; }
a { color: #0969da; }
.footer { margin-top: 3rem; padding-top: 1rem; border-top: 1px solid #ececec;
  color: #8a8a8a; font-size: .8rem; }
@media print { body { max-width: none; } a { color: inherit; } }
""".strip()

_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>%%TITLE%%</title>
<style>%%CSS%%</style>
</head>
<body>
%%BODY%%
<div class="footer">Generated from Markdown — compliance surveillance engineering team.</div>
</body>
</html>
"""


def _title_from(md_text: str, fallback: str) -> str:
    m = re.search(r"^#\s+(.+)$", md_text, re.MULTILINE)
    return m.group(1).strip() if m else fallback


def render(md_text: str, title: str) -> str:
    if markdown is None:
        raise RuntimeError("The 'Markdown' package is required: pip install -r requirements-dev.txt")
    body = markdown.markdown(
        md_text, extensions=["tables", "fenced_code", "toc", "sane_lists"]
    )
    return (
        _TEMPLATE.replace("%%TITLE%%", title)
        .replace("%%CSS%%", _CSS)
        .replace("%%BODY%%", body)
    )


def main() -> None:
    ap = argparse.ArgumentParser(description="Render a Markdown artifact to standalone HTML.")
    ap.add_argument("src", type=Path, help="path to the .md artifact")
    ap.add_argument("--out", type=Path, help="output .html path (default: alongside the .md)")
    args = ap.parse_args()

    md_text = args.src.read_text()
    out = args.out or args.src.with_suffix(".html")
    out.write_text(render(md_text, _title_from(md_text, args.src.stem)))
    print(f"Rendered {args.src} -> {out}")


if __name__ == "__main__":
    main()
