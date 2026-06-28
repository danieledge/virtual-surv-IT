# Comms Surveillance Lexicon Specification - <LEXICON / RISK NAME>

> Produced by `business-analyst` with `comms-surveillance-sme`. Specifies and governs a comms
> lexicon / risk-flag set for e-comms and voice monitoring. Terms and examples use
> **synthetic/masked data only** - never paste real comms (§5). Authored in `.md`, rendered to
> `.html`. NLP/risk-model build is owned by `ml-engineer` (then `model-validator`); this is the
> specification, not the production model.

> **Document control** · ID `LEX-001` · Version `0.1` · Status `Draft | In review | Approved`
> · Classification `Internal | Confidential` · Owner `<name / role>` · As-of `<YYYY-MM-DD>`
>
> | Version | Date | Author | Change |
> |---|---|---|---|
> | 0.1 | <YYYY-MM-DD> | <author> | Initial draft |

| | |
|---|---|
| **Lexicon / risk** | <name> |
| **Conduct targeted** | <e.g. insider dealing, collusion, mis-selling, off-channel solicitation> |
| **Channels** | <email / chat / voice-to-text / social> |
| **Jurisdiction(s)** | <applicable regime(s)> |
| **Date / author** | <YYYY-MM-DD> |

## 1. Risk / behaviour targeted
The conduct this lexicon is meant to surface, in plain terms, and the obligation it supports
(cite the article/rule, CLAUDE.md §2 - e.g. market abuse detection under **MAR**; comms recording
under **MiFID II Art 16(7)** / CDR (EU) 2017/565 Art 76, or US **17a-4 / FINRA 4511** - *citations
verified, see the comms-surveillance policy §3*).

> *Note: the lexicon **design/tuning practice** below (term selection, scoring, FP reduction) is
> grounded in industry practice, not yet verified against a primary source - treat as guidance.*

## 2. Terms & phrases
Each term with rationale, language, channel, and per-term hit-rate and FP-rate from the most
recent calibration run. No opaque keyword lists. A term with a hit-rate above threshold but
FP-rate above target is a candidate for exclusion refinement or weight reduction.

| Term / phrase | Rationale (why it signals risk) | Language | Channel(s) | Match type (exact / stem / regex / proximity) | Hit rate (per 1k msgs) | FP rate (% of hits reviewed) | Last calibrated |
|---|---|---|---|---|---|---|---|

## 3. Scoring / weighting
How term hits combine into an alert score - weights, proximity/co-occurrence boosts, thresholds.
Record the rationale for each weight (§4).

## 4. NLP / risk-model notes
Beyond keywords - negation handling, context windows, sentiment/intent classification,
multilingual handling, voice-to-text confidence. Note model dependencies for `ml-engineer`.

## 5. Expected performance
Target **precision** and **recall**, the basis for the estimate, and the evaluation set
(synthetic/masked). State the precision/recall trade-off chosen and why.

## 6. False-positive drivers & exclusions
Known benign sources of hits (idioms, product names, trader jargon) and the exclusion rules /
allow-lists that suppress them without creating coverage gaps.

## 7. Review & governance cadence
Who owns the lexicon, how often it is reviewed, the change-control process, and the trigger
events (new products, new slang, reg change) that force an out-of-cycle review.

## 7a. ATL / BTL calibration
Before finalising term weights and the alert threshold, run an ATL/BTL calibration on a
synthetic/masked sample. This prevents the lexicon from being set by intuition rather than evidence.

**ATL (Above-The-Line) - precision among flagged messages:**
- Sample N messages flagged at the candidate threshold.
- Label each: true positive (risk conduct genuinely present) or false positive (benign hit).
- Record precision = TP / (TP + FP) per term and in aggregate.

**BTL (Below-The-Line) - coverage just below the threshold:**
- Sample N messages with a score just below the alert threshold (e.g. within 10% of threshold).
- Label each: does any genuine risk conduct appear in the near-miss population?
- Record the missed-conduct rate and whether it indicates a threshold that is too high.

| Calibration window | Sample size (ATL) | Precision (ATL) | Sample size (BTL) | Missed-conduct rate (BTL) | Threshold verdict | Date |
|---|---|---|---|---|---|---|
| <period; synthetic/masked> | <n> | <%> | <n> | <%> | <hold / lower / raise> | <YYYY-MM-DD> |

## 8. Hand-off
SME review: `comms-surveillance-sme`. Build: `ml-engineer` → independent `model-validator`.
Tuning: `tuning-analyst`. Coverage feeds the Comms Surveillance Policy & Coverage Assessment.

## Sign-off
| Role | Name | Decision | Date |
|------|------|----------|------|
| Author / owner | | | |
| `compliance-reviewer` (DoD gate) | | | |
| Human approver (or `[IT team]`) | | | |
