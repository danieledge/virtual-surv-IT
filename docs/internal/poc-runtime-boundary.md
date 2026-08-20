# POC: owning the model-runtime boundary (removing the hard dependency on Claude CLI)

**Branch:** `poc/runtime-boundary` · **Date:** 2026-08-20 · **Status:** boundary proved,
migration NOT recommended yet · Investigation only - `dev` is untouched.

> Scope discipline: this answers "can virt-surv own the boundary?", not "should we migrate
> now?" and not "which framework wins?". Nothing here optimises or rewrites the existing
> architecture, and no number below is estimated - where something could not be verified in
> this environment, it says so.

## 1. What the Claude CLI currently provides

Mapped from the repo, sorted into the four categories the brief asks for.

| Capability | Category | Notes |
|---|---|---|
| Model invocation | **2 - replaceable** | The only genuinely provider-shaped thing. |
| Agent/subagent dispatch (`Task`, Workflow) | **2 - replaceable** | Concurrency and fan-out are orchestration, not provider features. |
| Session/context management, compaction | **1 - must survive** | Behaviour, not mechanism; today it is the CLI's. |
| Skill loading (`SKILL.md`, references) | **1 - must survive** | Plain file reads - trivially ours already. |
| Tool execution | **3 - stays ours** | Today the CLI executes; the POC moves the decision AND the call to our side. |
| Hooks / permissions / consent gates | **3 - stays ours** | The guards are PreToolUse hooks in the CLI's lifecycle - the single biggest migration risk (§8). |
| MCP integrations | **2 - replaceable, with work** | Jira/PR flows would need an MCP client or direct SDK calls. |
| Streaming | **4 - droppable in POC** | Not implemented here; contract has room for it. |
| Retries / timeouts | **2 - replaceable** | POC does timeouts; retry/backoff not implemented. |
| Resume / state | **1 + 3** | Already ours: `engagement-state.json` is the record, not the CLI's session. |
| Prompt caching | **2 - provider-dependent** | Not reproducible outside the CLI without provider support; see §9. |
| Token/cost visibility | **1 - must survive** | Already partly ours (Track D attribution). Contract exposes `Usage`. |
| Error handling | **2 - replaceable** | POC collapses every provider failure to one exception type. |

The load-bearing observation: **most of what makes this project what it is - engagement
state, the DoD gate, findings packs, evidence, the probe/launcher, the deterministic
scripts, the codebase map - has no dependency on the CLI at all.** The dependency is
concentrated in model invocation, tool execution and the hook lifecycle.

## 2. The proposed boundary

```
virt-surv workflow            (skills, DoD, evidence, state)   ← ours
        ↓
context / tools / policy      (poc/runtime/policy.py, loop.py) ← ours
        ↓
model runtime adapter         (poc/runtime/adapters/*)         ← thin
        ↓
provider / SDK / CLI                                            ← interchangeable
```

The design decision that matters is an inversion: **the agent loop is ours.** An adapter
answers one question - "given this conversation and these tool declarations, what next?" -
and returns. It never executes a tool, never decides whether a tool is allowed, never
writes state, never loops. `poc/runtime/contract.py` deliberately offers no `run_agent()`;
an adapter that grew one would be taking the loop back.

## 3. Framework comparison

Assessed against the brief's criteria; **none was adopted** for the POC.

| Option | Provider independence | Non-OpenAI-compatible internal SDK | Keeps our safety model | Dependency footprint | Verdict |
|---|---|---|---|---|---|
| **Thin custom runtime** (chosen) | Total - the interface is ours | Adapter is ~60 lines | Yes, by construction | stdlib only | **Recommended for the boundary** |
| Direct provider SDK, no framework | High | Yes | Yes | 1 dep | Fine as an *adapter*, not as the boundary |
| LiteLLM | High (proxy layer) | Only if it speaks that SDK - unverified | Yes | Medium | Candidate later for multi-provider routing |
| PydanticAI | Medium | Unverified | Mostly - it wants the loop | Medium | Re-evaluate if structured output becomes central |
| LangGraph | Medium | Unverified | It owns orchestration, which is our differentiator | Large | Not recommended |
| OpenAI Agents SDK | Low (assumes OpenAI shape) | Explicitly counter-indicated | It owns the loop | Medium | Rejected for this org's constraints |

Rationale: every framework's value is the agent loop, and the agent loop is the one thing
we must keep, because that is where the safety decisions live. Adopting one would trade our
strongest asset for convenience we do not need. A framework may still earn a place *below*
the adapter later (e.g. LiteLLM for routing) without touching workflow code.

**Could not verify:** the behaviour of any organisation-internal SDK - none is reachable
from this environment. §4 states the contract it would have to meet.

## 4. Organisation-specific SDK implications

An internal, non-OpenAI-compatible Anthropic SDK slots in as a third adapter with no
workflow change, provided it can: accept a message list with roles, accept tool
declarations (name/description/JSON-schema), return either text or structured tool-call
requests, and surface token counts. If it cannot return structured tool calls, the
`poc/runtime/adapters/claude_cli.py` fallback shape applies - ask for a strict JSON envelope and parse it -
which works but is weaker (§7).

## 5. POC architecture (what was built)

- `poc/runtime/contract.py` - `Message`, `ToolSpec`, `ToolCall`, `Reply`, `Usage`,
  `RuntimeUnavailable`, and the `ModelRuntime` protocol (one method: `complete`).
- `poc/runtime/policy.py` - the safety boundary. Default-deny allow-list, `data/raw/`
  refusal, workspace-escape refusal, refusals recorded as evidence.
- `poc/runtime/loop.py` - the virt-surv-owned agent loop: policy check → execute →
  feed result back → repeat, with a hard `max_turns` and cumulative usage.
- `poc/runtime/adapters/fake.py` - scripted adapter; carries the test suite.
- `poc/runtime/adapters/claude_cli.py` - reference adapter over `claude -p`.
- `poc/workflow_review.py` - one representative workflow (discover context → list files →
  read a file → verdict), written once, provider-agnostic.
- `tests/test_poc_runtime.py` - 16 tests, no credentials, no network.

## 6. What was demonstrated

1. **Current CLI path still works** - `dev` is untouched; the CLI adapter is implemented
   and importable. **Caveat:** a live end-to-end CLI run could not be completed *in this
   environment* - `claude -p` exits 1 because an `ANTHROPIC_API_KEY` conflicts with the
   claude.ai login here. That is an environment condition, not an adapter defect, and it
   is unverified whether the adapter's envelope parsing works against a real reply.
2. **New non-CLI path works** - the same workflow runs end to end against `FakeRuntime`:
   3 turns, 2 tool calls, a final verdict, usage accounted.
3. **Both consume the same workflow definition** - `poc/workflow_review.py` is unchanged
   between paths, and a test asserts it imports no provider module.
4. **Provider code is isolated** - only `adapters/` names a provider.
5. **Tool execution stays ours** - tested: an undeclared tool and a `data/raw/` argument
   are refused before any handler is touched, and the refusal is fed back to the model
   rather than raised.
6. **Usage is recorded** - input/cached/output tokens, model calls, tool calls, latency,
   accumulated across turns; `None` is preserved where a provider says nothing rather than
   invented.
7. **A failed provider call does not corrupt state** - tested, and demonstrated for real by
   the CLI auth failure above: it surfaced as `RuntimeUnavailable` and wrote nothing.
8. **An internal SDK could slot in** - §4; not proved, since no such SDK is reachable.

Two real bugs were found by running it rather than reading it: `claude -p` blocks ~3s on
inherited stdin (now `DEVNULL`), and an explicitly-empty executable was falling back to a
PATH lookup, so "there is no CLI" silently became "use the installed one".

## 7. What remains unresolved

- **The hook lifecycle.** The three guard hooks are PreToolUse hooks *in the CLI's*
  lifecycle. `poc/runtime/policy.py` shows the decision point survives, but a real migration must
  re-implement the guards as runtime policy **and** keep them enforcing for any CLI use -
  two enforcement paths, one truth. This is the hardest part and is not solved here.
- **Subagent dispatch.** The POC is single-agent. Fan-out, per-agent tool grants and the
  findings-pack write scoping are unmodelled.
- **Prompt caching.** Not reproducible here; savings unknown and unestimated.
- **MCP.** Jira/PR integrations assume MCP tools the CLI provides.
- **Streaming, retries/backoff, structured output** - deliberately dropped from POC scope.
- **Skills and AskUserQuestion.** Human-in-the-loop gating has no equivalent in the POC.

## 8. Migration risks

1. **Two enforcement paths** for the guards during any transition - the highest risk, and
   a security-relevant one.
2. **Loop parity.** The CLI's agentic behaviour (compaction, retries, tool orchestration)
   is mature; ours is 120 lines. Re-implementing it is where quality quietly regresses.
3. **Text-envelope fragility** if the chosen SDK lacks structured tool calls (§4).
4. **Windows/corporate.** The POC preserves the principle (context resolved before the
   model runs) but a Python runtime brings its own interpreter/TLS/proxy exposure on
   locked-down boxes - the exact class of problem that cost this project weeks.
5. **Effort vs benefit.** Nothing here is blocked *by* the CLI today.

## 9. Token/cost implications

The contract exposes `Usage` per turn, aggregated per run, including
`cached_input_tokens` separately so cache-hit ratio - not raw volume - can be tracked. That
is the shape CI budgets would consume, and it composes with the existing
`tests/test_prompt_budget.py` and the Track D per-run attribution on `dev`.

**No savings are claimed.** Whether a direct SDK is cheaper than the CLI depends on prompt
caching behaviour that could not be measured here. Anyone quoting a number for this
migration should be asked where they measured it.

## 10. Recommendation

**Adopt the boundary as a design principle now; do not migrate yet.**

The POC succeeds on its own success criterion: virt-surv owns the workflow, tools, safety
model, state and evidence, and the provider is an interchangeable implementation detail -
demonstrated by a real workflow running unchanged against a non-Claude, non-CLI, offline
runtime.

But "we *can*" is not "we *should*". The CLI is not currently blocking anything, the guard
lifecycle is unsolved, and the token case is unmeasured. Concretely:

1. Keep `poc/` as the reference boundary; do not wire it into `dev`.
2. When an approved internal SDK becomes available, write that adapter and re-run this
   POC's tests against it - that is the cheapest possible real answer.
3. Only then decide, with the guard-lifecycle design in hand and measured token numbers.
