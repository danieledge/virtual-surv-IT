# Artifact menu - standalone selection only (the packaging question is RETIRED)

> Loaded just-in-time by `engage` step 3, and ONLY when the user has asked for standalone
> documents (or adjusted packaging at the go-ahead gate). **The old stage-1 "How should the
> deliverables be packaged?" question is retired (2026-08-17 user decision): every real
> engagement chose the Consolidated Delivery Report, so it is the stated default in the brief,
> never a question - and `scripts/locked_menu_guard.py` now flags a re-asked packaging question
> as drift.** The grouped construction below exists because the question tool caps a question
> at 4 options - **never spec one giant multi-select of every template** (an 11-option list
> forces improvisation); the guard also checks each group's multiSelect/option-set before the
> question reaches the user.

**Standalone selection - when the user asked for separate artifacts (with or without the
consolidated report)** - ONE batched call of grouped multi-selects
(each `multiSelect: true`, each ≤4 options; skip any group irrelevant to the engagement):
- header `Spec docs`: Engagement Brief · BRD · FSD · RTM
- header `Reviews`: Code & Compliance Review · Performance Review · Model Validation Report · ADRs
- header `Handover`: Developer Handover · QA Handover · Ops Runbook + Release Notes · Change Request
Anything rarer (`docs/templates/` has the full catalogue - SAR referral, lexicon spec, …) is
reachable via each question's automatic "Other".

The **handover pack is a deliverable and belongs here** (not in the findings/fix question).
Each is delivered in **both `.md` and `.html`**.
