# Reference: running unattended (`--auto`)

> Loaded just-in-time: read this **only** when the opening command carries `--auto`. Every
> other engagement pays nothing for it - the flag is off by default and rare, so its detail
> has no business sitting in `SKILL.md` where every open would carry it.

The human authorised this run on the launcher's pre-flight screen and **will not be asked
anything else**. Ask no questions at all - not the opening batch, not a clarification, not
"shall I continue?".

## The gates are already answered

- **Execution consent** is whatever the marker says. Unchanged from any other run: you
  still never create it, and its absence means static review only, findings 🧠 inferred.
- **Data attestation** was given or withheld at the pre-flight screen. Withheld means
  synthetic data only.
- **Deliver-back** to the ticket is approved by the pick, exactly as in an attended
  `--jira` run.

## The assumption ledger - not optional

Every question you WOULD have asked becomes a recorded decision **the moment you make it**:

```
engagement_state set-decision assumed-<n> "<question> -> <what you assumed> because <why>"
```

They appear together in an **Assumptions made in auto mode** section of the delivery
report, and as ONE consolidated ticket comment at close. This is what makes an unattended
run reviewable rather than merely fast: the questions do not disappear, they become the
output a human checks. An auto run that answered its own questions and recorded none of
them has hidden its judgement calls - and `check_artifacts` fails it (`AUTO-LEDGER-MISSING`).

## Park, never guess

If the request is ambiguous in a way that changes **what gets built** (not merely its
detail), or data or access you need is missing, or a gate you were not authorised for is
required, or you stop making progress:

`set-status blocked`, record why, post one comment to the ticket naming exactly what you
need, and stop. A parked engagement resumes normally.

**Guessing the deliverable is the one failure this mode must never produce.** An agent that
quietly invents requirements is worse than one that stops.

## Always closes PARTIAL

Auto mode reaches every Definition-of-Done line **except human sign-off**, and must never
record itself as signed off. Close as PARTIAL with "human sign-off" outstanding, and say so
in the first line of the closing comment (`AUTO-NOT-PARTIAL` enforces it).

Everything else - safety gates, guards, data handling, the disclaimers, the DoD - applies
exactly as in an attended run. **Unattended changes who is asked, never what is required.**
