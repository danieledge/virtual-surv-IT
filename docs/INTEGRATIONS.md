# Integrations - Jira and pull-request presence

**The one place this is configured.** Everything on this page is **off by default**: a
project with no `integrations` block behaves exactly as before this feature existed, and
a malformed or partially-typed block resolves to *off*, never to a guess. An integration
only ever activates on an explicit, well-formed opt-in in the working project's own
config. Many corporate environments have a Jira or GitHub MCP server wired up for other
work; the team never starts driving one just because it exists.

## Where and how to enable

Add an `integrations` block to the **working project's** `.claude/team-preferences.json`
(the same file `virt-surv configure` manages; project-scoped on purpose - which tracker,
which project key and which MCP tools are facts about the project, never about your
machine, so there is no machine-default tier):

```json
{
  "integrations": {
    "jira": {
      "enabled": true,
      "tool_prefix": "mcp__atlassian",
      "project_key": "SURV",
      "mirror": "close-only"
    },
    "pr_comments": {
      "enabled": false,
      "tool_prefix": "mcp__github"
    }
  }
}
```

| Field | Meaning | Default |
|---|---|---|
| `jira.enabled` | Master switch for the Jira flow. | `false` |
| `jira.tool_prefix` | The MCP tool-name prefix of **your** Jira server as it appears in this Claude Code environment (check `/mcp`). The team calls whatever issue-create/comment/transition tools it finds under that prefix and degrades gracefully when none are available. | `"mcp__atlassian"` |
| `jira.project_key` | The Jira project new engagement issues are raised in. | unset (surfaced as `UNSET` so it is never silently missing) |
| `jira.mirror` | `"close-only"`: outward actions happen only at engagement close. `"live"`: phase transitions are mirrored as they happen, **only after the human approves that explicitly at the go-ahead gate** (see the approval model below). | `"close-only"` |
| `pr_comments.enabled` | Experimental (see below). | `false` |
| `pr_comments.tool_prefix` | MCP prefix of your GitHub/GitLab server. | `"mcp__github"` |

At engagement open, the step-0 probe surfaces the resolved state as one `INTEGRATIONS=`
line in the banner; **no line means everything is off**. The engage flow reads
`.claude/skills/engage/references/integrations.md` (its operating instructions) only when
that line is present, so a project without integrations pays zero context for them.

## What the Jira flow does when enabled

- **At open (after the go-ahead gate approves the plan, which names the action):** one
  issue is created in `project_key` for the engagement (summary = engagement title, body
  = the brief's summary), and the key is recorded on disk
  (`engagement_state set-decision jira-issue "<KEY>"`) so a resumed session reuses it
  instead of raising a duplicate.
- **During delivery (`"mirror": "live"` only):** phase changes and gate outcomes are
  posted as comments / transitions as they happen. This is the one sanctioned exception
  to the extensions contract's close-only rule, and it exists behind its own explicit
  config value plus the gate approval.
- **At close:** the issue gets the closing summary (the engagement-summary email text) as
  a comment and a transition to your done-state, offered in the same
  preview-then-approve step as every other close action.

Every outward call is an MCP tool call, so the harness's own permission prompt applies on
top of all of the above; nothing is sent anywhere silently. If the configured tools are
absent or a call fails, the engagement **continues and says so** (the failure lands in
the delivery report as an outstanding item); tracker availability is never load-bearing
for the work itself.

## Pull-request comments - experimental, double-gated

Posting review findings onto a pull request needs careful validation in a real corporate
environment, and a working, validated Jira setup is the prerequisite testbed for the same
outward-action machinery. Until then it is double-gated:

1. `"pr_comments": {"enabled": true}` in the project config, **and**
2. `CST_ENABLE_PR_COMMENTS=1` in the launch environment (same human-only environment
   channel as the other `CST_*` switches).

Configured-but-locked is surfaced in the banner
(`pr-comments:locked(set CST_ENABLE_PR_COMMENTS=1 ...)`) rather than silently off, so
the gate is discoverable. When both gates are open, review engagements offer (never
auto-run) posting the findings-pack summary as PR comments at review close, through the
configured MCP tools, with the same preview-then-approve step as close actions.

## What this is not

- **Not a safety waiver.** The extensions contract's rules stand: integrations never
  waive a gate, guard, disclaimer or the DoD; `"live"` mirroring is the single
  documented, individually-approved exception to close-only timing.
- **Not credential handling.** The team never sees or stores tracker credentials; your
  MCP server owns authentication (the secrets standard in the repo root `CLAUDE.md`
  applies as always).
- **Not a replacement for `docs/team-extensions.md`.** Free-form standing instructions,
  company analysers and bespoke close actions still live in the ADR-009 extensions
  contract; this page covers only the first-class, mechanically-validated tracker/PR
  config.
