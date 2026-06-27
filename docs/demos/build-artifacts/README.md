# 🏗️ Build-demo artifacts - the actual documents produced

These are the **real deliverables** the team produced during the [build demo](../build-demo.md) -
not summaries. A *complete* build stage (build core + 3 independent reviews + the delivery
compile) - open / download them:

| Document | Produced by | What it is |
|---|---|---|
| 📄 [`delivery-report.md`](delivery-report.md) | **Morgan** (PM) | **Start here.** The consolidated delivery: RTM, review findings + dispositions, DoD status, developer handover, and the **token-usage** capture. |
| [`wash-trade-scenario-spec.md`](wash-trade-scenario-spec.md) | **Amara** (`business-analyst`) | The full scenario spec (SS-TS-001 Rev B): behaviour, obligation, data, detection outline, parameters-to-tune, Gherkin acceptance criteria. |
| [`wash-trade-sme-validation.md`](wash-trade-sme-validation.md) | **Camila** (`trade-surveillance-sme`) | The typology validation: FP drivers, the UBO-graph pitfall, the off-market-price-as-necessary correction. |
| [`wash_trade.py`](wash_trade.py) | **Mateo** (`rules-developer`) | The detection function - UBO gate, off-market-necessary, exemptions, fail-loud thresholds, obligation+UBO on the alert. |
| [`test_wash_trade.py`](test_wash_trade.py) | **Mateo** (`rules-developer`) | Developer pytest (true-positive + false-positive guard). |
| [`test_wash_trade_qa.py`](test_wash_trade_qa.py) | **Linh** (`qa-engineer`) | The **independent** 33-test QA suite that *found* DEF-001. |
| [`qa-handover.md`](qa-handover.md) | **Linh** (`qa-engineer`) | QA evidence: coverage, gaps, residual risk, the defect found. |
| [`threshold-tuning-pack.md`](threshold-tuning-pack.md) | **Theo** (`tuning-analyst`) | Calibration - **measured** ATL/BTL on synthetic data (`price_tolerance_pct` 0.10-0.50%) + methodology. |
| [`calibrate_wash_trade.py`](calibrate_wash_trade.py) | **Theo** (`tuning-analyst`) | Synthesises a *labelled* set and runs the measured calibration (run it: `python3 calibrate_wash_trade.py`). |
| [`performance-review.md`](performance-review.md) | **Thabo** (`performance-reviewer`) | Static scalability review - won't scale as-is (O(n²)); the fix. |

> **The fix→re-review loop is real:** independent review (code/QA/compliance) found 7 defects
> (a buy-side false-negative, an off-by-one, a broken audit-trail field, more) - all **fixed** and
> re-tested (dev 2/2, QA 33/33 green). The disposition is in the [delivery report](delivery-report.md) §3.

### ⏪ Before → After ⏩ (two snapshots, on purpose)
The same deliverable appears at two points in time - this is deliberate, not a contradiction:

| | Doc | Shows |
|---|---|---|
| ⏪ **Before** (as-found) | [`qa-handover.md`](qa-handover.md) | What QA *caught* - DEF-001 + gaps, "not production-ready". **Preserved, not rewritten** (audit trail). |
| ⏩ **After** (as-delivered) | [`delivery-report.md`](delivery-report.md) | The resolved state - 7 defects ✅ Fixed; deploy-gates ⏭️ Deferred; sign-off ⛔ Pending. |

You don't retro-edit QA evidence; you **disposition** it. The QA handover says "here's what was
wrong"; the delivery report says "here's how it ended". Reading both *is* the demonstration of the
fix→re-review loop.

> ⚠️ **Demo artifacts - synthetic, not production.** They live under `docs/` and are **not** part of
> the repo's detection logic or test suite (`testpaths = ["tests"]`). All data is fabricated (§5).

**Run the example test in isolation** (it passes):
```bash
cd docs/demos/build-artifacts && python3 -m pytest test_wash_trade.py
```

### The advisory recommendations were actioned (loop closed)
Camila and Mateo each recommended additions to `docs/house-rules.md` (the UBO-graph keystone, the
affiliated-fund FP driver, off-market-price-as-necessary, the early-continue implementation rule).
Advisory agents *recommend*; the PM *commits* - so those are now recorded in
[`docs/house-rules.md`](../../house-rules.md) (2026-06-27 entries). That's the knowledge-compounds
pattern working, not just narrated.

### The review stage caught a real bug (the chain isn't a rubber stamp)
When Mateo's sketch was first run, the true-positive test **failed**: the original code checked UBO
staleness against `datetime.utcnow()` (wall-clock) while the test fixtures used a fixed date - a
**non-deterministic time dependency** that silently dropped the alert once "today" drifted past the
window. That's exactly what the **code-review / QA stage** exists to catch. The fix - inject the
reference date (`as_of_date`) so the function is deterministic and testable - is in `wash_trade.py`,
and the test now passes. Code doesn't ship until it's *run* and *reviewed*; this is that in action.
