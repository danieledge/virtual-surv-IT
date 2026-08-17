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
