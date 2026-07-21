# START HERE - <ENGAGEMENT TITLE>

> **The index artifact - the first thing a reader opens.** Written by the PM as the LAST
> artifact of the engagement, once everything else exists. Its job: a newcomer with no
> context knows in one minute what this engagement was, where things stand, and what to
> read in what order. Authored in `.md`, rendered to `.html` (links below point at `.md`;
> the renderer rewrites them to `.html` in the rendered pack).

| | |
|---|---|
| **Engagement** | <short name> |
| **Date closed** | <YYYY-MM-DD> |
| **Requested by** | <name if known> |
| **Verdict** | <ready / ready with conditions / not yet - one line of why> |
| **Team** | <e.g. 4 of 17: Amara (BA), Mateo (build), Ravi (review), Linh (QA)> |
| **Footprint** | ~<N> agents · roughly <tokens> tokens |

## Read in this order

1. [`engagement-summary-<slug>.txt`](engagement-summary-<slug>.txt) - the two-minute cover
   note (what was asked, what happened, where it stands).
2. [`delivery-report.md`](delivery-report.md) - the consolidated report: iteration log
   (§1a - how we got here), findings with dispositions, QA evidence, limitations.
3. *Then by interest:* the deep artifacts below.

## Everything in this delivery

| Artifact | What it is | Status |
|----------|------------|--------|
| [`delivery-report.md`](delivery-report.md) | Consolidated report - start here after the email | <final / draft> |
| [`qa-handover.md`](qa-handover.md) | Independent test evidence, cycles + defect lifecycle (as-found) | |
| [`rtm.md`](rtm.md) | Requirement → code → test → obligation traceability | |
| <...one row per artifact - nothing in the folder goes unlisted> | | |

## Open items a reader should know about

- <🔴 open decision / ⏭️ deploy-gate / correctly-open items - or "none">

## Provenance

Produced by the virtual compliance-surveillance engineering team
(<version> - see the Delivery Report's document control for sign-offs). Evidence basis
tags: 📊 measured · 🧠 inferred. Questions → the engagement summary email's sender.
