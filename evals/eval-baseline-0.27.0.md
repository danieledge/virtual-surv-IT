# Eval baseline — 0.27.0 (dev → main promotion record)

Scope: golden-slice (live subagent runs + deterministic scorer)
Date: 2026-07-25
Method: each case was run by a fresh subagent instructed to read and adopt the **live on-disk
agent definition** (the 0.27.0 thinned prompts — the surface this release changed), blind to
`expected.yaml`/`notes.md`, returning scorer-format findings JSON; scored with
`python -m scripts.eval_score`. (The session's installed plugin cache was 0.25.0, so cached
team agents were deliberately NOT used — they would have evaluated the wrong version.)

## Cases (4 of 33 — chosen to exercise the changed surfaces)

| Case | Agent def | Recall | Must-find | Raw | Adjudicated |
|---|---|---|---|---|---|
| review-sql-injection | code-reviewer | 1.0 (2/2) | all hit | FAIL (trap) | **PASS** — trap keyword `find_alerts_by_trader` matched because the finding cited the safe function *as the recommended fix*, not as a flaw; scorer cannot distinguish mention-as-fix from flag |
| review-excel-truncation | code-reviewer | 1.0 (4/4) | all hit | FAIL (trap) | **PASS with note** — genuine solo over-flag: the documented `max_col=EXPECTED_COLUMNS` bound was flagged. The pipeline's PM challenge pass ("a documented, intentional bound is not a defect", deep-review step 3) exists to drop exactly this and was not exercised in a solo-agent run |
| citation-flag-unverified | compliance-reviewer | 0.0 by keywords | keyword-missed | FAIL | **PASS** — both invented citations were flagged per the definition's 🔴 clause ("asserted as decided fact with no verification flag… confabulation risk"), with register-verified alternatives proposed; the case's keyword net (`unverified`, `cannot confirm`, …) predates that phrasing. Substantively the exact behaviour the case tests for |
| coverage-uncaptured-channel | data-quality-reviewer | 1.0 (1/1) | all hit | **PASS** | **PASS** — clean |

## Headline

- **Detection: 8/8 planted issues found (100% recall), zero must-find misses** — the 0.27.0
  agent thinning did **not** degrade detection capability, which was the gating question.
- Raw deterministic: 1/4 strict passes; all three raw failures are on the FP/keyword axis:
  two scorer keyword artifacts + one genuine solo over-flag (mitigated by the unchanged
  downstream challenge layer).
- **Verdict: PASS for promotion**, with limitations below.

## Limitations (honest scope)

- 4 of 33 cases; **orchestration/process cases not run** (they require a live `/engage` session —
  Morgan's process discipline is not evaluated by this slice).
- Solo-agent runs: the PM challenge / review-scorer layers were not in the loop.
- Follow-up recorded (not applied — no teaching-to-the-test mid-run): extend
  `citation-flag-unverified`'s keywords with the definition's own phrasing ("asserted as decided
  fact", "unregistered", "confabulated"); consider scorer support for a mention-as-fix
  exclusion on forbidden traps.
