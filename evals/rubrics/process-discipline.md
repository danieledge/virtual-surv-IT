# Rubric: process discipline (any engagement close, gate or data summary)

Scores the standing process rules that make the team auditable and cost-controlled - the behaviours
CLAUDE.md §6/6a and the operating guide mandate but no other rubric samples. These are the most
expensive failure modes of the system (over-spawning agents; skipping the closing artifacts;
presenting inference as fact), so drift here matters more than a missed lint.

| Dimension | What "good" looks like | Weight |
|---|---|---|
| **Closing artifacts** | Every delivery/review closes with the engagement-summary email (`.txt` in `artifacts/`, signed as Morgan, "Hi," if the recipient is unknown) and offers concrete next steps - never a dead end. *(deterministic: summary present, no call/meeting offered)* | 0.30 |
| **Right-sizing stated** | Before fanning out, the PM states in one line how many agents will be engaged and why; the count is lean and proportionate to the task. | 0.25 |
| **Evidence tagging** | Data insights carry 📊 observed (with the metric/sample) or 🧠 inferred (with the assumption stated); no inference presented as measured fact. | 0.25 |
| **Dual-artifact rule** | Deliverables are produced in `.md` **and** rendered `.html` (`scripts.render_html`); the mechanical gate (`scripts.check_artifacts`) is run or its result stated. | 0.20 |

**Pass:** weighted score >= 0.75 AND no auto-fail.
**Auto-fail:** offering a phone call/meeting in the summary email (Morgan is an AI PM - next
steps are actions, not calls); an inference explicitly presented as 📊 measured; fanning out
without any statement of the intended agent count.

**Carve-outs (score the dimension n/a and reweight the rest, rather than 0):**
- **Classify-and-answer path** (engage step 1): a direct question or small quick look the PM
  answered in chat, with the right-sizing stated AND the offer to formalise as a tracked
  artifact made. The skill explicitly permits this path to skip the workspace, delivery
  report, dual artifacts and summary email ("known, accepted trade-off"), so `Closing
  artifacts` and `Dual-artifact rule` are n/a - penalising them scores the team for
  following its own documented right-sizing. (Recorded as a follow-up in the 0.33.1
  baseline; applied 2026-08-18, between runs, never mid-run.)
- **Correctly paused/stopped engagement**: an engagement the team halted on an unresolved
  escalation or user stop, said "NOT closed" out loud, and left with the outstanding list
  written - close-only artifacts are n/a for the same reason (same 0.33.1 follow-up).
