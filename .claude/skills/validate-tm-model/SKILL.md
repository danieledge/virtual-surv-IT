---
description: Periodic transaction-monitoring model validation pack (coverage, thresholds, data integrity, FP & alert-to-SAR)
argument-hint: <the TM system/scenario set to validate, and where the alert/outcome data is>
disable-model-invocation: true
---

Run a periodic **transaction-monitoring model validation** of: **$ARGUMENTS**

This is the recurring "is the detection still fit for purpose" review (grounded in SR 11-7 +
FFIEC BSA/AML). It is **independent** of whoever tuned/built the model.

> **When to use this vs the others.** This is the **periodic umbrella** review. It **invokes**
> coverage (`/assess-coverage`), threshold tuning (`/tune-thresholds`) and data-quality as
> *components*, then adds the **independent `model-validator` verdict** (SR 11-7) on top - it is
> not a parallel re-implementation of them. Reach for the components directly when you only need
> that one slice: `/tune-thresholds` to calibrate one scenario's numbers, `/assess-coverage` to
> map typology→scenario→feed gaps. Use this skill for the whole periodic validation pack.

**1. Gather inputs - ask via the question tool, one question per axis; don't assume.** Ask as
discrete, structured questions: which **scenario set / TM system**; where the **alert + outcome
data** is (synthetic, masked, or data **attested safe** - at intake, or **confirm now if you
invoked this skill directly** rather than via `/engage`, §5 - if raw/unprepared use
`/prepare-data`; `data/raw/` is hard-blocked); the in-scope
**jurisdiction(s)** (CLAUDE.md §2); and the **validation period**. Where an axis is mutually
exclusive (e.g. a single jurisdiction or a fixed period), make that question **single-select**.

**2. Assess (drive `tuning-analyst` for the data work + `model-validator` for the independent
verdict; `tm-sme` for typology coverage):**
- **Rule/scenario coverage** - are the firm's risks & typologies all covered? Any gaps?
- **Threshold adequacy** - are thresholds still appropriate (ATL/BTL evidence), or drifted?
- **Data integrity** - completeness/accuracy of the feeds the model depends on (hand to
  `data-quality-reviewer` - a missing feed = an undetected-abuse blind spot).
- **Performance MI** - alert volumes, **false-positive rate**, **alert-to-SAR/STR** conversion,
  trends and **stability over time** (decay).
- **Segmentation** - still valid for the current book/customer base?

**3. Produce the model-validation pack** (`docs/templates/tm-model-validation.md`; a general
statistical/ML model outside TM uses `docs/templates/model-validation-report.md`) - findings by
severity, evidence, the **applicable obligations**, and a verdict (✅ fit / ⚠️ conditional / ❌
revalidate). Each finding carries a **disposition** (fixed / open / accepted / 🔴 open-needs-human).
Save under `artifacts/`, render to `.html`.

**4. Close - don't dead-end.** State the verdict + disposition, then offer: a `/tune-thresholds`
loop on the weak scenarios, route fixes to `rules-developer`, or a handover pack. Independent
model-risk sign-off stays with `model-validator`.
