# vendor/ - bundled third-party libraries

Pure-Python dependencies of `scripts/convert_file.py` and the launcher/installer TUI
(`scripts/launcher_textual.py`, `scripts/installer_app.py`, `scripts/launcher_tiers.py`), shipped
**verbatim inside the repo** so that a plain `git clone` is a complete, working install - no pip,
no network. Corporate environments frequently block PyPI; file conversion and the launcher are
mechanical steps the team must be able to rely on everywhere, so their dependencies travel with
the code.

| Package | Version | Licence | Why |
|---------|---------|---------|-----|
| openpyxl | 3.1.5 | MIT | `.xlsx`/`.xlsm` reader (and the writer the tests use) |
| et_xmlfile | 2.0.0 | MIT | openpyxl dependency |
| xlrd | 2.0.2 | BSD-3-Clause | legacy `.xls` reader (frozen upstream; stable) |
| pypdf | 6.14.2 | BSD-3-Clause | PDF text extraction |
| defusedxml | 0.7.1 | PSF-2.0 | hardened XML parsing - all converter input is untrusted |
| olefile | 0.47 | BSD-2-Clause | reading OLE containers (legacy `.msg`/`.xls` paths) |
| textual | 8.2.8 | MIT | `virt-surv go`'s full-screen launcher/installer TUI (2026-08-20) |
| rich | 15.0.0 | MIT | textual's rendering dependency, and used directly by the launcher's own rich-only rendering tier |
| prompt_toolkit | 3.0.53 | BSD-3-Clause | `virt-surv go`'s interactive prompt_toolkit tier (2026-08-17 user request: arrows/mouse/in-place toggles) - falls back to the numbered `input()` menus when absent or the terminal is not a tty |
| platformdirs | 4.11.5 | MIT | textual dependency - per-OS config/cache paths |
| wcwidth | 0.8.2 | MIT | prompt_toolkit dependency (terminal cell widths) |
| typing_extensions | 4.16.0 | PSF-2.0 | textual/pypdf dependency - typing back-compat |
| pygments | 2.20.0 | BSD-2-Clause | textual's `Markdown`/`MarkdownViewer` widgets import this unconditionally (`textual/highlight.py`) - vendored 2026-09-12 so those widgets do not `ImportError` in a plain-clone, no-pip environment; nothing in this repo's own scripts imports the widgets yet |
| markdown_it (markdown-it-py) | 4.2.0 | MIT | the same `Markdown`/`MarkdownViewer` widgets' Markdown parser (`textual/widgets/_markdown.py`); vendored alongside pygments for the same reason |
| mdurl | 0.1.2 | MIT | markdown-it-py's own required dependency |

Licence texts live in each package's `*.dist-info/` directory and are summarised in
`THIRD-PARTY-LICENSES.md`. One-row-per-package inventory with upstream URLs and the reason each is
vendored: `vendor/MANIFEST.md`.

**Textual's Markdown widgets are the one path not fully self-contained even now:** `MarkdownIt`'s
optional `linkify` behaviour lazily imports `linkify-it-py`, which is NOT vendored (markdown_it's
own code tolerates its absence, `self.linkify = None`, so this degrades a feature rather than
raising `ImportError`). Nothing under `scripts/` currently imports `textual.widgets.Markdown` or
`MarkdownViewer` (they are reached only via `widgets/__init__.py`'s lazy `__getattr__`), so this is
a documented gap, not a live defect.

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
