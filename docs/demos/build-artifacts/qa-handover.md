# QA Handover - Test Evidence - Wash Trade Detector (DEMO)

> **POST-REVIEW UPDATE (2026-06-27):** this handover is the record that *found* DEF-001 (UBO
> staleness off-by-one) and the coverage gaps. They were routed back and **fixed** - the QA suite
> now passes **33/33** and the dev suite 2/2. See the [delivery report](delivery-report.md) §3 for
> the full disposition. The "FAILED" / "open defect" text below is preserved as the original QA
> record (pre-fix).
>
> Produced by `qa-engineer` (Linh) - independent of the builder (Mateo / rules-developer).
> Evidences what was tested, the results, what is NOT covered, and what the QA team must
> note or re-verify before any production deployment.

| | |
|---|---|
| **Deliverable** | `wash_trade.py` - DEMO wash-trade / self-match detector |
| **Source file** | `docs/demos/build-artifacts/wash_trade.py` |
| **Developer suite** | `docs/demos/build-artifacts/test_wash_trade.py` |
| **QA suite** | `docs/demos/build-artifacts/test_wash_trade_qa.py` |
| **Version / commit** | `ff966f11bc4b5f54600fdd080f59271e4c8a08cc` |
| **Tested by** | qa-engineer (Linh) - independent |
| **Date** | 2026-06-27 |
| **Overall** | PASS-WITH-GAPS and 1 DEFECT - not production-ready as-is |

---

## 1. Test execution summary

### 1a. Developer suite (as delivered)

```
cmd: cd /home/daniel/www/virt-survtecb/docs/demos/build-artifacts
     python3 -m pytest test_wash_trade.py -v

result: 2 passed in 0.22s
```

| Suite | Tests | Passed | Failed | Skipped |
|-------|-------|--------|--------|---------|
| Developer (test_wash_trade.py) | 2 | 2 | 0 | 0 |

### 1b. Independent QA suite

```
cmd: cd /home/daniel/www/virt-survtecb/docs/demos/build-artifacts
     python3 -m pytest test_wash_trade_qa.py -v

result: 32 passed, 1 FAILED in 0.19s
```

| Suite | Tests | Passed | Failed | Skipped |
|-------|-------|--------|--------|---------|
| QA (test_wash_trade_qa.py) | 33 | 32 | 1 | 0 |
| **Combined** | **35** | **34** | **1** | **0** |

The one failure is a genuine defect (see §4, DEF-001).

### How to reproduce (exact commands)

```bash
# Prerequisites: Python 3.12, pytest 9.x
# From repo root:
cd /home/daniel/www/virt-survtecb/docs/demos/build-artifacts

# Developer suite (confirms baseline still green):
python3 -m pytest test_wash_trade.py -v

# Independent QA suite:
python3 -m pytest test_wash_trade_qa.py -v

# Run both together:
python3 -m pytest test_wash_trade.py test_wash_trade_qa.py -v
```

---

## 2. Environment and test data

- **Python:** 3.12.3
- **pytest:** 9.0.1
- **OS:** Linux 6.8.12 (Proxmox LXC)
- **Test data:** 100% synthetic. All account IDs (`ACC-A`, `ACC-B`, `ACC-MM`, `ACC-C`),
  trade IDs (`T001`–`T104`), instruments (`ACME`, `BETA`), prices, notionals and timestamps
  are fabricated. No real accounts, trades, or market data were used. No fixtures loaded from
  any external source. Consistent with CLAUDE.md §5.
- **UBO link:** injected as a lambda/closure in each test - no real UBO database queried.
- **Market mid:** injected via `params["market_mid"]` dict - no real price feed accessed.

---

## 3. What the developer tests actually cover

The two developer tests (`test_wash_trade.py`) cover a narrow but correct slice:

- **test_true_positive_wash_trade:** one UBO-linked pair, off-market price (6% from mid,
  tolerance 2%), fresh UBO, both accounts unexempted. Verifies exactly one alert fires with
  correct trade IDs and price deviation field.
- **test_false_positive_competitive_price_suppressed:** same pair, price only 0.5% from mid
  (below tolerance). Verifies the necessary off-market-price condition suppresses the alert.

Together they demonstrate the core happy path and ONE suppression condition. Nothing else.

---

## 3a. Key scenarios NOT covered (gaps a real deployment must test)

### Gap 1 - UBO staleness path (HIGH priority)
- No test in the developer suite exercises the staleness gate at all.
- The boundary condition (UBO `as_of` exactly equal to `staleness_cutoff`) contains a defect
  (DEF-001 below): the code accepts a UBO record that is exactly `ubo_staleness_days` old as
  fresh, because the check is `link["as_of"] < staleness_cutoff` (strict less-than), not `<=`.
  The comment says "reject links older than this" but the word "older" is ambiguous at equality.
- `ubo_link` returning `None` (unknown link) is not tested by the developer - QA confirms
  suppression works (test passes), but this was an untested path.

### Gap 2 - Exemption filter (HIGH priority)
- Entirely absent from the developer suite.
- QA confirms: buy-exempt, sell-exempt, both-exempt, and unrelated-exempt all behave
  correctly. The code is correct but was unverified.

### Gap 3 - Lookback boundary (HIGH priority)
- Entirely absent from the developer suite.
- QA confirms delta > lookback suppresses, delta == lookback does NOT suppress (the boundary
  is inclusive-at-limit: `> lookback_seconds`, not `>=`). This is a documented boundary
  behaviour the developer's tests leave entirely unchecked.
- **Structural limitation (undocumented in spec):** the inner loop iterates
  `trade_list[i+1:]` which means it only checks sells that appear AFTER the buy in list order.
  A sell that is timestamp-within-window but appears earlier in the list than its buy will not
  be matched. In a stream sorted descending by time (or unsorted), this produces false
  negatives. This is not a test failure - it is a latent architectural gap requiring manual
  QA and spec clarification before production.

### Gap 4 - min_notional gate (MEDIUM priority)
- Entirely absent from the developer suite.
- QA confirms: below threshold suppresses, above threshold fires, one-leg-below suppresses,
  and boundary-at-equality does NOT suppress (strict `<`). All pass.

### Gap 5 - Multiple instruments / cross-instrument pairing (MEDIUM priority)
- The developer suite uses only instrument `ACME` in every test.
- Cross-instrument pairs correctly do not match; two simultaneous wash pairs on two
  instruments both alert correctly. A three-account scenario produces exactly one alert for
  the UBO-linked pair. All QA tests pass.

### Gap 6 - Missing market_mid suppression (MEDIUM priority)
- Entirely absent from developer suite.
- Spec says: "No reference price - data-quality gap, not a detection gap." Suppression should
  be silent. QA confirms it is. But a monitoring obligation applies: in production, missing
  market_mid is a silent suppression that must be logged and surfaced to a data-quality feed,
  or real wash trades are invisible. The code does not log this path.

### Gap 7 - Missing required params → KeyError (LOW priority)
- Entirely absent from developer suite. QA confirms all 6 required keys raise `KeyError`
  when absent (parametrised; all 6 pass).

### Gap 8 - Degenerate inputs (LOW priority)
- Empty list, single trade, only-buys, only-sells: all return empty alert list with no
  exception. Not tested by developer. QA confirms all pass.

### Gaps NOT covered by either suite (residual - requires manual QA or integration testing)

- **Real UBO feed integration:** tests inject a mock UBO function. The actual UBO data
  provider, its SLA, and what `ubo_link` returns for edge cases (e.g. multiple UBO layers,
  circular ownership, partial/null fields) are untested. This is the highest operational risk.
- **List-order dependency (sell-before-buy):** as noted in Gap 3, the `trade_list[i+1:]`
  scan means sort order of the input iterable affects which pairs are checked. If the
  upstream feed delivers trades in reverse-chronological or random order, the detector will
  silently miss pairs. This must be stress-tested with realistic feed ordering in a UAT
  environment - cannot be resolved by unit tests alone.
- **Large-volume / performance:** O(n²) pairwise scan. For a 10,000-trade window this is
  100 million iterations. No performance test exists. Must be benchmarked against realistic
  daily trade volumes before production deployment.
- **Threshold calibration:** ALL numeric thresholds (`price_tolerance_pct`,
  `ubo_staleness_days`, `min_notional`, `lookback_seconds`) are marked `[TUNING REQUIRED]`
  in the source. No SME-approved values exist. Deploying with placeholder values would produce
  either mass false-positives or systematic false-negatives.
- **Alert field completeness:** the `WashTradeAlert` dataclass omits trade notional, quantity,
  and timestamp. Downstream alert-management systems typically require these for triage and
  regulatory record-keeping.
- **Regulatory jurisdiction mapping:** the code cites MAR Art. 12(1)(a), UK MAR Art. 12, and
  SEC Rule 10b-5 / FINRA 6140(b). No test verifies that the scenario as implemented actually
  satisfies each obligation. Compliance sign-off is required per jurisdiction before deployment.

---

## 4. Defects and known issues

| ID | Severity | Description | Status |
|----|----------|-------------|--------|
| DEF-001 | MEDIUM | **UBO staleness boundary off-by-one.** When `link["as_of"]` equals exactly `as_of_date - timedelta(days=ubo_staleness_days)` (i.e. the UBO record is exactly `ubo_staleness_days` old), the check `link["as_of"] < staleness_cutoff` is `False`, so the link is treated as fresh and the alert fires. The docstring says "reject UBO links older than this" - the intended boundary is ambiguous but a UBO record that is exactly at the configured age limit should almost certainly be treated as stale (inclusive boundary: `<=`). **Returning the alert here is a potential false-positive.** Fix: change to `link["as_of"] <= staleness_cutoff`. Requires compliance sign-off on whether the intended policy is strictly-older-than or at-least-as-old-as. | OPEN - back to builder |
| NOTE-001 | INFO | **Silent suppression on missing market_mid has no log/metric.** Not a code defect but an operational gap: when `market_mid.get(instrument)` returns `None`, the pair is silently dropped. In production, this creates invisible surveillance gaps. A counter or log line should be emitted. | OPEN - builder to assess |
| NOTE-002 | INFO | **List-order dependency in the inner loop (`trade_list[i+1:]`).** Pairs where the sell trade appears before the buy in the input list are never evaluated. Not a logic bug per the current spec (which does not define input ordering), but a latent false-negative risk if the feed is not sorted buy-before-sell. Needs a spec decision and, if needed, a pre-sort step. | OPEN - builder/SME to assess |

---

## 5. Items for the QA team to note and re-verify

1. **DEF-001 fix verification (re-test required):** once the builder changes `<` to `<=` in the
   staleness check (line 105 of `wash_trade.py`), re-run the full QA suite and confirm
   `test_ubo_exactly_at_staleness_boundary_suppressed` passes. The adjacent test
   `test_ubo_one_day_inside_window_fires` must still pass to confirm direction is correct.

2. **Threshold values before production:** the six numeric params are all `[TUNING REQUIRED]`
   in the source. No test uses SME-approved values. The QA team must obtain and document the
   approved values, re-run the test suite with those values substituted, and confirm the
   true-positive and false-positive cases still behave as expected.

3. **Input sort order / feed integration test:** manually confirm (or add an integration test)
   that the upstream trade feed delivers trades in an order that the detector can process
   correctly. If the feed is reverse-chronological, a pre-sort is mandatory or the detector
   will miss pairs.

4. **UBO data provider integration:** the `ubo_link` callable is entirely mocked in tests.
   An integration test against the real UBO provider (in a UAT environment, with synthetic
   accounts) is required before production sign-off. Specifically: what does the real provider
   return for unknown pairs (is it `None`, `{"linked": False, ...}`, or an exception)?

5. **Missing market_mid observability:** confirm with the platform team that a metric or log
   line exists (or will be added) for each instrument skipped due to missing market data, so
   surveillance coverage can be monitored.

6. **Regulatory mapping sign-off (compliance-reviewer):** the three cited obligations
   (MAR Art. 12(1)(a), UK MAR Art. 12, SEC Rule 10b-5 / FINRA 6140(b)) must each be
   individually reviewed by compliance to confirm the three-condition gate (UBO link +
   off-market price + non-exempt) satisfies each regime's full definition. In particular,
   whether off-market price is truly a necessary condition under all three regimes, or
   whether on-market self-matches are also in scope, must be signed off.

7. **Alert record completeness:** confirm with compliance / alert management whether the
   `WashTradeAlert` fields (buy/sell trade ID, accounts, instrument, price deviation, reason)
   are sufficient for the downstream alert workflow. Notional, quantity, and timestamp are
   absent and are typically required for triage.

---

## 6. QA verdict

**PASS-WITH-GAPS / NOT READY FOR PRODUCTION.**

The core detection logic (three-condition gate) is structurally sound and the developer's
2 tests are correct. The independent QA suite of 33 tests exposes 1 genuine defect (DEF-001:
UBO staleness off-by-one) and confirms the untested gates work, with structural limitations
and operational gaps that must be resolved before production.

### Top 3 tests to add before production (priority order)

1. **UBO staleness boundary with SME-approved `ubo_staleness_days` value** - DEF-001 must be
   fixed and the fix must be verified. The boundary test is the canary. Until this is resolved,
   the staleness gate cannot be relied on.

2. **Input-order / feed-sort integration test** - add a test that presents a valid wash-trade
   pair with the sell record appearing BEFORE the buy in the list, to document and enforce the
   expected behaviour. Either the detector must handle it (add a pre-sort) or the spec must
   explicitly state that input must be sorted buy-before-sell and the feed must be verified to
   guarantee that.

3. **Missing market_mid alert-count metric test** - given that missing reference prices produce
   silent suppression, add a test (and the corresponding production code) that counts/logs
   pairs dropped due to absent market mid. This is the difference between a silent surveillance
   gap and an observable one.

---

## 7. Sign-off

| Role | Name | Date | Decision |
|------|------|------|----------|
| qa-engineer (AI) | Linh (qa-engineer) | 2026-06-27 | PASS-WITH-GAPS - DEF-001 open; not production-ready |
| QA reviewer (human) | | | |
| Compliance reviewer | | | |
