# Orchestration discipline (evidence-based - see `docs/internal/research-virtual-team.md`)

> Extracted from `docs/team-operating-guide.md` (2026-08-14, open-latency review) - this is
> dispatch/delegation-time guidance, not needed for the open itself, so it no longer costs every
> `/engage` its own read. Every existing `§Orchestration discipline` pointer elsewhere in this repo
> still resolves correctly: the heading stayed in place in `team-operating-guide.md`, it just
> redirects here now instead of containing the content directly. Read this file the first time you
> actually delegate/dispatch in an engagement, not before.

- **Right-size first.** Multi-agent costs ~15× the tokens - use the **leanest** set that fits (a
  narrow change → one builder + one reviewer, not the whole team). **State the intended agent
  count and why, out loud, before ANY delegation - not only at the intake gate.** The rule used
  to say "at the gate", which left a real hole: an engagement with no fan-out planning gate (a
  close-only pass, a reconciliation, a review that turns up one thing needing a specialist)
  reaches its first `Task` call having never stated a count, and a count recorded afterwards in
  the footprint is a receipt, not a decision. So: if you are about to engage anyone, say who and
  why in one line first, **even when the decision emerged mid-engagement**; and when the answer
  is nobody, say that too ("no fan-out, I'll handle this myself") - a stated zero is
  right-sizing, silence is not. (The current external figure is 3-10x versus a single agent
  on equivalent tasks - Anthropic, Jan 2026; the ~15x above is the older vs-chat number.
  Either way: order of magnitude, so the rule stands unchanged.)
  - **When the engagement has a recorded budget, the sizing line gets a money line beside
    it (2026-08-17, assessment rec 1).** Run `engagement_state budget-status` at every gate
    and before any fan-out, and state its DAILY/HEADROOM output in the same breath as the
    agent count. `HEADROOM=approaching` or `exceeded` is never proceeded past silently -
    offer the **degrade ladder** via the question tool and let the human pick: (1) drop to
    the light profile for what remains; (2) retier the sonnet-eligible reviewer roles for
    this engagement; (3) defer a non-blocking review stage to the next day; (4) **park
    cleanly now** (the pacing rule in the engage skill: state advanced, index current,
    outstanding list written, "NOT closed - resuming tomorrow" said plainly). The budget is
    advisory pacing - the org-side spend limit stays the hard stop; the point is to reach a
    day boundary at a gate, never mid-review.
  - **When the count is 2 or more with no dependency between them, name the dispatch mechanism
    in that SAME statement, not as a separate later decision.** Live evidence, not a guess: a
    2026-08-08 test where the right-sizing line said "Ravi and Layla run first and concurrently"
    without naming a mechanism dispatched them fully sequentially, one per turn, no `Workflow`
    call attempted at all - the exact failure this rule exists to prevent. The SAME day, a
    right-sizing line that explicitly said "...dispatched together via the Workflow tool (this
    session's default parallel-dispatch path)" as part of stating the plan actually did dispatch
    via Workflow, 8 agents, genuinely concurrent. The only difference between the two was
    whether the mechanism was named inside the commitment itself. So the right-sizing line for
    2+ independent agents is not "N specialists, dispatched concurrently" - it is "N specialists,
    dispatched via the Workflow tool" (default path) or "N specialists, dispatched as N Task
    calls in one message" (fallback path) - name the actual one you are about to use, in the
    same breath as the count, per the dispatch rule below.
  **"Handle this myself" is Morgan's own PM-level work** (a
  reconciliation, a summary, running a check script) - **never writing or editing the
  deliverable's own code**, even when nothing in the roster is a domain-specific fit (route
  generic code to `platform-engineer` + `code-reviewer` instead - see the routing table above).
  If "running a check script" means driving one of the seven configurable analysers yourself
  for a direct-answer quick look (CLAUDE.md §6's classify-and-answer path, `engage/SKILL.md`
  step 1) rather than delegating to `code-reviewer`, the same on/off/auto config and
  `CST_NO_EXTERNAL_TOOLS` kill switch bind you too - `.claude/agents/code-reviewer.md`'s tool
  table is the single source of truth for which seven, their flags, and the config mechanism;
  don't duplicate or improvise a different list.
  (Live 2026-08-01: a close-only engagement delegated to two
  specialists with no count stated anywhere, and the engagement that did MORE work was scored
  worse than four earlier solo runs that did less.) Reserve full fan-out for high-value, broad
  deliverables. Numeric
  heuristic: simple fact-finding → 1 agent, 3-10 tool calls; direct comparison → 2-4 agents,
  10-15 calls each; full delivery → the minimal sufficient chain.
- **Dispatch independent calls concurrently.** Right-sizing
  decides *who* to engage; this rule decides *how to issue the calls once that's decided* - and
  the right-sizing bullet above now requires naming that mechanism in the SAME statement as the
  count, not deferring to this bullet as a separate step. When
  two or more subagent calls have no dependency on each other - non-overlapping scope, neither
  consumes the other's output - they must overlap in time. There is **no token-cost trade-off**:
  each subagent reads the same brief and does the same work either way; the only difference is
  whether they overlap in time, so dispatching independent calls one per turn is pure wall-clock
  waste, never a safe default. Sequential dispatch is only for genuine dependency: a fix pass
  that consumes a prior review's findings, the cross-component consolidation after split passes
  return, QA after the build, `review-scorer`'s score-and-filter pass over packs that must exist
  first.
  - **Default path - the Workflow tool** (`parallel_dispatch_via_workflow`, probe line
    `PARALLEL_DISPATCH_VIA_WORKFLOW=on|off`, on by default, no machine-wide tier). When the
    preference is on AND the `Workflow` tool is available this session, dispatch the
    independent set through the **fixed script** in
    `.claude/skills/.shared/workflow-dispatch.md` - its `parallel()` is a deterministic script
    construct, so concurrency stops being a per-turn judgement call. Availability means
    `Workflow` appears in this session's own tool listing (defined in context, or named in a
    system-reminder listing deferred tools); not named anywhere = not callable = fallback,
    without attempting the call. The trade-off, accepted by design: Workflow is **always
    asynchronous** - dispatch returns immediately and results arrive later as a background
    task notification (the two-turn flow, narration rules and failure handling are in that
    shared file). Any Workflow failure - disabled for the session, named-workflows-only
    restriction, declined approval - means the fallback for the rest of the engagement, stated
    in one line, never a retry loop.
  - **Fallback path - one message, multiple Task calls** (preference off, tool absent, or a
    failed Workflow call): send the set as **multiple Task tool calls in ONE assistant
    message**, so the runtime executes them concurrently, following the literal procedure
    below.
  - **The fallback is best-effort, and that is a known model tendency, not just a wording gap**
    (Anthropic's own tool-use docs
    note Claude can under-use parallel tool calls even when nothing disables it) - confirmed
    live here three times: a stated rule ("dispatch independent calls concurrently"), then the
    literal procedure below, then a worked example were each live-tested on 2026-08-07/08
    (0.33.47/0.33.48/0.33.49) and every time the calls still went out one per turn, once even
    while narrating "dispatching both now, concurrently" in the same breath. Three different
    phrasings failing identically is exactly why the Workflow path above exists and is the
    default. A *description* of the
    rule is not enough - on the fallback path, follow the **procedure** below literally, not
    just its intent.
  - **The fallback procedure, not just the principle:**
    1. Before making ANY of the independent calls, enumerate the full list - every
       `code-reviewer`/`performance-reviewer`/etc. call this fan-out needs.
    2. Emit **all of them as Task tool-uses in this one response**, back to back - do not send
       the first, read its result, and only then decide on the second. If a plan calls for N
       independent passes, this turn contains N Task tool-uses, not one.
    3. The wrong pattern looks like: *call 1 -> wait for its result -> call 2 -> wait -> call
       3*. The right pattern looks like: *call 1, call 2, call 3, all in this response -> wait
       for all three results together*. If you notice you are about to make an independent
       call **after** already having a prior independent call's result in hand, that call
       should have gone out with the earlier one - it is too late for that pair, but batch
       whatever is left.
  - Example: a component-split review - 3 `code-reviewer` passes over non-overlapping file sets
    plus a `performance-reviewer` pass over the same target - is **one response, four Task
    tool-uses**. (Live failure, reproduced twice: 2026-08-07 and 2026-08-08, exactly that shape
    of fan-out went out as lone calls across separate turns both times, and the serialised
    waiting dominated each run's wall-clock time.)
- **Split a large, multi-component review instead of one whole-diff call.** A single review
  spanning multiple components (frontend + backend + infra in one pass) both loses focus and
  risks a request timeout on a corporate proxy between Claude Code and Anthropic (live report,
  2026-08-04). Before delegating a review, check `git diff --stat`: if the diff spans more than
  one top-level component/directory **and** is large (roughly >15 files or >400 changed lines -
  a starting heuristic, tune per engagement), split by component instead of one call across
  everything; a flat layout with no real component boundary just doesn't split. The
  component-scoped calls are exactly the independent, non-overlapping case the dispatch rule
  above describes - dispatch them per that rule (the Workflow path when on and available,
  otherwise one message, multiple Task calls - never one per turn). **Each component-scoped
  reviewer call writes its own findings pack directly**, to its own component-qualified path
  (`artifacts/<slug>/data/findings-<slug>-<component>.jsonl`, e.g. `findings-<slug>-backend.jsonl`
  - never the shared canonical name), and returns only a short confirmation (finding counts +
  its own pack path), not its findings as prose text. This used to be the other way round
  ("returns findings as text, never writes directly") specifically to stop multiple calls
  racing on ONE shared path - since each call now targets its OWN distinct, never-shared path,
  that race cannot happen regardless of how many run concurrently, and there is no longer a
  reason to route findings through prose text first. (Live-verified 2026-08-10: the
  `agent_type`-based write-scoping guard, `guard-findings-pack-write.py`, was confirmed to fire
  identically whether a pass is dispatched via `Task` or via `Workflow`'s `agent()` - so this
  applies to both dispatch paths, not just one.) Do a light cross-component consistency pass
  yourself over the combined findings once merged (an API change on one side with no matching
  update on the other is exactly what siloed review misses).
  **Consolidating and writing the MERGED pack can still be the large-output timeout point**
  (live report, 2026-08-05: a 13-finding merge timed out repeatedly on the same single-Write
  attempt, making zero progress on retry) - this is now purely an OUTPUT-size concern on
  Morgan's own merge write, separate from how the component packs were collected. **Roughly >8
  findings to merge across component-scoped calls** (starting heuristic, same tuning status as
  the split trigger above): read each component's own pack back first (already-valid JSONL, no
  reconstruction from prose needed - just `Read` each small file) and merge their `findings`
  arrays; do the consolidation write **yourself** (Morgan) into the canonical
  `findings-<slug>.jsonl`, not via a delegated final `code-reviewer` call - you carry no
  *scoping* restriction on the findings-pack path (that half of the guard only fires for the
  four named reviewer agents' own calls; it has no opinion on yours), so you can build the
  merged file incrementally instead of emitting everything in one generation: **Write** a valid
  pack containing the first batch plus every required top-level field, then **Edit** to append
  the remaining findings in bounded batches (roughly 4-6 at a time) until the full merged set is
  in. (A single scoped agent hitting the same >8 threshold on its own, un-merged pack has the
  identical Write-then-Edit option for its own path - the guard's size cap applies to Write only
  and exempts Edit for exactly this reason - so a component pass with an unusually large finding
  count for its own slice uses the same batching, independently, before Morgan ever reads it
  back. What only Morgan does is the *cross-component merge*: no single scoped agent can write
  into another's pack, or a combined one, since the guard ties each to its own `agent_type`.)
  Track this as an explicit multi-step task list so a mid-sequence interruption is visibly
  incomplete, not silently missing findings; before calling it done, state the finding count
  you intended to write and confirm the file's `findings` array
  actually holds that many - a partial-but-valid pack passes schema validation same as a complete
  one, so this count check is the only thing that would catch a dropped batch. **Do this check
  by reading the file** (`Read`, then count `"id":` occurrences in the `findings` array, or
  count the top-level array entries directly in the text you already have from the Write/Edit
  call) - **never** by running `python -c "...json.load..."` or any other inline execution to
  parse it: the file is already text you can read and count without executing anything, and
  the code-execution gate blocks inline `-c` unconditionally regardless of intent (live
  report, recurring - a session reached for exactly this as an ad hoc JSON-parsing check on a
  findings pack). Below the ~8-finding
  threshold, the original design still applies (one delegated `code-reviewer` call, one write). If
  a review call fails or times out regardless (proxy, or a heuristic miss), retry only the failed
  unit - never discard already-completed components' work by restarting the whole review. If this
  recurs in a project, offer (never silently) to persist it - `large_context_review_split: true`
  in `team-preferences.json`, surfaced by the probe as `LARGE_CONTEXT_REVIEW_SPLIT=on|off`, same
  no-consent-gate write path already used for the docx preference. Full design and open questions:
  `docs/internal/large-context-review-splitting-plan.md`.
- **Don't delegate:** iterative back-and-forth, phases sharing significant context, quick
  targeted changes, latency-sensitive steps - those stay in the main loop. **Do delegate:**
  verbose self-contained work, tool-restricted review, research that returns a summary.
- **Delegate with explicit, non-overlapping briefs** (weak delegation is the #1 failure): objective,
  scope boundaries (what *another* agent owns), inputs/artifacts to read, expected output format.
  **A subagent inherits none of the conversation** - its brief is the only channel in, so put every
  needed input in it; an underspecified brief is what makes two agents duplicate work or leave a gap.
- **Condensed returns (standing rule - a hard budget, not a nicety).** Every brief instructs the
  subagent to return a distilled summary within a **hard budget of ≤ ~1,500 tokens (~30 lines)**;
  the artifact carries the detail. Anthropic's sub-agent guidance puts a good distilled return at
  **1,000-2,000 tokens** - a subagent may explore over tens of thousands of tokens internally but
  must hand back only the distilled result. **A return over budget is a defect to trim, not
  something to pass through:** the subagent's final message lands verbatim in the orchestrator's
  context, so a verbose return balloons Morgan and pushes a long engagement toward premature
  compaction. The orchestrator's context is an attention budget (Anthropic's context-engineering
  guidance); state the budget in the brief, and if a return blows it, send it back to be distilled
  (or distil it before acting) rather than carrying the bloat. A PostToolUse hook on Task
  completion (`scripts/subagent_return_budget.py`, audit finding #4, 2026-07-30) now gives one-line
  feedback the moment a return is clearly (2x) over budget - advisory, never blocking, don't rely
  on it instead of briefing well in the first place.
- **Coordinate through artifacts, not chatter (the "blackboard")** - agents read/write the shared
  set (Delivery Report, RTM, specs); each step's output is the next step's input. **When a review
  sends work back to a build agent, log it**: `python -m scripts.engagement_state log-note
  --tag review-loop "code-reviewer -> rules-developer: 3 findings, resubmit"` - the local
  dashboard's per-engagement timeline (`/dashboard`, ADR-013) reads the `--tag` prefix to
  render a distinct icon for a handoff; a plain `log-note` (no `--tag`) works exactly as
  before and still lands on the timeline, just without the icon.
- **Challenge the agents - the PM is a sceptic, not a relay.** Don't pass findings through verbatim:
  **spot-check, don't re-score** (the scorer already applied the rubric - challenge every Critical,
  anything regulated, anything whose evidence basis looks thin, a sample of the rest, **and a sample
  of the _filtered_ set** - a real issue scored just under the threshold is a false negative, the
  costliest miss in a regulated review and the one mechanical scoring can silently make, so don't
  only audit what was reported), downgrade or drop what fails, **promote anything wrongly filtered**,
  and verify the evidence basis (📊 observed/measured vs 🧠 inferred - never let
  an inference reach the user as fact; "observed" for something seen directly in data, "measured" for
  a computed/executed number, **📄 "coded" for an explicit literal read from source with nothing run**
  (never let a read constant masquerade as 📊 measured) - see the legend in
  `docs/WAYS-OF-WORKING.md`). Prefer an adversarial second look over duplicated work.
- **Agents self-verify before returning** - plan, then check output against the brief; state any
  gap rather than hiding it (a flagged gap is cheap, a silent one is a defect). (Anthropic guidance;
  see `docs/agent-design.md`.)
- **The orchestrator defaults to sonnet** - testing to date has not yielded any better results
  from opus for orchestration, so sonnet is the default; opus remains available per-project for
  critical/high-stakes engagements (`install_helper.py`, menu option 8, or
  `--model-project . --model opus`).

## Exploration discipline (2026-08-18, evidence-based)

Every search round-trip is a full model turn re-reading the whole context; the measured
evidence (Agentless's $0.34/issue skeleton-walk localisation, RepoGraph's +32.8%
resolve-rate from a code graph, Anthropic's own "infinite exploration" warning) says
structure-first beats search-first at this repo scale. Five rules, for Morgan and every
dispatched agent alike:

1. **Orientation before any search**: the codebase map, the brief's file list, or ONE
   `repo_skeleton` call - never an opening grep on a concept word.
2. **Search budget**: after 2-3 misses, stop guessing synonyms - read the skeleton or
   the likeliest file whole instead. A miss spiral is the worst documented failure mode.
3. **Read small files whole** (one Read beats three greps plus their per-turn context
   tax); grep-plus-window only on genuinely large files.
4. **Batch independent lookups into one turn** - parallel calls, alternation patterns
   (`rg 'foo|bar'`) - never serial single greps.
5. **Grep is pinpoint symbol lookup, never exploration or coverage proof**: search for
   names the map or a read file already gave you; "who uses X" goes to the import graph.

Briefs remain the sharing mechanism: exploration results travel as file lists with
one-line roles, so downstream agents read named files instead of re-searching
(the map-first briefing rule, `docs/review/agent-router.md`).
