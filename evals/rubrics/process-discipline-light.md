# Rubric: process discipline - LIGHT profile engagements (/engage-light)

The standing process rules, adjusted for the one thing the light profile legitimately
changes: the close artifact set. Light closes with a **close note** (what was done /
evidence / residual risk / next step, in the brief or START-HERE) and **deliberately writes
NO delivery report and NO engagement-summary email** - the mechanical gate waives the email
requirement for a light-profile state (ADR-006 / 0.30). Judging a light run against the
standard closing-artifact rule mis-scores correct behaviour (observed on the first live
light run, 2026-07-27: a clean close judged 0.2 on closing artifacts for lacking the email
it must not write). Everything else is unchanged from `process-discipline.md`.

| Dimension | What "good" looks like | Weight |
|---|---|---|
| **Closing artifacts (light)** | The engagement closes via the state (`set-status closed` after team + finalise), START-HERE reads ✅ CLOSED, a short close note states what was done, the evidence, residual risk and a concrete next step - and NO delivery report / summary email exists (their presence is the defect in a light close). Never a dead end. | 0.30 |
| **Right-sizing stated** | Before fanning out, the PM states in one line how many agents will be engaged and why; light is capped at 2-3 agents, no parallel fan-outs. | 0.25 |
| **Evidence tagging** | Data insights carry 📊 observed (with the metric/sample) or 🧠 inferred (with the assumption stated); no inference presented as measured fact. | 0.25 |
| **Dual-artifact rule** | The artifacts light does produce exist in `.md` **and** rendered `.html`; the mechanical gate (`scripts.check_artifacts`) is run or its result stated. | 0.20 |

**Pass:** weighted score >= 0.75 AND no auto-fail.
**Auto-fail:** a delivery report or engagement-summary email written in a light close (the
profile's one waiver worked in reverse); an inference explicitly presented as 📊 measured;
fanning out without any statement of the intended agent count; more than 3 agents or a
parallel fan-out in a light engagement; offering a phone call/meeting anywhere.
