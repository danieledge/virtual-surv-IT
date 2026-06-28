# Operational Runbook / Support Handover - <TITLE>

> **Drafted by the virtual team** for your operations/support function. Items marked
> **[IT team]** (contacts, alert thresholds, escalation, schedules) are for your team to set
> against your tooling and standards. Authored in `.md`, rendered to `.html`.

> **Document control** · ID `RUN-001` · Version `0.1` · Status `Draft | In review | Approved`
> · Classification `Internal | Confidential` · Owner `<name / role>` · As-of `<YYYY-MM-DD>`
>
> | Version | Date | Author | Change |
> |---|---|---|---|
> | 0.1 | <YYYY-MM-DD> | <author> | Initial draft |

| | |
|---|---|
| **Service / component** | <...> |
| **Version** | <...> |
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
[IT team] - complete against your standards and DR policy.

| Field | Value |
|---|---|
| **RTO (Recovery Time Objective)** | [IT team - maximum tolerable downtime before service must be restored] |
| **RPO (Recovery Point Objective)** | [IT team - maximum tolerable data loss; e.g. last good batch, last committed offset] |
| **Backup frequency / method** | [IT team] |
| **Recovery procedure** | [IT team - step-by-step restore; link runbook if separate] |
| **DR test cadence** | [IT team] |
| **Last DR test date / result** | [IT team] |

> Note for surveillance: an RTO or RPO breach may itself constitute a compliance event (gap in
> surveillance coverage). Ensure your DR targets are agreed with the compliance function and
> recorded in your surveillance-coverage assurance framework.

## Sign-off
| Role | Name | Decision | Date |
|------|------|----------|------|
| Author / owner | | | |
| `compliance-reviewer` (DoD gate) | | | |
| Human approver (or `[IT team]`) | | | |
