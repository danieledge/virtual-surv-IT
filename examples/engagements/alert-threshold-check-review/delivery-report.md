# Delivery Report - Code review: `alert_threshold_check.py`

> **Document control** · ID `DLVR-001` · Version `1.0` · Status `Approved`
> · Classification `Internal` · Owner `🤖 Morgan, PM (Virtual Surveillance IT)` · As-of `2026-09-14`
>
> | Version | Date | Author | Change |
> |---|---|---|---|
> | 1.0 | 2026-09-14 | 🤖 Morgan, PM (Virtual Surveillance IT) | Close |

| | |
|---|---|
| **Deliverable** | `alert_threshold_check.py` (19 lines as found) and its new test file |
| **Type** | review, with a fix and re-review loop |
| **Version / commit** | none. The project is not a git repository. Scope anchor is the file as read on 2026-09-14 |
| **Date** | 2026-09-14 |
| **Classification / distribution** | Internal |
| **Overall verdict** | **❌ not yet** fit for a production alerting job |
| **Findings disposition** | 7 fixed · 3 partially fixed · 7 accepted by your decision · 16 open |

## 1. Executive summary & next steps

You asked three questions. Here are the answers.

**Is the threshold defensible as written? No, and the number is not the problem.** `10000` matches the US CTR trigger, and the strict `>` at the comparison is correct: the rule attaches above $10,000, so a day totalling exactly $10,000.00 is rightly not reported. Changing that to `>=` would be a defect. What fails is governance. The constant carried no rationale, owner, tuning date, review cycle, currency or unit, so it could not be evidenced as governed. It was exposed as a `limit=` default any caller could override with nothing recorded, so it could not be evidenced as applied. With no repository and no version identifier, the value in force on any past date is unrecoverable. Separately, setting the alerting threshold exactly on the statutory line leaves no margin for rounding or late postings and makes the rule structurally blind to structuring, which happens below $10,000 by definition.

**Does the aggregation do what its name says? No, on three counts.** `aggregate_daily` filtered on neither date nor account, so it summed whatever list it was handed while its docstring promised one account-day. It summed signed amounts, so a credit nets against a deposit and can suppress a reportable cash-in leg. And it aggregated by account where the rule aggregates by person. **All three are still present in the code.** They are documented now, not fixed.

**What else before production.** No tests, no type hints, no input validation, a bare `bool` return discarding the evidence for the decision, an empty list indistinguishable from a broken feed, an import-time default binding that made a runtime threshold override silently ineffective, and a module docstring asserting a synthetic-data guarantee the code could not enforce. Most of these are now addressed.

**Reconciliation: what was found, then what was done.** Seven findings are fixed. Three are partially fixed. Seven are **accepted and documented rather than fixed**, because you chose safe fixes only and the caller could not be seen: keying the aggregation to a person, a business day and a direction would have changed both public signatures. That was the right call with an unknown caller, and it is why the verdict is still not-yet. Sixteen remain open, most of them compliance items that need a human, such as naming the threshold owner and filling the governance dates.

**One thing we caught on ourselves.** The first fix round introduced a data-safety regression: the new validation error messages interpolated the whole transaction record, which would have put customer data into tracebacks and logs. The original code never did that. Ravi found it on re-review, and Kenji fixed it in a second round. The error messages now name the record by its index and the field by name, never by value.

**Next steps, with my recommendation.**
1. **Recommended.** Answer the two open questions that block the rest: who owns this threshold, and does the calling job scope the input. Then commission the full fix for the aggregation, which needs signature changes and a caller inventory.
2. Put the file under version control before it governs any reporting decision. Nothing in this engagement could establish authorship, approval or change history, because none exists.
3. Grant execution consent so the 15 tests actually run. The QA verdict is currently inferred, not observed.
4. Have a human verify the 31 CFR citations against eCFR. Every one is marked TO-VERIFY.

I can carry out any of these. Say which.

## 1a. Iteration log

> 🔎 Review P1 (Ravi 12 · Layla 11) → 📊 Pip score → 🎩 Morgan challenge → ⛔ blocked on 3 user questions → 🔧 Fix R1 (Kenji) → 🧪 QA (Linh, static) + 🔎 Re-review P2 (Ravi) ❌ *(1 data-safety regression)* → 🔧 Fix R2 (Kenji) → 📊 Pip score → 🎩 Morgan verify

| # | Date | Hand-off | Trigger | Outcome | Evidence |
|---|---|---|---|---|---|
| 1 | 2026-09-14 | Morgan → Pip | Context and lens selection | 1 Python file, 19 lines, no CLAUDE.md, 4 lenses, 2 analysers unavailable | state log |
| 2 | 2026-09-14 | Morgan → Ravi + Layla | Deep review, concurrent | 12 code findings (2 critical), 11 compliance findings (4 critical), verdict FAIL | `data/findings-*.jsonl` |
| 3 | 2026-09-14 | Morgan → Pip | Score and filter | 23 found, 23 reported, 0 filtered, 6 cross-pack overlaps | pack envelopes |
| 4 | 2026-09-14 | Morgan challenge | Spot-check | Corrected Ravi's envelope severity split (5/4 stated, 6/3 actual). Overruled Layla's invented `9000` band and Ravi's "verified against eCFR" comment text | pack envelopes, state log |
| 5 | 2026-09-14 | Morgan → user | 3 questions that change the correct fix | Answered. Safe fixes only, so 7 findings become accepted-not-fixed | state decisions |
| 6 | 2026-09-14 | Morgan → Kenji | Fix round 1 | 5 fixed, 3 partial, 15 tests written, not run | module + test file |
| 7 | 2026-09-14 | Morgan → Linh + Ravi | QA and re-review, concurrent | QA 🧠 inferred, DoD PARTIAL. Re-review: 10 new findings, no new critical, **RR-01 data-safety regression** | `qa-handover.md`, re-review pack |
| 8 | 2026-09-14 | Ravi → Kenji | RR-01 and RR-04 | Both fixed. Error messages no longer disclose record contents. `DAILY_LIMIT` retype reverted | module |
| 9 | 2026-09-14 | Morgan → Pip | Score the re-review pack | 13 found, 10 reported, 3 filtered, split confirmed, RR-01 confirmed never-filter | re-review envelope |

Pass 7's failure is kept on the record deliberately. A regression that was caught, routed, fixed and recorded is evidence the loop works.

## 2. Scope & what was delivered

Reviewed: `alert_threshold_check.py`, whole file, 19 lines as found. One Python file, the only source file in the project. Nothing excluded, so there is no unreviewed remainder.

Delivered: the module with safe fixes applied, a new `test_alert_threshold_check.py` with 15 tests, three findings packs, an independent QA handover, and this report.

Out of scope: the calling alerting job, the upstream data contract, any downstream case management. None of it exists in this project and none was supplied. Jurisdiction: **US (BSA / FinCEN) only**. EU, UK and NYDFS Part 504 were explicitly not assessed, on your confirmation that the institution is not New York regulated.

## 3. Requirements & traceability

N/A for a review. Worth stating plainly as a finding rather than an omission: **no RTM, no requirement id, no obligation reference and no specification exist anywhere in this project.** That is CMP-01 and it is open.

## 4. Code review

`Found 12 · Reported 12 · Filtered 0` on the first pass, `Found 13 · Reported 10 · Filtered 3` on the re-review. Deep depth, audit mode. Scored by Pip (`review-scorer`) in both cases, then challenged by me. Full detail with diffs and rationale is in the findings packs; this is the summary.

| Sev | Location | Issue | Basis | Status |
|---|---|---|---|---|
| 🔴 Critical | `aggregate_daily` | Filters on neither date nor account nor person. Sums whatever list it is given (CR-01) | 📄 coded | **Accepted, documented not fixed** |
| 🔴 Critical | the accumulator line | Sums signed amounts, so a credit nets against a deposit and can suppress a reportable day (CR-02) | 📄 coded | **Accepted, documented not fixed** |
| 🟠 Warning | error messages | Validation messages interpolated the whole record into tracebacks and logs (RR-01, introduced by our own fix) | 📄 coded | **Fixed** |
| 🟠 Warning | `DAILY_LIMIT` | Bare untyped int, no unit, currency, rationale, owner or tuning date (CR-05) | 📄 coded | Partially fixed. Comment block added with placeholders; the values are yours to fill |
| 🟠 Warning | `txn["amount"]` | Unvalidated. Missing key, string, `None` or `bool` each mishandled (CR-04) | 📄 coded | Partially fixed. Validation added; RR-02 numpy scalars and RR-03 NaN remain |
| 🟠 Warning | whole module | No tests at all (CR-07) | 📊 measured | Partially fixed. 15 tests written, none executed |
| 🟠 Warning | `is_reportable` | Returns a bare bool, discarding the total, the limit applied and the count (CR-08) | 📄 coded | **Accepted, documented not fixed** |
| 🟠 Warning | both signatures | No type hints, no transaction data contract (CR-12) | 📊 measured, ruff | **Fixed** |
| 🟡 Medium | comparison line | Float accumulation deciding an exact monetary boundary (CR-03) | 🧠 inferred | **Fixed**, Decimal internally |
| 🟡 Medium | `limit=DAILY_LIMIT` | Import-time binding made a runtime threshold override silently ineffective (CR-10) | 📄 coded | **Fixed**, resolved at call time |
| 🟡 Medium | docstrings | Asserted a synthetic-data guarantee the code cannot enforce, and a scoping it does not implement (CR-11) | 📄 coded | **Fixed** |
| 🟡 Medium | empty input | An empty list is indistinguishable from a broken feed (CR-09) | 📄 coded | **Accepted, documented not fixed.** Raising would break unknown callers |
| 🔵 Style | comparison line | The strict `>` is **correct** and now carries a comment saying so. Recorded so nobody "fixes" it to `>=` (CR-06) | 📄 coded | **Fixed** |

Eight further re-review findings are open and are in the pack: numpy scalar rejection, NaN and Infinity passing validation, unfilled governance placeholders, no dependency manifest or CI, fail-stop batch validation with no quarantine, and two comments that overclaim.

**Architectural note.** The module conflates computing an aggregate with deciding a policy, and you confirmed it serves both a mandatory CTR filing determination and a discretionary investigation alert from one bool. Those carry different obligations and different error tolerance. Separating them is a signature change and is open.

**🔵 Developer guidance - improving future code.**
1. Put the aggregation key in the signature, not in the docstring. A function named for one day and one account should take that day and that account, so the contract is enforced rather than asserted.
2. Money is neither a float nor a bare int. Use `Decimal` or integer minor units from the edge of the system inward.
3. Write the boundary tests before the logic. The cases that decide this module are exactly at the limit, one cent either side, the empty list, a netting pair, and a record with no amount key.
4. When code makes a regulatory decision, return the evidence with the decision. A bare bool cannot be explained to an examiner six months later.

**🧑‍💻 Prompting guidance.** You told us the origin was mixed. Two findings here are classic AI-assisted shapes. CR-01 is the strongest example: the docstring described an aggregation that was never implemented, and it reads as correct precisely because the name supplies the missing logic to the reader. CR-02 is the same pattern at the data level, an unstated assumption that every amount is a same-direction positive. A prompt that said "the function must take the aggregation key as arguments and must not trust the caller to pre-filter" would have prevented both. When asking for detection logic, state the rule's qualifiers explicitly, entity, direction and window, rather than the headline number.

## 5. Performance & scalability

N/A. You chose no performance review and the module processes one list per call with no I/O.

## 6. Compliance & audit

Assessed by Layla (`compliance-reviewer`) against US BSA and FinCEN, 31 CFR Chapter X. Verdict **FAIL**, 4 critical findings, 11 open.

- **Traceability: NOT MET.** No obligation reference, no requirement id, no spec, no RTM. `check_citations` returned zero citations in the file, which confirms the absence mechanically.
- **Threshold governance: NOT MET.** Covered in §1. The fix added the governance comment block; the owner, dates and version are `<to be completed>` placeholders and are yours.
- **Decision auditability: NOT MET.** A bare bool creates no record. A look-back cannot do below-the-line testing because non-alerting days leave no total.
- **Change control: NOT MET.** No repository, so no authorship, approval or history exists.
- **Data safety: MET, and stated because a clean result is a result.** The file contains no personal data, no identifiers, no transaction records, no MNPI and no secrets. The one regression we introduced against this limb (RR-01) was caught and fixed.
- **Citations.** Every 31 CFR and 31 USC pinpoint is marked **TO-VERIFY** with a primary-source permalink. The bundled regulatory register holds no BSA or FinCEN entries, so none of them is asserted as verified. Do not quote them to a regulator until a human has checked them against eCFR.

**Limitation on this section.** Layla assessed the code **as found**. No second compliance pass was run after the fixes, so the dispositions of her findings in this report are mine, not hers, and are 🧠 inferred. A fresh compliance pass would be needed before anyone relies on the compliance limb as current.

## 7. QA / test evidence

Independent pass by Linh (`qa-engineer`). Full detail in [`qa-handover.md`](qa-handover.md).

| Suite | Tests | Pass | Fail | Skip |
|---|---|---|---|---|
| `test_alert_threshold_check.py` | 15 | **not run** | **not run** | **not run** |

**No test was executed.** Execution consent was withheld, which was your choice and the safe default. Under the static-only DoD path the QA verdict is **🧠 inferred** and the **DoD is PARTIAL**. Linh read all 15 tests statically and found none vacuous, none that would error at collection, and no wrong expected values. The characterisation test pinning the known CR-02 netting defect is clearly commented as such and cannot be misread as an assertion that the behaviour is correct.

Reproduce: `pytest test_alert_threshold_check.py`. Test data is synthetic amounts with no identifiers.

**NOT covered:** an `int` limit exercising the coercion branch, a `Decimal` amount, a non-dict record, an assertion that `aggregate_daily` actually returns `Decimal`, and any volume test.

**Residual risk.** The module and its tests have never been executed by anyone in this engagement. Every behavioural claim in this report is reasoned from source, not observed. Grant execution consent and the QA verdict upgrades from 🧠 to 📊.

## 8. Developer handover

The two public functions keep their names and parameter lists, so existing callers are unaffected by signature. Three behavioural changes to know about:

1. `aggregate_daily` now returns `Decimal`. A caller doing float arithmetic on it, JSON-serialising it, or `isinstance(x, int)` on it will break.
2. Malformed records now raise a clear error naming the index and the field. Previously they raised `KeyError`, raised `TypeError`, or were silently miscounted. A caller that relied on the silent path will now see an exception.
3. The `limit` default resolves at call time, so rebinding `DAILY_LIMIT` at runtime now actually takes effect. Previously it silently did not.

`DAILY_LIMIT` remains a plain `int`. Kenji briefly retyped it to `Decimal`; Ravi ruled that a public API change outside the safe-fixes mandate that bought nothing, and it was reverted.

**Known limitations, carried deliberately.** The aggregation still does not scope to a day, an account, a person, a direction or to currency transactions only. Those gaps are now written as a prominent `WARNING:` block in the function docstring, stating what the function does not do and that the caller must guarantee it. That is documentation, not a fix.

## 9. Change & operations

Drafted for your IT team, who approve and deploy. This team does not self-certify these controls.

- **Change request:** low-risk edits to one module plus a new test file. No signature changes. Rollback is reverting two files. **Approval: [IT team / CAB].**
- **Blocking pre-deploy gate:** the file must go under version control first. There is currently no rollback point and no approval record.
- **Ops:** the module emits nothing. There is no alert-liveness signal and no way to distinguish a quiet day from a broken feed. Add feed-volume reconciliation upstream before relying on a non-alert. **[IT team].**

> **Run provenance & non-determinism** *(standing statement)*
> · Model `Claude Opus 4.5` · Framework `compliance-surveillance-team 0.37.0` · Run `2026-09-14`
>
> The findings and conclusions in this document are **one sample from a non-deterministic process**. The same inputs, run again by the same model, can yield a different set of findings, in a different order, with different confidence scores. **Absence of a finding is not evidence of absence:** this document evidences what *was* found on this run, never that nothing further exists. Anything load-bearing for a control decision needs human verification; repeat runs raise confidence but never make the result exhaustive.

> **Known gap in this engagement.** The `.html` renderer is not installed in this environment, so no artifact here has an HTML sibling. Markdown is complete and authoritative. Install the dev requirements and re-render to close it.
>
> **Independence gap, stated plainly.** The second fix round (RR-01, RR-04) was verified by me, the PM, not by an independent re-review pass. There was not enough budget headroom to buy both that pass and a complete close. Treat those two fixes as 🧠 PM-verified, not independently reviewed.

## Sign-off

> 🤖 = AI agent (Virtual Surveillance IT), not a human. Agent rows and human-approver rows stay separate.

| Role | Name | Decision | Date |
|---|---|---|---|
| Author / owner | 🤖 Morgan, PM (Virtual Surveillance IT) | Delivered | 2026-09-14 |
| PM (`Morgan`) | 🤖 Morgan, PM (Virtual Surveillance IT) | Verdict: not yet | 2026-09-14 |
| `code-reviewer` | 🤖 Ravi (Virtual Surveillance IT) | Reviewed, 2 passes | 2026-09-14 |
| `compliance-reviewer` (DoD gate) | 🤖 Layla (Virtual Surveillance IT) | FAIL, as-found only, not re-run after fixes | 2026-09-14 |
| `qa-engineer` | 🤖 Linh (Virtual Surveillance IT) | 🧠 inferred, DoD PARTIAL, no test executed | 2026-09-14 |
| Human approver (or `[IT team]`) | | Pending | |

---
> **Code-execution note.** Review was **static by default**, and you declined execution consent, so nothing in the reviewed code or its tests was ever run. **Ensuring code handed over for review is safe to run remains your responsibility** (CLAUDE.md §7).
>
> **Data note.** `data/raw/` is hard-blocked from agents. No data was shared in this engagement and none was analysed. **Ensuring shared data is safe and policy-compliant remains your responsibility** (CLAUDE.md §5).
