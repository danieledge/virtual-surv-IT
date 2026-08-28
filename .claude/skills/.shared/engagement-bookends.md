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

**Single-deliverable close (2026-08-18, any workflow):** when ONE artifact already
carries the engagement's substance - a diagnosis report, a review report, an assessment -
that artifact IS the delivery. Append a short closing block to it (final status/verdict,
the team with 🤖 markers, next steps) instead of authoring a separate delivery report,
and never invent wrapper documents or executive summaries to satisfy the packaging
default (live 2026-08-18: a /why-no-alert close demanded an "engagement report" over a
diagnosis that already covered everything, then offered an exec summary when challenged).
The summary email stays - it is the short requester-facing bookend, not a duplicate of
the deliverable. The full consolidated Delivery Report is for engagements whose substance
spans MULTIPLE artifacts. **Naming is deterministic (2026-08-18):** the single
deliverable keeps its work-product name (`DIAGNOSIS-*`, `REVIEW-*`, `ASSESSMENT-*`)
and is designated the delivery at close - `delivery-report.md` is RESERVED for the
multi-artifact consolidation, and `check_artifacts` treats that name as close-only,
so a mid-engagement file named like one trips the gate. Two runs of the same
workflow must not choose different shapes.

**Author closing artifacts final-form, then gate ONCE, then close.** Write the summary email and
delivery report complete on the first pass - final `Status:` lines (never a draft/interim word),
every roster name carrying its 🤖 marker on first mention, no placeholder sections - **before**
running the gate. `set-status closed` refuses on more than a plain `check_artifacts` run reports
(unfinalised artifacts, draft statuses, missing agent markers), so a clean gate is not proof close
will succeed. Topping up the artifacts a little at a time between gate runs turns the gate into a
one-item-at-a-time discovery loop instead of a single check - each partial re-run only surfaces
what's new since the last edit. Write complete, run the gate once, fix everything it lists in one
pass, close.

The close sequence, in order (use these exact forms rather than guessing a flag and correcting
after a usage error - **`set-status closing` is the FIRST command, not an implicit side effect**:
it enters the 🔒 closing window that makes the summary email and delivery report legitimate
work-in-progress rather than artifacts appearing with no state transition to explain them,
`docs/team-operating-guide.md`'s "Close ordering"):

```
<python> -m scripts.engagement_state set-status closing --slug <slug>
<python> -m scripts.engagement_state resolve-outstanding "<substring>" --slug <slug>
<python> -m scripts.engagement_state set-team "Name (role)" "Name2 (role2)" --slug <slug>
<python> -m scripts.engagement_state finalise-artifacts --slug <slug>
<python> -m scripts.engagement_state set-footprint --agents N --tokens "<estimate>" --slug <slug>
<python> -m scripts.check_artifacts --fix
<python> -m scripts.engagement_state set-status closed --slug <slug>
```

(the `--fix` mode auto-renders missing `.html` siblings and renames a mis-typed summary email to
`.txt`).

**Map currency (before `set-status closed`, 2026-08-17 build review):** a build is the one
activity guaranteed to outdate the codebase map, and direct-invoked skills never pass through
`/engage`'s close where the update used to live. When `VSIT/shared/map.md` exists AND this
engagement changed code: update the touched §2 rows (bounded - only areas this engagement
touched, never a full re-map), append the §3 history row, and re-fingerprint:

```
<python> -m scripts.repo_skeleton --fingerprint VSIT/shared/map.md --project-dir .
```

Skipping this hands the NEXT open a `MAP_DRIFT` flag against a map the team itself outdated -
and hands the next review a stale inventory. No map, or a no-code engagement: skip silently. **`check_artifacts` takes no `--slug`** - unlike the `engagement_state` commands around
it, it always scans the whole `VSIT/engagements/` root and discovers every engagement's own workspace
itself, same as the DoD backstop Stop hook does. Write the
**engagement-summary email**
(`docs/templates/engagement-summary-email.md`) as a `.txt` in the workspace, **signed off as
Morgan**, right after `set-status closing` (during the closing window it just opened, alongside
the delivery report) and before the rest of the sequence. Act on anything the gate still flags
before handing back.
