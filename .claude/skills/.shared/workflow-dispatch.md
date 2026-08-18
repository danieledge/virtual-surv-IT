# Shared: parallel dispatch via the Workflow tool

> Shared by the review skills and the operating guide's dispatch rule (this folder is not a
> skill of its own). Repo path: `.claude/skills/.shared/workflow-dispatch.md`; installed
> plugin: `$PLUGIN_ROOT/.claude/skills/.shared/workflow-dispatch.md`.

## Why this exists

Three prompt-only fixes for concurrent Task dispatch (0.33.47, 0.33.48, 0.33.49) all failed
live: the rule, the literal procedure and the worked example each still produced one Task call
per turn, once while narrating "dispatching both now, concurrently" in the same breath. That is
a documented model tendency, not a wording problem. Claude Code's **Workflow** tool removes the
judgement call entirely: its `parallel()` construct is a deterministic script primitive, so the
passes genuinely run concurrently. Trade-off (accepted): Workflow is **always asynchronous** -
the call returns a task id immediately and the result arrives later as a background task
notification. There is no synchronous mode.

## When to use it

Use this path when **both** hold:

1. `PARALLEL_DISPATCH_VIA_WORKFLOW=on` (the step-0 probe line; on by default - only an explicit
   `parallel_dispatch_via_workflow: false` in `team-preferences.json` turns it off).
2. The **Workflow tool is available in this session**: it appears in the session's own tool
   listing - either a tool defined in context or a name in a system-reminder listing deferred
   tools. If `Workflow` is not named anywhere in your context, it is not callable this session -
   do not attempt the call and do not probe for it; use the fallback.

Being listed does not guarantee the call succeeds: dynamic workflows can be disabled per
session (managed settings, org policy, the "Dynamic workflows" setting in `/config`), the
session can be restricted to named workflows only, or the user can decline the approval prompt.
**Any Workflow failure is a fallback trigger for the rest of this engagement** - say so in one
line and use the fallback; never retry-loop the tool.

**Fallback** (preference off, tool absent, or a failed call): the operating guide's literal
one-message multi-Task procedure ("Dispatch independent calls concurrently", §Orchestration
discipline). Keep following it exactly - it is best-effort, but it is the only lever left.

## The fixed script - use verbatim, never improvise

Morgan passes this script **exactly as written** (a per-engagement rewrite is where a syntax
error gets in). Everything engagement-specific travels in `args`.

```js
export const meta = {
  name: "team-parallel-dispatch",
  description: "Dispatch independent team subagent passes concurrently; each returns its final text"
};

const specs = typeof args === "string" ? JSON.parse(args) : args;
if (!Array.isArray(specs) || specs.length === 0) {
  throw new Error("args must be a non-empty array of {label, prompt, agentType?} specs");
}
log("Dispatching " + specs.length + " independent passes concurrently");
const results = await parallel(specs.map((spec) => () => {
  const opts = { label: spec.label, phase: "Independent passes" };
  if (spec.agentType) opts.agentType = spec.agentType;
  return agent(spec.prompt, opts);
}));
return specs.map((spec, i) => ({ label: spec.label, result: results[i] }));
```

Call shape:

```
Workflow
  script: <the template above, verbatim>
  args: [ {"label": "...", "prompt": "...", "agentType": "..."}, ... ]
```

- Pass `args` as a **real JSON array in the tool call, never a hand-stringified one**
  (an explicitly stringified list is a call-site mistake, still worth avoiding). **Live-tested
  2026-08-08: it arrived inside the script as a JSON-encoded string even when passed as a
  real array in the tool call** - contradicting the Workflow tool's own documented contract,
  reproduced twice, not a one-off. The script above defends against both shapes
  (`typeof args === "string" ? JSON.parse(args) : args`) rather than trusting the documented
  behaviour - this is the fix, verified live: the undefended version threw on every call in
  this environment; the defended version dispatched and returned correctly
  (`[{"label":"smoke-a","result":"alpha"},{"label":"smoke-b","result":"bravo"}]`, 2 agents,
  0 errors, 3.6s).
- One spec per independent pass. `label`: short display label ("code-reviewer: frontend").
  `prompt`: the same full brief you would put in that pass's Task call today - a workflow
  subagent inherits none of the conversation, so the brief is its only channel in.
  `agentType` (optional): the same agent type name you would give the Task tool in this
  session (e.g. `code-reviewer`, `performance-reviewer`); omit it for a general-purpose pass.
- `agent()` without a `schema` option returns the subagent's **final text as a string** - for a
  general-purpose pass, that text IS the result. **For a findings-producing pass (`code-reviewer`,
  `performance-reviewer`, `compliance-reviewer`, `model-validator`), the prompt must instead
  instruct it to `Write` its own findings pack directly** to its own component-qualified path,
  never the shared canonical name, and return only a short confirmation (finding counts + the
  path it wrote) as its text result - same convention, same rationale and live verification as
  the operating guide's own copy (§Orchestration discipline, "Split a large, multi-component
  review"); this file doesn't repeat it. Morgan still does the final cross-component merge into
  the canonical `findings-<slug>.jsonl` herself.
- A `null` slot in the returned array means that pass was skipped by the user or died on a
  terminal API error. Re-run **just that pass** via the fallback Task path; keep the others.

Contract notes (verified against Claude Code 2.1.226, 2026-08-08; the `args` line below is
verified by a real live invocation, everything else by schema extraction - if the tool
rejects the script on a future version, treat it as a fallback trigger and report the error,
do not patch the script live):

- The `export const meta = {...}` literal must be the **first statement** and pure (no computed
  values). `name` and `description` are required.
- `parallel()` takes an **array of functions**, not promises - hence `() => agent(...)`.
- Scripts must be deterministic plain JavaScript: no `Date.now()`/`Math.random()`/`new Date()`,
  no `import()`, no TypeScript syntax.
- The tool result returns immediately with `status: "async_launched"`, a `taskId`, a `runId`
  and a persisted `scriptPath`; the completion arrives later as a task notification. If a
  completed run's result looks empty, `journal.jsonl` in the run's transcript directory records
  each agent's actual return value. **Read it directly - it's already text, no `python -c` (or
  any inline execution) needed to parse or count it, and the code-execution gate blocks that
  unconditionally regardless of size** (live-tested 2026-08-10: reaching for `python -c
  "import json; ..."` on this exact file cost a full blocked-then-retry cycle before falling
  back to reading it plainly, which is what `check_artifacts`/the findings-count-verification
  guidance already expect). Same applies to any other JSON/text output this step reads
  (`*.meta.json`, findings packs) - `cat`/`Read` first, always.
- `args` arrives as a JSON-encoded string, not the array passed in - see the dispatch bullet
  above for the evidence; the script's normalisation line is the fix, do not remove it.

## The two-turn flow - what Morgan says and does

**At dispatch:** state it plainly, one or two lines, 🎩 voice: the N independent passes are
running **in the background via the Workflow tool** (guaranteed concurrent execution), and the
results will follow in a later turn once it completes. The user may first see a "Review dynamic
workflow before running" approval - that decision is theirs; a decline means the fallback, not
persuasion. While the workflow runs: do only work that does not depend on its results, or hand
the turn back. **Never narrate, predict or summarise results that have not arrived** - the
completion notification is never something you write yourself, and an artifact may not claim
these passes are done until they are (no unevidenced in-progress claims).

**When the notification arrives:** read the per-label results, then consolidate and continue
exactly where batched Task returns would have resumed the pipeline - the scorer pass over the
packs, the merged-pack write, the challenge pass. Nothing downstream changes; only the dispatch
mechanism did.

**For findings-producing passes (the normal case), this is now cheap by construction:** each
pass wrote its own pack directly (see the `agentType`/prompt bullet above) and returned only a
short confirmation, so "read the per-label results" means reading N small confirmation strings
plus N small pack files - never the full `journal.jsonl`. The technique notes below are the
**fallback**, for a general-purpose (non-findings) pass whose real result IS its returned text,
or for the rare case a findings-producing pass didn't follow the write-directly instruction and
its findings ended up in `journal.jsonl` as prose after all.

**Fallback - reading `journal.jsonl` cheaply, if you ever do need it (live-tested 2026-08-10:
a 3-pass run that returned text instead of writing produced a ~32k-token file - too large to
`Read` whole without burning a large chunk of context on it).** Each pass's own `label` (the
string you set in `args` at dispatch, e.g. `"code-reviewer: frontend"`) is the one anchor you
already know going in, regardless of the journal's exact JSON shape - `Grep` for it first to
find which line(s) belong to that pass, then read only that range, not the whole file. Repeat
per label rather than loading everything at once - `Read`/`Grep` only, same as above, never
`python -c`.

**Fallback - if you still end up extracting individual findings from returned text, do it in
ONE pass, never one `Grep` call per finding.** The live case that motivated writing packs
directly in the first place: 71 findings total (34 backend + 27 frontend + 10 performance)
across three text-returning passes, pulled out **one at a time** - a separate `grep -o` per
finding ID (`BE-006`, then `BE-009`, then `BE-012`...), several individually hitting a 1-minute
timeout, and each call paying its own PreToolUse hook-dispatch overhead on top. At that rate,
extracting the results took longer than the 11.8 minutes the three passes spent producing them
- the mechanical step outweighing the actual analysis is the tell that the technique, not the
data, is the problem (this is exactly the failure mode writing packs directly avoids - prefer
that over getting good at this fallback). If you are in this fallback anyway: one `Grep` with a
**general pattern that matches every finding marker at once** (e.g. every `**[XX-###]`
occurrence, not one literal ID per call), so the IDs and their positions come back in a single
pass; batch-read the content from there rather than re-querying per ID.
