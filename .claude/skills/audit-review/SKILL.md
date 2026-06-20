---
description: Review existing code for robustness and audit/regulatory defensibility (evaluator-optimizer loop)
argument-hint: <path/glob of code to review, or a commit range>
allowed-tools: Read, Grep, Glob, Bash(git diff:*), Bash(git status:*), Bash(git log:*), Bash(git blame:*), Bash(git show:*)
---

Under the PM (CLAUDE.md §6), review for robustness and whether it would **stand up to audit
and regulatory scrutiny**: **$ARGUMENTS**

**First, confirm the outcome wanted:** the review + verdict only, or also **fixes/refactor
applied** as part of the loop, and/or a **handover pack** at the end? Default here is the
fix→re-review loop, but confirm before changing the user's code.

Run an **evaluator–optimizer loop**:

1. **code-reviewer** in **deep** mode (i.e. run `/deep-review` first) — comprehensive review
   across the languages present, driving the standard analysers (ruff/mypy/bandit,
   Checkstyle/PMD/SpotBugs, scalafmt/scapegoat, PSScriptAnalyzer, ShellCheck, Semgrep),
   citing OWASP ASVS / CWE / SEI CERT, with confidence scoring and filter transparency
   (`docs/code-review-method.md`). Audit mode: pre-existing issues stay in scope.
2. **compliance-reviewer** — auditability, the alert→logic→obligation trace, threshold
   rationale, secrets/PII, test coverage, and change control.
3. If any **Critical/Warning** findings, route fixes to `rules-developer` / `ml-engineer`,
   then **re-review** — loop until no Critical findings remain (or the user calls it).
4. Produce the report — **by default the consolidated Delivery Report**
   (`docs/templates/delivery-report.md`), or the standalone `review-report.md` if the user
   prefers a separate file. Give an explicit verdict (✅ audit-ready / ⚠️ conditional / ❌ not
   yet), findings by severity with standards cited, audit/regulatory checks, and a
   tooling-coverage section (state what couldn't run).

Save `artifacts/REVIEW-<slug>.md` and render to `.html` (`python -m scripts.render_html`).

**Close with next steps (don't dead-end).** State the verdict, then offer concrete follow-ups
with a recommendation — e.g. *"Verdict: conditional. I can fix the 2 remaining warnings,
add the missing tests, or produce the handover pack for your IT team. Which next?"*
