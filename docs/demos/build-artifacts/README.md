# 🏗️ Build-demo artifacts - the actual documents produced (Run 2, canonical)

The **real deliverables** the team produced in the [build demo](../build-demo.md) - a *complete*
build stage (build core + 3 independent reviews + tuning + performance + the delivery compile). This
is **Run 2**, the canonical run; for how it compares to Run 1 see the
[run comparison](../build-run-comparison.md). Open / download:

| Document | Produced by | What it is |
|---|---|---|
| 📄 [`delivery-report.md`](delivery-report.md) | **Morgan** (PM) | **Start here.** Consolidated: RTM, review dispositions, DoD, handover, token+runtime+cost. |
| [`ts001-scenario-spec.md`](ts001-scenario-spec.md) | **Amara** (`business-analyst`) | The scenario spec (TS-001) + the §9 open-questions decision log. |
| [`ts001-sme-validation.md`](ts001-sme-validation.md) | **Camila** (`trade-surveillance-sme`) | Typology validation: FP drivers, the UBO-graph pitfall, the question dispositions. |
| [`ts001_wash_trade.py`](ts001_wash_trade.py) | **Mateo** (`rules-developer`) | The detector - UBO gate, off-market-necessary, exemptions, obligation+status+UBO fields, fail-loud. |
| [`test_ts001_wash_trade.py`](test_ts001_wash_trade.py) | **Mateo** (`rules-developer`) | Developer tests (TP + FP + stale-UBO). |
| [`test_ts001_qa.py`](test_ts001_qa.py) | **Linh** (`qa-engineer`) | The independent QA suite (boundaries, exemptions, missing-snapshot observability…). |
| [`qa-handover.md`](qa-handover.md) | **Linh** (`qa-engineer`) | QA evidence (⏪ as-found): coverage, gaps, the defects caught. |
| [`threshold-tuning-pack.md`](threshold-tuning-pack.md) | **Theo** (`tuning-analyst`) | Calibration method + illustrative values (spread-normalised; `min_notional` required). |
| [`performance-review.md`](performance-review.md) | **Thabo** (`performance-reviewer`) | Static scalability review - won't scale as-is (O(n²)); the fix. |

> **The fix→re-review loop is real:** independent review found genuine issues (a dual-source
> deviation, a missing-snapshot blind spot, and - the standout - an obligation literal that *looked*
> finalised while the SME flagged the mapping as blocked). All fixed or dispositioned; suites green.
> Dispositions: [delivery report](delivery-report.md) §3.

### ⏪ Before → After ⏩ (two snapshots, on purpose)
| | Doc | Shows |
|---|---|---|
| ⏪ **Before** (as-found) | [`qa-handover.md`](qa-handover.md) | What QA *caught* - preserved, not rewritten (audit trail). |
| ⏩ **After** (as-delivered) | [`delivery-report.md`](delivery-report.md) | Resolved state - defects fixed; deploy-gates + sign-off open by design. |

> ⚠️ **Demo artifacts - synthetic, not production.** Under `docs/`, **not** part of the repo's
> detection logic or test suite (`testpaths = ["tests"]`). All data fabricated (§5).

**Run the tests in isolation** (they pass):
```bash
cd docs/demos/build-artifacts && python3 -m pytest test_ts001_wash_trade.py test_ts001_qa.py
```

### Knowledge compounded - the lessons that prevented Run 1's defects, then grew
Run 1's review found 7 defects; they became `docs/house-rules.md` entries. In Run 2, Mateo applied
them and **none recurred**. Run 2's review then added *new* rules (obligation-status not a finalised
literal; spread-normalised threshold; `min_notional` required) - now recorded for Run 3. Advisory
agents recommend; the PM commits. That's the [house-rules](../../house-rules.md) loop working.
