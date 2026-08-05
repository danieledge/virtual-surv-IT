#!/usr/bin/env python3
"""Deterministic, mechanical first-contact orientation for an unfamiliar codebase (ADR-007).

Problem this exists to fix: without a bounded tool, first-contact exploration on a large or
unfamiliar codebase tends toward ad hoc, unscoped `find`/`ls`/`grep` sweeps - noisy (picks up
`__pycache__`, `node_modules`, build output), unbounded (can dump thousands of files into an
agent's own context), and non-reproducible. `repo_skeleton` replaces that with one deterministic
pass: inventory the tree (respecting `.gitignore` where possible), extract symbols per file
(tiered: whatever's actually available on the host, stdlib `ast` as the always-present floor),
and emit a token-budgeted, human-and-agent-readable skeleton. Zero LLM calls, zero third-party
hard dependencies, zero network.

Design constraints (see docs/adr/ADR-007-codebase-map-evolution.md for the full record):
  - Tree-sitter/ctags are SOFT runtime probes only, never vendored (compiled wheels/binaries
    cannot be vendored under this repo's vendor/README.md convention) - if neither is present
    on the host, the tool still works via the stdlib-ast/filename-floor tiers.
  - Deterministic: two runs on the same input produce byte-identical output. No LLM in this
    script at all.
  - Token-budgeted, not file-count-budgeted: the output stops growing once it would exceed the
    budget, with an explicit footer note naming what got left out - never a silent truncation.

Usage:
  python -m scripts.repo_skeleton [PATH] [--budget N] [--out FILE]

PATH defaults to the current directory. Output goes to stdout unless --out is given.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import shutil
import subprocess  # nosec B404 - fixed-argv git/ctags calls only, never shell=True
import sys
from pathlib import Path

# Directory names skipped entirely during the os.walk fallback (git ls-files already excludes
# gitignored paths for free, so this list only matters when there's no git repo to ask).
_EXCLUDE_DIRS = frozenset(
    {
        "__pycache__",
        ".git",
        ".hg",
        ".svn",
        "node_modules",
        "dist",
        "build",
        "venv",
        ".venv",
        ".tox",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "vendor",  # this repo's own vendored-dependency convention (vendor/README.md)
        ".idea",
        ".vscode",
    }
)
# Suffix-shaped exclusions (egg-info dirs carry a version in the name, so an exact-name
# set can't match them).
_EXCLUDE_SUFFIXES = (".egg-info",)

_PY_EXT = ".py"
# Extensions the filename/heading floor treats as markdown-shaped (heading scan applies).
_MARKDOWN_EXTS = frozenset({".md", ".markdown", ".rst"})

# Rough chars-per-token proxy - the same approximation scripts/subagent_return_budget.py
# already uses (a true count needs the model's own tokenizer, unavailable to a standalone
# script). Not a target to be exact about: the budget check exists to keep output bounded,
# not to hit an exact token count.
_CHARS_PER_TOKEN = 4
_DEFAULT_BUDGET_TOKENS = 6000


def _force_utf8_output() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass


def _estimate_tokens(text: str) -> int:
    return len(text) // _CHARS_PER_TOKEN


# --------------------------------------------------------------------------- inventory


def _git_ls_files(root: Path) -> list[str] | None:
    """Tracked + untracked-but-not-ignored files, via git (None if no repo / git unavailable).
    `-c` (cached/tracked) + `-o --exclude-standard` (other files, respecting .gitignore) covers
    a working tree with uncommitted new files without re-implementing gitignore matching."""
    try:
        result = subprocess.run(  # nosec B603 B607 - fixed argv, no shell
            ["git", "-C", str(root), "ls-files", "-c", "-o", "--exclude-standard", "-z"],
            capture_output=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    raw = result.stdout.decode("utf-8", errors="replace")
    return [p for p in raw.split("\0") if p]


def _os_walk_files(root: Path) -> list[str]:
    """Fallback inventory when there's no git repo to ask - skips _EXCLUDE_DIRS/_EXCLUDE_SUFFIXES
    entirely (not just from the listing - os.walk is told not to descend into them at all, so a
    huge node_modules never gets stat'd file-by-file)."""
    out: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            d
            for d in dirnames
            if d not in _EXCLUDE_DIRS and not any(d.endswith(s) for s in _EXCLUDE_SUFFIXES)
        ]
        rel_dir = Path(dirpath).relative_to(root)
        for name in filenames:
            rel = name if rel_dir == Path(".") else str(rel_dir / name)
            out.append(rel.replace(os.sep, "/"))
    return out


def inventory(root: Path) -> list[str]:
    """Sorted, forward-slash-normalised relative file paths under `root`. Deterministic
    regardless of filesystem iteration order (always sorted before returning)."""
    files = _git_ls_files(root)
    if files is None:
        files = _os_walk_files(root)
    return sorted(set(files))


# --------------------------------------------------------------------------- symbol extraction

_TIER_TREE_SITTER = "tree-sitter"
_TIER_CTAGS = "ctags"
_TIER_AST = "ast"
_TIER_FLOOR = "floor"


def _symbols_tree_sitter(_path: Path) -> list[str] | None:
    """Soft probe only - tree-sitter is never vendored (compiled wheel), so this tier is
    live only when the host environment happens to already have it installed. Not
    implemented beyond the presence probe in this first version: a positive probe with no
    extraction still means "unavailable for now", so callers fall through to the next tier.
    Kept as a real tier (not deleted) so a future version can add real extraction here
    without touching the tiering logic anywhere else."""
    try:
        import tree_sitter  # noqa: F401
    except ImportError:
        return None
    return None  # probed present, but extraction isn't implemented yet - fall through


def _symbols_ctags(path: Path) -> list[str] | None:
    """Soft probe via `ctags` on PATH (never vendored - a compiled binary, not a Python
    package). None if ctags isn't installed OR the call fails/times out for any reason -
    this tier degrading never blocks the always-available floor below it."""
    if shutil.which("ctags") is None:
        return None
    try:
        result = subprocess.run(  # nosec B603 B607 - fixed argv, path arg only
            ["ctags", "-x", "--output-format=json", str(path)],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    names: list[str] = []
    for line in result.stdout.splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        name = row.get("name")
        if name:
            names.append(name)
    return names or None


def _symbols_ast_python(path: Path) -> list[str] | None:
    """Stdlib ast - the always-available floor for Python specifically. Top-level (and
    one-level-nested, e.g. class methods) def/class names, never executes the file."""
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source, filename=str(path))
    except (OSError, SyntaxError, ValueError):
        return None
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.append(node.name)
    return names or None


def _symbols_floor(path: Path) -> list[str]:
    """The universal floor for anything not covered by a richer tier: markdown-shaped files
    contribute their heading lines; everything else contributes nothing beyond its own
    filename (the caller already has the path, so an empty symbol list here is a legitimate,
    honest "no further detail available", not a failure)."""
    if path.suffix.lower() not in _MARKDOWN_EXTS:
        return []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return [
        line.strip("# ").strip()
        for line in text.splitlines()
        if line.lstrip().startswith("#")
    ][:20]  # a runaway heading-shaped file (rare) still can't blow the per-file budget


def extract_symbols(path: Path) -> tuple[list[str], str]:
    """Tiered dispatcher: tree-sitter -> ctags -> stdlib ast (Python only) -> filename/heading
    floor. Returns (symbols, tier_name) - the tier is surfaced in output so a reader knows how
    much to trust the listing (an ast-derived def list is exact; a floor-tier heading scan is
    approximate)."""
    symbols = _symbols_tree_sitter(path)
    if symbols is not None:
        return symbols, _TIER_TREE_SITTER
    symbols = _symbols_ctags(path)
    if symbols is not None:
        return symbols, _TIER_CTAGS
    if path.suffix == _PY_EXT:
        symbols = _symbols_ast_python(path)
        if symbols is not None:
            return symbols, _TIER_AST
    return _symbols_floor(path), _TIER_FLOOR


# --------------------------------------------------------------------------- budgeted output


def _file_block(rel_path: str, symbols: list[str], tier: str, *, compact: bool) -> str:
    if compact:
        head = ", ".join(symbols[:5])
        more = f" (+{len(symbols) - 5} more)" if len(symbols) > 5 else ""
        return f"- {rel_path}: {head}{more}" if symbols else f"- {rel_path}"
    lines = [f"## {rel_path}  [{tier}]"]
    if symbols:
        lines.extend(f"  - {s}" for s in symbols)
    else:
        lines.append("  (no symbols extracted)")
    return "\n".join(lines)


def build_skeleton(
    root: Path, budget_tokens: int = _DEFAULT_BUDGET_TOKENS, *, ranks: dict | None = None
) -> str:
    """Walk `inventory(root)` ranked by `(-rank, path)` (rank defaults to 0 for every file -
    Chunk B wires in real PageRank ranks here without changing this function's shape),
    extracting symbols per file and emitting full detail until the running token estimate
    would exceed `budget_tokens`, then switching remaining files to a compact one-liner tier,
    then omitting the rest with an explicit count - never a silent truncation."""
    files = inventory(root)
    ranks = ranks or {}
    ordered = sorted(files, key=lambda p: (-ranks.get(p, 0.0), p))

    header = [
        f"# Repository skeleton - {root}",
        f"# {len(files)} files inventoried, budget ~{budget_tokens} tokens",
        "",
    ]
    body: list[str] = []
    used_tokens = _estimate_tokens("\n".join(header))
    compact_from: int | None = None
    omitted = 0

    for i, rel_path in enumerate(ordered):
        symbols, tier = extract_symbols(root / rel_path)
        compact = compact_from is not None
        block = _file_block(rel_path, symbols, tier, compact=compact)
        block_tokens = _estimate_tokens(block) + 1
        if used_tokens + block_tokens > budget_tokens:
            if compact_from is None:
                # First file that doesn't fit at full detail - switch this and every
                # remaining file to the compact tier instead of dropping it outright.
                compact_from = i
                block = _file_block(rel_path, symbols, tier, compact=True)
                block_tokens = _estimate_tokens(block) + 1
                if used_tokens + block_tokens > budget_tokens:
                    omitted += 1
                    continue
            else:
                omitted += 1
                continue
        body.append(block)
        used_tokens += block_tokens

    if omitted:
        body.append(
            f"\n...and {omitted} more lower-ranked file(s) omitted "
            "(--budget to raise, or run against a narrower path)."
        )

    return "\n".join(header) + "\n".join(body) + "\n"


# --------------------------------------------------------------------------- CLI


def main(argv: list[str]) -> int:
    _force_utf8_output()
    ap = argparse.ArgumentParser(
        description="Deterministic, token-budgeted first-contact skeleton of a codebase."
    )
    ap.add_argument("path", nargs="?", default=".", help="root to inventory (default: .)")
    ap.add_argument(
        "--budget", type=int, default=_DEFAULT_BUDGET_TOKENS, help="approx. token budget"
    )
    ap.add_argument("--out", type=Path, default=None, help="write to a file instead of stdout")
    args = ap.parse_args(argv[1:])

    root = Path(args.path).expanduser().resolve()
    if not root.is_dir():
        print(f"not a directory: {root}", file=sys.stderr)
        return 1

    text = build_skeleton(root, args.budget)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
        print(f"Wrote skeleton -> {args.out}")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
