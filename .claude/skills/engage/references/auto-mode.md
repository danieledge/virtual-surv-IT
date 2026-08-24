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
  **Static-only is a degraded run, not a blocked one** - carry on and say so. Park (below)
  only if executing is the deliverable rather than an aid to it: "run the suite and report
  the failures" cannot be answered statically, so park and say what is needed; a code
  review can, so review it and mark the dynamic findings inferred.
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

## Spend: the ladder is already answered

`budget-status` runs at every gate exactly as in an attended run. What differs is what you do
with `HEADROOM=approaching` or `exceeded`: **do not offer the degrade ladder** - that is a
question, and this run has nobody to ask (and `--permission-mode dontAsk` denies the question
tool outright). The human chose a rung at the pre-flight screen; it is on the state as
`auto_on_budget`:

- **`park`** (the default) - park cleanly at the next gate, per the section below. The
  engagement resumes normally, which is why it is the default: a parked run is recoverable,
  a truncated one is not.
- **`light`** - drop to the light profile for what remains and say so in the report.
- **`continue`** - carry on and record the overrun as an outstanding item. Never silently.

Record which rung you applied as an assumption-ledger entry, with the figures. The ceiling is
**advisory pacing, not a hard stop** - the org-side spend limit is the only real one, and
attribution is project-wide, so treat the number as a signal to reach a gate, not a fence.

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

## Close the execution gate you were given

If this run was granted execution consent at the pre-flight screen, **delete the consent
marker as part of the close**. Deleting it is always permitted - closing a gate needs no
consent, only opening one does. The launcher expires it at the next `virt-surv go`, but
that may be hours away, and until then the grant is open to **every** session in this
project rather than just this engagement (2026-08-21 audit). Leave a gate open no longer
than the work needed it.

Everything else - safety gates, guards, data handling, the disclaimers, the DoD - applies
exactly as in an attended run. **Unattended changes who is asked, never what is required.**
