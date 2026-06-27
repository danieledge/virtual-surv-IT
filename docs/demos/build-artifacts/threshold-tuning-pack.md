# Threshold-Tuning Pack - Wash Trade / Self-Match (DEMO)

> Produced by `tuning-analyst` (Theo). Calibration for SS-TS-001. Obligation: MAR Art. 12(1)(a).
> **Now with MEASURED results** - a labelled synthetic set ([`calibrate_wash_trade.py`](calibrate_wash_trade.py))
> lets us run real ATL/BTL instead of guessing. Synthetic only (§5).

## 0. Measured calibration (📊 - the headline)
Ran the detector over a synthetic set of **600 trades with 60 injected wash pairs** (known ground
truth) + 240 legit-activity pairs (the SME's FP drivers: unaffiliated, affiliated-but-competitive,
market-maker). Swept `price_tolerance_pct`:

| price_tol % | alerts | TP | FP | precision (ATL) | recall (coverage) | missed (BTL) |
|---|---|---|---|---|---|---|
| 0.05 | 117 | 60 | 57 | 51.3% | 100% | 0 |
| **0.10** | **60** | **60** | **0** | **100%** | **100%** | **0** |
| 0.20 | 60 | 60 | 0 | 100% | 100% | 0 |
| 0.50 | 60 | 60 | 0 | 100% | 100% | 0 |
| 1.00 | 50 | 50 | 0 | 100% | 83.3% | 10 |
| 2.00 | 24 | 24 | 0 | 100% | 40.0% | 36 |

**Measured recommendation:** `price_tolerance_pct` in **0.10-0.50%** for this segment - 100%
precision *and* recall. Below it (0.05%) the off-market test admits competitive-price noise (57 FPs);
above it (≥1%) the **BTL "missed" column climbs** as genuine washes priced 0.3-1% off mid slip below
the line. 📊 measured on synthetic ground truth - reproduce with `python3 calibrate_wash_trade.py`.

> **Honest caveat (do not skip).** These numbers are measured on a **synthetic distribution we
> control** (washes injected at 0.3-3% off-mid, legit at <0.1%), so the clean 0-FP plateau is partly
> by construction - real markets are messier. This **validates the calibration *method* and the
> volume↔coverage curve**; the deployment value still needs ATL/BTL on a **real labelled set**. The
> label "measured on synthetic data" is not a regulatory defence.

## 1. Methodology (how each parameter is set)
- **Segment first** (calibrate per segment, not globally): instrument **liquidity band**, **venue
  type** (lit/dark/OTC - OTC has no exchange mid), **account type** (retail vs prop changes the noise floor).
- **`price_tolerance_pct`** - from the empirical bid/ask **spread distribution**: set above the 97.5th
  percentile / mean+2σ of normal spread so a competitive price is never flagged. *(Measured above.)*
- **`lookback_seconds`** - from the distribution of legitimate same-UBO round-trip times; 90-95th pct.
- **`min_notional`** - a percentile (5-10th) of the segment's trade-size distribution; never a round number.
- **`ubo_staleness_days`** - a **data-governance** bound: the firm's KYC refresh SLA (e.g. 180d
  higher-risk / 365d standard), per FATF R.10. Not an independent tuning choice.
- **repetition floor** - the tail of the legitimate per-UBO pair-count distribution (Poisson/neg-binomial).
- **`market_mid`** - a *feed*, not a threshold: source/latency/coverage gated by `data-quality-reviewer`
  via `/assess-coverage`. Missing mid = silent miss (the FCA MW79 failure mode).

## 2. Illustrative starting points (🧠 - for un-measured segments)
For segments without a labelled set yet: large-cap liquid equities ~0.10% (10bps); mid-cap ~0.50%;
illiquid ~1%+. `lookback` 300s lit / 1800s OTC. `min_notional` ~GBP 10k institutional. `ubo_staleness`
180d. repetition floor 2. All 🧠 inferred - replace via §0 measurement per segment.

## 3. Data needed to calibrate the *real* scenario
12m masked trade feed (RTS 25 timestamps), the UBO table with as-of dates, per-instrument spread
series, a labelled alert/SAR set (even n=100-200), legitimate round-trip distribution, and the
`market_mid` coverage inventory. (Masked/synthetic only, §5.)

## 4. MI & cadence
Track monthly: alert volume/segment, FP rate (ATL), alert-to-SAR conversion, analyst-minutes/alert;
flag >20% volume drift (decay or feed problem). Re-calibrate annually or on universe change.
House-rules lessons recorded in [`../../house-rules.md`](../../house-rules.md).
