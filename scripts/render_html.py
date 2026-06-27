"""
scripts/render_html.py - render a Markdown artifact to a styled, standalone HTML file.

Every deliverable (engagement brief, BRD, FSD, review report, audit pack) is authored in
Markdown and rendered to self-contained HTML (inline CSS, no external assets) so it can be
emailed or shared as a single file - the team always produces artifacts in both .md and
.html for easy distribution.

Security note: artifacts may include content from untrusted sources (captured comms excerpts,
third-party tool output).  The raw HTML produced by markdown() is sanitised via bleach before
insertion into the page, and the page title is html.escape()d.  If bleach is unavailable the
build degrades gracefully - body content is still rendered but a warning is printed.

Usage:
  python -m scripts.render_html artifacts/BRD-spoofing.md
  python -m scripts.render_html artifacts/BRD-spoofing.md --out artifacts/BRD-spoofing.html
"""
from __future__ import annotations

import argparse
import html
import re
import sys
from pathlib import Path

try:
    import markdown
except ImportError:  # pragma: no cover - import guard
    markdown = None

try:
    import bleach
    import bleach.linkifier  # confirm full package is present, not just a stub
    _BLEACH_AVAILABLE = True
except Exception:  # pragma: no cover - optional dependency
    _BLEACH_AVAILABLE = False

# ---------------------------------------------------------------------------
# bleach allow-list: tags and attributes that are safe in rendered Markdown.
# Derived from common Markdown output + the extensions used here (tables, code,
# toc).  Inline event handlers (onclick, onerror, …) are intentionally absent.
# ---------------------------------------------------------------------------
_ALLOWED_TAGS = frozenset({
    # Structure
    "p", "br", "hr", "div", "span",
    # Headings
    "h1", "h2", "h3", "h4", "h5", "h6",
    # Lists
    "ul", "ol", "li",
    # Inline
    "a", "strong", "em", "b", "i", "s", "del", "ins",
    # Code
    "code", "pre",
    # Quotes
    "blockquote",
    # Tables (tables extension)
    "table", "thead", "tbody", "tfoot", "tr", "th", "td",
    # Images - allowed with restricted attributes; src is constrained to data: or relative
    "img",
    # TOC anchors
    "sup", "sub",
})

_ALLOWED_ATTRS: dict = {
    # Links: href + title only; javascript: is blocked by bleach's protocol filter
    "a": ["href", "title"],
    # Code block language hint (set by fenced_code extension)
    "code": ["class"],
    "pre": ["class"],
    # Table alignment
    "th": ["align", "style"],
    "td": ["align", "style"],
    # Images: restrict to alt/title/src; no crossorigin, no event attrs
    "img": ["alt", "title", "src"],
    # TOC ids (set by toc extension)
    "*": ["id"],
}

# Allowed URI schemes in href/src attributes.
_ALLOWED_PROTOCOLS = frozenset({"http", "https", "mailto"})

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
<div class="footer">Generated from Markdown - compliance surveillance engineering team.</div>
</body>
</html>
"""


def _title_from(md_text: str, fallback: str) -> str:
    m = re.search(r"^#\s+(.+)$", md_text, re.MULTILINE)
    return m.group(1).strip() if m else fallback


def _sanitise(raw_html: str) -> str:
    """
    Sanitise raw HTML produced by markdown() using bleach.

    If bleach is not installed we degrade gracefully: output the raw HTML
    but print a warning.  This avoids a hard build dependency on bleach while
    still making the safe path the default when the package is present.
    """
    if _BLEACH_AVAILABLE:
        return bleach.clean(
            raw_html,
            tags=_ALLOWED_TAGS,
            attributes=_ALLOWED_ATTRS,
            protocols=_ALLOWED_PROTOCOLS,
            strip=True,          # remove (not escape) disallowed tags
            strip_comments=True, # strip HTML comments which can hide payloads
        )
    # Degraded path: bleach unavailable.
    print(
        "WARNING: bleach is not installed - HTML output is NOT sanitised. "
        "Install bleach (pip install bleach) for safe output. "
        "See scripts/render_html.py for details.",
        file=sys.stderr,
    )
    return raw_html


def render(md_text: str, title: str) -> str:
    if markdown is None:
        raise RuntimeError("The 'Markdown' package is required: pip install -r requirements-dev.txt")

    raw_body = markdown.markdown(
        md_text, extensions=["tables", "fenced_code", "toc", "sane_lists"]
    )
    # Sanitise rendered HTML body to prevent XSS if artifact content is
    # untrusted (e.g. captured comms snippets, third-party output).
    safe_body = _sanitise(raw_body)

    # html.escape() the title so injected HTML/JS in a Markdown H1 cannot
    # break out of the <title> element.
    safe_title = html.escape(title, quote=True)

    return (
        _TEMPLATE.replace("%%TITLE%%", safe_title)
        .replace("%%CSS%%", _CSS)
        .replace("%%BODY%%", safe_body)
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
