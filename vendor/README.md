# vendor/ - bundled third-party libraries

Pure-Python dependencies of `scripts/convert_file.py`, shipped **verbatim inside the repo**
so that a plain `git clone` is a complete, working install - no pip, no network. Corporate
environments frequently block PyPI; file conversion is a mechanical step the team must be
able to rely on everywhere, so its dependencies travel with the code.

| Package | Version | Licence | Why |
|---------|---------|---------|-----|
| openpyxl | 3.1.5 | MIT | `.xlsx`/`.xlsm` reader (and the writer the tests use) |
| et_xmlfile | 2.0.0 | MIT | openpyxl dependency |
| xlrd | 2.0.2 | BSD-3-Clause | legacy `.xls` reader (frozen upstream; stable) |
| pypdf | 6.14.2 | BSD-3-Clause | PDF text extraction |
| defusedxml | 0.7.1 | PSF-2.0 | hardened XML parsing - all converter input is untrusted |

Licence texts live in each package's `*.dist-info/` directory and are summarised in
`THIRD-PARTY-LICENSES.md`.

## Rules

- **Never edit vendored code.** Diffs against upstream must stay empty so provenance and
  licence review stay trivial. Fixes go upstream or in `scripts/convert_file.py`.
- **Vendored-first:** `convert_file.py` puts this directory at the front of `sys.path`, so
  these pinned versions win over anything installed in site-packages. Deterministic
  behaviour beats freshness for a conversion tool.
- **Pure Python only.** Compiled wheels (lxml, python-calamine, numpy...) cannot be vendored
  this way - that constraint drove the library choices. Do not add one.
- Excluded from ruff/format (`pyproject.toml` `extend-exclude`) and not covered by the CI
  lint jobs; it is third-party code, linted upstream.

## Updating a package

```
rm -rf vendor/<package> vendor/<package>-*.dist-info
pip install --target vendor --no-compile --no-deps <package>==<new-version>
rm -rf vendor/bin vendor/**/__pycache__
```

Then: update the version in this table and in `THIRD-PARTY-LICENSES.md`, re-run the test
suite (`pytest tests/test_convert_file.py`), and mention the bump in `CHANGELOG.md`. Keep
`--no-deps` and add any new transitive dependency deliberately, with its licence recorded.
