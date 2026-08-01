# Resume-or-new menu and the active engagement (read when `list --menu` shows open packs)

> Loaded just-in-time by `engage` step 0b. Skip it entirely when `open` is empty: there is
> nothing to resume, so classify the request as new work.

## The question (one call, question tool)

`<python> -m scripts.engagement_state list --menu` returns the ready-made option set as JSON.
Use it; never re-derive the menu in prose. Ask ONE question:

- **Resume** one of `shown` - one option per pack, showing slug + status + title so a scope
  mismatch is visible to the user.
- **Start new**.
- `more` > 0: say so in the question text ("+N more, ask me by slug").
- `archived` > 0: add one clause ("N archived engagements excluded - say unarchive to revive one").

**`default` is a hint for which option to pre-select, not an instruction to skip the question.**

## Scope-fit decides what you recommend

- The incoming request matches an open engagement's title/scope → default to resuming it.
- A different deliverable or a different scope → default to **start new**.

An open pack is never a reason to fold unrelated work into it. The same rule holds
MID-engagement: before every `add-artifact`, the artifact must belong to the ACTIVE engagement's
brief, and work outside that brief gets its own `init` (new slug) even in the same session.

## One ACTIVE engagement per session

The active slug is recorded ON DISK in `artifacts/.active-engagement.json`: written by `init`,
switched with `set-active <slug>`, cleared at close. `list` marks it, so offer it as the default
resume target rather than guessing. Name the active slug in your banner line and target its
workspace in every state command (`--slug <slug>`).

## A resumed workspace's state file is the record

Re-read `phase`, `decisions` (go-ahead, fix-cycle, data-attestation), `execution_consent_outcome`
and `runtime` from that workspace's `engagement-state.json`. Answers recorded there are **not**
re-asked: a recorded consent `declined` stands until the HUMAN says otherwise, and the persisted
`runtime` (mode, plugin root, interpreter) replaces a fresh run-mode guess after a compaction.

A ⛔ sibling engagement never blocks the active one: its stop-gate stays silent while parked
(ADR-008).
