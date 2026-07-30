# Artifact menu - LOCKED two-stage construction (read at the packaging step)

> Loaded just-in-time by `engage` step 3. Two stages because the question tool caps a question at
> 4 options - **never spec one giant multi-select of every template** (an 11-option list forces
> improvisation). `scripts/locked_menu_guard.py` (audit finding #7, 2026-07-30) mechanically
> checks stage 1's options and each stage-2 group's multiSelect/option-set before the question
> reaches the user - don't rely on it instead of following this file.

**Stage 1** (header `Artifacts`, `multiSelect: false`):
*"How should the deliverables be packaged?"* →
**Consolidated Delivery Report** (the default - everything as sections of one document) ·
**Separate artifacts** (standalone documents, e.g. a change request for a ticket) ·
**Both** (the consolidated report plus selected standalones).

**Stage 2 - only if "Separate" or "Both"** - ONE batched call of grouped multi-selects
(each `multiSelect: true`, each ≤4 options; skip any group irrelevant to the engagement):
- header `Spec docs`: Engagement Brief · BRD · FSD · RTM
- header `Reviews`: Code & Compliance Review · Performance Review · Model Validation Report · ADRs
- header `Handover`: Developer Handover · QA Handover · Ops Runbook + Release Notes · Change Request
Anything rarer (`docs/templates/` has the full catalogue - SAR referral, lexicon spec, …) is
reachable via each question's automatic "Other".

The **handover pack is a deliverable and belongs here** (not in the findings/fix question).
Each is delivered in **both `.md` and `.html`**.
