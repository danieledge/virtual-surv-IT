#!/usr/bin/env python3
"""Validate a Requirements Traceability Matrix against the code, tests and obligations it claims.

The traceability spine (BRD -> FSD -> code -> test -> obligation) is what lets a surveillance
solution stand up to audit, and `docs/templates/rtm.md` has always specified a
"bidirectional-coverage check (run at each review gate)" - orphan tests, requirements with no
obligation, orphan obligations. Until this script it was a prose instruction with nothing behind
it: an RTM could cite `rules/spoofing.py::detect_spoofing` long after the module was renamed and
every gate would still pass. This is that check, mechanised.

What it reports (one line per finding, machine-readable prefix, same shape as
`scripts/validate_findings.py`):

  RTM-CODE-MISSING       a row's Code cell names a path that does not exist on disk
  RTM-TEST-MISSING       a row's Test cell names a test file that does not exist on disk
  RTM-NO-OBLIGATION      a requirement row cites no regulatory/business obligation AND records
                         no gap disposition - it cannot satisfy the audit trail
  RTM-ORPHAN-OBLIGATION  an obligation in the regulatory register that no row references -
                         advisory: a potential surveillance gap, or simply out of this
                         engagement's scope (the register is firm-wide, an RTM is not)
  RTM-ORPHAN-TEST        a test file that no row references - OPT-IN, and only over the
                         directories named with `--tests-dir` (a repo-wide sweep would drown
                         a single-scenario RTM in noise)
  RTM-MALFORMED          no traceability table found, or a row whose cell count does not
                         match the header

Cells are read tolerantly: backticks, markdown links, `path::symbol` pinpoints, `a, b`
lists and dotted module paths (`rules.spoofing` -> `rules/spoofing.py`) all resolve. A
placeholder cell (`-`, `n/a`, `TBD`, `...`) is "not stated", never a broken path - the
template tracks those in the Gap / exception disposition column.

Exit 0 = the RTM is traceable; exit 1 = findings printed. A missing RTM is NOT a finding
(most engagements never author one) - it exits 0 with a note. stdlib only, so it runs in an
installed plugin with no pip step; output is forced to UTF-8 so it cannot crash a Windows
console. Usage:

  python -m scripts.validate_rtm [rtm.md] [--project-root DIR] [--tests-dir DIR] [--json]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# The bundled register, used when the working project has no overlay of its own (plugin mode).
_BUNDLED_REGISTER = Path(__file__).resolve().parent.parent / "config" / "regulatory-register.yaml"

# The traceability table is identified by its COLUMNS, not by a heading or a row position, so a
# renamed section or a reordered template still validates (same rule check_artifacts.check_map
# uses for map entries). These are the columns the check needs; `docs/templates/rtm.md` spells
# them "Code (module / fn)", "Test", "Regulatory obligation".
_REQUIRED_COLUMNS = ("code", "test", "obligation")

# Cell values that mean "nothing stated here" rather than a path/citation. The template writes a
# gap as `-` and tracks it in the disposition column, so these must not read as broken paths.
_PLACEHOLDERS = {
    *("", "-", "--", "---", "—", "–", "?"),
    *("n/a", "na", "none", "tbd", "tba", "...", "…"),
}

# Test-file naming across the stacks this team works in (Python/pytest, Scala/Java, JS/TS).
_TEST_FILE_RE = re.compile(r"(^test_|_test\.|Test\.|\.spec\.|\.test\.)")

# Where bare test filenames (`test_spoofing.py`, no directory) are looked up when the caller
# names no --tests-dir. Kept to conventional roots: an unbounded repo walk to resolve one cell
# is not worth the I/O on a large working project.
_DEFAULT_TEST_DIRS = ("tests", "test", "src/test")

# Source extensions a Code/Test cell may point at. A cell that is not file-shaped (prose, a
# ticket id, a class name) is left alone rather than reported as a missing path - the check
# exists to catch stale paths, not to police cell wording.
_SOURCE_EXTS = {".py", ".scala", ".sql", ".sh", ".ps1", ".java", ".js", ".ts", ".yaml", ".yml"}

_MD_LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)]+)\)")
_CELL_SPLIT_RE = re.compile(r"[,;]|<br\s*/?>")


def _force_utf8_output() -> None:
    """Windows consoles default to cp1252 and raise on the non-ASCII an RTM carries (`§`, en
    dashes, emoji basis tags). Inlined rather than imported so the script also runs by direct
    path from an installed plugin, where `from scripts...` would not resolve."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass


def _clean(cell: str) -> str:
    """Strip the markdown a cell is dressed in (backticks, bold/italic, link syntax)."""
    text = _MD_LINK_RE.sub(r"\2", cell)
    return text.replace("`", "").replace("**", "").strip()


def _is_placeholder(cell: str) -> bool:
    return _clean(cell).lower() in _PLACEHOLDERS


def _split_cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _is_divider(cells: list[str]) -> bool:
    return bool(cells) and set("".join(cells)) <= {"-", ":", " "}


def parse_rtm(text: str) -> tuple[list[dict], list[str]]:
    """Parse the traceability table out of an RTM document.

    Returns `(rows, problems)`. Each row is `{"label": str, "line": int, "cells": {column: value}}`
    where the column keys are the LOWERCASED header cells. `problems` holds RTM-MALFORMED
    details: no table with the required columns, or a row whose cell count differs from the
    header (a ragged row silently shifts every value one column left - the failure mode that
    makes a matrix lie).

    Only the traceability table is read: the document-control and sign-off tables carry none of
    the required columns, so column-driven detection skips them without needing to know they exist.
    """
    rows: list[dict] = []
    problems: list[str] = []
    header: list[str] | None = None
    header_line = 0
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line.startswith("|"):
            header = None  # any non-table line ends the current table
            continue
        cells = _split_cells(line)
        if _is_divider(cells):
            continue
        lowered = [c.lower() for c in cells]
        if header is None:
            if all(any(col in c for c in lowered) for col in _REQUIRED_COLUMNS):
                header, header_line = lowered, lineno
            continue
        if len(cells) != len(header):
            problems.append(
                f"line {lineno}: row has {len(cells)} cells but the header (line {header_line}) "
                f"has {len(header)} - a ragged row shifts every value into the wrong column"
            )
            continue
        row_cells = dict(zip(header, cells))
        rows.append({"label": _row_label(row_cells, lineno), "line": lineno, "cells": row_cells})
    if header is None and not rows:
        problems.append(
            "no traceability table found - expected a markdown table whose header carries "
            "Code, Test and obligation columns (docs/templates/rtm.md)"
        )
    return rows, problems


def _row_label(cells: dict[str, str], lineno: int) -> str:
    """A human-recognisable name for a row: its requirement id(s), else its line number."""
    ids = [
        _clean(v)
        for k, v in cells.items()
        if ("brd" in k or "fsd" in k or k.strip() in {"id", "req", "requirement"})
        and not _is_placeholder(v)
    ]
    return " / ".join(ids) if ids else f"line {lineno}"


def _column(cells: dict[str, str], keyword: str) -> str:
    """The value of the first column whose header contains *keyword* ('' when absent)."""
    for header, value in cells.items():
        if keyword in header:
            return value
    return ""


def _references(cell: str) -> list[str]:
    """The individual file references in a Code/Test cell, stripped of `::symbol` pinpoints.

    `` `rules/spoofing.py::detect_spoofing`, tests/test_x.py `` -> `['rules/spoofing.py',
    'tests/test_x.py']`. A placeholder cell yields nothing.
    """
    if _is_placeholder(cell):
        return []
    refs = []
    for part in _CELL_SPLIT_RE.split(_clean(cell)):
        ref = part.split("::", 1)[0].strip().strip("'\"")
        if ref and ref.lower() not in _PLACEHOLDERS:
            refs.append(ref)
    return refs


def _candidate_paths(ref: str) -> list[str]:
    """Relative paths *ref* could denote: itself, and the module form `a.b` -> `a/b.py`."""
    candidates = [ref]
    if "/" not in ref and "\\" not in ref and Path(ref).suffix not in _SOURCE_EXTS and "." in ref:
        candidates.append(ref.replace(".", "/") + ".py")
    return candidates


def _file_shaped(ref: str) -> bool:
    """True when *ref* looks like something resolvable on disk - a known source extension, or a
    dotted module path. Prose ("manual control"), ticket ids and class names are left alone."""
    if Path(ref).suffix.lower() in _SOURCE_EXTS:
        return True
    return "." in ref and " " not in ref and "/" not in ref and "\\" not in ref


def _resolve(ref: str, roots: list[Path], by_name: dict[str, list[Path]]) -> bool:
    """True when *ref* resolves to a file under one of *roots*, or - for a bare filename with no
    directory part - to an indexed test file of that name."""
    for candidate in _candidate_paths(ref):
        rel = candidate.replace("\\", "/")
        for root in roots:
            if (root / rel).is_file():
                return True
        if "/" not in rel and by_name.get(Path(rel).name):
            return True
    return False


def index_test_files(dirs: list[Path]) -> dict[str, list[Path]]:
    """Index test files under *dirs* by filename, for resolving bare `test_x.py` cells and for
    the orphan-test sweep. Hidden and cache directories are skipped."""
    index: dict[str, list[Path]] = {}
    for directory in dirs:
        if not directory.is_dir():
            continue
        for path in sorted(directory.rglob("*")):
            if not path.is_file() or not _TEST_FILE_RE.search(path.name):
                continue
            if any(part.startswith((".", "__")) for part in path.parts):
                continue
            index.setdefault(path.name, []).append(path)
    return index


def _normalise_citation(text: str) -> str:
    """Comparable form of an obligation citation: lower-case, 'article' -> 'art', no whitespace
    or dots. 'Article 12(1)(a)' and 'MAR Art.12(1)(a)' compare on the same footing (the rule
    scripts/check_citations.py uses for the same register)."""
    return re.sub(r"[\s.]", "", text.lower().replace("article", "art"))


def _scalar(value: str) -> object:
    """One YAML scalar from the register: a quoted/bare string, or an inline `["a", "b"]` list."""
    value = value.strip()
    if value.startswith("["):
        try:
            return json.loads(value.replace("'", '"'))
        except ValueError:
            return [v.strip().strip("'\"") for v in value.strip("[]").split(",") if v.strip()]
    return value.strip("'\"")


def parse_register(text: str) -> list[dict]:
    """Read the `obligations:` list out of a regulatory register.

    A deliberately minimal YAML reader: this script is stdlib-only so it runs in an installed
    plugin with no pip step, and the register is a flat list of `key: value` entries whose shape
    is fixed by config/regulatory-register.yaml's own documented schema. Only `id`, `pinpoint`
    and `aliases` are used; anything more structured is out of contract and simply not read.
    """
    obligations: list[dict] = []
    current: dict | None = None
    in_block = False
    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if re.match(r"^obligations\s*:\s*$", raw):
            in_block = True
            continue
        if in_block and raw[:1] not in (" ", "\t", "-"):
            in_block = False  # a new top-level key closes the list
        if not in_block:
            continue
        entry = re.match(r"^\s*-\s*([\w-]+)\s*:\s*(.*)$", raw)
        if entry:
            current = {entry.group(1): _scalar(entry.group(2))}
            obligations.append(current)
            continue
        field = re.match(r"^\s+([\w-]+)\s*:\s*(.*)$", raw)
        if field and current is not None:
            current[field.group(1)] = _scalar(field.group(2))
    return obligations


def load_register(project_root: Path, register_path: Path | None = None) -> list[dict]:
    """The obligations in scope: the bundled register, extended/overridden by the working
    project's `config/regulatory-register.yaml` overlay when it is a different file (the
    two-tier pattern check_citations._load_register documents). An explicit *register_path*
    replaces both."""
    paths = [register_path] if register_path else [_BUNDLED_REGISTER]
    overlay = project_root / "config" / "regulatory-register.yaml"
    if not register_path and overlay.is_file() and overlay.resolve() != _BUNDLED_REGISTER.resolve():
        paths.append(overlay)
    merged: dict[str, dict] = {}
    for path in paths:
        if path is None or not path.is_file():
            continue
        for obligation in parse_register(path.read_text(encoding="utf-8", errors="replace")):
            merged[str(obligation.get("id", ""))] = obligation
    return list(merged.values())


def _obligation_cited(obligation: dict, cited_raw: str, cited_norm: str) -> bool:
    """True when an RTM's obligation cells reference *obligation* by id, pinpoint or alias.

    Substring matching on the normalised forms, so `MAR Art.12` counts as cited by a row that
    says `MAR Art.12(1)(a)`. That errs toward NOT reporting an orphan, which is the right
    direction for an advisory finding.
    """
    identifier = str(obligation.get("id", "")).lower()
    if identifier and identifier in cited_raw:
        return True
    keys = [str(obligation.get("pinpoint", ""))] + [
        str(a) for a in (obligation.get("aliases") or []) if isinstance(a, (str, int))
    ]
    return any(k and _normalise_citation(k) in cited_norm for k in keys)


def validate(
    rtm_path: Path,
    project_root: Path | None = None,
    tests_dirs: list[Path] | None = None,
    register_path: Path | None = None,
    check_orphan_tests: bool = False,
) -> dict:
    """Validate one RTM. Returns `{"rtm", "rows", "findings"}`; each finding is
    `{"code", "row", "detail"}` with `code` one of the RTM-* codes in the module docstring.

    *project_root* is the working project the Code/Test cells are relative to (default: cwd);
    the RTM's own directory is always tried too, so code delivered into the engagement pack
    beside the matrix resolves. *tests_dirs* names the directories indexed for bare test
    filenames - passing it explicitly is also what opts the orphan-test sweep in
    (*check_orphan_tests*), because an unscoped sweep reports every unrelated test in the repo.

    Pure apart from filesystem reads; raises OSError if the RTM itself cannot be read.
    """
    root = (project_root or Path.cwd()).resolve()
    roots = [root, rtm_path.resolve().parent]
    index_dirs = tests_dirs if tests_dirs else [root / d for d in _DEFAULT_TEST_DIRS]
    by_name = index_test_files(index_dirs)

    text = rtm_path.read_text(encoding="utf-8", errors="replace")
    rows, problems = parse_rtm(text)
    findings = [{"code": "RTM-MALFORMED", "row": None, "detail": p} for p in problems]

    cited_tests: set[str] = set()
    cited_obligations: list[str] = []
    for row in rows:
        cells = row["cells"]
        for keyword, code in (("code", "RTM-CODE-MISSING"), ("test", "RTM-TEST-MISSING")):
            for ref in _references(_column(cells, keyword)):
                if keyword == "test":
                    cited_tests.add(Path(ref.replace("\\", "/")).name)
                if not _file_shaped(ref) or _resolve(ref, roots, by_name):
                    continue
                findings.append(
                    {
                        "code": code,
                        "row": row["label"],
                        "detail": (
                            f"row {row['label']} cites {ref!r} but no such file exists under "
                            f"{root} - the trace is broken (renamed/moved/never written)"
                        ),
                    }
                )
        obligation = _column(cells, "obligation")
        if _is_placeholder(obligation):
            # A stated gap with an owner and target-close date IS the template's sanctioned
            # handling of a missing obligation ("must be justified or removed"), so a filled
            # disposition cell answers this finding; an empty one leaves it unanswered.
            if _is_placeholder(_column(cells, "disposition")):
                findings.append(
                    {
                        "code": "RTM-NO-OBLIGATION",
                        "row": row["label"],
                        "detail": (
                            f"row {row['label']} cites no regulatory/business obligation and "
                            "records no gap disposition - justify it (owner + target-close "
                            "date in the disposition column) or remove the row"
                        ),
                    }
                )
        else:
            cited_obligations.append(_clean(obligation))

    cited_raw = " | ".join(cited_obligations).lower()
    cited_norm = _normalise_citation(" | ".join(cited_obligations))
    for obligation in load_register(root, register_path):
        if _obligation_cited(obligation, cited_raw, cited_norm):
            continue
        findings.append(
            {
                "code": "RTM-ORPHAN-OBLIGATION",
                "row": None,
                "detail": (
                    f"{obligation.get('pinpoint') or obligation.get('id')} "
                    f"[{obligation.get('id')}] is in the regulatory register but no RTM row "
                    "references it - a potential surveillance gap, or an obligation outside "
                    "this engagement's scope (advisory: confirm which)"
                ),
            }
        )

    if check_orphan_tests:
        scope = ", ".join(str(d) for d in index_dirs)
        for name in sorted(by_name):
            if name in cited_tests:
                continue
            findings.append(
                {
                    "code": "RTM-ORPHAN-TEST",
                    "row": None,
                    "detail": (
                        f"{name} exists under {scope} but no RTM row references it - it may "
                        "test undocumented behaviour or untraceable scope; trace it or "
                        "resolve it before sign-off"
                    ),
                }
            )

    return {"rtm": str(rtm_path), "rows": len(rows), "findings": findings}


def format_findings(findings: list[dict]) -> list[str]:
    """Render findings as `CODE: detail` lines - the one-line-per-finding shape the rest of the
    tooling (validate_findings, check_artifacts) prints and greps for."""
    return [f"{f['code']}: {f['detail']}" for f in findings]


def find_rtm(directory: Path) -> Path | None:
    """The RTM in *directory*, if any. `rtm.md` is a fixed artifact name (operating guide,
    "Where every document lives"); a numbered variant (`rtm-001.md`) is accepted too."""
    if not directory.is_dir():
        return None
    matches = sorted(p for p in directory.glob("*.md") if p.stem.lower().startswith("rtm"))
    return matches[0] if matches else None


def main(argv: list[str] | None = None) -> int:
    _force_utf8_output()
    parser = argparse.ArgumentParser(
        description="Validate an RTM's traceability against code, tests and obligations."
    )
    parser.add_argument(
        "rtm", nargs="?", type=Path, help="path to the RTM .md (default: ./rtm.md, else none)"
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        default=None,
        help="working project the Code/Test cells are relative to (default: cwd)",
    )
    parser.add_argument(
        "--tests-dir",
        type=Path,
        action="append",
        default=[],
        help="directory to index for test files (repeatable); passing it also enables the "
        "RTM-ORPHAN-TEST sweep over exactly those directories",
    )
    parser.add_argument("--register", type=Path, default=None, help="regulatory register to use")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)

    root = args.project_root or Path.cwd()
    rtm_path = args.rtm or find_rtm(root)
    if rtm_path is None:
        # Absence is not a defect: most engagements never author an RTM (CLAUDE.md §8 - the
        # spine is tracked in one when the deliverable warrants it).
        print(f"No RTM found in {root} - nothing to validate.")
        return 0
    if not rtm_path.is_file():
        print(f"RTM-NOT-FOUND: {rtm_path} was given explicitly but does not exist", file=sys.stderr)
        return 1

    result = validate(
        rtm_path,
        project_root=args.project_root,
        tests_dirs=args.tests_dir or None,
        register_path=args.register,
        check_orphan_tests=bool(args.tests_dir),
    )
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        for line in format_findings(result["findings"]):
            print(line)
        if result["findings"]:
            print(
                f"RTM traceability: {len(result['findings'])} finding(s) across "
                f"{result['rows']} row(s) - NOT satisfied ({rtm_path})"
            )
        else:
            print(f"RTM traceability: OK ({rtm_path}; {result['rows']} row(s))")
    return 1 if result["findings"] else 0


if __name__ == "__main__":
    sys.exit(main())
