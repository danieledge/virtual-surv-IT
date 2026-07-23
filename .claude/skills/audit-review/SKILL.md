---
description: Review existing code for robustness and audit/regulatory defensibility (evaluator-optimizer loop)
argument-hint: <path/glob of code to review, or a commit range>
disable-model-invocation: true
---

Under the PM (CLAUDE.md §6), review for robustness and whether it would **stand up to audit
and regulatory scrutiny**: **$ARGUMENTS**

**If no target was given, first ask the user where the code is** (path/glob, repo/branch,
commit range, or paste it) and wait - don't review an assumed target.

**Fix-cycle (report / fix / loop):** if invoked **via `engage`**, inherit its answer (Q3) -
**don't re-ask**. If invoked **directly**, ask it once via the **question tool** (`multiSelect:
false`): report only · apply fixes · fix→re-review loop (the default here). **Confirm before
changing the user's code.** Don't blur in the handover pack - that's a **deliverable**, offered
from the artifact menu / at close, not mixed into this action question.

**Chained skills are dormant** - where a step routes to another workflow (`/deep-review`), read
`.claude/skills/<name>/SKILL.md` and follow it in this session; do not invoke it via the Skill
tool (full rule + plugin-mode path: `/engage`).

Run an **evaluator-optimizer loop**:

1. **code-reviewer** in **deep** mode (i.e. run `/deep-review` first, telling it to inherit
   **Mode = audit** and the **compliance** dimension and not to re-ask those) - comprehensive review
   across the languages present, driving the standard analysers (ruff/mypy/bandit,
   Checkstyle/PMD/SpotBugs, scalafmt/scapegoat, PSScriptAnalyzer, ShellCheck, Semgrep),
   citing OWASP ASVS / CWE / SEI CERT, with confidence scoring and filter transparency
   (`docs/code-review-method.md`). Audit mode: pre-existing issues stay in scope. The embedded
   `/deep-review` asks whether the code was **AI-assisted / vibe-coded**; if so, carry its
   **🧑‍💻 Prompting guidance** through into the audit report (see `docs/review/output-format.md`).
2. **compliance-reviewer** - use the **jurisdiction(s)** already established in step 1's
   `/deep-review` (or CLAUDE.md §2 / `docs/scope-and-stack.md`); **only ask if still unknown** -
   don't re-ask what step 1 captured. It assesses against the **applicable** regime(s) and states
   what's applicable vs not. Then: auditability, the alert→logic→obligation trace, threshold
   rationale, secrets/PII, test coverage, and change control.
3. If any **Critical/Warning** findings (and fixes are in scope), route fixes to the right
   builder, then **re-review** - and **fix everything you safely can in this pass, don't defer
   fixable work to a later sprint**. **Record every pass as it happens** in the Delivery
   Report's iteration log (§1a: journey strip + append-only hand-off row per review pass, fix
   routing and re-review - operating guide, Outcome discipline 5); earlier pass verdicts are
   never rewritten. Loop until everything fixable is fixed; the only items left
   are those needing a **human decision** (mark 🔴 Open / needs human review, not "deferred").
4. **Morgan's challenge pass (opus) - a spot-check, not a re-score** (the scorer already applied
   the rubric; re-scoring everything on opus pays twice for the same judgement). Challenge every
   🔴 Critical, anything §4/§5-regulated, any finding whose **evidence basis** looks thin (🧠
   presented as 📊 - never let an inference reach the user as fact), and a sample of the rest;
   downgrade or drop what fails. Be a sceptic, not a relay - and not a second scorer.
5. Present in the shared `docs/review/output-format.md`: a clean traffic-light **scoreboard to
   the console**, with the full findings in the **clean artifact**. Give an explicit verdict
   (✅ audit-ready / ⚠️ conditional / ❌ not yet), standards cited, audit/regulatory checks, the
   🔵 style & form lane, a tooling-coverage section, **and - MANDATORY - a `## 🔵 Developer
   guidance - improving future code` section** (2-4 points, even on a clean pass; verify it's in
   the artifact before presenting). Use the standalone clean review artifact by default; fold
   into the consolidated `delivery-report.md` only when audit is part of a larger handover.

6. **Independent read of the consolidated pack (Audit depth - the check on Morgan).** Before close,
   hand the finished audit artifact / `delivery-report` **itself** to **compliance-reviewer**
   (structurally independent of the PM - no Write/Edit) for a final read of the *synthesis*, not the
   code: does the **verdict follow from the findings register**? is any claim in the summary
   **unsupported by an artifact**? are dispositions, counts and evidence tags (📊/📄/🧠) internally
   consistent? This is the one pass Morgan cannot reliably do on its **own** output (ungrounded
   self-review is unreliable - `docs/research-virtual-team.md`); fix or escalate what it flags before
   ✅. Right-sized: it reads the pack, it does not re-run the review.

Save `artifacts/REVIEW-<slug>.md` and render to `.html` (`<python> -m scripts.render_html`).
(`<python>`: resolve your interpreter - try python3, then python, then py - and in an
installed-plugin session invoke the bundled `scripts/` copy by path; see the operating guide,
"Run mode & the bundled scripts".)

**Close with a clear disposition - never leave it ambiguous.** State the verdict **and the
disposition of every finding**: ✅ fixed (what changed) · 🔴 open · ⚖️ accepted (rationale) ·
⏭️ deferred. A ❌/conditional verdict must **list the Open items explicitly** - don't just say
"failed". For anything with no straightforward fix, mark it **🔴 Open (needs human developer
review)** with the reason and options rather than guessing. Then offer concrete follow-ups with
a recommendation - e.g. *"Verdict: conditional - 2 fixed, 1 open (needs your call on the
threshold). I can fix the 2 remaining warnings, escalate the open one, or produce the handover
pack. Which next?"* **Among the follow-ups, offer a dedicated deep security audit
(`/security-audit`)** - and recommend it when the code touches a security-sensitive surface or the
audit surfaced any security finding; it goes deeper on security (OWASP ASVS / CWE + a threat model)
than this audit's security lens.

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
