# Elicitation & Requirements - TS-002 Layering Detection *(worked example)*

> **Worked example** of the clarification-rounds capability (operating guide, Outcome
> discipline 5). Fictional engagement, synthetic throughout - illustrates the *shape*, not a
> real delivery. Companion examples: [`qa-handover-example.md`](qa-handover-example.md),
> [`delivery-report-example.md`](delivery-report-example.md).

> **Document control** · ID `ELC-002` · Version `0.3` · Status `Approved`
> · Classification `Internal` · Owner `business-analyst / Morgan (PM)` · As-of `2026-07-19`
>
> | Version | Date | Author | Change |
> |---|---|---|---|
> | 0.1 | 2026-07-19 | business-analyst | Initial draft from intake |
> | 0.2 | 2026-07-19 | business-analyst | Round 1 answered (tm-sme): per-asset-class thresholds → §6 rewritten |
> | 0.3 | 2026-07-19 | business-analyst | Round 2 answered (user via Morgan): equities-only venue scope → §2 narrowed |

## 1. Context & regulatory driver
Detect **layering** (MAR Art. 12(1)(a); FCA MW69 expects typology- and asset-class-specific
calibration): non-bona-fide orders on one side of the book to move the touch, with genuine
executions on the opposite side.

## 2. Scope
Equities on venue set `XLON`/`XETR` only (Round 2 decision - see register). Order-level data
including cancels/amends; **out of scope:** cross-product spoof-and-trade (tracked as a
watch item for a TS-003).

## 5. Business requirements (EARS) *(excerpt)*
| ID | Requirement | Priority |
|----|-------------|----------|
| REQ-B-001 | When a participant places and cancels non-marketable orders on one side while executing on the other within the detection window, the system shall raise a layering alert | Must |
| REQ-B-002 | The system shall apply per-asset-class thresholds, configurable without code change | Must |

## 6. Functional / detection requirements *(excerpt)*
| ID | Requirement | Traces to |
|----|-------------|-----------|
| REQ-F-001 | Detection window: 120s rolling (Round 1: tm-sme - liquid equities baseline; document per-venue override) | REQ-B-001 |
| REQ-F-002 | Cancel-ratio threshold ≥ 0.8 on the non-genuine side, min 5 orders (Round 1) | REQ-B-001 |

## 10. Clarification rounds & open questions
Material unknowns the PM is clarifying with the user or an SME (never guessed). **The rounds
are the audit trail of how the spec evolved - append-only, one row per question raised**, so
"v0.3" is traceable to *which answer changed which section*. Unanswered rounds stay visibly
open; they never dissolve.

| Round | Date | Question (raised by) | Answered by | Answer (summary) | Spec change (section · version) | Status |
|-------|------|----------------------|-------------|------------------|---------------------------------|--------|
| 1 | 2026-07-19 | Single global threshold or per-asset-class? Window length? (`business-analyst`) | `tm-sme` | Per-asset-class, config-driven; 120s window for liquid equities, venue override documented | §5 REQ-B-002, §6 REQ-F-001/002 · v0.2 | ✅ answered |
| 2 | 2026-07-19 | Venue scope: all equities venues or the two primary? (`business-analyst`) | user (via Morgan) | XLON + XETR only for this phase | §2 · v0.3 | ✅ answered |
| 3 | 2026-07-19 | Production alert-volume ceiling for calibration? (`tuning-analyst`) | - | - | - | ⏭️ needs deployment input (real volumes) |

> Traceability: REQ-B/F-### flow into the FSD and the RTM: BRD → FSD → code → test →
> obligation.

## Sign-off
| Role | Name | Decision | Date |
|------|------|----------|------|
| Author / owner | business-analyst | Drafted | 2026-07-19 |
| `compliance-reviewer` (DoD gate) | compliance-reviewer | Rounds register complete; R3 correctly deferred | 2026-07-19 |
| Human approver | *(example - unsigned)* | | |
