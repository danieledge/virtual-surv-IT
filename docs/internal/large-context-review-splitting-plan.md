# Component-wise review splitting - design record (2026-08-04)

> Status: **implemented (documentation + preference plumbing).** The behaviour itself lives in
> `docs/team-operating-guide.md`'s orchestration-discipline section - Morgan follows it as
> orchestration guidance, there is no new mechanical enforcement, by design (see design point 4).
> This doc is kept as the design record: the reasoning, the options considered, and the open
> tuning question left for real-world calibration.
>
> **Update 2026-08-05:** a live corp report found the original design's single-write consolidation
> step can itself hit the same proxy timeout once a merge is large enough - design point 4 below
> now has a dated update covering the fix (chunked consolidation, above roughly 8 findings).
>
> **Update 2026-08-10 - point 4's "calls never write at all" premise is superseded.** That
> premise was to avoid multiple component-scoped calls racing on ONE shared pack path; it
> predates the Workflow tool by four days and was never revisited when Workflow shipped. A live
> session showed the actual cost of "return findings as text": Morgan had to reconstruct 71
> findings from prose buried in a large `journal.jsonl`, one `Grep` call per finding, slower
> than the review itself. Live-verified the same day that `guard-findings-pack-write.py`'s
> `agent_type` scoping fires identically for Task- and Workflow-dispatched calls, so the
> original race concern can be solved more simply: each component call writes its OWN
> distinctly-named pack (`findings-<slug>-<component>.jsonl`) - never the shared canonical name
> - so no two calls ever target the same path and nothing needs to return text instead of
> writing. Current behaviour lives in `docs/team-operating-guide.md`'s orchestration-discipline
> section and `.claude/skills/.shared/workflow-dispatch.md`; point 4 below is kept for the
> now-superseded reasoning, not as the current design.

## The problem(s) - two, not one

1. **Corp-proxy timeouts.** A corporate proxy sitting between Claude Code and Anthropic times out
   on large-context requests. Observed most often on `code-reviewer`, since it's the reviewer most
   likely to be handed a whole-repo diff. Manual workaround already in use: telling Morgan about
   the issue and having her split the review component-wise fixes it.
2. **Splitting is also just better review practice, independent of the proxy.** (User's own
   observation, 2026-08-04.) A reviewer scoped to one component produces sharper findings than one
   context-switching across frontend/backend/infra in a single pass.

## What's already true (researched, not assumed)

- All four findings-pack reviewers (`code-reviewer`, `compliance-reviewer`, `performance-reviewer`,
  `model-validator`) run `git diff` (or a named target) **once**, whole-diff, single call. No
  existing chunking, retry, or timeout handling anywhere in the agent-invocation flow.
- `code-reviewer.md` already groups changed files by language internally, for LENS selection - a
  content-dimension split within one call, not a size-based split across multiple calls.
- The operating guide's right-sizing rule (`docs/team-operating-guide.md:511-529`) is explicit:
  *"Multi-agent costs ~15× the tokens - use the leanest set that fits."* This governs agent
  *count*; nothing before this change governed a single call's context *size*.
- Every prior corp-environment fix in this repo (Windows interpreter probing, cp1252-safe output,
  quote-nested bash) was a **silent auto-detect-and-fix**, never a user-facing flag. The two
  existing `team-preferences.json` fields (`extra_formats`, `regulatory_citations`) are pure
  output-format choices, not reliability workarounds - `large_context_review_split` (added by this
  change) is the first of the latter kind, worth naming as a precedent shift.
- The four reviewers' Write access is mechanically scoped to one findings-pack path per role per
  engagement (`guard-findings-pack-write.py`). The design below never needs to widen that.

## Design (as implemented)

**1. Trigger - proactive primary, reactive safety net.**
Before delegating a review, Morgan checks `git diff --stat`. Splits by component when the diff
both spans more than one top-level component/directory **and** exceeds the size heuristic (see
"Tuning" below); a flat layout with no real component boundary just doesn't split. If a review
call fails or times out regardless (the proxy case, or a heuristic miss), that's the reactive
safety net: retry only the failed unit, never the whole review (see point 4). Also trigger
immediately, for the rest of the session, if the user explicitly names the proxy/timeout issue.

**2. Splitting - by component, capped by size.**
Group changed files by top-level directory/module (preserves review coherence - a component's
changes stay together, matching how the workaround was originally described: "split
component-wise", not "split by raw line count"). One reviewer call per resulting group, scoped
only to that group's files.

**3. Cross-cutting findings - resolved as an orchestrator-level pass, not an extra agent call.**
A strictly siloed per-component pass can miss issues that span components (a backend API change
with no matching frontend update). Decision: Morgan does this herself over the combined output
(she already has full visibility - the diff stat and every component's returned findings) rather
than spawning a dedicated integration-review agent. Zero extra agent-call cost; relies on Morgan's
own judgement rather than a mechanical check, which is an accepted tradeoff given the
alternative's cost.

**4. Merging findings - resolves the sequential-write/parallel-speed tension AND the mid-write
corruption risk at once.** (Revised 2026-08-05 - the single-write assumption below held for
corruption risk but not for timeout risk; see the update at the end of this section.)
Original draft of this design had each component call read-merge-write the same findings-pack
path sequentially - which is both a bottleneck (no real parallelism) and exactly the shape that
can leave a corrupted file if one write is interrupted mid-way, breaking every later component's
read. Superseded: **component-scoped reviewer calls never write at all** - they return their
findings as text output, same as every other advisory-style agent call in this system. Morgan
collects all of them, then, for a small merged set, ONE final `code-reviewer` call (cheap - no
diff re-reading, just consolidating already-computed findings) does the single Write. This is no
riskier than what already happens today (one `code-reviewer` call already does one Write) -
splitting the *analysis* across multiple calls doesn't multiply the *write* risk, because there's
still exactly one write. No guard change needed; no atomic-write primitive needed beyond what
already exists, because the failure mode that motivated this design (a mid-write timeout
corrupting a file a later step depends on) no longer has multiple sequential writes to corrupt.

**Update, 2026-08-05 (live corp report): the single write itself can be the timeout, once the
merge is big enough.** A 13-finding merge (CRIT/WARN/BACK/CROSS across four components) hit
`API Error: The operation timed out` on the SAME single-Write attempt twice in a row - the fix
above solved corruption risk but implicitly assumed the merged pack's OUTPUT size was always
small ("cheap... consolidating already-computed findings"), which holds for a handful of findings
but not for a genuinely large merge. Retrying the identical giant write is not a retry that can
succeed - it hits the same proxy limit every time, and the engagement makes zero progress while
burning turns. Fix (now in `docs/team-operating-guide.md`'s orchestration-discipline bullet):
above roughly 8 findings to merge, Morgan does the consolidation write **herself** instead of
delegating to a final `code-reviewer` call, and builds the pack incrementally - one small `Write`
(first batch + all required top-level fields), then several `Edit` calls appending the rest in
bounded batches. This is available to her specifically because `guard-findings-pack-write.py`'s
Write-scoping only fires for the four named reviewer agents' own calls (`agent_type` present),
never for the orchestrator's own tool calls - no guard change needed here either. The tradeoff
this reopens: incremental building reintroduces a *mid-sequence-interruption* risk (a
partial-but-schema-valid pack that silently under-reports if the sequence never finishes) that
the all-in-one-write design had specifically eliminated - mitigated, not eliminated, by tracking
the batches as an explicit task list and checking the written `findings` array length against the
count Morgan stated she intended to write before calling the consolidation done. Below the
threshold, the original single-write design is unchanged and still preferred (fewer moving parts,
no reintroduced interruption risk).

**5. Failed component retry.** Since component calls only return text (no side effects until the
final write), a failed/timed-out component is simply re-run - nothing to roll back, no partial
state to reconcile. Never restart the whole review; that would discard already-completed
components' work for no reason.

**6. Persistence.** `team-preferences.json` gained `large_context_review_split` (bool, default
`false`) - `scripts/engage_probe.py` reads it and surfaces `LARGE_CONTEXT_REVIEW_SPLIT=on|off` in
the step-0 probe output, documented in `.claude/skills/.shared/engage-open.md` and
`.claude/skills/preferences/SKILL.md` (now a third preference alongside docx/citations, same
question-tool flow, same no-consent-gate write path). Morgan offers to set it - never silently -
once she's hit the issue in a project.

**7. Where it lives.** `docs/team-operating-guide.md`'s orchestration-discipline section, as a new
bullet next to the existing right-sizing rule (this is a refinement of right-sizing, not a
separate concern). Applies to any of the four reviewers, not just `code-reviewer` - the root cause
(large context, proxy or genuinely multi-component) applies equally to all of them.

## Tuning - the one open question left

**Size threshold** for the proactive trigger: shipped as "roughly >15 files or >400 changed
lines" - a starting heuristic, not empirically derived (no real corp-proxy environment available
to calibrate against). Revisit once there's evidence: if the threshold trips too early (splitting
adds overhead for diffs that would have been fine in one call) or too late (still timing out
before the heuristic fires), adjust the numbers in `docs/team-operating-guide.md` directly - no
code depends on this exact figure, so it's a documentation-only tuning pass.

## Why this is orchestration guidance, not a mechanical control

Unlike the guard-enforced pieces of this system (raw-data blocking, execution consent,
findings-pack write scoping), this behaviour is entirely a prompt-level instruction Morgan
follows - there is no hook or code path that enforces "split when the diff is large." That's a
deliberate choice, not an oversight: right-sizing itself (the rule this extends) is already
judgement-based, not mechanically gated, and a diff-size heuristic firing a hard block would risk
false positives blocking legitimate single-call reviews. The cost is the usual one for
prompt-level guidance: it can be forgotten or misjudged in a given engagement. Consider a
mechanical nudge (comparable to `scripts/subagent_return_budget.py`'s advisory-only over-budget
notice) if this turns out to be forgotten often in practice - not built now, since there's no
evidence yet that prose guidance alone is insufficient.
