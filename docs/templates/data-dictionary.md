# Data Dictionary - <DATASET / FEED>

> Produced by `data-analyst`. The authoritative field-level reference for a dataset/feed feeding
> surveillance - what each field means, where it comes from, how it's classified and masked.
> Documents **synthetic/masked data only - no real PII/MNPI** (§5); masking treatment per
> `config/masking-schema.yaml`. Authored in `.md`, rendered to `.html`. Aligns to DAMA-DMBOK
> metadata-management practice.

> **Document control** · ID `DD-001` · Version `0.1` · Status `Draft | In review | Approved`
> · Classification `Internal | Confidential` · Owner `<name / role>` · As-of `<YYYY-MM-DD>`
>
> | Version | Date | Author | Change |
> |---|---|---|---|
> | 0.1 | <YYYY-MM-DD> | <author> | Initial draft |

| | |
|---|---|
| **Dataset / feed** | <logical name; what surveillance use it serves (§2)> |
| **Owner / steward** | <data owner · data steward> |
| **Source system(s)** | <originating system(s) of record> |
| **Refresh / latency** | <batch nightly / streaming; expected latency> |
| **Lineage pointer** | <link to pipeline/ETL job + masking config: `config/masking-schema.yaml`> |
| **Date / author** | <YYYY-MM-DD · data-analyst> |
| **Timestamp granularity** | <microsecond / millisecond / second / date> |
| **Clock-sync standard** | <MiFID II RTS 25 compliant? Gateway clock accuracy (e.g. <=1 ms from UTC); HFT venues require microsecond; note any known drift or gaps> |

## 1. Dataset overview
One paragraph: grain (one row per …), key, expected volume, and the in-scope surveillance
domain(s) (TM / trade / comms). Note the masked-vs-source relationship (this dictionary
describes the **masked** dataset agents see).

## 2. Field definitions
One row per field. **PII/MNPI** classifies the *source* value; **masking treatment** is the role
applied per `config/masking-schema.yaml` (`token` / `shift` / `keep` / dropped). Example values
are **synthetic** only.

| Field | Source / system | Type | Description | Allowed values / domain | PII/MNPI | Masking treatment | Nullable | Example (synthetic) |
|---|---|---|---|---|---|---|---|---|
| `<field>` | `<system.table.col>` | string | <what it means> | <enum / range / regex> | none / PII / MNPI | token(domain) / shift / keep / dropped | N | `<synthetic>` |
| `<field>` | `<...>` | timestamp(ms) | <event time> | epoch ms | indirect | shift(entity) - deltas preserved | N | `<synthetic>` |
| `<field>` | `<...>` | decimal | <signal value> | > 0 | none (signal) | keep | N | `<synthetic>` |

## 3. Keys & relationships
Primary key, foreign keys / join keys to other datasets, and which token `domain` preserves
referential integrity across feeds (e.g. `party`, `order`, `instrument`).

| Key | Type | Fields | Joins to | Token domain |
|---|---|---|---|---|

## 4. Data-quality expectations
The rules a feed-validation/DQ job should enforce - completeness, uniqueness, range, referential
integrity, timeliness. Ties to any reconciliation job and surveillance coverage.

Severity scale (use consistently; do not rely on emoji alone):
- 🔴 Critical - breach silently disables a detection scenario or creates a regulatory exposure; escalate immediately.
- 🟠 High - material coverage or accuracy gap; resolve within SLA or escalate.
- 🟡 Medium - quality degraded but detection not fully blocked; log and track.
- 🔵 Low - cosmetic or informational; record and review at next cycle.

| Field / rule | Expectation | Severity if breached |
|---|---|---|

## 5. Notes & open questions
Ambiguous fields, deprecated columns, fields dropped by `on_unknown: drop`, and anything needing
sign-off from the data owner before downstream use.

## Sign-off
| Role | Name | Decision | Date |
|------|------|----------|------|
| Author / owner | | | |
| `compliance-reviewer` (DoD gate) | | | |
| Human approver (or `[IT team]`) | | | |
