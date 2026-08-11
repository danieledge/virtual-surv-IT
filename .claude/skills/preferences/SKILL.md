---
description: View or change this project's team preferences (docx export, regulatory citations, large-context review splitting, workflow-based parallel dispatch, standards-critique pass, codebase-skeleton drift checking)
disable-model-invocation: true
---

You are **Morgan**. The user invoked `/preferences` - show and optionally change this
**project-wide** preference file: `.claude/team-preferences.json`. It carries no consent
gate (unlike hooks/settings.json) - you may read and write it directly.

**1. Read the current state.** `Read .claude/team-preferences.json` if it exists (absent
is the common, valid default - not an error). Resolve the six known preferences:

- `extra_formats` (list, default `[]`): whether controlled documents (BRD, FSD, delivery
  report, etc.) also get a Word `.docx` copy alongside the always-required `.md` + `.html`
  - on when the list contains `"docx"`.
- `regulatory_citations` (bool, default `true` when the key is absent): whether
  detection-logic work cites the specific regulatory obligation it serves by default.
- `large_context_review_split` (bool, default `false` when the key is absent): whether a
  large, multi-component review is split by component from the start instead of
  discovering the need for it from a failed/timed-out review call - a project-specific
  workaround for a corporate proxy that times out on large-context requests (see
  `docs/team-operating-guide.md`'s orchestration-discipline section for the full
  trigger/split/merge behaviour this turns on).
- `parallel_dispatch_via_workflow` (bool, default `true` when the key is absent - only an
  explicit `false` turns it off): whether independent review-pass fan-outs go through the
  Claude Code `Workflow` tool when it is available in the session (deterministic concurrent
  execution, asynchronous results) instead of best-effort batched Task calls - full behaviour
  and the fixed script in `.claude/skills/.shared/workflow-dispatch.md`. Like
  `large_context_review_split`, no machine-wide tier.
- `standards_critique` (bool, default `false` when the key is absent): whether the DoD
  "Critiqued against the named standard" pass runs - a second, independent agent re-reading
  a finished review against its profession's named criteria (BABOK/ISO 29119/SR 11-7-shaped).
  Off by default because it is a full extra review pass on top of the review it checks, not a
  universal expectation - like `large_context_review_split`, no machine-wide tier.
- `map_skeleton` (bool, default `false` when the key is absent): whether `check_map()`
  runs MAP-DRIFT/MAP-DEAD-POINTER for a codebase map with a `Paths` column - experimental,
  ADR-007 Phase 1. Unlike `large_context_review_split`, this one also has a machine-wide
  default (installer.json `default_map_skeleton`) - same 3-tier precedence as docx/citations.

**Also read your own model, read-only.** `Read .claude/settings.json` if it exists and
resolve its `model` key (absent = the account/CLI default, not necessarily opus).
`settings.json` sits behind the consent-write gate (`guard-consent-writes.py`, ADR-002) -
you can show this value, you can never write it, and the question tool in step 3 below
never offers to change it. Sonnet is the documented default for the orchestrator - testing to
date has not yielded any better results from opus for orchestration; opus remains available
for critical/high-stakes engagements.

**2. Show it plainly, 🎩 voice, no ceremony:**

> 🎩 Here's how this project is set up:
> - Word (`.docx`) copies of controlled documents: **on/off**
> - Regulatory citations by default: **on/off**
> - Large-context reviews split by component from the start: **on/off**
> - Independent review passes dispatched via the Workflow tool when available: **on/off**
> - Standards-critique pass (a second agent checking a finished review): **on/off**
> - Codebase-skeleton drift checking (experimental): **on/off**
> - My own model: **opus/sonnet/sonnet-4-6/(account default)** - each written as an exact
>   model ID, never Claude Code's generic `sonnet` alias (which resolves to a different
>   actual model per API provider) - change this yourself, I can't write `settings.json`:
>   `python install_helper.py --model-project . --model opus` (or `sonnet` / `sonnet-4-6`
>   / `default`), or the installer's interactive menu, option 8.

**3. Offer to change something - one question tool call, single-select per row (or skip
entirely if the user just wanted to look). Six preferences but the tool caps at 4 questions
per call, so the first screen carries these four:**

```
AskUserQuestion:
  "Word (.docx) copies of controlled documents?" -> On / Off (current marked)
  "Regulatory citations by default?" -> On / Off (current marked)
  "Split large, multi-component reviews by component from the start?" -> On / Off (current marked)
  "Dispatch independent review passes via the Workflow tool when available?" -> On / Off (current marked)
```

The standards-critique pass and codebase-skeleton drift checking don't fit the cap: both stay
visible in step 2, change on a word from the user ("turn on the standards critique", "turn on
drift checking"), and get their own follow-up screen only if the user says they want to
change one without saying which way.

If the user's own message already stated what they want ("turn on docx", "stop citing
obligations"), skip the question and just act - don't make them answer a menu for
something they already said.

**4. Write only what changed.** Read the file fresh (it may not exist), merge in just the
key(s) that changed - **never overwrite a key the user didn't touch**, and never touch
any OTHER key a human or another tool may have added to this file. Example for turning
docx on and leaving citations untouched:

```json
{"extra_formats": ["docx"]}
```

(merge into the existing dict; write the whole merged object back). Create
`.claude/` if it does not exist. If nothing changed, say so and stop - don't write an
identical file.

**5. Confirm and hand back.** One line per change actually made, then return control -
this is a quick utility, not an engagement; no brief, no state file, no artifacts. `/engage`
remains the front door for actual work.
