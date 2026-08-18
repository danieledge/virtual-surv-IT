# SME knowledge pack: Transaction Monitoring / AML

> Consult in-line, just-in-time (usage rules: `docs/sme/README.md`). Converted from the
> `tm-sme` subagent 2026-08-17; the substance below is unchanged. Advises detection
> design only - implementation is `rules-developer`'s, threshold calibration/tuning
> execution is `tuning-analyst`'s.

Frameworks span the firm's configured jurisdictions (see `docs/scope-and-stack.md`) plus
the firm's risk appetite. Apply the regime(s) relevant to the flow. Always tie a scenario
back to the predicate typology and the regulatory obligation it serves. Never request or
echo raw transaction or customer record content (§5) - work from schemas and synthetic
examples.

## Consultation protocol

1. Restate the money-laundering typology in scope (e.g. structuring, rapid movement of
   funds, round-tripping, mule activity, trade-based ML).
2. Specify the detection logic: entities, time windows, aggregation, peer-group or
   behavioural baselining, and the threshold/parameter set.
3. Identify the data required and any data-quality dependencies.
4. Call out the likely false-positive drivers and how segmentation or suppression would
   reduce them without creating coverage gaps.
5. Note SAR/STR considerations and what evidence an investigator would need.

## Output format

- **Typology & obligation** (with citation)
- **Detection logic** (precise, implementable)
- **Data requirements**
- **Tuning / FP considerations**
- **Audit & explainability notes**

Flag anything that would be hard to explain to a regulator. A consult that turns into
implementation hands a clear specification to `rules-developer`. **Tag every insight
📊 observed (a source states it) / 🧠 inferred (expert reasoning)** (CLAUDE.md §6).
Durable lessons per CLAUDE.md §6: project-specific → the working project's own
`CLAUDE.md`; general → `docs/house-rules.md`.

## Under-alerting diagnosis (consult on "why no alert?" - `/why-no-alert` walks the chain)

TM-specific absence causes, in the order they actually occur: **eligibility/exclusion
lists** (the customer, account type or product was scoped out at ingestion - the most
common invisible cause); **segmentation misassignment** (right customer, wrong segment,
so the wrong threshold set applied); **aggregation windows** (activity split across a
period boundary never summed over the line); **suppression as an FP-reduction lever that
over-reached** (a rule quieted for noise now swallowing true positives); **threshold
drift vs behaviour drift** (thresholds tuned on last year's volumes). Distinguish "the
scenario never saw it" (data/eligibility) from "saw it and scored under the line"
(threshold - route to BTL) before proposing any fix.
