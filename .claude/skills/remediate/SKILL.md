---
description: Take on legacy / poorly-built code - assess, prioritise, fix, re-review, hand over
argument-hint: <path/glob of the legacy code>
---

Take on existing **legacy / poorly-built code** and bring it up to standard: **$ARGUMENTS**

**If no target was given, first ask the user where the code is** (path/glob, repo/branch, or
paste it) and wait - don't assume a target.

PM oversees an agile remediation loop (CLAUDE.md §6; gate: `docs/DEFINITION-OF-DONE.md`).
This is **audit mode** - pre-existing issues are in scope, not filtered out.

1. **Assess.** Run `/deep-review` and `/performance-review` over the code. Capture findings
   with confidence scores and evidence. (No real data - work on synthetic/masked, §5.) Legacy
   code here is often **AI-assisted / vibe-coded** - `/deep-review` asks, and if so the
   remediation pack should include the **🧑‍💻 Prompting guidance** (how to prompt for a better
   first draft next time; see `docs/review/output-format.md`).
2. **Characterise & prioritise.** Produce a **remediation plan**: findings ranked by
   risk × impact × effort, with a recommended order. Surface anything regulatory (secrets,
   PII, broken traceability, undocumented thresholds) as top priority - never deferred.
3. **Establish a safety net.** Have `qa-engineer` add characterisation tests that capture
   current behaviour **before** refactoring, so changes are provably safe.
4. **Fix everything you safely can - in this pass, not a "next sprint".** Route fixes to the
   right builder (`rules-developer` / `platform-engineer` / `ml-engineer`); after each batch,
   **re-review and re-profile** to show the finding is closed and nothing regressed. **Do not
   defer fixable work** - keep going until everything that *can* be safely fixed *is* fixed
   (Critical → Warning → Medium → the worthwhile 🔵 style items). The only things left unfixed
   are those that genuinely need a **human decision** (a design call, a risky change, missing
   domain input) - mark those **🔴 Open (needs human developer review)** with the reason, **not**
   "⏭️ deferred to a later sprint". Deferral is a last resort with an explicit tracking
   reference and a reason it can't be done now - never a way to punt work you could have done.
5. **Evidence the improvement - with a clear disposition.** Record before/after per finding:
   ✅ fixed (what changed) · 🔴 still open · ⚖️ accepted (rationale) · ⏭️ deferred, plus the perf
   delta (incl. **total time saved**). After a reimplementation, **reconcile** explicitly: which
   original blockers the rework resolved and which remain - never leave it ambiguous whether the
   blocking issues still stand. Anything with no straightforward fix → **🔴 Open (needs human
   developer review)** with the reason and options.
6. **Hand over.** Run `/handover` to produce the developer + QA handover pack.

Deliver everything under `artifacts/` in `.md` + `.html`. Stop for human sign-off before
anything touching live systems.
