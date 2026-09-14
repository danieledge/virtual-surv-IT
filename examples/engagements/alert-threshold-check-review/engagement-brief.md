# Engagement Brief - Code review: `alert_threshold_check.py`

> **Document control** · ID `ENG-001` · Version `1.0` · Status `Approved - pending human sign-off`
> · Classification `Internal` · Owner `🤖 Morgan, PM (Virtual Surveillance IT)` · As-of `2026-09-14`
>
> | Version | Date | Author | Change |
> |---|---|---|---|
> | 0.1 | 2026-09-14 | 🤖 Morgan, PM (Virtual Surveillance IT) | Initial draft |

| | |
|---|---|
| **Engagement** | alert-threshold-check-review |
| **Requested by** | <requester> (the eval harness's account; replaced when the run was frozen as the shipped sample)|
| **Date** | 2026-09-14 |
| **Type** | review |
| **Status** | intake |

## 1. The ask (PM's restatement)

Review `alert_threshold_check.py`, a 19-line helper that decides whether one day's activity on
one account is reportable. Three specific questions:

1. Is the threshold defensible as written?
2. Does the aggregation do what its name says?
3. What else would we want fixed before this goes near a production alerting job?

The write-up lands in this workspace so it can be handed on. The user asked for a short review
proportionate to a small file.

## 2. Regulatory obligation

🧠 Inferred, not confirmed. The code carries no obligation reference of its own. A same-day
aggregate over one account against a hard `10000` limit is the shape of a cash-transaction
reporting threshold. Two candidates, both TO-VERIFY:

| Obligation | Jurisdiction | Article / rule | What it requires |
|---|---|---|---|
| BSA currency transaction reporting | US | 31 CFR 1010.311 | Report currency transactions over $10,000 by or on behalf of one person in one business day, aggregated |
| AML cash-payment limit | EU | AMLD/AMLR cash thresholds | Obliged-entity controls around large cash amounts, threshold set by regime |

The absence of a stated obligation in or beside the code is itself a finding candidate. The
applicable regime(s) are being confirmed with the user at the go-ahead gate.

## 3. Agreed success criteria

| # | Success criterion | How measured / verified | Agreed by |
|---|---|---|---|
| 1 | The three questions above are each answered explicitly, with the evidence basis tagged | The review artifact contains a direct answer to each | user |
| 2 | Findings carry dispositions and the fix→re-review loop runs to no open Criticals, or names what needs a human decision | Findings register + iteration log | user |
| 3 | The write-up is short and hand-on-able | One consolidated Delivery Report in this workspace, `.md` (+ `.html` if the renderer is installed) | user |

## 4. Decisions taken

| Decision | Answer | Source |
|---|---|---|
| Work type | Code review (not a build) | Derived from the request, stated for correction |
| Execution consent | No - do not run the code under review | User, 2026-09-14 |
| Data attestation | No data involved - code only | Recorded silently; no data was shared |
| Review depth | Deep | User, 2026-09-14 |
| Performance review | No | User, 2026-09-14 |
| Fix-cycle | Fix → re-review loop | User, 2026-09-14 |
| Origin | Mixed (human and AI interleaved) | User, 2026-09-14 |
| Packaging | One consolidated Delivery Report | Default (2026-08-17 user decision) |

**Derived review scope:** Deep · Full review (core + quality + 📋 compliance/audit) ·
`alert_threshold_check.py`, whole file, 19 lines · mode `audit` · origin: mixed.

**Not in scope:** nothing is excluded. It is the only source file in the project, so there is no
remainder to leave unread.

📋 compliance/audit is in the dimension set because this code decides reportability. That makes
it detection logic under §4, not general-purpose code.

## 5. Open questions / clarifications needed

1. Which jurisdiction(s) apply, so the compliance pass assesses the applicable regime and says
   what is not applicable. Put to the user at the go-ahead gate.
2. Where the `10000` value came from, and whether a rationale, owner and tuning date exist
   anywhere outside the file. Nothing in the repo records one.
3. What `txn["amount"]` actually holds upstream: currency, sign convention, type, and whether
   reversals and cancellations appear in the same list.

## 6. Assumptions & constraints

- The file's docstring says synthetic sample. Taken at face value; no data was shared with us.
- Execution consent is withheld, so nothing is run. Findings that would need the code to execute
  stay 🧠 inferred, and the QA pass takes the static-only DoD path with a 🧠 verdict and a
  PARTIAL DoD. Untested code is named as residual risk at close.
- No git repository here, so there is no commit anchor for the scope. The scope anchor is the
  file as read on 2026-09-14.
- The `.html` renderer is not installed in this environment. Markdown always lands; HTML siblings
  may not, and that is recorded rather than worked around.
- 🧠 Analysers: ruff, mypy, bandit and black are installed, so Python findings can be measured.
  opengrep and ast-grep are not, so anything that would have relied on them stays inferred.

## 7. Documentary artifacts requested

One consolidated **Delivery Report** (`delivery-report.md`), written at close, holding the
review findings, the iteration log, the QA evidence summary and the close verdict. The findings
pack (`data/findings-*.jsonl`) and the rendered review are produced by the pipeline underneath
it. This brief and the summary email complete the set.

## 8. Proposed approach & routing plan

Pipeline roll-call: **Pip context → Ravi → Pip score/filter → Layla → my challenge → Kenji fix
→ Linh QA + Ravi re-review.**

| # | Stage | Owner | Note |
|---|---|---|---|
| 1 | Context, language and lens selection | 🤖 Pip (`review-scorer`) | Cheap tier, rote work |
| 2 | Deep review pass | 🤖 Ravi (`code-reviewer`) | One folded pass: security + correctness + architecture. 19 lines does not justify three facet passes |
| 3 | Score and filter | 🤖 Pip (`review-scorer`) | Found / Reported / Filtered, never filters regulated findings |
| 4 | Compliance and audit trail | 🤖 Layla (`compliance-reviewer`) | §4/§5 trail, threshold rationale, traceability |
| 5 | Challenge pass | 🤖 Morgan (PM) | Spot-check, not a re-score |
| 6 | Apply fixes and add tests | 🤖 Kenji (`platform-engineer`) | Utility script, so the builder is platform-engineer, not rules-developer |
| 7 | Independent QA | 🤖 Linh (`qa-engineer`) | Static-only, consent withheld |
| 8 | Re-review | 🤖 Ravi (`code-reviewer`) | Fresh context, loop until no open Criticals |

**Right-sizing.** Seven subagent calls across the three phases. Stages 1 to 4 are one concurrent
dispatch where independent; stages 7 and 8 go out together. No `tuning-analyst` pass: threshold
calibration needs data to calibrate against and no data exists here, so a tuning pass would
return pure inference. The threshold question is answered instead as a design and traceability
question by Layla, plus the PM's read of the `docs/sme/tm-monitoring.md` knowledge pack.

## 9. Risks & dependencies

| Risk | Impact | Handling |
|---|---|---|
| Jurisdiction unknown at dispatch | Compliance pass assesses the wrong regime | Asked at the go-ahead gate before Layla is briefed |
| The `10000` rationale may exist outside this repo | We report a traceability gap that is really a documentation-location gap | Finding stated as "no rationale reachable from the code", not "no rationale exists" |
| Execution withheld | No measured test evidence | Static-only DoD path, PARTIAL, residual risk named at close |
| Upstream data contract unknown | Aggregation findings stay inferred | Stated as an assumption, raised as an open question |

## 10. Next action

User answers the go-ahead gate and the jurisdiction question. Then the review dispatch goes out.

## Sign-off

> 🤖 = AI agent (Virtual Surveillance IT), not a human. Agent rows and human-approver rows stay separate - never combine an agent and a human on one line.

| Role | Name | Decision | Date |
|---|---|---|---|
| Author / owner | 🤖 Morgan, PM (Virtual Surveillance IT) | Drafted | 2026-09-14 |
| `compliance-reviewer` (DoD gate) | 🤖 Layla (Virtual Surveillance IT) | Not yet run | |
| Human approver (or `[IT team]`) | | Pending | |
