# Performance Review - Wash Trade Detector (DEMO)

> Produced by `performance-reviewer` (Thabo). **Static-only** (CLAUDE.md §7 - the code was not
> executed for profiling). Surveillance volumes are large (millions of trades/instrument/day).

## Verdict: ❌ will NOT scale as-is
The O(n²) pairwise cross-scan against a fully-materialised input is a hard ceiling.

## Findings
- 🔴 **O(n²) cross-scan** (`detect_wash_trades`, the nested loop) - 🧠 inferred. The inner loop
  iterates the *entire* trade list for every buy, regardless of instrument/window. At 10⁵ trades ≈
  10¹⁰ pair-evals; 10⁶ ≈ 10¹²; 10⁷ ≈ 10¹⁴. The instrument/window guards fire *inside* the loop, so
  they cut the constant factor, not the complexity. **Fix:** group by `(instrument, time-bucket)`
  before scanning (a `defaultdict(list)` on instrument + a `bisect` window on a per-instrument
  timestamp-sorted list) → expected **O(n·k)** where k = trades per instrument per window (k ≪ n).
  Transformative at scale (minutes-to-hours → seconds).
- 🟠 **Full materialisation** `trade_list = list(trades)` - 📊 measured (explicit at that line). The
  whole input is loaded before processing; at 10⁶ trades ≈ hundreds of MB-low GB; 10⁷ may exhaust
  heap. **Fix:** the grouping above can be a single streaming pass, capping peak memory to the
  largest instrument's active window.

## Done well
- 📊 Cheap structural filters (instrument/side/account/exemption) run **before** the expensive
  `ubo_link()` call and mid lookup - limits UBO calls to already-qualified pairs.
- 📊 `ubo_link` injected (mockable; a cache wrapper can be inserted without touching detection logic).
- 📊 `as_of_date` injected, fail-loud params - correct for a regulated, deterministic rule.

## Potential gains
| Issue | Current | After fix | Gain | Basis |
|---|---|---|---|---|
| O(n²) scan | ~10¹² evals @ 10⁶ | O(n·k), k≪n | orders of magnitude | 🧠 inferred (loop shape) |
| Full materialisation | full set in heap | window-bounded | ~10-100× peak memory | 📊 explicit + 🧠 projection |

Exact wall-clock savings need a benchmark (off by default, §7); the O(n²)→O(n·k) reduction is
🧠 inferred and expected to be transformative, not incremental.
