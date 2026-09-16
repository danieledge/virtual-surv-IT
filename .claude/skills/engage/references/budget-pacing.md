# Budget and day pacing

Read this only when the user has named a spend cap (now or at intake - many corporate users run
under a daily limit). Budgetless engagements skip all of this at zero cost - don't ask a
dedicated question when no cap was hinted at.

**Record it the same moment** the workspace opens: `set-budget --daily-usd <N> [--engagement-usd
<N>]`. Never invent a cap.

When a budget IS recorded (assessment rec 1+2, 2026-08-17):

- **(a) Day plan.** The brief's estimate is compared against the DAILY cap. When the estimate
  exceeds it, the plan section proposes a **day plan with gates falling at day boundaries** (e.g.
  day 1 spec + build, day 2 QA + reviews, day 3 close) rather than pretending it fits one day.
- **(b) Status at every gate.** `budget-status` runs at every gate and its DAILY/HEADROOM line is
  stated beside the team-sizing line (degrade ladder on approaching/exceeded:
  `docs/team-operating-guide-orchestration.md`).
- **(c) No telemetry.** `HEADROOM=unknown` means the box has no spend telemetry: say so once,
  pace on the `DISPATCHES` line against the agents cap, and ask the user whether to continue on
  that basis (auto mode proceeds and records it instead of asking - `references/auto-mode.md`).
- **(d) Park, don't push.** An approaching cap near a natural gate means **park cleanly, not push
  on**: advance the state file, keep the index current, write the outstanding list, and end the
  turn saying plainly "NOT closed - resuming tomorrow at <next gate>". The resume machinery makes
  tomorrow's pickup cheap; a hard org-side stop mid-review does not.
