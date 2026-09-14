> As-found QA evidence. The as-delivered view is in [`delivery-report.md`](delivery-report.md).

# QA Handover - Test Evidence - alert_threshold_check.py (CTR daily aggregate and reporting threshold)

> Produced by `qa-engineer` (independent of the builder). Evidences what was tested, the
> results, what is **not** covered, and what the QA team should note or re-verify. Authored
> in `.md`, rendered to `.html`.

> **QA level for this pass:** `deep` (no level stated in the dispatch brief; deep is the
> default). This pass is additionally constrained to **static-only**, per explicit
> instruction in the dispatch: execution consent is withheld for this engagement, so no test
> was run. This is not a QA-level reduction (quick vs deep); it is the static-only DoD path,
> orthogonal to level. Verdict is 🧠 inferred throughout, never 📊 observed.

> **Document control** · ID `QAH-001` · Version `0.1` · Status `Draft`
> · Classification `Internal` · Owner `Linh (qa-engineer)` · As-of `2026-09-14`
>
> | Version | Date | Author | Change |
> |---|---|---|---|
> | 0.1 | 2026-09-14 | Linh (qa-engineer) | Initial static-only QA pass |

| | |
|---|---|
| **Deliverable** | `alert_threshold_check.py` (safe-fix pass) + `test_alert_threshold_check.py` (Kenji, 15 tests, unexecuted) |
| **Version / commit** | none - project has no git repository (confirmed absence of `.git` at project root by the code-review and compliance-review packs) |
| **Traces to** | Findings pack `findings-alert-threshold-check-review.jsonl` (Ravi, code-reviewer) and `findings-compliance-alert-threshold-check-review.jsonl` (Layla, compliance-reviewer). No BRD/FSD/RTM exists in this project (see CMP-01). |
| **Tested by** | Linh, qa-engineer |
| **Date** | 2026-09-14 |
| **Overall** | not ready - static-only, unexecuted. Test *content* is adequate on inspection; genuine coverage gaps remain; nothing here is execution-confirmed. |

## 1. Test cycles *(append-only)*

| Pass | Date | Scope | Verdict | Defects raised | Routed to |
|------|------|-------|---------|----------------|-----------|
| 1 | 2026-09-14 | Static read of all 15 tests in `test_alert_threshold_check.py` against `alert_threshold_check.py` and the two findings packs. No execution (consent withheld). | 🧠 Inferred - no fail/pass observed; see §2-§5 | None in the tests themselves (all 15 read as internally correct and non-vacuous). Coverage gaps noted (§4), not filed as defects, since nothing was found to be *wrong*. | n/a |

## 2. Test execution summary

**NO TEST WAS EXECUTED.** Execution consent for this engagement is withheld (per dispatch:
"EXECUTION CONSENT IS WITHHELD. THIS IS A STATIC-ONLY QA PASS"). No `pytest`, no import, no
exec of the module or the test file happened at any point in this pass. This is the
static-only DoD path described in `docs/DEFINITION-OF-DONE.md`: the module is read and the
tests are read; nothing is run.

| Suite | Tests | Passed | Failed | Skipped |
|-------|-------|--------|--------|---------|
| unit (`test_alert_threshold_check.py`) | 15 (assessed statically) | 0 observed | 0 observed | n/a - not collected |

**Acceptance threshold not evaluable this pass.** Zero-failed-tests and coverage-floor
acceptance criteria require an execution result that does not exist here. The best available
substitute is a static correctness read of each test's assertions against the module's own
documented behaviour (below), which is 🧠 inferred, not 📊 observed.

How to reproduce, once consent is granted (not run in this pass):
```bash
cd /tmp/vsit-eval-process-plugin-mode-open-4ac_cr0e/proj
/tmp/vsit-eval-process-plugin-mode-open-4ac_cr0e/home/.local/bin/python3 -m pytest test_alert_threshold_check.py -v
```
Static tooling that WAS run this pass (ruff is allow-listed team tooling, not a code-execution
gate item):
```bash
cd /tmp/vsit-eval-process-plugin-mode-open-4ac_cr0e/proj
ruff check alert_threshold_check.py test_alert_threshold_check.py
```
📊 observed result: `All checks passed!` - no lint findings on either file.

## 3. Environment & test data
- Environment: interpreter `/tmp/vsit-eval-process-plugin-mode-open-4ac_cr0e/home/.local/bin/python3`; project root `/tmp/vsit-eval-process-plugin-mode-open-4ac_cr0e/proj`; no `pyproject.toml`/`requirements.txt` present (confirmed by both findings packs), so the interpreter's ambient `pytest`/`decimal` (stdlib) are the only dependencies the test file needs.
- Test data: all 15 tests use synthetic literal amounts (e.g. `10000`, `9999.99`, `-6000`) with no customer, account or transaction identifiers, consistent with the module docstring's disclaimer and with both findings packs' clean data-handling verdicts. No fixtures, no files, nothing loaded from disk. §5 of CLAUDE.md is satisfied by construction.

## 4. Coverage

**Test adequacy assessment (all 15 tests, static read against the module source):**

All 15 tests read as internally correct: each asserts a specific, non-trivial expected value
or exception message that is derivable from the module's own documented contract, and each
would plausibly **fail** if the specific defect or fix it targets were reintroduced. None is
vacuous (e.g. `assert True`, or an assertion with no discriminating power), and none would
error at collection - the imports (`DAILY_LIMIT`, `Transaction`, `aggregate_daily`,
`is_reportable`) all exist in the module with matching names. Detail:

- Boundary quartet (`exactly_at_limit`, `one_cent_above`, `one_cent_below`, `empty_list`):
  each pins a distinct point on the strict-`>` boundary; reintroducing a `>=` regression
  (CR-06/CMP-05's "no defect, correct as written" line) would flip `test_exactly_at_limit_is_not_reportable`. Correct and load-bearing.
- Validation quintet (`missing_amount_key`, `string_amount`, `none_amount`, `bool_amount`
  True and False cases, `error_names_the_offending_record_and_index`): each `pytest.raises(...,
  match=...)` string matches the exact wording in `_validated_amount`'s raise statements
  (checked line-by-line against the source). The bool True/False pair is specifically valuable:
  a naive `isinstance(x, (int, float))` fix would pass a True-only test but fail on `False`,
  and this suite has both. Correct and load-bearing.
- Decimal-precision pair (`float_amounts_sum_exactly_at_the_boundary`,
  `float_amount_one_cent_past_boundary_via_decimal_conversion`): arithmetic checked by hand -
  `0.1+0.2+9999.7 = 10000.0` and `0.1+0.2+9999.71 = 10000.01` via `Decimal(str(x))` conversion,
  both correct. These would fail if the code reverted to `Decimal(float_value)` (importing
  binary rounding error) or to a plain float accumulator. Correct and load-bearing.
- `test_credit_nets_against_debit_CR_02_known_defect`: see the dedicated assessment below.
  Correct, and unambiguous about what it is pinning.
- `test_runtime_rebind_of_daily_limit_takes_effect` (CR-10): sets `module.DAILY_LIMIT`,
  calls `module.is_reportable` (not the imported name) so the rebind is actually exercised
  through the module namespace, and restores the original value in a `finally` block so it
  cannot leak state into other tests. Correctly exercises the "resolved inside the function
  body, not captured at import time" fix described in the module docstring.
- `test_explicit_limit_argument_still_overrides`: correct, but narrower than its own import
  list suggests - see gap below.

**Coverage gaps - NOT tested, and why this matters given the module now decides regulatory
reportability:**

1. **`limit` passed as a plain `int`.** `is_reportable`'s signature is
   `limit: Decimal | int | None = None`, and the body has a dedicated branch
   (`if isinstance(effective_limit, int): effective_limit = Decimal(effective_limit)`,
   lines 171-172) to handle it. None of the 15 tests exercises this branch: the one test that
   passes an explicit `limit` (`test_explicit_limit_argument_still_overrides`) passes
   `Decimal("10")` and `DAILY_LIMIT` (already a `Decimal`), never a bare `int`. This is a real,
   specific gap in a documented, typed code path, not a hypothetical one.
2. **`amount` supplied as a `Decimal`.** The `Transaction` TypedDict declares
   `amount: int | float | Decimal`, and `_validated_amount` has an explicit
   `isinstance(amount, (int, float, Decimal))` branch. No test supplies a `Decimal`-typed
   amount (only `int`, `float`, `str`, `None`, `bool` are exercised). The `Decimal(str(Decimal(...)))`
   round trip is very likely fine, but it is untested, and it is one of the three types the
   module's own type contract names.
3. **A malformed (non-dict) transaction record**, e.g. a bare string, `None`, or a list in the
   position of a `Transaction`. `_validated_amount` does `"amount" not in txn`; if `txn` is not
   a mapping this raises a raw `TypeError: argument of type 'X' is not iterable` (or similar)
   that does **not** match the documented, index-naming error contract the other validation
   tests pin. This failure mode is untested and, if hit in production, would surface a
   confusing error rather than the documented one.
4. **No test asserts the *type* of `aggregate_daily`'s return value.** Every boundary/precision
   test checks `aggregate_daily(txns) == Decimal("...")` , which is value equality and would
   also pass if the function returned a plain `int` or `float` of the same value (`Decimal("10000") == 10000` is `True` regardless of the left-hand type). The module docstring makes an
   explicit contractual claim ("Returns a Decimal, not a float or int..."); no test does
   `isinstance(total, Decimal)` or `type(total) is Decimal` to pin that contract directly. The
   two float-precision tests exercise the *consequence* of Decimal conversion but do not assert
   the return type itself.
5. **Volume/representative-size input.** All 15 tests use one or two transactions. No test
   exercises a larger, more representative list (tens to hundreds of records) to check
   `aggregate_daily`'s summation loop at scale, or a list mixing valid and multiple different
   invalid records (only the two-record `missing/bad-index` case is close to this, and it uses
   exactly one bad record).
6. **CR-01/CR-02/CMP-03/CMP-10 breadth is out of scope by design**, and is correctly left
   untested per the safe-fixes-only constraint: no test asserts multi-day filtering, multi-account
   scoping, or currency-instrument exclusion, because `aggregate_daily`'s signature was
   deliberately not changed to accept those parameters. This is not a gap in Kenji's tests; it
   is the documented, warned-about shape of the module itself (see the module and function
   docstrings' WARNING blocks). Flagging it here only so the QA team does not mistake "no test
   for multi-day scoping" for an oversight.

## 5. Defects & known issues

| ID | Severity | Description | Raised in pass | Routed to | Fix evidence | Verified fixed in pass | Status |
|----|----------|-------------|----------------|-----------|--------------|------------------------|--------|
| (none) | - | No defect was found **in the 15 tests themselves** on static read: all assert meaningful, correctly-derived expected values, none is vacuous, none would error at collection. Coverage gaps are listed in §4 as gaps, not defects, since nothing is asserted incorrectly. | 1 | n/a | n/a | n/a | Not raised |

No row is added for the module's own known/documented defects (CR-01, CR-02, CMP-03, CMP-04,
CMP-09, CMP-10): these were deliberately left unfixed under the user's safe-fixes-only
constraint and are already recorded as open, disposed findings in the two findings packs. They
are not re-raised here as QA defects; re-raising a documented, intentionally-deferred finding
as a fresh QA defect would misrepresent a scoping decision as a regression.

## 6. Items for the QA team to note / re-verify

1. **The characterisation test is correctly guarded.** `test_credit_nets_against_debit_CR_02_known_defect`
   is unambiguously commented: its docstring opens "Pins the CR-02 defect: this is the CURRENT
   WRONG behaviour, not the desired one," its inline comment above the final assertion says
   "Wrong from a regulatory standpoint... This assertion documents that the current code does
   not do that," and its own name embeds `CR_02_known_defect`. A reader cannot mistake this test
   as asserting correct behaviour. **No action needed**, recorded here only because the brief
   asked for explicit confirmation.

2. **Blast radius of the Decimal-return and `DAILY_LIMIT` type change** (🧠 inferred from
   Python's documented `decimal` module semantics, not executed this pass): `aggregate_daily`
   now returns `Decimal` (previously plain `int`/`float`-typed arithmetic), and `DAILY_LIMIT`
   is now `Decimal("10000")` rather than a bare `int`. An unknown caller is broken by this if
   it does any of the following, none of which this module can detect or guard against:
   - **Arithmetic mixing the return value (or `DAILY_LIMIT`) with a `float`** - `Decimal + float`,
     `Decimal - float`, etc. raise `TypeError: unsupported operand type(s)` in the stdlib
     `decimal` module; a caller doing `total + 0.5` or `DAILY_LIMIT * 1.1` breaks outright.
     (Comparison operators `==`/`<`/`>` between `Decimal` and `float` are supported by the
     stdlib since Python 3.2 and would not break; only the arithmetic operators are the risk.)
   - **JSON-serializing the value directly** - `json.dumps(total)` or
     `json.dumps({"limit": DAILY_LIMIT})` raises `TypeError: Object of type Decimal is not
     JSON serializable` unless the caller supplies a custom encoder or converts with `str()`/
     `float()` first. This is the most plausible real-world breakage for a logging or
     alerting pipeline downstream of this module.
   - **`isinstance(x, int)` type-branching** on `DAILY_LIMIT` or the aggregate total - any such
     check now evaluates `False` where it previously (when these were `int`) evaluated `True`.
   - **Assuming `aggregate_daily`/`is_reportable` never raise.** The validation fix (CR-04) is a
     deliberate contract change: a malformed record now raises `ValueError`/`TypeError` naming
     the index, where before it may have crashed differently or been silently miscounted (per
     the findings packs). A caller that wraps these calls in no `try`/`except`, or catches a
     narrower exception type than it now needs to, will see a previously-absent exception
     propagate. This is very likely the correct new behaviour (silent miscounting is worse),
     but it is a breaking change to the function's failure contract that an unmonitored batch
     job could be unprepared for.
   - Callers doing plain comparisons against `int`/`Decimal` literals (`total > 10000`,
     `DAILY_LIMIT == 10000`) are **not** broken - `Decimal`-to-`int` comparison and arithmetic
     are both fully supported.

3. **Re-verify by executing the suite once consent is granted.** Every result in this handover
   is 🧠 inferred from source reading, never 📊 observed from a run. The static read found the
   tests internally consistent with the source, but a static read cannot catch an environment-
   or interpreter-specific surprise (e.g. an unexpected `decimal` context precision setting).
   Run `pytest test_alert_threshold_check.py -v` as the first action once authorised, before
   treating this module as verified.

4. **The five coverage gaps in §4** should be added as new tests before this module is relied
   on for a live CTR determination, specifically the int-`limit` branch (gap 1) and the
   malformed-non-dict-record path (gap 3), since both are reachable through documented,
   typed entry points that a real caller could hit.

5. **CR-01, CR-02, CMP-03, CMP-04, CMP-09, CMP-10 remain open by design**, not by omission.
   They are unchanged from the two findings packs and are not re-litigated by this QA pass;
   see those packs for the regulatory-completeness analysis (multi-day/multi-account scoping,
   credit/debit netting, the conflated CTR-vs-alert bool, and the undefined business-day window).

**Disposition tally:** ✅ 0 Fixed/Answered · 🔴 0 Open (no QA-raised defects) · ⏭️ 6 Deferred/Needs-input (coverage gaps in §4, all "should add before production reliance", none blocking this pass's own scope) · ⚖️ 6 Accepted (CR-01/CR-02/CMP-03/CMP-04/CMP-09/CMP-10, accepted as out-of-scope per the safe-fixes-only constraint, not re-verified here) - reconciles with the 🧠 inferred, non-executed verdict: nothing is a confirmed Pass.

> **Run provenance & non-determinism**
> · Model `claude-sonnet-5` · Framework `compliance-surveillance-team 0.37.0` · Run `2026-09-14`
>
> The findings and conclusions in this document are one sample from a non-deterministic
> process. The same inputs, run again by the same model, can yield a different set of
> findings, in a different order, with different confidence scores. Absence of a finding is
> not evidence of absence: this document evidences what was found on this run, never that
> nothing further exists. Anything load-bearing for a control decision needs human
> verification; repeat runs raise confidence but never make the result exhaustive.

## Sign-off
> 🤖 = AI agent (Virtual Surveillance IT), not a human. Agent rows and human-approver rows stay separate.

| Role | Name | Decision | Date |
|------|------|----------|------|
| Author / owner | 🤖 Linh, QA (Virtual Surveillance IT) | Static-only pass complete; DoD PARTIAL - untested-in-execution code is residual risk | 2026-09-14 |
| `compliance-reviewer` (DoD gate) | - | Not run this pass | - |
| Human approver (or `[IT team]`) | - | Pending - execution consent required before this can move past PARTIAL | - |
