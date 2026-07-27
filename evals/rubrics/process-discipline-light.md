# Rubric: process discipline - LIGHT profile engagements (/engage-light)

The standing process rules, adjusted for the one thing the light profile legitimately
changes: the close artifact set. Light writes **NO delivery report**; the
**engagement-summary email STAYS, kept SHORT** (user ruling 2026-07-27: every close in
every profile ends with Morgan's email - a few lines: what was done, evidence in one line,
residual risk, one next step). Judging a light run against the standard rubric mis-scores
the report's absence; this rubric scores the light close as designed. Everything else is
unchanged from `process-discipline.md`.

| Dimension | What "good" looks like | Weight |
|---|---|---|
| **Closing artifacts (light)** | The engagement closes via the state (`set-status closed` after team + finalise), START-HERE reads ✅ CLOSED, and a SHORT engagement-summary email exists (`.txt`, signed as Morgan, "Hi," if the requester is unknown; what was done / evidence one-liner / residual risk / one next step) - while NO delivery report exists (its presence is the defect in a light close). Never a dead end. | 0.30 |
| **Right-sizing stated** | Before fanning out, the PM states in one line how many agents will be engaged and why; light is capped at 2-3 agents, no parallel fan-outs. | 0.25 |
| **Evidence tagging** | Data insights carry 📊 observed (with the metric/sample) or 🧠 inferred (with the assumption stated); no inference presented as measured fact. | 0.25 |
| **Dual-artifact rule** | The artifacts light does produce exist in `.md` **and** rendered `.html`; the mechanical gate (`scripts.check_artifacts`) is run or its result stated. | 0.20 |

**Pass:** weighted score >= 0.75 AND no auto-fail.
**Auto-fail:** a delivery report written in a light close; an inference explicitly presented as 📊 measured;
fanning out without any statement of the intended agent count; more than 3 agents or a
parallel fan-out in a light engagement; offering a phone call/meeting anywhere.
