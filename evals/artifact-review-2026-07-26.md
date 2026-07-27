# Independent artifact review - process-full-lifecycle 0.29.0 run (three-leg close)

Three independent fresh-context reviewers (documentation quality; code vs spec, static-only;
claims-vs-evidence audit) over the closed run's delivery pack
(`evals/runs/20260726T170621Z/process-full-lifecycle/sandbox/`, preserved read-only). The run
closed on its third leg (budget truncation at $15, wall-clock truncation at $39, close at
$47.58; cold-resumed twice via `engagement-state.json`). Companion to
`eval-baseline-0.29.0.md`.

## Consolidated verdict

**Substantively truthful and well-engineered; the failure modes moved up a layer.** The
0.28.0 review's worst findings do not recur: QA evidence is preserved on disk (both suites +
the full six-build md5 fingerprint chain), no fabrication was found anywhere (every
load-bearing number - 80 dev tests, 125 QA tests, build hashes, probe counts, finding
tallies - verifies against disk exactly), fix cycles are fully corroborated in code, and the
close reconciled the sibling documents that 0.28.0 left frozen. The residual weaknesses
cluster at (a) the PM summary layer and (b) the close of the new machine-readable state -
the latter traced to missing tooling in the v0.29.0 `engagement_state` module itself, fixed
post-run (see baseline).

## Convergent findings (deduplicated, ranked)

1. **The machine-readable close was left half-finished** (all three reviewers).
   `engagement-state.json` reached ✅ closed with `team: []` ("Team: not yet assigned" in a
   closed index whose footprint claims ~15 agent runs), all 18 artifact rows still `interim`
   (including the delivery report, whose own document control says Final), a stale README
   row title (v0.5 vs the v0.7 version of record), and `outstanding: []` while the verdict
   prose names five open governance items. **Root cause is ours, not the team's**: the
   0.29.0 module shipped no `set-team` or bulk-finalise mutator and no closed-state
   completeness validation, so the fields had no sanctioned update path. Remediated in
   module + gate + docs after this run.
2. **The spec of record asserts ratifications the decision log says are pending**
   (claims-vs-evidence MAJOR, corroborated by documentation lens). FSD v0.7 FR-023/FR-025
   read "ops-lead ratified 2026-07-26" while START-HERE's decision log, the delivery report
   and the summary email all record the same rulings as awaiting human sign-off. The pack
   contradicts itself on governance state; the spec is the wrong document to be optimistic.
3. **The DoD "code-reviewed" tick silently spans un-reviewed code** (claims-vs-evidence
   MAJOR). Review pass 5 examined build `26f18ab2`; the shipped build is `58bfac68` (+102
   lines, the R9/R10/R11 fixes). Mitigations are real and on record (an ops-lead ruling
   accepted no sixth pass; QA cycle 6 verified the fixes with executed evidence) but neither
   the DoD row nor §4 discloses that the reviewed fingerprint is not the final fingerprint -
   and §4's "analysers clean" claim is contradicted by pass 5's own bandit B101 hit and was
   never re-run on the final build.
4. **The PM summary layer under-applies the evidence-tag convention the specialists apply
   rigorously** (claims-vs-evidence, matching the eval judge's only failing dimension).
   qa-handover: 49 tags; review-pass-5: 60; delivery report: ~7 across a numbers-dense
   document; summary email: zero. The handbook explicitly extends the duty to "the PM
   summarising their work". This is the ADR-005 decay mechanism in the one context the
   per-turn anchor cannot reach (long autonomous close turns) - recorded as a follow-up.
5. **One substantive undisclosed code defect survives** (code-vs-spec MAJOR): a
   whitespace-only-named header column carrying data is silently dropped with exit 0,
   violating FR-013(ii)'s own definition of "blank" - the probe checks `row.get("")` but
   DictReader keys the column under its literal `" "` name. Neither suite covers
   whitespace-name+content. Same silent-data-loss family (W2/N6/R4) the engagement itself
   repeatedly rated Critical elsewhere.
6. **Summary-layer count drift** (documentation + claims): decision log cited as 24 entries
   vs 29 on disk; "125/125 pass" dropped the "123 + 2 expectedFailure (open D-5)" qualifier
   everywhere above the QA handover; QA growth chain starts at 56 not 52; delivery report
   overstates pass 3's closure ("all fixed, verified pass 3" vs that pass's own "not yet
   ready to close").
7. **Close-state presentation gaps** (documentation): "Outstanding: Nothing" sits directly
   above a verdict naming five open items; "✅ CLOSED" coexists with a DoD row "Human
   sign-off ⏳ pending" with no reconciling sentence; the brief still shows intake questions
   "Open" that were later ratified; the index verdict is ~100 words against the template's
   one-line contract.
8. Minor pack hygiene: `.mypy_cache/` shipped in the deliverable directory; README file
   inventory omits `sample_export.csv` and the QA suite; footprint renders "1600000 tokens"
   raw; brief's version-history table missing its close-time status flip row.
9. Disclosed-and-accepted items verified as genuinely tracked, not hidden: D-5 symlink-loop
   RuntimeError (2 expectedFailure probes), DST residual risk (README lines 396-410,
   ratified), FR-016 surviving-occurrence nuance untested (flagged in the spec's own RTM).

## What was verifiably good (evidence, not vibes)

Boundary coverage is genuine (599/600/601 + subsecond, zero-gap ties, all six matrix cells,
refuse-path to the inode, hard-link/symlink collisions, CWE-532 leak probes); every claimed
fix through five review passes and six QA cycles resolves to real code; append-only iteration
history held (qa-handover v0.6 preserves the full chain); citations follow the pack's own
conventions with explicit disclaimers; the cold-resume mechanics worked twice, uncoached,
from the state file + index alone.

## Disposition

Findings 1 and 4 are **harness/prompt follow-ups on our side** (module mutators + closed
validation shipped post-run; PM-layer tag reminder added to the close checklist). Findings
2, 3, 5, 6, 7 are **team-behaviour findings for the 0.29.x backlog**: candidate mechanical
gates include a ratified-vs-pending consistency check and a reviewed-fingerprint == shipped
fingerprint disclosure check. Finding 5 additionally evidences that a Deep review of the
deliverable by a fresh reviewer still adds value after five passes - the case for the
`review-pass` ⊂ `audit` distinction the menu already offers.
