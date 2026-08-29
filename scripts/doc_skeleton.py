#!/usr/bin/env python3
"""Deterministic, token-budgeted inventory of a DOCUMENTATION tree (2026-08-25).

WHY THIS EXISTS. `repo_skeleton` answers "what is in this codebase" for first contact. There
was no equivalent for documents, so a session handed a Confluence export, a vendor feed specification
and three hundred supporting files had no bounded way to know what it had - only to start
opening things, which is unbounded, non-reproducible, and pulls content into context that may
never be needed.

WHY NOT RAG. Anthropic's own guidance on Contextual Retrieval is explicit: under ~200,000
tokens (about 500 pages) you should put the corpus in the prompt rather than build retrieval
infrastructure. Most documentation sets an engagement is handed are under that. What is
missing is not retrieval, it is ORIENTATION - knowing what exists before deciding what to
read. This is that, and it needs no embeddings, no index and no network.

HOW IT DIFFERS FROM THE DATA TOOLS. `profile_temporal` and `tag_columns` emit aggregates only
and never a record, which is what makes them safe to point at client data. This one is
different and the difference matters: **document titles and headings ARE content**. A heading
can name a client, a case or a counterparty. So this tool is subject to the normal data
rules (CLAUDE.md §5), not exempt from them - point it at documentation, not at evidence, and
never at `data/raw/`.

WHAT IT READS. Structure, not prose: filenames, sizes, dates, and for text-shaped documents
their heading outline. Binary documents (.pdf, .docx, .xlsx, .msg) are INVENTORIED but never
parsed here - that is `convert_file`'s job, and doing it twice would be both slower and a
second place to get it wrong.

Usage:
    python -m scripts.doc_skeleton [PATH] [--budget N] [--out FILE] [--json]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

# Text-shaped: an outline can be read directly, cheaply, with no conversion.
_OUTLINE_EXTS = frozenset({".md", ".markdown", ".rst", ".txt"})
# Documents worth listing but never parsed here - convert_file owns their extraction.
_DOCUMENT_EXTS = frozenset(
    {".pdf", ".docx", ".doc", ".xlsx", ".xlsm", ".xls", ".csv", ".tsv", ".pptx", ".msg", ".eml"}
)
_SKIP_DIRS = frozenset(
    {".git", "node_modules", "__pycache__", ".venv", "venv", ".mypy_cache", ".ruff_cache"}
)
_CHARS_PER_TOKEN = 4  # the same rough proxy repo_skeleton uses; bounding, not accounting
_DEFAULT_BUDGET = 6000
_MAX_HEADINGS = 12  # per document - an outline, not a table of contents

_MD_HEADING = re.compile(r"^(#{1,3})\s+(.+?)\s*#*$")
_RST_UNDERLINE = re.compile(r"^[=\-~^\"']{3,}$")


def _headings(path: Path) -> list[str]:
    """Heading outline for a text-shaped document. Never the body."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    found: list[str] = []
    previous = ""
    for line in text.splitlines():
        if len(found) >= _MAX_HEADINGS:
            break
        match = _MD_HEADING.match(line.strip())
        if match:
            found.append(f"{'  ' * (len(match.group(1)) - 1)}{match.group(2).strip()}")
        elif _RST_UNDERLINE.match(line.strip()) and previous.strip():
            # reStructuredText underlines the heading on the NEXT line.
            found.append(previous.strip())
        previous = line
    return found


def _kind(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in _OUTLINE_EXTS:
        return "text"
    if suffix in _DOCUMENT_EXTS:
        return "document"
    return "other"


def inventory(root: Path) -> list[dict]:
    """Every document under `root`, sorted for determinism."""
    entries: list[dict] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        kind = _kind(path)
        if kind == "other":
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        entries.append(
            {
                "path": str(path.relative_to(root)).replace("\\", "/"),
                "kind": kind,
                "suffix": path.suffix.lower(),
                "bytes": stat.st_size,
                "modified": date.fromtimestamp(stat.st_mtime).isoformat(),
                "headings": _headings(path) if kind == "text" else [],
            }
        )
    return entries


def render(root: Path, entries: list[dict], budget: int) -> str:
    by_type: dict[str, int] = {}
    for entry in entries:
        by_type[entry["suffix"]] = by_type.get(entry["suffix"], 0) + 1
    head = [
        f"# Documentation skeleton - {root}",
        f"# {len(entries)} document(s) inventoried, budget ~{budget} tokens",
        "# " + ", ".join(f"{suffix} x{count}" for suffix, count in sorted(by_type.items())),
        "",
    ]
    lines: list[str] = []
    spent = sum(len(line) for line in head) // _CHARS_PER_TOKEN
    shown = 0
    for entry in entries:
        block = [
            f"## {entry['path']}  [{entry['kind']}], {entry['bytes']:,} bytes, "
            f"modified {entry['modified']}"
        ]
        if entry["kind"] == "document":
            block.append(f"  (read with: python -m scripts.convert_file {entry['path']})")
        for heading in entry["headings"]:
            block.append(f"  - {heading}")
        if not entry["headings"] and entry["kind"] == "text":
            block.append("  (no headings)")
        cost = sum(len(line) for line in block) // _CHARS_PER_TOKEN
        if spent + cost > budget and shown:
            break
        lines += block
        spent += cost
        shown += 1
    out = head + lines
    if shown < len(entries):
        out += [
            "",
            f"# {len(entries) - shown} more document(s) not shown - the budget stopped the "
            "listing, it was not truncated silently. Raise it with --budget or point at a "
            "narrower path.",
        ]
    out += [
        "",
        "> Structure only - filenames, sizes, dates and heading outlines. Bodies are NOT read",
        "> here; convert a document when you actually need it. Headings are CONTENT (a heading",
        "> can name a client or a case), so the usual data-handling rules apply to this output.",
    ]
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass
    ap = argparse.ArgumentParser(description="Token-budgeted inventory of a documentation tree.")
    ap.add_argument("path", nargs="?", default=".", help="root to inventory (default: .)")
    ap.add_argument("--budget", type=int, default=_DEFAULT_BUDGET)
    ap.add_argument("--out", type=Path, default=None, help="write to a file instead of stdout")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args(argv)

    root = Path(args.path).resolve()
    if not root.is_dir():
        print(f"not a directory: {root}", file=sys.stderr)
        return 2
    entries = inventory(root)
    text = (
        json.dumps({"root": str(root), "documents": entries}, indent=2)
        if args.json
        else render(root, entries, args.budget)
    )
    if args.out:
        args.out.write_text(text + "\n", encoding="utf-8")
        print(f"wrote {args.out}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
