---
description: Drive a new detection scenario end to end - spec → SME review → implement → compliance review
argument-hint: <scenario name or regulatory requirement>
disable-model-invocation: true
---

Stand up a new detection scenario for: **$ARGUMENTS**

**If no scenario was given, first ask** what behaviour/obligation to detect and in which
domain (TM, trade, or comms), and wait - don't invent a scenario from a bare `/new-scenario`.

**Scope note:** `/new-scenario` is the lean path for a *single* detection scenario (one rule,
spec → SME → build → review). For a multi-unit deliverable built from a full requirements
pack, use `/build-solution` (the full orchestrator-workers fan-out) instead.

You are the orchestrator (CLAUDE.md §6). Do **not** write detection logic yourself - route
each step to the right agent and chain them in this session:

1. **business-analyst** - turn "$ARGUMENTS" into a spec using
   `docs/templates/scenario-spec.md` (obligation, data, detection requirements,
   true-positive / false-positive acceptance criteria). **Cite the obligation by RETRIEVING it
   from the regulatory register** (`python -m scripts.check_citations --typology <x>` /
   `config/regulatory-register.yaml`) - never invent a pinpoint article/section/rule; flag any
   citation not in the register as to-verify (ADR-001; `compliance-reviewer` runs the check).
2. **Domain SME** - pick by domain: `trade-surveillance-sme`, `tm-sme`, or
   `comms-surveillance-sme`. Have them review the proposed detection logic and thresholds.
   (Advisory/read-only - they recommend, they do not edit.)
3. **rules-developer** - implement under `rules/` with synthetic tests under `tests/`
   (synthetic data only - §5), thresholds documented with rationale + tuning date (§4).
   If the detection is model-based, route to **ml-engineer** instead, then **model-validator**
   for independent validation before sign-off.
4. **code-reviewer** - comprehensive code review of the implementation (correctness,
   security, maintainability) using the standard linters/analysers for the language.
5. **compliance-reviewer** - check auditability, the alert→logic→obligation trace,
   thresholds rationale, secrets/PII, and test coverage.
6. Produce the scenario doc from `docs/templates/scenario-doc.md` (a trade scenario's design
   detail can use `docs/templates/trade-scenario-design.md`; a comms scenario adds
   `comms-surveillance-policy.md` + `lexicon-spec.md`), then render it to `.html`:
   `python -m scripts.render_html artifacts/<scenario>.md` (every artifact ships as `.md` +
   `.html` - §8 / Definition of Done).

Confirm the **project's test suite** passes (`pytest` in this repo; Pester / JUnit / ScalaTest /
Jest / etc. in other stacks - use whatever the target uses), and check the result against
`docs/DEFINITION-OF-DONE.md` for the
items that apply to a detection scenario (traceable, tested, reviewed, documented).

**Close - don't dead-end (CLAUDE.md §6).** Summarise what was built (the rule, its tests, the
obligation it serves), then offer the next step with a recommendation - typically a
`/handover` pack for the dev/QA teams, or `/audit-review` for an independent robustness pass -
and wait for the user's choice. Stop for human approval before anything that touches live
systems.
