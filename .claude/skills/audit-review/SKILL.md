---
description: Review existing code for robustness and audit/regulatory defensibility (evaluator-optimizer loop)
argument-hint: <path/glob of code to review, or a commit range>
allowed-tools: Read, Grep, Glob, Bash(git diff:*), Bash(git status:*), Bash(git log:*), Bash(git blame:*), Bash(git show:*)
---

Under the PM (CLAUDE.md §6), review for robustness and whether it would **stand up to audit
and regulatory scrutiny**: **$ARGUMENTS**

**If no target was given, first ask the user where the code is** (path/glob, repo/branch,
commit range, or paste it) and wait - don't review an assumed target.

**First, confirm the outcome wanted:** the review + verdict only, or also **fixes/refactor
applied** as part of the loop, and/or a **handover pack** at the end? Default here is the
fix→re-review loop, but confirm before changing the user's code.

Run an **evaluator–optimizer loop**:

1. **code-reviewer** in **deep** mode (i.e. run `/deep-review` first) - comprehensive review
   across the languages present, driving the standard analysers (ruff/mypy/bandit,
   Checkstyle/PMD/SpotBugs, scalafmt/scapegoat, PSScriptAnalyzer, ShellCheck, Semgrep),
   citing OWASP ASVS / CWE / SEI CERT, with confidence scoring and filter transparency
   (`docs/code-review-method.md`). Audit mode: pre-existing issues stay in scope.
2. **compliance-reviewer** - first establish the **jurisdiction(s)** (from CLAUDE.md §2 /
   `docs/scope-and-stack.md`, or ask) so it assesses against the **applicable** regime(s) and
   states what's applicable vs not. Then: auditability, the alert→logic→obligation trace,
   threshold rationale, secrets/PII, test coverage, and change control.
3. If any **Critical/Warning** findings (and fixes are in scope), route fixes to the right
   builder, then **re-review** - and **fix everything you safely can in this pass, don't defer
   fixable work to a later sprint**. Loop until everything fixable is fixed; the only items left
   are those needing a **human decision** (mark 🔴 Open / needs human review, not "deferred").
4. **Morgan's challenge pass (opus).** Independently re-score the reviewers' findings, downgrade
   or drop the weak ones, and confirm each **evidence basis** (📊 measured / 🧠 inferred - never
   present an inference as fact) before presenting. Be a sceptic, not a relay.
5. Present in the shared `docs/review/output-format.md`: a clean traffic-light **scoreboard to
   the console**, with the full findings in the **clean artifact**. Give an explicit verdict
   (✅ audit-ready / ⚠️ conditional / ❌ not yet), standards cited, audit/regulatory checks, the
   🔵 style & form lane, a tooling-coverage section, **and - MANDATORY - a `## 🔵 Developer
   guidance - improving future code` section** (2–4 points, even on a clean pass; verify it's in
   the artifact before presenting). Use the standalone clean review artifact by default; fold
   into the consolidated `delivery-report.md` only when audit is part of a larger handover.

Save `artifacts/REVIEW-<slug>.md` and render to `.html` (`python -m scripts.render_html`).

**Close with a clear disposition - never leave it ambiguous.** State the verdict **and the
disposition of every finding**: ✅ fixed (what changed) · 🔴 open · ⚖️ accepted (rationale) ·
⏭️ deferred. A ❌/conditional verdict must **list the Open items explicitly** - don't just say
"failed". For anything with no straightforward fix, mark it **🔴 Open (needs human developer
review)** with the reason and options rather than guessing. Then offer concrete follow-ups with
a recommendation - e.g. *"Verdict: conditional - 2 fixed, 1 open (needs your call on the
threshold). I can fix the 2 remaining warnings, escalate the open one, or produce the handover
pack. Which next?"*
