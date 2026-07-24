"""
scripts/render_html.py - render a Markdown artifact to a styled, standalone HTML file.

Every deliverable (engagement brief, BRD, FSD, review report, audit pack) is authored in
Markdown and rendered to self-contained HTML (inline CSS, no external assets) so it can be
emailed or shared as a single file - the team always produces artifacts in both .md and
.html for easy distribution.

Security note: artifacts may include content from untrusted sources (captured comms excerpts,
third-party tool output).  The raw HTML produced by markdown() is sanitised via bleach before
insertion into the page, and the page title is html.escape()d.  bleach is a pinned dependency
(requirements-dev.txt); if it is unavailable the render **fails closed** (raises) rather than
emitting unsanitised HTML - we never silently produce a potentially-XSS artifact.

Usage:
  python -m scripts.render_html artifacts/BRD-spoofing.md
  python -m scripts.render_html artifacts/BRD-spoofing.md --out artifacts/BRD-spoofing.html
"""

from __future__ import annotations

import argparse
import datetime as _dt
import html
import re
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

# Optional CSS sanitiser so Markdown table column alignment (style="text-align: …") survives.
# Needs the bleach[css] extra (tinycss2). It is purely cosmetic: sanitisation itself must NOT
# depend on it, so we load it separately and fall back to None (alignment lost, output still
# safe) if the extra is absent. Without ANY css_sanitizer, bleach empties allowed style attrs.
_CSS_SANITIZER = None
if _BLEACH_AVAILABLE:
    try:
        from bleach.css_sanitizer import CSSSanitizer

        _CSS_SANITIZER = CSSSanitizer(allowed_css_properties=["text-align"])
    except Exception:  # pragma: no cover - bleach[css]/tinycss2 not installed
        _CSS_SANITIZER = None

# ---------------------------------------------------------------------------
# bleach allow-list: tags and attributes that are safe in rendered Markdown.
# Derived from common Markdown output + the extensions used here (tables, code,
# toc).  Inline event handlers (onclick, onerror, …) are intentionally absent.
# ---------------------------------------------------------------------------
_ALLOWED_TAGS = frozenset(
    {
        # Structure
        "p",
        "br",
        "hr",
        "div",
        "span",
        # Headings
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        # Lists
        "ul",
        "ol",
        "li",
        # Inline
        "a",
        "strong",
        "em",
        "b",
        "i",
        "s",
        "del",
        "ins",
        # Code
        "code",
        "pre",
        # Quotes
        "blockquote",
        # Tables (tables extension)
        "table",
        "thead",
        "tbody",
        "tfoot",
        "tr",
        "th",
        "td",
        # Images - allowed with restricted attributes; src may be http(s), relative, or an
        # inline data: URI (see _ALLOWED_PROTOCOLS) so artifacts can embed charts self-contained.
        "img",
        # TOC anchors
        "sup",
        "sub",
    }
)

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

# Allowed URI schemes in href/src attributes. `data:` is included so images can be embedded
# inline (base64) and the artifact stays truly self-contained; bleach cannot scope a protocol
# to a tag/mediatype, so a `data:` URI in an <a href> is also permitted (low risk for a
# locally-opened artifact, and javascript:/vbscript: remain blocked).
_ALLOWED_PROTOCOLS = frozenset({"http", "https", "mailto", "data"})

_CSS = """
body { font-family: -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif;
  line-height: 1.55; max-width: 52rem; margin: 0 auto; padding: 0 1.25rem 3rem;
  color: #1a1a1a; background: #fff; }
.letterhead { border-bottom: 2px solid #0969da; margin: 0 -1.25rem 1.5rem; padding: .7rem 1.25rem;
  display: flex; justify-content: space-between; align-items: baseline; flex-wrap: wrap;
  font-size: .8rem; color: #57606a; }
.letterhead .brand { font-weight: 600; color: #0969da; letter-spacing: .02em; }
h1, h2, h3 { line-height: 1.25; margin-top: 1.8em; }
h1 { border-bottom: 2px solid #e3e3e3; padding-bottom: .3em; }
h2 { border-bottom: 1px solid #ececec; padding-bottom: .2em; }
/* An H1 inside a callout blockquote should not look like a second document title. */
blockquote h1, blockquote h2 { border: 0; font-size: 1.05em; margin: .2em 0; padding: 0; }
code { background: #f4f4f5; padding: .15em .35em; border-radius: 4px; font-size: .9em;
  font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace; }
pre { background: #f6f8fa; padding: 1em; border-radius: 8px; overflow-x: auto;
  border: 1px solid #eaecef; }
pre code { background: none; padding: 0; }
table { border-collapse: collapse; width: 100%; margin: 1em 0; }
th, td { border: 1px solid #dcdcdc; padding: .5em .7em; text-align: left; vertical-align: top; }
th { background: #f6f8fa; }
tbody tr:nth-child(even) { background: #fafbfc; }
blockquote { border-left: 4px solid #d0d7de; margin: 1em 0; padding: .2em 1em; color: #4a5158; }
a { color: #0969da; }
.footer { margin-top: 3rem; padding-top: 1rem; border-top: 1px solid #ececec;
  color: #595959; font-size: .8rem; }
@media (prefers-color-scheme: dark) {
  body { background: #0d1117; color: #e6edf3; }
  h1, h2 { border-color: #30363d; }
  .letterhead { border-color: #1f6feb; color: #9da7b3; }
  code, pre { background: #161b22; } pre { border-color: #30363d; }
  th { background: #161b22; } th, td { border-color: #30363d; }
  tbody tr:nth-child(even) { background: #11161d; }
  blockquote { color: #9da7b3; border-color: #30363d; }
  a { color: #539bf5; } .footer { color: #8b949e; border-color: #30363d; }
}
@media print {
  body { max-width: none; font-size: 11pt; }
  a { color: inherit; text-decoration: none; }
  @page { margin: 18mm; }
  h1, h2, h3 { break-after: avoid; }
  tr, pre, table, blockquote { break-inside: avoid; }
  thead { display: table-header-group; }   /* repeat table headers on each page */
  .letterhead { position: running(head); }
}
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
<header class="letterhead"><span class="brand">Compliance Surveillance Engineering</span><span>%%META%%</span></header>
%%BODY%%
<div class="footer">%%FOOTER%%</div>
</body>
</html>
"""


def _title_from(md_text: str, fallback: str) -> str:
    m = re.search(r"^#\s+(.+)$", md_text, re.MULTILINE)
    return m.group(1).strip() if m else fallback


def _sanitise(raw_html: str) -> str:
    """
    Sanitise raw HTML produced by markdown() using bleach.

    Fails closed: bleach is a pinned dependency, so if it is unavailable we raise
    rather than emit unsanitised HTML.  Artifacts may carry untrusted content
    (captured comms, third-party output); silently shipping raw HTML would be an
    XSS exposure for a single-file artifact that gets emailed or shared.
    """
    if not _BLEACH_AVAILABLE:
        raise RuntimeError(
            "bleach is required to render HTML safely but is not installed. "
            "Install it (pip install -r requirements-dev.txt). Refusing to emit "
            "unsanitised HTML - see scripts/render_html.py for details."
        )
    return bleach.clean(
        raw_html,
        tags=_ALLOWED_TAGS,
        attributes=_ALLOWED_ATTRS,
        protocols=_ALLOWED_PROTOCOLS,
        css_sanitizer=_CSS_SANITIZER,  # keep table text-align; drop everything else
        strip=True,  # remove (not escape) disallowed tags
        strip_comments=True,  # strip HTML comments which can hide payloads
    )


# An all-empty table header row (from a "| | |" metadata block) renders as an ugly grey bar.
_EMPTY_THEAD = re.compile(r"<thead>\s*<tr>\s*(?:<th[^>]*>\s*</th>\s*)+</tr>\s*</thead>", re.I)
# Relative links between artifacts point at .md; in the rendered .html pack they must point at .html.
_MD_LINK = re.compile(r'(<a\s+[^>]*href=")(?!https?:|mailto:|#)([^":]+?)\.md((?:#[^"]*)?)"', re.I)


def render(md_text: str, title: str, source: str = "", generated: str = "") -> str:
    if markdown is None:
        raise RuntimeError(
            "The 'Markdown' package is required: pip install -r requirements-dev.txt"
        )

    # toc_depth 2-2: a `[TOC]` contents block lists only the MAJOR sections (h2 / `## N.`), not the
    # H1 title and not h3+ subsections - so a large report's Contents stays a short, clickable index.
    raw_body = markdown.markdown(
        md_text,
        extensions=["tables", "fenced_code", "toc", "sane_lists"],
        extension_configs={"toc": {"toc_depth": "2-2"}},
    )
    # Sanitise rendered HTML body to prevent XSS if artifact content is
    # untrusted (e.g. captured comms snippets, third-party output).
    safe_body = _sanitise(raw_body)
    # Drop empty metadata-table header rows, and repoint inter-artifact .md links to .html.
    safe_body = _EMPTY_THEAD.sub("", safe_body)
    safe_body = _MD_LINK.sub(r'\1\2.html\3"', safe_body)

    # html.escape() the title so injected HTML/JS in a Markdown H1 cannot
    # break out of the <title> element.
    safe_title = html.escape(title, quote=True)
    meta = html.escape(generated, quote=True)
    footer_bits = ["Generated from Markdown by the compliance surveillance engineering team."]
    if source:
        footer_bits.append(f"Source: {html.escape(source, quote=True)}")
    if generated:
        footer_bits.append(html.escape(generated, quote=True))

    fields = {
        "TITLE": safe_title,
        "CSS": _CSS,
        "META": meta,
        "BODY": safe_body,
        "FOOTER": " &middot; ".join(footer_bits),
    }
    # Single-pass substitution: inserted content (e.g. a title or body that itself contains a
    # literal %%BODY%%/%%FOOTER%% token) is never re-scanned, so it cannot collide with a later
    # placeholder. The callback's return value is inserted verbatim (no backref processing).
    return re.sub(r"%%(TITLE|CSS|META|BODY|FOOTER)%%", lambda m: fields[m.group(1)], _TEMPLATE)


def main() -> None:
    ap = argparse.ArgumentParser(description="Render a Markdown artifact to standalone HTML.")
    ap.add_argument("src", type=Path, help="path to the .md artifact")
    ap.add_argument("--out", type=Path, help="output .html path (default: alongside the .md)")
    args = ap.parse_args()

    # Pin UTF-8 explicitly: Path.read_text/write_text otherwise use the OS locale default
    # (e.g. cp1252 on Windows), which mangles emoji / non-ASCII into replacement boxes. UTF-8
    # keeps rendering identical on every platform, not just UTF-8-locale Linux/macOS.
    md_text = args.src.read_text(encoding="utf-8")
    out = args.out or args.src.with_suffix(".html")
    generated = _dt.date.today().isoformat()
    out.write_text(
        render(
            md_text, _title_from(md_text, args.src.stem), source=args.src.name, generated=generated
        ),
        encoding="utf-8",
    )
    print(f"Rendered {args.src} -> {out}")


if __name__ == "__main__":
    main()
