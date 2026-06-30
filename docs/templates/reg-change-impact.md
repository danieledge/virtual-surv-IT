# Regulatory-Change Impact Assessment - <CHANGE NAME>

> Produced by `business-analyst` with the relevant SME (`tm-sme` / `trade-surveillance-sme` /
> `comms-surveillance-sme`). Assesses what a changed obligation means for scenarios, controls,
> data and specs. Authored in `.md`, rendered to `.html`. Synthetic illustrations only - no
> real data (§5).

> **Document control** · ID `RCI-001` · Version `0.1` · Status `Draft | In review | Approved`
> · Classification `Internal | Confidential` · Owner `<name / role>` · As-of `<YYYY-MM-DD>`
>
> | Version | Date | Author | Change |
> |---|---|---|---|
> | 0.1 | <YYYY-MM-DD> | <author> | Initial draft |

| | |
|---|---|
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

## 5. Risk register
Structured risk register for delivery of this change. Assess each risk before the change plan
is agreed.

| ID | Risk | Probability (H/M/L) | Impact (H/M/L) | Mitigation | Owner | Residual risk |
|----|------|---------------------|----------------|------------|-------|---------------|
| RISK-001 | <e.g. feed change delayed beyond effective date> | M | H | <e.g. interim manual review of affected population> | <platform-engineer / IT> | M |
| RISK-002 | <e.g. SME interpretation ambiguous - wrong detection scope> | L | H | <e.g. legal/compliance sign-off on obligation read before build> | <business-analyst / SME> | L |

## 6. Interim-control table
Where a gap will not be closed before the effective date, document the interim control.
Each row must have a named owner and a planned retire date (the date the permanent control
goes live). This table is reviewed at every change-plan gate until all rows are retired.

| Gap / RISK-ID | Interim control | Control owner | Retire date (target) | Review cadence |
|---------------|-----------------|---------------|----------------------|----------------|
| <e.g. RISK-001 - feed delay> | <e.g. manual daily review of OMS exceptions by senior analyst> | <Head of Surveillance> | <YYYY-MM-DD> | Weekly until retired |

## 7. Prioritised change plan
| ID | Change | Owner | Priority | Target date | Depends on |
|----|--------|-------|----------|-------------|------------|
| CHG-001 | <build/amend> | rules-developer | Must | <≤ effective date> | data feed |
| CHG-002 | re-tune thresholds | data-analyst / tuning-analyst | Must | … | CHG-001 |
| CHG-003 | feed / pipeline change | platform-engineer | Should | … | |
| CHG-004 | update specs & RTM | business-analyst | Must | … | |

## 8. Risk & timeline
Overall delivery risk vs. the effective date, key dependencies, and a recommendation
(e.g. phased delivery, interim manual control). **Close with next-step options** - never a
dead end.

## 9. Lessons - house-rules prompt
After each regulatory-change engagement, capture recurring patterns and pitfalls for
`docs/house-rules.md`. Prompt: did any requirement pattern, elicitation gap, or control
mapping recur that should be standardised? Record it here before the engagement closes.

| Lesson | Category (elicitation / req pattern / control mapping / other) | Proposed house-rule |
|--------|----------------------------------------------------------------|---------------------|
| <e.g. feed-change lead time always underestimated> | elicitation | <add feed-readiness check to intake checklist> |

**Disposition tally:** ✅ _N_ Fixed/Answered · 🔴 _N_ Open · ⏭️ _N_ Deferred/Needs-input · ⚖️ _N_ Accepted - across the impacted scenarios/controls in §7. *(Severity / disposition / evidence-basis legends: see `docs/WAYS-OF-WORKING.md`.)*

## 10. Sign-off
| Role | Name | Decision | Date |
|------|------|----------|------|
| SME | | | |
| Head of Surveillance / MLRO | | | |
| `compliance-reviewer` (DoD gate) | | | |
| Human approver (or `[IT team]`) | | | |

> Traceability: every CHG-### lands as a BRD/FSD/RTM update and is verified by
> `compliance-reviewer` against the cited obligation before handover.
