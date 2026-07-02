---
name: Python Issues
model: sonnet
applies_to: ["*.py"]
---

> Vendored from **turingmind-code-review** (MIT, © 2026 TuringMind) and lightly adapted. This
> is the **preferred Python lens** - it's mature; keep it close to upstream. See THIRD-PARTY-LICENSES.md.

Language-specific checks for Python.

## Checks

### Type safety
- Missing type hints on public signatures; `Any` where a specific type is known; incorrect
  `Optional` handling.

### Common pitfalls
- Mutable default arguments (`def foo(x=[])`); bare `except:`; `is` for value comparison;
  missing `if __name__ == "__main__"`.

### Resource management
- Missing context managers for files/connections; unclosed cursors; missing `finally`.

### Performance (matters at surveillance volumes)
- String concatenation in loops (use `join`); repeated dict lookups; loading large files wholly
  into memory instead of streaming; per-row work that should be vectorised.

### Data extraction (pandas / openpyxl pitfalls)
- `nrows=`/`skipfooter=`/`ws.max_row` caps that silently truncate; `wb.active` when the data
  sheet isn't first; `pd.read_*(..., errors="coerce")` turning bad values into silent NaNs;
  `dtype=str` vs mixed-type columns; `encoding errors="ignore"` eating bytes. Extraction with
  no source-vs-output reconciliation is a finding (see `lenses/bugs.md`).

## Output

Use the shared format in `docs/review/output-format.md`: `file:line`, confidence, evidence
basis (📊 measured / 🧠 inferred), and a `diff`-style fix + "why this works". Drive
`ruff`/`mypy`/`bandit` where available and cite the rule. Defer §4/§5 to `compliance-reviewer`.
