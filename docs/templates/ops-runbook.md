# Operational Runbook / Support Handover - <TITLE>

> **Drafted by the virtual team** for your operations/support function. Items marked
> **[IT team]** (contacts, alert thresholds, escalation, schedules) are for your team to set
> against your tooling and standards. Authored in `.md`, rendered to `.html`.

| | |
|---|---|
| **Service / component** | <…> |
| **Version** | <…> |
| **Owner (team)** | [IT team] |
| **Date** | <YYYY-MM-DD> |

## 1. What it does & how it runs
Purpose, and how it executes - batch/streaming, schedule/trigger, where it runs.

## 2. Architecture & dependencies
Components, data flow, upstream/downstream systems, and external dependencies.

## 3. Configuration
Key config and environment variables (**secrets via your secrets manager - never in code**).

## 4. Monitoring & alerting
- **What to watch:** health signals, throughput, lag, error rates, and - critically for
  surveillance - **alert-generation liveness** (silent failure = compliance risk).
- **Suggested metrics / SLOs:** <draft>
- **Alert thresholds & destinations:** [IT team to wire to your monitoring]

## 5. Common failure modes & recovery
| Symptom | Likely cause | Action / recovery |
|---------|--------------|-------------------|
| | | |

## 6. Routine operations
Start/stop, reprocessing/backfill, retention/archival, and any periodic tuning cadence.

## 7. Data handling
Inputs/outputs, classification, and where masking/synthetic data applies (CLAUDE.md §5).

## 8. Escalation & contacts - [IT team]
| Tier | Who | When |
|------|-----|------|
| L1 / on-call | | |
| L2 / engineering | | |
| Compliance contact | | |

## 9. Backup / recovery & DR
[IT team] - recovery objectives and procedures per your standards.
