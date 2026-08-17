# Backlog: map-first review scoping + batched review-target question

Status: PROPOSED - investigation only, nothing implemented (user instruction 2026-08-17:
"don't change anything, propose approach"). Source: live corp-box run on engagement
bx-dp-new (IMG_0738) - three dispatched reviewers each explored the repo with their own
file discovery even though `docs/codebase-map.md` existed (map-skeleton=on), and the
review target took an extra conversational turn to pin down.

## Item 1 - reviewers should start from the codebase map, not a fresh find

### Observed

Each review agent (code-reviewer, performance-reviewer) begins by building its own
picture of the repo: Glob/Grep sweeps, directory listings, file reads. On a large
codebase that is the most expensive part of the pass, it is duplicated per agent, and
it reproduces information the PM-curated map already holds (module inventory, roles,
entry points - ADR-003/ADR-007).

### Why it happens

The map is read by Morgan at engagement open, but the reviewer BRIEFS do not carry it,
and the reviewer agent prompts say nothing about consulting it. Agents cannot see the
orchestrator's context, so anything not in the brief gets re-derived.

### Proposed approach (in preference order, combinable)

1. **Diff-scoped reviews need no discovery at all.** Quick/Deep on changed code already
   takes its file list from `git diff`; state this as a hard rule in the reviewer
   agents' prompts too ("your file list is in the brief - do not enumerate the repo").
2. **Map POINTER in the brief - point, never paste** (user question 2026-08-17: "does
   Morgan pass the code map or just point to it? we don't want an expensive turn").
   The economics decide this: Morgan emitting the map body into N briefs spends
   orchestrator OUTPUT tokens (the expensive kind, ~5x input price) N times over. The
   brief carries only (a) the map's path with "read `docs/codebase-map.md` first - it
   is your inventory, do not enumerate the repo", and (b) the in-scope file list
   itself, a few lines. An agent-side Read of the map costs cheap input tokens once
   per agent that actually needs it - and a diff-scoped review needs no map read at
   all, the brief's file list is already the whole scope.
3. **Staleness guard, bounded.** The map is advisory and can drift. Cheap check before
   trusting it for scope: compare the map's recorded update date against
   `git log -1 --format=%ci` (or newest mtime under the target dirs). If drifted,
   refresh ONLY the target directories (`git ls-files <dir>` - respects .gitignore,
   far cheaper than find) rather than a whole-repo walk.
4. **No-map fallback stays as today**, but prefer `git ls-files` over find/Glob sweeps
   for the initial inventory in a git repo.
5. **Where to encode it:** the reviewer agent prompts + `docs/review/agent-router.md`
   (briefing rules) + `deep-review` SKILL step that composes the briefs. Optionally a
   pin test asserting the agent prompts contain the no-self-enumeration rule, in the
   spirit of the consolidation-rule tests.

### Expected effect

Removes the per-agent discovery walk (turns + tokens + latency) on mapped projects;
on the observed 3-agent pipeline that is three repo walks replaced by one map slice.

## Item 2 - ask the review target in the same question screen, not a later turn

### Observed

User requests a code review; the target/location lands in a separate follow-up turn.

### Constraints

- AskUserQuestion is capped at 4 questions per call.
- The locked review menu is exactly 4 questions (Depth/Performance/Fix-cycle/Origin),
  mechanically enforced by locked_menu_guard - no fifth slot there.

### Proposed approach

1. **Derive before asking (default).** Same philosophy as the derived fine scope: if
   the working tree/branch has a diff, that is the target; if the prompt names a path
   or repo, that is the target. Only ambiguity earns a question. In the common case
   this is ZERO extra turns - stated in the brief at the go-ahead gate, adjustable
   there.
2. **When a question is genuinely needed, ride the intake batch.** If the opening
   prompt already says "code review", the step 0a Work-type question is redundant -
   its slot can become "Review target" (options: uncommitted changes / branch vs main
   / I'll name a path (Other) / whole codebase). Keeps the batch at 4, saves the turn.
3. Never a solo target question turn when either of the above can answer it.

### Touch points if approved

`engage` SKILL step 0a (conditional slot swap), `deep-review` step 2 (target
derivation rule already half-exists for Quick - generalise), review-menu.md preamble
(state the derived target in the price line message), locked_menu_guard unchanged
(intake batch is not the locked menu).

## Item 3 - merge the data-consent question into the same ask session (review + opinion)

User request 2026-08-17: "the data consent could be merged into the same ask session -
review and opine".

### Current design

It already is batched - on current dev the Data-safety attestation rides the step 0a
intake batch (Work type / Execution / Data safety / Engagements, ONE AskUserQuestion
call). A session showing it as its own turn is either running a pre-batch build (the
corp box was one pull behind on 2026-08-17) or drifting from the skill; the drift case
is worth a screenshot and a guard, not a redesign.

### Opinion on merging it FURTHER (into the review menu call)

Recommend against:

- **Ordering.** The attestation must be answered before any project data is read -
  that is intake, before the work is even classified. The review menu (step 1b) runs
  later; by then data may already be in scope. Moving the question later weakens the
  gate it exists to be.
- **No slot.** The review menu is locked at the 4-question cap; review-menu.md
  explicitly bans carrying Execution/Data safety into that call because they are
  already answered by then.

### What IS worth doing here

If Item 2's slot swap goes ahead (Work type replaced by Review target when the prompt
names a review), the intake batch remains ONE call of 4 with data consent inside it -
so the user-visible flow for "review this code" becomes: one intake screen, one review
menu screen, gate. Verify on the corp box after it pulls dev that intake really is a
single batched screen; if not, capture and treat as skill drift.
