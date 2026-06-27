# Threshold-Tuning Pack - TS-001 Wash Trade (DEMO, Run 2)

> Produced by `tuning-analyst` (Theo). Obligation: MAR Art 12(1)(a). Synthetic only.
> No labelled production data here - values are **🧠 inferred** (illustrative), to be re-calibrated
> via ATL/BTL on a real labelled set. Run 1 proved the measured-sweep-on-synthetic-labelled-data
> method works (it found a 0-FP plateau); apply the same per segment.

## Method (per parameter)
- **`off_market_threshold_bps`** - the natural unit is **deviation ÷ prevailing spread**
  (spread-normalised), not flat bps. Set per liquidity segment where the true-positive ratio
  distribution separates from the FP distribution (sweep, P5-TP subject to P95-FP below it).
- **`lookback_days`** - P90-P95 of the legitimate same-UBO round-trip lag.
- **`ubo_graph_max_age_days`** - a **data-quality gate**, not a stat threshold: the UBO feed refresh
  SLA + a grace day (confirm with the data owner).
- **`min_notional`** *(required, currently absent - QA DEF-003)* - a de-minimis floor; an
  immaterial-notional pair can't give a "false or misleading signal" under MAR Art 12(1)(a). A
  **compliance risk-appetite** decision, not pure stats.

## Illustrative starting values (🧠 inferred - NOT measured)
| Parameter | Segment | Value | Rationale |
|---|---|---|---|
| off-market (spread ratio) | liquid large-cap | 1.5× spread | abuse hides at tight prices |
| off-market (spread ratio) | mid/small-cap | 2.0× spread | wider natural spread |
| off-market (spread ratio) | illiquid/OTC | 3.0× spread | high spread variance |
| off-market (abs fallback) | no spread data | 50 bps | only with a coverage-gap flag |
| `lookback_days` | exchange equities | 3 | same-day/T+1 typical |
| `ubo_graph_max_age_days` | all | feed SLA + 1 | data-quality, confirm with owner |
| `min_notional` | all | *firm STOR materiality* | compliance decision, placeholder only |

## Volume↔coverage trade-off
Tightening off-market catches at-market evasion but floods on affiliated-fund flow; loosening cuts
load but blinds the scenario to near-market washes. **Two highest-value moves:** add `min_notional`
(precision gain, negligible coverage cost) and switch to **spread-normalised** thresholds per segment
(improves precision in illiquid names and recall in liquid ones simultaneously).

## To actually calibrate
Need: labelled/SME-assessed pairs (50-100/segment); populated `spread_bps`; UBO feed SLA; the notional
distribution; alert-to-STOR history; a verified exempt-account list. (Masked/synthetic only, §5.)
