---
description: Review existing code for robustness and audit/regulatory defensibility (evaluator-optimizer loop)
argument-hint: <path/glob of code to review, or a commit range>
---

Under the PM (CLAUDE.md §6), review for robustness and whether it would **stand up to audit
and regulatory scrutiny**: **$ARGUMENTS**

Run an **evaluator–optimizer loop**:

1. **code-reviewer** — comprehensive review across the languages present, driving the
   standard analysers (ruff/mypy/bandit, Checkstyle/PMD/SpotBugs, scalafmt/scapegoat,
   PSScriptAnalyzer, ShellCheck, Semgrep) and citing OWASP ASVS / CWE / SEI CERT.
2. **compliance-reviewer** — auditability, the alert→logic→obligation trace, threshold
   rationale, secrets/PII, test coverage, and change control.
3. If any **Critical/Warning** findings, route fixes to `rules-developer` / `ml-engineer`,
   then **re-review** — loop until no Critical findings remain (or the user calls it).
4. Produce a **Review Report** (`docs/templates/review-report.md`) with an explicit verdict
   (✅ audit-ready / ⚠️ conditional / ❌ not yet), findings by severity with standards cited,
   audit/regulatory checks, and a tooling-coverage section (state what couldn't run).

Save `artifacts/REVIEW-<slug>.md` and render to `.html` (`python -m scripts.render_html`).
