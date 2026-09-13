"""Test hygiene: no test may assert an intermediate bug state as a precondition
(2026-09-13 framework review, step 5.7).

The one red test on `dev` that day asserted `STAGED._EXEC_RE.search("...against source
code")` as a PRECONDITION - "the prose really does trip an exec pattern" - and went stale the
moment 236d2cf anchored the pattern so the prose no longer tripped it. A guard regex matching
prose is a defect the guards keep fixing; a test that depends on the defect staying is a test
that fails when the fix lands. This walks every test file's AST and refuses that shape.
"""

from __future__ import annotations

import ast
from pathlib import Path

TESTS = Path(__file__).resolve().parent
_GUARD_REGEXES = {"_EXEC_RE", "_RAW_MARKER_RE", "_TEAM_ALLOW", "_HOOK_MUTATE"}


def _prose(value: str) -> bool:
    """A string with spaces and no path separator reads as prose, not a command or a path."""
    return " " in value and "/" not in value and "\\" not in value


def _offending_asserts(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    hits: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assert):
            continue
        test = node.test
        if not (isinstance(test, ast.Call) and isinstance(test.func, ast.Attribute)):
            continue
        if test.func.attr != "search" or not isinstance(test.func.value, ast.Attribute):
            continue
        if test.func.value.attr not in _GUARD_REGEXES or not test.args:
            continue
        arg = test.args[0]
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str) and _prose(arg.value):
            hits.append(f"{path.name}:{node.lineno}")
    return hits


def test_no_test_asserts_a_guard_regex_matches_prose_as_a_precondition():
    offenders = []
    for path in sorted(TESTS.glob("test_*.py")):
        if path.name == Path(__file__).name:
            continue
        offenders += _offending_asserts(path)
    assert not offenders, (
        "a test asserts a guard regex MATCHES prose as a precondition; that pins a "
        "false-positive defect in place and goes stale when it is fixed: " + ", ".join(offenders)
    )


def test_the_lint_recognises_the_shape_it_exists_for(tmp_path):
    bad = tmp_path / "test_bad.py"
    bad.write_text(
        'def test_x():\n    assert STAGED._EXEC_RE.search("prose about source code"), "trips"\n',
        encoding="utf-8",
    )
    good = tmp_path / "test_good.py"
    good.write_text(
        'def test_y():\n    assert STAGED._EXEC_RE.search("python -m pytest tests/x.py")\n'
        '    assert not STAGED._EXEC_RE.search("prose about source code")\n',
        encoding="utf-8",
    )
    assert _offending_asserts(bad) == ["test_bad.py:2"]
    assert _offending_asserts(good) == []
