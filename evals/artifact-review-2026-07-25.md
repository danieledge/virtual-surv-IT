# Independent artifact review - process-full-lifecycle baseline run (093815Z)

Three independent fresh-context reviewers (documentation quality; code vs spec, static-only;
claims-vs-evidence audit) over the clean-close run's delivery pack
(`evals/runs/20260725T093815Z/process-full-lifecycle/sandbox/`, preserved read-only).
Companion to `eval-engage-shakedown-2026-07-25.md`.

## Consolidated verdict

**Materially truthful, traceable and well-engineered; the failure mode is close-time
reconciliation, not substance.** No fabrication found anywhere: the 48-test count is exact on
disk, all 20 FSD requirements and 22 Gherkin scenarios exist as claimed, every RTM-cited
function/test resolves to a real definition, the boundary matrix (9:59 / 10:00 inclusive /
10:01, anchor-to-survivor) is genuinely covered, thresholds carry rationale + date per
convention, stdlib-only and no-secrets/PII hold, and the pack proactively discloses its own
weaknesses (un-QA'd final fix cycle, unverified 3.9 target, uncalibrated threshold).

## Convergent findings (deduplicated, ranked)

1. **Cycle-2 fixes never propagated to sibling artifacts** (all three reviewers). Developer
   handover and deliverable README frozen at fix cycle 1 in a fix-cycle-2 pack (44/44 vs 48,
   stale FSD-001..017 range, "not yet reconciled" claims that were closed); RTM postdates the
   final code yet carries no N1/N3 rows or `N1N3PmFixTests` reference; rtm.md prose still
   cites the interim banner the close correctly removed.
2. **Test suite `__main__` guard sits mid-file** (code, major): `python3 tests/test_dedupe_alerts.py`
   silently runs 44/48 and reports OK, skipping the only negative reconciliation test. The
   documented entry points (unittest discover / pytest) collect all 48.
3. **Withdrawn SYSC 10A citation survives** in developer-handover §1 and the module docstring,
   although brief/FSD/RTM/delivery report all record it withdrawn-as-misapplied (two reviewers).
4. **Status machinery contradicts the CLOSED index** (docs): 5 of 7 docs still read
   Draft/In-review with pending sign-offs under a "✅ CLOSED, everything final" START-HERE;
   defensible only for human sign-off, not stated as such.
5. **"Six accepted findings" has drifting membership across four documents** (docs + claims):
   the count survives everywhere, the enumeration doesn't; N2 is absent from the handover list
   readers are directed to.
6. **QA independence evidence deleted, not preserved** (code + claims): both independent QA
   suites were tmp-written and removed; no preserved QA run covers the shipped 48-test state.
   A few measured-tagged claims (600-run sweep, bandit/semgrep/gitleaks) leave no artifact.
7. Minor code findings: read/decode errors exit 1 colliding with `EXIT_FILE_NOT_FOUND`
   (undermines part of the C2 contract); AC-12 determinism fixture decayed to passthrough
   after C1/D8; ragged-row overflow cell silently dropped on write; FSD-014 ordering deviation
   documented in code but never amended in the FSD nor tested.

## What this feeds back into the team/evals

- The close checklist's reconciliation sweep stops at artifacts/: it missed code-adjacent docs
  (README, module docstring) and content-level staleness (counts, ranges, prose banner refs).
  Candidate golden case: "close-time reconciliation" seeding a stale sibling doc.
- Candidate DoD gate hardening (human-applied): STALE-STATUS could extend to document-control
  Status fields under a CLOSED index; a close-time grep for withdrawn citations.
- QA evidence retention: preserve independent suites under artifacts/ (or a hash of them)
  instead of deleting - the independence claim is currently unfalsifiable.
- The `__main__`-guard-mid-file defect is a good seed for a future review golden case.

Reviewer detail (full findings lists with file:line evidence) is in the session transcripts of
the three review agents; this file records the deduplicated consensus.
