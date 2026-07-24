# Third-Party Licences

**This project is licensed under GNU AGPL-3.0-only** (see [`LICENSE`](LICENSE)). It bundles and
adapts third-party open-source work under **permissive** licences (MIT / BSD-3-Clause / PSF), which
may be included in an AGPL-licensed work without conflict. Each component's licence and copyright
notice is reproduced below, as required by its terms, and is unaffected by the project's AGPL
licence.

---

## Vendored Python libraries (`vendor/`)

The file-conversion front door (`scripts/convert_file.py`) depends on pure-Python libraries
vendored verbatim under `vendor/`, so a plain `git clone` works in environments without pip
access (corporate networks). Each package's own licence text ships inside its
`vendor/<name>-<version>.dist-info/` directory; the summary:

| Package | Version | Licence | Source | Used for |
|---------|---------|---------|--------|----------|
| openpyxl | 3.1.5 | MIT | <https://foss.heptapod.net/openpyxl/openpyxl> | reading `.xlsx`/`.xlsm` |
| et_xmlfile | 2.0.0 | MIT | <https://foss.heptapod.net/openpyxl/et_xmlfile> | openpyxl dependency |
| xlrd | 2.0.2 | BSD-3-Clause | <https://github.com/python-excel/xlrd> | reading legacy `.xls` |
| pypdf | 6.14.2 | BSD-3-Clause | <https://github.com/py-pdf/pypdf> | PDF text extraction |
| defusedxml | 0.7.1 | PSF-2.0 | <https://github.com/tiran/defusedxml> | safe XML parsing (entity-expansion defence) |

The vendored code is unmodified. Update procedure and pinned-version rationale:
`vendor/README.md`.

---

## turingmind-code-review

- **Project:** turingmind-code-review
- **Source:** <https://github.com/turingmindai/turingmind-code-review>
- **Licence:** MIT
- **Copyright:** © 2026 TuringMind

**What we use.** The review subsystem's design leans heavily on turingmind-code-review: the
modular per-dimension review lenses (bugs, security, architecture, language-specific), the
progressive-loading router, the confidence-scoring + false-positive-filtering method, the
traffic-light output format with filter transparency and diff-style fixes, and the optional
severity-blocking git-hook gate. We have adapted these for a regulated surveillance-engineering
domain (audit mode, §4 traceability / §5 data-safety weighting, evidence-basis labelling, a
non-blocking style-&-form lane, additional language lenses for Scala/Java/PowerShell/Bash, and
artifact-first output). Adapted files carry an attribution header pointing here.

Files derived from this project include `docs/review/output-format.md`,
`docs/review/false-positive-rules.md`, `docs/review/lenses/*`, `docs/review/agent-router.md`,
parts of `docs/code-review-method.md`, and the optional review git-hook.

### MIT License

```
MIT License

Copyright (c) 2026 TuringMind

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
