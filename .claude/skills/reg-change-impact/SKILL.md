---
description: Regulatory-change impact analysis - what a changed obligation means for scenarios, controls, data and specs
argument-hint: <the regulatory change / new obligation, and the affected area>
disable-model-invocation: true
---

Assess the impact of a regulatory change: **$ARGUMENTS**

Under the PM (CLAUDE.md §6), drive **business-analyst** (with the relevant **`*-sme`** for the
regulatory reading, and `data-quality-reviewer`/`tuning-analyst` where data or thresholds are
touched). **Establish the change and the jurisdiction(s) first - ask via the question tool, one
question per axis; make any mutually-exclusive axis (e.g. a single jurisdiction) single-select**
(CLAUDE.md §2).

**The standard open applies before any agent is dispatched, even when this skill is invoked
directly.** Read `.claude/skills/.shared/engagement-bookends.md` and follow it - the Engagement
Brief and `engagement_state init` (unless `/engage` already wrote them) before step 1, the closing
bookend at the end.

1. **Understand the change** - what obligation changed, effective date, the new/amended
   requirement (get the `*-sme` to read it; don't interpret regulation unaided). **Ground every
   pinpoint citation against the regulatory register** (`config/regulatory-register.yaml`); a new
   or amended obligation belongs in the register first, not asserted from memory (ADR-001). Run
   `<python> -m scripts.check_citations <artifact>` over the output and resolve any UNVERIFIED hits.
   (`<python>`: the `INTERPRETER=` word the step-0 probe printed, verbatim, never re-probed; direct invocation and plugin-mode paths: `.claude/skills/.shared/run-mode.md`)
2. **Trace the blast radius** - which **detection scenarios**, **controls**, **data feeds/
   lineage**, **specs (BRD/FSD/RTM)** and **thresholds** are affected. Use the RTM to find what's
   linked to the old obligation.
3. **Assess gaps** - does current coverage still meet the changed obligation? New scenarios
   needed? Re-tuning? New data? Recordkeeping changes?
4. **Change plan** - prioritised actions with owners (`rules-developer` for logic, `tuning-analyst`
   for thresholds, `platform-engineer` for feeds, `business-analyst` for spec updates), risk and
   a target date.

Output: a **reg-change impact assessment** (`docs/templates/reg-change-impact.md`) - change,
affected items (traced), gaps, and the prioritised change plan with owners. Under `VSIT/engagements/`,
rendered to `.html`.

**Close - don't dead-end.** State the impact + the plan, then offer to kick off the highest-
priority changes (`/new-scenario`, `/tune-thresholds`, spec updates) or produce a handover.
