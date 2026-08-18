# Delivery standards - outcome discipline, items 4-7 in full

> Deferred from `docs/team-operating-guide.md` (open-core split, token plan Phase 1,
> 2026-08-18). The open-core keeps outcome items 1-3 (agree the outcome, never end at
> analysis, the close-only summary email) and one-line forms of the items below; **read this
> file before producing the first deliverable artifact** of an engagement (review report,
> spec, code, QA evidence), and again before any critique/DoD gate.

4. **Audit-compatible structure by default; governance depth by choice.** Every codebase-review
   response ships in the audit skeleton at **every** depth (quick included): scope at a stated
   commit, reviewer independence, methodology + tooling coverage, findings register with
   dispositions, filtered transparency, and **limitations & residual risk** - it is what lets a
   third party reconstruct what was done, and retrofitting it later is expensive and lossy. The
   governance **extras** (control mappings, model-validation opinions, ops runbook / change
   request, split artifact packs) stay opt-in via the artifact menu - right-sizing still applies.
   Frame outputs as *consumable by a model-governance or audit reviewer*, never as "SR 11-7 /
   SS1/23 compliant" (formal MRM scope for surveillance code review is contested; make no
   compliance claims). Spec: `docs/templates/review-report.md` + `docs/review/output-format.md`.
4a. **Code ships only with tests and an independent QA pass - no workflow exempts it.** The
   build chain (`code-reviewer` → independent `qa-engineer` with test scripts → DoD) attaches
   to **deliverable code**, not to the workflow that happened to produce it: an analysis or
   tuning engagement whose later phase implements something runs that phase under
   `/build-solution`'s chain. (Live failure, 2026-07-21: a phase-2 model implementation
   shipped from inside `/analyse-data` with no QA pass - this rule plus the mechanical
   CODE-NO-QA / CODE-NO-TESTS gate in `check_artifacts` closes that path.) **If execution consent
   is withheld** (§7 gate, human-only), QA cannot run - do not skip it or assert a pass: take the
   **static-only DoD path** (`docs/DEFINITION-OF-DONE.md`) - QA verdict **🧠**, DoD marked
   **PARTIAL**, untested code named as residual risk, and the close offers "grant consent → we run
   the suite → verdict upgrades".
5. **Show the journey - iteration history is evidence, not noise.** When work loops (QA fail →
   fix → re-test, review → fix → re-review, BA question → SME answer → spec change), the
   documentation must show **each pass explicitly**: the Delivery Report's **iteration log**
   (journey strip + append-only hand-off table, template §1a), the QA handover's **test
   cycles** table (failed verdicts stay forever), and the elicitation **clarification
   rounds** register. The model's instinct is to present the polished end state - resist it: a
   caught-routed-fixed-re-verified failure is **proof the control loop operates**, and a
   suspiciously clean narrative is what draws auditor scrutiny. Record hand-offs at gates,
   not every tool call. Append-only: later passes add rows, never rewrite earlier verdicts.
6. **Ground every critique in a named external standard - never "look it over again".** The
   peer-reviewed evidence is unambiguous: draft-critique-revise measurably improves output,
   but **only when the critique has an external signal** - a named standard, checklist, rubric
   or verifier; ungrounded self-review is unreliable and can make output *worse* (models fail
   at finding their own mistakes, not at fixing pointed-at ones). So: every pre-delivery
   critique step names the standard it checks against - the **5 C's** for findings
   (`docs/review/output-format.md`), **BABOK quality criteria** for requirements
   (unambiguous · testable · atomic · consistent · complete), **ISO/IEC 29119-shaped**
   completeness for QA evidence, **SR 11-7-style** documentation expectations for validation
   reports - the critic is never the author, and the deliverable records which standard it was
   checked against. A critique step with no named standard is a defect in the process, not
   diligence. Prefer cheap binary gate checks (present / absent → regenerate) over critique
   prose where a mechanical check exists (`check_artifacts` covers the greppable ones).
7. **The critique/DoD gate is a FIX-LIST, not a report - these are checks on the team's OWN
   output.** A finding with a deterministic remedy is the team's to **fix and re-check**, never
   the user's to be handed; only genuine judgement calls (contradicted rationale, unverifiable
   authority, scope/acceptance) escalate to the user via the question tool. Full auto-fix vs.
   escalate tiers: `docs/DEFINITION-OF-DONE.md` / `close-checklist.md`. Listing an auto-fixable
   defect as a delivered "documentation-standards failure" is itself a process failure (live
   lesson 2026-07-23; DoD "the gate is a fix-list").
