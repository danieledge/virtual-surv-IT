# Reference: acting on an `INTEGRATIONS=` banner line

> Loaded just-in-time: read this **only** when the step-0 probe printed an
> `INTEGRATIONS=` line. No line = everything off = this file is never read and no
> outward action of any kind is taken. Configuration itself lives in
> `docs/INTEGRATIONS.md` (the user-facing page); this file is the flow's operating
> rules.

## Ground rules (all modes)

- **Preview-then-approve, always.** Every outward action is named in advance and taken
  only after the human approves it: issue creation is named in the plan the go-ahead
  gate approves; close actions are offered after the summary email exactly like
  ADR-009 close actions. Never fire an outward call the user has not seen coming.
- **The harness prompts on every MCP call on top of that.** Expect it; never work
  around it.
- **Degrade gracefully, out loud.** Configured tools missing from `/mcp`, or a call
  failing, never blocks the engagement: note it in one line, record it as an
  outstanding item, and carry on. Tracker availability is never load-bearing.
- **Record what you created.** The moment an issue exists:
  `engagement_state set-decision jira-issue "<KEY>"` - a resumed or compacted session
  re-reads the key from state and never raises a duplicate.
- **Never put secrets, real data or the consent marker's path into any outward text.**
  Issue bodies and comments carry the same synthetic/masked-only discipline as every
  artifact (CLAUDE.md §5), and outward text is written for the client's tracker
  audience: 🤖 AI-identity marking applies exactly as in artifacts.

## Jira: `jira:on(<mirror>,key=<KEY>,tools=<prefix>)`

**At open** - after the go-ahead gate approves a plan that names it: create one issue in
`<KEY>` via the `<prefix>` tools (summary = engagement title; description = the brief's
summary section plus a link line naming the workspace `artifacts/<slug>/`). Record the
key (rule above). `key=UNSET` means the config is missing `project_key`: say so at the
gate and skip issue creation rather than guessing a project.

**During delivery** - `close-only` (the default): nothing outward until close.
`live`: ask ONCE at the go-ahead gate ("mirror phase changes to <KEY> as we go?"); on
yes, post a short comment at each phase change and gate outcome as it happens. On no,
behave as close-only; never re-ask mid-flight.

**At close** - offer, in the standard close-action step after the summary email: post
the summary-email text as a comment, and transition the issue to the project's
done-state (name the transition; if the tools expose none, comment only). A ⛔ parked
or PARTIAL close posts the honest status instead; never transition to done on a
partial.

## PR comments: `pr-comments:on(EXPERIMENTAL,...)`

Only ever active behind its double gate (config + `CST_ENABLE_PR_COMMENTS=1`). At
REVIEW close only: offer posting the findings-pack summary (per finding: severity,
title, location, one-line fix direction - never the full pack) as comments on the PR
the user names, via the configured tools. Preview the exact comment text before
posting. No mid-review posting in this experimental stage; if the offer is declined,
note it and move on. `pr-comments:locked(...)` in the banner: mention the lock once at
the gate if a PR was part of the request, otherwise stay silent about it.
