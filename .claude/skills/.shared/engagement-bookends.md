# Shared: the standard open and close (Definition of Done)

> Shared by any skill directly invocable outside `/engage` (review/audit skills and
> `/remediate` alike - anything with its own slash command in the routing table needs the same
> bookends). Repo path:
> `.claude/skills/.shared/engagement-bookends.md`; installed plugin:
> `$PLUGIN_ROOT/.claude/skills/.shared/engagement-bookends.md`. `<python>` and plugin-mode paths:
> `.claude/skills/.shared/run-mode.md`. Full detail: `docs/team-operating-guide.md`.

Both bookends apply **even when the skill was invoked directly**, not via `/engage`.

## Standard open (the opening bookend, before delivering the work)

Unless you arrived via `/engage` (which already wrote it), write a **proportionate Engagement
Brief** (`docs/templates/engagement-brief.md`) as `.md` + `.html` in the engagement workspace:
the target, the scope and decisions taken, assumptions, and the plan. **Right-size it** (a few
lines for a small piece of work, not a full programme). The brief is the opening artifact of
**every** engagement and the bookend to the summary email below.

With the brief, **open the machine-readable engagement state**: `<python> -m
scripts.engagement_state init` (ADR-006), which renders the START-HERE living index at status ⏳.
Record each artifact with `add-artifact` as it lands, and **write the brief and its index row
together in the same turn, before ending the turn; never leave the index trailing** (it is the
external memory that survives compaction).

Lifecycle discipline: a pause on unanswered user input is ⛔ BLOCKED said out loud ("this
engagement is NOT closed - outstanding: ..."), interim output takes pass-scoped names
(`review-pass-N`, `interim-*`), and `delivery-report.md` + the summary email are written at ✅
close only.

## Standard close

Write the **engagement-summary email** (`docs/templates/engagement-summary-email.md`) as a `.txt`
in the workspace, **signed off as Morgan**, then run the mechanical gate: `<python> -m
scripts.check_artifacts --fix` (the `--fix` mode auto-renders missing `.html` siblings and renames
a mis-typed summary email to `.txt`). Act on anything it still flags (a missing `.html` sibling, a
missing email) before handing back.
