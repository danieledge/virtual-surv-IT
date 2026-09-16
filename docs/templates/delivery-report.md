# Delivery Report - <TITLE>

> **The team's default deliverable: one consolidated report.** All findings and evidence
> (review, performance, compliance, QA, handover, change/ops) live in this single file
> instead of many - easier to read and distribute. Omit or mark **N/A** any section that
> doesn't apply; split into separate artifacts only if the user/their controls require it.
> Authored in `.md`, rendered to `.html`. **Close-only artifact:** this filename may exist
> only once START-HERE says ✅ closed (`FINAL-BEFORE-CLOSE`) - interim output takes a
> pass-scoped name (`review-pass-N`, `qa-cycle-N`, `interim-*`) instead.

> **This document must stand alone** (ISRT 2026-09-16 live report - read end to end with the
> lens "if this is handed over with nothing else, no `data/` folder, no companion memos, does
> it hold up?"). Two rules that follow from that:
> - **Every pack that was merged in is fully represented, not just its worst findings** -
>   when §1a/§2 says findings were merged from N packs, all N are reflected in the header's
>   disposition count and the exec summary's severity counts, with **no pack reduced to a
>   single summary sentence elsewhere while its findings are absent from every count and
>   index** (a live report undercounted its own Criticals this way - a whole specialist's
>   pack, 2 of them, never itemized anywhere).
> - **A finding that's rolled up ("+N more, see pack") still gets one line in the Appendix
>   findings index** (end of document) - ID, severity, one-line summary, minimum. Rolling up
>   the detail in §4-§6 is good scanning; rolling a finding out of the document ENTIRELY is
>   not standalone. If full detail can only be had by opening `data/findings-*.jsonl`, say so
>   explicitly where the rollup happens - never let "see pack" imply detail this document
>   doesn't actually contain when handed over alone.

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
| **Version / commit** | <project-relative path or repo name + commit SHA - never a local absolute filesystem path (`LOCAL-PATH-LEAK`: `C:/Users/<name>/...` leaks an OS username into a doc classified for external distribution)> |
| **Date** | <YYYY-MM-DD> |
| **Classification / distribution** | Internal - restricted to `<named recipients / role group>` |
| **Overall verdict** | ready / ready with conditions / not yet |
| **Findings disposition** | _N_ fixed · _N_ open · _N_ accepted · _N_ deferred |

**Findings at a glance** _(the master index - every finding minted anywhere below, one row
each; the same "scannable list before the detail" GitHub code scanning / SonarQube / SARIF all
lead with, and `REVIEW-<slug>.md`'s own summary table already does - ISRT 2026-09-15: without
this the report had per-section tables but no single place answering "what are ALL the
findings". Populate from the underlying `id` each finding already carries in its source
findings pack - never invent a new numbering scheme.)_ **The ID is a link, not just a label**
(ISRT 2026-09-16 - "navigable" means a reader can actually jump there, not just read a table of
labels that don't go anywhere): `[CR-01](#cr-01)`, pointing at the matching anchor on that
finding's row in its own section below (`` <a id="cr-01"></a> `` right before the row's ID
cell - plain markdown links/anchors, nothing the sanitiser strips). Lowercase the anchor;
`render_html` doesn't case-fold ids.

| ID | Sev | Section | Location | Impact | Status |
|----|-----|---------|----------|--------|--------|
| [CR-01](#cr-01) | 🔴 Critical | §4 Code review | `path/file.py:12` | one line - what happens if this ships unfixed | Open |

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
next-step options with a recommendation** - never a dead end. **Name the finding ID** (e.g.
"CR-01") for each blocking or otherwise notable item mentioned here - the detail sections below
use IDs consistently (see the Findings at a glance table above); an exec summary that only
narrates in prose forces the reader to go hunting for which detail row it means.

**Iteration history:** how this outcome was reached (a failed pass caught and fixed, a
clarification round) is in §2a below, not here - this section stays the outcome and the ask, not
the journey.

**Citing the codebase map:** a fact stated here (or anywhere in this report) that was sourced
from the project's codebase map cites it inline, e.g. `(map §2 #4)` - the map's own `#` column
is the anchor. Don't restate map content without pointing back to it; the map is the durable
record and this report is one dated read of it.

> **This is the "as-delivered / after" view.** Where it supersedes earlier *as-found* evidence
> (e.g. a [`qa-handover`](qa-handover.md), a review report), **reference that evidence as the
> "before" and show the resolved state here - do not rewrite the source** (it's the audit trail of
> what was caught). **Distinguish two kinds of "open":** *unresolved defects* (a real problem -
> the verdict can't be ready) vs *deferred deploy-gates* (e.g. calibrate on real data, scale-test,
> human sign-off) that are **correctly** open and out of scope for this stage. A report
> showing the latter as open is *good*; a report that hides them to look "all green" is the failure.

## 2. Scope & what was delivered
What was reviewed or built, the languages/components involved, and what's explicitly out of
scope.

## 2a. Iteration log - how we got here *(always include)*
> Deliberately positioned AFTER Scope, not between the exec summary and it (ISRT 2026-09-15:
> the section used to sit as "1a", directly interrupting the exec-summary → scope reading
> path for a stakeholder who wants the outcome and what was covered before the process detail).
> §1 links forward to this section rather than containing it.

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

## 3. Requirements & traceability  *(builds; N/A for pure reviews)*
| BRD | FSD | Code | Test | Obligation | Status |
|-----|-----|------|------|------------|--------|

## 4. Code review
`Found N · Reported R · Filtered F` (depth, mode - see `docs/code-review-method.md`).
Each finding gets a `diff`-style fix + "why it works" **and a Status**; if none: *no
significant issues*. **ID** carries the finding's own id from its source findings pack (never
renumbered here) - it's what the Findings at a glance table above and the exec summary cite,
and it's an anchor target: `` <a id="cr-01"></a> `` immediately before the cell, lowercased, so
the master index's link actually lands here. **Impact is its own column, not buried in prose
below** (ISRT 2026-09-16: "detail the impact of issues" means at the row a reader scans, not
only in an optional block three sections later) - one line, what happens if this ships unfixed,
not a restatement of the issue itself. **Basis icons defined here, at their first use, not in
§5** (ISRT 2026-09-16: a live report used them in this table before defining them three
sections later) - **📊 measured** (profiler/analyser ran) · **📄 coded** (an explicit value
read from source, nothing run) · **🧠 inferred** (reasoned from structure). Standard codes
(CWE, OWASP ASVS, ...) get a one-line meaning on first appearance too, or a footnote - never
assume the reader already knows CWE-670 by number; the full catalogue lives in the Glossary
at the end regardless.

| ID | Sev | File:line | Issue | Impact | Conf. | Basis | Standard | Status |
|----|-----|-----------|-------|--------|-------|-------|----------|--------|
| <a id="cr-01"></a>CR-01 | 🔴 Critical | | | | | 📊 measured / 🧠 inferred | CWE-... | Fixed / Open / Accepted |
| <a id="cr-02"></a>CR-02 | 🟠 Warning | | | | | | |

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

| ID | Location | Issue | Basis | Evidence | Impact at target | Sev | Fix |
|----|----------|-------|-------|----------|------------------|-----|-----|
| <a id="pr-01"></a>PR-01 | | | | | | | |

> **Table shape varies deliberately by section** (ISRT 2026-09-15) - §4/§5/§6 hold different
> kinds of data (a code finding's `File:line` isn't a performance finding's `Location at
> target volume`), so their columns differ; within one section every row uses the same shape.
> What's constant across all three: the `ID` column, and (when a finding gets its own
> block below the table, output-format.md's shape) the five NAMED fields - Standard, Problem,
> Likely cause, Impact, Fix.

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

## Appendix: Full findings index *(generated last, after every section is final)*

> Every finding minted anywhere in this engagement, one row - **including ones rolled up as
> "+N more, see pack" above**. The Findings at a glance table near the top is a curated
> highlights view for a 30-second orientation; this is the complete one, and it's what makes
> the "stands alone with no `data/` folder" promise true rather than aspirational
> (ISRT 2026-09-16). Same anchor convention as §4/§5: link the ID to `#<id>` when the finding
> has its own row/block above, otherwise the ID is unlinked (it exists only here).

| ID | Section | Sev | One-line summary | Status |
|----|---------|-----|-------------------|--------|
| [CR-01](#cr-01) | §4 | 🔴 Critical | one line, enough to know what it is without opening the pack | Open |

**Glossary** *(define on first use in the body too, where it lands harder - this is the
catch-all, ISRT 2026-09-16: CWE codes, "sargable," and the 📊/📄/🧠 basis icons appeared
unexplained through a live report, for an audience that isn't only engineers)*. Name every
standard/code family used (CWE, OWASP ASVS, ...) and every jargon term a compliance or
model-risk reader wouldn't already know, one line each.

> **Run provenance & non-determinism** *(standing statement - keep it in the rendered artifact)*
> · Model `<model id>` · Framework `compliance-surveillance-team <version>` · Run `<YYYY-MM-DD>`
>
> The findings and conclusions in this document are **one sample from a non-deterministic
> process**. The same inputs, run again by the same model, can yield a different set of findings,
> in a different order, with different confidence scores. **Absence of a finding is not evidence
> of absence:** this document evidences what *was* found on this run, never that nothing further
> exists. Anything load-bearing for a control decision needs human verification; repeat runs
> raise confidence but never make the result exhaustive.

## Sign-off
> 🤖 = AI agent (Virtual Surveillance IT), not a human. Agent rows and human-approver rows stay separate - never combine an agent and a human on one line.

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
