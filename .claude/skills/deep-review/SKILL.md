---
description: Detailed multi-dimension code review (bugs, security, architecture, impact) with confidence scoring
argument-hint: <path/glob, commit range, or nothing for the working diff>
allowed-tools: Read, Grep, Glob, Bash(git diff:*), Bash(git status:*), Bash(git log:*), Bash(git blame:*), Bash(git show:*)
---

Run a **deep (detailed) code review** of: **$ARGUMENTS**.

**If no target was given** (no path/glob/commit range in `$ARGUMENTS` and no uncommitted
`git diff`), **ask the user where the code is** — a path/glob, repo/branch, commit range, or
to paste it — and wait. Don't review an assumed target.

**Then ask what outcome the user wants** (don't assume "review and stop"): just the review,
or also **fixes/refactor applied**, a **remediation plan/loop** (`/remediate`), and/or a
**handover pack**? Proceed on their answer.

Drive **code-reviewer** in **deep** mode (CLAUDE.md §6; method in
`docs/code-review-method.md`):

1. Detect languages from the target; load the relevant review dimensions — **bugs & logic**
   and **security** always, **language** checks by file type, and the **architecture**
   dimension (deep only). Run the standard analysers per language (ruff/mypy/bandit,
   Checkstyle/PMD/SpotBugs, scalafmt/scapegoat, PSScriptAnalyzer, ShellCheck, Semgrep).
2. **Score** every candidate finding 0–100 and **filter** noise per the method — but never
   filter regulated findings (secrets, PII/raw data §5, undocumented thresholds / broken
   traceability §4).
3. For anything touching detection logic, hand to **compliance-reviewer** for the
   audit/traceability dimension.
4. Produce the report. **By default write into the consolidated Delivery Report**
   (`docs/templates/delivery-report.md`, the *Code review* + *Performance* + *Compliance*
   sections); use the standalone `docs/templates/review-report.md` only if the user wants a
   separate file. Include the **transparency counts** (Found / Reported / Filtered + reasons),
   per-finding confidence, **Architectural Notes** and **Impact Analysis**.

Save `artifacts/REVIEW-<slug>.md` and render to `.html` (`python -m scripts.render_html`).

**Close with next steps (don't dead-end).** Summarise what you found, then present concrete
options with your recommendation and offer to do them — e.g. *"3 criticals, 5 warnings. I can:
(a) fix the criticals now, (b) refactor the worst module, (c) run `/remediate` for a full
assess→fix→re-review loop, or (d) produce a handover pack. Which would you like?"*

> For audit/regulatory sign-off with a fix→re-review loop, use `/audit-review` (which runs
> this deep review as its first step).
