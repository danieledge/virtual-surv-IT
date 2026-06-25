# Process Map - <PROCESS NAME>

> Produced by `business-analyst` (BPMN-style). Captures current- and target-state flow,
> actors, decisions, controls and hand-offs for a surveillance process. Authored in `.md`,
> rendered to `.html`. Synthetic illustrations only - no real data (§5).

| | |
|---|---|
| **Document ID** | PRC-<slug> |
| **Process owner** | <role> |
| **Author / owner** | business-analyst / <user> |
| **Version / date** | 0.1 / <YYYY-MM-DD> |
| **Trigger** | <event that starts the process> |
| **Outcome** | <what "done" looks like> |

## 1. Overview
One paragraph: what the process does and why it exists (link the obligation it supports, §2 -
e.g. alert triage feeding SAR/STR decisioning).

## 2. Actors / swimlanes
| Lane | Actor / system | Responsibility in this process |
|------|----------------|--------------------------------|
| 1 | Data feed / ingestion | deliver masked, complete data |
| 2 | Detection engine | run scenarios, raise alerts |
| 3 | Surveillance analyst | triage, escalate or close |
| 4 | MLRO / Compliance | decision & regulatory filing |

## 3. Current-state (as-is) steps
| # | Step | Lane | Input → Output | Pain point / risk |
|---|------|------|----------------|-------------------|
| 1 | <step> | <lane> | … | <manual / gap / delay> |

## 4. Target-state (to-be) steps
| # | Step | Lane | Input → Output | Change vs as-is |
|---|------|------|----------------|-----------------|
| 1 | <step> | <lane> | … | <automated / new control> |

## 5. Target-state diagram (Mermaid)
Replace the placeholder nodes with the real flow; keep decisions as diamonds and controls
annotated.
```mermaid
flowchart TD
    A([Trigger: <event>]) --> B[Ingest & mask data]
    B --> C{Data complete?}
    C -- No --> X[/Raise data-quality exception/]
    C -- Yes --> D[Run detection scenarios]
    D --> E{Alert raised?}
    E -- No --> Z([End - no action])
    E -- Yes --> F[Analyst triage]
    F --> G{Escalate?}
    G -- No --> H[Close with rationale]
    G -- Yes --> I[MLRO review → SAR/STR decision]
    I --> Z
```

## 6. Decision points
| ID | Decision | Criteria | Outcomes |
|----|----------|----------|----------|
| D1 | Data complete? | reconciliation pass | proceed / exception |
| D2 | Escalate alert? | typology + materiality | close / escalate |

## 7. Exceptions & error paths
| Exception | Detected at | Handling | Owner |
|-----------|-------------|----------|-------|
| Missing feed | ingestion | block + alert ops | IT team |
| Late data | batch window | reprocess | platform-engineer |

## 8. Controls in the flow
| Control | Step | Type (preventive/detective) | Obligation (§2) |
|---------|------|-----------------------------|-----------------|
| Reconciliation check | step 1 | detective | FCA SYSC record-keeping |
| Alert audit trail | triage | detective | MAR / SR 11-7 |

## 9. Hand-offs
| From → To | What is handed over | SLA / trigger |
|-----------|---------------------|---------------|
| Detection → Analyst | alert + evidence | on raise |
| Analyst → MLRO | escalation pack | on escalate |

> Traceability: process steps and controls map to FSD functional requirements and RTM rows;
> data-quality exceptions feed the data requirements in the elicitation doc.
