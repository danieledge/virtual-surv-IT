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

PRIOR ART (added 2026-08-26, after a survey asked the fair question "why build our own?").
This is the same SHAPE as aider's repo map (Apache-2.0): symbol tags -> a file-node graph ->
PageRank importance -> fill to a token budget. None of its code is used here, and it could
not be: aider's tag extraction is tree-sitter, a compiled C extension that cannot be vendored
under vendor/README.md's pure-Python rule, and it is load-bearing there - no tags, no map.
The same constraint rules out every other well-trodden option for their own reasons: SCIP and
LSIF need a working compile (which this repo's own execution guard blocks), LSP-based
retrieval needs a language server per language, and the packers (Repomix, gitingest,
code2prompt) dump a repo rather than ranking and bounding it, which is the opposite of the
job. ADR-007 records the same credit; it is repeated here because this is the file people
actually read. What is NOT aider-shaped: --slice, churn annotation, Mermaid output and the
--fingerprint drift stamps.

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
import re
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


# Answered once per process. Neither answer can change mid-run, and asking per file cost a
# measured 335ms over this repo's 1,294 files (2026-08-25 performance review).
_probe_cache: dict[str, bool] = {}


# Which grammar to ask tree_sitter_language_pack for, per extension. Only languages this
# team actually reviews (docs/scope-and-stack.md and the review lenses) - the pack ships
# ~100, and listing them all would mean claiming coverage nobody has tested.
_TS_LANGS = {
    ".py": "python",
    ".java": "java",
    ".scala": "scala",
    ".kt": "kotlin",
    ".cs": "csharp",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".js": "javascript",
    ".jsx": "javascript",
    ".sql": "sql",
    ".sh": "bash",
    ".bash": "bash",
    ".go": "go",
    ".rb": "ruby",
    ".rs": "rust",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".hpp": "cpp",
}

# Node types that name a symbol worth listing, across grammars. Tree-sitter node type names
# are per-grammar, so this is a union rather than a per-language table: an unknown type is
# simply not collected, which degrades to fewer symbols and never to a wrong one.
_TS_DECL_TYPES = {
    "function_definition",
    "function_declaration",
    "function_item",
    "method_definition",
    "method_declaration",
    "class_definition",
    "class_declaration",
    "class_specifier",
    "interface_declaration",
    "enum_declaration",
    "record_declaration",
    "struct_specifier",
    "struct_item",
    "object_definition",
    "trait_definition",
    "type_definition",
    "module_definition",
    "impl_item",
    "decorated_definition",
    "function_signature",
    "val_definition",
    "var_definition",
    "constructor_declaration",
    # SQL: the pack's grammar names these without a "_statement" suffix. The earlier set
    # used the suffixed forms from a DIFFERENT sql grammar, so SQL matched nothing at all
    # and silently fell through - "exact symbols for SQL" was advertised and never true.
    # Verified against the shipped grammar, 2026-08-27.
    "create_table",
    "create_view",
    "create_function",
    "create_procedure",
    "create_index",
    "create_materialized_view",
    # Scala 3 (verified present in the shipped grammar).
    "given_definition",
    "enum_definition",
    # Kotlin names its objects differently from Scala.
    "object_declaration",
    # C#, which only started reaching this tier when the grammar name was corrected to
    # "csharp" - the old "c_sharp" matched nothing, so every .cs file fell to regex.
    "struct_declaration",
    "delegate_declaration",
    "property_declaration",
    "namespace_declaration",
    # Java @interface.
    "annotation_type_declaration",
}


def _ts_parser(path: Path):
    """A parser for this file's language, or None. Every failure is a None, never a raise.

    The probe is cached per language: importing the pack is cheap but building a parser is
    not, and repo_skeleton walks whole trees.

    "Never a raise" is meant literally, including for an input that is not a path at all -
    this is a fall-through tier on the orientation path, and a tier that can throw is worse
    than a tier that is absent."""
    try:
        lang = _TS_LANGS.get(path.suffix.lower())
    except AttributeError:
        return None
    if not lang:
        return None
    key = f"tree_sitter:{lang}"
    if key not in _probe_cache:
        try:
            from tree_sitter_language_pack import get_parser

            _probe_cache[key] = get_parser(lang)
        except Exception:
            # ImportError (not installed), LookupError (grammar missing from this pack
            # version), OSError (the compiled extension will not load - the AppLocker case).
            # All three mean the same thing to a caller: this tier is unavailable.
            _probe_cache[key] = False
    parser = _probe_cache[key]
    return parser or None


def _ts_symbols_and_ranges(path: Path) -> tuple[list[str], dict] | None:
    """(names, {name: (start_line, end_line)}) via tree-sitter, or None if unavailable.

    IMPLEMENTED 2026-08-26. This tier was a stub for its whole life - it probed for the
    library and then returned None regardless, so every host fell through to the regex
    floor even when the mature parser was sitting right there. Measured on the owner's
    corporate Windows box: tree-sitter installs by plain pip, loads, and parses. The
    packaging objection that kept this stubbed turned out not to hold on the machine it was
    written for.

    Still never vendored (~29MB across platforms, and the core is not abi3 so it would need
    a wheel per Python version). It stays a SOFT probe: present means exact symbols and
    exact ranges for ~15 languages; absent means the regex tier, exactly as before."""
    parser = _ts_parser(path)
    if parser is None:
        return None
    try:
        source = path.read_bytes()
        tree = parser.parse(source)
    except Exception:
        return None
    names: list[str] = []
    ranges: dict = {}
    seen: set = set()

    def walk(node, depth: int = 0) -> None:
        # Bounded: a pathological file must not make orientation the expensive step.
        # Depth 40, not 12: measured, a method of an anonymous class inside a method body
        # already sits at depth 11 in a real Java tree, so 12 pruned genuine symbols -
        # silently, and under a tier label readers are taught to trust. The recursion is
        # cheap and RecursionError is caught by the caller either way.
        if depth > 40 or len(names) >= _REGEX_MAX_SYMBOLS:
            return
        if node.type in _TS_DECL_TYPES:
            ident = None
            for field in ("name", "declarator"):
                try:
                    ident = node.child_by_field_name(field)
                except Exception:
                    ident = None
                if ident is not None:
                    break
            if ident is None:
                # simple_identifier is Kotlin's: without it every `fun` was found and
                # then dropped nameless, so Kotlin listed classes and no methods.
                _IDENT = ("identifier", "type_identifier", "field_identifier", "simple_identifier")
                # SQL wraps the name one level down (create_table -> object_reference ->
                # identifier), so a direct-children-only search found nothing and SQL fell
                # through entirely. These wrappers are descended into, one level, by name -
                # not a general deep search, which would happily pick up an identifier from
                # a body and label it the symbol.
                _WRAPPERS = (
                    "object_reference",
                    "qualified_name",
                    "dotted_name",
                    "scoped_identifier",
                )
                for child in node.children:
                    if child.type in _IDENT:
                        ident = child
                        break
                    if child.type in _WRAPPERS:
                        for inner in child.children:
                            if inner.type in _IDENT:
                                ident = inner
                                break
                        if ident is not None:
                            break
            if ident is not None:
                try:
                    name = source[ident.start_byte : ident.end_byte].decode("utf-8", "replace")
                except Exception:
                    name = ""
                if name and name not in seen:
                    seen.add(name)
                    names.append(name)
                    ranges[name] = (node.start_point[0] + 1, node.end_point[0] + 1)
        for child in node.children:
            walk(child, depth + 1)

    try:
        walk(tree.root_node)
    except RecursionError:
        return None
    return (names, ranges) if names else None


def _symbols_tree_sitter(path: Path) -> list[str] | None:
    """Soft probe - tree-sitter is never vendored, so this tier is live only when the host
    has it installed. None means "unavailable here", and the caller falls through."""
    found = _ts_symbols_and_ranges(path)
    return found[0] if found else None


def _symbols_ctags(path: Path) -> list[str] | None:
    """Soft probe via `ctags` on PATH (never vendored - a compiled binary, not a Python
    package). None if ctags isn't installed OR the call fails/times out for any reason -
    this tier degrading never blocks the always-available floor below it."""
    if _probe_cache.get("ctags") is None:
        _probe_cache["ctags"] = shutil.which("ctags") is not None
    if not _probe_cache["ctags"]:
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


# Every Python file was read and ast.parsed TWICE - once for symbols, once for the import
# graph - which measured 1,472 parses over 736 files and dominated the profile (2026-08-25
# performance review). One parse, one walk, both answers cached. Results are cached, not the
# trees: an AST for every file in a large repo is a lot of memory to hold for no benefit.
_python_facts_cache: dict[str, tuple[list[str], set[str]]] = {}
# name -> (start_line, end_line), per file. Populated by the SAME walk as the names above -
# ast nodes already carry lineno/end_lineno, so this costs two attribute reads and was
# simply being discarded (2026-08-26 exploration audit). Ranges are what make `--slice`
# possible, and `--slice` is what makes "don't full-read a 2,800-line file" a cheap action
# rather than a rule someone has to remember.
_python_ranges_cache: dict[str, dict[str, tuple[int, int]]] = {}


def _python_facts(path: Path) -> tuple[list[str], set[str]]:
    """(def/class names, imported top-level modules) from ONE parse. Never executes."""
    key = str(path)
    cached = _python_facts_cache.get(key)
    if cached is not None:
        return cached
    names: list[str] = []
    modules: set[str] = set()
    ranges: dict[str, tuple[int, int]] = {}
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"), filename=key)
    except (OSError, SyntaxError, ValueError):
        _python_facts_cache[key] = ([], set())
        _python_ranges_cache[key] = {}
        return [], set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.append(node.name)
            end = getattr(node, "end_lineno", None) or node.lineno
            # A decorated def reports lineno at the `def`, not the first decorator - take
            # the earliest decorator so a slice includes what applies to the symbol.
            start = node.lineno
            for decorator in getattr(node, "decorator_list", []) or []:
                start = min(start, getattr(decorator, "lineno", start))
            # Last definition wins on a duplicate name, matching what the file would do.
            ranges[node.name] = (start, end)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            modules.add(node.module)
    _python_facts_cache[key] = (names, modules)
    _python_ranges_cache[key] = ranges
    return names, modules


def python_symbol_ranges(path: Path) -> dict:
    """{symbol: (start_line, end_line)} for a Python file, exact (stdlib ast, never runs
    the file). Empty for anything unparseable - callers fall back to reading."""
    _python_facts(path)
    return _python_ranges_cache.get(str(path), {})


def _symbols_ast_python(path: Path) -> list[str] | None:
    """Stdlib ast - the always-available floor for Python specifically. Top-level (and
    one-level-nested, e.g. class methods) def/class names, never executes the file."""
    names, _modules = _python_facts(path)
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
        line.strip("# ").strip() for line in text.splitlines() if line.lstrip().startswith("#")
    ][:20]  # a runaway heading-shaped file (rare) still can't blow the per-file budget


# --------------------------------------------------------------------------- regex tier
#
# WHY THIS TIER EXISTS (2026-08-24). Until now anything that was not Python or Markdown got
# NOTHING from the skeleton beyond its own filename: tree-sitter and ctags are optional
# probes, and neither is present on a locked-down corporate box (nor, as it happens, on the
# dev box). Surveillance systems in banks are overwhelmingly Java, C#, SQL and Scala, so the
# codebase map degraded to a file listing on exactly the work it was built for.
#
# This closes that without touching the constraint that caused it: pure stdlib, no compiled
# wheel, no install, no network. Regex is a deliberate choice, not a shortcut - a real parser
# for five languages cannot be vendored, and the alternative on offer was nothing at all.
#
# HONESTY ABOUT WHAT IT IS. Regex cannot parse these languages and does not pretend to. It
# finds DECLARATION LINES, which is what a first-contact skeleton needs ("what is in this
# file"), and it will miss things inside unusual formatting and occasionally over-match in a
# comment or string. That is why it is its own tier: the tier name travels with the output,
# so a reader knows an `ast` listing is exact and a `regex` listing is indicative. Anchored
# at line starts (allowing indentation and modifiers) to keep the over-matching low.
_TIER_REGEX = "regex"

# Modifier soup that can precede a declaration in these languages, matched loosely on purpose.
_MODS = r"(?:(?:public|private|protected|internal|static|final|abstract|override|virtual|sealed|async|partial|synchronized|native|transient|strictfp|implicit|lazy|open|case|suspend)\s+)*"

_REGEX_RULES: dict[str, tuple[tuple[str, str], ...]] = {
    ".java": (
        (rf"^\s*{_MODS}(?:class|interface|enum|record)\s+(\w+)", "type"),
        (
            rf"^\s*{_MODS}(?:[\w<>\[\],.?\s]+\s+)?(\w+)\s*\([^;{{]*\)\s*(?:throws [\w,.\s]+)?\{{",
            "method",
        ),
    ),
    ".cs": (
        (rf"^\s*{_MODS}(?:class|interface|enum|struct|record)\s+(\w+)", "type"),
        (rf"^\s*{_MODS}(?:[\w<>\[\],.?\s]+\s+)?(\w+)\s*\([^;{{]*\)\s*\{{", "method"),
    ),
    ".scala": (
        (rf"^\s*{_MODS}(?:class|trait|object|enum)\s+(\w+)", "type"),
        (rf"^\s*{_MODS}def\s+(\w+)", "def"),
    ),
    ".kt": (
        (rf"^\s*{_MODS}(?:class|interface|object|enum class)\s+(\w+)", "type"),
        (rf"^\s*{_MODS}fun\s+(?:<[^>]+>\s*)?(?:[\w.]+\.)?(\w+)", "fun"),
    ),
    ".sql": (
        (
            r"^\s*CREATE\s+(?:OR\s+REPLACE\s+)?(?:GLOBAL\s+|LOCAL\s+|TEMP\w*\s+)?"
            r"(TABLE|VIEW|PROCEDURE|PROC|FUNCTION|INDEX|TRIGGER|SCHEMA|TYPE|MATERIALIZED VIEW)"
            r"\s+(?:IF\s+NOT\s+EXISTS\s+)?([\w.\[\]\"`]+)",
            "sql",
        ),
    ),
}
# JS/TS share a ruleset - common in surveillance dashboards and tooling.
_REGEX_RULES[".ts"] = _REGEX_RULES[".tsx"] = _REGEX_RULES[".js"] = _REGEX_RULES[".jsx"] = (
    (r"^\s*(?:export\s+)?(?:abstract\s+)?class\s+(\w+)", "class"),
    (r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s*\*?\s*(\w+)", "function"),
    (
        r"^\s*(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?(?:\([^)]*\)|\w+)\s*=>",
        "arrow",
    ),
)

_REGEX_COMPILED = {
    suffix: tuple((re.compile(pattern), kind) for pattern, kind in rules)
    for suffix, rules in _REGEX_RULES.items()
}
_REGEX_MAX_LINES = 4000  # a generated 100k-line file must not cost the whole budget
_REGEX_MAX_SYMBOLS = 40  # per file, same reasoning as the floor tier's heading cap
_REGEX_SKIP_NAMES = frozenset(
    {"if", "for", "while", "switch", "catch", "do", "else", "try", "using", "lock", "return"}
)


def _symbols_regex(path: Path) -> list[str] | None:
    """Declaration-line symbols for languages with no parser available here. None when the
    suffix has no ruleset, so the dispatcher falls through to the floor exactly as before."""
    rules = _REGEX_COMPILED.get(path.suffix.lower())
    if rules is None:
        return None
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    found: list[str] = []
    seen: set[str] = set()
    for line in text.splitlines()[:_REGEX_MAX_LINES]:
        stripped = line.lstrip()
        # Cheap comment guard - control-flow keywords that look like calls are handled by
        # _REGEX_SKIP_NAMES below, but a commented-out declaration is pure noise.
        if stripped.startswith(("//", "*", "#", "--", "/*")):
            continue
        for pattern, kind in rules:
            match = pattern.match(line)
            if not match:
                continue
            groups = [g for g in match.groups() if g]
            name = groups[-1].strip('"`[]')
            if name.lower() in _REGEX_SKIP_NAMES:
                continue
            # SQL's rule captures the object type too - report "table orders", not "sql
            # orders". Knowing a name is a VIEW rather than a PROCEDURE is most of the value
            # of seeing it at all in a surveillance schema.
            shown = groups[0].lower() if kind == "sql" and len(groups) > 1 else kind
            label = f"{shown} {name}"
            if label not in seen:
                seen.add(label)
                found.append(label)
            break
        if len(found) >= _REGEX_MAX_SYMBOLS:
            break
    return found


def extract_symbols(path: Path) -> tuple[list[str], str]:
    """Tiered dispatcher: tree-sitter -> ctags -> stdlib ast (Python only) -> regex
    (Java/C#/Scala/Kotlin/SQL/JS/TS) -> filename/heading floor. Returns (symbols, tier_name) - the tier is surfaced in output so a reader knows how
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
    symbols = _symbols_regex(path)
    if symbols is not None:
        return symbols, _TIER_REGEX
    return _symbols_floor(path), _TIER_FLOOR


# --------------------------------------------------------------------------- reference graph + rank


def build_reference_graph(root: Path, files: list[str]) -> dict[str, set[str]]:
    """Best-effort file-level def/ref graph. Python-only for this version - the ast tier is the
    only one that gives real import statements without a heavier parser dependency; non-Python
    files simply contribute no edges (uniform base rank, not an error). A future version can add
    an import-graph builder per language without changing pagerank()/the ranking contract.
    `files` are root-relative (as returned by inventory()) - resolved against `root` to read
    each file, never against the current working directory."""
    py_files = {f for f in files if f.endswith(_PY_EXT)}
    module_index: dict[str, str] = {}
    for f in py_files:
        p = Path(f)
        if p.name == "__init__.py":
            dotted = ".".join(p.parent.parts)
        else:
            dotted = ".".join((*p.parent.parts, p.stem)) if p.parent.parts else p.stem
        if dotted:
            module_index[dotted] = f

    graph: dict[str, set[str]] = {f: set() for f in files}
    for f in sorted(py_files):
        for mod in _python_import_modules(root / f):
            target = module_index.get(mod)
            if target is None and "." in mod:
                # "from foo.bar import baz" where baz is a symbol, not a module - foo.bar
                # itself is still the right file-level edge.
                target = module_index.get(mod.rsplit(".", 1)[0])
            if target and target != f:
                graph[f].add(target)
    return graph


def _python_import_modules(path: Path) -> set[str]:
    """Top-level (non-relative) import module names from one Python file - AST-only, never
    executes the file. Relative imports (`from . import x`) are skipped: resolving them needs
    the importing file's own package position, which is a real feature but not needed for a
    first version whose absolute-import coverage already gives PageRank a real graph to rank
    with on typical Python projects."""
    _names, modules = _python_facts(path)
    return modules


_DAMPING = 0.85
_PAGERANK_ITERATIONS = 50
_PAGERANK_TOL = 1e-6


def pagerank(graph: dict[str, set[str]]) -> dict[str, float]:
    """Minimal pure-stdlib power-iteration PageRank over a file-level def/ref graph - no
    numpy/networkx (ADR-007's compiled-wheel constraint: neither can be vendored under this
    repo's vendor/README.md convention). Uniform personalization - no engagement-aware
    weighting (recently-edited-file boosts etc. are Phase 3 territory, ADR-007). Deterministic:
    nodes are always iterated in sorted order, so floating-point summation order never varies
    run to run on the same input graph."""
    nodes = sorted({*graph} | {t for outs in graph.values() for t in outs})
    if not nodes:
        return {}
    n = len(nodes)
    base = 1.0 / n
    scores = {node: base for node in nodes}
    out_deg = {node: len(graph.get(node, ())) for node in nodes}
    dangling = [node for node in nodes if out_deg[node] == 0]
    for _ in range(_PAGERANK_ITERATIONS):
        new_scores = {node: (1 - _DAMPING) * base for node in nodes}
        leaked = _DAMPING * sum(scores[d] for d in dangling) * base
        for node in nodes:
            new_scores[node] += leaked
        for src in nodes:
            targets = graph.get(src) or set()
            if not targets:
                continue
            share = _DAMPING * scores[src] / out_deg[src]
            for dst in sorted(targets):
                new_scores[dst] += share
        delta = sum(abs(new_scores[k] - scores[k]) for k in nodes)
        scores = new_scores
        if delta < _PAGERANK_TOL:
            break
    return scores


# --------------------------------------------------------------------------- Mermaid


def _mermaid_node_id(rel_path: str) -> str:
    return re.sub(r"[^0-9a-zA-Z_]", "_", rel_path)


def render_mermaid(graph: dict[str, set[str]]) -> str:
    """Deterministic `graph TD` Mermaid subset - the smallest useful one (labelled nodes,
    `-->` edges, nothing else: no subgraphs, no classDef, no click handlers). Nodes sorted by
    path, edges collected into a set then sorted before emission - dict/set iteration order is
    not a determinism guarantee on its own, sorting before emission is the whole story. Only
    files that actually have an edge (source or target) are drawn - an isolated file with no
    import relationship to anything else adds no signal to a dependency diagram."""
    edges: set[tuple[str, str]] = set()
    for src, targets in graph.items():
        for dst in targets:
            edges.add((src, dst))
    if not edges:
        return "graph TD\n"
    connected = sorted({n for pair in edges for n in pair})
    lines = ["graph TD"]
    for node in connected:
        lines.append(f'    {_mermaid_node_id(node)}["{node}"]')
    for src, dst in sorted(edges):
        lines.append(f"    {_mermaid_node_id(src)} --> {_mermaid_node_id(dst)}")
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- churn


def git_churn(root: Path, files: list[str]) -> dict[str, int] | None:
    """Commit-count churn per file, ONE batched `git log` call - not one per file, same "one
    subprocess, not N" discipline as scripts/check_artifacts.py's _batch_resolve_shas. None if
    git is unavailable (caller falls back to mtime-based churn, tagged inferred, at that
    point) - never raises."""
    try:
        result = subprocess.run(  # nosec B603 B607 - fixed argv, no shell
            ["git", "-C", str(root), "log", "--name-only", "--pretty=format:", "--no-renames"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    inventory_set = set(files)
    counts: dict[str, int] = {}
    for line in result.stdout.splitlines():
        line = line.strip()
        if line in inventory_set:
            counts[line] = counts.get(line, 0) + 1
    return counts


def mtime_churn(root: Path, files: list[str]) -> dict[str, float]:
    """Fallback churn signal when there's no git repo to ask: raw mtime. Tagged 🧠 inferred
    wherever displayed (never 📊 measured like the git-log figure) - it conflates recency with
    actual change frequency, which git-log commit counts do not."""
    out: dict[str, float] = {}
    for f in files:
        try:
            out[f] = (root / f).stat().st_mtime
        except OSError:
            pass
    return out


def compute_ranks(root: Path, files: list[str]) -> dict[str, float]:
    """PageRank over the best-effort reference graph - the single entry point main() calls to
    wire real ranks into build_skeleton() (which otherwise defaults every file to rank 0, i.e.
    path-only ordering)."""
    return pagerank(build_reference_graph(root, files))


# --------------------------------------------------------------------------- budgeted output


def _churn_suffix(rel_path: str, churn: dict | None, churn_measured: bool) -> str:
    if not churn or rel_path not in churn:
        return ""
    value = churn[rel_path]
    if churn_measured:
        return f", churn: {value} commits (\U0001f4ca measured)"
    from datetime import datetime, timezone

    dt = datetime.fromtimestamp(value, tz=timezone.utc).strftime("%Y-%m-%d")
    return f", last modified {dt} (\U0001f9e0 inferred - no git history to measure churn)"


def _file_block(
    rel_path: str,
    symbols: list[str],
    tier: str,
    *,
    compact: bool,
    churn: dict | None = None,
    churn_measured: bool = False,
) -> str:
    suffix = _churn_suffix(rel_path, churn, churn_measured)
    if compact:
        head = ", ".join(symbols[:5])
        more = f" (+{len(symbols) - 5} more)" if len(symbols) > 5 else ""
        return f"- {rel_path}: {head}{more}{suffix}" if symbols else f"- {rel_path}{suffix}"
    lines = [f"## {rel_path}  [{tier}]{suffix}"]
    if symbols:
        lines.extend(f"  - {s}" for s in symbols)
    else:
        lines.append("  (no symbols extracted)")
    return "\n".join(lines)


def build_skeleton(
    root: Path,
    budget_tokens: int = _DEFAULT_BUDGET_TOKENS,
    *,
    ranks: dict | None = None,
    churn: dict | None = None,
    churn_measured: bool = False,
    mermaid_graph: dict | None = None,
    files: list[str] | None = None,
) -> str:
    """Walk `inventory(root)` (or the pre-computed `files` list, if the caller already has one -
    main() passes it to avoid a second `git ls-files` subprocess call for the same tree) ranked
    by `(-rank, path)` (rank defaults to 0 for every file if `ranks` is omitted - path-only
    ordering), extracting symbols per file and emitting full detail until the running token
    estimate would exceed `budget_tokens`, then switching remaining files to a compact
    one-liner tier, then omitting the rest with an explicit count - never a silent truncation.
    `churn` (rel_path -> commit count or mtime, see compute_ranks()'s caller in main()) is
    display-only, never a ranking input. `mermaid_graph`, if given, appends a rendered
    dependency diagram after the file listing."""
    files = inventory(root) if files is None else files
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
        block = _file_block(
            rel_path, symbols, tier, compact=compact, churn=churn, churn_measured=churn_measured
        )
        block_tokens = _estimate_tokens(block) + 1
        if used_tokens + block_tokens > budget_tokens:
            if compact_from is None:
                # First file that doesn't fit at full detail - switch this and every
                # remaining file to the compact tier instead of dropping it outright.
                compact_from = i
                block = _file_block(
                    rel_path,
                    symbols,
                    tier,
                    compact=True,
                    churn=churn,
                    churn_measured=churn_measured,
                )
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

    out = "\n".join(header) + "\n".join(body) + "\n"
    if mermaid_graph is not None:
        rendered = render_mermaid(mermaid_graph)
        if rendered.strip() != "graph TD":
            out += "\n## Dependency graph\n\n```mermaid\n" + rendered + "```\n"
    return out


# --------------------------------------------------------------------------- drift-stamp writer

_FINGERPRINTS_FILENAME = "codebase-map.fingerprints.json"


def _split_paths_cell(cell: str) -> list[str]:
    return [g.strip() for g in cell.split(",") if g.strip()]


def _parse_map_paths_column(map_path: Path) -> dict[str, list[str]]:
    """Area -> globs, from the §2 table's optional `Paths` column - same column-driven
    detection scripts.check_artifacts.check_map() already uses for As-of/Anchor (a table
    without a Paths column contributes nothing, additively - no error, no entries)."""
    if not map_path.is_file():
        return {}
    lines = map_path.read_text(encoding="utf-8", errors="replace").splitlines()
    columns: dict[str, int] | None = None
    result: dict[str, list[str]] = {}
    for line in lines:
        if not line.lstrip().startswith("|"):
            columns = None
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if not cells or set("".join(cells)) <= {"-", ":", " "}:
            continue
        lowered = [c.lower() for c in cells]
        if any("basis" in c for c in lowered):
            columns = {name: i for i, name in enumerate(lowered)}
            continue
        if columns is None:
            continue
        area_idx = columns.get("area")
        paths_idx = next((i for n, i in columns.items() if "paths" in n), None)
        if area_idx is None or paths_idx is None:
            continue
        if area_idx >= len(cells) or paths_idx >= len(cells):
            continue
        area = cells[area_idx].strip()
        globs = _split_paths_cell(cells[paths_idx])
        if area and globs:
            result[area] = globs
    return result


def _current_head_sha(repo_root: Path) -> str:
    try:
        result = subprocess.run(  # nosec B603 B607 - fixed argv, no shell
            ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return "no-vcs"
    sha = result.stdout.strip()
    return sha if result.returncode == 0 and sha else "no-vcs"


def _load_map_fingerprint_module():
    """Import scripts.map_fingerprint in BOTH run modes - same dual-mode pattern as
    scripts.check_artifacts._load_map_fingerprint_module (proper package import when run as
    `-m scripts.repo_skeleton`; a file-relative importlib fallback when run by direct path,
    the plugin-mode invocation form with no package context to resolve `scripts.` against).
    Bug found 2026-08-06 building Chunk E: the plain `from scripts.map_fingerprint import ...`
    this replaced worked only in the first mode, so `--fingerprint` crashed with
    ModuleNotFoundError under the exact invocation form /map-codebase (Chunk E) needs."""
    try:
        from scripts import map_fingerprint

        return map_fingerprint
    except ImportError:
        pass
    import importlib.util

    path = Path(__file__).with_name("map_fingerprint.py")
    spec = importlib.util.spec_from_file_location("map_fingerprint", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_fingerprints(
    map_path: Path, project_dir: Path | None = None, out_path: Path | None = None
) -> dict:
    """Read a codebase map's (root OR an area file - identical §2 table shape, so this
    function has no notion of "root" vs "area", just "a map-shaped file") `Paths` column,
    fingerprint each entry's globs (scripts.map_fingerprint.compute_fingerprint), and write
    the sidecar to the SAME directory as map_path (design: docs/adr/ADR-007-codebase-map-
    evolution.md) - never a project-root-relative path, so the root map's sidecar
    (docs/codebase-map.fingerprints.json) and each docs/codebase-map.d/ area file's shared
    sidecar (docs/codebase-map.d/codebase-map.fingerprints.json) each live next to what they
    describe. Bug found 2026-08-06 (Chunk E): scripts.check_artifacts._check_map_drift used
    to look for the sidecar at project_dir/<name> while this wrote it at
    map_path.parent/<name> - identical only when the map lives at the project ROOT, silently
    wrong for the documented default location (docs/codebase-map.md) - fixed on both sides
    together, see that function's own docstring.

    `project_dir` is a SEPARATE concern from the sidecar's location: it is what the Paths
    column's globs are relative to (`scripts/*.py` means the project's own scripts/, not
    docs/scripts/) and what `_check_map_drift` also uses for the exact same globs - the two
    must agree, or every entry drifts permanently the moment the map isn't at the project
    root. Second bug found alongside the first: this used to hash relative to map_path.parent
    (silently wrong for the same reason). Defaults to map_path.parent only as a last resort
    (correct for a map placed directly at the project root); the CLI passes it explicitly.

    MERGES into an existing sidecar rather than overwriting it (2026-08-06, needed once
    multiple area files share one directory and therefore one sidecar): re-fingerprinting
    file A must not erase file B's already-recorded entries."""
    from datetime import datetime, timezone

    mf = _load_map_fingerprint_module()
    compute_fingerprint, resolve_globs = mf.compute_fingerprint, mf.resolve_globs

    project_dir = project_dir or map_path.parent
    sidecar_dir = map_path.parent
    out_path = out_path or (sidecar_dir / _FINGERPRINTS_FILENAME)
    existing_entries: dict = {}
    if out_path.is_file():
        try:
            existing = json.loads(out_path.read_text(encoding="utf-8"))
            existing_entries = existing.get("entries") or {} if isinstance(existing, dict) else {}
        except (OSError, ValueError):
            existing_entries = {}  # unreadable/corrupt sidecar - rebuild from this file only
    entries = dict(existing_entries)
    for area, globs in _parse_map_paths_column(map_path).items():
        fp = compute_fingerprint(globs, project_dir)
        files_hashed = len(resolve_globs(globs, project_dir))
        entries[area] = {"paths": globs, "fingerprint": fp, "files_hashed": files_hashed}
    payload = {
        "generated_by": "repo_skeleton",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "root_anchor": _current_head_sha(project_dir),
        "entries": entries,
    }
    out_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


# --------------------------------------------------------------------------- slice


# Anchors for languages with no stdlib parser. Deliberately conservative: they find where a
# symbol STARTS; the end is inferred by brace/indent, and the tier is reported so a reader
# knows whether a range is exact or indicative - the same honesty contract the symbol tiers
# already carry.
_SLICE_ANCHORS = (
    r"^\s*(?:@\w+[^\n]*\n\s*)*(?:(?:public|private|protected|final|static|abstract|"
    r"override|implicit|lazy|case|sealed)\s+)*"
    r"(?:def|class|object|trait|interface|enum|record|fun|func|val|var|function)\s+{name}\b",
    r"^\s*(?:export\s+)?(?:async\s+)?(?:function|class|const|let|var)\s+{name}\b",
    r"^\s*(?:CREATE\s+(?:OR\s+REPLACE\s+)?(?:PROCEDURE|FUNCTION|VIEW|TABLE))\s+{name}\b",
    r"^\s*{name}\s*(?:=|:)\s*(?:function|\()",
)


def _slice_range_regex(lines: list[str], name: str) -> tuple[int, int] | None:
    """Best-effort (start, end) for a symbol in a non-Python file.

    Finds the declaration line, then walks forward closing braces from the first one seen.
    With no braces (SQL, indent-structured text) it falls back to the next declaration at
    the same or lower indent, and failing that a bounded window - never the whole file,
    because "I could not find the end" must still cost less than a full read."""
    import re as _re

    for template in _SLICE_ANCHORS:
        pattern = _re.compile(template.format(name=_re.escape(name)), _re.IGNORECASE)
        for index, line in enumerate(lines):
            if not pattern.search(line):
                continue
            start = index
            depth = 0
            seen_brace = False
            for cursor in range(index, min(len(lines), index + 2000)):
                depth += lines[cursor].count("{") - lines[cursor].count("}")
                if "{" in lines[cursor]:
                    seen_brace = True
                if seen_brace and depth <= 0:
                    return start + 1, cursor + 1
            if not seen_brace:
                base = len(lines[index]) - len(lines[index].lstrip())
                for cursor in range(index + 1, len(lines)):
                    stripped = lines[cursor].strip()
                    if not stripped:
                        continue
                    indent = len(lines[cursor]) - len(lines[cursor].lstrip())
                    if indent <= base and any(
                        _re.compile(tpl.format(name=r"\w+"), _re.IGNORECASE).search(lines[cursor])
                        for tpl in _SLICE_ANCHORS
                    ):
                        return start + 1, cursor
                return start + 1, min(len(lines), start + 120)
            return start + 1, min(len(lines), start + 120)
    return None


def slice_symbol(path: Path, name: str) -> tuple[str, str] | None:
    """Return (text, tier) for one symbol's body, or None if it cannot be located.

    THE POINT (2026-08-26 exploration audit): a review that needs one 30-line function out
    of a 2,800-line file was reading the whole file - roughly 31,700 tokens to obtain about
    340. Exact for Python via stdlib ast; indicative elsewhere via anchors. Never executes
    anything it reads."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    lines = text.splitlines()
    if path.suffix.lower() == ".py":
        ranges = python_symbol_ranges(path)
        found = ranges.get(name)
        if found:
            start, end = found
            return "\n".join(lines[start - 1 : end]), "ast"
    # tree-sitter next: exact ranges for ~15 languages when the host has it, which is the
    # difference between an exact Scala/Java slice and an anchor-and-brace-count guess.
    # Absent, this costs one dict lookup and falls straight through.
    ts = _ts_symbols_and_ranges(path)
    if ts and name in ts[1]:
        start, end = ts[1][name]
        return "\n".join(lines[start - 1 : end]), "tree-sitter"
    found = _slice_range_regex(lines, name)
    if not found:
        return None
    start, end = found
    return "\n".join(lines[start - 1 : end]), "regex"


# --------------------------------------------------------------------------- CLI


def main(argv: list[str]) -> int:
    _force_utf8_output()
    ap = argparse.ArgumentParser(
        description="Deterministic, token-budgeted first-contact skeleton of a codebase."
    )
    ap.add_argument("path", nargs="?", default=".", help="root to inventory (default: .)")
    ap.add_argument(
        "--slice",
        metavar="FILE:SYMBOL",
        default=None,
        help="print ONE symbol's body instead of an inventory, e.g. "
        "--slice scripts/engagement_state.py:set_status . Exact for Python (stdlib ast); "
        "best-effort elsewhere. Use this instead of reading a large file whole.",
    )
    ap.add_argument(
        "--budget", type=int, default=_DEFAULT_BUDGET_TOKENS, help="approx. token budget"
    )
    ap.add_argument("--out", type=Path, default=None, help="write to a file instead of stdout")
    ap.add_argument(
        "--no-rank",
        action="store_true",
        help="skip PageRank (path-only ordering) - useful on a huge non-Python tree where the "
        "reference graph would be empty anyway",
    )
    ap.add_argument(
        "--no-churn", action="store_true", help="skip git-log/mtime churn annotation per file"
    )
    ap.add_argument(
        "--mermaid",
        action="store_true",
        help="append a Mermaid dependency graph section (only edges PageRank could resolve)",
    )
    ap.add_argument(
        "--fingerprint",
        type=Path,
        default=None,
        metavar="MAP_PATH",
        help="drift-stamp mode: read MAP_PATH's codebase-map §2 'Paths' column, fingerprint "
        "each entry's globs (relative to --project-dir, default: current directory), write/"
        "merge codebase-map.fingerprints.json alongside MAP_PATH. Ignores --budget/--out/"
        "--mermaid/etc - this is a separate mode, not a skeleton render",
    )
    ap.add_argument(
        "--project-dir",
        type=Path,
        default=None,
        metavar="DIR",
        help="with --fingerprint only: what the Paths column's globs are relative to - "
        "default: current directory (run this from the project root, the normal case)",
    )
    args = ap.parse_args(argv[1:])

    if args.slice:
        # FILE:SYMBOL - rsplit so a Windows drive letter ("C:/x/y.py:name") still splits
        # on the right colon.
        target, _, symbol = args.slice.rpartition(":")
        if not target or not symbol:
            print("--slice expects FILE:SYMBOL", file=sys.stderr)
            return 2
        path = Path(target).expanduser()
        if not path.is_file():
            print(f"not a file: {path}", file=sys.stderr)
            return 1
        found = slice_symbol(path, symbol)
        if found is None:
            print(
                f"symbol not found: {symbol} in {path}\n"
                "Locate it first with Grep, then slice, or read the file if it is short.",
                file=sys.stderr,
            )
            return 1
        body, tier = found
        # The tier travels with the output, same honesty contract the symbol tiers carry:
        # 'ast' is exact, 'regex' located the declaration and inferred the end.
        print(f"# {path}:{symbol}  [{tier}]")
        print(body)
        return 0

    if args.fingerprint:
        map_path = args.fingerprint.expanduser().resolve()
        if not map_path.is_file():
            print(f"not a file: {map_path}", file=sys.stderr)
            return 1
        project_dir = (args.project_dir or Path.cwd()).expanduser().resolve()
        payload = write_fingerprints(map_path, project_dir=project_dir)
        out_path = map_path.parent / _FINGERPRINTS_FILENAME
        print(f"Wrote {len(payload['entries'])} fingerprint(s) -> {out_path}")
        return 0

    root = Path(args.path).expanduser().resolve()
    if not root.is_dir():
        print(f"not a directory: {root}", file=sys.stderr)
        return 1

    files = inventory(root)
    graph = None if (args.no_rank and not args.mermaid) else build_reference_graph(root, files)
    ranks = {} if args.no_rank else pagerank(graph)

    churn = None
    churn_measured = False
    if not args.no_churn:
        churn = git_churn(root, files)
        churn_measured = churn is not None
        if churn is None:
            churn = mtime_churn(root, files)

    text = build_skeleton(
        root,
        args.budget,
        ranks=ranks,
        churn=churn,
        churn_measured=churn_measured,
        mermaid_graph=graph if args.mermaid else None,
        files=files,
    )
    if args.out:
        args.out.write_text(text, encoding="utf-8")
        print(f"Wrote skeleton -> {args.out}")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
