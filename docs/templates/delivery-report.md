# Delivery Report - <TITLE>

> **The team's default deliverable: one consolidated report.** All findings and evidence
> (review, performance, compliance, QA, handover, change/ops) live in this single file
> instead of many - easier to read and distribute. Omit or mark **N/A** any section that
> doesn't apply; split into separate artifacts only if the user/their controls require it.
> Authored in `.md`, rendered to `.html`. **Close-only artifact:** this filename may exist
> only once START-HERE says ✅ closed (`FINAL-BEFORE-CLOSE`) - interim output takes a
> pass-scoped name (`review-pass-N`, `qa-cycle-N`, `interim-*`) instead.

> **Document control** · ID `DLVR-001` · Version `0.1` · Status `Draft | In review | Approved`
> · Classification `Internal | Confidential` · Owner `<name / role>` · As-of `<YYYY-MM-DD>`
>
> | Version | Date | Author | Change |
> |---|---|---|---|
> | 0.1 | <YYYY-MM-DD> | <author> | Initial draft |

| | |
|---|---|
| **Deliverable** | <name> |
| **Type** | review / build / remediation |
| **Version / commit** | <...> |
| **Date** | <YYYY-MM-DD> |
| **Classification / distribution** | Internal - restricted to `<named recipients / role group>` |
| **Overall verdict** | ready / ready with conditions / not yet |
| **Findings disposition** | _N_ fixed · _N_ open · _N_ accepted · _N_ deferred |

**Contents** _(keep for a large multi-section report - `[TOC]` renders a clickable, internal-link
section index in the `.html` via `render_html`; omit on a short report)_

[TOC]

## 1. Executive summary & next steps
Plain-language outcome in a few lines. **Reconcile findings with what was then done** - this is
mandatory: if the engagement found blocking issues **and** then fixed/reimplemented, state the
**current** status of each (addressed by the rework - say how / still open / open, needs
human developer review), so the verdict can't be read as "blocked" when it was actually resolved
(or vice-versa). The **Overall verdict must match the disposition**: not-yet only if items are still
Open; ready/ready-with-conditions once they're fixed or explicitly accepted. Then give **concrete
next-step options with a recommendation** - never a dead end.

> **This is the "as-delivered / after" view.** Where it supersedes earlier *as-found* evidence
> (e.g. a [`qa-handover`](qa-handover.md), a review report), **reference that evidence as the
> "before" and show the resolved state here - do not rewrite the source** (it's the audit trail of
> what was caught). **Distinguish two kinds of "open":** *unresolved defects* (a real problem -
> the verdict can't be ready) vs *deferred deploy-gates* (e.g. calibrate on real data, scale-test,
> human sign-off) that are **correctly** open and out of scope for this stage. A report
> showing the latter as open is *good*; a report that hides them to look "all green" is the failure.

## 1a. Iteration log - how we got here *(always include)*
The engagement's journey at a glance, then the append-only pass record. **A failed pass that
was caught, routed, fixed and re-verified is proof the control loop operates - show it, never
smooth it into a clean narrative.** One row per gate-level hand-off (build, review pass, QA
pass, clarification round) - not per tool call. First-pass-clean is one strip and one row.

> 🔨 Build → 🔎 Review P1 ❌ *(3 Critical)* → 🔧 Fix (`rules-developer`) → 🔎 Review P2 ✅ →
> 🧪 QA P1 ❌ *(2 defects)* → 🔧 Fix → 🧪 QA P2 ✅

| # | Date | Hand-off (actor → actor) | Trigger | Outcome | Evidence |
|---|------|--------------------------|---------|---------|----------|
| 1 | <YYYY-MM-DD> | `qa-engineer` → `rules-developer` | QA pass 1: Fail (QAH-001 defects D-1, D-2) | Fixes applied to `<files>` | [`qa-handover`](qa-handover.md) (as-found) |
| 2 | <YYYY-MM-DD> | `rules-developer` → `qa-engineer` | re-test request | QA pass 2: Pass | §7 below |

## 2. Scope & what was delivered
What was reviewed or built, the languages/components involved, and what's explicitly out of
scope.

## 3. Requirements & traceability  *(builds; N/A for pure reviews)*
| BRD | FSD | Code | Test | Obligation | Status |
|-----|-----|------|------|------------|--------|

## 4. Code review
`Found N · Reported R · Filtered F` (depth, mode - see `docs/code-review-method.md`).
Each finding gets a `diff`-style fix + "why it works" **and a Status**; if none: *no
significant issues*.

| Sev | File:line | Issue | Conf. | Basis | Standard | Status |
|-----|-----------|-------|-------|-------|----------|--------|
| Critical | | | | 📊 measured / 🧠 inferred | CWE-... | Fixed / Open / Accepted |
| Warning | | | | | | |

**Disposition:** _N_ fixed · _N_ open · _N_ accepted · _N_ deferred. A not-yet verdict lists
the Open items. **No straightforward fix - mark Open (needs human developer review)** with the
reason and options - never a guessed fix.

Per critical/warning, a suggested fix:
```diff
- before
+ after
```
*Why this works:* ...

Architectural notes & impact (deep): patterns, coupling, blast radius, breaking changes.

**Developer guidance - improving future code *(always include).*** 2-4 constructive, non-blocking
points on the original coding style and how to improve next time (style/form; does not affect
the verdict). If it's strong, say what's done well.

## 5. Performance & scalability  *(N/A if it doesn't process data at volume)*
Workload & target volume; method (profiler used); evidence-backed findings; **scale verdict**.

All findings carry a basis qualifier: **📊 measured** (profiler/benchmark that ran) · **📄 coded**
(an explicit value read from source - not a run) vs **🧠 inferred** (reasoned from structure - name
the benchmark that would confirm it). The
verdict for a static-only review must read "inferred - not profiled" rather than asserting
scale as measured.

| Location | Issue | Basis | Evidence | Impact at target | Sev | Fix |
|----------|-------|-------|----------|------------------|-----|-----|

## 6. Compliance & audit
Auditability (alert -> logic -> obligation), documented thresholds (§4), data safety (no
secrets/PII/raw data, §5), change-control readiness.

## 7. QA / test evidence  *(independent - qa-engineer)*
| Suite | Tests | Pass | Fail | Skip |
|-------|-------|------|------|------|

Reproduce: `<project's test command - pytest / Pester / mvn test / npm test ...>`. Test data:
synthetic/masked (§5). **Covered / NOT covered / residual
risk.** Items for a human QA reviewer to re-verify.

## 8. Developer handover
How to build/run/test, configuration, key design decisions (ADRs), known limitations & tech
debt, how to extend.

## 9. Change & operations  *(when handing to an IT team - [IT team] fields left blank)*
- **Change request:** summary, risk & impact, rollback; approvals **[IT team / CAB]**.
- **Ops:** monitoring/alerting (incl. alert-liveness), failure modes & recovery, escalation
  **[IT team]**.
- **Release notes:** what changed, known issues.

> The team **drafts** §9; **your IT team approves, deploys and signs off** - it does not
> self-certify these controls.

## Sign-off
| Role | Name | Decision | Date |
|------|------|----------|------|
| Author / owner | | | |
| PM (`Morgan`) | | | |
| `compliance-reviewer` (DoD gate) | | | |
| Human approver (or `[IT team]`) | | | |

---
> **Code-execution note.** Review was **static by default**; any execution of the reviewed code
> (tests/profiling) happened **only with the user's consent** in a safe environment on
> synthetic data. **Ensuring code handed over for review is safe to run remains the user's
> responsibility** (CLAUDE.md §7).
>
> **Data note.** `data/raw/` is hard-blocked from agents. Any other data analysed was provided on
> the user's **attestation** that it is masked/synthetic/anonymised with no prohibited PII/MNPI;
> **ensuring shared data is safe and policy-compliant remains the user's responsibility** (CLAUDE.md §5).
