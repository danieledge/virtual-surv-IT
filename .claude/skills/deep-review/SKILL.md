---
description: Detailed multi-dimension code review (bugs, security, architecture, impact) with confidence scoring
argument-hint: <path/glob, commit range, or nothing for the working diff>
disable-model-invocation: true
---

Run a **deep (detailed) code review** of: **$ARGUMENTS**.

**1. Confirm the target.** If none was given (no path/glob/commit range and no uncommitted
`git diff`), ask where the code is - a path/glob, repo/branch, commit range, or to paste it -
and wait. Don't review an assumed target.

**2. Put scope on a menu - ask, don't assume.** Ask the axes below **in ONE `AskUserQuestion`
call** (one screen, not separate round-trips); they stay distinct questions with the stated
`multiSelect` and header. **Hard tool limits: max 4 questions per call, max 4 options per
question** ("Other" is added automatically) - the constructions below are sized to fit; don't
un-bundle them back into a 7-option list:
- **Dimensions** (header `Dimensions`, **`multiSelect: false`** - four locked bundles; a bespoke
  mix goes through "Other", e.g. *"bugs + docs only"*):
  - **Full review (recommended)** - all seven lenses: bugs & logic · security · architecture ·
    language-specific · docs/comments · style & form · compliance/audit.
  - **Core** - 🐛 bugs & logic + 🔐 security + 🧰 language-specific. *For a plain utility script.*
  - **Core + quality** - Core plus 📐 architecture + 📝 docs/comments + 🔵 style & form.
  - **Core + compliance** - Core plus 📋 compliance/audit (§4/§5 trail).
  Run only what was picked - don't force a lens the user didn't choose.
- **Breadth** (header `Breadth`, **`multiSelect: false`**, exactly one): the working diff ·
  named files/glob · whole module · whole repo.
- **Mode** (header `Mode`, **`multiSelect: false`**): change review (filter pre-existing) **or**
  audit (keep pre-existing in scope).
- **Origin** (header `Origin`, **`multiSelect: false`**): was this **AI-assisted /
  "vibe-coded"**? (yes · mixed · no, hand-written). If **yes/mixed**, the report adds a
  **🧑‍💻 Prompting guidance** section (see `docs/review/output-format.md`): how a better prompt
  would have prevented the top findings, plus example prompts to reuse. (The reviewer also adds
  it if the findings clearly show vibe-coding.)

> **Do NOT re-ask the fix-cycle (report / fix / loop) here** - `engage` already captured it
> (its Q3) and it is the single source of truth; inherit that answer. If this skill was invoked
> **directly** (not via `engage`), ask it once (header `Fix-cycle`) - but the call is already at
> the 4-question cap, so in direct mode **swap Origin out of the first call** and ask it in the
> follow-up screen (with jurisdiction, if 📋 compliance is in scope; otherwise on its own or
> defaulted to "unknown - infer from the findings").

**If 📋 compliance/audit is among the dimensions**, ask **jurisdiction(s)** as a follow-up -
**`multiSelect: true`** (may operate in several) - or use the configured scope (CLAUDE.md §2 /
`docs/scope-and-stack.md`), so `compliance-reviewer` assesses only the **applicable** regime(s)
and states what's applicable vs not.

**3. Run the tiered review** (CLAUDE.md §6; method `docs/code-review-method.md`; lenses
`docs/review/lenses/`; router `docs/review/agent-router.md`):

1. **Context** *(delegate to `review-scorer`, haiku)* - detect languages, list changed
   files/lines, check for CLAUDE.md, and select the minimal lens set per the router. This is
   rote work - run it on the cheap tier, not opus.
2. **Load lenses** progressively via the router - only those `review-scorer` selected.
3. **Analyse** - drive `code-reviewer` to run the loaded lenses as **sequential focused passes**
   (one lens at a time, so each dimension gets full attention - a single agent cannot be "blind"
   to its own earlier passes; true independence would need separate agents, which this pipeline
   deliberately doesn't spend), plus the standard analysers (ruff/mypy/bandit,
   Checkstyle/PMD/SpotBugs, scalafmt/scapegoat, PSScriptAnalyzer, ShellCheck, Semgrep). Deep adds
   the **architecture** lens, **impact analysis**, and test/doc coverage.
4. **Score & filter** *(delegate to `review-scorer`, haiku)* - apply the scoring rubric and
   produce the Found/Reported/Filtered counts (`docs/code-review-method.md`). Tag each finding's
   **evidence basis** (📊 measured / 🧠 inferred). **Never** filter regulated findings (secrets,
   PII/raw data §5, undocumented thresholds / broken traceability §4) - those stay with
   `code-reviewer`/`compliance-reviewer`, not the scorer.
5. For anything touching detection logic, hand to **compliance-reviewer** for the §4/§5 trail.
6. **Morgan's challenge pass** *(opus)* - a **spot-check, not a re-score**: the scorer already
   applied the rubric (step 4), and re-scoring everything on opus pays twice for the same
   judgement. Challenge the findings that *matter*: every 🔴 Critical, anything §4/§5-regulated,
   any finding whose evidence basis looks thin (🧠 presented as 📊), and a sample of the rest.
   Downgrade or drop what fails the challenge. You are a sceptic, not a relay - and not a second
   scorer.
   - **A documented, intentional bound is not a defect.** Before flagging a cap, bound, limit or
     threshold as a bug (e.g. "silently drops rows beyond N", "truncates to M"), check whether the
     code documents its rationale or the value is a by-design contract (a column cap set to the
     expected schema width, a threshold carrying a rationale + tuning date per §4). If it's
     intentional, don't raise it - drop the finding unless the rationale itself is wrong or the
     bound is genuinely silent/undocumented. Distinguish a *silent-truncation bug* (no rationale, no
     reconciliation, unbounded loss) from an *intended limit* (documented, expected).

**4. Present - scoreboard + clean artifact** (`docs/review/output-format.md`; document skeleton:
`docs/templates/review-report.md`): a glanceable
traffic-light **scoreboard to the console**, with the **full findings written to the clean
artifact** `artifacts/REVIEW-<slug>.md`, rendered to `.html` (`<python> -m scripts.render_html`;
`<python>`: resolve your interpreter - try python3, then python, then py - and in an
installed-plugin session invoke the bundled `scripts/` copy by path; see the operating guide,
"Run mode & the bundled scripts").
🔵 style & form is a non-blocking "consider in future" lane. (Fold into the consolidated
`delivery-report.md` only if this review is part of a larger build/handover.)

   ⚠️ **MANDATORY - the artifact is NOT complete without a `## 🔵 Developer guidance - improving
   future code` section.** Always write it (2-4 constructive points on the author's coding
   style and what to improve next time; if the code is strong, say what's done well), **even on
   a clean pass**. Before you present, check the artifact contains this heading - if it's
   missing, you are not done; add it. This is a required deliverable, not an optional extra.

**5. Close - don't dead-end.** Summarise from the scoreboard, then offer concrete next steps
with a recommendation - *"3 🔴, 5 🟠. I can fix the criticals, run `/remediate`, or produce a
handover pack. Which?"* - and offer to carry them out. **Always include a deep security audit
(`/security-audit`) among the options**, and **recommend** it when the review touched a
security-sensitive surface (auth, input parsing, DB access, external I/O, crypto, secrets, or
PII/data handling) or surfaced any security finding - it runs a dedicated OWASP ASVS / CWE +
threat-model pass beyond this review's inline security lens.

**Standard open (Definition of Done - the opening bookend; do this before delivering the review
above, and it applies even when this skill is invoked directly):** unless you arrived via
`/engage` (which already wrote it), write a **proportionate Engagement Brief**
(`docs/templates/engagement-brief.md`) as `.md` + `.html` in `artifacts/` - the target, the scope
and decisions taken, assumptions, and the plan; **right-size it** (a few lines for a small review,
not a full programme). The brief is the opening artifact of **every** engagement and the bookend to
the summary email below. With the brief, **open the START-HERE living index** (`docs/templates/start-here.md`, status ⏳), appending a row to it as each artifact lands - lifecycle discipline (operating guide): a pause on unanswered user input is ⛔ BLOCKED said out loud ("this engagement is NOT closed - outstanding: ..."), interim output takes pass-scoped names (`review-pass-N`, `interim-*`), and `delivery-report.md` + the summary email are written at ✅ close only.

**Standard close (Definition of Done - applies even when this skill is invoked directly):**
write the **engagement-summary email** (`docs/templates/engagement-summary-email.md`) as a
`.txt` in `artifacts/`, **signed off as Morgan**, then run the mechanical gate -
`<python> -m scripts.check_artifacts` - and fix anything it flags (missing `.html` siblings or
a missing email) before handing back. Detail: `docs/team-operating-guide.md`.

> For audit/regulatory sign-off with a fix→re-review loop, use `/audit-review` (which runs this
> deep review as its first step).
