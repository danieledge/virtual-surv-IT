---
description: Deep security audit of code - OWASP ASVS / CWE / SEI CERT, threat model, secrets & data-safety, with the audit-review evaluator-optimizer loop
argument-hint: <path/glob of code to audit, a commit range, or nothing for the working diff>
disable-model-invocation: true
---

Under the PM (CLAUDE.md §6), run a **deep security audit** of: **$ARGUMENTS** - a focused,
defensible review of the code's **security posture**, following the same conventions as
`/audit-review` but aimed entirely at security depth. General correctness, architecture and style
are `/deep-review`'s job, not this one.

> **What this is vs the others.** The general reviews (`/deep-review`, `/audit-review`) already run
> a **security lens** that catches the obvious issues inline. This skill is the **dedicated deep
> pass**: a threat-model view, the security lenses driven hard with the security analysers,
> dependency / supply-chain, and the §5 data-safety trail - for when security is the point, not one
> dimension of many. It **complements** the general review; it does not replace it.

**If no target was given** (no path/glob/commit range and no uncommitted `git diff`), first ask
where the code is (path/glob, repo/branch, commit range, or paste it) and wait - don't audit an
assumed target.

**Fix-cycle (report / fix / loop):** if invoked **via `engage`**, inherit its answer (Q3) -
**don't re-ask**. If invoked **directly**, ask once via the **question tool** (`multiSelect:
false`): report only · apply fixes · fix→re-review loop (the default here). **Confirm before
changing the user's code.**

**Chained skills are dormant** - where a step routes to another team workflow (`/deep-review`,
`/remediate`), read `.claude/skills/<name>/SKILL.md` and follow it in this session; do not invoke
it via the Skill tool (full rule + plugin-mode path: `/engage`).

**Scope routing - pick the right engine for the target** (the `/security-review` pipeline is
diff-only; see `docs/adr/ADR-002-safety-hook-threat-model.md` context on tooling boundaries and the
review-method notes):

- **The target is a real change set** (a branch/PR, a commit range, or uncommitted edits that form a
  `git diff`) → additionally run **Anthropic's `/security-review`** pipeline (invoke the
  `security-review` skill, or ask the user to run `/security-review`) as the specialised engine, and
  **merge + dedupe** its findings into this audit. That pipeline is diff-native and carries a
  security-tuned methodology.
- **The target is arbitrary local code with no diff** (a file/dir you were pointed at, committed
  code with a clean tree, or a non-git folder) → the **team's own deep security pass below is the
  engine.** Do **not** point `/security-review` at a clean tree: with no diff it falls back to a
  **general-purpose agent**, not the security pipeline (no scope control, none of the
  specialisation), so it adds nothing here.
- State in one line which engine(s) you're running and why, so the scope is never a surprise.

Run an **evaluator-optimizer loop** (same shape as `/audit-review`, security-focused):

1. **Threat-model framing (do this first, briefly).** Map the **attack surface**, the **trust
   boundaries**, and the **sensitive data flows** - where PII/MNPI (personal data / material
   non-public information) and secrets enter, move and leave. A few lines, right-sized: it tells the
   review where to look hardest. Name the assets a surveillance system must protect: **alert
   integrity, the audit trail, and the data itself** (§5).

2. **Deep security review** (`code-reviewer` in **audit** mode - pre-existing issues stay in scope).
   Load the **security + per-language + architecture** lenses via `docs/review/agent-router.md`, and
   drive the **security analysers** where available: `bandit`, `semgrep`, `gitleaks` / secret-scan,
   `find-sec-bugs` (JVM), `ShellCheck`, `PSScriptAnalyzer` security rules, plus a **dependency /
   supply-chain** scan (`pip-audit`, `npm audit`, `osv-scanner`) for known-vulnerable dependencies.
   Cite **OWASP ASVS / CWE / SEI CERT** per finding, with confidence scoring, evidence basis
   (📊 measured / 🧠 inferred - never let an inference read as fact), and filter transparency
   (`docs/code-review-method.md`). Cover, at depth: injection (CWE-78/89/22), deserialisation /
   parsing (CWE-502, XXE), **secrets & data exposure** (CWE-798, plus real PII/MNPI or raw records
   in code/logs/fixtures - §5, **never filtered**), auth & access (authn bypass, broken authz,
   IDOR), SSRF, weak crypto / weak randomness, and vulnerable dependencies.

3. **compliance-reviewer** - the **§5 data-safety trail** (no secrets, no PII/MNPI/raw data in
   code, logs or fixtures) and, where detection logic is touched, the §4 alert→logic→obligation
   trace. Use the jurisdiction(s) established in step 2 (or CLAUDE.md §2 / `docs/scope-and-stack.md`);
   only ask if still unknown. Regulated findings are **never filtered**.

4. If any **Critical/Warning** findings (and fixes are in scope), route fixes to the right builder
   (or `/remediate`), then **re-review** - **fix everything you safely can this pass; don't defer
   fixable work.** Loop until only human-decision items remain, marked **🔴 Open (needs human
   review)**, not "deferred".

5. **Morgan's challenge pass (opus) - a spot-check, not a re-score** (the scorer already applied the
   rubric; re-scoring everything on opus pays twice). Challenge every 🔴 Critical, every §5/§4
   regulated finding, anything whose evidence basis looks thin (🧠 presented as 📊), and a sample of
   the rest; downgrade or drop what fails. Be a sceptic, not a relay - and not a second scorer.

6. **Present** in the shared `docs/review/output-format.md`: a clean traffic-light **scoreboard to
   the console**, full findings in the **clean artifact**. Give an explicit **security verdict**
   (✅ no unresolved security findings / ⚠️ conditional / ❌ not secure as-is), the **threat-model
   summary**, standards cited (OWASP ASVS / CWE), a **tooling-coverage** section (which scanners
   ran, which were unavailable - say so rather than upgrading a guess to a certainty), the 🔵
   style/form lane, **and - MANDATORY - a `## 🔵 Developer guidance - improving future code`
   section** (2-4 security-hardening points, even on a clean pass; verify it is in the artifact
   before presenting).

**The report is rendered from a findings pack, not hand-authored** (`docs/review/output-format.md`,
schema `docs/review/findings-schema.json`). Write the findings to
`artifacts/data/findings-<slug>.json` with **`"kind": "security-audit"`** (each finding the five
named fields - `standard` = the CWE/OWASP ASVS ref - + severity/basis/disposition), then run
**`<python> -m scripts.check_artifacts --fix`** (allow-listed): it validates the pack
(`FINDINGS-INVALID` → fix and re-run) and renders `artifacts/SECURITY-AUDIT-<slug>.md` + `.html`
(the `kind` drives the `SECURITY-AUDIT-` prefix). Don't hand-author or hand-edit the report.
(`<python>`: resolve your interpreter - try python3, then python, then py - and in an installed-plugin
session invoke the bundled `scripts/` copy by path; see the operating guide, "Run mode & the
bundled scripts").

**Close with a clear disposition - never leave it ambiguous.** State the verdict **and the
disposition of every finding**: ✅ fixed (what changed) · 🔴 open · ⚖️ accepted (rationale) ·
⏭️ deferred. A ❌/conditional verdict must **list the Open items explicitly** - don't just say
"failed". For anything with no straightforward fix, mark it **🔴 Open (needs human developer
review)** with the reason and options rather than guessing. Then offer concrete follow-ups with a
recommendation - e.g. *"Security verdict: conditional - 3 fixed, 1 open (a crypto choice that needs
your call). I can fix the remaining items, escalate the open one, or fold this into the delivery
report. Which next?"*

**Standard open (Definition of Done - the opening bookend; do this before delivering the audit
above, and it applies even when this skill is invoked directly):** unless you arrived via
`/engage` (which already wrote it), write a **proportionate Engagement Brief**
(`docs/templates/engagement-brief.md`) as `.md` + `.html` in `artifacts/` - the target, the scope
and decisions taken, assumptions, and the plan; **right-size it** (a few lines for a small audit,
not a full programme). The brief is the opening artifact of **every** engagement and the bookend to
the summary email below. With the brief, **open the START-HERE living index** (`docs/templates/start-here.md`, status ⏳), appending a row to it as each artifact lands - lifecycle discipline (operating guide): a pause on unanswered user input is ⛔ BLOCKED said out loud ("this engagement is NOT closed - outstanding: ..."), interim output takes pass-scoped names (`review-pass-N`, `interim-*`), and `delivery-report.md` + the summary email are written at ✅ close only.

**Standard close (Definition of Done - applies even when this skill is invoked directly):**
write the **engagement-summary email** (`docs/templates/engagement-summary-email.md`) as a
`.txt` in `artifacts/`, **signed off as Morgan**, then run the mechanical gate -
`<python> -m scripts.check_artifacts --fix` (the `--fix` mode auto-renders missing `.html` siblings and renames a mis-typed summary email to `.txt`), then act on anything it still flags (missing `.html` siblings or
a missing email) before handing back. Detail: `docs/team-operating-guide.md`.
