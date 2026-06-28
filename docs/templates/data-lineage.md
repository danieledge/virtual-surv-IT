# Data Lineage - <FEED / PROGRAMME>

> Produced by `platform-engineer` or `data-analyst`; reviewed by `data-quality-reviewer`.
> Documents the end-to-end lineage of each surveillance data feed: source system through
> transformation to the detection scenario(s) consuming it. Supports feed-completeness and
> coverage assurance, and satisfies RTS 25 timestamp-granularity requirements.

> **Document control** · ID `LIN-001` · Version `0.1` · Status `Draft | In review | Approved`
> · Classification `Internal` · Owner `<platform-engineer / data owner>` · As-of `<YYYY-MM-DD>`
>
> | Version | Date | Author | Change |
> |---|---|---|---|
> | 0.1 | <YYYY-MM-DD> | <author> | Initial draft |

---

## Scope

| Field | Value |
|---|---|
| Programme | <e.g. Trade Surveillance / AML TM> |
| Feeds in scope | <list feed names> |
| Scenarios consuming these feeds | <list scenario IDs> |
| As-of date | <YYYY-MM-DD> |

---

## Feed inventory

| Feed ID | Feed name | Source system | Owner (team) | Frequency | Format | Classification |
|---|---|---|---|---|---|---|
| FEED-001 | <e.g. order events> | <e.g. OMS - Fidessa> | <team> | <real-time / T+0 batch / T+1> | <FIX / CSV / Avro> | `Internal` / `Confidential` |
| FEED-002 | | | | | | |

---

## Field-level lineage

One section per feed. For each field, trace: source -> ingestion -> transformation -> target field
consumed by detection.

### FEED-001: <Feed name>

| Source field | Source type | Ingestion step | Transformation applied | Target field (detection layer) | Scenarios consuming |
|---|---|---|---|---|---|
| <e.g. OrderTimestamp> | `datetime` | Raw ingest - scripts.ingest | Normalise to UTC; truncate to microseconds | `order_ts` | FSD-001, FSD-004 |
| <e.g. Quantity> | `decimal(18,6)` | Raw ingest | Cast to float; fill null = 0 | `order_qty` | FSD-001 |
| <field 3> | | | | | |

**Timestamp granularity (RTS 25 check)**

| Event type | Source granularity | Normalised granularity | RTS 25 requirement | Compliant? |
|---|---|---|---|---|
| <e.g. Order received> | <microseconds> | <microseconds UTC> | 1 microsecond (Annex I) | Yes / No - gap noted |

---

## Completeness and SLA

| Feed ID | Expected volume (daily / per batch) | Completeness threshold | Reconciliation point | SLA - delivery deadline | Breach action |
|---|---|---|---|---|---|
| FEED-001 | <e.g. 95% of exchange session trades> | >= 99% records received | `data/reconciliation/feed001_recon` | <T+0 17:00 UTC> | Alert `data-quality-reviewer`; hold alerts until gap resolved |

---

## Reconciliation points

| Recon ID | Feed(s) | Recon method | Frequency | Owner | Last run | Outcome |
|---|---|---|---|---|---|---|
| RECON-001 | FEED-001 | Count + checksum vs source extract | Daily T+1 | `data-quality-reviewer` | <YYYY-MM-DD> | <pass / fail / partial - N records missing> |

---

## Data quality issues log

| # | Feed | Issue description | Discovered | Impact on scenarios | Status | Remediated |
|---|---|---|---|---|---|---|
| DQ-001 | FEED-001 | <e.g. Timestamp missing for 0.3% orders on 2026-01-15> | <YYYY-MM-DD> | FSD-001 - potential missed alerts | `Open` / `Closed` | <YYYY-MM-DD or N/A> |

---

## Open items

| # | Item | Owner | Target date | Status |
|---|---|---|---|---|
| L1 | <e.g. Microsecond normalisation not yet applied for FEED-002> | `platform-engineer` | <YYYY-MM-DD> | `Open` |

---

## Sign-off
| Role | Name | Decision | Date |
|------|------|----------|------|
| Author / owner | | | |
| `compliance-reviewer` (DoD gate) | | | |
| Human approver (or `[IT team]`) | | | |
