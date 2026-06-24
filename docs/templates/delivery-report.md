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
| **Findings disposition** | ✅ _N_ fixed · 🔴 _N_ open · ⚖️ _N_ accepted · ⏭️ _N_ deferred |

## 1. Executive summary & next steps
Plain-language outcome in a few lines. **Reconcile findings with what was then done** — this is
mandatory: if the engagement found blocking issues **and** then fixed/reimplemented, state the
**current** status of each (✅ addressed by the rework — say how / 🔴 still open / 🔴 open, needs
human developer review), so the verdict can't be read as "blocked" when it was actually resolved
(or vice-versa). The **Overall verdict must match the disposition**: ❌ only if items are still
Open; ✅/⚠️ once they're fixed or explicitly accepted. Then give **concrete next-step options with
a recommendation** — never a dead end.

## 2. Scope & what was delivered
What was reviewed or built, the languages/components involved, and what's explicitly out of
scope.

## 3. Requirements & traceability  *(builds; N/A for pure reviews)*
| BRD | FSD | Code | Test | Obligation | Status |
|-----|-----|------|------|------------|--------|

## 4. Code review
`Found N · Reported R · Filtered F` (depth, mode — see `docs/code-review-method.md`).
Each finding gets a `diff`-style fix + "why it works" **and a Status**; if none: *✅ no
significant issues*.

| Sev | File:line | Issue | Conf. | Standard | Status |
|-----|-----------|-------|-------|----------|--------|
| 🔴 | | | | CWE-… | ✅ Fixed / 🔴 Open / ⚖️ Accepted |
| 🟠 | | | | | |

**Disposition:** ✅ _N_ fixed · 🔴 _N_ open · ⚖️ _N_ accepted · ⏭️ _N_ deferred. A ❌ verdict lists
the Open items. **No straightforward fix → mark 🔴 Open (needs human developer review)** with the
reason and options — never a guessed fix.

Per critical/warning, a suggested fix:
```diff
- before
+ after
```
*Why this works:* …

Architectural notes & impact (deep): patterns, coupling, blast radius, breaking changes.

**Developer guidance — improving future code *(always include).*** 2–4 constructive, non-blocking
points on the original coding style and how to improve next time (🔵 style/form; does not affect
the verdict). If it's strong, say what's done well.

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

Reproduce: `<project's test command — pytest / Pester / mvn test / npm test …>`. Test data:
synthetic/masked (§5). **Covered / NOT covered / residual
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

---
> **Code-execution note.** Review was **static by default**; any execution of the reviewed code
> (tests/profiling) happened **only with the user's consent** in a safe environment on
> synthetic data. **Ensuring code handed over for review is safe to run remains the user's
> responsibility** (CLAUDE.md §7).
