# SAR/STR Referral Pack - <SUBJECT REF / CASE ID>

> Produced by the compliance / second-line team on the basis of an escalated alert investigation.
> The referral pack handed to compliance for filing or not-filing a Suspicious Activity Report
> (SAR) or Suspicious Transaction Report (STR). Synthetic identifiers only - no real PII (§5).

> **Document control** · ID `SAR-001` · Version `0.1` · Status `Draft | In review | Approved`
> · Classification `Confidential` · Owner `<compliance officer / MLRO>` · As-of `<YYYY-MM-DD>`
>
> | Version | Date | Author | Change |
> |---|---|---|---|
> | 0.1 | <YYYY-MM-DD> | <author> | Initial draft |

---

## 1. Subject(s)

All identifiers are synthetic or masked (§5 - no real PII in this artifact).

| Field | Value |
|---|---|
| Subject ref | <SUBJ-001 - synthetic> |
| Relationship type | <e.g. client / employee / counterparty> |
| Account ref(s) | <ACC-001, ACC-002 - masked> |
| Jurisdiction | <country / regulatory regime> |

---

## 2. Activity summary

A factual, chronological narrative of the activity giving rise to suspicion. Plain language;
no conclusions in this section - those belong in section 4. Dates, amounts and instruments
must use masked/synthetic values.

<Narrative - 3-10 sentences>

---

## 3. Reasons for suspicion - the legal trigger

The reasonable grounds for suspicion that trigger the reporting obligation. Cite the specific
legal basis (e.g. POCA 2002 s.330 / MLD5 Art.33 / FinCEN 31 CFR 1020.320). Each ground
must be stated as a factual observation, not an assertion.

- Ground 1: <factual observation>
- Ground 2: <factual observation>
- Ground 3: <if applicable>

Regulatory basis for reporting: <cite article / rule>

---

## 4. Supporting documents

| # | Document | Reference / masked ID | Date | Relevance |
|---|---|---|---|---|
| 1 | Alert investigation record | AINV-<NNN> | <YYYY-MM-DD> | Source alert |
| 2 | <e.g. transaction records> | <masked ref> | <YYYY-MM-DD> | <one line> |
| 3 | <e.g. communications evidence> | <masked ref> | <YYYY-MM-DD> | <one line> |

---

## 5. Filing decision

| Field | Value |
|---|---|
| Decision | `File SAR/STR` / `Do NOT file - insufficient grounds` / `Defer - further information required` |
| Rationale | <paragraph - the legal and factual basis for the decision> |
| Decision maker | <name / MLRO> |
| Date of decision | <YYYY-MM-DD> |

### 5a. If filing
| Field | Value |
|---|---|
| Filing reference | <regulator-assigned reference, once filed> |
| Date filed | <YYYY-MM-DD> |
| Filed with | <FCA / FinCEN / AUSTRAC / etc.> |
| Tipping-off controls applied | Yes / No - <brief note> |

### 5b. If not filing
State clearly why the legal threshold for filing was not met. This rationale is itself a
required retention record (CDR 2016/957 Art.3(8) / equivalent).

<Rationale for not filing>

---

## 6. Retention note

The decision to file or not to file, and the reasons, must be retained for **5 years** from
the date of the decision (CDR 2016/957 Art.3(8); local equivalent as applicable). This
document constitutes that record. Store in the compliance case management system under
case reference <CASE-NNN>. Destroy or anonymise at end of retention period per data
retention policy.

---

## Sign-off
| Role | Name | Decision | Date |
|------|------|----------|------|
| Author / owner | | | |
| `compliance-reviewer` (DoD gate) | | | |
| Human approver (or `[IT team]`) | | | |
