---
name: SQL Issues
model: sonnet
applies_to: ["*.sql"]
---

> Lens structure follows **turingmind-code-review** (MIT, © 2026 TuringMind). See THIRD-PARTY-LICENSES.md.

Language-specific checks for SQL — queries, views, stored procedures and embedded SQL. SQL is
everywhere in surveillance (TM/trade detection, reconciliation, MI), so correctness and scale
here directly affect whether alerts are right and whether jobs finish.

## Checks

### Security
- **Injection** (CWE-89) — string-built/interpolated SQL instead of parameterised/bound queries;
  dynamic SQL (`EXEC`/`sp_executesql`/`format()`) over untrusted input.
- **Least privilege** — DDL/`GRANT`, `DELETE`/`TRUNCATE` without scope; broad service-account rights.
- **Data exposure (§5)** — PII/MNPI columns in `SELECT *`, in logs, or in error/debug output.

### Correctness (gets detection wrong silently)
- **NULL handling** — `=`/`<>` vs `IS NULL`; `NOT IN (… NULL …)` returning no rows; `COUNT(col)`
  skipping NULLs unexpectedly.
- **JOIN fan-out** — many-to-many joins inflating counts/sums (double-counted alerts); missing
  join keys → accidental cross join.
- **GROUP BY / aggregation** — columns not grouped/aggregated; `HAVING` vs `WHERE`; averaging averages.
- **Window functions** — wrong `PARTITION BY`/`ORDER BY` or frame (`ROWS` vs `RANGE`) for
  running totals / lookbacks in a detection.
- **Time windows & timezones** — boundary errors (inclusive/exclusive), naive vs tz-aware
  timestamps, DST — a common source of missed/false alerts.

### Performance (at surveillance volumes)
- **Non-sargable predicates** — functions on indexed columns (`WHERE CAST(ts)…`), leading-wildcard
  `LIKE`, implicit type coercion defeating indexes.
- **Full scans / missing indexes** — check the `EXPLAIN`/plan; large `IN (…)` lists; `SELECT *`
  pulling wide rows; `DISTINCT`/`ORDER BY` spills.
- **N+1 / per-row subqueries** — correlated subqueries that should be a join or window.

## Output

Use the shared format in `docs/review/output-format.md`: `file:line`, confidence, **evidence
basis** (📊 measured — e.g. an `EXPLAIN ANALYZE` plan you ran — vs 🧠 inferred from the query
shape), and a `diff`-style fix + "why this works". Defer §4/§5 (auditability of the detection
SQL, data handling) to `compliance-reviewer`.
