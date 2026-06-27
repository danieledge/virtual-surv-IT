# Performance Review - TS-001 Wash Trade Detector (DEMO, Run 2)

> Produced by `performance-reviewer` (Thabo). **Static-only** (§7 - not executed). Surveillance
> volumes are large (millions of trades/day).

## Verdict: ❌ will NOT scale as-is
The flat `buys × sells` cross-join with no pre-grouping is the binding constraint.

## Findings
- 🔴 **O(B×S) nested loop** (`detect_wash_trades`) - 🧠 inferred. Every buy is compared against every
  sell across all instruments/UBO groups before the structural guards prune. ~2.5×10⁹ iterations at
  10⁵ trades; untenable at 10⁶; infeasible at 10⁷. **Fix:** pre-group sells into a dict keyed by
  `(instrument, ubo_group_id)`, then the inner loop visits only same-instrument/same-UBO sells →
  collapses toward O(n). 🔴 Open for productionisation.
- 🟠 **Unbounded in-memory accumulation** - 📊 the whole input is materialised and `alerts` grows
  without a cap/stream. At 10⁷ trades, multi-GB. **Fix:** stream in instrument/date-partitioned
  chunks and flush alerts. 🔴 Open for productionisation.

## Done well
- 📊 UBO + market indices pre-built as dicts (O(1) lookups); freshness validated eagerly; exempt
  accounts filtered once upfront; frozen dataclasses; obligation cited on the alert; deterministic
  alert id.

Exact wall-clock needs a benchmark (off by default, §7); the O(n²)→O(n) reduction is 🧠 inferred and
expected to be transformative. **Deferred** to productionisation (demo has no volume).
