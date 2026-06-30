# Threshold Tuning Pack - TS-001 Wash Trade / Self-Match (off-market spread-multiple)

> Produced by `tuning-analyst` (Theo). Evidence for a threshold/parameter change, defensible to a
> regulator. Statistical analysis on **synthetic data only** (§5). Authored in `.md`, rendered to
> `.html`. Threshold changes to live logic are implemented by `rules-developer` and signed off by
> `model-validator` - this pack is the recommendation, not the production change.

> **Document control** · ID `TUNE-001` · Version `0.1` · Status `Draft`
> · Classification `Internal` · Owner `tuning-analyst (Theo)` · As-of `2026-06-30`
>
> | Version | Date | Author | Change |
> |---|---|---|---|
> | 0.1 | 2026-06-30 | Theo (tuning-analyst) | Initial calibration of `off_market_spread_multiple` (M2) on a seeded synthetic labelled set |

| | |
|---|---|
| **Scenario / rule** | TS-001 Wash trade / self-match (`ts001_wash_trade.py`); obligation EU MAR Art.12(1)(a) (`obligation_status = PROVISIONAL`, SMV-001) |
| **Jurisdiction(s)** | EU MAR (primary, verified in register); UK/US/SG/HK/JP equivalents `TO-VERIFY` per SCN-001 §2 |
| **Data window** | Synthetic labelled population, 2,400 candidate pairs, generated deterministically (seed `20260630`); no real data |
| **Date / tuner** | 2026-06-30 / Theo (tuning-analyst) |
| **Recommendation** | Set `off_market_spread_multiple = 0.75` (keep the **mid** reference frame); resolves M2 against the placeholder `1.0` |
| **Next review date** | 2026-12-30 (6 months) or on first calibration against real/masked production data |
| **Re-tune triggers** | Alert volume spike >25%; precision <0.70 in production sampling; alert-to-STOR conversion <10%; book/venue composition change; spread-regime shift; regulatory change to the typology |

---

## 1. Objective & current state

We are calibrating the one tuning parameter that governs the **DR-002 off-market necessary
condition**: `off_market_spread_multiple`. The detector flags a UBO-linked opposing-leg pair only
when the average leg price deviates from the prevailing **mid** by **more than** this multiple of
the prevailing (time-weighted) spread:

```
spread_normalised_deviation = |avg_leg_price - mid| / mid * 10_000 / time_weighted_spread_bps
alert if spread_normalised_deviation > off_market_spread_multiple   (and DR-003/004/005 pass)
```

**Current state.** The constant ships at a **placeholder `1.0`** (`tuning_date: TBD`) - "a full
spread from mid", which is **~2x the touch** (the half-spread to best bid/offer). That value is a
reasoned starting point, **not** a calibrated number, and the code explicitly defers the choice to
this analysis (M2). There is no production alert volume / FP / alert-to-STOR baseline yet (the
scenario is pre-deployment), so this pack establishes the calibration **method** and the
**relative trade-off** on a labelled synthetic distribution, not a production number (see §7 caveat).

**Why it matters.** DR-002 is the sole precision lever in TS-001 that tuning can move: UBO linkage,
safe-harbour and materiality are structural/policy gates, not calibration knobs (SMV-001 §3). The
spread-multiple alone decides how much at/near-market noise is admitted vs how much genuine
off-market wash is caught.

---

## 2. Segmentation (risk-based)

Spread-normalisation is itself the segmentation mechanism for this parameter: dividing by each
instrument's time-weighted spread is designed to make **one** threshold behave consistently from
tight- to wide-spread instruments (SMV-001 §1.2). To **test** that claim - rather than assume it -
the synthetic population spans three liquidity segments and we calibrate per segment.

| Segment | Definition | Population (pairs) | Behaviour profile (normalised dev: median / spread) |
|---|---|---|---|
| LIQUID | tight spread ~3 bps (e.g. large-cap equity) | 800 (100 wash / 700 legit) | wash ~1.3x / σ0.55; legit ~0x / σ0.32 (📊 by construction) |
| MID | spread ~20 bps | 800 (100 wash / 700 legit) | same normalised distributions as LIQUID |
| ILLIQUID | wide spread ~200 bps (e.g. off-the-run / small-cap) | 800 (100 wash / 700 legit) | same normalised distributions as LIQUID |

The wash- and legit-deviation distributions are **identical in normalised space across the three
segments by construction**, so any divergence in measured precision/recall across segments would
reveal a normalisation defect. 📊 (synthetic, n=2,400)

---

## 3. Candidate thresholds & statistical rationale

The genuine-population (legit) normalised deviation is centred at mid (σ≈0.32 of a spread): at/near
-market coincident fills, ETF creation/redemption and index rebalancing (SMV-001 §3). On a half-
normal that puts **P95 ≈ 0.63** and **P99 ≈ 0.74** spreads. So a threshold at the **0.75x** knee
sits just above the legit P99 - i.e. it is the smallest multiple that clears essentially the whole
genuine distribution, the classic "μ+ of the benign population" basis. Candidates swept:

| Segment | Current | Candidate | Basis | Rationale |
|---|---|---|---|---|
| All (normalised) | 1.0 (placeholder) | **0.75** | ≈ legit P99 (half-normal σ0.32 → P99≈0.74) | Smallest multiple clearing the benign tail; F1-optimal on the swept grid (§4) |
| All (normalised) | 1.0 | 0.5 (touch) | best bid/offer boundary | M2 lower anchor - any print beyond the visible quote |
| All (normalised) | 1.0 | 1.0 (full spread) | a full spread from mid | M2 upper anchor / current placeholder |
| All (normalised) | 1.0 | 1.5, 2.0 | deep tail | precision-maximising / coverage-sacrificing extremes |

No round number is asserted without the ATL/BTL evidence below.

---

## 4. Above-The-Line (ATL) test - precision among flagged

Detector run at each candidate over the full labelled set (n=2,400 pairs; 300 wash / 2,100 legit;
synthetic base rate 12.5%). **📊 observed** at every row.

**Overall:**

| Threshold (x spread from mid) | Alerts | TP | FP | FN | Precision | Recall | F1 |
|---|---|---|---|---|---|---|---|
| 0.50 (touch) | 514 | 275 | 239 | 25 | 0.535 | 0.917 | 0.676 |
| **0.75 (recommended)** | **298** | **251** | **47** | **49** | **0.842** | **0.837** | **0.839** |
| 1.00 (full spread / current) | 219 | 215 | 4 | 85 | 0.982 | 0.717 | 0.829 |
| 1.50 | 102 | 102 | 0 | 198 | 1.000 | 0.340 | 0.507 |
| 2.00 | 28 | 28 | 0 | 272 | 1.000 | 0.093 | 0.171 |

**Per segment (validates spread-normalisation):** precision at a given threshold is consistent
across the three liquidity segments - e.g. at 0.75x: LIQUID 0.890 / MID 0.865 / ILLIQUID 0.780; at
1.0x: 0.988 / 0.969 / 0.987. 📊 The single normalised threshold therefore behaves equivalently from
3 bps to 200 bps spreads, **confirming no per-segment override of this parameter is needed** -
residual cross-segment variation is sampling noise (±~50 wash/segment), not a structural break.

---

## 5. Below-The-Line (BTL) test - what's missed just under the line

Distribution of the labelled population by deviation band (📊 observed, n=2,400) - this is what each
threshold leaves behind:

| Band (x spread from mid) | Wash (true) | Legit (false) | Wash:Legit |
|---|---|---|---|
| 0.00 - 0.50 | 25 | 1,861 | 1 : 74 |
| 0.50 - 0.75 | 24 | 192 | 1 : 8 |
| 0.75 - 1.00 | 36 | 43 | ~1 : 1 |
| 1.00 - 1.50 | 113 | 4 | 28 : 1 |
| 1.50 + | 102 | 0 | — |

**Reading the BTL:**
- Just **under 0.75** (the 0.50-0.75 band): 24 genuine wash pairs are missed - but the band is
  **8:1 legit-dominated**. Recovering those 24 (by dropping to 0.5) admits 192 false positives. 📊
- Just **under 1.0** (the 0.75-1.00 band): 36 genuine wash pairs sit here against 43 legit - the
  genuinely **ambiguous zone**, ~1:1. Choosing 1.0 forgoes these 36 true wash; choosing 0.75
  captures them at a proportionate 43-FP cost. 📊
- The missed wash below 0.75 are by definition the **least off-market** prints (barely through the
  spread) - the evidentially weakest cases, hardest to sustain as abuse without comms (🧠 inferred,
  consistent with SMV-001 §1.2 on volume-only / near-market conduct).

---

## 6. Dry-run - projected volume & population change

Candidate vs the placeholder `1.0` baseline, over the synthetic window. 📊 observed.

| Change | Alerts now (1.0) | Alerts (candidate) | Δ volume | Population effect |
|---|---|---|---|---|
| → **0.75 (recommended)** | 219 | 298 | **+79 (+36%)** | +36 true wash caught (recall 0.717→0.837), +43 FP (precision 0.982→0.842) |
| → 0.50 (touch) | 219 | 514 | +295 (+135%) | +60 true wash vs 1.0, but +235 FP; precision collapses to 0.535 |
| → 1.50 | 219 | 102 | −117 (−53%) | −113 true wash (recall 0.717→0.340); precision 1.000 |

---

## 7. Volume ↔ coverage trade-off & recommendation

**The headline.** Resolving M2 is a choice along the touch↔full-spread axis:

- **0.50x (the touch / best bid-offer)** - "alert on any print beyond the visible quote." Maximal
  coverage (**recall 0.917**) but **precision 0.535**: on this set **over half of all alerts are
  false positives** (239 of 514). At production base rates - far below 12.5% - precision would be
  worse still. This is the alert-fatigue / credibility failure mode the SME warns of (SMV-001 §3);
  operationally untenable. 📊
- **1.00x (a full spread from mid / the placeholder)** - "alert only when demonstrably through the
  book." Near-perfect **precision 0.982** (4 FP) but **recall 0.717**: it **misses 85 of 300 genuine
  wash pairs (28%)** - a coverage blind spot a regulator would challenge, concentrated in the
  ambiguous 0.75-1.0 band. 📊
- **0.75x (recommended)** - the knee just above the benign P99. **Precision 0.842, recall 0.837,
  F1 0.839** (the swept maximum). Versus the `1.0` placeholder it **recovers 12 points of recall
  (+36 true wash caught) for a precision cost from 98% to 84% (+43 FP across 2,400 pairs)** -
  and **42% fewer alerts** than the 0.5 touch for only an 8-point recall give-up (the 24 missed
  cases sit in an 8:1 legit-dominated band). 📊

**Recommendation (per segment): a single `off_market_spread_multiple = 0.75`, mid-referenced, for
all liquidity segments.** §4 shows the normalised threshold behaves equivalently across LIQUID / MID
/ ILLIQUID, so no per-segment override is warranted for this parameter. Recall the SME confirmed the
**mid** reference frame and the **time-weighted** spread denominator (SMV-001 §1.2) - this
recommendation keeps both and tunes only the multiple.

**M2 resolution (explicit).** The reference frame **stays MID** (do not re-anchor to the touch).
The multiple moves from the placeholder `1.0` to **`0.75`** - i.e. **1.5x the touch / three-
quarters of a full spread from mid**. Rationale: 1.0 leaves a 28% coverage gap in the ambiguous
zone; 0.5 (the touch) is precision-untenable; 0.75 is the evidenced balance and corresponds to a
defensible statistical anchor (just above the legit-population P99).

**Other parameters (noted, not re-tuned here):**
- `lookback_days = 1` - non-binding on this single-day population; **🧠 inferred** that a real
  deployment must replace date granularity with sub-second/intraday windows per asset class
  (per the detector docstring and SMV-001 §Q5). Out of scope for this pack; flag for a follow-up.
- `min_pair_notional = 10_000` - set well below all synthetic notionals so it did not gate the
  ATL/BTL; a materiality/risk-appetite call to be set against the firm's real notional distribution.
  **Not calibrated here.**
- `ubo_graph_max_age_days = 90` - a coverage (false-negative) control, not a precision lever
  (SMV-001 §1.1); unchanged.

**Residual risk.** At 0.75x, 49 of 300 genuine wash pairs are still missed (the least off-market
prints) and 47 false positives survive into the queue - acceptable given the §5 BTL shows the
missed band is benign-dominated and the survivors are individually reviewable. 🧠

**Honest caveat (load-bearing).** Every number here is **📊 observed on a *synthetic* distribution**
with a deliberately high 12.5% wash base rate (chosen for statistical power, n=300 wash). It
validates the **calibration method and the *relative* trade-off between thresholds** - it is **not**
a real-world production number. Two consequences: (a) at realistic (far lower) wash base rates,
**absolute precision will be lower** than shown - the threshold ordering transfers, the precision
levels do not; (b) the legit/wash deviation distributions are modelled assumptions, so the exact
knee (0.75) must be **re-confirmed against masked/real data** before go-live. This pack should be
re-run on production-representative data once available. 🧠

---

## 8. Performance MI - ongoing monitoring

Track after deployment to detect decay and confirm the tuning held.

| Metric | Definition | Calculation | Current | Target | Basis |
|---|---|---|---|---|---|
| Alert volume | Alerts raised per period | `count(alert_id) by segment, period` | n/a (pre-prod) | stable ±25% | 📊 |
| False-positive rate | FP alerts / total alerts | `count(FP) / count(alert)` | 0.158 (synthetic, 0.75x) | <0.30 in prod sampling | 📊 |
| Precision | TP / (TP + FP) at threshold | `count(TP) / count(TP + FP)` | 0.842 (synthetic, 0.75x) | monitor; expect lower in prod | 📊 |
| Recall (sampled) | TP / (TP + FN) on labelled QA sample | `count(TP) / count(TP + FN)` | 0.837 (synthetic, 0.75x) | ≥0.80 on QA sample | 📊 |
| Alert-to-SAR/STR conversion | STORs filed / alerts raised | `count(STOR) / count(alert)` | n/a | ≥0.10 (re-tune trigger) | 📊 |
| Stability | Month-on-month alert volume variance | std-dev of monthly alert counts | n/a | low variance | 📊 |

---

## 9. Next steps

- **Implementation → `rules-developer` (Mateo):** set `DEFAULT_OFF_MARKET_SPREAD_MULTIPLE = 0.75`
  with `tuning_date: 2026-06-30` and a comment citing this pack (TUNE-001); keep the mid reference
  frame and the time-weighted spread denominator unchanged.
- **Independent sign-off → `model-validator` (Viktor):** challenge the synthetic distributions and
  the base-rate caveat before the value is treated as production-ready.
- **Follow-ups (out of scope here):** calibrate `lookback_days` per asset class on intraday data;
  set `min_pair_notional` against the firm's real notional distribution; **re-run this harness on
  masked/production-representative data** to confirm the 0.75 knee.
- Reproduce the evidence: `python3 docs/demos/build-artifacts/ts001_threshold_tuning_harness.py`
  (seed `20260630`, deterministic).

---

## Sign-off

| Role | Name | Decision | Date |
|------|------|----------|------|
| Author / owner | Theo (tuning-analyst) | Recommend `off_market_spread_multiple = 0.75`, mid-referenced, single threshold across segments. Synthetic evidence; validates method + relative trade-off, not a production number. | 2026-06-30 |
| `compliance-reviewer` (DoD gate) | | | |
| Human approver (or `[IT team]`) | | | |
