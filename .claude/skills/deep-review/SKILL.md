---
description: Detailed multi-dimension code review (bugs, security, architecture, impact) with confidence scoring
argument-hint: <path/glob, commit range, or nothing for the working diff>
allowed-tools: Read, Grep, Glob, Bash(git diff:*), Bash(git status:*), Bash(git log:*), Bash(git blame:*), Bash(git show:*)
---

Run a **deep (detailed) code review** of: **$ARGUMENTS**.

**1. Confirm the target.** If none was given (no path/glob/commit range and no uncommitted
`git diff`), ask where the code is — a path/glob, repo/branch, commit range, or to paste it —
and wait. Don't review an assumed target.

**2. Put scope on a menu — ask, don't assume.** Offer the user the review scope and wait:
- **Dimensions** (multi-select; default = all): 🐛 bugs & logic · 🔐 security · 📐 architecture ·
  🧰 language-specific · 📝 docs/comments · 🔵 style & form · 📋 compliance/audit. **All are
  opt-in** — the user can run only the ones they want (e.g. a plain utility script may want bugs
  + security only, no compliance). Don't force a dimension they didn't pick.
- **If 📋 compliance/audit is selected, ask the jurisdiction(s)/region** the code will operate in
  (or use the configured scope in CLAUDE.md §2 / `docs/scope-and-stack.md`) so
  `compliance-reviewer` derives the **applicable** obligations and states what's applicable vs
  not — don't apply rules from a region that doesn't apply.
- **Breadth**: just the working diff · named files/glob · whole module · whole repo.
- **Mode**: **change review** (filter pre-existing) or **audit** (keep pre-existing in scope).
- **Outcome** (don't assume "review & stop"): review only · also **fixes applied** · a
  **`/remediate` loop** · and/or a **handover pack**.

**3. Run the tiered review** (CLAUDE.md §6; method `docs/code-review-method.md`; lenses
`docs/review/lenses/`; router `docs/review/agent-router.md`):

1. **Context** *(delegate to `review-scorer`, haiku)* — detect languages, list changed
   files/lines, check for CLAUDE.md, and select the minimal lens set per the router. This is
   rote work — run it on the cheap tier, not opus.
2. **Load lenses** progressively via the router — only those `review-scorer` selected.
3. **Analyse** — drive `code-reviewer` to run the loaded lenses as **parallel passes** (each
   blind to the others), plus the standard analysers (ruff/mypy/bandit, Checkstyle/PMD/SpotBugs,
   scalafmt/scapegoat, PSScriptAnalyzer, ShellCheck, Semgrep). Deep adds the **architecture**
   lens, **impact analysis**, and test/doc coverage.
4. **Score & filter** *(delegate to `review-scorer`, haiku)* — apply the scoring rubric and
   produce the Found/Reported/Filtered counts (`docs/code-review-method.md`). Tag each finding's
   **evidence basis** (📊 measured / 🧠 inferred). **Never** filter regulated findings (secrets,
   PII/raw data §5, undocumented thresholds / broken traceability §4) — those stay with
   `code-reviewer`/`compliance-reviewer`, not the scorer.
5. For anything touching detection logic, hand to **compliance-reviewer** for the §4/§5 trail.
6. **Morgan's challenge pass** *(opus)* — independently re-score the lenses' findings, downgrade
   or drop the weak ones, and confirm each evidence basis before anything reaches the user. You
   are a sceptic, not a relay.

**4. Present — scoreboard + clean artifact** (`docs/review/output-format.md`): a glanceable
traffic-light **scoreboard to the console**, with the **full findings written to the clean
artifact** `artifacts/REVIEW-<slug>.md`, rendered to `.html` (`python -m scripts.render_html`).
🔵 style & form is a non-blocking "consider in future" lane. (Fold into the consolidated
`delivery-report.md` only if this review is part of a larger build/handover.)

   ⚠️ **MANDATORY — the artifact is NOT complete without a `## 🔵 Developer guidance — improving
   future code` section.** Always write it (2–4 constructive points on the author's coding
   style and what to improve next time; if the code is strong, say what's done well), **even on
   a clean pass**. Before you present, check the artifact contains this heading — if it's
   missing, you are not done; add it. This is a required deliverable, not an optional extra.

**5. Close — don't dead-end.** Summarise from the scoreboard, then offer concrete next steps
with a recommendation — *"3 🔴, 5 🟠. I can fix the criticals, run `/remediate`, or produce a
handover pack. Which?"* — and offer to carry them out.

> For audit/regulatory sign-off with a fix→re-review loop, use `/audit-review` (which runs this
> deep review as its first step).
