# 🏗️ Build-demo artifacts - the actual documents produced

These are the **real deliverables** the team produced during the [build demo](../build-demo.md) -
not summaries. Open / download them:

| Document | Produced by | What it is |
|---|---|---|
| [`wash-trade-scenario-spec.md`](wash-trade-scenario-spec.md) | **Amara** (`business-analyst`) | The full scenario spec (SS-TS-001): behaviour, obligation, data, detection outline, parameters-to-tune, examples, Gherkin acceptance criteria, open questions. |
| [`wash-trade-sme-validation.md`](wash-trade-sme-validation.md) | **Camila** (`trade-surveillance-sme`) | The typology validation: FP drivers, the biggest pitfall (the UBO graph), and the off-market-price-as-necessary correction. |
| [`wash_trade.py`](wash_trade.py) | **Mateo** (`rules-developer`) | The detection function sketch - UBO gate, off-market-necessary, exemptions, fail-loud thresholds. |
| [`test_wash_trade.py`](test_wash_trade.py) | **Mateo** (`rules-developer`) | A pytest with a true-positive and a false-positive guard. |

> ⚠️ **Demo artifacts - synthetic, not production.** They live under `docs/` and are **not** part of
> the repo's detection logic or test suite (`testpaths = ["tests"]`). All data is fabricated (§5).

**Run the example test in isolation** (it passes):
```bash
cd docs/demos/build-artifacts && python3 -m pytest test_wash_trade.py
```

### The review stage caught a real bug (the chain isn't a rubber stamp)
When Mateo's sketch was first run, the true-positive test **failed**: the original code checked UBO
staleness against `datetime.utcnow()` (wall-clock) while the test fixtures used a fixed date - a
**non-deterministic time dependency** that silently dropped the alert once "today" drifted past the
window. That's exactly what the **code-review / QA stage** exists to catch. The fix - inject the
reference date (`as_of_date`) so the function is deterministic and testable - is in `wash_trade.py`,
and the test now passes. Code doesn't ship until it's *run* and *reviewed*; this is that in action.
