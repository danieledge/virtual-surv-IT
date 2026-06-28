# Alert Investigation Record - <SCENARIO / ALERT ID>

> Produced by the first-line analyst reviewing an alert. The case-review record that links signal
> to evidence, assessment and disposition - underpins the alert-to-SAR metric and audit trail.

> **Document control** · ID `AINV-001` · Version `0.1` · Status `Draft | In review | Approved`
> · Classification `Confidential` · Owner `<analyst name / first-line surveillance>` · As-of `<YYYY-MM-DD>`
>
> | Version | Date | Author | Change |
> |---|---|---|---|
> | 0.1 | <YYYY-MM-DD> | <author> | Initial draft |

---

## 1. Alert identity

| Field | Value |
|---|---|
| Alert ID | <system-generated ID> |
| Detection scenario | <scenario name + ID> |
| Regulatory obligation | <e.g. MAR Art.12 / MLD5 Art.33> |
| Alert generated | <YYYY-MM-DD HH:MM UTC> |
| Review opened | <YYYY-MM-DD> |
| Analyst | <name / analyst ID> |
| Subject(s) | <synthetic ID or masked reference - no real PII> |

---

## 2. Signal - what fired

Describe in plain terms what the detection logic flagged: the specific behaviour, the parameter(s)
that breached threshold, and the alert score or severity if applicable. Reference the scenario
specification (FSD / scenario-spec) rather than restating the logic.

- Triggered parameter: <parameter name> = <value> vs threshold <value>
- Alert score / severity: <if applicable>
- Scenario reference: `<FSD-NNN / scenario-spec ref>`

---

## 3. Evidence considered

List every source reviewed. Use masked or synthetic identifiers for subjects and accounts
(§5 - no real PII/MNPI in this record).

### 3a. Orders / trades / transactions
| Evidence item | Reference / masked ID | Period | Relevance |
|---|---|---|---|
| <e.g. order blotter> | <ref> | <from - to> | <one line> |

### 3b. Communications (if applicable)
| Evidence item | Reference / masked ID | Channel | Relevance |
|---|---|---|---|
| <e.g. chat extract> | <ref> | <email / chat / voice> | <one line> |

### 3c. Contextual / reference data
| Evidence item | Source | Relevance |
|---|---|---|
| <e.g. news event, client classification> | <source> | <one line> |

---

## 4. Analyst assessment

Set out the analyst's reasoning: does the evidence support or refute the signal? Consider
legitimate explanations, known patterns and any prior alerts on the same subject.

**Assessment:** <Suspicious activity supported / Not supported - legitimate explanation found>

Key points:
- <point 1>
- <point 2>
- <point 3>

---

## 5. Disposition

| Field | Value |
|---|---|
| Decision | `Close - no further action` / `Escalate to second line` / `Refer for SAR/STR` |
| Rationale | <one paragraph - the legal/factual basis for the decision> |
| SAR/STR referral ID | <if applicable - link to `sar-str-referral.md` SAR-NNN> |
| Date disposed | <YYYY-MM-DD> |

---

## 6. QA / second-line review

| Field | Value |
|---|---|
| Reviewer | <name / QA analyst> |
| Review date | <YYYY-MM-DD> |
| Outcome | `Agreed` / `Overturned` / `Referred back` |
| Notes | <one line - reason if overturned or referred back> |

---

## 7. Linked artifacts

| Artifact | ID / location |
|---|---|
| Detection scenario spec | <FSD-NNN / scenario-spec ref> |
| SAR/STR referral pack | <SAR-NNN or N/A> |
| Prior alerts - same subject | <AINV-NNN list or N/A> |

---

## Sign-off
| Role | Name | Decision | Date |
|------|------|----------|------|
| Author / owner | | | |
| `compliance-reviewer` (DoD gate) | | | |
| Human approver (or `[IT team]`) | | | |
