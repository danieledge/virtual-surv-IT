# Token usage and optimisation

> Moved out of README.md on 2026-09-14 (framework review, step 6.8); the README keeps a one-line pointer. Relative links below are relative to the repository root.


Multi-agent setups cost tokens, so the team is built to be cost-conscious, the biggest lever being
**right-sizing** (engaging only the agents a task needs, never all 13).

In one line: one code review ~51k tokens (~$2, measured) · a lean engagement ~35-50k (estimate) · a full build-review-tuning delivery ~500k (~$4-8, measured); levers: right-sizing, model tiering (4 opus / 8 sonnet / 1 haiku), artifacts-as-blackboard, dormancy.

<details>
<summary>💰 <b>Measured per-run numbers + the optimisations in place</b></summary>

Rows marked **measured** come from a real run (the Agent tool reports actual usage; ~4 chars/token,
so ±15%); the rest are estimates with no run behind them yet:

| What | Tokens | ~API cost | When it's paid |
|---|---|---|---|
| One `code-reviewer` review (opus; **measured** in the build demo) | **~51k** | **~$2** | per review agent |
| A lean engagement (intake + scorer + reviewer + synthesis), *estimate* | ~35-50k | ~$0.50-1.00 | per engagement |
| A **full build → 3 reviews → tuning → performance** delivery (9 agent runs, **measured**) | **~500k** | **~$4-8** | the heavy end, a complete reviewed+calibrated deliverable |
| A full fan-out (right-sizing off), *estimate* | ~500k+ | ~$5-10 | rarely, reserved for broad work |

> 💵 **Cost basis (rough, ±2×; prices refreshed 2026-08-17).** At current list prices: **Opus 5
> $5/$25, Sonnet 5 $3/$15 (intro $2/$10 through 2026-08-31), Haiku 4.5 $1/$5** per million
> input/output tokens - the Opus:Sonnet ratio is now only **1.67×**, not the ~5× of the Opus 4.1
> era these notes were first written under, so the opus tier on the final-word reviewer roles is
> cheap insurance rather than a big lever. The reported token counts are *totals* (no
> input/output split), so these assume a ~50/50 mix; actual cost varies with the split, prices
> change, and prompt-caching can cut it substantially. Treat as order-of-magnitude, not a quote.
>
> ⏱️ **Caching decides the day's bill.** Cache reads are ~0.1× input price, but matching is
> byte-exact on the prefix and the TTL is **5 minutes on API keys and Bedrock/Vertex** versus
> **1 hour on subscription seats** - so a stop-start working pattern on the API/cloud path pays
> cache-cold re-reads repeatedly, and the same engagement can cost 2-3× more cold than warm.
> API-key users can set `ENABLE_PROMPT_CACHING_1H=1` (included in `install_helper.py
> --env-tuning`'s curated set). Bank-grade deployments note: Bedrock/Vertex with zero-data-
> retention keeps prompt caching but loses the Batch API's 50% discount, and Anthropic-side
> analytics don't cover cloud usage - per-user cost visibility there needs OTEL or a gateway.
>
> 🧾 **Perspective:** that full 9-run delivery (~$4-8 API) is the routine ~80% of a real
> engagement done in minutes, standing in for human effort measured in days, not dollars.
> *So people spend their day on the judgement that matters.* (The figure was measured on a
> real 9-agent run; the captured delivery it came from was a pre-0.16 artifact and is no
> longer published, so the number stands on this note rather than on a document you can
> open.)

**Optimisations in place** (these are the levers that matter, per Anthropic's cost guidance):
- **Right-sizing**: the headline lever: a narrow change fires 2-3 agents, not all 13; the PM states the
  agent count at the gate, so over-spawning is visible.
- **Model tiering**: opus (1.67× sonnet at current prices) reserved for final-judgement/novel-design roles only, haiku
  for the mechanical review bookkeeping (exact split and rationale: [Notes on the
  config](#-notes-on-the-config)).
- **Artifacts-as-blackboard**: agents return condensed results; big output goes to files, not back
  through the orchestrator's context.
- **Clean console**: detail to artifacts, not the chat.
- **True dormancy (0.8.x, from the 2026-07-01 setup audit)**: a session that never types
  `/engage` still pays a small, measured amount for the team, not zero - what actually loads is
  `CLAUDE.md` plus every skill's and agent's `description:` frontmatter field (that's what makes
  them typeable/routable at all); what does **not** load is any skill or agent **body** (the
  multi-KB workflow instructions and agent prompts stay unread until something actually invokes
  that skill or dispatches that agent):
  - `disable-model-invocation: true` on all 32 skills stops the model **auto-triggering** a skill
    on its own judgement - it does not remove the description from context; the description is
    exactly what needs to be resident for `/`-typing and routing to work at all;
  - measured 2026-09-12: the 27 skill descriptions sum to ~3.0k chars, the 13 agent descriptions
    to ~3.2k chars, and `CLAUDE.md` itself is ~12.3k chars - **~18.4k chars total, ≈4.6k tokens
    at a rough 4-chars/token estimate** (±15%, no run behind this figure) - this is the real
    per-session dormant floor, not "zero";
  - `CLAUDE.md` was slimmed once already (from ~185 lines / ~3.1k tokens to roughly 125 / ~2k,
    2026-07-01), with the roster, routing table and standing rules moved to
    [`docs/team-operating-guide.md`](docs/team-operating-guide.md), which `/engage` now
    **explicitly reads** (previously it was referenced but never wired in) - it has since grown
    back to ~176 lines / ~3.1k tokens as engagement dormancy/safety carve-outs were added;
  - the 13 agent descriptions are trimmed to crisp routing lines;
  - the plugin is no longer enabled at user scope, so other projects don't load the roster, and
    this repo no longer **double-loads** everything as plugin + project config at once.
  `CLAUDE.md` and every description load into *every* session and are inherited by *every*
  subagent, so the ~4.5k-token floor multiplies across a fan-out - it is a real, worthwhile
  reduction from an un-optimised setup, just not the "zero" the shorthand elsewhere implies.

</details>

<sub>[↑ Back to top](#readme-top)</sub>
