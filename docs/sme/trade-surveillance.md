# SME knowledge pack: Trade Surveillance / market abuse

> Consult in-line, just-in-time (usage rules: `docs/sme/README.md`). Converted from the
> `trade-surveillance-sme` subagent 2026-08-17; the substance below is unchanged.
> Advises scenario design only - implementation is `rules-developer`'s.

Frameworks span the firm's configured jurisdictions (see `docs/scope-and-stack.md`).
Distinguish clearly between manipulative trading (order-book behaviour) and
information-based abuse (insider dealing, unlawful disclosure). Never request or echo
raw order/trade record content (§5) - work from schemas and synthetic examples.

## Consultation protocol

1. Identify the abuse typology and the behavioural signature that distinguishes it from
   legitimate activity.
2. Specify detection logic: order/trade events, order-book reconstruction needs, timing
   relationships, cancellation ratios, price/volume impact, and cross-product or
   cross-venue linkage where relevant.
3. State the reference and market data required (e.g. best bid/offer, benchmark windows).
4. Identify benign explanations that drive false positives (legitimate market making,
   hedging, iceberg orders) and how to exclude them.
5. Note what an investigator needs to evidence intent and the regulatory citation.

## Output format

- **Typology & obligation** (with citation)
- **Behavioural signature**
- **Detection logic** (implementable, with data/timing precision)
- **Benign-activity exclusions / FP drivers**
- **Evidence & explainability notes**

A consult that turns into implementation hands a precise spec to `rules-developer`.
**Tag every insight 📊 observed (a source states it) / 🧠 inferred (expert reasoning)**
(CLAUDE.md §6). Durable lessons per CLAUDE.md §6: project-specific → the working
project's own `CLAUDE.md`; general → `docs/house-rules.md`.

## Under-alerting diagnosis (consult on "why no alert?" - `/why-no-alert` walks the chain)

Trade-surveillance-specific absence causes: **instrument/venue scope gaps** (the scenario
runs, just not on that instrument class, venue or order type - and liquid-name alert flow
masks illiquid-name silence: FCA MW79's Firm B pattern); **reference-data dependencies**
(a scenario conditioned on a news/price feed that is stale or was never activated - MW79
Firm A, zero insider alerts for 3+ years); **order-lifecycle completeness** (amends/
cancels or sponsored-DMA flow never ingested - MW79 Firm C); **baseline starvation**
(behaviour-relative logic with too little history for that trader/instrument, so the rule
skips silently - the worked spoofing example documents exactly this mode); **cross-day or
cross-venue logic** that requires co-timed events the data model splits. Segment-granular
volume checks, never aggregate: presence elsewhere masks absence somewhere.
