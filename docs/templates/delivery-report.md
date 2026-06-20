# Delivery Report — <TITLE>

> **The team's default deliverable: one consolidated report.** All findings and evidence
> (review, performance, compliance, QA, handover, change/ops) live in this single file
> instead of many — easier to read and distribute. Omit or mark **N/A** any section that
> doesn't apply; split into separate artifacts only if the user/their controls require it.
> Authored in `.md`, rendered to `.html`.

| | |
|---|---|
| **Deliverable** | <name> |
| **Type** | review / build / remediation |
| **Version / commit** | <…> |
| **Date** | <YYYY-MM-DD> |
| **Overall verdict** | ✅ ready / ⚠️ ready with conditions / ❌ not yet |

## 1. Executive summary & next steps
Plain-language outcome in a few lines. Then **concrete next-step options with a
recommendation** — never a dead end (e.g. "fix the 3 criticals / run `/remediate` / produce a
change pack?").

## 2. Scope & what was delivered
What was reviewed or built, the languages/components involved, and what's explicitly out of
scope.

## 3. Requirements & traceability  *(builds; N/A for pure reviews)*
| BRD | FSD | Code | Test | Obligation | Status |
|-----|-----|------|------|------------|--------|

## 4. Code review
`Found N · Reported R · Filtered F` (depth, mode — see `docs/code-review-method.md`).
Each finding gets a `diff`-style fix + "why it works"; if none: *✅ no significant issues*.

| Sev | File:line | Issue | Conf. | Standard |
|-----|-----------|-------|-------|----------|
| 🔴 | | | | CWE-… |
| 🟠 | | | | |

Per critical/warning, a suggested fix:
```diff
- before
+ after
```
*Why this works:* …

Architectural notes & impact (deep): patterns, coupling, blast radius, breaking changes.

## 5. Performance & scalability  *(N/A if it doesn't process data at volume)*
Workload & target volume; method (profiler used); evidence-backed findings; **scale verdict**.

| Location | Issue | Evidence | Impact at target | Sev | Fix |
|----------|-------|----------|------------------|-----|-----|

## 6. Compliance & audit
Auditability (alert→logic→obligation), documented thresholds (§4), data safety (no
secrets/PII/raw data, §5), change-control readiness.

## 7. QA / test evidence  *(independent — qa-engineer)*
| Suite | Tests | Pass | Fail | Skip |
|-------|-------|------|------|------|

Reproduce: `pytest …`. Test data: synthetic/masked (§5). **Covered / NOT covered / residual
risk.** Items for a human QA reviewer to re-verify.

## 8. Developer handover
How to build/run/test, configuration, key design decisions (ADRs), known limitations & tech
debt, how to extend.

## 9. Change & operations  *(when handing to an IT team — [IT team] fields left blank)*
- **Change request:** summary, risk & impact, rollback; approvals **[IT team / CAB]**.
- **Ops:** monitoring/alerting (incl. alert-liveness), failure modes & recovery, escalation
  **[IT team]**.
- **Release notes:** what changed, known issues.

> The team **drafts** §9; **your IT team approves, deploys and signs off** — it does not
> self-certify these controls.

## 10. Sign-off
| Role | Name | Decision | Date |
|------|------|----------|------|
| qa-engineer (AI) | | | |
| Human reviewer | | | |
