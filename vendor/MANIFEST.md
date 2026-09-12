# vendor/MANIFEST.md - one row per vendored package

Companion to `vendor/README.md` (rationale + update mechanics) and `THIRD-PARTY-LICENSES.md`
(full licence texts/notices). This file is the single inventory: version, upstream source,
licence, and why each package is vendored - kept in sync by hand, same as the other two.

| Package | Version | Upstream | Licence | Why vendored |
|---|---|---|---|---|
| openpyxl | 3.1.5 | <https://foss.heptapod.net/openpyxl/openpyxl> | MIT | `.xlsx`/`.xlsm` reading (and the writer the tests use) for `scripts/convert_file.py` |
| et_xmlfile | 2.0.0 | <https://foss.heptapod.net/openpyxl/et_xmlfile> | MIT | openpyxl's own XML-writing dependency |
| xlrd | 2.0.2 | <https://github.com/python-excel/xlrd> | BSD-3-Clause | legacy `.xls` reading (frozen upstream; stable, no further releases expected) |
| pypdf | 6.14.2 | <https://github.com/py-pdf/pypdf> | BSD-3-Clause | PDF text extraction for `convert_file.py`; also used by maintainer tooling to strip leaked local-path link annotations from tracked PDFs (`docs/internal/README.md`) |
| defusedxml | 0.7.1 | <https://github.com/tiran/defusedxml> | PSF-2.0 | hardened XML parsing - every converter input is untrusted |
| olefile | 0.47 | <https://github.com/decalage2/olefile> | BSD-2-Clause | reading OLE containers (legacy `.msg`/some `.xls` paths) |
| textual | 8.2.8 | <https://github.com/Textualize/textual> | MIT | `virt-surv go`'s full-screen launcher/installer TUI |
| rich | 15.0.0 | <https://github.com/Textualize/rich> | MIT | textual's rendering dependency; also used directly by the launcher's rich-only rendering tier |
| prompt_toolkit | 3.0.53 | <https://github.com/prompt-toolkit/python-prompt-toolkit> | BSD-3-Clause | the launcher's interactive prompt tier (arrow keys/mouse/in-place toggles); falls back to plain `input()` menus when absent |
| platformdirs | 4.11.5 | <https://github.com/tox-dev/platformdirs> | MIT | textual's dependency for per-OS config/cache paths |
| wcwidth | 0.8.2 | <https://github.com/jquast/wcwidth> | MIT | prompt_toolkit's dependency for terminal cell widths |
| typing_extensions | 4.16.0 | <https://github.com/python/typing_extensions> | PSF-2.0 | textual/pypdf's typing back-compat dependency |
| pygments | 2.20.0 | <https://github.com/pygments/pygments> | BSD-2-Clause | textual's `Markdown`/`MarkdownViewer` widgets import this unconditionally (vendored 2026-09-12; those widgets are not currently used by any shipped script) |
| markdown-it-py (module `markdown_it`) | 4.2.0 | <https://github.com/executablebooks/markdown-it-py> | MIT | the same textual Markdown widgets' parser (vendored 2026-09-12, same reason as pygments) |
| mdurl | 0.1.2 | <https://github.com/executablebooks/mdurl> | MIT | markdown-it-py's own required dependency |

## Refresh procedure

Vendor refreshes are **dedicated chore commits only** - never bundled into a feature commit.
Three historical commits mixed the two (each 39k-110k changed lines, carrying a vendor bump
inside a feature change), which made the vendor tree unreviewable and hard to attribute to a
pinned upstream version - a refresh must be its own diff, checkable against the version bump
alone. To refresh one package:

```
rm -rf vendor/<package> vendor/<package>-*.dist-info
pip install --target vendor --no-compile --no-deps <package>==<new-version>
rm -rf vendor/bin vendor/**/__pycache__
```

Then update the version in this file, `vendor/README.md`'s table, and
`THIRD-PARTY-LICENSES.md`; re-run the relevant test suite (`pytest tests/test_convert_file.py`
for the document-conversion packages); and record the bump as its own line in `CHANGELOG.md`,
separate from any feature change landing in the same release. Keep `--no-deps` and add any new
transitive dependency to all three files deliberately, with its own licence recorded - never let
a dependency arrive silently as part of another package's install.

Where `pip install` cannot reach the network (the common case this tree exists for), copy the
package directory and its `*.dist-info` straight from a dev environment's
`.venv/lib/python<version>/site-packages/` instead, as was done for `pygments`, `markdown_it` and
`mdurl` on 2026-09-12 - the result is byte-identical to what `pip install --no-compile --no-deps`
would have produced, provided the dev environment's version matches the one being pinned.
