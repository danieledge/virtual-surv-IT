# 🏗️ Build-demo artifacts - the documents the team actually produced (DEMO)

The **real deliverables** from the [build demo](../build-demo.md) - a *complete* build stage (spec →
SME → build → independent QA → code/compliance/performance review → measured tuning → the delivery
compile), on synthetic data. Open / download:

| Document | Produced by | What it is |
|---|---|---|
| 📄 [`delivery-report.md`](delivery-report.md) | **Morgan** (PM) | **Start here.** Consolidated: RTM, finding dispositions, DoD status, handover, measured token table. |
| 📧 [`engagement-summary-email.txt`](engagement-summary-email.txt) | **Morgan** (PM) | The one-page summary email that closes every engagement (kept as `.txt`). |
| [`ts001-scenario-spec.md`](ts001-scenario-spec.md) | **Amara** (`business-analyst`) | The scenario spec (SCN-001) + EARS requirements, Gherkin criteria, open-questions log. |
| [`ts001-sme-validation.md`](ts001-sme-validation.md) | **Camila** (`trade-surveillance-sme`) | Typology validation: FP drivers, the affiliated-fund pitfall, the Q1-Q5 dispositions. |
| [`ts001_wash_trade.py`](ts001_wash_trade.py) | **Mateo** (`rules-developer`) | The detector - UBO gate, off-market-necessary (spread-normalised, mid-referenced), exemptions, obligation+status+UBO as typed fields. |
| [`test_ts001_wash_trade.py`](test_ts001_wash_trade.py) | **Mateo** (`rules-developer`) | Developer tests (TP + FP + bad-data DQ + freshest-edge). |
| [`test_ts001_qa.py`](test_ts001_qa.py) | **Linh** (`qa-engineer`) | The independent QA suite (boundaries, exemption register, observability…). |
| [`qa-handover.md`](qa-handover.md) | **Linh** (`qa-engineer`) | QA evidence (⏪ as-found): coverage, gaps, residual risk, the defect caught. |
| [`threshold-tuning-pack.md`](threshold-tuning-pack.md) | **Theo** (`tuning-analyst`) | **Measured** ATL/BTL calibration (recommend 0.75× spread; precision/recall) + the synthetic caveat. |
| [`ts001_threshold_tuning_harness.py`](ts001_threshold_tuning_harness.py) | **Theo** (`tuning-analyst`) | The seeded, reproducible labelled-data harness behind the tuning numbers. |
| [`performance-review.md`](performance-review.md) | **Thabo** (`performance-reviewer`) | Static scalability review - won't scale as-is (O(B×S)); the bucketing fix. |
| [`scenario-learnings.md`](scenario-learnings.md) | **Morgan** (PM) | Project/scenario memory - what this build taught (lives with the demo, not the plugin). |

> **The fix→re-review loop is real.** Two reviewers independently caught a genuine silent
> false-negative (a non-positive market price dropped with no audit trail); it was fixed and **both
> test suites re-run green (43/43)**. Compliance also flagged that the rework had desynced the old
> QA/RTM/handover - exactly the re-sync discipline that produced this set. Dispositions:
> [delivery report](delivery-report.md) §3.

### ⏪ Before → After ⏩ (two snapshots, on purpose)
| | Doc | Shows |
|---|---|---|
| ⏪ **Before** (as-found) | [`qa-handover.md`](qa-handover.md) + review findings | What QA / review *caught* - preserved, not rewritten (audit trail). |
| ⏩ **After** (as-delivered) | [`delivery-report.md`](delivery-report.md) | Resolved state - defects fixed; deploy-gates + sign-off open by design. |

> ⚠️ **Demo artifacts - synthetic, not production.** Under `docs/`, **not** part of the repo's
> detection logic or test suite (`testpaths = ["tests"]`). All data fabricated (§5). The deliverable
> is **demo-complete, not deployable** - obligation mapping PROVISIONAL, threshold synthetic-only,
> O(B×S) pairing to bucket, human sign-off pending.

**Run the tests in isolation** (they pass):
```bash
cd docs/demos/build-artifacts && python3 -m pytest test_ts001_wash_trade.py test_ts001_qa.py
```

### Knowledge compounds - scenario memory
The build's scenario-specific lessons (the affiliated-fund pitfall, spread-normalised/mid-referenced
tuning, treat-every-data-fault-symmetrically, bucket-the-pairing) are recorded in
[`scenario-learnings.md`](scenario-learnings.md) - project memory that travels with the demo. The
*general* engineering/audit patterns go to [`docs/house-rules.md`](../../house-rules.md). Advisory
agents recommend; the PM commits.
