# Gold-standard findings - worked exemplars of the required shape

> **Anchor on these before writing findings.** The shape is specified in
> [`output-format.md`](output-format.md); these are known-good *instances* of it, because a
> generator anchored on a concrete exemplar drifts less than one following rules alone.
> Both are fully synthetic. The test of a good finding: **a reader who was not in the
> session and did not write the code understands what is wrong, why it happened, why it
> matters, and what to do - without asking a follow-up question.**

## Exemplar 1 - code-review finding (canonical block shape, the 5 C's)

### 🔴 Position-limit query built by string concatenation (SQL injection)
**Location:** `position_limit_check.py:17`  ·  **Confidence:** 97/100  ·  **Basis:** 📊 measured (semgrep `python.lang.security.audit.formatted-sql-query` + read confirmation)
**Standard:** CWE-89 / OWASP ASVS V5.3.4

**Problem:** The instrument name is concatenated directly into the SQL string. Any caller
(or upstream data) that controls `instrument` controls the query - a value like
`EQ-ACME' OR '1'='1` changes what the check returns.

**Likely cause:** The query began as a fixed two-instrument loop where the input *felt*
trusted; the parameterised form was never introduced when the function was generalised
(spec drift, not intent).

**Impact if unaddressed:** A crafted instrument value can make the breach check return
**no rows** - a silent false negative on the position-limit control itself. Because output
feeds the nightly breach report, a suppressed breach would be invisible to supervision
(audit exposure: the control exists on paper but is defeatable). 🧠 projected - no evidence
of exploitation; the mechanism is measured.

**Fix:**
```diff
-    query = (
-        "SELECT account_id, net_position, limit_value FROM positions p "
-        "JOIN limits l ON l.instrument = p.instrument "
-        "WHERE p.instrument = '" + instrument + "' AND p.net_position > l.limit_value"
-    )
-    rows = conn.execute(query).fetchall()
+    query = (
+        "SELECT account_id, net_position, limit_value FROM positions p "
+        "JOIN limits l ON l.instrument = p.instrument "
+        "WHERE p.instrument = ? AND p.net_position > l.limit_value"
+    )
+    rows = conn.execute(query, (instrument,)).fetchall()
```
*Why this works:* the driver binds `instrument` as data, never as SQL - the query's
structure can no longer be altered by the value.

**Status:** Open

## Exemplar 2 - requirements-assessment verdict (the six-part shape, `/beta-assess-quantexa` step 3)

**REQ-D-014 - per-venue lookback window · Verdict: PARTIAL**

1. **Expected:** TSD §5.3 (v2.1): the layering detection applies a *per-venue* lookback
   window, configurable without code change, defaulting to 120s.
2. **Found:** 📊 The scorer reads a single global `lookback.seconds` from the scoring
   config (`scoring.conf` key `detection.layering.lookback`, observed at commit `4e91c2a`);
   no per-venue override key exists, and the venue field is unused in the window logic
   (`LayeringScorer.scala:88-104`).
3. **Why this is an issue:** the implementation satisfies "configurable" but not
   "per-venue" - every venue shares one window, so the TSD's venue-specific calibration
   cannot be expressed at all, not merely "isn't configured yet".
4. **Likely cause:** the TSD gained the per-venue clause at v2.1 (change log, 2026-03);
   the scorer predates it and was not updated - spec drift, not a coding error.
5. **Potential impact if unaddressed:** 🧠 venues with slower book dynamics keep a window
   tuned for the fastest venue - projected effect is missed layering sequences on slower
   venues (false negatives) or noise on faster ones (alert volume), direction depending on
   the calibrated value. Magnitude unquantified: needs ATL/BTL evidence per venue.
6. **Recommended action:** code + config change (add per-venue override keyed by venue MIC,
   fall back to global default), then re-run venue-level BTL sampling; TSD unchanged.

## What makes these "gold" (the checkable properties)

- Every factual claim is **cited** (file:line, config key, commit, TSD §) and **tagged** 📊/🧠.
- **Cause is present** even when it is an informed reconstruction - and says so.
- **Impact is in the domain's terms** (false negatives, alert volume, audit exposure), tagged
  🧠 when projected, honest about magnitude.
- The fix/action is **concrete and routed** - a diff or a named change type, never "improve this".
- No unglossed jargon; nothing depends on having been in the session.
