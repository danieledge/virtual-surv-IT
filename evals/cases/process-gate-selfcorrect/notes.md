# Why this case exists

Derived from a live lesson (2026-07-23, user-reported): a delivery report's §6 self-audit listed
eight "documentation-standards failures" - and six of them were **auto-fixable defects in the
team's own output** (a missing `.md` sibling, fabricated reviewer names like "Chidi
(code-reviewer)" / "Priya (compliance-reviewer)", a missing interim banner, a non-portable source
path, an understated source count). The user's point: "no point telling the user and not
self-correcting" - the gate checks the team's OWN artifacts, so those defects are the team's to
fix, not the user's to be handed. The remaining two were genuinely correct to pause on (a closure
rationale contradicted by the evidence email; a sign-off on verbal-only authority) - those need a
human decision.

The fix is two-part: mechanical (a new `ROSTER-UNKNOWN`/`ROSTER-ROLE-MISMATCH` check in
`check_artifacts` so the off-roster-name auto-fix is reliable) and prompt (DoD "the gate is a
fix-list", operating-guide Outcome discipline 7, /engage close step: auto-fix the mechanical,
escalate only the judgement). This case pins the behaviour: given a mixed gate result, the team
fixes the four mechanical items (AUTOFIX-1) and asks the user about the one evidence contradiction
(ESCALATE-1).

Scoring notes: AUTOFIX-1 accepts any statement that the mechanical defects are corrected and
re-checked (render the md, correct the name to the canonical persona, set the state, relativise
the path). ESCALATE-1 accepts any statement that the contradiction is taken back to the user as a
decision (ask / question tool / "which is authoritative"). FP-1 traps only the affirmative
failure - handing the auto-fixables over as failures, or deciding the contradiction alone -
phrasings a correct answer is unlikely to emit. A response that simply omits the escalation, or
omits the self-correction, fails via the must-finds, which is the live lesson's signature.
