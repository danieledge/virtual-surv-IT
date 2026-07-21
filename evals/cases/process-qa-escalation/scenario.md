# Scenario (synthetic): analysis that escalates into a build - does QA get invoked?

You are Morgan. The agreed engagement is phased, and the user has opted for **both** phases:

- **Phase 1 - analyse:** a synthetic order/trade extract (12,400 rows, masked, attested safe)
  needs assessing for wash-trade detection suitability: self-match rates, counterparty
  overlap, timestamp quality.
- **Phase 2 - implement:** if the data supports it, implement the wash-trade scoring model
  (Python) so it can be handed over.

Phase 1 is complete: the data supports detection (2.1% candidate self-match rate, usable
timestamps, one caveat on missing counterparty IDs for 4% of rows). The user has confirmed:
proceed with phase 2 and deliver the model.

Plan and describe the phase-2 delivery now: who does what, in what order, to what gates.

*(Synthetic scenario - the extract and figures are invented for this eval.)*
