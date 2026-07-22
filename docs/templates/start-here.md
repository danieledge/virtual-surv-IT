# START HERE - <ENGAGEMENT TITLE>

> **The living index - created at engagement OPEN, updated with every artifact, finalised
> at close.** The PM creates this alongside the Engagement Brief (status ⏳), appends a row
> the moment any artifact lands, sets ⛔ with the outstanding list whenever the engagement
> pauses on unanswered input, and fills the verdict/footprint at ✅ close. Its job: a reader
> opening the folder at ANY moment knows in one minute what this engagement is, **whether it
> is finished**, and what to read in what order. Never written "at the end" - an engagement
> that stalls must still show its true state. Authored in `.md`, rendered to `.html`
> (re-render on every update; links below point at `.md` - the renderer rewrites them to
> `.html` in the rendered pack). Mechanically checked: `MISSING-INDEX` / `INDEX-NO-STATUS` /
> `STALE-INDEX` / `FINAL-BEFORE-CLOSE` / `SUMMARY-BEFORE-CLOSE`.

| | |
|---|---|
| **Engagement** | <short name> |
| **Status** | ⏳ IN PROGRESS · ⛔ BLOCKED - awaiting input · ✅ CLOSED <YYYY-MM-DD> - keep exactly one |
| **Opened** | <YYYY-MM-DD> |
| **Requested by** | <name if known> |
| **Verdict** | <at ⏳/⛔: "none yet - engagement not closed, DoD not yet run" · at ✅: ready / ready with conditions / not yet - one line of why> |
| **Team** | <e.g. 4 of 17: Amara (BA), Mateo (build), Ravi (review), Linh (QA)> |
| **Footprint** | ~<N> agents · roughly <tokens> tokens <at ⏳/⛔: so far> |

## ⚠️ Outstanding before this is done

*Keep current at every update; at ✅ close replace with "Nothing - closed <date>".*

- <the unanswered clarification, by question - who it's waiting on>
- <gates not yet run: e.g. "independent QA (Linh) - not yet run" · "DoD check_artifacts - not yet run">

## Read in this order

*(At ⏳/⛔ this lists the interim pack; the summary email and Delivery Report exist only at ✅ close.)*

1. [`engagement-summary-<slug>.txt`](engagement-summary-<slug>.txt) - the two-minute cover
   note (what was asked, what happened, where it stands). *Close only.*
2. [`delivery-report.md`](delivery-report.md) - the consolidated report: iteration log
   (§1a - how we got here), findings with dispositions, QA evidence, limitations. *Close only.*
3. *Then by interest:* the deep artifacts below.

## Everything in this delivery

*One row appended per artifact, at the moment it is written - nothing in the folder goes
unlisted. Interim artifacts carry pass-scoped names (`review-pass-1`, `qa-cycle-2`,
`interim-*`) - `delivery-report.md` and `final-*` names are reserved for close.*

| Artifact | What it is | Status |
|----------|------------|--------|
| [`engagement-brief.md`](engagement-brief.md) | Scope, decisions, plan - the opening bookend | interim / final |
| <...one row per artifact, appended as it lands> | | interim / final |

## Open items a reader should know about

- <🔴 open decision / ⏭️ deploy-gate / correctly-open items - or "none">

## Provenance

Produced by the virtual compliance-surveillance engineering team
(<version> - see the Delivery Report's document control for sign-offs). Evidence basis
tags: 📊 measured · 🧠 inferred. Questions → the engagement summary email's sender.
