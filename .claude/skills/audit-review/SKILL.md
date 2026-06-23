---
description: Review existing code for robustness and audit/regulatory defensibility (evaluator-optimizer loop)
argument-hint: <path/glob of code to review, or a commit range>
allowed-tools: Read, Grep, Glob, Bash(git diff:*), Bash(git status:*), Bash(git log:*), Bash(git blame:*), Bash(git show:*)
---

Under the PM (CLAUDE.md §6), review for robustness and whether it would **stand up to audit
and regulatory scrutiny**: **$ARGUMENTS**

**If no target was given, first ask the user where the code is** (path/glob, repo/branch,
commit range, or paste it) and wait — don't review an assumed target.

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
4. **Morgan's challenge pass (opus).** Independently re-score the reviewers' findings, downgrade
   or drop the weak ones, and confirm each **evidence basis** (📊 measured / 🧠 inferred — never
   present an inference as fact) before presenting. Be a sceptic, not a relay.
5. Present in the shared `docs/review/output-format.md`: a clean traffic-light **scoreboard to
   the console**, with the full findings in the **clean artifact**. Give an explicit verdict
   (✅ audit-ready / ⚠️ conditional / ❌ not yet), standards cited, audit/regulatory checks, the
   🔵 style & form lane, and a tooling-coverage section (state what couldn't run). Use the
   standalone clean review artifact by default; fold into the consolidated
   `delivery-report.md` only when audit is part of a larger handover.

Save `artifacts/REVIEW-<slug>.md` and render to `.html` (`python -m scripts.render_html`).

**Close with next steps (don't dead-end).** State the verdict, then offer concrete follow-ups
with a recommendation — e.g. *"Verdict: conditional. I can fix the 2 remaining warnings,
add the missing tests, or produce the handover pack for your IT team. Which next?"*
