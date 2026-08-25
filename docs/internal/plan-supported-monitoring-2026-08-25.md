# How unattended runs SHOULD be monitored

**Status:** finding + proposal, 2026-08-25. Nothing built.
**Trigger (owner):** "this feels unreliable - how do anthropic suggest headless agents are
monitored". Correct instinct. Checked the documentation rather than defended the design.

---

## 1. What we built, and why it is the weakest option

The workflow view parses `~/.claude/projects/<slug>/<session>.jsonl` - Claude Code's
**internal** transcript. Consequences, all of which have already bitten:

- it is not a public API and can change shape without notice;
- it records **no cost**, so we carry a rate table and multiply tokens ourselves;
- it has **no engagement boundary**, so scoping is by date and two engagements opened the
  same day cannot be told apart;
- a subagent's turns are absent, so a stage is an opaque total;
- it is written by another process, so every read races a writer.

Each was worked around. None had to be.

## 2. What Anthropic actually documents

### (a) OpenTelemetry - the monitoring answer

`CLAUDE_CODE_ENABLE_TELEMETRY=1` plus OTLP exporters. It emits exactly what this feature
hand-derives, and more:

| We derive | It publishes |
|---|---|
| cost from a rate table | **`claude_code.cost.usage`** in USD |
| tokens summed by hand | `claude_code.token.usage`, attribute `type` = input/output/cacheRead/cacheCreation |
| "is this a stage or the PM" | attribute **`query_source`** = `main` / `subagent` / `auxiliary` |
| stage identity from `agentType` | attribute **`agent.name`** |
| model per stage | attribute `model` |
| session correlation by newest-file | **`session.id`** on every metric and event |
| nothing comparable | **`prompt.id`** linking every API request and tool result from one prompt |

Events (`OTEL_LOGS_EXPORTER`) include `claude_code.api_request` carrying `cost_usd`,
`input_tokens`, `output_tokens`, `cache_read_tokens` and `model` per request, and
`claude_code.tool_result` with `duration_ms` and `success`.

There is also a **tracing beta** (`CLAUDE_CODE_ENHANCED_TELEMETRY_BETA=1`) whose span tree is
literally the picture this feature draws:

```
claude_code.interaction        (one per prompt)
├── claude_code.llm_request
├── claude_code.tool
│   └── claude_code.tool.execution
└── claude_code.hook
```

**Cost:** it needs somewhere to export to. That is trivial in an estate that already runs a
collector and a real obstacle in one that does not.

### (b) `claude -p --output-format stream-json` - the headless answer

For an **unattended** run this is decisive, because unattended work does not need a terminal
at all:

- newline-delimited JSON events, live, as the run happens;
- the first event, `system/init`, **reports the session id** - which is the correlation
  problem solved outright, no newest-file guessing, no date scoping;
- subagent messages carry **`parent_tool_use_id`**, so the stage tree can be rebuilt exactly,
  including nested subagents (`--forward-subagent-text` adds their text);
- `--output-format json` returns **`total_cost_usd` and a per-model breakdown** per
  invocation - Anthropic's own figure, not our multiplication;
- `system/api_retry` surfaces retries, which we cannot see at all today;
- exit code 0 / non-zero, and SIGTERM handling with `SessionEnd` hooks, so a supervisor can
  actually manage the run.

Both figures are documented as **client-side estimates**, so the honesty framing stays - but
it becomes *Anthropic's* estimate rather than one we compute from a rate table we maintain.

## 3. What this means for the three problems we hit

| Problem | Our fix | The supported fix |
|---|---|---|
| Rate table that disagreed with `dashboard.py` | one table, verified | none needed - cost is published |
| Which session belongs to this engagement | newest file, then date-scope | `system/init` returns the session id |
| Subagent internals invisible | treat a stage as an atom | `parent_tool_use_id` rebuilds the tree |

## 4. Proposal

**Unattended runs move to `claude -p --output-format stream-json`.** The launcher consumes
the stream directly: it becomes the live workflow view with no transcript parsing, no rate
table and no scoping heuristic, and the same change is the headless capability that was
always the next step. The session id it hands back gets recorded on the engagement pack,
which fixes correlation for everything else too.

**Attended runs keep the transcript reader**, clearly labelled as best-effort, because `-p`
is non-interactive by definition. Where an estate runs a collector, OTel is strictly better
and the view should read from it.

**Do not delete what exists.** `workflow_trace` remains the zero-infrastructure fallback for
a machine with no collector and an attended session - which is a real case, and the one most
corporate users start in.

## 5. Risks of the change

- `-p` is a different execution mode: permissions must be pre-granted (`--allowedTools`,
  `--permission-mode`), which suits an unattended run whose gates were answered at the
  pre-flight, and suits nothing else.
- `--bare` is recommended for scripted calls but skips hooks, skills, plugins and CLAUDE.md -
  which would disable this entire team. **Do not use `--bare` here.**
- Consuming a stream means owning a process, its lifetime and its failure modes. That is a
  real supervisor, not a screen refresh, and it should be built as one.
