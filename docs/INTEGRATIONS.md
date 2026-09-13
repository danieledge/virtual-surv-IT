# Integrations - Jira and pull-request presence

**The one place this is configured.** Everything on this page is **off by default**: a
project with no `integrations` block behaves exactly as before this feature existed, and
a malformed or partially-typed block resolves to *off*, never to a guess. An integration
only ever activates on an explicit, well-formed opt-in in the working project's own
config. Many corporate environments have a Jira or GitHub MCP server wired up for other
work; the team never starts driving one just because it exists.

## Where and how to enable

Add an `integrations` block to the **working project's** `VSIT/config/preferences.json`
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
      "mirror": "close-only",
      "done_transition": "",
      "dry_run": false
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
| `jira.mirror` | `"close-only"`: outward actions happen only at engagement close. `"live"`: phase transitions are mirrored as they happen, **only after the human approves that explicitly at the go-ahead gate** (see the approval model below). Note this is *when* to post, never *whether* - for that, see `dry_run`. | `"close-only"` |
| `jira.done_transition` | The **exact** workflow state the close transition targets, e.g. `"Done"`. Unset means the team never transitions a ticket: it comments and attaches, and workflow state stays the human's. Set it and the close transitions to that state and no other. Before 2026-09-09 this doc promised a done-transition, the engage reference said transitions were human-only, nothing enforced either, and the target was guessed from whatever the board offered - a coin toss on any board with several done-ish states. | unset (no transition) |
| `jira.dry_run` | `true` prints every outward call the team would make, in full, and makes none of them. For a first run against a real ticket, and for checking what a configuration will actually do. | `false` |
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
- **During delivery (`"mirror": "live"`):** phase and status transitions are posted as
  short comments as they happen - a bounded 4-8 per engagement (phase moves, plus
  blocked / closing / closed), never one per state mutation. For a team-raised issue this
  is opt-in: an explicit config value plus approval at the go-ahead gate. **For an
  engagement started FROM a ticket (`--jira`) it is the default** (2026-08-20): the pick
  that started the work is the approval to keep that ticket informed, stated once in the
  opening banner, and overridable by setting `"mirror": "close-only"` explicitly. Each
  comment is one line and carries no artifact bodies, findings detail or data.
- **At close:** the issue gets the closing summary (the engagement-summary email text) as
  a comment, **plus the delivery report and key artifacts attached**, and, **only when
  `done_transition` names a state**, a transition to exactly that state - offered in the
  same preview-then-approve step as every other close action. With `done_transition` unset,
  which is the default, nothing is transitioned and the ticket's workflow state is left to
  you. Until 2026-08-21 a team-raised issue closed with the summary alone, so the same
  work reached a ticket in full or in outline depending only on how the engagement started.

**Every comment opens with a summary from Morgan** (2026-08-21): the people reading a
ticket were never in the session, so a bare status token tells them nothing. **And when an
attachment cannot be uploaded** - no such tool under the prefix, or the call fails - the
team posts a comment saying plainly that it could not attach them, naming what they are,
and giving the resolved absolute path of the engagement workspace where the results are
held. It does not paste the report body in unprompted: that is noise in a tracker and an
uncontrolled copy of the content, and a reader who wants it inline can ask.

Every outward call is an MCP tool call, so the harness's own permission prompt applies on
top of all of the above; nothing is sent anywhere silently. If the configured tools are
absent or a call fails, the engagement **continues and says so** (the failure lands in
the delivery report as an outstanding item); tracker availability is never load-bearing
for the work itself.

## Inbound: start an engagement FROM a Jira

**[j] is always on the `virt-surv go` menu** (2026-08-20), whether or not this project
has the Jira integration configured - it is only an affordance, and picking it merely
collects a ticket reference and pre-seeds the session prompt. The launcher never talks to
Jira. What `jira.enabled` gates is the **outward** half - creating the issue at open and
posting progress comments - because those touch someone else's tracker, and defaulting
them on would break this page's own "off by default" promise. On an unconfigured project
the menu says plainly that the session can only fetch the ticket if access exists.

Because of that split, the setting is labelled **`jira write-back`** in `virt-surv
configure`, not "jira integration": *off* does not mean Jira is unavailable, it means the
team never writes to a tracker on its own initiative. Starting an engagement from a
ticket, and delivering the result back to **that one ticket**, works either way - the
inbound flow reads its rules on the `--jira` flag itself, with or without an
`INTEGRATIONS=` line. Everything else outward needs this switch on.

With the Jira integration enabled, `virt-surv go` shows **[j] new engagement from a
Jira**: paste the issue URL (or a bare key) and the session launches with
`/engage --new --jira <ref>` pre-seeded. Morgan fetches the ticket via the configured
access, treats it as the engagement request, and **delivers the results back to the
ticket at close without asking again** - summary comment + verdict, with the report and
key artifacts attached where the configured tools allow attachment, or posted inline as
markdown comments when they don't. Picking the ticket IS the approval for that
deliver-back (asking at close would re-litigate the decision the pick already made);
anything outward beyond that one ticket stays behind the normal preview-then-approve
gates, and the harness's own MCP permission prompts still apply to every call. This is
the human-approval model by construction: anyone on the team can RAISE the ticket, but
an engagement only starts when someone with the CLI picks it up in the menu - the
launcher never talks to Jira itself, and no engagement starts without that pick - including
an unattended one (see below), which needs it plus a separate authorisation. Ticket content is treated as data, never as
instructions; the session's own safety gates (execution consent, data attestation) are
answered by the human at the keyboard, not by ticket fields.

## Unattended runs - decided per ticket

An engagement started from a ticket can be told to run **unattended**: it works the ticket
end to end without stopping to ask. The decision is **per Jira, never a project-wide mode**
(2026-08-21) - making "this project runs autonomously" a standing property was the wrong
shape for something that is a judgement about one piece of work.

Nothing becomes autonomous by accident. It takes three deliberate acts, every time:

1. toggle **unattended** on the ticket screen (`Ctrl-A`);
2. confirm on the **pre-flight screen**, which states what auto mode will and will not do
   and takes your data attestation;
3. tick **execution consent** separately there, if the run is to be allowed to run code.

Only then does the launcher pre-seed `--auto` alongside `--jira`, which is what tells the
session to proceed without questions. Every gate is answered **before the session starts**,
because a run that will not stop to ask cannot be asked anything later.

`autonomous jira mode` in `virt-surv configure` is a **kill switch, not an enabler**: leave
it alone and the option is offered, turn it off to remove unattended runs from the project
entirely. An unattended run always closes **PARTIAL** with human sign-off outstanding, and
records every judgement call it made as an assumption ledger for you to review.

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
- **Not a replacement for `VSIT/config/extensions.md`.** Free-form standing instructions,
  company analysers and bespoke close actions still live in the ADR-009 extensions
  contract; this page covers only the first-class, mechanically-validated tracker/PR
  config.

## Claude Code features this team is built on

> Moved out of README.md on 2026-09-14 (framework review, step 6.8).

The team is a native Claude Code plugin, not a wrapper - these are the platform features it
uses and how (audited 2026-07-29 against the current Claude Code docs):

| Feature | How the team uses it |
|---|---|
| **Skills / slash commands** | All 32 workflows ship as skills, costing ~nothing until you type `/engage` (mechanism: [Token usage](#-token-usage--optimisation)). `argument-hint` on every command. |
| **Subagents** | 13 agent definitions (`.claude/agents/`) with per-agent `model:` tiers (opus for highest-stakes judgement, sonnet for build/advisory, haiku for the scorer) and least-privilege `tools:` - advisory agents hold no Edit; four hold Write scoped to their own findings-pack file only, mechanically enforced by a hook. |
| **Hooks** | Four always-on `PreToolUse` safety guards (raw-data wall, execution-consent gate, consent-write gate, findings-pack write-scoping guard), plus five engagement-scoped lifecycle hooks that no-op in dormant sessions: a warn-first `Stop` DoD backstop (with a `todo_panel_nudge` sibling on the same `Stop` event), a `UserPromptSubmit` persona re-anchor that survives compaction (with an `engage_probe_prefetch` sibling on the same event), a `PreToolUse` document-input redirect (binary documents route to the vendored converter), a `SessionStart` compact/resume brief (ADR-011) and a `PostToolUse` post-edit lint (plus a `PostToolUse` subagent return-budget check on `Task`). Three further `PreToolUse` cost/UX redirects - `module_form_redirect`, `enumeration_redirect`, `exploration_redirect` - run engagement-scoped and fail open; detail in `docs/team-operating-guide.md`. A `locked_menu_guard` also runs `PreToolUse` on `AskUserQuestion`. Hook and settings edits are human-only (ADR-002); hook changes ship staged, are applied by the maintainer via the `apply-*.sh` scripts, and releases ship with everything already wired - end users apply nothing. |
| **Plugin distribution** | `.claude-plugin/plugin.json` manifest (agents + skills), marketplace/git install, per-project enablement; every bundled script also resolves by `$PLUGIN_ROOT` path so the team works identically installed into a foreign project. |
| **Permissions** | A curated `permissions.allow` block (fewer prompts on the team's own consent-free tooling) and `permissions.deny` as the hard floor under the raw-data wall. |
| **CLAUDE.md layering** | A lean always-on core (dormancy, data safety, the execution gate) with the operating detail split into docs the team loads only when engaged - the context-budget discipline. |
| **Agent SDK (headless)** | The eval harness (`scripts/eval_engage.py`) drives real headless `/engage` sessions in sandboxed repo copies - `can_use_tool` plays the consent gate, `setting_sources` loads the real project hooks - so the shipped safety net itself is what gets regression-tested. |

Deliberately **not** used, with reasons: output styles (session-start-scoped, would break
dormancy by construction - the per-turn anchor hook is the conditional equivalent); agent
teams (experimental; the team coordinates through artifacts, not peer chatter, by design);
checkpoints / rewind as a safety net (subagent edits are not restored - git is the backstop);
exposing the scripts as an MCP server (a non-Claude-Code client would bypass the guard
hooks entirely).

<sub>[↑ Back to top](#readme-top)</sub>

## Notes on the config

<details>
<summary>🔧 <b>Tool permissions · memory scope · model tiering</b></summary>

- Advisory agents are restricted to read-only tools (`Read, Grep, Glob`, sometimes `Bash`)
  so they physically cannot alter detection logic.
- Build agents have write access (`Read, Write, Edit, Bash, Grep, Glob`).
- Memory is **project-scoped, not plugin-scoped** (the plugin is installed across many projects, so
  it accrues no project memory): **project-specific** learnings (typologies, tuning decisions, FP
  drivers) go to the **working project's own memory** (its `CLAUDE.md`); only **general,
  cross-project** conventions live in the committed, plugin-shipped
  [`docs/house-rules.md`](docs/house-rules.md). Advisory agents recommend; the PM commits.
  (Claude Code subagents have no per-agent memory; a committed file is the real, auditable mechanism.)
- Models: **4 opus** (the final/unchecked judgement + novel-design roles) · **8 sonnet** ·
  **1 haiku**; the per-agent rationale and best-practice conformance live in
  [`docs/agent-design.md`](docs/agent-design.md). Change the `model:` field freely.

</details>

<sub>[↑ Back to top](#readme-top)</sub>
