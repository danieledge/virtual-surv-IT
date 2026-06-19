# Review of the team & pipeline (2026-06-19)

A critical review of this repo's readiness to take **real delivery** — including legacy code
remediation — where **real developers and QA reviewers** will rely on the outputs.

## What's already strong

- **Clear roles + safe defaults:** advisory (read-only) vs build agents; secrets/PII never
  reach an agent; masking + synthetic data pipeline with a validating gate.
- **A real delivery flow:** PM front door, requirements→spec→build→review, traceability spine
  (RTM), artifacts in `.md` + `.html`.
- **Detailed code review:** `code-reviewer` (quick/deep) drives standard linters across 5
  languages, with confidence scoring, false-positive filtering and transparency.

## Gaps for real-world handover (what this change closes)

| # | Gap | Risk | Fix |
|---|-----|------|-----|
| 1 | **No performance review.** "Performance" was a bullet in code-reviewer, not a real capability. Surveillance runs on huge volumes — unscaled code fails in prod, not in tests. | Slow/again-unusable code passes review. | New **`performance-reviewer`** agent + `/performance-review` + performance report, driving established profilers. |
| 2 | **No developer handover.** Nothing a real developer can pick the work up from. | Delivery isn't maintainable by the receiving team. | `developer-handover.md` template + `/handover`. |
| 3 | **No QA evidence.** No record of what tests ran, what passed, what's *not* covered, what QA should re-check. | QA can't sign off; no audit evidence of testing. | New **`qa-engineer`** agent + `qa-handover.md` (test evidence) + `/handover`. |
| 4 | **No Definition of Done.** "Done" was implicit, so confidence was inconsistent. | Variable quality; reviewers can't trust outputs. | `docs/DEFINITION-OF-DONE.md` — an explicit, evidenced gate every delivery meets. |
| 5 | **No legacy remediation path.** Review existed, but not assess→prioritise→fix→re-review for "old, not well-built code". | Can't take on the actual legacy workload. | `/remediate` workflow with before/after evidence. |
| 6 | **Independence of testing.** The builder wrote and judged its own tests. | Marking own homework. | `qa-engineer` is a separate role from the builder. |

## The confidence model (how outputs become trustworthy)

Every delivery now ends with **evidence a human can check**, not just code:

```
build ─▶ tests (independent QA) ─▶ code review (deep) ─▶ performance review
      ─▶ compliance review ─▶ Definition of Done met ─▶ handover pack (.md + .html):
         · Developer handover   · QA handover (test evidence)   · Review + performance reports
         · RTM (traceability)   · sign-off
```

A real developer gets a maintainable handover; a QA reviewer gets evidence of what was
tested and what to re-check; an auditor gets the traceable thread. That is what lets us hand
real delivery to this team.
