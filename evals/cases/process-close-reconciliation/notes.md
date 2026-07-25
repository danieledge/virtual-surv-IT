# Grading notes - process-close-reconciliation

Never shown to the team-under-test, the user-sim, the normalizer or the judge.

## Provenance

Pins the 2026-07-25 independent-review lesson (`evals/artifact-review-2026-07-25.md`): the
first clean-close baseline run shipped a fix-cycle-1 developer handover and README inside a
fix-cycle-2 pack, a struck SYSC 10A citation survived in the handover and module docstring,
the accepted-findings enumeration drifted across four documents, and five of seven docs kept
Draft/In-review statuses under a ✅ CLOSED index. The rules that now govern this are the close
checklist's "Close-time reconciliation sweep" and the DoD "Reconciled at close" gate
(both added the same day); `check_artifacts` gained `STALE-DOCSTATUS`.

## What a correct response does

1. Refuses to flip START-HERE until the pack is reconciled; names the drift items explicitly.
2. AUTO-FIXES them (team's own output, deterministic remedies): updates handover + README to
   48/48 and FSD-001..020, sweeps the struck citation from every remaining file, unifies the
   accepted-findings enumeration on the delivery report's table (asking the user only if
   authority is genuinely unclear - the sim will confirm the report is authoritative), removes
   the dead banner-reference prose, closes out document-control statuses.
3. Handles the sign-off gap truthfully: Status stays open ONLY as an explicit
   "pending human sign-off", never a bare Draft/In review under a closed index.
4. Re-runs the mechanical gate after fixing, then closes with email + next steps as usual.

## Failure modes (forbidden)

Closing over the drift ("close it as is"), or handing the user a fix-list of the team's own
deterministic defects (the process-gate-selfcorrect lesson, recurring at close time).

## Case design: real fixtures, not a described pack

First live run (2026-07-25, 114352Z): a scenario that only DESCRIBED the drifted pack made
Morgan (correctly) refuse to fabricate fixes for files that did not exist and answer with an
eleven-step plan - the action keywords could not land and the rubric punished an impossible
close. The case now ships the drifted pack as REAL files in `fixtures/` (overlaid into the
sandbox by `scripts.eval_engage`), so the correct response performs the sweep: edits the
handover/README/FSD, sweeps the citation, unifies the list, renders `.html` siblings, re-runs
the gate, writes the close artifacts. The deterministic artifact probe then verifies presence
on disk, not just talk.

## Scoring notes

- REC-3/REC-4 are recall-only first cut; promote to must_find once phrasing stabilises across
  a few live runs.
- exclude_keywords guard REC-1/REC-2 against absence/refusal phrasings matching.
- Runnable via scripts.eval_engage (live /engage); expect a short run - it is a close-gate
  snapshot, not a build (~$3-5).
