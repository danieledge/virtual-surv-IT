---
description: Take on legacy / poorly-built code — assess, prioritise, fix, re-review, hand over
argument-hint: <path/glob of the legacy code>
---

Take on existing **legacy / poorly-built code** and bring it up to standard: **$ARGUMENTS**

PM oversees an agile remediation loop (CLAUDE.md §6; gate: `docs/DEFINITION-OF-DONE.md`).
This is **audit mode** — pre-existing issues are in scope, not filtered out.

1. **Assess.** Run `/deep-review` and `/performance-review` over the code. Capture findings
   with confidence scores and evidence. (No real data — work on synthetic/masked, §5.)
2. **Characterise & prioritise.** Produce a **remediation plan**: findings ranked by
   risk × impact × effort, with a recommended order. Surface anything regulatory (secrets,
   PII, broken traceability, undocumented thresholds) as top priority — never deferred.
3. **Establish a safety net.** Have `qa-engineer` add characterisation tests that capture
   current behaviour **before** refactoring, so changes are provably safe.
4. **Fix in iterations.** Route fixes to the right builder (`rules-developer` /
   `cloud-architect` / `ml-engineer`); after each batch, **re-review and re-profile** to show
   the finding is closed and nothing regressed. Loop until no Critical remains (or the user
   calls it).
5. **Evidence the improvement.** Record before/after (findings closed, tests added, perf
   delta).
6. **Hand over.** Run `/handover` to produce the developer + QA handover pack.

Deliver everything under `artifacts/` in `.md` + `.html`. Stop for human sign-off before
anything touching live systems.
