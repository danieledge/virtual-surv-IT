# Regulatory-Change Impact Assessment - <CHANGE NAME>

> Produced by `business-analyst` with the relevant SME (`tm-sme` / `trade-surveillance-sme` /
> `comms-surveillance-sme`). Assesses what a changed obligation means for scenarios, controls,
> data and specs. Authored in `.md`, rendered to `.html`. Synthetic illustrations only - no
> real data (§5).

| | |
|---|---|
| **Document ID** | RCI-<slug> |
| **Author / owner** | business-analyst / <user> |
| **Version / date** | 0.1 / <YYYY-MM-DD> |
| **Status** | draft / assessed / planned |
| **Effective date** | <YYYY-MM-DD> |
| **Jurisdiction(s)** | <EU / UK / US / SG / HK / JP> |

## 1. The change
What changed (new/amended obligation, guidance, RTS/ITS, enforcement signal), source citation,
effective/transition date, and jurisdictions affected (§2).

## 2. Obligation read (SME)
The SME's plain-English interpretation: what the obligation now requires, what is new vs.
existing, and any ambiguity. Cite the specific article/rule (e.g. MAR Art.x, 6AMLD,
FCA SYSC, SEC 17a-4).

| Obligation | Old requirement | New requirement | Net change |
|------------|-----------------|-----------------|------------|
| <ref> | … | … | new / tightened / relaxed |

## 3. Affected items (traced)
Walk the traceability spine outward from the obligation. Mark each item's impact.

| Type | Item | Impact (new / change / retire / none) | Notes |
|------|------|---------------------------------------|-------|
| Scenario / rule | `rules/<x>.py` | change | threshold + logic |
| Control | <control in process map> | new | |
| Data feed | <feed> | change | new field required |
| Spec / requirement | REQ-/FSD-### | change | |
| Threshold | <param> | change | re-tune needed |

## 4. Gap assessment
Where the current solution does **not** yet meet the new obligation, and the risk of the gap
(regulatory exposure, undetected abuse, audit finding).

| Gap | Current state | Required state | Risk if unaddressed |
|-----|---------------|----------------|---------------------|
| <…> | … | … | High / Med / Low |

## 5. Prioritised change plan
| ID | Change | Owner | Priority | Target date | Depends on |
|----|--------|-------|----------|-------------|------------|
| CHG-001 | <build/amend> | rules-developer | Must | <≤ effective date> | data feed |
| CHG-002 | re-tune thresholds | data-analyst / tuning-analyst | Must | … | CHG-001 |
| CHG-003 | feed / pipeline change | platform-engineer | Should | … | |
| CHG-004 | update specs & RTM | business-analyst | Must | … | |

## 6. Risk & timeline
Overall delivery risk vs. the effective date, key dependencies, and a recommendation
(e.g. phased delivery, interim manual control). **Close with next-step options** - never a
dead end.

## 7. Sign-off
| Role | Name | Decision | Date |
|------|------|----------|------|
| SME | | | |
| Head of Surveillance / MLRO | | | |

> Traceability: every CHG-### lands as a BRD/FSD/RTM update and is verified by
> `compliance-reviewer` against the cited obligation before handover.
