---
description: Surveillance coverage assessment - are all in-scope risks detected, and are the data feeds actually live?
argument-hint: <the surveillance area / book / desk to assess>
---

Assess **surveillance coverage** for: **$ARGUMENTS**

> **When to use this vs the others.** Use this to check whether **all in-scope risks are
> monitored and the data feeds are actually live** (the typology→scenario→feed gap map). To
> calibrate one scenario's thresholds (ATL/BTL, segmentation), use `/tune-thresholds`. For the
> periodic umbrella review that invokes this plus tuning and data-quality and adds an
> independent model-validator verdict, use `/validate-tm-model`.

> Why this matters (FCA Market Watch 79, verified): surveillance failures often come from **data
> gaps, not thresholds** - a feed left un-activated meant an insider-dealing scenario fired **zero
> alerts for 3+ years**. And effective testing is **four-component** (parameter calibration · model
> logic · model code · **data** comprehensiveness/accuracy), not calibration alone. This skill
> checks the **data + coverage** side that tuning misses.

Under the PM (CLAUDE.md §6), drive **business-analyst** (scope/obligations), **data-quality-reviewer**
(feed health), **tuning-analyst** (scenario performance) and the relevant **`*-sme`** (typologies).
**Establish the jurisdiction(s) and in-scope population first - ask via the question tool, one
question per axis; make any mutually-exclusive axis (e.g. a single jurisdiction) single-select**
(CLAUDE.md §2).

1. **Map the scope** - in-scope risks / typologies / products / venues / desks / comms channels
   (from the obligation; the SME confirms what *should* be surveilled).
2. **Map scenario coverage** - each typology → the detection scenario(s) that cover it. **Flag any
   in-scope typology with no scenario** (an unmonitored risk).
3. **Map & health-check the data feeds** - each scenario → the feeds it depends on (orders, trades,
   reference/news/market data, comms capture). For each feed: **is it live, complete, and timely?**
   Flag any **missing, dead, late or partial feed** (the MW79 blind spot). Hand feed integrity to
   `data-quality-reviewer`.
4. **Coverage gaps** - consolidate: unmonitored typologies, scenarios with broken feeds, channels
   not captured (incl. **off-channel** comms risk). Each gap = potential undetected abuse.

Output: a **surveillance coverage assessment** (`docs/templates/surveillance-coverage-assessment.md`)
- the typology→scenario→feed map, feed health, and gaps by severity with the obligation each
serves and a remediation owner (`platform-engineer` for feeds, `rules-developer` for new scenarios,
`business-analyst` for spec). Save under `artifacts/`, render to `.html`.

**Close - don't dead-end.** State the coverage verdict + the gaps, then offer to remediate
(wire a feed, build a missing scenario, `/tune-thresholds` the weak ones) or produce a handover.
