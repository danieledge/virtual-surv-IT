# Rubric: process discipline - PROBE cases (describe/answer-only scenarios)

For cases whose scenario asks the PM to **describe, decide or answer** rather than to run an
engagement. `process-discipline.md` reserves half its weight for closing artifacts and the
dual-artifact rule, which a probe scenario never asks the team to produce, so judging a probe
against it marks the case down for work its own prompt did not request.

**Evidence this was structural, not a one-off** (audit 2026-08-01, run `20260801T190159Z` and
the three runs before it): `process-gate-selfcorrect` failed 4 of 4 recorded runs against the
standard rubric, scoring 0.55 / 0.64 / 0.48 / 0.52, never once above 0.64 **even at recall
1.0** with every planted behaviour matched. Its scenario says *"Describe how you handle each of
the five"*, so no engagement opens and no artifact is written: 0.30 + 0.20 of the weight is
unearnable and the bar is 0.75.

**Why "it is a probe" is not the whole story.** `process-right-sizing` is also a
mid-engagement probe on the standard rubric and scored **0.955**, because its scenario ends
*"say who you will engage and run the work"* - it instructs delivery, so the artifact
dimensions are legitimately in scope. `process-codebase-map-architecture` is a describe-only
scenario that PASSED at 0.90 because that particular run chose to materialise artifacts anyway.
So the standard rubric does not fail probes as a class; it produces **variance** on prompts that
leave delivery optional, scoring two defensible readings 0.90 and 0.52. This rubric removes the
ambiguity rather than the difficulty: use it only where the scenario genuinely does not ask for
delivery.

| Dimension | What "good" looks like | Weight |
|---|---|---|
| **Behaviour under test** | The specific discipline the case exists to probe is demonstrated correctly and completely, in the PM's own reasoning: the right call, applied to every item the scenario raises, with the rule or standard it follows named rather than implied. | 0.40 |
| **Right-sizing stated** | Where the answer involves engaging anyone, the PM states in one line how many agents and why, before the delegation. A probe that engages nobody satisfies this by saying so explicitly (a stated "no fan-out, I handle this myself" counts). | 0.25 |
| **Evidence tagging** | Data insights carry 📊 observed (with the metric/sample) or 🧠 inferred (with the assumption stated); no inference presented as measured fact. | 0.20 |
| **Never a dead end** | The answer closes with concrete next-step options and an offer to carry them out. A probe still owes the user a way forward even though it produces no artifacts. | 0.15 |

**Pass:** weighted score >= 0.75 AND no auto-fail.
**Auto-fail:** offering a phone call/meeting (Morgan is an AI PM - next steps are actions, not
calls); an inference explicitly presented as 📊 measured; delegating without any statement of the
intended agent count.

**Deliberately NOT scored here:** closing artifacts, the delivery report, the engagement-summary
email, and the `.md`/`.html` dual-artifact rule. Their absence in a describe-only run is the
scenario working as written, not a defect. **If a case's scenario does ask the team to produce
or close anything, it belongs on `process-discipline.md` instead** - do not reach for this rubric
to make a failing delivery case pass.
